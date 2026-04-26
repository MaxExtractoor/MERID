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
from merid.event_venues.kalshi.types import (
    BalanceSuccess, BalanceTemporaryError, BalancePermanentError,
    MarketSuccess, MarketTemporaryError, MarketPermanentError,
    OrderSuccess, OrderTemporaryError, OrderPermanentError,
    RawVenueBalance, InternalBankroll, BalanceState,
    BalanceResult, MarketResult, OrderResult,
)

logger = get_logger("merid.event_venues.kalshi.client_v2")


class KalshiClientV2:
    """Clean Kalshi client with explicit result types and NO assertions."""
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key_id: Optional[str] = None,
        private_key_path: Optional[str] = None,
        private_key_pem: Optional[str] = None,
        max_riskable_frac: Optional[Decimal] = None,
    ):
        # Load from env/settings if not provided
        # Default includes /trade-api/v2 to match KalshiConfig standard
        self._base_url = base_url or os.getenv(
            "KALSHI_API_URL", 
            "https://api.elections.kalshi.com/trade-api/v2"
        )
        
        # KALSHI_ENV-aware key selection (matches KalshiConfig logic)
        _kalshi_env = os.getenv("KALSHI_ENV", "").lower()
        if _kalshi_env == "live":
            # Use live-specific credentials if available, fall back to generic
            _env_key = os.getenv("KALSHI_LIVE_API_KEY_ID")
            _env_path = os.getenv("KALSHI_LIVE_PRIVATE_KEY_PATH")
            _env_pem = os.getenv("KALSHI_LIVE_PRIVATE_KEY_PEM")
            self._api_key_id = api_key_id or _env_key or os.getenv("KALSHI_API_KEY_ID")
            self._private_key_path = private_key_path or _env_path or os.getenv("KALSHI_PRIVATE_KEY_PATH")
            self._private_key_pem = private_key_pem or _env_pem or os.getenv("KALSHI_PRIVATE_KEY_PEM")
        elif _kalshi_env == "demo":
            # Use demo-specific credentials if available
            _env_key = os.getenv("KALSHI_DEMO_API_KEY_ID")
            _env_path = os.getenv("KALSHI_DEMO_PRIVATE_KEY_PATH")
            _env_pem = os.getenv("KALSHI_DEMO_PRIVATE_KEY_PEM")
            self._api_key_id = api_key_id or _env_key or os.getenv("KALSHI_API_KEY_ID")
            self._private_key_path = private_key_path or _env_path or os.getenv("KALSHI_PRIVATE_KEY_PATH")
            self._private_key_pem = private_key_pem or _env_pem or os.getenv("KALSHI_PRIVATE_KEY_PEM")
        else:
            # Legacy behavior - use generic env vars
            self._api_key_id = api_key_id or os.getenv("KALSHI_API_KEY_ID")
            self._private_key_path = private_key_path or os.getenv("KALSHI_PRIVATE_KEY_PATH")
            self._private_key_pem = private_key_pem or os.getenv("KALSHI_PRIVATE_KEY_PEM")
        
        # Risk config - default 2% per position
        self._max_riskable_frac = max_riskable_frac or Decimal("0.02")
        
        # Log credential config (masked) for debugging
        key_preview = self._api_key_id[:8] + "..." if self._api_key_id else "NOT SET"
        logger.info(f"[KalshiClientV2] Initializing: env={_kalshi_env}, key_id={key_preview}, key_path={self._private_key_path or 'NOT SET'}")
        
        # HTTP client (lazily initialized)
        self._client: Optional[httpx.AsyncClient] = None
        self._client_lock = asyncio.Lock()
        
        # RSA key (lazily loaded)
        self._private_key: Optional[Any] = None
        self._cached_key_source: Optional[str] = None
        
        # Metrics
        self._requests_total = 0
        self._requests_failed = 0
        
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with proper timeouts."""
        if self._client is None:
            async with self._client_lock:
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
        """Generate Kalshi RSA auth headers."""
        if self._private_key is None and not self._load_private_key():
            return {}
        
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        
        ts_ms = str(int(time.time() * 1000))
        message = ts_ms + method.upper() + path
        
        try:
            signature = self._private_key.sign(
                message.encode(),
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
                hashes.SHA256(),
            )
            return {
                "KALSHI-ACCESS-KEY": self._api_key_id or "",
                "KALSHI-ACCESS-TIMESTAMP": ts_ms,
                "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
            }
        except Exception as e:
            logger.error("[RSA] Signing failed: %s", e)
            return {}
    
    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Make authenticated request with RSA signing."""
        client = await self._get_client()
        headers = kwargs.pop("headers", {})
        if self._api_key_id:
            # Kalshi expects full API path in signature including /trade-api/v2
            # Even though base_url has /trade-api/v2, path doesn't, so we prepend it
            full_api_path = f"/trade-api/v2{path}"
            headers.update(self._sign_request(method, full_api_path))
        headers.setdefault("Content-Type", "application/json")
        self._requests_total += 1
        return await client.request(method, path, headers=headers, **kwargs)
    
    async def get_balance(self) -> BalanceResult:
        """Fetch balance from Kalshi /portfolio/balance.
        
        Returns:
            BalanceSuccess: Fresh data available
            BalanceTemporaryError: Network/timeout issue - use stale if available
            BalancePermanentError: Auth/account issue - STOP
            
        NO ASSERTIONS. NO "error -> 0". NO "locked bankroll" nonsense.
        """
        start_ms = time.time() * 1000
        operation = "get_balance"
        
        try:
            response = await self._request("GET", "/portfolio/balance")
            latency_ms = time.time() * 1000 - start_ms
            
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
            bankroll = InternalBankroll(
                equity_usd=raw_balance.total_equity,
                max_riskable_frac=self._max_riskable_frac,
                as_of=raw_balance.as_of,
                source=raw_balance.source,
                state=BalanceState.FRESH,
            )
            
            logger.info(
                f"[{operation}] Success: equity=${bankroll.equity_usd}, "
                f"max_position=${bankroll.max_position_usd}, latency={latency_ms:.1f}ms"
            )
            
            return BalanceSuccess(
                bankroll=bankroll,
                raw=raw_balance,
                latency_ms=latency_ms,
            )
            
        except httpx.TimeoutException as e:
            latency_ms = time.time() * 1000 - start_ms
            logger.warning(f"[{operation}] Timeout after {latency_ms:.1f}ms")
            return BalanceTemporaryError(
                reason=f"Kalshi timeout: {e}",
                details={"latency_ms": latency_ms},
                last_known=None,
                retry_after_seconds=30,
            )
            
        except httpx.ConnectError as e:
            logger.warning(f"[{operation}] Connection error: {e}")
            return BalanceTemporaryError(
                reason=f"Cannot connect to Kalshi: {e}",
                details={},
                last_known=None,
                retry_after_seconds=60,
            )
            
        except Exception as e:
            # Catch-all for unexpected errors - log FULL details
            logger.exception(f"[{operation}] Unexpected error: {type(e).__name__}: {e}")
            return BalanceTemporaryError(
                reason=f"Unexpected error: {type(e).__name__}: {e}",
                details={"exception_type": type(e).__name__, "str": str(e)},
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
