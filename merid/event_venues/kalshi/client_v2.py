"""Kalshi API Client v2 - No assertions, typed results.

This is a complete rewrite of the Kalshi client that:
- NEVER asserts on external data
- Returns explicit result types (Success | TemporaryError | PermanentError)
- Logs full context for debugging
- Has NO legacy "locked bankroll" concepts

Usage:
    client = KalshiClientV2()
    result = await client.get_balance()
    
    if isinstance(result, BalanceSuccess):
        print(f"Equity: ${result.bankroll.equity_usd}")
    elif isinstance(result, BalanceTemporaryError):
        # Use stale or wait
        print(f"Temp error, retry in {result.retry_after_seconds}s")
    elif isinstance(result, BalancePermanentError):
        # STOP - alert, disable trading
        print(f"CRITICAL: {result.reason}")
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from decimal import Decimal
from typing import Any, Dict, Optional

import httpx

from utils.logger import get_logger
from utils.http_client import get_shared_ssl_context
from merid.event_venues.kalshi.types import (
    BalanceSuccess, BalanceTemporaryError, BalancePermanentError,
    MarketSuccess, MarketTemporaryError, MarketPermanentError,
    OrderSuccess, OrderTemporaryError, OrderPermanentError,
    RawVenueBalance, InternalBankroll, BalanceState,
    BalanceResult, MarketResult, OrderResult,
)
from merid.event_venues.kalshi.rate_limiter import get_rate_limiter
from merid.event_venues.kalshi.kalshi_config import (
    get_kalshi_config, 
    build_auth_message, 
    log_auth_debug,
    verify_kalshi_config
)

logger = get_logger("merid.event_venues.kalshi.client_v2")

# ── Rate limit tiers (from Kalshi API policies) ───────────────────────────────
# Kalshi tiers: Basic 20r/10w, Advanced 30/30, Premier 100/100, Prime 400/400
KALSHI_RATE_TIERS = {
    "basic":    {"read": 20, "write": 10},
    "advanced": {"read": 30, "write": 30},
    "premier":  {"read": 100, "write": 100},
    "prime":    {"read": 400, "write": 400},
}

# ── Retry/backoff configuration ───────────────────────────────────────────────
KALSHI_MAX_RETRIES = 3
KALSHI_BACKOFF_BASE = 2.0
KALSHI_RETRY_STATUSES = {429, 500, 502, 503, 504}


class KalshiClientV2:
    """Clean Kalshi client with explicit result types and NO assertions."""
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key_id: Optional[str] = None,
        private_key_path: Optional[str] = None,
        private_key_pem: Optional[str] = None,
        max_riskable_frac: Optional[Decimal] = None,
        rate_limit_tier: str = "basic",
    ):
        # Verify config at initialization time (not relying on global flag which may have timing issues)
        try:
            is_valid, error_msg, config = verify_kalshi_config()
            if not is_valid:
                error_msg = f"[KalshiClientV2] Config validation failed: {error_msg}. Verify config via /api/health/kalshi-config"
                logger.error(error_msg)
                raise RuntimeError(error_msg)
        except Exception as e:
            error_msg = f"[KalshiClientV2] Exception during config verification: {e}. Verify config via /api/health/kalshi-config"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        # FORCE UNIFIED CONFIG: Always use unified config, no overrides allowed
        # This prevents config drift between REST and WS
        try:
            config = get_kalshi_config()
            self._base_url = config.rest_base_url
            self._api_key_id = config.api_key_id
            self._private_key_path = config.private_key_path
            self._private_key_pem = config.private_key_pem
            self._config = config  # Store for auth logging
            
            # Log that we're using unified config
            logger.info(
                f"[KALSHI-CONFIG-REST] env={config.env} rest_base={config.rest_base_url} key_id={config.api_key_id[:4]}****{config.api_key_id[-4:] if len(config.api_key_id) > 8 else '****'}"
            )
        except Exception as e:
            error_msg = f"[KalshiClientV2] Failed to load unified config: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        # Risk config - default 2% per position
        self._max_riskable_frac = max_riskable_frac or Decimal("0.02")
        
        # Rate limit tier configuration
        self._rate_limit_tier = rate_limit_tier
        tier_limits = KALSHI_RATE_TIERS.get(rate_limit_tier, KALSHI_RATE_TIERS["basic"])
        self._read_rate = tier_limits["read"]
        self._write_rate = tier_limits["write"]
        
        # Rate-limit tracking (token bucket)
        self._read_tokens = float(self._read_rate)
        self._write_tokens = float(self._write_rate)
        self._last_refill = time.monotonic()
        # EVENT-LOOP-FIX: Lazy-initialize to avoid binding to wrong event loop
        self._rate_limit_lock: Optional[asyncio.Lock] = None
        
        # Log credential config (masked) for debugging
        key_preview = self._api_key_id[:8] + "..." if self._api_key_id else "NOT SET"
        logger.info(
            f"[KalshiClientV2] Initializing: base_url={self._base_url}, key_id={key_preview}, "
            f"key_path={self._private_key_path or 'NOT SET'}, rate_tier={rate_limit_tier}"
        )
        
        # HTTP client (lazily initialized)
        self._client: Optional[httpx.AsyncClient] = None
        # EVENT-LOOP-FIX: Lazy-initialize to avoid binding to wrong event loop
        self._client_lock: Optional[asyncio.Lock] = None
        
        # RSA key (lazily loaded)
        self._private_key: Optional[Any] = None
        self._cached_key_source: Optional[str] = None
        
        # Metrics
        self._requests_total = 0
        self._requests_failed = 0
        self._rate_limit_hits = 0

    def _ensure_rate_limit_lock(self) -> asyncio.Lock:
        """Lazy-initialize the rate limit lock in the current event loop."""
        if self._rate_limit_lock is None:
            self._rate_limit_lock = asyncio.Lock()
        return self._rate_limit_lock

    def _ensure_client_lock(self) -> asyncio.Lock:
        """Lazy-initialize the client lock in the current event loop."""
        if self._client_lock is None:
            self._client_lock = asyncio.Lock()
        return self._client_lock

    def _refill_tokens(self) -> None:
        """Refill rate-limit tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._read_tokens = min(self._read_rate, self._read_tokens + elapsed * self._read_rate)
        self._write_tokens = min(self._write_rate, self._write_tokens + elapsed * self._write_rate)
        self._last_refill = now
    
    async def _acquire_token(self, is_write: bool = False) -> float:
        """Acquire a rate-limit token, sleeping if necessary. Returns wait time in seconds."""
        async with self._ensure_rate_limit_lock():
            self._refill_tokens()
            tokens = self._write_tokens if is_write else self._read_tokens
            if tokens >= 1.0:
                if is_write:
                    self._write_tokens -= 1.0
                else:
                    self._read_tokens -= 1.0
                return 0.0
            
            # Need to wait for a token
            rate = self._write_rate if is_write else self._read_rate
            wait = (1.0 - tokens) / rate if rate > 0 else 1.0
        
        # Sleep outside the lock so other coroutines can proceed
        await asyncio.sleep(wait)
        async with self._ensure_rate_limit_lock():
            self._refill_tokens()
            if is_write:
                self._write_tokens = max(0, self._write_tokens - 1.0)
            else:
                self._read_tokens = max(0, self._read_tokens - 1.0)
        return wait
    
    def get_rate_limit_stats(self) -> Dict[str, Any]:
        """Get current rate-limit statistics for observability."""
        self._refill_tokens()
        return {
            "tier": self._rate_limit_tier,
            "read_tokens": round(self._read_tokens, 2),
            "write_tokens": round(self._write_tokens, 2),
            "read_rate": self._read_rate,
            "write_rate": self._write_rate,
            "rate_limit_hits": self._rate_limit_hits,
        }
        
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with proper timeouts."""
        if self._client is None:
            async with self._ensure_client_lock():
                if self._client is None:
                    self._client = httpx.AsyncClient(
                        base_url=self._base_url,
                        timeout=httpx.Timeout(
                            connect=15.0,
                            read=60.0,
                            write=15.0,
                            pool=10.0,
                        ),
                        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                        verify=get_shared_ssl_context(),
                    )
        return self._client
    
    def _load_private_key(self) -> bool:
        """Load RSA private key for request signing."""
        _this_cache_key = self._private_key_path or ("pem" if self._private_key_pem else "")
        if self._private_key is not None and self._cached_key_source == _this_cache_key:
            return True
        
        try:
            from cryptography.hazmat.primitives import serialization
            
            pem_bytes: Optional[bytes] = None
            if self._private_key_path:
                if not os.path.exists(self._private_key_path):
                    logger.error(
                        "[RSA] Key file not found: %s. "
                        "Download your %s key from https://kalshi.com/account/keys",
                        self._private_key_path,
                        "LIVE" if os.getenv("KALSHI_ENV", "").lower() == "live" else "demo"
                    )
                    return False
                with open(self._private_key_path, "rb") as f:
                    pem_bytes = f.read()
            elif self._private_key_pem:
                pem_bytes = self._private_key_pem.encode()
            
            if pem_bytes is None:
                return False
            
            self._private_key = serialization.load_pem_private_key(pem_bytes, password=None)
            self._cached_key_source = _this_cache_key
            return True
        except Exception as e:
            logger.error("[RSA] Failed to load key: %s", e)
            return False
    
    def _sign_request(self, method: str, path: str) -> Dict[str, str]:
        """Generate Kalshi RSA auth headers using unified signing logic."""
        if self._private_key is None and not self._load_private_key():
            return {}
        
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        
        # Use system time (assumes NTP-synced clock)
        # Modern systems typically have NTP sync, so complex clock skew calculation is unnecessary
        # If clock skew issues occur, ensure system time is synchronized via NTP
        ts_ms = str(int(time.time() * 1000))
        
        # Use unified message building
        message = build_auth_message(ts_ms, method, path)
        
        try:
            signature = self._private_key.sign(
                message.encode(),
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
                hashes.SHA256(),
            )
            
            # Side-by-side auth logging for debugging
            if self._config:
                log_auth_debug(
                    component="REST",
                    config=self._config,
                    method=method,
                    path=path,
                    timestamp_ms=ts_ms,
                    message=message,
                    signature_length=len(signature),
                )
            
            return {
                "KALSHI-ACCESS-KEY": self._api_key_id or "",
                "KALSHI-ACCESS-TIMESTAMP": ts_ms,
                "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
            }
        except Exception as e:
            logger.error("[RSA] Signing failed: %s", e)
            return {}
    
    async def _request(self, method: str, path: str, is_write: bool = False, **kwargs) -> httpx.Response:
        """Make authenticated request with RSA signing, centralized rate-limiting, and retry/backoff."""
        # Determine endpoint name for rate limiting
        endpoint = "write" if is_write else "read"
        
        # Use centralized rate limiter
        rate_limiter = get_rate_limiter()
        
        # Wait for rate limiter permission
        max_wait_time = 30.0  # Maximum time to wait for rate limiter
        wait_start = time.time()
        while not await rate_limiter.acquire(endpoint):
            if time.time() - wait_start > max_wait_time:
                logger.error(f"[KalshiClientV2] Rate limiter timeout after {max_wait_time}s for {endpoint}")
                raise httpx.TimeoutException("Rate limiter timeout")
            await asyncio.sleep(0.1)
        
        client = await self._get_client()
        headers = kwargs.pop("headers", {})
        # Kalshi expects full API path in signature including /trade-api/v2
        # Even though base_url has /trade-api/v2, path doesn’t, so we prepend it
        full_api_path = f"/trade-api/v2{path}" if self._api_key_id else None
        headers.setdefault("Content-Type", "application/json")

        # Retry loop with exponential backoff and proper 429 handling
        # CRITICAL FIX (2026-08-08): Re-sign on every attempt so a long rate-limiter wait
        # or retry backoff does not make the KALSHI-ACCESS-TIMESTAMP expire before the
        # request is actually sent. Kalshi rejects requests with stale timestamps.
        last_error = None
        for attempt in range(KALSHI_MAX_RETRIES + 1):
            self._requests_total += 1
            if full_api_path:
                headers.update(self._sign_request(method, full_api_path))
            try:
                response = await client.request(method, path, headers=headers, **kwargs)
                
                # Handle 429 rate limit responses with centralized backoff
                if response.status_code == 429:
                    self._rate_limit_hits += 1
                    
                    # Extract Retry-After header if present
                    retry_after = None
                    if "Retry-After" in response.headers:
                        try:
                            retry_after = float(response.headers["Retry-After"])
                        except ValueError:
                            logger.warning("[KalshiClientV2] Invalid Retry-After header value")
                    
                    # ALERT THRESHOLDS MONITORING: Track 429 rate limit hits
                    try:
                        from merid.event_venues.kalshi.monitoring import get_monitor
                        monitor = get_monitor()
                        await monitor.update_rate_limit_metrics(
                            endpoint=path,
                            hit_429=True,
                            retry_after=retry_after
                        )
                    except Exception as monitor_err:
                        pass
                    
                    # Get recommended backoff from rate limiter
                    backoff = rate_limiter.handle_429(endpoint, retry_after)
                    
                    logger.warning(
                        f"[KalshiClientV2] Rate limit hit (429) on attempt {attempt + 1}/{KALSHI_MAX_RETRIES + 1}, "
                        f"backing off for {backoff:.1f}s"
                    )
                    
                    if attempt < KALSHI_MAX_RETRIES:
                        await asyncio.sleep(backoff)
                        continue
                    else:
                        logger.error(f"[KalshiClientV2] Max retries exceeded for 429")
                        return response
                
                # Handle other retryable status codes
                if response.status_code in KALSHI_RETRY_STATUSES and response.status_code != 429:
                    last_error = f"HTTP {response.status_code}"
                    if attempt < KALSHI_MAX_RETRIES:
                        backoff = KALSHI_BACKOFF_BASE ** attempt
                        logger.warning(
                            f"[KalshiClientV2] Retryable error {response.status_code} on attempt {attempt + 1}/{KALSHI_MAX_RETRIES + 1}, "
                            f"retrying in {backoff:.1f}s"
                        )
                        await asyncio.sleep(backoff)
                        continue
                    else:
                        logger.error(f"[KalshiClientV2] Max retries exceeded for {response.status_code}")
                        return response
                
                # Successful response - notify rate limiter
                rate_limiter.handle_success(endpoint)
                return response
                    
            except httpx.TimeoutException as e:
                last_error = f"Timeout: {e}"
                if attempt < KALSHI_MAX_RETRIES:
                    backoff = KALSHI_BACKOFF_BASE ** attempt
                    logger.warning(f"[KalshiClientV2] Timeout on attempt {attempt + 1}/{KALSHI_MAX_RETRIES + 1}, retrying in {backoff:.1f}s")
                    await asyncio.sleep(backoff)
                else:
                    logger.error(f"[KalshiClientV2] Max retries exceeded for timeout")
                    raise
                    
            except httpx.ConnectError as e:
                last_error = f"Connect error: {e}"
                if attempt < KALSHI_MAX_RETRIES:
                    backoff = KALSHI_BACKOFF_BASE ** attempt
                    logger.warning(f"[KalshiClientV2] Connect error on attempt {attempt + 1}/{KALSHI_MAX_RETRIES + 1}, retrying in {backoff:.1f}s")
                    await asyncio.sleep(backoff)
                else:
                    logger.error(f"[KalshiClientV2] Max retries exceeded for connect error")
                    raise
                    
            except Exception as e:
                # Non-retryable error - raise immediately
                logger.error(f"[KalshiClientV2] Non-retryable error: {type(e).__name__}: {e}")
                raise
        
        # Should not reach here, but just in case
        raise RuntimeError(f"Request failed after retries: {last_error}")
    
    async def get_balance(self) -> BalanceResult:
        """Fetch balance from Kalshi /portfolio/balance.
        
        Returns:
            BalanceSuccess: Fresh data available
            BalanceTemporaryError: Network/timeout issue - use stale if available
            BalancePermanentError: Auth/account issue - STOP
            
        NO ASSERTIONS. NO "error -> 0". NO "locked bankroll" nonsense.
        """
        # CRITICAL INSTRUMENTATION: Capture environment and client details
        import os
        env = os.getenv("MERID_ENV", "unknown")
        profile = os.getenv("MERID_PROFILE", "unknown")
        
        # Log client initialization details
        client_info = f"env={env}, profile={profile}"
        if hasattr(self, 'key_id'):
            client_info += f", key_id={self.key_id}"
        if hasattr(self, 'key_path'):
            client_info += f", key_path={self.key_path}"
        if hasattr(self, 'base_url'):
            client_info += f", base_url={self.base_url}"
        
        logger.info(f"[KALSHI-CLIENT-INSTRUMENT] get_balance() called - {client_info}")
        
        start_ms = time.time() * 1000
        operation = "get_balance"
        
        try:
            logger.info(f"[KALSHI-CLIENT-INSTRUMENT] About to call _request() for {operation}")
            response = await self._request("GET", "/portfolio/balance")
            latency_ms = time.time() * 1000 - start_ms
            
            logger.info(f"[KALSHI-CLIENT-INSTRUMENT] _request() completed in {latency_ms:.1f}ms, status={response.status_code}")
            
            # Check HTTP status
            if response.status_code >= 500:
                # Server error - temporary
                logger.warning(f"[{operation}] Kalshi 5xx error: {response.status_code}")
                return BalanceTemporaryError(
                    reason=f"Kalshi server error: {response.status_code}",
                    details={"status_code": response.status_code},
                    last_known=None,  # Will need to fetch from cache
                    retry_after_seconds=30,
                )
            
            if response.status_code == 401:
                # Auth error - permanent
                error_body = response.text[:500] if response.text else "No response body"
                key_preview = self._api_key_id[:8] + "..." if self._api_key_id else "NOT SET"
                logger.error(
                    f"[{operation}] Authentication failed: status={response.status_code}, "
                    f"key_id={key_preview}, body={error_body}"
                )
                return BalancePermanentError(
                    reason="Kalshi authentication failed - check API credentials",
                    details={"status_code": 401, "key_id_preview": key_preview, "response": error_body},
                    alert_immediately=True,
                )
            
            if response.status_code >= 400:
                # Client error - likely permanent
                logger.error(f"[{operation}] Client error: {response.status_code}")
                return BalancePermanentError(
                    reason=f"Kalshi client error: {response.status_code}",
                    details={"status_code": response.status_code, "body": response.text[:500]},
                    alert_immediately=True,
                )
            
            # Parse response
            try:
                data = response.json()
            except json.JSONDecodeError as e:
                logger.error(f"[{operation}] Invalid JSON response: {e}")
                return BalanceTemporaryError(
                    reason=f"Invalid JSON from Kalshi: {e}",
                    details={"body_preview": response.text[:200]},
                    last_known=None,
                    retry_after_seconds=10,
                )
            
            # Validate we have some balance data (but NO assertions)
            if not isinstance(data, dict):
                logger.error(f"[{operation}] Response not a dict: {type(data)}")
                return BalanceTemporaryError(
                    reason="Invalid response structure from Kalshi",
                    details={"type": str(type(data))},
                    last_known=None,
                    retry_after_seconds=30,
                )
            
            # Extract raw balance (will handle missing fields gracefully)
            raw_balance = RawVenueBalance.from_kalshi_response(data)
            
            # Build canonical internal bankroll
            # Bankroll split: equity = portfolio_value + cash_available
            bankroll = InternalBankroll(
                equity_usd=raw_balance.total_equity,  # portfolio_value + cash
                available_cash_usd=raw_balance.cash_available,  # spendable cash only
                max_riskable_frac=self._max_riskable_frac,
                as_of=raw_balance.as_of,
                source=raw_balance.source,
                state=BalanceState.FRESH,
            )
            
            logger.info(
                f"[{operation}] Success: equity=${bankroll.equity_usd} "
                f"(cash=${bankroll.available_cash_usd}, positions=${bankroll.locked_cash_usd}), "
                f"max_position=${bankroll.max_position_usd}, latency={latency_ms:.1f}ms"
            )
            
            return BalanceSuccess(
                bankroll=bankroll,
                raw=raw_balance,
                latency_ms=latency_ms,
            )
            
        except httpx.TimeoutException as e:
            latency_ms = time.time() * 1000 - start_ms
            logger.error(f"[KALSHI-CLIENT-INSTRUMENT] TIMEOUT after {latency_ms:.1f}ms - {type(e).__name__}: {str(e)}")
            return BalanceTemporaryError(
                reason=f"Kalshi timeout: {e}",
                details={"latency_ms": latency_ms},
                last_known=None,
                retry_after_seconds=30,
            )
            
        except httpx.ConnectError as e:
            logger.error(f"[KALSHI-CLIENT-INSTRUMENT] CONNECTION ERROR - {type(e).__name__}: {str(e)}")
            return BalanceTemporaryError(
                reason=f"Cannot connect to Kalshi: {e}",
                details={},
                last_known=None,
                retry_after_seconds=60,
            )
            
        except Exception as e:
            # Catch-all for unexpected errors - log FULL details
            latency_ms = time.time() * 1000 - start_ms
            logger.error(f"[KALSHI-CLIENT-INSTRUMENT] UNEXPECTED ERROR after {latency_ms:.1f}ms - {type(e).__name__}: {str(e)}")
            logger.exception(f"[KALSHI-CLIENT-INSTRUMENT] Full exception traceback:")
            return BalanceTemporaryError(
                reason=f"Unexpected error: {type(e).__name__}: {e}",
                details={"exception_type": type(e).__name__, "str": str(e), "latency_ms": latency_ms},
                last_known=None,
                retry_after_seconds=30,
            )
    
    async def get_market(self, market_id: str) -> MarketResult:
        """Fetch market details from Kalshi.
        
        Same pattern: explicit results, no assertions.
        """
        start_ms = time.time() * 1000
        operation = f"get_market({market_id})"
        
        try:
            response = await self._request("GET", f"/markets/{market_id}")
            latency_ms = time.time() * 1000 - start_ms
            
            if response.status_code == 404:
                return MarketPermanentError(
                    reason=f"Market {market_id} not found",
                    market_id=market_id,
                )
            
            if response.status_code >= 500:
                return MarketTemporaryError(
                    reason=f"Server error: {response.status_code}",
                    retry_after_seconds=30,
                )
            
            if response.status_code >= 400:
                # Log the actual error response from Kalshi for debugging
                error_body = response.text[:500] if response.text else "empty"
                logger.error(f"[{operation}] Client error: {response.status_code} - Response body: {error_body}")
                return MarketPermanentError(
                    reason=f"Client error: {response.status_code}",
                    market_id=market_id,
                )
            
            data = response.json()
            return MarketSuccess(data=data, latency_ms=latency_ms)
            
        except httpx.TimeoutException:
            return MarketTemporaryError(reason="Timeout", retry_after_seconds=30)
        except Exception as e:
            logger.exception(f"[{operation}] Error: {e}")
            return MarketTemporaryError(reason=f"Error: {e}", retry_after_seconds=30)
    
    async def get_markets(
        self,
        series_ticker: Optional[str] = None,
        status: str = "open",
        limit: int = 100,
    ) -> MarketResult:
        """List markets from Kalshi."""
        start_ms = time.time() * 1000
        
        params = {"status": status, "limit": limit}
        if series_ticker:
            params["series_ticker"] = series_ticker
        
        try:
            response = await self._request("GET", "/markets", params=params)
            latency_ms = time.time() * 1000 - start_ms
            
            if response.status_code >= 500:
                return MarketTemporaryError(
                    reason=f"Server error: {response.status_code}",
                    retry_after_seconds=30,
                )
            
            if response.status_code >= 400:
                return MarketPermanentError(reason=f"Client error: {response.status_code}")
            
            data = response.json()
            return MarketSuccess(data=data, latency_ms=latency_ms)
            
        except Exception as e:
            logger.exception(f"[list_markets] Error: {e}")
            return MarketTemporaryError(reason=f"Error: {e}", retry_after_seconds=30)
    
    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
