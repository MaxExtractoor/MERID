"""Kalshi REST client - Implements EventVenueClient interface.

This is the **canonical resilient venue client** implementation.
Pattern: circuit breaker per venue, retry with backoff on I/O,
explicit OperationResult returns instead of silent fallbacks.
"""

from __future__ import annotations

import threading
import asyncio
import base64
import json
import random
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, TypeVar

import uuid

import httpx

from merid.event_venues.base import (
    EventMarket,
    EventOutcome,
    EventVenueClient,
    MarketFilter,
    PlacedOrder,
    VenueOrder,
    VenueOrderBook,
    VenuePosition,
    VenueTrade,
)
from merid.event_venues.kalshi.models import (
    KalshiBalance,
    KalshiConfig,
    KalshiMarket,
    KalshiOrder,
    KalshiOrderBook,
    KalshiOutcome,
    KalshiPosition,
    KalshiTrade,
)
from merid.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    OperationResult,
    get_circuit_breaker,
)
from utils.http_client import get_shared_ssl_context
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.client")


async def _validate_ticker_exists(ticker: str) -> tuple[bool, Optional[str]]:
    """Validate that a ticker exists in the Kalshi market catalog.

    Args:
        ticker: The Kalshi market ticker to validate (e.g., KXETH15M-26APR192030-30)

    Returns:
        Tuple of (exists: bool, error_message: Optional[str])
        If exists is False, error_message explains why.
    """
    if not ticker:
        return False, "Empty ticker"

    # Basic format validation - Kalshi tickers should start with KX
    if not ticker.startswith("KX"):
        return False, f"Invalid ticker format (must start with KX): {ticker}"

    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        catalog = get_market_catalog()
        if catalog:
            market = catalog.get_market(ticker)
            if market:
                return True, None
            return False, f"Ticker not found in catalog: {ticker}"
    except Exception as exc:
        # If catalog is unavailable, log warning but allow (fail-open for resilience)
        logger.debug(f"Could not validate ticker {ticker} against catalog: {exc}")

    return True, None  # Fail-open if catalog check fails


def merid_time_in_force_to_kalshi_api(tif: Optional[str]) -> str:
    """Map internal/MERID time-in-force labels to Kalshi Trade API v2 strings.

    ``CreateOrderRequest.time_in_force`` accepts only:
    ``fill_or_kill``, ``good_till_canceled``, ``immediate_or_cancel`` (OpenAPI oneof).
    Legacy short forms ``gtc`` / ``ioc`` / ``fok`` and ``GTC`` / ``IOC`` / ``FOK`` are accepted.
    """
    if tif is None:
        return "good_till_canceled"
    s = str(tif).strip()
    if not s:
        return "good_till_canceled"
    upper = s.upper()
    if upper == "GTC":
        return "good_till_canceled"
    if upper == "IOC":
        return "immediate_or_cancel"
    if upper == "FOK":
        return "fill_or_kill"
    lower = s.lower()
    if lower in ("gtc", "good_till_canceled"):
        return "good_till_canceled"
    if lower in ("ioc", "immediate_or_cancel"):
        return "immediate_or_cancel"
    if lower in ("fok", "fill_or_kill"):
        return "fill_or_kill"
    logger.warning(
        "[kalshi] unknown time_in_force=%r — using good_till_canceled",
        tif,
    )
    return "good_till_canceled"


# ═══════════════════════════════════════════════════════════════════════════
# Order Group Status Enum
# ═══════════════════════════════════════════════════════════════════════════

class OrderGroupStatus:
    """Order group lifecycle status constants.

    Used for monitoring order group state via REST polling or WS updates.
    """
    PENDING = "pending"
    ACTIVE = "active"
    TRIGGERED = "triggered"
    COMPLETED = "completed"
    CANCELED = "canceled"

T = TypeVar("T")

# BUG-1: Load resilience constants from settings so they can be tuned via env vars
# without a redeploy.  Fall back to hardcoded defaults if settings are unavailable
# (e.g. during unit tests that don't load .env).
try:
    from merid.settings import settings as _s
    KALSHI_MAX_RETRIES: int = _s.KALSHI_MAX_RETRIES
    KALSHI_BACKOFF_BASE: float = _s.KALSHI_BACKOFF_BASE
    KALSHI_CIRCUIT_FAILURE_THRESHOLD: int = _s.KALSHI_CIRCUIT_FAILURE_THRESHOLD
    KALSHI_CIRCUIT_RECOVERY_TIMEOUT: float = _s.KALSHI_CIRCUIT_RECOVERY_TIMEOUT
    KALSHI_MAX_CONCURRENT_REQUESTS: int = _s.KALSHI_MAX_CONCURRENT_REQUESTS
    _KALSHI_CONNECT_TIMEOUT: float = _s.KALSHI_CONNECT_TIMEOUT
    _KALSHI_READ_TIMEOUT: float = _s.KALSHI_READ_TIMEOUT
    _KALSHI_WRITE_TIMEOUT: float = _s.KALSHI_WRITE_TIMEOUT
    _KALSHI_POOL_TIMEOUT: float = _s.KALSHI_POOL_TIMEOUT
except Exception:
    KALSHI_MAX_RETRIES = 3
    KALSHI_BACKOFF_BASE = 2.0
    KALSHI_CIRCUIT_FAILURE_THRESHOLD = 10
    KALSHI_CIRCUIT_RECOVERY_TIMEOUT = 30.0
    KALSHI_MAX_CONCURRENT_REQUESTS = 10
    _KALSHI_CONNECT_TIMEOUT = 5.0
    _KALSHI_READ_TIMEOUT = 15.0
    _KALSHI_WRITE_TIMEOUT = 10.0
    _KALSHI_POOL_TIMEOUT = 5.0

KALSHI_RETRY_STATUSES = {429, 500, 502, 503, 504}


# ── Kalshi-specific exceptions ───────────────────────────────────────────

class KalshiSessionError(Exception):
    """Auth / session-level error (401, 403, 503) or FIX SessionReject (35=3).

    Attributes:
        reason_code: Optional FIX SessionRejectReason (tag 373)
        text: Error description
        status_code: HTTP status if from REST (401/403/503), None if from FIX
    """

    def __init__(
        self,
        text: str,
        *,
        reason_code: Optional[int] = None,
        status_code: Optional[int] = None,
    ):
        self.reason_code = reason_code
        self.text = text
        self.status_code = status_code
        parts = []
        if status_code is not None:
            parts.append(f"{status_code}")
        if reason_code is not None:
            parts.append(f"reason={reason_code}")
        parts.append(text)
        super().__init__(" ".join(parts))


class KalshiBusinessError(Exception):
    """Business-level error (400, 422) — bad params, invalid ticker, etc.

    Attributes:
        status_code: HTTP status (400 or 422)
        reason_code: Optional FIX-style BusinessRejectReason (tag 380)
        text: Error body / description
        ref_msg_type: Optional FIX MsgType that was rejected (tag 372)
    """

    def __init__(
        self,
        text: str,
        *,
        status_code: int = 400,
        reason_code: Optional[int] = None,
        ref_msg_type: Optional[str] = None,
    ):
        self.status_code = status_code
        self.reason_code = reason_code
        self.text = text
        self.ref_msg_type = ref_msg_type
        parts = [f"{status_code}"]
        if reason_code is not None:
            parts.append(f"reason={reason_code}")
        if ref_msg_type:
            parts.append(f"ref={ref_msg_type}")
        parts.append(text)
        super().__init__(" ".join(parts))


# Alias for FIX-style usage
KalshiBusinessReject = KalshiBusinessError


# ── Rate limit tiers ─────────────────────────────────────────────────────
# Kalshi tiers: Basic 20r/10w, Advanced 30/30, Premier 100/100, Prime 400/400

KALSHI_RATE_TIERS = {
    "basic":    {"read": 20, "write": 10},
    "advanced": {"read": 30, "write": 30},
    "premier":  {"read": 100, "write": 100},
    "prime":    {"read": 400, "write": 400},
}


class KalshiTokenBucket:
    """Token-bucket rate limiter — self-limit before hitting 429s.

    Tracks read and write tokens separately per the Kalshi tier system.
    Tokens refill at the tier's per-second rate.
    
    NOTE: Lazily initializes asyncio.Lock to avoid event loop binding issues
    when the bucket is created in one loop but used in another (e.g., via run_in_executor).
    """

    def __init__(self, tier: str = "basic") -> None:
        limits = KALSHI_RATE_TIERS.get(tier, KALSHI_RATE_TIERS["basic"])
        self.tier = tier
        self.read_rate: float = limits["read"]
        self.write_rate: float = limits["write"]
        self._read_tokens: float = self.read_rate
        self._write_tokens: float = self.write_rate
        self._last_refill: float = time.monotonic()
        # Lazy-init the lock to avoid event loop binding issues
        self._lock: Optional[asyncio.Lock] = None
        self._lock_init_lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._read_tokens = min(self.read_rate, self._read_tokens + elapsed * self.read_rate)
        self._write_tokens = min(self.write_rate, self._write_tokens + elapsed * self.write_rate)
        self._last_refill = now

    def _ensure_lock(self) -> asyncio.Lock:
        """Lazy-initialize the asyncio.Lock in the current event loop."""
        if self._lock is None:
            with self._lock_init_lock:
                if self._lock is None:
                    self._lock = asyncio.Lock()
        return self._lock

    async def acquire(self, is_write: bool = False) -> float:
        """Acquire a token, sleeping if necessary. Returns wait time in seconds."""
        lock = self._ensure_lock()
        async with lock:
            self._refill()
            tokens = self._write_tokens if is_write else self._read_tokens
            if tokens >= 1.0:
                if is_write:
                    self._write_tokens -= 1.0
                else:
                    self._read_tokens -= 1.0
                return 0.0

            # Need to wait for a token
            rate = self.write_rate if is_write else self.read_rate
            wait = (1.0 - tokens) / rate if rate > 0 else 1.0
        # Sleep outside the lock so other coroutines can proceed
        await asyncio.sleep(wait)
        lock = self._ensure_lock()
        async with lock:
            self._refill()
            if is_write:
                self._write_tokens = max(0, self._write_tokens - 1.0)
            else:
                self._read_tokens = max(0, self._read_tokens - 1.0)
        return wait

    @property
    def read_tokens_available(self) -> float:
        self._refill()
        return self._read_tokens

    @property
    def write_tokens_available(self) -> float:
        self._refill()
        return self._write_tokens

    def get_stats(self) -> Dict[str, Any]:
        """Return current token levels for observability."""
        self._refill()
        return {
            "tier": self.tier,
            "read_tokens": round(self._read_tokens, 2),
            "write_tokens": round(self._write_tokens, 2),
            "read_rate": self.read_rate,
            "write_rate": self.write_rate,
        }


class KalshiVenueClient(EventVenueClient):
    """
    Kalshi implementation of EventVenueClient.
    
    Uses Kalshi REST API (v2) for trading operations.
    Supports both email/password auth and RSA key auth.
    
    Resilience features:
    - Circuit breaker: Opens after KALSHI_CIRCUIT_FAILURE_THRESHOLD failures, recovers after KALSHI_CIRCUIT_RECOVERY_TIMEOUT s
    - Retry with backoff: KALSHI_MAX_RETRIES retries with exponential backoff
    - Explicit results: All methods return OperationResult for clear error handling
    """
    
    def __init__(self, config: Optional[KalshiConfig] = None, rate_tier: str = "basic"):
        self.config = config or KalshiConfig()
        self._http_client: Optional[httpx.AsyncClient] = None
        self._auth_token: Optional[str] = None
        self._member_id: Optional[str] = None

        # BUG-3: instance-level RSA key cache — prevents cross-instance contamination
        # when demo and live clients coexist in the same process.
        self._private_key: Optional[Any] = None
        self._cached_key_source: Optional[str] = None
        self._auth_mode: Optional[str] = None

        # BUG-5: stable circuit breaker name keyed on env (demo vs live) so the
        # breaker survives client reinstantiation and is queryable by name.
        _env = "demo" if self.config.use_demo else "live"
        self._circuit_breaker = get_circuit_breaker(
            f"kalshi_{_env}",
            failure_threshold=KALSHI_CIRCUIT_FAILURE_THRESHOLD,
            recovery_timeout=KALSHI_CIRCUIT_RECOVERY_TIMEOUT,
        )

        # Token bucket + semaphore are bound to the running event loop; create lazily
        # on first request so importing/instantiating the client on another loop never
        # trips "bound to a different event loop."
        self._rate_tier = rate_tier
        self._rate_limiter: Optional[KalshiTokenBucket] = None
        self._request_semaphore: Optional[asyncio.Semaphore] = None
        self._async_network_init_lock = threading.Lock()

        # Event-loop tracking for auto-reset on loop mismatch (Windows startup optimization)
        self._client_loop_id: Optional[int] = None
        self._loop_check_lock = threading.Lock()

        # Circuit-open log suppression: avoid flooding logs when many callers
        # hit an open circuit simultaneously (e.g. 20+ agents per tick)
        self._circuit_open_log_count: int = 0
        self._circuit_open_first_ts: float = 0.0
        
    @property
    def venue_name(self) -> str:
        return "kalshi"

    def _ensure_async_network_resources(self) -> None:
        if self._rate_limiter is not None and self._request_semaphore is not None:
            return
        with self._async_network_init_lock:
            if self._rate_limiter is not None and self._request_semaphore is not None:
                return
            asyncio.get_running_loop()
            self._rate_limiter = KalshiTokenBucket(tier=self._rate_tier)
            self._request_semaphore = asyncio.Semaphore(KALSHI_MAX_CONCURRENT_REQUESTS)
    
    async def _reset_http_client_after_loop_error(self) -> None:
        """Drop httpx client when the bound event loop was closed or replaced (e.g. asyncio.run)."""
        if self._http_client is not None:
            try:
                if not self._http_client.is_closed:
                    await self._http_client.aclose()
            except Exception as _close_err:
                logger.debug("[kalshi] HTTP client close error during reset: %s", _close_err)
            self._http_client = None
        self._auth_token = None
        self._rate_limiter = None
        self._request_semaphore = None
        self._client_loop_id = None  # Reset loop tracking

    def _get_current_loop_id(self) -> Optional[int]:
        """Get ID of current event loop, or None if no loop running."""
        try:
            loop = asyncio.get_running_loop()
            return id(loop)
        except RuntimeError:
            return None

    def _is_loop_mismatch(self) -> bool:
        """Check if client was created in a different event loop."""
        if self._client_loop_id is None:
            return False  # No client created yet
        current_loop_id = self._get_current_loop_id()
        if current_loop_id is None:
            return False  # Not in async context
        return current_loop_id != self._client_loop_id

    def _is_recoverable_windows_error(self, exc: Exception) -> bool:
        """Check if exception is a recoverable Windows I/O error.

        Recoverable errors (WinError 995, 10038, 10054, 10060) can often be
        resolved by retrying with a fresh connection. This prevents unnecessary
        full system shutdowns due to transient Windows networking issues.
        """
        import sys

        if sys.platform != "win32":
            return False

        # Check for ConnectionResetError (always recoverable on retry)
        if isinstance(exc, ConnectionResetError):
            return True

        # Check for specific WinError codes in string representation
        exc_str = str(exc)
        win_errors = ["WinError 995", "WinError 10038", "WinError 10054", "WinError 10060"]
        if any(code in exc_str for code in win_errors):
            return True

        # Check OSError winerror attribute
        if isinstance(exc, OSError) and hasattr(exc, 'winerror'):
            if exc.winerror in {995, 10038, 10054, 10060}:
                return True

        return False

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Ensure HTTP client is initialized and authenticated.
        
        Auto-resets client if bound to a different event loop (Windows startup optimization).
        This prevents "Event loop is closed" errors during startup when the client singleton
        was created in a different loop context.
        """
        # Check for event-loop mismatch and auto-reset (prevents retry storms)
        if self._http_client is not None and self._is_loop_mismatch():
            logger.debug("[kalshi] Event-loop mismatch detected, resetting HTTP client proactively")
            await self._reset_http_client_after_loop_error()

        if self._http_client is None or self._http_client.is_closed:
            logger.debug("[kalshi] Initializing new HTTP client")
            # BUG-4: per-operation timeouts instead of a single global value
            # BUG-4: per-operation timeouts instead of a single global value
            # C4-FIX: Add connection pool limits to prevent exhaustion under burst load
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=_KALSHI_CONNECT_TIMEOUT,
                    read=_KALSHI_READ_TIMEOUT,
                    write=_KALSHI_WRITE_TIMEOUT,
                    pool=_KALSHI_POOL_TIMEOUT,
                ),
                limits=httpx.Limits(
                    max_connections=200,
                    max_keepalive_connections=50,
                    keepalive_expiry=30.0,
                ),
                headers={
                    "User-Agent": "MERID-Kalshi-Client/1.0",
                    "Content-Type": "application/json"
                },
                verify=get_shared_ssl_context(),
            )
            # Track which loop this client is bound to
            self._client_loop_id = self._get_current_loop_id()
            # Authenticate immediately on new client
            await self._authenticate()
        return self._http_client

    async def connect(self) -> None:
        """Initialize HTTP client and authenticate."""
        await self._ensure_client()
    
    async def _authenticate(self) -> None:
        """Authenticate with Kalshi API."""
        if self._http_client is None:
            raise RuntimeError("HTTP client not initialized before authentication")

        if self.config.api_key and (self.config.private_key_path or getattr(self.config, "private_key_pem", None)):
            # RSA key authentication
            await self._authenticate_rsa()
        elif self.config.email and self.config.password:
            # Email/password authentication
            await self._authenticate_password()
        else:
            logger.debug("No Kalshi credentials provided, operations will fail")
    
    async def _authenticate_password(self) -> None:
        """Authenticate with email/password."""
        try:
            url = f"{self.config.base_url}/login"
            response = await self._http_client.post(
                url,
                json={"email": self.config.email, "password": self.config.password}
            )
            response.raise_for_status()
            data = response.json()
            
            self._auth_token = data.get("token")
            self._member_id = data.get("member_id")
            
            # Update client with auth header
            self._http_client.headers["Authorization"] = f"Bearer {self._auth_token}"
            
            logger.info(f"Authenticated with Kalshi (member: {self._member_id})")
            
        except (ConnectionError, RuntimeError, ValueError, httpx.HTTPStatusError) as e:
            # BUG-2: httpx.HTTPStatusError (raised by raise_for_status()) was not caught;
            # record the failure against the circuit breaker so repeated auth errors
            # eventually open the circuit instead of hammering the auth endpoint.
            logger.error("[kalshi] Authentication failed (%s): %s", type(e).__name__, e)
            await self._circuit_breaker.record_failure(e)
            raise
    
    async def _authenticate_rsa(self) -> None:
        """Load RSA private key for per-request signing.

        Kalshi RSA auth signs every request: timestamp_ms + METHOD + path.
        Signature uses PSS padding with SHA-256.

        Key loading priority:
          1. private_key_path (file on disk)
          2. private_key_pem  (inline PEM string from env/settings)

        BUG-3: Uses instance-level cache (self._private_key / self._cached_key_source)
        to prevent demo and live instances from sharing a key object.  No silent
        fallback to password auth — if RSA is configured and fails, raise immediately
        so the operator is forced to fix credentials rather than silently downgrading.
        """
        _this_cache_key = self.config.private_key_path or ("pem" if getattr(self.config, "private_key_pem", None) else "")
        try:
            # Fast path: reuse instance-cached key if same source
            if self._private_key is not None and self._cached_key_source == _this_cache_key:
                self._auth_mode = "rsa"
                logger.debug("Kalshi RSA auth ready (cached, source: %s)", self._cached_key_source)
                return

            from cryptography.hazmat.primitives import serialization

            pem_bytes: Optional[bytes] = None
            if self.config.private_key_path:
                with open(self.config.private_key_path, "rb") as f:
                    pem_bytes = f.read()
                logger.info("Loaded Kalshi RSA key from file: %s", self.config.private_key_path)
            elif getattr(self.config, "private_key_pem", None):
                pem_bytes = self.config.private_key_pem.encode()
                logger.info("Loaded Kalshi RSA key from inline PEM (KALSHI_PRIVATE_KEY_PEM)")

            if pem_bytes is None:
                raise ValueError("No RSA key source: set private_key_path or KALSHI_PRIVATE_KEY_PEM")

            self._private_key = serialization.load_pem_private_key(pem_bytes, password=None)
            self._auth_mode = "rsa"
            self._cached_key_source = _this_cache_key
            logger.info("Kalshi RSA auth ready (source: %s)", _this_cache_key)
        except ImportError as e:
            # BUG-3: no silent fallback — cryptography is a required dependency for RSA auth
            raise RuntimeError(
                "cryptography package not installed — cannot use RSA auth. "
                "Run: pip install cryptography"
            ) from e
        except (FileNotFoundError, ValueError, OSError) as e:
            # BUG-3: raise unconditionally; do not silently downgrade to password auth
            logger.error("[kalshi] Failed to load RSA key (source=%s): %s", _this_cache_key, e)
            raise

    def _sign_headers(self, method: str, path: str) -> Dict[str, str]:
        """Generate Kalshi RSA auth headers for a single request.

        Args:
            method: HTTP method (GET, POST, DELETE)
            path: Full API path (e.g. /trade-api/v2/portfolio/orders)

        Returns:
            Dict with KALSHI-ACCESS-KEY, KALSHI-ACCESS-TIMESTAMP, KALSHI-ACCESS-SIGNATURE

        Note: Kalshi v2 signs timestamp + METHOD + path only (no request body).
        """
        if not hasattr(self, "_private_key") or self._private_key is None:
            raise RuntimeError("RSA private key not loaded. Check credentials and private_key_path.")

        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        ts_ms = str(int(time.time() * 1000))
        message = ts_ms + method.upper() + path
        signature = self._private_key.sign(
            message.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.config.api_key,
            "KALSHI-ACCESS-TIMESTAMP": ts_ms,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
            "Content-Type": "application/json",
        }
    
    async def close(self) -> None:
        """Close HTTP client and clear auth state.

        Safe to call multiple times (idempotent).
        """
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
        self._http_client = None
        self._auth_token = None

    def __del__(self) -> None:
        """Safety net: warn if client was never closed."""
        # Use getattr to handle case where __init__ wasn't fully called
        http_client = getattr(self, '_http_client', None)
        if http_client is not None and not http_client.is_closed:
            logger.warning(
                "KalshiVenueClient garbage-collected without close(). "
                "Use 'async with client:' or call 'await client.close()' explicitly."
            )
    
    # ------------------------------------------------------------------------
    # Resilient Request Infrastructure
    # ------------------------------------------------------------------------
    
    async def _request_with_resilience(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        operation_name: str = "request",
    ) -> OperationResult[Dict[str, Any]]:
        """
        Execute HTTP request with circuit breaker and retry logic.
        
        This is the core resilient I/O method. All public methods should use this.
        
        Args:
            method: HTTP method (GET, POST, DELETE, etc.)
            path: URL path (appended to base_url)
            params: Query parameters
            json_data: JSON body for POST/PUT
            operation_name: Human-readable name for logging
            
        Returns:
            OperationResult with parsed JSON data or error
        """
        url = f"{self.config.base_url}{path}"
        start_time = time.time()
        last_error: Optional[Exception] = None

        for attempt in range(KALSHI_MAX_RETRIES + 1):
            try:
                self._ensure_async_network_resources()
                client = await self._ensure_client()
                # Token bucket: self-limit before hitting 429s
                is_write = method.upper() in ("POST", "PUT", "DELETE", "PATCH")
                assert self._rate_limiter is not None and self._request_semaphore is not None
                await self._rate_limiter.acquire(is_write=is_write)

                # Check circuit breaker before making request
                # Also apply concurrency semaphore to limit in-flight requests
                async with self._request_semaphore:
                    async with self._circuit_breaker:
                        # RSA per-request signing: generate timestamp as late as
                        # possible so it doesn't expire while queued behind the
                        # semaphore or circuit breaker.
                        extra_headers: Dict[str, str] = {}
                        if getattr(self, "_auth_mode", None) == "rsa":
                            full_path = f"/trade-api/v2{path}"
                            extra_headers = self._sign_headers(method.upper(), full_path)

                        response = await client.request(
                            method=method,
                            url=url,
                            params=params,
                            json=json_data,
                            headers=extra_headers if extra_headers else None,
                        )
                    
                    latency_ms = (time.time() - start_time) * 1000
                    
                    # Check for retryable status codes
                    if response.status_code in KALSHI_RETRY_STATUSES:
                        if attempt < KALSHI_MAX_RETRIES:
                            # Jittered exponential backoff: base^attempt * [1.0, 2.0)
                            # Prevents thundering herd when services recover
                            base_wait = KALSHI_BACKOFF_BASE ** attempt
                            jitter = 1.0 + random.random()  # Uniform [1.0, 2.0)
                            
                            # For 429, honour Retry-After header if present and larger
                            if response.status_code == 429:
                                retry_after = response.headers.get("Retry-After")
                                try:
                                    ra_seconds = float(retry_after) if retry_after else 0
                                    wait_time = max(base_wait * jitter, ra_seconds)
                                except (ValueError, TypeError):
                                    wait_time = base_wait * jitter
                                logger.warning(
                                    f"[kalshi] {operation_name} rate-limited (429), "
                                    f"Retry-After={retry_after}, sleeping {wait_time:.2f}s (attempt {attempt + 1})"
                                )
                            else:
                                wait_time = base_wait * jitter
                                logger.debug(
                                    f"[kalshi] {operation_name} returned {response.status_code}, "
                                    f"retrying in {wait_time:.2f}s (attempt {attempt + 1})"
                                )
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            error = httpx.HTTPStatusError(
                                f"Max retries exceeded: {response.status_code}",
                                request=response.request,
                                response=response,
                            )
                            return OperationResult.fail(
                                error,
                                latency_ms=latency_ms,
                                retries=attempt,
                                operation=operation_name,
                                status_code=response.status_code,
                            )
                    
                    # Auth errors — log details and attempt re-auth once
                    if response.status_code in (401, 403):
                        body_text = response.text[:200] if response.text else ""
                        if not getattr(self, '_auth_warned', False):
                            logger.warning(
                                f"[kalshi] {operation_name} auth error "
                                f"{response.status_code}: {body_text}. "
                                f"Check: key ID, private key path, timestamp (ms), "
                                f"signed path starts with /trade-api/v2/"
                            )
                            self._auth_warned = True
                        else:
                            logger.debug(f"[kalshi] {operation_name} auth error {response.status_code} (suppressed)")
                        # Try re-auth once on first 401
                        if response.status_code == 401 and attempt == 0:
                            try:
                                await self._authenticate()
                                logger.debug("[kalshi] Re-authenticated after 401, retrying")
                                continue
                            except Exception as auth_exc:
                                logger.debug(f"[kalshi] Re-auth failed: {auth_exc}")

                        error = httpx.HTTPStatusError(
                            f"Auth error: {response.status_code}",
                            request=response.request,
                            response=response,
                        )
                        return OperationResult.fail(
                            error,
                            latency_ms=latency_ms,
                            retries=attempt,
                            operation=operation_name,
                            status_code=response.status_code,
                        )

                    # Business errors (400, 422) — bad params, invalid ticker
                    if response.status_code in (400, 422):
                        body_text = response.text[:300] if response.text else ""
                        logger.warning(
                            f"[kalshi] {operation_name} business error "
                            f"{response.status_code}: {body_text}"
                        )
                        error = KalshiBusinessError(
                            body_text,
                            status_code=response.status_code,
                        )
                        return OperationResult.fail(
                            error,
                            latency_ms=latency_ms,
                            retries=attempt,
                            operation=operation_name,
                            status_code=response.status_code,
                        )

                    # Other client errors (4xx) - don't retry
                    if 400 <= response.status_code < 500:
                        error = httpx.HTTPStatusError(
                            f"Client error: {response.status_code}",
                            request=response.request,
                            response=response,
                        )
                        return OperationResult.fail(
                            error,
                            latency_ms=latency_ms,
                            retries=attempt,
                            operation=operation_name,
                            status_code=response.status_code,
                        )
                    
                    # Success
                    response.raise_for_status()
                    data = response.json()
                    
                    # Reset circuit-open log suppression on success
                    if self._circuit_open_log_count > 0:
                        logger.info(
                            f"[kalshi] Circuit recovered — {self._circuit_open_log_count} calls were blocked"
                        )
                        self._circuit_open_log_count = 0
                    
                    return OperationResult.ok(
                        data,
                        latency_ms=latency_ms,
                        retries=attempt,
                        operation=operation_name,
                    )
                    
            except CircuitOpenError as e:
                # Circuit is open - fail fast
                latency_ms = (time.time() - start_time) * 1000
                self._circuit_open_log_count += 1
                if self._circuit_open_log_count == 1:
                    self._circuit_open_first_ts = time.time()
                    logger.warning(f"[kalshi] Circuit OPEN — blocking {operation_name} (retry in {e.time_until_retry:.1f}s)")
                elif self._circuit_open_log_count == 10:
                    elapsed = time.time() - self._circuit_open_first_ts
                    logger.warning(
                        f"[kalshi] Circuit still OPEN — suppressed {self._circuit_open_log_count} blocked calls in {elapsed:.1f}s"
                    )
                else:
                    logger.debug(f"[kalshi] Circuit open for {operation_name} (suppressed #{self._circuit_open_log_count})")
                return OperationResult.fail(
                    e,
                    latency_ms=latency_ms,
                    retries=attempt,
                    operation=operation_name,
                    circuit_open=True,
                )
                
            except httpx.TimeoutException as e:
                last_error = e
                if attempt < KALSHI_MAX_RETRIES:
                    # Jittered exponential backoff
                    wait_time = (KALSHI_BACKOFF_BASE ** attempt) * (1.0 + random.random())
                    logger.warning(
                        f"[kalshi] {operation_name} timeout, retrying in {wait_time:.2f}s "
                        f"(attempt {attempt + 1})"
                    )
                    await asyncio.sleep(wait_time)
                    continue
                    
            except (httpx.ConnectError, httpx.ReadError) as e:
                last_error = e
                if attempt < KALSHI_MAX_RETRIES:
                    # Jittered exponential backoff
                    wait_time = (KALSHI_BACKOFF_BASE ** attempt) * (1.0 + random.random())
                    logger.warning(
                        f"[kalshi] {operation_name} connection error, retrying in {wait_time:.2f}s "
                        f"(attempt {attempt + 1}): {e}"
                    )
                    await asyncio.sleep(wait_time)
                    continue

            except RuntimeError as e:
                msg = str(e).lower()
                if "event loop is closed" in msg or "different event loop" in msg:
                    last_error = e
                    if attempt < KALSHI_MAX_RETRIES:
                        await self._reset_http_client_after_loop_error()
                        logger.warning(
                            "[kalshi] %s event-loop mismatch (%s), HTTP client reset; retry %s/%s",
                            operation_name,
                            e,
                            attempt + 1,
                            KALSHI_MAX_RETRIES + 1,
                        )
                        await asyncio.sleep(0.05)
                        continue
                # Handle "client has been closed" error - reset and retry
                if "client has been closed" in msg:
                    last_error = e
                    if attempt < KALSHI_MAX_RETRIES:
                        await self._reset_http_client_after_loop_error()
                        logger.warning(
                            "[kalshi] %s HTTP client was closed (%s), reset; retry %s/%s",
                            operation_name,
                            e,
                            attempt + 1,
                            KALSHI_MAX_RETRIES + 1,
                        )
                        await asyncio.sleep(0.05)
                        continue
                latency_ms = (time.time() - start_time) * 1000
                logger.warning(f"[kalshi] {operation_name} RuntimeError after retries: {e}")
                return OperationResult.fail(
                    e,
                    latency_ms=latency_ms,
                    retries=attempt,
                    operation=operation_name,
                )

            except (OSError, ConnectionResetError, asyncio.InvalidStateError) as e:
                # Windows I/O error recovery (WinError 995, 10038, 10054, etc.)
                # These errors can occur under high load and are often recoverable
                last_error = e
                exc_str = str(e)
                is_recoverable = False

                # Check for specific Windows error codes
                import sys
                if sys.platform == "win32":
                    win_errors = ["WinError 995", "WinError 10038", "WinError 10054", "WinError 10060"]
                    if any(code in exc_str for code in win_errors):
                        is_recoverable = True
                    # Also check winerror attribute on OSError
                    if isinstance(e, OSError) and hasattr(e, 'winerror'):
                        if e.winerror in {995, 10038, 10054, 10060}:
                            is_recoverable = True

                # InvalidStateError from asyncio is often recoverable
                if isinstance(e, asyncio.InvalidStateError):
                    is_recoverable = True

                if is_recoverable and attempt < KALSHI_MAX_RETRIES:
                    # Use longer backoff for Windows errors - they may need more time
                    wait_time = (KALSHI_BACKOFF_BASE ** attempt) * (1.0 + random.random()) * 2.0
                    logger.warning(
                        "[kalshi] %s Windows/async I/O error, retrying in %.2fs "
                        "(attempt %s/%s): %s",
                        operation_name,
                        wait_time,
                        attempt + 1,
                        KALSHI_MAX_RETRIES + 1,
                        e,
                    )
                    # Reset client to ensure clean state for retry
                    await self._reset_http_client_after_loop_error()
                    await asyncio.sleep(wait_time)
                    continue

                # Not recoverable or max retries exhausted
                latency_ms = (time.time() - start_time) * 1000
                logger.error(
                    "[kalshi] %s Windows/async I/O error not recoverable: %s",
                    operation_name,
                    e,
                )
                return OperationResult.fail(
                    e,
                    latency_ms=latency_ms,
                    retries=attempt,
                    operation=operation_name,
                )

            except Exception as e:
                # Unexpected error - don't retry
                latency_ms = (time.time() - start_time) * 1000
                logger.warning(f"[kalshi] {operation_name} unexpected error: {e}")
                return OperationResult.fail(
                    e,
                    latency_ms=latency_ms,
                    retries=attempt,
                    operation=operation_name,
                )
        
        # Max retries exhausted
        latency_ms = (time.time() - start_time) * 1000
        error = last_error or RuntimeError(f"Max retries exceeded for {operation_name}")
        return OperationResult.fail(
            error,
            latency_ms=latency_ms,
            retries=KALSHI_MAX_RETRIES,
            operation=operation_name,
        )
    
    @property
    def is_circuit_open(self) -> bool:
        """True if the circuit breaker is currently open (blocking calls).

        Callers can use this to skip batches of requests that would all fail
        immediately, avoiding log noise and wasted latency.
        """
        return self._circuit_breaker.is_open

    def get_circuit_status(self) -> Dict[str, Any]:
        """Get circuit breaker status for monitoring."""
        return self._circuit_breaker.get_stats()
    
    # ------------------------------------------------------------------------
    # Market Data
    # ------------------------------------------------------------------------
    
    async def list_markets(self, filter_params: Optional[MarketFilter] = None) -> List[EventMarket]:
        """List Kalshi markets.
        
        Returns empty list on failure for backward compatibility.
        Use list_markets_result() for explicit error handling.
        """
        result = await self.list_markets_result(filter_params)
        return result.unwrap_or([])
    
    async def list_markets_result(
        self, filter_params: Optional[MarketFilter] = None
    ) -> OperationResult[List[EventMarket]]:
        """List Kalshi markets with explicit result.

        Supports cursor-based pagination to fetch beyond the 200-item page
        limit.  Set ``filter_params.limit`` to the *total* number of markets
        you want; this method pages through automatically.

        Returns:
            OperationResult containing list of markets or error details
        """
        filter_params = filter_params or MarketFilter()
        desired = filter_params.limit
        page_size = min(desired, 200)  # Kalshi max per page

        params: Dict[str, Any] = {
            "limit": page_size,
            "status": "open" if filter_params.active_only else None,
        }
        if filter_params.category:
            params["category"] = filter_params.category
        if filter_params.search:
            params["series_ticker"] = filter_params.search
        if filter_params.event_ticker:
            params["event_ticker"] = filter_params.event_ticker

        all_markets: List[EventMarket] = []
        cursor: Optional[str] = None
        total_latency = 0.0
        total_retries = 0
        max_pages = max(1, (desired + page_size - 1) // page_size)

        for _ in range(max_pages):
            if cursor:
                params["cursor"] = cursor

            result = await self._request_with_resilience(
                "GET", "/markets", params=params, operation_name="list_markets"
            )
            total_latency += result.latency_ms or 0
            total_retries += result.retries or 0

            if not result.success:
                if all_markets:
                    # Return what we have so far on partial failure
                    break
                return OperationResult.fail(
                    result.error,
                    latency_ms=total_latency,
                    retries=total_retries,
                )

            for market_data in result.data.get("markets", []):
                market = self._parse_market(market_data)
                if market:
                    all_markets.append(self._to_event_market(market))

            cursor = result.data.get("cursor")
            if not cursor or len(all_markets) >= desired:
                break

        return OperationResult.ok(
            all_markets[:desired],
            latency_ms=total_latency,
            retries=total_retries,
        )
    
    async def get_market(self, market_id: str) -> Optional[EventMarket]:
        """Get market details by ticker.
        
        Returns None on failure for backward compatibility.
        Use get_market_result() for explicit error handling.
        """
        result = await self.get_market_result(market_id)
        return result.unwrap_or(None)
    
    async def get_market_result(self, market_id: str) -> OperationResult[Optional[EventMarket]]:
        """Get market details with explicit result."""
        result = await self._request_with_resilience(
            "GET", f"/markets/{market_id}", operation_name=f"get_market({market_id})"
        )
        
        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
            )
        
        market = self._parse_market(result.data.get("market", result.data))
        return OperationResult.ok(
            self._to_event_market(market) if market else None,
            latency_ms=result.latency_ms,
            retries=result.retries,
        )
    
    async def get_orderbook(self, market_id: str, outcome_id: Optional[str] = None) -> Optional[VenueOrderBook]:
        """Get order book for a market.
        
        Returns None on failure for backward compatibility.
        Use get_orderbook_result() for explicit error handling.
        """
        result = await self.get_orderbook_result(market_id, outcome_id)
        return result.unwrap_or(None)
    
    async def get_orderbook_result(
        self, market_id: str, outcome_id: Optional[str] = None
    ) -> OperationResult[Optional[VenueOrderBook]]:
        """Get order book with explicit result."""
        result = await self._request_with_resilience(
            "GET", f"/markets/{market_id}/orderbook", operation_name=f"get_orderbook({market_id})"
        )
        
        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
            )
        
        return OperationResult.ok(
            self._to_venue_orderbook(result.data, market_id),
            latency_ms=result.latency_ms,
            retries=result.retries,
        )
    
    async def list_events(
        self, series_ticker: Optional[str] = None, limit: int = 100
    ) -> OperationResult[List[Dict[str, Any]]]:
        """List Kalshi events with cursor-based pagination.

        Supports filtering by series_ticker and automatically pages through
        all results up to the specified limit.

        Args:
            series_ticker: Optional series ticker to filter events
            limit: Maximum number of events to fetch (default 100)

        Returns:
            OperationResult containing list of event dictionaries
        """
        all_events: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        total_latency = 0.0
        total_retries = 0
        page_size = min(limit, 200)  # Kalshi max per page
        max_pages = max(1, (limit + page_size - 1) // page_size)

        for _ in range(max_pages):
            params: Dict[str, Any] = {"limit": page_size}
            if series_ticker:
                params["series_ticker"] = series_ticker
            if cursor:
                params["cursor"] = cursor

            result = await self._request_with_resilience(
                "GET", "/events", params=params, operation_name="list_events"
            )

            total_latency += result.latency_ms or 0
            total_retries += result.retries or 0

            if not result.success:
                if all_events:
                    logger.warning(f"list_events: Partial failure, returning {len(all_events)} events")
                    break
                return OperationResult.fail(
                    result.error,
                    latency_ms=total_latency,
                    retries=total_retries,
                )

            events = result.data.get("events", [])
            all_events.extend(events)

            cursor = result.data.get("cursor")
            if not cursor or len(all_events) >= limit:
                break

        return OperationResult.ok(
            all_events[:limit],
            latency_ms=total_latency,
            retries=total_retries,
        )

    # ------------------------------------------------------------------------
    # Trading
    # ------------------------------------------------------------------------

    async def list_series(
        self, limit: int = 200
    ) -> OperationResult[List[Dict[str, Any]]]:
        """List all series with cursor-based pagination.

        Args:
            limit: Maximum number of series to fetch (default 200)

        Returns:
            OperationResult containing list of series dictionaries
        """
        all_series: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        total_latency = 0.0
        total_retries = 0
        page_size = min(limit, 200)
        max_pages = max(1, (limit + page_size - 1) // page_size)

        for _ in range(max_pages):
            params: Dict[str, Any] = {"limit": page_size}
            if cursor:
                params["cursor"] = cursor

            result = await self._request_with_resilience(
                "GET", "/series", params=params, operation_name="list_series"
            )

            total_latency += result.latency_ms or 0
            total_retries += result.retries or 0

            if not result.success:
                if all_series:
                    logger.warning(f"list_series: Partial failure, returning {len(all_series)} series")
                    break
                return OperationResult.fail(
                    result.error,
                    latency_ms=total_latency,
                    retries=total_retries,
                )

            series_list = result.data.get("series", [])
            all_series.extend(series_list)

            cursor = result.data.get("cursor")
            if not cursor or len(all_series) >= limit:
                break

        return OperationResult.ok(
            all_series[:limit],
            latency_ms=total_latency,
            retries=total_retries,
        )

    async def get_series(self, series_ticker: str) -> OperationResult[Optional[Dict[str, Any]]]:
        """Get a single series by ticker.

        Args:
            series_ticker: The series ticker identifier

        Returns:
            OperationResult containing series dict or None if not found
        """
        result = await self._request_with_resilience(
            "GET", f"/series/{series_ticker}", operation_name=f"get_series({series_ticker})"
        )

        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
            )

        return OperationResult.ok(
            result.data.get("series", result.data),
            latency_ms=result.latency_ms,
            retries=result.retries,
        )

    async def list_multivariate_events(
        self,
        series_ticker: Optional[str] = None,
        collection_ticker: Optional[str] = None,
        limit: int = 200,
    ) -> OperationResult[List[Dict[str, Any]]]:
        """List multivariate events with cursor-based pagination.

        Supports filtering by series_ticker and collection_ticker.

        Args:
            series_ticker: Optional series ticker to filter events
            collection_ticker: Optional collection ticker to filter events
            limit: Maximum number of events to fetch (default 200, max 200)

        Returns:
            OperationResult containing list of multivariate event dicts
        """
        all_events: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        total_latency = 0.0
        total_retries = 0
        page_size = min(limit, 200)
        max_pages = max(1, (limit + page_size - 1) // page_size)

        for _ in range(max_pages):
            params: Dict[str, Any] = {"limit": page_size}
            if series_ticker:
                params["series_ticker"] = series_ticker
            if collection_ticker:
                params["collection_ticker"] = collection_ticker
            if cursor:
                params["cursor"] = cursor

            result = await self._request_with_resilience(
                "GET", "/multivariate/events", params=params, operation_name="list_multivariate_events"
            )

            total_latency += result.latency_ms or 0
            total_retries += result.retries or 0

            if not result.success:
                if all_events:
                    logger.warning(f"list_multivariate_events: Partial failure, returning {len(all_events)} events")
                    break
                return OperationResult.fail(
                    result.error,
                    latency_ms=total_latency,
                    retries=total_retries,
                )

            events = result.data.get("events", [])
            all_events.extend(events)

            cursor = result.data.get("cursor")
            if not cursor or len(all_events) >= limit:
                break

        return OperationResult.ok(
            all_events[:limit],
            latency_ms=total_latency,
            retries=total_retries,
        )

    async def get_portfolio_history(
        self, limit: int = 200
    ) -> OperationResult[Dict[str, Any]]:
        """Get portfolio history for PnL calculation.

        Paginates through portfolio history and aggregates realized PnL and fees.

        Args:
            limit: Maximum number of history entries per page

        Returns:
            OperationResult containing dict with realized_pnl, fees_paid, net_pnl
        """
        cursor: Optional[str] = None
        total_latency = 0.0
        total_retries = 0
        realized_pnl = Decimal("0")
        fees_paid = Decimal("0")
        entries_count = 0
        max_pages = 50  # P0-4 FIX: Prevent unbounded pagination
        page = 0

        while page < max_pages:
            params: Dict[str, Any] = {"limit": limit}
            if cursor:
                params["cursor"] = cursor

            result = await self._request_with_resilience(
                "GET", "/portfolio/history", params=params, operation_name="get_portfolio_history"
            )

            total_latency += result.latency_ms or 0
            total_retries += result.retries or 0

            if not result.success:
                if entries_count > 0:
                    logger.warning(f"get_portfolio_history: Partial failure, returning {entries_count} entries")
                    break
                return OperationResult.fail(
                    result.error,
                    latency_ms=total_latency,
                    retries=total_retries,
                )

            data = result.data or {}
            history = data.get("history", [])

            for entry in history:
                realized_pnl += Decimal(str(entry.get("realized_pnl", 0)))
                fees_paid += Decimal(str(entry.get("fees_paid", 0)))
                entries_count += 1

            cursor = data.get("cursor")
            if not cursor:
                break
            page += 1

        if cursor:
            logger.warning(f"get_portfolio_history: Hit max_pages limit ({max_pages}), returning partial data")

        net_pnl = realized_pnl - fees_paid

        return OperationResult.ok(
            {
                "realized_pnl": realized_pnl,
                "fees_paid": fees_paid,
                "net_pnl": net_pnl,
                "entries_count": entries_count,
            },
            latency_ms=total_latency,
            retries=total_retries,
        )
    
    async def place_order(self, order: VenueOrder) -> Optional[PlacedOrder]:
        """Place order on Kalshi.
        
        Returns None on failure for backward compatibility.
        Use place_order_result() for explicit error handling.
        """
        result = await self.place_order_result(order)
        return result.unwrap_or(None)
    
    async def place_order_result(self, order: VenueOrder, order_group_id: Optional[str] = None, self_trade_prevention_type: Optional[str] = None) -> OperationResult[Optional[PlacedOrder]]:
        """Place order with explicit result.

        Kalshi order format:
          POST /portfolio/orders
          {ticker, side, action, type, count, {side}_price, time_in_force, client_order_id}
        
        Args:
            order: VenueOrder to place
            order_group_id: Optional order group ID for aggregate limits
            self_trade_prevention_type: Optional STP mode (e.g., "taker_at_cross")
        """
        # Use market_id directly as the ticker - it should already be in Kalshi's format
        # from the market catalog. DO NOT normalize here - normalization is for internal
        # grouping only and can break the actual Kalshi ticker format.
        # Example: KXETH15M-26APR192030-30 is VALID from Kalshi catalog
        #          KXETH-15M-26APR192030-30 is INVALID (normalization incorrectly adds dash)
        ticker = order.market_id

        # Pre-send validation: verify ticker exists in catalog to prevent 404s
        valid, error_msg = await _validate_ticker_exists(ticker)
        if not valid:
            logger.error(f"[KALSHI_PRE_SEND_VALIDATION] Rejecting order for invalid ticker: {error_msg}")
            return OperationResult.fail(
                error_msg or f"Invalid ticker: {ticker}",
                latency_ms=0.0,
                retries=0,
            )

        outcome = order.outcome_id or "yes"
        kalshi_order: Dict[str, Any] = {
            "ticker": ticker,
            "action": order.side,           # "buy" or "sell"
            "side": outcome,                # "yes" or "no"
            "count": int(order.size),
            "type": order.order_type,       # "limit" or "market"
            "client_order_id": order.client_order_id or f"merid_{datetime.now(timezone.utc).timestamp()}",
        }

        if order.order_type == "limit" and order.price:
            # Kalshi uses {side}_price: yes_price or no_price (cents, integer)
            kalshi_order[f"{outcome}_price"] = int(order.price * 100)

        # Kalshi Trade API v2: enum is good_till_canceled | immediate_or_cancel | fill_or_kill
        kalshi_order["time_in_force"] = merid_time_in_force_to_kalshi_api(
            getattr(order, "time_in_force", None) or "GTC"
        )
        
        # Add optional STP and order group
        if order_group_id:
            kalshi_order["order_group_id"] = order_group_id
        if self_trade_prevention_type:
            kalshi_order["self_trade_prevention_type"] = self_trade_prevention_type
        
        # Add post_only if specified
        if getattr(order, "post_only", False):
            kalshi_order["post_only"] = True

        result = await self._request_with_resilience(
            "POST", "/portfolio/orders", json_data=kalshi_order, operation_name="place_order"
        )
        
        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
            )
        
        return OperationResult.ok(
            self._to_placed_order(result.data.get("order", result.data)),
            latency_ms=result.latency_ms,
            retries=result.retries,
        )
    
    async def cancel_order(self, order_id: str, market_id: Optional[str] = None) -> bool:
        """Cancel an order.
        
        Returns False on failure for backward compatibility.
        Use cancel_order_result() for explicit error handling.
        """
        result = await self.cancel_order_result(order_id, market_id)
        return result.success
    
    async def cancel_order_result(
        self, order_id: str, market_id: Optional[str] = None
    ) -> OperationResult[bool]:
        """Cancel order with explicit result.

        Uses Kalshi's cancel endpoint: POST /portfolio/orders/{order_id}/cancel
        """
        result = await self._request_with_resilience(
            "POST",
            f"/portfolio/orders/{order_id}/cancel",
            json_data={"order_id": order_id},
            operation_name=f"cancel_order({order_id})",
        )

        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
            )

        return OperationResult.ok(
            True,
            latency_ms=result.latency_ms,
            retries=result.retries,
        )

    async def batch_cancel_orders(self, order_ids: List[str]) -> Dict[str, Any]:
        """Batch cancel up to 20 orders in a single API call.

        Kalshi supports batch cancel via POST /portfolio/orders/batch_cancel
        with a list of order_ids. This is more efficient than individual cancels
        and reduces rate limit pressure.

        Args:
            order_ids: List of order IDs to cancel (max 20 per Kalshi limits)

        Returns:
            Dict with canceled, failed, and not_found order IDs
        """
        if not order_ids:
            return {"canceled": [], "failed": [], "not_found": [], "message": "No orders provided"}

        if len(order_ids) > 20:
            logger.warning(f"batch_cancel_orders: Truncating to 20 orders (received {len(order_ids)})")
            order_ids = order_ids[:20]

        result = await self._request_with_resilience(
            "POST",
            "/portfolio/orders/batch_cancel",
            json_data={"order_ids": order_ids},
            operation_name=f"batch_cancel_orders({len(order_ids)})",
        )

        if not result.success:
            logger.warning(f"Batch cancel failed: {result.error}")
            return {
                "canceled": [],
                "failed": order_ids,
                "not_found": [],
                "error": str(result.error),
            }

        # Parse response - Kalshi returns canceled orders in the response
        data = result.data or {}
        canceled = data.get("canceled", [])
        failed = data.get("failed", [])
        not_found = data.get("not_found", [])

        # Determine which orders weren't in the response
        canceled_set = set(canceled)
        failed_set = set(failed)
        not_found_set = set(not_found)

        # Any input order not in response is considered failed
        missing = set(order_ids) - canceled_set - failed_set - not_found_set
        if missing:
            failed.extend(list(missing))

        return {
            "canceled": canceled,
            "failed": failed,
            "not_found": not_found,
            "count": len(canceled),
        }

    async def batch_place_orders(
        self,
        order_specs: List[Dict[str, Any]],
    ) -> OperationResult[List[Dict[str, Any]]]:
        """Batch place up to 20 orders in a single API call.

        Kalshi supports batch order creation via POST /portfolio/orders/batched
        with a list of orders. This is more efficient than individual orders
        and reduces rate limit pressure.

        Args:
            order_specs: List of order specification dicts, each containing:
                - ticker: Market ticker (required)
                - side: "yes" or "no" (required)
                - action: "buy" or "sell" (default: "buy")
                - type: "limit" or "market" (default: "limit")
                - count: Number of contracts (required)
                - yes_price: Price in cents for yes side (optional)
                - no_price: Price in cents for no side (optional)
                - subaccount: Subaccount number (optional)
                - time_in_force: API v2 (good_till_canceled, …) or legacy gtc/ioc/fok
                - client_order_id: Optional client order ID (auto-generated if not provided)
                - order_group_id: Optional order group ID for aggregate limits
                - self_trade_prevention_type: Optional STP mode (e.g., "taker_at_cross")

        Returns:
            OperationResult with list of created order responses

        Raises:
            ValueError: If more than 20 orders provided
        """
        if not order_specs:
            return OperationResult.ok(
                [],
                latency_ms=0.0,
                retries=0,
            )

        if len(order_specs) > 20:
            raise ValueError(f"Max 20 orders per batch, received {len(order_specs)}")

        # Build order payloads
        body_orders = []
        for spec in order_specs:
            order = {
                "client_order_id": spec.get("client_order_id", str(uuid.uuid4())),
                "ticker": spec["ticker"],
                "side": spec["side"],
                "action": spec.get("action", "buy"),
                "type": spec.get("type", "limit"),
                "count": spec["count"],
            }

            if "yes_price" in spec:
                order["yes_price"] = spec["yes_price"]
            if "no_price" in spec:
                order["no_price"] = spec["no_price"]
            if "subaccount" in spec:
                order["subaccount_number"] = spec["subaccount"]
            if "time_in_force" in spec:
                order["time_in_force"] = merid_time_in_force_to_kalshi_api(
                    spec["time_in_force"]
                )
            if "post_only" in spec:
                order["post_only"] = spec["post_only"]
            if "reduce_only" in spec:
                order["reduce_only"] = spec["reduce_only"]
            if "order_group_id" in spec:
                order["order_group_id"] = spec["order_group_id"]
            if "self_trade_prevention_type" in spec:
                order["self_trade_prevention_type"] = spec["self_trade_prevention_type"]

            body_orders.append(order)

        payload = {"orders": body_orders}

        result = await self._request_with_resilience(
            "POST",
            "/portfolio/orders/batched",
            json_data=payload,
            operation_name=f"batch_place_orders({len(order_specs)})",
        )

        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
            )

        data = result.data or {}
        orders = data.get("orders", [])

        return OperationResult.ok(
            orders,
            latency_ms=result.latency_ms,
            retries=result.retries,
        )

    async def amend_order(
        self,
        order_id: str,
        yes_price: Optional[int] = None,
        no_price: Optional[int] = None,
        new_count: Optional[int] = None,
    ) -> OperationResult[Dict[str, Any]]:
        """Amend an existing order's price and/or quantity.

        Uses Kalshi's amend endpoint: POST /portfolio/orders/{order_id}/amend
        Only resting orders can be amended.

        Args:
            order_id: The order ID to amend
            yes_price: New yes price in cents (optional)
            no_price: New no price in cents (optional)
            new_count: New contract count (optional)

        Returns:
            OperationResult with amended order details

        Raises:
            ValueError: If no amendments provided
        """
        body: Dict[str, Any] = {}
        if yes_price is not None:
            body["yes_price"] = yes_price
        if no_price is not None:
            body["no_price"] = no_price
        if new_count is not None:
            body["count"] = str(new_count)

        if not body:
            raise ValueError("Nothing to amend - provide yes_price, no_price, or new_count")

        result = await self._request_with_resilience(
            "POST",
            f"/portfolio/orders/{order_id}/amend",
            json_data=body,
            operation_name=f"amend_order({order_id})",
        )

        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
            )

        data = result.data or {}
        order = data.get("order", data)

        return OperationResult.ok(
            order,
            latency_ms=result.latency_ms,
            retries=result.retries,
        )

    async def amend_order_and_validate(
        self,
        order_id: str,
        expected_ticker: str,
        yes_price: Optional[int] = None,
        no_price: Optional[int] = None,
        new_count: Optional[int] = None,
        validate_status: bool = True,
    ) -> Dict[str, Any]:
        """Amend an order and validate the response matches intent.

        Ensures the amended order reflects the requested changes and
        validates critical fields like order_id, ticker, and status.

        Args:
            order_id: The order ID to amend
            expected_ticker: Expected ticker for validation
            yes_price: New yes price in cents (optional)
            no_price: New no price in cents (optional)
            new_count: New contract count (optional)
            validate_status: If True, ensure status remains "resting"

        Returns:
            Dict containing the validated order data

        Raises:
            KalshiValidationError: If response doesn't match expected values
        """
        from merid.event_venues.kalshi.order_errors import KalshiValidationError

        # Perform the amend
        result = await self.amend_order(
            order_id=order_id,
            yes_price=yes_price,
            no_price=no_price,
            new_count=new_count,
        )

        if not result.success:
            raise KalshiValidationError(
                f"Amend failed: {result.error}",
                field="amend_operation",
            )

        new_order = result.data
        if not isinstance(new_order, dict):
            raise KalshiValidationError(
                "Invalid order response format",
                field="response_format",
            )

        # Validate order_id matches
        if new_order.get("order_id") != order_id:
            raise KalshiValidationError(
                f"Order ID mismatch: expected {order_id}, got {new_order.get('order_id')}",
                field="order_id",
            )

        # Validate ticker matches
        if new_order.get("ticker") != expected_ticker:
            raise KalshiValidationError(
                f"Ticker mismatch: expected {expected_ticker}, got {new_order.get('ticker')}",
                field="ticker",
            )

        # Validate price updates
        if yes_price is not None:
            actual_yes = new_order.get("yes_price")
            if actual_yes != yes_price:
                raise KalshiValidationError(
                    f"yes_price not updated: expected {yes_price}, got {actual_yes}",
                    field="yes_price",
                )

        if no_price is not None:
            actual_no = new_order.get("no_price")
            if actual_no != no_price:
                raise KalshiValidationError(
                    f"no_price not updated: expected {no_price}, got {actual_no}",
                    field="no_price",
                )

        # Validate count update via remaining_count
        if new_count is not None:
            remaining = new_order.get("remaining_count")
            if str(remaining) != str(new_count):
                raise KalshiValidationError(
                    f"remaining_count mismatch: expected {new_count}, got {remaining}",
                    field="remaining_count",
                )

        # Validate status
        if validate_status and new_order.get("status") != "resting":
            raise KalshiValidationError(
                f"Unexpected status after amend: {new_order.get('status')}",
                field="status",
            )

        return new_order

    async def batch_amend_orders(
        self,
        amends: List[Dict[str, Any]],
        delay_ms: float = 100.0,
    ) -> List[Dict[str, Any]]:
        """Amend multiple orders sequentially with rate limiting.

        There is no dedicated batch amend endpoint, so we fan out
        individual amend calls with optional delay between requests.

        Args:
            amends: List of amend specifications, each containing:
                - order_id: Order ID to amend (required)
                - expected_ticker: Expected ticker for validation (required)
                - yes_price: New yes price in cents (optional)
                - no_price: New no price in cents (optional)
                - new_count: New contract count (optional)
            delay_ms: Milliseconds to wait between amends (default 100ms)

        Returns:
            List of amended order responses

        Note:
            Each amend counts against your per-second order limit.
            The client-side rate limiter should ensure compliance.
        """
        results = []

        for i, spec in enumerate(amends):
            order_id = spec["order_id"]
            expected_ticker = spec["expected_ticker"]
            yes_price = spec.get("yes_price")
            no_price = spec.get("no_price")
            new_count = spec.get("new_count")

            try:
                updated = await self.amend_order_and_validate(
                    order_id=order_id,
                    expected_ticker=expected_ticker,
                    yes_price=yes_price,
                    no_price=no_price,
                    new_count=new_count,
                )
                results.append({
                    "success": True,
                    "order_id": order_id,
                    "order": updated,
                })
            except Exception as e:
                # Classify error for better handling
                error_str = str(e).lower()
                error_code = None
                remediation = None

                if "invalid_order_size" in error_str:
                    error_code = "invalid_order_size"
                    remediation = "clamp count to remaining quantity"
                elif "available_balance_too_low" in error_str or "insufficient" in error_str:
                    error_code = "available_balance_too_low"
                    remediation = "reduce order size"
                elif "post only cross" in error_str or "post-only" in error_str:
                    error_code = "post_only_cross"
                    remediation = "back off price and resubmit"
                elif "unknown order" in error_str or "too late" in error_str:
                    error_code = "order_not_found"
                    remediation = "order already filled or canceled"
                elif "ticker mismatch" in error_str:
                    error_code = "ticker_mismatch"
                    remediation = "verify order metadata"

                results.append({
                    "success": False,
                    "order_id": order_id,
                    "error": str(e),
                    "error_code": error_code,
                    "remediation": remediation,
                })

            # Rate limiting delay between amends (except after last)
            if i < len(amends) - 1 and delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)

        return results

    async def safe_decrease_order(
        self,
        order: Dict[str, Any],
        reduce_by: Optional[int] = None,
        reduce_to: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Safely decrease an order with pre-validation and error handling.

        Pre-validates parameters against order state and handles common
        error scenarios gracefully.

        Args:
            order: Order dict with at least order_id, remaining_count, ticker
            reduce_by: Number of contracts to reduce by (relative)
            reduce_to: Target remaining contract count (absolute)

        Returns:
            Decreased order dict, or original order if no-op

        Raises:
            KalshiValidationError: For invalid parameters
            KalshiOrderError: For API-level errors (order not found, etc.)
        """
        from merid.event_venues.kalshi.order_errors import KalshiValidationError, KalshiOrderError

        order_id = order.get("order_id")
        remaining = order.get("remaining_count", 0)

        # Nothing to do
        if remaining <= 0:
            return order

        # Validate parameters
        if reduce_by is None and reduce_to is None:
            raise KalshiValidationError(
                "Must provide reduce_by or reduce_to",
                field="reduce_params",
            )

        if reduce_by is not None and reduce_to is not None:
            raise KalshiValidationError(
                "Cannot specify both reduce_by and reduce_to",
                field="reduce_params",
            )

        # Adjust reduce_by if exceeds remaining
        if reduce_by is not None:
            if reduce_by > remaining:
                reduce_by = remaining
            if reduce_by <= 0:
                return order  # No-op

        # Adjust reduce_to if out of bounds
        if reduce_to is not None:
            if reduce_to < 0:
                reduce_to = 0
            if reduce_to >= remaining:
                # Already at or below target
                return order

        try:
            result = await self.decrease_order(
                order_id=order_id,
                reduce_by=reduce_by,
                reduce_to=reduce_to,
            )

            if not result.success:
                # Classify error
                error_str = str(result.error).lower()
                if "unknown order" in error_str or "too late" in error_str:
                    raise KalshiOrderError(
                        f"Order {order_id} not found or already filled/canceled",
                        order_id=order_id,
                    )
                raise KalshiOrderError(
                    f"Decrease failed: {result.error}",
                    order_id=order_id,
                )

            return result.data

        except Exception as e:
            # Re-raise if already our exception type
            if isinstance(e, (KalshiValidationError, KalshiOrderError)):
                raise
            # Wrap unexpected errors
            raise KalshiOrderError(
                f"Unexpected error during decrease: {e}",
                order_id=order_id,
            )

    async def decrease_order(
        self,
        order_id: str,
        reduce_by: Optional[int] = None,
        reduce_to: Optional[int] = None,
    ) -> OperationResult[Dict[str, Any]]:
        """Decrease a resting order's contract count.

        Uses Kalshi's decrease endpoint: POST /portfolio/orders/{order_id}/decrease
        Reduces contracts by reduce_by or to reduce_to (mutually exclusive).

        Args:
            order_id: The order ID to decrease
            reduce_by: Number of contracts to reduce by (relative)
            reduce_to: Target remaining contract count (absolute)

        Returns:
            OperationResult with updated order details

        Raises:
            ValueError: If neither reduce_by nor reduce_to provided, or both provided
        """
        if reduce_by is not None and reduce_to is not None:
            raise ValueError("Cannot specify both reduce_by and reduce_to - choose one")
        if reduce_by is None and reduce_to is None:
            raise ValueError("Must provide reduce_by or reduce_to")

        body: Dict[str, Any] = {}
        if reduce_by is not None:
            body["reduce_by"] = reduce_by
        if reduce_to is not None:
            body["reduce_to"] = reduce_to

        result = await self._request_with_resilience(
            "POST",
            f"/portfolio/orders/{order_id}/decrease",
            json_data=body,
            operation_name=f"decrease_order({order_id})",
        )

        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
            )

        data = result.data or {}
        order = data.get("order", data)

        return OperationResult.ok(
            order,
            latency_ms=result.latency_ms,
            retries=result.retries,
        )

    async def create_order_group(
        self,
        name: str,
        max_cost_cents: int,
    ) -> OperationResult[str]:
        """Create an order group for aggregate risk management.

        Order groups allow setting aggregate limits and triggers across
        multiple orders. Assign orders via order_group_id field.

        Args:
            name: Group name
            max_cost_cents: Maximum cost in cents for this group

        Returns:
            OperationResult containing the new order_group_id
        """
        body = {
            "name": name,
            "max_cost": max_cost_cents,
        }

        result = await self._request_with_resilience(
            "POST",
            "/portfolio/order_groups",
            json_data=body,
            operation_name=f"create_order_group({name})",
        )

        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
            )

        data = result.data or {}
        group_id = data.get("order_group_id", data.get("id", ""))

        return OperationResult.ok(
            group_id,
            latency_ms=result.latency_ms,
            retries=result.retries,
        )

    async def set_order_group_limit(
        self,
        group_id: str,
        max_cost_cents: Optional[int] = None,
        contracts_limit: Optional[int] = None,
        contracts_limit_fp: Optional[str] = None,
    ) -> OperationResult[Dict[str, Any]]:
        """Update the cost/contracts limit for an order group.

        Args:
            group_id: Order group ID
            max_cost_cents: New maximum cost in cents (legacy param)
            contracts_limit: Contracts limit for rolling 15-second window
            contracts_limit_fp: Contracts limit as string (e.g., "10.00")

        Returns:
            OperationResult with updated group details

        Raises:
            ValueError: If no limit parameters provided or if both contracts_limit
                       and contracts_limit_fp provided but don't match
        """
        # Validate at least one limit is provided
        if max_cost_cents is None and contracts_limit is None and contracts_limit_fp is None:
            raise ValueError("Provide max_cost_cents, contracts_limit, or contracts_limit_fp")

        # Validate contracts_limit range
        if contracts_limit is not None:
            if contracts_limit < 1:
                raise ValueError("contracts_limit must be >= 1")
            if contracts_limit > 1_000_000:
                raise ValueError("contracts_limit must be <= 1,000,000")

        # Build request body
        body: Dict[str, Any] = {}
        if max_cost_cents is not None:
            body["max_cost"] = max_cost_cents
        if contracts_limit is not None:
            body["contracts_limit"] = contracts_limit
        if contracts_limit_fp is not None:
            body["contracts_limit_fp"] = contracts_limit_fp

        result = await self._request_with_resilience(
            "PUT",
            f"/portfolio/order_groups/{group_id}/limit",
            json_data=body,
            operation_name=f"set_order_group_limit({group_id})",
        )

        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
            )

        return OperationResult.ok(
            result.data or {},
            latency_ms=result.latency_ms,
            retries=result.retries,
        )

    async def safe_update_group_limit(
        self,
        group_id: str,
        new_limit: int,
    ) -> OperationResult[Dict[str, Any]]:
        """Safely update order group contracts limit with validation.

        Clamps limit to valid range [1, 1_000_000] before updating.

        Args:
            group_id: Order group ID
            new_limit: Desired contracts limit

        Returns:
            OperationResult with updated group details
        """
        # Clamp to valid range
        clamped_limit = max(1, min(new_limit, 1_000_000))
        if clamped_limit != new_limit:
            logger.warning(f"Clamped contracts_limit from {new_limit} to {clamped_limit}")

        return await self.set_order_group_limit(
            group_id=group_id,
            contracts_limit=clamped_limit,
        )

    async def trigger_order_group(
        self,
        group_id: str,
    ) -> OperationResult[Dict[str, Any]]:
        """Trigger an order group (e.g., for OCO or conditional orders).

        Args:
            group_id: Order group ID to trigger

        Returns:
            OperationResult with trigger result
        """
        result = await self._request_with_resilience(
            "PUT",
            f"/portfolio/order_groups/{group_id}/trigger",
            operation_name=f"trigger_order_group({group_id})",
        )

        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
            )

        return OperationResult.ok(
            result.data or {},
            latency_ms=result.latency_ms,
            retries=result.retries,
        )

    async def get_order_groups(
        self,
        limit: int = 200,
    ) -> OperationResult[List[Dict[str, Any]]]:
        """Get all order groups with pagination.

        Args:
            limit: Maximum groups per page

        Returns:
            OperationResult with list of order group dicts
        """
        all_groups: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        total_latency = 0.0
        total_retries = 0
        max_pages = 10

        for page in range(max_pages):
            params: Dict[str, Any] = {"limit": limit}
            if cursor:
                params["cursor"] = cursor

            result = await self._request_with_resilience(
                "GET",
                "/portfolio/order_groups",
                params=params,
                operation_name="get_order_groups",
            )

            total_latency += result.latency_ms or 0
            total_retries += result.retries or 0

            if not result.success:
                if all_groups:
                    logger.warning(f"get_order_groups: Partial failure on page {page}, returning {len(all_groups)} groups")
                    break
                return OperationResult.fail(
                    result.error,
                    latency_ms=total_latency,
                    retries=total_retries,
                )

            data = result.data or {}
            groups = data.get("order_groups", [])
            all_groups.extend(groups)

            cursor = data.get("cursor")
            if not cursor:
                break

            if page >= max_pages - 1:
                logger.warning(f"get_order_groups: Hit max_pages limit ({max_pages}), returning {len(all_groups)} groups")
                break

        return OperationResult.ok(
            all_groups,
            latency_ms=total_latency,
            retries=total_retries,
        )

    async def get_order_group(
        self,
        group_id: str,
    ) -> OperationResult[Dict[str, Any]]:
        """Get a single order group by ID.

        Args:
            group_id: Order group ID

        Returns:
            OperationResult with order group details
        """
        result = await self._request_with_resilience(
            "GET",
            f"/portfolio/order_groups/{group_id}",
            operation_name=f"get_order_group({group_id})",
        )

        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
            )

        return OperationResult.ok(
            result.data or {},
            latency_ms=result.latency_ms,
            retries=result.retries,
        )

    async def delete_order_group(
        self,
        group_id: str,
    ) -> OperationResult[bool]:
        """Delete an order group and cancel all orders within it.

        Args:
            group_id: Order group ID to delete

        Returns:
            OperationResult with True if deleted, False if not found

        Note:
            404 is treated as "already deleted/unknown" and returns False
            without error. 200/204 returns True.
        """
        from merid.event_venues.kalshi.order_errors import KalshiOrderGroupDeleteError

        result = await self._request_with_resilience(
            "DELETE",
            f"/portfolio/order_groups/{group_id}",
            operation_name=f"delete_order_group({group_id})",
        )

        if result.success:
            # 200 or 204 - success
            return OperationResult.ok(
                True,
                latency_ms=result.latency_ms,
                retries=result.retries,
            )

        # Check for 404 - treat as already deleted
        error_str = str(result.error).lower()
        if "404" in error_str or "not found" in error_str:
            return OperationResult.ok(
                False,
                latency_ms=result.latency_ms,
                retries=result.retries,
            )

        # Other errors - fail
        return OperationResult.fail(
            KalshiOrderGroupDeleteError(
                f"Failed to delete order group {group_id}: {result.error}",
                group_id=group_id,
            ),
            latency_ms=result.latency_ms,
            retries=result.retries,
        )

    async def reset_order_group(
        self,
        group_id: str,
        new_max_cost_cents: Optional[int] = None,
    ) -> OperationResult[Dict[str, Any]]:
        """Reset an order group by updating its cost limit.

        This effectively clears/resets the group for reuse. If no new cost
        is specified, sets max_cost to 0 (disabled).

        Args:
            group_id: Order group ID to reset
            new_max_cost_cents: New maximum cost in cents (None = 0)

        Returns:
            OperationResult with updated group details
        """
        max_cost = new_max_cost_cents if new_max_cost_cents is not None else 0
        return await self.set_order_group_limit(group_id, max_cost)

    async def reset_order_group_endpoint(
        self,
        group_id: str,
    ) -> OperationResult[bool]:
        """Reset order group matched contracts counter via dedicated endpoint.

        Uses Kalshi's reset endpoint: PUT /portfolio/order_groups/{group_id}/reset
        This resets the matched contracts counter so the group can trade again.

        Args:
            group_id: Order group ID to reset

        Returns:
            OperationResult with True if reset successful
        """
        result = await self._request_with_resilience(
            "PUT",
            f"/portfolio/order_groups/{group_id}/reset",
            operation_name=f"reset_order_group_endpoint({group_id})",
        )

        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
            )

        # Empty body on success (200/204)
        return OperationResult.ok(
            True,
            latency_ms=result.latency_ms,
            retries=result.retries,
        )

    async def delete_order_group_and_sync(
        self,
        group_id: str,
    ) -> Dict[str, Any]:
        """Delete order group and sync portfolio state.

        Deletes the group (cancels all orders within it), then fetches
        current orders and positions to ensure local state matches.

        Args:
            group_id: Order group ID to delete

        Returns:
            Dict with deleted status, orders, and positions
        """
        # Delete the group
        delete_result = await self.delete_order_group(group_id)

        if not delete_result.success:
            return {
                "deleted": False,
                "error": str(delete_result.error),
                "orders": [],
                "positions": [],
            }

        # Sync portfolio state
        orders_result = await self.get_open_orders_result()
        positions_result = await self.get_positions_result()

        return {
            "deleted": delete_result.data,  # True if deleted, False if not found
            "orders": orders_result.unwrap_or([]),
            "positions": positions_result.unwrap_or([]),
        }

    async def get_order(self, order_id: str, market_id: Optional[str] = None) -> Optional[PlacedOrder]:
        """Get order status.
        
        Returns None on failure for backward compatibility.
        Use get_order_result() for explicit error handling.
        """
        result = await self.get_order_result(order_id, market_id)
        return result.unwrap_or(None)
    
    async def get_order_result(
        self, order_id: str, market_id: Optional[str] = None
    ) -> OperationResult[Optional[PlacedOrder]]:
        """Get order status with explicit result."""
        result = await self._request_with_resilience(
            "GET", f"/portfolio/orders/{order_id}", operation_name=f"get_order({order_id})"
        )

        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
            )

        return OperationResult.ok(
            self._to_placed_order(result.data.get("order", result.data)),
            latency_ms=result.latency_ms,
            retries=result.retries,
        )
    
    async def get_order_by_client_id_result(
        self, client_order_id: str, market_id: Optional[str] = None
    ) -> OperationResult[Optional[PlacedOrder]]:
        """Get order by client_order_id with explicit result.
        
        Used for idempotency: when we receive a duplicate error, we can look up
        the order to confirm it was accepted and get its current state.
        
        Kalshi API supports filtering by client_order_id via query parameter.
        """
        params: Dict[str, Any] = {"client_order_id": client_order_id, "limit": 10}
        if market_id:
            params["ticker"] = market_id
        
        result = await self._request_with_resilience(
            "GET", "/portfolio/orders", 
            params=params, 
            operation_name=f"get_order_by_client_id({client_order_id[:16]}...)"
        )
        
        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
            )
        
        orders = result.data.get("orders", [])
        if orders:
            # Return the first matching order
            return OperationResult.ok(
                self._to_placed_order(orders[0]),
                latency_ms=result.latency_ms,
                retries=result.retries,
            )
        
        # Order not found - might be old/canceled, return None but success
        return OperationResult.ok(
            None,
            latency_ms=result.latency_ms,
            retries=result.retries,
        )
    
    async def get_open_orders(self, market_id: Optional[str] = None) -> List[PlacedOrder]:
        """Get open orders. Returns empty list on failure."""
        result = await self.get_open_orders_result(market_id)
        return result.unwrap_or([])
    
    async def get_open_orders_result(
        self, market_id: Optional[str] = None
    ) -> OperationResult[List[PlacedOrder]]:
        """Get open orders with explicit result.

        Supports cursor-based pagination to fetch all open orders across multiple pages.
        This is critical for active trading accounts with many orders.
        """
        all_orders: List[PlacedOrder] = []
        cursor: Optional[str] = None
        total_latency = 0.0
        total_retries = 0
        max_pages = 10  # Safety limit to prevent runaway pagination

        for page in range(max_pages):
            params: Dict[str, Any] = {"status": "open", "limit": 100}
            if market_id:
                params["ticker"] = market_id
            if cursor:
                params["cursor"] = cursor

            result = await self._request_with_resilience(
                "GET", "/portfolio/orders", params=params, operation_name="get_open_orders"
            )

            total_latency += result.latency_ms or 0
            total_retries += result.retries or 0

            if not result.success:
                if all_orders:
                    # Return what we have so far on partial failure
                    logger.warning(f"get_open_orders: Partial failure on page {page}, returning {len(all_orders)} orders")
                    break
                return OperationResult.fail(
                    result.error,
                    latency_ms=total_latency,
                    retries=total_retries,
                )

            for order_data in result.data.get("orders", []):
                order = self._to_placed_order(order_data)
                if order:
                    all_orders.append(order)

            cursor = result.data.get("cursor")
            if not cursor:
                break

            if page >= max_pages - 1:
                logger.warning(f"get_open_orders: Hit max_pages limit ({max_pages}), returning {len(all_orders)} orders")
                break

        return OperationResult.ok(
            all_orders,
            latency_ms=total_latency,
            retries=total_retries,
        )
    
    # ------------------------------------------------------------------------
    # Account Data
    # ------------------------------------------------------------------------
    
    async def get_positions(self) -> List[VenuePosition]:
        """Get positions. Returns empty list on failure."""
        result = await self.get_positions_result()
        return result.unwrap_or([])
    
    async def get_positions_result(self) -> OperationResult[List[VenuePosition]]:
        """Get positions with explicit result.

        Supports cursor-based pagination to fetch all positions across multiple pages.
        Handles both market_positions and event_positions from Kalshi API.
        This is critical for accounts with many open positions.
        """
        all_positions: List[VenuePosition] = []
        cursor: Optional[str] = None
        total_latency = 0.0
        total_retries = 0
        max_pages = 10  # Safety limit to prevent runaway pagination

        for page in range(max_pages):
            params: Dict[str, Any] = {"limit": 100}
            if cursor:
                params["cursor"] = cursor

            result = await self._request_with_resilience(
                "GET", "/portfolio/positions", params=params, operation_name="get_positions"
            )

            total_latency += result.latency_ms or 0
            total_retries += result.retries or 0

            if not result.success:
                if all_positions:
                    # Return what we have so far on partial failure
                    logger.warning(f"get_positions: Partial failure on page {page}, returning {len(all_positions)} positions")
                    break
                return OperationResult.fail(
                    result.error,
                    latency_ms=total_latency,
                    retries=total_retries,
                )

            # Parse market_positions (if present)
            for pos_data in result.data.get("market_positions", []):
                position = self._parse_position(pos_data)
                if position:
                    all_positions.append(self._to_venue_position(position))

            # Parse event_positions (if present)
            for pos_data in result.data.get("event_positions", []):
                position = self._parse_position(pos_data)
                if position:
                    all_positions.append(self._to_venue_position(position))

            # Fallback to legacy "positions" field if present
            if "positions" in result.data:
                for pos_data in result.data.get("positions", []):
                    position = self._parse_position(pos_data)
                    if position:
                        all_positions.append(self._to_venue_position(position))

            cursor = result.data.get("cursor")
            if not cursor:
                break

            # P1-HARDENING: Yield between pages to prevent event loop blocking
            await asyncio.sleep(0)

            if page >= max_pages - 1:
                logger.warning(f"get_positions: Hit max_pages limit ({max_pages}), returning {len(all_positions)} positions")
                break

        return OperationResult.ok(
            all_positions,
            latency_ms=total_latency,
            retries=total_retries,
        )
    
    async def get_trades(self, limit: int = 100) -> List[VenueTrade]:
        """Get trade history. Returns empty list on failure."""
        result = await self.get_trades_result(limit)
        return result.unwrap_or([])
    
    async def get_trades_result(self, limit: int = 100) -> OperationResult[List[VenueTrade]]:
        """Get trade history with explicit result.

        Supports cursor-based pagination to fetch all trades up to the limit.
        Uses 100-item pages with cursor chaining.
        """
        all_trades: List[VenueTrade] = []
        cursor: Optional[str] = None
        total_latency = 0.0
        total_retries = 0
        remaining = limit
        max_pages = max(1, (limit + 99) // 100)  # Ceiling division

        for page in range(max_pages):
            page_size = min(remaining, 100)
            if page_size <= 0:
                break

            params: Dict[str, Any] = {"limit": page_size}
            if cursor:
                params["cursor"] = cursor

            result = await self._request_with_resilience(
                "GET", "/portfolio/trades", params=params, operation_name="get_trades"
            )

            total_latency += result.latency_ms or 0
            total_retries += result.retries or 0

            if not result.success:
                if all_trades:
                    # Return what we have so far on partial failure
                    logger.warning(f"get_trades: Partial failure on page {page}, returning {len(all_trades)} trades")
                    break
                return OperationResult.fail(
                    result.error,
                    latency_ms=total_latency,
                    retries=total_retries,
                )

            for trade_data in result.data.get("trades", []):
                trade = self._parse_trade(trade_data)
                if trade:
                    all_trades.append(self._to_venue_trade(trade))
                    remaining -= 1

            cursor = result.data.get("cursor")
            if not cursor or remaining <= 0:
                break

        return OperationResult.ok(
            all_trades[:limit],
            latency_ms=total_latency,
            retries=total_retries,
        )
    
    async def get_balance(self) -> Dict[str, Decimal]:
        """Get account balance. Returns zeros on failure."""
        result = await self.get_balance_result()
        return result.unwrap_or({"USD": Decimal("0"), "locked": Decimal("0")})
    
    async def get_balance_result(self) -> OperationResult[Dict[str, Decimal]]:
        """Get account balance with explicit result."""
        result = await self._request_with_resilience(
            "GET", "/portfolio/balance", operation_name="get_balance"
        )
        
        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
            )
        
        raw = result.data or {}
        balance_cents = raw.get("balance", 0)
        locked_cents = raw.get("locked_balance", 0)
        if isinstance(balance_cents, dict):
            locked_cents = balance_cents.get("locked_balance", 0)
            balance_cents = balance_cents.get("balance", 0)
        return OperationResult.ok(
            {
                "USD": Decimal(str(balance_cents)) / 100,
                "locked": Decimal(str(locked_cents)) / 100
            },
            latency_ms=result.latency_ms,
            retries=result.retries,
        )
    
    async def get_positions_aggregated_by_event(
        self, limit: int = 200
    ) -> OperationResult[Dict[str, Dict[str, Any]]]:
        """Aggregate portfolio positions by event_ticker.

        Fetches all positions via cursor pagination and aggregates
        event_positions and market_positions by their event_ticker,
        summing exposure, cost, PnL, and fees.

        Args:
            limit: Maximum number of positions to fetch per page

        Returns:
            OperationResult containing dict mapping event_ticker -> aggregated stats
        """
        from collections import defaultdict

        agg: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "event_exposure": Decimal("0"),
            "total_cost": Decimal("0"),
            "realized_pnl": Decimal("0"),
            "fees_paid": Decimal("0"),
            "market_positions": [],
        })

        cursor: Optional[str] = None
        total_latency = 0.0
        total_retries = 0
        max_pages = 10

        for page in range(max_pages):
            params: Dict[str, Any] = {"limit": limit}
            if cursor:
                params["cursor"] = cursor

            result = await self._request_with_resilience(
                "GET", "/portfolio/positions", params=params, operation_name="get_positions_aggregated"
            )

            total_latency += result.latency_ms or 0
            total_retries += result.retries or 0

            if not result.success:
                if agg:
                    logger.warning(f"get_positions_aggregated: Partial failure on page {page}")
                    break
                return OperationResult.fail(
                    result.error,
                    latency_ms=total_latency,
                    retries=total_retries,
                )

            data = result.data or {}

            # Aggregate event_positions (event-level exposure)
            for ep in data.get("event_positions", []):
                et = ep.get("event_ticker")
                if not et:
                    continue
                a = agg[et]
                a["event_exposure"] += Decimal(str(ep.get("event_exposure", 0)))
                a["total_cost"] += Decimal(str(ep.get("total_cost", 0)))
                a["realized_pnl"] += Decimal(str(ep.get("realized_pnl", 0)))
                a["fees_paid"] += Decimal(str(ep.get("fees_paid", 0)))

            # Aggregate market_positions (roll up into events if event_ticker present)
            for mp in data.get("market_positions", []):
                et = mp.get("event_ticker")
                if not et:
                    # Skip market positions without event context
                    continue
                a = agg[et]
                # Use market_exposure or fallback to position value
                exposure = mp.get("market_exposure") or (mp.get("count", 0) * mp.get("avg_price", 0) / 100)
                a["event_exposure"] += Decimal(str(exposure))
                a["total_cost"] += Decimal(str(mp.get("total_cost", 0)))
                a["realized_pnl"] += Decimal(str(mp.get("realized_pnl", 0)))
                a["fees_paid"] += Decimal(str(mp.get("fees_paid", 0)))
                a["market_positions"].append(mp.get("ticker", ""))

            cursor = data.get("cursor")
            if not cursor:
                break

        return OperationResult.ok(
            dict(agg),
            latency_ms=total_latency,
            retries=total_retries,
        )

    async def get_positions_with_filters(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 200,
    ) -> OperationResult[Dict[str, List[Dict[str, Any]]]]:
        """Get positions with optional filters and full pagination.

        Supports filters: event_ticker, market_ticker, subaccount_number,
        nonzero (position,total_traded)

        Args:
            filters: Optional dict of filter parameters
            limit: Maximum positions per page (max 200)

        Returns:
            OperationResult with market_positions and event_positions lists
        """
        filters = filters or {}
        all_market: List[Dict[str, Any]] = []
        all_event: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        total_latency = 0.0
        total_retries = 0
        max_pages = 50  # P0-4 FIX: Prevent unbounded pagination
        page = 0

        while page < max_pages:
            params: Dict[str, Any] = {"limit": min(limit, 200), **filters}
            if cursor:
                params["cursor"] = cursor

            result = await self._request_with_resilience(
                "GET", "/portfolio/positions", params=params, operation_name="get_positions_filtered"
            )

            total_latency += result.latency_ms or 0
            total_retries += result.retries or 0

            if not result.success:
                if all_market or all_event:
                    logger.warning(f"get_positions_filtered: Partial failure, returning collected data")
                    break
                return OperationResult.fail(
                    result.error,
                    latency_ms=total_latency,
                    retries=total_retries,
                )

            data = result.data or {}
            all_market.extend(data.get("market_positions", []))
            all_event.extend(data.get("event_positions", []))

            cursor = data.get("cursor")
            if not cursor:
                break
            page += 1

        if cursor:
            logger.warning(f"get_positions_filtered: Hit max_pages limit ({max_pages}), returning partial data")

        return OperationResult.ok(
            {"market_positions": all_market, "event_positions": all_event},
            latency_ms=total_latency,
            retries=total_retries,
        )

    async def get_subaccount_balances(
        self,
    ) -> OperationResult[Dict[str, Any]]:
        """Get all subaccount balances and aggregate totals.

        Returns:
            OperationResult with total_balance and by_subaccount breakdown
        """
        result = await self._request_with_resilience(
            "GET", "/portfolio/subaccounts/balances", operation_name="get_subaccount_balances"
        )

        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
            )

        data = result.data or {}
        balances = data.get("subaccount_balances", [])

        total_balance = Decimal("0")
        by_subaccount: Dict[str, Decimal] = {}

        for b in balances:
            sub = str(b.get("subaccount_number", "unknown"))
            # Balance may be in cents or decimal dollars depending on API version
            bal_raw = b.get("balance", 0)
            if isinstance(bal_raw, str):
                bal = Decimal(bal_raw)
            else:
                bal = Decimal(str(bal_raw)) / 100  # Assume cents if numeric
            by_subaccount[sub] = bal
            total_balance += bal

        return OperationResult.ok(
            {
                "total_balance": total_balance,
                "by_subaccount": by_subaccount,
                "subaccount_count": len(balances),
            },
            latency_ms=result.latency_ms,
            retries=result.retries,
        )

    async def get_fills(
        self,
        limit: int = 200,
        since_ts: Optional[int] = None,
    ) -> OperationResult[List[Dict[str, Any]]]:
        """Get paginated fills with optional time filter.

        Args:
            limit: Maximum fills per page
            since_ts: Optional minimum timestamp filter

        Returns:
            OperationResult containing list of fill dicts
        """
        all_fills: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        total_latency = 0.0
        total_retries = 0
        max_pages = 50  # P0-4 FIX: Prevent unbounded pagination
        page = 0

        while page < max_pages:
            params: Dict[str, Any] = {"limit": min(limit, 200)}
            if cursor:
                params["cursor"] = cursor
            if since_ts:
                params["min_ts"] = since_ts

            result = await self._request_with_resilience(
                "GET", "/portfolio/fills", params=params, operation_name="get_fills"
            )

            total_latency += result.latency_ms or 0
            total_retries += result.retries or 0

            if not result.success:
                if all_fills:
                    logger.warning(f"get_fills: Partial failure, returning {len(all_fills)} fills")
                    break
                return OperationResult.fail(
                    result.error,
                    latency_ms=total_latency,
                    retries=total_retries,
                )

            data = result.data or {}
            fills = data.get("fills", [])
            all_fills.extend(fills)

            cursor = data.get("cursor")
            if not cursor:
                break
            page += 1

        if cursor:
            logger.warning(f"get_fills: Hit max_pages limit ({max_pages}), returning partial data")

        return OperationResult.ok(
            all_fills,
            latency_ms=total_latency,
            retries=total_retries,
        )

    async def compute_portfolio_risk(
        self,
        filters: Optional[Dict[str, Any]] = None,
    ) -> OperationResult[Dict[str, Any]]:
        """Compute portfolio risk metrics from positions.

        Calculates per-event exposure, realized PnL, and fees.
        Returns aggregated risk metrics suitable for risk monitoring.

        Args:
            filters: Optional filters for position query (nonzero, etc.)

        Returns:
            OperationResult with by_event breakdown and totals
        """
        from collections import defaultdict

        # Get filtered positions
        pos_result = await self.get_positions_with_filters(filters)
        if not pos_result.success:
            return OperationResult.fail(
                pos_result.error,
                latency_ms=pos_result.latency_ms,
                retries=pos_result.retries,
            )

        pos_data = pos_result.data or {}
        risk: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "exposure": Decimal("0"),
            "realized_pnl": Decimal("0"),
            "fees": Decimal("0"),
        })

        # Aggregate event_positions
        for ep in pos_data.get("event_positions", []):
            et = ep.get("event_ticker")
            if not et:
                continue
            r = risk[et]
            r["exposure"] += Decimal(str(ep.get("event_exposure", 0)))
            r["realized_pnl"] += Decimal(str(ep.get("realized_pnl", 0)))
            r["fees"] += Decimal(str(ep.get("fees_paid", 0)))

        # Aggregate market_positions
        for mp in pos_data.get("market_positions", []):
            et = mp.get("event_ticker")
            if not et:
                continue
            r = risk[et]
            exposure = mp.get("market_exposure") or (mp.get("count", 0) * mp.get("avg_price", 0) / 100)
            r["exposure"] += Decimal(str(exposure))
            r["realized_pnl"] += Decimal(str(mp.get("realized_pnl", 0)))
            r["fees"] += Decimal(str(mp.get("fees_paid", 0)))

        # Calculate totals
        total_exposure = sum(v["exposure"] for v in risk.values())
        total_realized = sum(v["realized_pnl"] for v in risk.values())
        total_fees = sum(v["fees"] for v in risk.values())

        return OperationResult.ok(
            {
                "by_event": dict(risk),
                "total_exposure": total_exposure,
                "total_realized_pnl": total_realized,
                "total_fees": total_fees,
                "net_realized_pnl": total_realized - total_fees,
                "event_count": len(risk),
            },
            latency_ms=pos_result.latency_ms,
            retries=pos_result.retries,
        )

    async def compute_var(
        self,
        alpha: float = 0.1,
        filters: Optional[Dict[str, Any]] = None,
    ) -> OperationResult[Dict[str, Any]]:
        """Compute simple delta-style VaR from event positions.

        Uses per-event exposure and an assumed shock fraction (alpha) to
        estimate Value at Risk. This is a toy approximation - real VaR would
        use historical shocks or Monte Carlo simulation.

        Args:
            alpha: Shock fraction (e.g., 0.1 = 10% probability change)
            filters: Optional filters for position query

        Returns:
            OperationResult with VaR breakdown by event and portfolio total
        """
        # Get filtered positions
        pos_result = await self.get_positions_with_filters(
            filters={**(filters or {}), "nonzero": "position"}
        )
        if not pos_result.success:
            return OperationResult.fail(
                pos_result.error,
                latency_ms=pos_result.latency_ms,
                retries=pos_result.retries,
            )

        pos_data = pos_result.data or {}
        var_by_event: Dict[str, Decimal] = {}
        total_var = Decimal("0")

        for ep in pos_data.get("event_positions", []):
            exposure_cents = Decimal(str(ep.get("event_exposure", 0)))
            var_cents = abs(exposure_cents) * Decimal(str(alpha))
            et = ep.get("event_ticker")
            if et:
                var_by_event[et] = var_cents
                total_var += var_cents

        return OperationResult.ok(
            {
                "var_by_event_cents": var_by_event,
                "portfolio_var_cents": total_var,
                "portfolio_var_usd": total_var / 100,
                "alpha": alpha,
            },
            latency_ms=pos_result.latency_ms,
            retries=pos_result.retries,
        )

    async def compute_market_pnl(
        self,
        tickers: Optional[List[str]] = None,
    ) -> OperationResult[Dict[str, Any]]:
        """Compute market-level PnL using current mark prices.

        Fetches positions and current market prices to calculate mark-to-market
        PnL for each market position.

        Args:
            tickers: Optional list of tickers to filter (if None, uses all positions)

        Returns:
            OperationResult with total_pnl and per_market breakdown
        """
        # Get positions
        pos_result = await self.get_positions_with_filters(
            filters={"nonzero": "position"} if tickers is None else {"nonzero": "position"}
        )
        if not pos_result.success:
            return OperationResult.fail(
                pos_result.error,
                latency_ms=pos_result.latency_ms,
                retries=pos_result.retries,
            )

        pos_data = pos_result.data or {}
        mps = pos_data.get("market_positions", [])

        # Filter by tickers if specified
        if tickers:
            ticker_set = set(tickers)
            mps = [mp for mp in mps if mp.get("market_ticker") in ticker_set]

        if not mps:
            return OperationResult.ok(
                {"total_pnl_cents": Decimal("0"), "pnl_by_market_cents": {}},
                latency_ms=pos_result.latency_ms,
                retries=pos_result.retries,
            )

        # Fetch marks for all tickers
        market_tickers = [mp.get("market_ticker") for mp in mps if mp.get("market_ticker")]
        marks: Dict[str, int] = {}

        for ticker in market_tickers:
            market_result = await self._request_with_resilience(
                "GET", f"/markets/{ticker}", operation_name=f"get_market_for_pnl({ticker})"
            )
            if market_result.success:
                market_data = market_result.data or {}
                market = market_data.get("market", market_data)
                marks[ticker] = market.get("last_price", 0) or market.get("yes_price", 0)

        # Calculate PnL
        total_pnl = Decimal("0")
        pnl_by_market: Dict[str, Decimal] = {}

        for mp in mps:
            t = mp.get("market_ticker")
            side = mp.get("side", "yes")
            contracts = int(mp.get("contracts", 0) or mp.get("count", 0))
            avg_price = Decimal(str(mp.get("avg_price", 0)))
            mark = marks.get(t)

            if mark is None:
                continue

            mark_val = Decimal(mark) if side == "yes" else Decimal(100 - mark)
            pos_val = contracts * mark_val
            cost = contracts * avg_price
            pnl = pos_val - cost

            total_pnl += pnl
            pnl_by_market[t] = pnl

        return OperationResult.ok(
            {
                "total_pnl_cents": total_pnl,
                "total_pnl_usd": total_pnl / 100,
                "pnl_by_market_cents": pnl_by_market,
            },
            latency_ms=pos_result.latency_ms,
            retries=pos_result.retries,
        )

    async def aggregate_positions_by_subaccount(
        self,
        subaccount_range: range = range(0, 33),
    ) -> OperationResult[Dict[str, Any]]:
        """Aggregate positions by subaccount number.

        Iterates through subaccount numbers and aggregates exposure,
        cost, realized PnL, and fees for each.

        Args:
            subaccount_range: Range of subaccount numbers to query (default 0-32)

        Returns:
            OperationResult with aggregated data per subaccount
        """
        from collections import defaultdict

        result: Dict[int, Dict[str, Any]] = defaultdict(lambda: {
            "event_exposure": Decimal("0"),
            "total_cost": Decimal("0"),
            "realized_pnl": Decimal("0"),
            "fees_paid": Decimal("0"),
            "market_count": 0,
            "event_count": 0,
        })

        total_latency = 0.0
        total_retries = 0

        for sub in subaccount_range:
            pos_result = await self._request_with_resilience(
                "GET",
                "/portfolio/positions",
                params={"limit": 200, "nonzero": "position", "subaccount_number": sub},
                operation_name=f"get_positions_subaccount_{sub}",
            )

            total_latency += pos_result.latency_ms or 0
            total_retries += pos_result.retries or 0

            if not pos_result.success:
                continue

            data = pos_result.data or {}
            if not data.get("market_positions") and not data.get("event_positions"):
                continue

            agg = result[sub]
            for ep in data.get("event_positions", []):
                agg["event_exposure"] += Decimal(str(ep.get("event_exposure", 0)))
                agg["total_cost"] += Decimal(str(ep.get("total_cost", 0)))
                agg["realized_pnl"] += Decimal(str(ep.get("realized_pnl", 0)))
                agg["fees_paid"] += Decimal(str(ep.get("fees_paid", 0)))
                agg["event_count"] += 1

            for mp in data.get("market_positions", []):
                agg["total_cost"] += Decimal(str(mp.get("total_cost", 0)))
                agg["realized_pnl"] += Decimal(str(mp.get("realized_pnl", 0)))
                agg["fees_paid"] += Decimal(str(mp.get("fees_paid", 0)))
                agg["market_count"] += 1

        # Convert to regular dict with string keys for JSON serialization
        return OperationResult.ok(
            {str(k): dict(v) for k, v in result.items()},
            latency_ms=total_latency,
            retries=total_retries,
        )

    async def get_portfolio_summary(
        self, position_limit: int = 200
    ) -> OperationResult[Dict[str, Any]]:
        """Get comprehensive portfolio summary combining balance and positions.

        Fetches both balance and aggregated positions in parallel for efficiency,
        returning a unified view of account state.

        Args:
            position_limit: Maximum positions per page for aggregation

        Returns:
            OperationResult containing balance, portfolio_value, and by_event breakdown
        """
        from collections import defaultdict

        # Fetch balance and positions in parallel
        balance_result, positions_result = await asyncio.gather(
            self._request_with_resilience("GET", "/portfolio/balance", operation_name="get_balance"),
            self._request_with_resilience(
                "GET", "/portfolio/positions", params={"limit": position_limit}, operation_name="get_positions_summary"
            ),
        )

        # Process balance
        if not balance_result.success:
            return OperationResult.fail(
                balance_result.error,
                latency_ms=balance_result.latency_ms,
                retries=balance_result.retries,
            )

        bal_data = balance_result.data or {}
        balance_cents = bal_data.get("balance", 0)
        portfolio_value_cents = bal_data.get("portfolio_value", balance_cents)

        if isinstance(balance_cents, dict):
            balance_cents = balance_cents.get("balance", 0)
            portfolio_value_cents = bal_data.get("portfolio_value", balance_cents)

        # Process positions aggregation
        by_event: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "exposure": Decimal("0"),
            "realized_pnl": Decimal("0"),
            "fees": Decimal("0"),
        })

        if positions_result.success:
            pos_data = positions_result.data or {}

            # Aggregate event_positions
            for ep in pos_data.get("event_positions", []):
                et = ep.get("event_ticker")
                if not et:
                    continue
                a = by_event[et]
                a["exposure"] += Decimal(str(ep.get("event_exposure", 0)))
                a["realized_pnl"] += Decimal(str(ep.get("realized_pnl", 0)))
                a["fees"] += Decimal(str(ep.get("fees_paid", 0)))

            # Aggregate market_positions
            for mp in pos_data.get("market_positions", []):
                et = mp.get("event_ticker")
                if not et:
                    continue
                a = by_event[et]
                exposure = mp.get("market_exposure") or (mp.get("count", 0) * mp.get("avg_price", 0) / 100)
                a["exposure"] += Decimal(str(exposure))
                a["realized_pnl"] += Decimal(str(mp.get("realized_pnl", 0)))
                a["fees"] += Decimal(str(mp.get("fees_paid", 0)))

        total_latency = balance_result.latency_ms + (positions_result.latency_ms or 0)
        total_retries = balance_result.retries + (positions_result.retries or 0)

        return OperationResult.ok(
            {
                "balance": Decimal(str(balance_cents)) / 100,
                "portfolio_value": Decimal(str(portfolio_value_cents)) / 100,
                "by_event": dict(by_event),
            },
            latency_ms=total_latency,
            retries=total_retries,
        )

    # ------------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------------
    
    def _parse_market(self, data: Dict[str, Any]) -> Optional[KalshiMarket]:
        """Parse market from API response."""
        try:
            outcomes = []
            
            # Kalshi markets typically have Yes/No outcomes
            # Prefer last_price, then yes_price, then yes_ask
            yes_price_raw = data.get("last_price") or data.get("yes_price") or data.get("yes_ask", 0)
            yes_price = Decimal(str(yes_price_raw))
            
            # For NO, we might not have a direct last_price if it's YES-focused
            no_price_raw = data.get("no_price") or data.get("no_ask")
            if no_price_raw is None and yes_price:
                no_price = Decimal("100") - yes_price
            elif no_price_raw is None:
                no_price = Decimal("0")
            else:
                no_price = Decimal(str(no_price_raw))
            
            # Extract bid/ask if available
            yes_bid = Decimal(str(data.get("yes_bid"))) if data.get("yes_bid") is not None else None
            yes_ask = Decimal(str(data.get("yes_ask"))) if data.get("yes_ask") is not None else None
            no_bid = Decimal(str(data.get("no_bid"))) if data.get("no_bid") is not None else None
            no_ask = Decimal(str(data.get("no_ask"))) if data.get("no_ask") is not None else None

            if yes_price:
                outcomes.append(KalshiOutcome(
                    outcome_id="yes",
                    name="Yes",
                    price=yes_price,
                    probability=yes_price / Decimal("100"),
                    best_bid=yes_bid,
                    best_ask=yes_ask
                ))
            
            if no_price:
                outcomes.append(KalshiOutcome(
                    outcome_id="no",
                    name="No",
                    price=no_price,
                    probability=no_price / Decimal("100"),
                    best_bid=no_bid,
                    best_ask=no_ask
                ))
            
            # Kalshi may use "subtitle" instead of "category"
            category = data.get("category") or data.get("subtitle")
            
            return KalshiMarket(
                ticker=data.get("ticker", ""),
                event_ticker=data.get("event_ticker", ""),
                title=data.get("title", data.get("question", "")),
                description=data.get("description", ""),
                outcomes=outcomes,
                category=category,
                series_ticker=data.get("series_ticker"),
                open_time=self._parse_datetime(data.get("open_time")),
                close_time=self._parse_datetime(data.get("close_time")),
                expiration_time=self._parse_datetime(data.get("expiration_time")),
                settlement_time=self._parse_datetime(data.get("settlement_time")),
                active=data.get("status") == "active",
                status=data.get("status", "active"),
                volume=Decimal(str(data.get("volume", 0))),
                volume_24h=Decimal(str(data.get("volume_24h", 0))) if data.get("volume_24h") is not None else None,
                open_interest=Decimal(str(data.get("open_interest", 0))),
                liquidity=Decimal(str(data.get("liquidity", 0))),
                rules_primary=data.get("rules_primary"),
                rules_secondary=data.get("rules_secondary"),
                resolution_source=data.get("resolution_source"),
                tags=data.get("tags", []),
                can_close_position=data.get("can_close_position", True),
                created_at=self._parse_datetime(data.get("created_at"))
            )
            
        except (ValueError, TypeError, KeyError) as e:
            logger.warning(f"Failed to parse Kalshi market: {e}")
            return None
    
    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        """Parse datetime from various formats."""
        if not value:
            return None
        try:
            if isinstance(value, int):
                # Unix timestamp
                return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
            elif isinstance(value, str):
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            logger.debug("silent catch in client:3074")
        return None
    
    def _to_event_market(self, market: KalshiMarket) -> EventMarket:
        """Convert to venue-agnostic EventMarket."""
        return EventMarket(
            market_id=market.ticker,
            venue="kalshi",
            question=market.title,
            description=market.description,
            outcomes=[
                EventOutcome(
                    outcome_id=o.outcome_id,
                    outcome_name=o.name,
                    price=o.price / 100,  # Convert cents to dollars
                    probability=o.probability,
                    best_ask=o.price / 100,
                    best_bid=o.price / 100
                )
                for o in market.outcomes
            ],
            category=market.category,
            tags=market.tags,
            end_date=market.close_time or market.expiration_time,
            active=market.active,
            volume=market.volume,
            open_interest=market.open_interest,
            liquidity=market.liquidity,
            created_at=market.created_at,
            resolved=market.status == "settled",
            resolution=None,
            resolved_at=market.settlement_time,
            raw_data={
                "series_ticker": market.series_ticker,
                "event_ticker": market.event_ticker,
                "volume_24h": int(market.volume_24h) if market.volume_24h is not None else None,
            }
        )
    
    def _to_venue_orderbook(self, data: Dict[str, Any], market_id: str) -> VenueOrderBook:
        """Convert to VenueOrderBook."""
        bids = []
        asks = []
        
        # Kalshi orderbook has yes/no specific fields
        if "yes_bid" in data and data["yes_bid"]:
            bids.append((Decimal(str(data["yes_bid"])) / 100, Decimal("1")))
        if "no_bid" in data and data["no_bid"]:
            bids.append((Decimal(str(data["no_bid"])) / 100, Decimal("1")))
        if "yes_ask" in data and data["yes_ask"]:
            asks.append((Decimal(str(data["yes_ask"])) / 100, Decimal("1")))
        if "no_ask" in data and data["no_ask"]:
            asks.append((Decimal(str(data["no_ask"])) / 100, Decimal("1")))
        
        return VenueOrderBook(
            market_id=market_id,
            outcome_id=None,
            bids=bids,
            asks=asks,
            timestamp=datetime.now(timezone.utc),
            venue="kalshi"
        )
    
    def _to_placed_order(self, data: Dict[str, Any]) -> Optional[PlacedOrder]:
        """Convert to PlacedOrder."""
        try:
            return PlacedOrder(
                order_id=data.get("order_id", data.get("id", "")),
                market_id=data.get("ticker", ""),
                side=data.get("action", ""),
                size=Decimal(str(data.get("count", 0))),
                price=Decimal(str(data.get("price", 0))) / 100 if data.get("price") else None,
                filled_size=Decimal(str(data.get("filled_count", 0))),
                remaining_size=Decimal(str(data.get("remaining_count", data.get("count", 0)))),
                status=data.get("status", "pending"),
                venue="kalshi",
                created_at=self._parse_datetime(data.get("created_at"))
            )
        except (ValueError, TypeError, KeyError) as e:
            logger.warning(f"Failed to parse Kalshi order: {e}")
            return None
    
    def _parse_position(self, data: Dict[str, Any]) -> Optional[KalshiPosition]:
        """Parse position from API."""
        try:
            return KalshiPosition(
                ticker=data.get("ticker", ""),
                side=data.get("side", ""),
                count=int(data.get("count", 0)),
                avg_price=Decimal(str(data.get("avg_price", 0))),
                total_cost=Decimal(str(data.get("total_cost", 0))),
                unrealized_pnl=Decimal(str(data.get("unrealized_pnl", 0))) if "unrealized_pnl" in data else None,
                realized_pnl=Decimal(str(data.get("realized_pnl", 0))) if "realized_pnl" in data else None,
                created_at=self._parse_datetime(data.get("created_at"))
            )
        except (ValueError, TypeError, KeyError) as e:
            logger.warning(f"Failed to parse Kalshi position: {e}")
            return None
    
    def _to_venue_position(self, pos: KalshiPosition) -> VenuePosition:
        """Convert to VenuePosition."""
        return VenuePosition(
            market_id=pos.ticker,
            outcome_id=pos.side,
            size=Decimal(pos.count),
            average_entry_price=pos.avg_price / 100,  # Convert cents to dollars
            unrealized_pnl=pos.unrealized_pnl / 100 if pos.unrealized_pnl else None,
            realized_pnl=pos.realized_pnl / 100 if pos.realized_pnl else None,
            venue="kalshi",
            created_at=pos.created_at
        )
    
    def _parse_trade(self, data: Dict[str, Any]) -> Optional[KalshiTrade]:
        """Parse trade from API."""
        try:
            return KalshiTrade(
                trade_id=data.get("trade_id", data.get("id", "")),
                ticker=data.get("ticker", ""),
                order_id=data.get("order_id", ""),
                side=data.get("side", ""),
                count=int(data.get("count", 0)),
                price=Decimal(str(data.get("price", 0))),
                fee=Decimal(str(data.get("fee", 0))),
                timestamp=self._parse_datetime(data.get("created_at")) or datetime.now(timezone.utc)
            )
        except (ValueError, TypeError, KeyError) as e:
            logger.warning(f"Failed to parse Kalshi trade: {e}")
            return None
    
    def _to_venue_trade(self, trade: KalshiTrade) -> VenueTrade:
        """Convert to VenueTrade."""
        return VenueTrade(
            trade_id=trade.trade_id,
            market_id=trade.ticker,
            order_id=trade.order_id,
            side=trade.side,
            size=Decimal(trade.count),
            price=trade.price / 100,  # Convert cents to dollars
            fee=trade.fee / 100,
            timestamp=trade.timestamp,
            venue="kalshi"
        )

    # ------------------------------------------------------------------------
    # Trades-based volume aggregation
    # ------------------------------------------------------------------------

    async def get_volume_for_window(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
    ) -> OperationResult[Dict[str, Any]]:
        """Aggregate trade volume for a ticker in a time window.

        Paginates through ``GET /trades`` and sums both contract counts
        and price-weighted notional volume.

        Returns dict with:
            - ``total_contracts``: sum of trade counts
            - ``notional_usd``: sum of count × (price_cents / 100)

        Args:
            ticker: Market ticker
            start: Window start (UTC)
            end: Window end (UTC)
        """
        start_ts = int(start.replace(tzinfo=timezone.utc).timestamp())
        end_ts = int(end.replace(tzinfo=timezone.utc).timestamp())
        cursor: Optional[str] = None
        total_contracts = 0
        notional_usd = 0.0
        max_pages = 50  # P0-4 FIX: Prevent unbounded pagination
        pages = 0

        while pages < max_pages:
            params: Dict[str, Any] = {
                "ticker": ticker,
                "limit": 1000,
                "start_ts": start_ts,
                "end_ts": end_ts,
            }
            if cursor:
                params["cursor"] = cursor

            result = await self._request_with_resilience(
                "GET", "/trades", params=params,
                operation_name="get_volume_for_window",
            )
            if not result.success:
                return OperationResult.fail(
                    result.error,
                    latency_ms=result.latency_ms,
                    retries=result.retries,
                    operation="get_volume_for_window",
                )

            for tr in result.data.get("trades", []):
                count = tr.get("count", 0)
                price_cents = tr.get("price", 0)
                total_contracts += count
                notional_usd += count * (price_cents / 100.0)

            cursor = result.data.get("cursor")
            pages += 1
            if not cursor:
                break

        if cursor:
            logger.warning(f"get_volume_for_window: Hit max_pages limit ({max_pages}), returning partial data")

        return OperationResult.ok(
            {
                "total_contracts": total_contracts,
                "notional_usd": round(notional_usd, 2),
            },
            latency_ms=result.latency_ms,
            retries=result.retries,
            operation="get_volume_for_window",
        )


# ═══════════════════════════════════════════════════════════════════════════
# FIX message parsing utilities
# ═══════════════════════════════════════════════════════════════════════════

# BusinessRejectReason codes (FIX tag 380) from Kalshi FIX docs
KALSHI_REJECT_REASONS: Dict[int, str] = {
    0: "Other",
    1: "Unknown ID",
    2: "Unknown Security",
    3: "Unsupported Message Type",
    4: "Application not available",
    5: "Conditionally required field missing",
    6: "Not authorized",
    7: "DeliverTo firm not available at this time",
    18: "Invalid price increment",
}

# Common business reject descriptions for logging
KALSHI_BUSINESS_REJECT_CAUSES: Dict[str, str] = {
    "unknown_security": "Invalid or delisted market ticker (reason 2)",
    "exchange_closed": "Order sent outside trading hours or after market expired",
    "order_exceeds_limit": "Position or order-size limit violated, or insufficient balance",
    "unsupported_msg_type": "Unsupported order type/flag or message type (reason 3)",
    "invalid_quantity": "Negative/zero size, invalid size increments, or missing fields",
}


def parse_fix(msg_str: str) -> Dict[str, str]:
    """Parse a FIX message string into a tag→value dict.

    FIX fields are delimited by SOH (``\\x01``).
    Example: ``'8=FIX.4.4\\x019=...\\x0135=D\\x01'``
    """
    fields = msg_str.strip().split("\x01")
    out: Dict[str, str] = {}
    for f in fields:
        if "=" not in f:
            continue
        tag, val = f.split("=", 1)
        out[tag] = val
    return out


def handle_fix_reject(msg: Dict[str, str]) -> Optional[Exception]:
    """Inspect a parsed FIX message for Reject (35=3) or BusinessMessageReject (35=j).

    Returns:
        KalshiSessionError for session rejects,
        KalshiBusinessError for business rejects,
        None if the message is not a reject.
    """
    msg_type = msg.get("35")

    if msg_type == "3":
        # Session-level Reject
        reason = msg.get("373")
        text = msg.get("58", "")
        ref_tag = msg.get("371")
        ref_type = msg.get("372")
        logger.error(
            f"[kalshi-fix] Session Reject: reason={reason} text={text} "
            f"ref_tag={ref_tag} ref_type={ref_type}"
        )
        try:
            rc = int(reason) if reason is not None else None
        except (ValueError, TypeError):
            rc = None
        return KalshiSessionError(
            text or f"FIX Session Reject",
            reason_code=rc,
        )

    if msg_type == "j":
        # BusinessMessageReject
        code_str = msg.get("380", "0")
        text = msg.get("58", "")
        ref_type = msg.get("372")
        try:
            code = int(code_str)
        except (ValueError, TypeError):
            code = 0
        desc = KALSHI_REJECT_REASONS.get(code, "Unknown")
        logger.error(
            f"[kalshi-fix] BusinessMessageReject: code={code} ({desc}) "
            f"text={text} ref_type={ref_type}"
        )
        return KalshiBusinessError(
            text or desc,
            status_code=400,
            reason_code=code,
            ref_msg_type=ref_type,
        )

    return None

    async def close(self) -> None:
        """Close HTTP client and cleanup resources with Windows error handling.

        Handles Windows-specific asyncio errors gracefully during shutdown
        to prevent ERROR_OPERATION_ABORTED (WinError 995) from propagating.
        """
        if self._http_client is not None:
            try:
                await self._http_client.aclose()
            except asyncio.CancelledError:
                # Normal during shutdown - don't log as error
                pass
            except OSError as e:
                # Handle Windows-specific errors silently
                if self._is_windows_recoverable_error(e):
                    logger.debug("[kalshi] close() suppressed Windows error: %r", e)
                else:
                    logger.warning("[kalshi] close() got OSError: %r", e)
            except Exception as e:
                logger.debug("[kalshi] close() error (non-fatal): %r", e)
            finally:
                self._http_client = None


# ── Singleton ────────────────────────────────────────────────────────────

_client: Optional[KalshiVenueClient] = None
_client_lock = threading.Lock()


def get_kalshi_client(config: Optional[KalshiConfig] = None) -> KalshiVenueClient:
    """Get or create the singleton KalshiVenueClient.

    Rate tier is read from KALSHI_RATE_TIER env var (default "basic").
    Set to "advanced", "premier", or "prime" to lift the self-imposed throttle.
    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                import os as _os
                _rate_tier = _os.getenv("KALSHI_RATE_TIER", "basic")
                _client = KalshiVenueClient(config, rate_tier=_rate_tier)
    return _client
