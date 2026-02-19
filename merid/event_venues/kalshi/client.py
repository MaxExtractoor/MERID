"""Kalshi REST client - Implements EventVenueClient interface.

This is the **canonical resilient venue client** implementation.
Pattern: circuit breaker per venue, retry with backoff on I/O,
explicit OperationResult returns instead of silent fallbacks.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, TypeVar

import aiohttp
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
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.client")

T = TypeVar("T")

# Retry configuration for Kalshi
KALSHI_MAX_RETRIES = 3
KALSHI_BACKOFF_BASE = 2.0
KALSHI_RETRY_STATUSES = {429, 500, 502, 503, 504}
KALSHI_CIRCUIT_FAILURE_THRESHOLD = 5
KALSHI_CIRCUIT_RECOVERY_TIMEOUT = 30.0


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
    """

    def __init__(self, tier: str = "basic") -> None:
        limits = KALSHI_RATE_TIERS.get(tier, KALSHI_RATE_TIERS["basic"])
        self.tier = tier
        self.read_rate: float = limits["read"]
        self.write_rate: float = limits["write"]
        self._read_tokens: float = self.read_rate
        self._write_tokens: float = self.write_rate
        self._last_refill: float = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._read_tokens = min(self.read_rate, self._read_tokens + elapsed * self.read_rate)
        self._write_tokens = min(self.write_rate, self._write_tokens + elapsed * self.write_rate)
        self._last_refill = now

    async def acquire(self, is_write: bool = False) -> float:
        """Acquire a token, sleeping if necessary. Returns wait time in seconds."""
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
        await asyncio.sleep(wait)
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


class KalshiVenueClient(EventVenueClient):
    """
    Kalshi implementation of EventVenueClient.
    
    Uses Kalshi REST API (v2) for trading operations.
    Supports both email/password auth and RSA key auth.
    
    Resilience features:
    - Circuit breaker: Opens after 5 failures, recovers after 30s
    - Retry with backoff: 3 retries with exponential backoff (2^n seconds)
    - Explicit results: All methods return OperationResult for clear error handling
    """
    
    def __init__(self, config: Optional[KalshiConfig] = None, rate_tier: str = "basic"):
        self.config = config or KalshiConfig()
        self._http_client: Optional[httpx.AsyncClient] = None
        self._auth_token: Optional[str] = None
        self._member_id: Optional[str] = None
        
        # Resilience: one circuit breaker per venue instance
        self._circuit_breaker = get_circuit_breaker(
            f"kalshi_{id(self)}",
            failure_threshold=KALSHI_CIRCUIT_FAILURE_THRESHOLD,
            recovery_timeout=KALSHI_CIRCUIT_RECOVERY_TIMEOUT,
        )
        
        # Token bucket: self-limit requests before hitting 429s
        self._rate_limiter = KalshiTokenBucket(tier=rate_tier)
        
    @property
    def venue_name(self) -> str:
        return "kalshi"
    
    async def _ensure_client(self) -> httpx.AsyncClient:
        """Ensure HTTP client is initialized and authenticated."""
        if self._http_client is None or self._http_client.is_closed:
            logger.info("[kalshi] Initializing new HTTP client")
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout),
                headers={
                    "User-Agent": "MERID-Kalshi-Client/1.0",
                    "Content-Type": "application/json"
                }
            )
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
            
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Kalshi authentication failed: {e}")
            raise
    
    async def _authenticate_rsa(self) -> None:
        """Load RSA private key for per-request signing.

        Kalshi RSA auth signs every request: timestamp_ms + METHOD + path + body.
        Signature uses PSS padding with SHA-256.

        Key loading priority:
          1. private_key_path (file on disk)
          2. private_key_pem  (inline PEM string from env/settings)
        """
        try:
            from cryptography.hazmat.primitives import serialization

            pem_bytes: Optional[bytes] = None
            if self.config.private_key_path:
                with open(self.config.private_key_path, "rb") as f:
                    pem_bytes = f.read()
                logger.info(f"Loaded Kalshi RSA key from file: {self.config.private_key_path}")
            elif getattr(self.config, "private_key_pem", None):
                pem_bytes = self.config.private_key_pem.encode()
                logger.info("Loaded Kalshi RSA key from inline PEM (KALSHI_PRIVATE_KEY_PEM)")

            if pem_bytes is None:
                raise ValueError("No RSA key source: set private_key_path or private_key_pem")

            self._private_key = serialization.load_pem_private_key(pem_bytes, password=None)
            self._auth_mode = "rsa"
            logger.info(f"Kalshi RSA auth ready (key_id: {self.config.api_key[:8]}...)")
        except ImportError:
            logger.warning("cryptography package not installed — RSA auth unavailable, falling back")
            if self.config.email and self.config.password:
                await self._authenticate_password()
        except (FileNotFoundError, ValueError, OSError) as e:
            logger.error(f"Failed to load Kalshi RSA key: {e}")
            if self.config.email and self.config.password:
                await self._authenticate_password()

    def _sign_headers(self, method: str, path: str, body: str = "") -> Dict[str, str]:
        """Generate Kalshi RSA auth headers for a single request.

        Args:
            method: HTTP method (GET, POST, DELETE)
            path: Full API path (e.g. /trade-api/v2/portfolio/orders)
            body: JSON body string (empty for GET/DELETE)

        Returns:
            Dict with KALSHI-ACCESS-KEY, KALSHI-ACCESS-TIMESTAMP, KALSHI-ACCESS-SIGNATURE
        """
        if not hasattr(self, "_private_key") or self._private_key is None:
            raise RuntimeError("RSA private key not loaded. Check credentials and private_key_path.")

        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        ts_ms = str(int(time.time() * 1000))
        message = ts_ms + method.upper() + path + body
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
        """Close connections."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
    
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

        client = await self._ensure_client()

        for attempt in range(KALSHI_MAX_RETRIES + 1):
            try:
                # Token bucket: self-limit before hitting 429s
                is_write = method.upper() in ("POST", "PUT", "DELETE", "PATCH")
                await self._rate_limiter.acquire(is_write=is_write)

                # RSA per-request signing: sign(timestamp + METHOD + full_path + body)
                extra_headers: Dict[str, str] = {}
                if getattr(self, "_auth_mode", None) == "rsa":
                    body_str = json.dumps(json_data) if json_data else ""
                    # Kalshi expects the full path including /trade-api/v2 prefix
                    full_path = f"/trade-api/v2{path}"
                    extra_headers = self._sign_headers(method.upper(), full_path, body_str)

                # Check circuit breaker before making request
                async with self._circuit_breaker:
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
                            # For 429, honour Retry-After header if present
                            if response.status_code == 429:
                                retry_after = response.headers.get("Retry-After")
                                try:
                                    wait_time = float(retry_after) if retry_after else KALSHI_BACKOFF_BASE ** attempt
                                except (ValueError, TypeError):
                                    wait_time = KALSHI_BACKOFF_BASE ** attempt
                                logger.warning(
                                    f"[kalshi] {operation_name} rate-limited (429), "
                                    f"Retry-After={retry_after}, sleeping {wait_time}s (attempt {attempt + 1})"
                                )
                            else:
                                wait_time = KALSHI_BACKOFF_BASE ** attempt
                                logger.debug(
                                    f"[kalshi] {operation_name} returned {response.status_code}, "
                                    f"retrying in {wait_time}s (attempt {attempt + 1})"
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
                        logger.debug(
                            f"[kalshi] {operation_name} auth error "
                            f"{response.status_code}: {body_text}. "
                            f"Check: key ID, private key path, timestamp (ms), "
                            f"signed path starts with /trade-api/v2/"
                        )
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
                        logger.error(
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

                    # Service unavailable (503) — session-level
                    if response.status_code == 503:
                        logger.error(
                            f"[kalshi] {operation_name} service unavailable (503)"
                        )
                        error = KalshiSessionError(
                            f"503 Service unavailable"
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
                    
                    return OperationResult.ok(
                        data,
                        latency_ms=latency_ms,
                        retries=attempt,
                        operation=operation_name,
                    )
                    
            except CircuitOpenError as e:
                # Circuit is open - fail fast
                latency_ms = (time.time() - start_time) * 1000
                logger.debug(f"[kalshi] Circuit open for {operation_name}: {e}")
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
                    wait_time = KALSHI_BACKOFF_BASE ** attempt
                    logger.warning(
                        f"[kalshi] {operation_name} timeout, retrying in {wait_time}s "
                        f"(attempt {attempt + 1})"
                    )
                    await asyncio.sleep(wait_time)
                    continue
                    
            except (httpx.ConnectError, httpx.ReadError) as e:
                last_error = e
                if attempt < KALSHI_MAX_RETRIES:
                    wait_time = KALSHI_BACKOFF_BASE ** attempt
                    logger.warning(
                        f"[kalshi] {operation_name} connection error, retrying in {wait_time}s "
                        f"(attempt {attempt + 1}): {e}"
                    )
                    await asyncio.sleep(wait_time)
                    continue
                    
            except Exception as e:
                # Unexpected error - don't retry
                latency_ms = (time.time() - start_time) * 1000
                logger.error(f"[kalshi] Unexpected error in {operation_name}: {e}")
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
    
    # ------------------------------------------------------------------------
    # Trading
    # ------------------------------------------------------------------------
    
    async def place_order(self, order: VenueOrder) -> Optional[PlacedOrder]:
        """Place order on Kalshi.
        
        Returns None on failure for backward compatibility.
        Use place_order_result() for explicit error handling.
        """
        result = await self.place_order_result(order)
        return result.unwrap_or(None)
    
    async def place_order_result(self, order: VenueOrder) -> OperationResult[Optional[PlacedOrder]]:
        """Place order with explicit result.

        Kalshi order format:
          POST /portfolio/orders
          {ticker, side, action, type, count, {side}_price, time_in_force, client_order_id}
        """
        outcome = order.outcome_id or "yes"
        kalshi_order: Dict[str, Any] = {
            "ticker": order.market_id,
            "action": order.side,           # "buy" or "sell"
            "side": outcome,                # "yes" or "no"
            "count": int(order.size),
            "type": order.order_type,       # "limit" or "market"
            "client_order_id": order.client_order_id or f"merid_{datetime.now().timestamp()}",
        }

        if order.order_type == "limit" and order.price:
            # Kalshi uses {side}_price: yes_price or no_price (cents, integer)
            kalshi_order[f"{outcome}_price"] = int(order.price * 100)

        # Map MERID time_in_force to Kalshi (gtc, ioc, fok)
        tif_map = {"GTC": "gtc", "IOC": "ioc", "FOK": "fok"}
        kalshi_order["time_in_force"] = tif_map.get(
            getattr(order, "time_in_force", "GTC"), "gtc"
        )

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
        """Cancel order with explicit result."""
        result = await self._request_with_resilience(
            "DELETE", f"/orders/{order_id}", operation_name=f"cancel_order({order_id})"
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
            "GET", f"/orders/{order_id}", operation_name=f"get_order({order_id})"
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
    
    async def get_open_orders(self, market_id: Optional[str] = None) -> List[PlacedOrder]:
        """Get open orders. Returns empty list on failure."""
        result = await self.get_open_orders_result(market_id)
        return result.unwrap_or([])
    
    async def get_open_orders_result(
        self, market_id: Optional[str] = None
    ) -> OperationResult[List[PlacedOrder]]:
        """Get open orders with explicit result."""
        params = {"status": "open"}
        if market_id:
            params["ticker"] = market_id
        
        result = await self._request_with_resilience(
            "GET", "/orders", params=params, operation_name="get_open_orders"
        )
        
        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
            )
        
        orders = []
        for order_data in result.data.get("orders", []):
            order = self._to_placed_order(order_data)
            if order:
                orders.append(order)
        
        return OperationResult.ok(
            orders,
            latency_ms=result.latency_ms,
            retries=result.retries,
        )
    
    # ------------------------------------------------------------------------
    # Account Data
    # ------------------------------------------------------------------------
    
    async def get_positions(self) -> List[VenuePosition]:
        """Get positions. Returns empty list on failure."""
        result = await self.get_positions_result()
        return result.unwrap_or([])
    
    async def get_positions_result(self) -> OperationResult[List[VenuePosition]]:
        """Get positions with explicit result."""
        result = await self._request_with_resilience(
            "GET", "/portfolio/positions", operation_name="get_positions"
        )
        
        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
            )
        
        positions = []
        for pos_data in result.data.get("positions", []):
            position = self._parse_position(pos_data)
            if position:
                positions.append(self._to_venue_position(position))
        
        return OperationResult.ok(
            positions,
            latency_ms=result.latency_ms,
            retries=result.retries,
        )
    
    async def get_trades(self, limit: int = 100) -> List[VenueTrade]:
        """Get trade history. Returns empty list on failure."""
        result = await self.get_trades_result(limit)
        return result.unwrap_or([])
    
    async def get_trades_result(self, limit: int = 100) -> OperationResult[List[VenueTrade]]:
        """Get trade history with explicit result."""
        result = await self._request_with_resilience(
            "GET", "/portfolio/trades", params={"limit": limit}, operation_name="get_trades"
        )
        
        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
            )
        
        trades = []
        for trade_data in result.data.get("trades", []):
            trade = self._parse_trade(trade_data)
            if trade:
                trades.append(self._to_venue_trade(trade))
        
        return OperationResult.ok(
            trades,
            latency_ms=result.latency_ms,
            retries=result.retries,
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
            logger.error(f"Failed to parse Kalshi market: {e}")
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
            pass
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
            raw_data={"series_ticker": market.series_ticker, "event_ticker": market.event_ticker}
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
            logger.error(f"Failed to parse Kalshi order: {e}")
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
            logger.error(f"Failed to parse Kalshi position: {e}")
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
            logger.error(f"Failed to parse Kalshi trade: {e}")
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
        pages = 0

        while True:
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


# ── Singleton ────────────────────────────────────────────────────────────

_client: Optional[KalshiVenueClient] = None


def get_kalshi_client(config: Optional[KalshiConfig] = None) -> KalshiVenueClient:
    """Get or create the singleton KalshiVenueClient."""
    global _client
    if _client is None:
        _client = KalshiVenueClient(config)
    return _client
