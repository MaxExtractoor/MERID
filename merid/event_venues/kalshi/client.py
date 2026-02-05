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
    
    def __init__(self, config: Optional[KalshiConfig] = None):
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
        
    @property
    def venue_name(self) -> str:
        return "kalshi"
    
    async def connect(self) -> None:
        """Initialize HTTP client and authenticate."""
        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.timeout),
            headers={
                "User-Agent": "MERID-Kalshi-Client/1.0",
                "Content-Type": "application/json"
            }
        )
        
        # Authenticate
        await self._authenticate()
    
    async def _authenticate(self) -> None:
        """Authenticate with Kalshi API."""
        if self.config.api_key and self.config.private_key_path:
            # RSA key authentication
            await self._authenticate_rsa()
        elif self.config.email and self.config.password:
            # Email/password authentication
            await self._authenticate_password()
        else:
            logger.warning("No Kalshi credentials provided, operations will fail")
    
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
        """Authenticate with RSA key (not implemented - placeholder)."""
        # RSA auth requires signing requests with private key
        # For now, use password auth or implement RSA signing
        logger.warning("RSA auth not yet implemented, falling back to password auth if available")
        if self.config.email and self.config.password:
            await self._authenticate_password()
    
    async def close(self) -> None:
        """Close connections."""
        if self._http_client:
            await self._http_client.aclose()
    
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
                # Check circuit breaker before making request
                async with self._circuit_breaker:
                    response = await self._http_client.request(
                        method=method,
                        url=url,
                        params=params,
                        json=json_data,
                    )
                    
                    latency_ms = (time.time() - start_time) * 1000
                    
                    # Check for retryable status codes
                    if response.status_code in KALSHI_RETRY_STATUSES:
                        if attempt < KALSHI_MAX_RETRIES:
                            wait_time = KALSHI_BACKOFF_BASE ** attempt
                            logger.warning(
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
                    
                    # Check for client errors (4xx) - don't retry
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
                logger.warning(f"[kalshi] Circuit open for {operation_name}: {e}")
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
        
        Returns:
            OperationResult containing list of markets or error details
        """
        filter_params = filter_params or MarketFilter()
        params = {
            "limit": filter_params.limit,
            "status": "active" if filter_params.active_only else None,
        }
        if filter_params.category:
            params["category"] = filter_params.category
        
        result = await self._request_with_resilience(
            "GET", "/markets", params=params, operation_name="list_markets"
        )
        
        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
            )
        
        markets = []
        for market_data in result.data.get("markets", []):
            market = self._parse_market(market_data)
            if market:
                markets.append(self._to_event_market(market))
        
        return OperationResult.ok(
            markets,
            latency_ms=result.latency_ms,
            retries=result.retries,
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
        """Place order with explicit result."""
        # Convert to Kalshi format
        kalshi_order = {
            "ticker": order.market_id,
            "action": order.side,
            "side": order.outcome_id or "yes",
            "count": int(order.size),
            "type": order.order_type,
            "client_order_id": order.client_order_id or f"merid_{datetime.now().timestamp()}"
        }
        
        if order.order_type == "limit" and order.price:
            kalshi_order["price"] = int(order.price * 100)
        
        result = await self._request_with_resilience(
            "POST", "/orders", json_data=kalshi_order, operation_name="place_order"
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
        
        balance = result.data.get("balance", {})
        return OperationResult.ok(
            {
                "USD": Decimal(str(balance.get("balance", 0))) / 100,
                "locked": Decimal(str(balance.get("locked_balance", 0))) / 100
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
            yes_price = data.get("yes_price", data.get("yes_ask", 0))
            no_price = data.get("no_price", data.get("no_ask", 0))
            
            if yes_price:
                outcomes.append(KalshiOutcome(
                    outcome_id="yes",
                    name="Yes",
                    price=Decimal(str(yes_price)),
                    probability=Decimal(str(yes_price)) / 100 if yes_price else None
                ))
            
            if no_price:
                outcomes.append(KalshiOutcome(
                    outcome_id="no",
                    name="No",
                    price=Decimal(str(no_price)),
                    probability=Decimal(str(no_price)) / 100 if no_price else None
                ))
            
            return KalshiMarket(
                ticker=data.get("ticker", ""),
                event_ticker=data.get("event_ticker", ""),
                title=data.get("title", data.get("question", "")),
                description=data.get("description", ""),
                outcomes=outcomes,
                category=data.get("category"),
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
            liquidity=market.liquidity,
            created_at=market.created_at,
            resolved=market.status == "settled",
            resolution=None,
            resolved_at=market.settlement_time
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
