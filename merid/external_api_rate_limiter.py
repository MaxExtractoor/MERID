"""External API Rate Limiting — Centralized outbound request governance.

Implements token bucket rate limiting for all third-party API calls with:
- Provider-specific limits from config/rate_limits.yaml
- Automatic retry with exponential backoff on 429s
- Per-agent quota allocation
- Prometheus metrics integration
- Structured logging for observability

Usage:
    from merid.external_api_rate_limiter import RateLimitedClient, get_limiter

    # Rate-limited Messari call
    async with RateLimitedClient(
        base_url="https://data.messari.io",
        provider="messari",
        read_per_sec=0.27,  # 20/min with safety margin
    ) as client:
        data = await client.get("/api/v1/assets/bitcoin/metrics")
"""

from __future__ import annotations

import asyncio
import time
import random
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional
from contextlib import asynccontextmanager

import httpx
import yaml
from pathlib import Path

from utils.logger import get_logger

logger = get_logger("merid.external_api_rate_limiter")


# =============================================================================
# Token Bucket Implementation
# =============================================================================

@dataclass
class TokenBucketConfig:
    """Configuration for token bucket rate limiter."""
    read_per_sec: float
    write_per_sec: float
    burst_limit: Optional[float] = None
    safety_factor: float = 0.8  # Use 80% of documented limit for headroom
    
    def __post_init__(self):
        if self.burst_limit is None:
            self.burst_limit = max(self.read_per_sec, self.write_per_sec)
        # Apply safety factor
        self.read_per_sec *= self.safety_factor
        self.write_per_sec *= self.safety_factor
        self.burst_limit *= self.safety_factor


class TokenBucket:
    """Async token bucket for rate limiting outbound API calls.
    
    Separate read/write buckets allow different limits for queries vs mutations.
    
    NOTE: Lazily initializes asyncio.Lock to avoid event loop binding issues
    when the bucket is created in one loop but used in another.
    """
    
    def __init__(self, config: TokenBucketConfig, provider: str = "unknown"):
        self.config = config
        self.provider = provider
        self._read_tokens = config.burst_limit
        self._write_tokens = config.burst_limit
        self._last_refill = time.monotonic()
        # Lazy-init the lock to avoid event loop binding issues
        self._lock: Optional[asyncio.Lock] = None
        self._lock_init_lock = threading.Lock()
        
        # Metrics
        self._total_requests = 0
        self._throttled_requests = 0
        self._rate_limited_responses = 0
    
    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        
        if elapsed > 0:
            self._read_tokens = min(
                self.config.burst_limit,
                self._read_tokens + elapsed * self.config.read_per_sec
            )
            self._write_tokens = min(
                self.config.burst_limit,
                self._write_tokens + elapsed * self.config.write_per_sec
            )
            self._last_refill = now
    
    def _ensure_lock(self) -> asyncio.Lock:
        """Lazy-initialize the asyncio.Lock in the current event loop."""
        if self._lock is None:
            with self._lock_init_lock:
                if self._lock is None:
                    self._lock = asyncio.Lock()
        return self._lock

    async def acquire(
        self,
        is_write: bool = False,
        tokens: float = 1.0,
        block: bool = True,
        timeout: Optional[float] = None
    ) -> bool:
        """Acquire tokens for request.
        
        Args:
            is_write: True for mutations (POST/PUT/DELETE)
            tokens: Number of tokens to consume
            block: Whether to block until tokens available
            timeout: Max wait time if blocking
            
        Returns:
            True if tokens acquired
        """
        lock = self._ensure_lock()
        async with lock:
            self._refill()
            self._total_requests += 1
            
            bucket = self._write_tokens if is_write else self._read_tokens
            rate = self.config.write_per_sec if is_write else self.config.read_per_sec
            
            if bucket >= tokens:
                if is_write:
                    self._write_tokens -= tokens
                else:
                    self._read_tokens -= tokens
                return True
            
            if not block:
                self._throttled_requests += 1
                return False
            
            deficit = tokens - bucket
            wait_time = deficit / rate if rate > 0 else 1.0
            
            if timeout is not None and wait_time > timeout:
                self._throttled_requests += 1
                return False
        
        # Wait outside lock
        await asyncio.sleep(wait_time)
        
        lock = self._ensure_lock()
        async with lock:
            self._refill()
            target = self._write_tokens if is_write else self._read_tokens
            if target >= tokens:
                if is_write:
                    self._write_tokens -= tokens
                else:
                    self._read_tokens -= tokens
                return True
            self._throttled_requests += 1
            return False
    
    def get_status(self) -> Dict[str, Any]:
        """Get current bucket status."""
        return {
            "provider": self.provider,
            "read_tokens": self._read_tokens,
            "write_tokens": self._write_tokens,
            "max_tokens": self.config.burst_limit,
            "read_rate": self.config.read_per_sec,
            "write_rate": self.config.write_per_sec,
            "total_requests": self._total_requests,
            "throttled_requests": self._throttled_requests,
            "rate_limited_responses": self._rate_limited_responses,
        }
    
    def record_rate_limited_response(self) -> None:
        """Record that we received a 429 from provider."""
        self._rate_limited_responses += 1


# =============================================================================
# Global Rate Limiter Registry
# =============================================================================

_buckets: Dict[str, TokenBucket] = {}
_buckets_lock = threading.Lock()


def get_limiter(provider: str, config: Optional[TokenBucketConfig] = None) -> TokenBucket:
    """Get or create rate limiter for a provider.
    
    Args:
        provider: Provider name (e.g., "messari", "coingecko")
        config: TokenBucketConfig (required if creating new limiter)
    """
    if provider in _buckets:
        return _buckets[provider]
    
    with _buckets_lock:
        if provider in _buckets:
            return _buckets[provider]
        
        if config is None:
            # Try to load from config file
            config = _load_config_for_provider(provider)
        
        if config is None:
            raise ValueError(f"No config for provider: {provider}")
        
        bucket = TokenBucket(config, provider=provider)
        _buckets[provider] = bucket
        logger.info(
            f"Created rate limiter for {provider}: "
            f"{config.read_per_sec:.2f}r/s read, {config.write_per_sec:.2f}r/s write"
        )
        return bucket


def _load_config_for_provider(provider: str) -> Optional[TokenBucketConfig]:
    """Load rate limit config from YAML file.
    
    Handles unit conversion (per_min -> per_sec) and applies safety factor.
    """
    try:
        config_path = Path(__file__).parent.parent / "config" / "rate_limits.yaml"
        with open(config_path) as f:
            data = yaml.safe_load(f)
        
        providers = data.get("providers", {})
        if provider not in providers:
            return None
        
        cfg = providers[provider]
        self_limits = cfg.get("self_limits", {})
        
        # Handle per_min -> per_sec conversion
        read_per_sec = self_limits.get("read_per_sec")
        if read_per_sec is None:
            read_per_min = self_limits.get("read_per_min", 60)  # Default generous
            read_per_sec = read_per_min / 60.0
        
        write_per_sec = self_limits.get("write_per_sec")
        if write_per_sec is None:
            write_per_min = self_limits.get("write_per_min", 60)
            write_per_sec = write_per_min / 60.0
        
        # Burst limit (default to read_per_sec if not specified)
        burst = self_limits.get("burst_limit", max(read_per_sec, write_per_sec) * 2)
        
        return TokenBucketConfig(
            read_per_sec=read_per_sec,
            write_per_sec=write_per_sec,
            burst_limit=burst,
            safety_factor=0.8  # Always apply 20% headroom
        )
    except Exception as e:
        logger.warning(f"Could not load config for {provider}: {e}")
        return None


def get_all_limiter_status() -> Dict[str, Dict[str, Any]]:
    """Get status of all rate limiters."""
    return {name: bucket.get_status() for name, bucket in _buckets.items()}


# =============================================================================
# Rate-Limited HTTP Client
# =============================================================================

class ExternalAPIClient:
    """HTTP client with token bucket rate limiting and automatic retry.
    
    Features:
    - Separate read/write rate limits
    - Exponential backoff with jitter on 429s
    - Structured logging with provider/endpoint/request_id
    - Optional circuit breaker integration
    """
    
    def __init__(
        self,
        base_url: str,
        provider: str,
        read_per_sec: float,
        write_per_sec: float,
        burst_limit: Optional[float] = None,
        safety_factor: float = 0.8,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        auth_token: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.provider = provider
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        
        # Get or create rate limiter
        config = TokenBucketConfig(
            read_per_sec=read_per_sec,
            write_per_sec=write_per_sec,
            burst_limit=burst_limit,
            safety_factor=safety_factor
        )
        self._limiter = get_limiter(provider, config)
        
        self._client: Optional[httpx.AsyncClient] = None
        self._auth_token = auth_token
        self._extra_headers = extra_headers or {}
    
    async def __aenter__(self) -> ExternalAPIClient:
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            headers=self._build_headers()
        )
        return self
    
    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
    
    def _build_headers(self) -> Dict[str, str]:
        headers = {
            "User-Agent": f"MERID/1.0 ({self.provider})",
            "Accept": "application/json",
        }
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"
        headers.update(self._extra_headers)
        return headers
    
    def _log_request(
        self,
        method: str,
        path: str,
        status: int,
        latency_ms: float,
        attempt: int,
        request_id: str
    ) -> None:
        """Log structured request metadata."""
        logger.info(
            f"[{self.provider}] {method} {path} -> {status} "
            f"({latency_ms:.1f}ms, attempt {attempt}, rid={request_id})"
        )
    
    async def _request(
        self,
        method: str,
        path: str,
        is_write: bool = False,
        **kwargs
    ) -> httpx.Response:
        """Make rate-limited request with retry logic."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        request_id = f"{self.provider}-{time.time_ns():x}"[:16]
        
        for attempt in range(self.max_retries + 1):
            # Acquire rate limit token
            acquired = await self._limiter.acquire(
                is_write=is_write,
                block=True,
                timeout=30.0
            )
            if not acquired:
                raise RateLimitError(
                    f"Could not acquire rate limit token for {self.provider}"
                )
            
            t0 = time.monotonic()
            try:
                response = await self._client.request(
                    method,
                    url,
                    headers=self._build_headers(),
                    **kwargs
                )
                latency_ms = (time.monotonic() - t0) * 1000
                
                # Handle rate limit responses
                if response.status_code == 429:
                    self._limiter.record_rate_limited_response()
                    
                    if attempt < self.max_retries:
                        # Check for Retry-After header
                        retry_after = response.headers.get("Retry-After")
                        if retry_after:
                            wait = float(retry_after)
                        else:
                            # Exponential backoff with full jitter
                            wait = self.backoff_base * (2 ** attempt) + random.uniform(0, 1)
                        
                        logger.warning(
                            f"[{self.provider}] Rate limited (429), "
                            f"retrying in {wait:.1f}s (attempt {attempt + 1}/{self.max_retries + 1})"
                        )
                        await asyncio.sleep(wait)
                        continue
                    else:
                        self._log_request(method, path, 429, latency_ms, attempt + 1, request_id)
                        raise RateLimitError(
                            f"Rate limit exceeded for {self.provider} after {self.max_retries} retries"
                        )
                
                # Server error retry
                if 500 <= response.status_code < 600 and attempt < self.max_retries:
                    wait = self.backoff_base * (2 ** attempt)
                    logger.warning(
                        f"[{self.provider}] Server error {response.status_code}, "
                        f"retrying in {wait:.1f}s"
                    )
                    await asyncio.sleep(wait)
                    continue
                
                self._log_request(method, path, response.status_code, latency_ms, attempt + 1, request_id)
                response.raise_for_status()
                return response
                
            except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as e:
                latency_ms = (time.monotonic() - t0) * 1000
                if attempt < self.max_retries:
                    wait = self.backoff_base * (2 ** attempt)
                    logger.warning(
                        f"[{self.provider}] Network error: {e}, retrying in {wait:.1f}s"
                    )
                    await asyncio.sleep(wait)
                    continue
                self._log_request(method, path, 0, latency_ms, attempt + 1, request_id)
                raise
        
        raise RateLimitError(f"Max retries exceeded for {url}")
    
    async def get(self, path: str, **kwargs) -> httpx.Response:
        return await self._request("GET", path, is_write=False, **kwargs)
    
    async def post(self, path: str, **kwargs) -> httpx.Response:
        return await self._request("POST", path, is_write=True, **kwargs)
    
    async def put(self, path: str, **kwargs) -> httpx.Response:
        return await self._request("PUT", path, is_write=True, **kwargs)
    
    async def delete(self, path: str, **kwargs) -> httpx.Response:
        return await self._request("DELETE", path, is_write=True, **kwargs)


class RateLimitError(Exception):
    """Raised when rate limit is exceeded and retries exhausted."""
    pass


# =============================================================================
# Convenience Functions for Common Providers
# =============================================================================

async def messari_get(endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
    """Rate-limited GET to Messari API."""
    from merid.settings import settings
    
    headers = {}
    if settings.MESSARI_API_KEY:
        headers["x-messari-api-key"] = settings.MESSARI_API_KEY
    
    async with ExternalAPIClient(
        base_url="https://data.messari.io/api/v1",
        provider="messari",
        read_per_sec=0.27,  # 20/min with 0.8 safety factor
        write_per_sec=0.1,
        extra_headers=headers
    ) as client:
        resp = await client.get(endpoint, params=params)
        return resp.json()


async def coingecko_get(endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
    """Rate-limited GET to CoinGecko API."""
    from merid.settings import settings
    
    headers = {}
    if settings.COINGECKO_PRO_API_KEY:
        headers["x-cg-pro-api-key"] = settings.COINGECKO_PRO_API_KEY
    elif settings.COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = settings.COINGECKO_API_KEY
    
    async with ExternalAPIClient(
        base_url="https://api.coingecko.com/api/v3",
        provider="coingecko",
        read_per_sec=0.4,  # 30/min with 0.8 safety factor
        write_per_sec=0.1,
        extra_headers=headers
    ) as client:
        resp = await client.get(endpoint, params=params)
        return resp.json()


async def finnhub_get(endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
    """Rate-limited GET to Finnhub API."""
    from merid.settings import settings
    
    params = params or {}
    if settings.FINNHUB_API_KEY:
        params["token"] = settings.FINNHUB_API_KEY
    
    async with ExternalAPIClient(
        base_url="https://finnhub.io/api/v1",
        provider="finnhub",
        read_per_sec=0.8,  # 60/min with 0.8 safety factor
        write_per_sec=0.1
    ) as client:
        resp = await client.get(endpoint, params=params)
        return resp.json()


# =============================================================================
# Per-Agent Quota Management
# =============================================================================

@dataclass
class AgentQuota:
    """Quota allocated to an agent for a specific provider."""
    agent_id: str
    provider: str
    read_per_sec: float
    write_per_sec: float
    priority: int = 5  # 1-10


class AgentQuotaManager:
    """Manages fair-share allocation across agents.
    
    Ensures sum of agent quotas doesn't exceed global provider limits.
    
    NOTE: Lazily initializes asyncio.Lock to avoid event loop binding issues
    when created in one loop but used in another.
    """
    
    def __init__(self):
        self._quotas: Dict[str, AgentQuota] = {}  # key: "agent_id:provider"
        # Lazy-init the lock to avoid event loop binding issues
        self._lock: Optional[asyncio.Lock] = None
        self._lock_init_lock = threading.Lock()

    def _ensure_lock(self) -> asyncio.Lock:
        """Lazy-initialize the asyncio.Lock in the current event loop."""
        if self._lock is None:
            with self._lock_init_lock:
                if self._lock is None:
                    self._lock = asyncio.Lock()
        return self._lock
    
    async def register(
        self,
        agent_id: str,
        provider: str,
        read_per_sec: float,
        write_per_sec: float,
        priority: int = 5
    ) -> bool:
        """Register agent quota.
        
        Returns True if approved, False if would exceed global limits.
        """
        lock = self._ensure_lock()
        async with lock:
            key = f"{agent_id}:{provider}"
            
            if provider not in _buckets:
                logger.warning(f"No rate limiter for {provider}")
                return False
            
            global_limiter = _buckets[provider]
            global_read = global_limiter.config.read_per_sec
            global_write = global_limiter.config.write_per_sec
            
            # Calculate current allocation
            current_read = sum(
                q.read_per_sec for k, q in self._quotas.items()
                if q.provider == provider
            )
            current_write = sum(
                q.write_per_sec for k, q in self._quotas.items()
                if q.provider == provider
            )
            
            # Check fit
            if current_read + read_per_sec > global_read:
                logger.warning(
                    f"Agent {agent_id} read quota ({read_per_sec:.2f}) would exceed "
                    f"{provider} global limit ({global_read:.2f}, used {current_read:.2f})"
                )
                return False
            
            if current_write + write_per_sec > global_write:
                logger.warning(
                    f"Agent {agent_id} write quota ({write_per_sec:.2f}) would exceed "
                    f"{provider} global limit ({global_write:.2f}, used {current_write:.2f})"
                )
                return False
            
            self._quotas[key] = AgentQuota(
                agent_id=agent_id,
                provider=provider,
                read_per_sec=read_per_sec,
                write_per_sec=write_per_sec,
                priority=priority
            )
            
            logger.info(
                f"Registered {agent_id} for {provider}: "
                f"{read_per_sec:.2f}r/s read, priority {priority}"
            )
            return True
    
    async def unregister(self, agent_id: str, provider: Optional[str] = None) -> None:
        """Unregister agent quotas."""
        lock = self._ensure_lock()
        async with lock:
            if provider:
                self._quotas.pop(f"{agent_id}:{provider}", None)
            else:
                keys = [k for k in self._quotas if k.startswith(f"{agent_id}:")]
                for k in keys:
                    self._quotas.pop(k, None)
    
    def get_quota(self, agent_id: str, provider: str) -> Optional[AgentQuota]:
        return self._quotas.get(f"{agent_id}:{provider}")
    
    def get_all(self) -> Dict[str, AgentQuota]:
        return dict(self._quotas)


# Global quota manager
_quota_mgr: Optional[AgentQuotaManager] = None
_quota_mgr_lock = threading.Lock()


def get_quota_manager() -> AgentQuotaManager:
    """Get global quota manager."""
    global _quota_mgr
    if _quota_mgr is None:
        with _quota_mgr_lock:
            if _quota_mgr is None:
                _quota_mgr = AgentQuotaManager()
    return _quota_mgr
