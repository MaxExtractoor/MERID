"""Polymarket REST client - Implements EventVenueClient interface.

This is a **resilient venue client** implementation.
Pattern: circuit breaker per venue, retry with backoff on I/O,
explicit OperationResult returns instead of silent fallbacks.
"""

from __future__ import annotations

import asyncio
import json
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional, TypeVar

import aiohttp

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
from merid.event_venues.polymarket.models import (
    Market,
    MarketOutcome,
    Order,
    OrderBook,
    PolymarketConfig,
    Position,
    Trade,
)
from merid.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    OperationResult,
    get_circuit_breaker,
    get_bulkhead,
    BulkheadFullError,
)
from utils.logger import get_logger

logger = get_logger("merid.event_venues.polymarket.client")

T = TypeVar("T")

# Retry configuration for Polymarket
POLYMARKET_MAX_RETRIES = 3
POLYMARKET_BACKOFF_BASE = 2.0
POLYMARKET_RETRY_STATUSES = {429, 500, 502, 503, 504}
POLYMARKET_CIRCUIT_FAILURE_THRESHOLD = 5
POLYMARKET_CIRCUIT_RECOVERY_TIMEOUT = 30.0


class PolymarketVenueClient(EventVenueClient):
    """
    Polymarket implementation of EventVenueClient.
    
    Wraps Gamma API, CLOB client, and Data API into unified interface.
    """
    
    def __init__(self, config: Optional[PolymarketConfig] = None):
        self.config = config or PolymarketConfig()
        self._http_client: Optional[aiohttp.ClientSession] = None
        self._clob_client = None
        
        # Resilience: circuit breaker for this venue
        self._circuit_breaker = get_circuit_breaker(
            "polymarket",
            failure_threshold=POLYMARKET_CIRCUIT_FAILURE_THRESHOLD,
            recovery_timeout=POLYMARKET_CIRCUIT_RECOVERY_TIMEOUT,
        )
        
        # Resilience: bulkhead for concurrency isolation
        self._bulkhead = get_bulkhead(
            "polymarket",
            max_concurrent=10,
            max_queued=50,
            timeout=30.0,
        )
        
    @property
    def venue_name(self) -> str:
        return "polymarket"
    
    async def connect(self) -> None:
        """Initialize HTTP clients."""
        self._http_client = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.config.timeout),
            headers={"User-Agent": "MERID-Polymarket-Client/1.0"}
        )
        
        # Initialize CLOB client for trading
        if self.config.api_key and self.config.api_secret:
            try:
                from polymarket_clob import ClobClient
                self._clob_client = ClobClient(
                    api_key=self.config.api_key,
                    api_secret=self.config.api_secret,
                    chain_id="polygon"
                )
                logger.info("CLOB client initialized for trading")
            except ImportError:
                logger.warning("polymarket-clob package not installed, trading disabled")
        else:
            logger.info("CLOB credentials not provided, trading disabled")
    
    async def close(self) -> None:
        """Close all connections."""
        if self._http_client:
            await self._http_client.close()
    
    def get_circuit_status(self) -> dict:
        """Get circuit breaker status for this venue."""
        return self._circuit_breaker.get_stats()
    
    # ------------------------------------------------------------------------
    # Resilience: Request wrapper with circuit breaker and retry
    # ------------------------------------------------------------------------
    
    async def _request_with_resilience(
        self,
        method: str,
        url: str,
        operation: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> OperationResult[Dict[str, Any]]:
        """
        Execute HTTP request with circuit breaker and retry logic.
        
        Returns OperationResult instead of raising exceptions.
        """
        start_time = time.time()
        last_error: Optional[Exception] = None
        retries = 0
        
        for attempt in range(POLYMARKET_MAX_RETRIES + 1):
            try:
                async with self._bulkhead:
                  async with self._circuit_breaker:
                    if method.upper() == "GET":
                        async with self._http_client.get(url, params=params) as response:
                            latency_ms = (time.time() - start_time) * 1000
                            
                            if response.status in POLYMARKET_RETRY_STATUSES:
                                raise aiohttp.ClientResponseError(
                                    response.request_info,
                                    response.history,
                                    status=response.status,
                                )
                            
                            if response.status != 200:
                                return OperationResult.fail(
                                    ValueError(f"HTTP {response.status}"),
                                    latency_ms=latency_ms,
                                    retries=retries,
                                    operation=operation,
                                )
                            
                            data = await response.json()
                            return OperationResult.ok(
                                data,
                                latency_ms=latency_ms,
                                retries=retries,
                                operation=operation,
                            )
                    else:  # POST
                        async with self._http_client.post(url, json=json_data) as response:
                            latency_ms = (time.time() - start_time) * 1000
                            
                            if response.status in POLYMARKET_RETRY_STATUSES:
                                raise aiohttp.ClientResponseError(
                                    response.request_info,
                                    response.history,
                                    status=response.status,
                                )
                            
                            if response.status != 200:
                                return OperationResult.fail(
                                    ValueError(f"HTTP {response.status}"),
                                    latency_ms=latency_ms,
                                    retries=retries,
                                    operation=operation,
                                )
                            
                            data = await response.json()
                            return OperationResult.ok(
                                data,
                                latency_ms=latency_ms,
                                retries=retries,
                                operation=operation,
                            )
                            
            except CircuitOpenError as e:
                return OperationResult.fail(
                    e,
                    latency_ms=(time.time() - start_time) * 1000,
                    retries=retries,
                    operation=operation,
                )
            except BulkheadFullError as e:
                return OperationResult.fail(
                    e,
                    latency_ms=(time.time() - start_time) * 1000,
                    retries=retries,
                    operation=operation,
                )
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = e
                retries = attempt
                if attempt < POLYMARKET_MAX_RETRIES:
                    backoff = POLYMARKET_BACKOFF_BASE ** attempt
                    logger.warning(
                        f"Polymarket {operation} failed (attempt {attempt + 1}), "
                        f"retrying in {backoff:.1f}s: {e}"
                    )
                    await asyncio.sleep(backoff)
                    continue
                break
            except Exception as e:
                return OperationResult.fail(
                    e,
                    latency_ms=(time.time() - start_time) * 1000,
                    retries=retries,
                    operation=operation,
                )
        
        return OperationResult.fail(
            last_error or RuntimeError("Unknown error"),
            latency_ms=(time.time() - start_time) * 1000,
            retries=retries,
            operation=operation,
        )
    
    # ------------------------------------------------------------------------
    # Market Data (with _result suffix for explicit error handling)
    # ------------------------------------------------------------------------
    
    async def list_markets_result(
        self, filter_params: Optional[MarketFilter] = None
    ) -> OperationResult[List[EventMarket]]:
        """List markets with explicit OperationResult return."""
        filter_params = filter_params or MarketFilter()
        url = f"{self.config.gamma_api_base}/markets"
        params = {"limit": filter_params.limit}
        
        if filter_params.active_only:
            params["active"] = "true"
        if filter_params.category:
            params["category"] = filter_params.category
        if filter_params.search:
            params["search"] = filter_params.search
        
        result = await self._request_with_resilience("GET", url, "list_markets", params=params)
        
        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
                operation="list_markets",
            )
        
        # Parse markets
        data = result.data
        items = data if isinstance(data, list) else data.get("data", data.get("markets", []))
        
        markets = []
        for item in items:
            if isinstance(item, str):
                try:
                    item = json.loads(item)
                except (json.JSONDecodeError, ValueError):
                    continue
            if not isinstance(item, dict):
                continue
            
            market = self._parse_market(item)
            if market:
                markets.append(self._to_event_market(market))
        
        return OperationResult.ok(
            markets,
            latency_ms=result.latency_ms,
            retries=result.retries,
            operation="list_markets",
        )
    
    async def get_market_result(self, market_id: str) -> OperationResult[Optional[EventMarket]]:
        """Get market with explicit OperationResult return."""
        url = f"{self.config.gamma_api_base}/markets/{market_id}"
        
        result = await self._request_with_resilience("GET", url, "get_market")
        
        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
                operation="get_market",
            )
        
        market = self._parse_market(result.data)
        return OperationResult.ok(
            self._to_event_market(market) if market else None,
            latency_ms=result.latency_ms,
            retries=result.retries,
            operation="get_market",
        )
    
    async def get_orderbook_result(
        self, market_id: str, outcome_id: Optional[str] = None
    ) -> OperationResult[Optional[VenueOrderBook]]:
        """Get orderbook with explicit OperationResult return."""
        url = f"{self.config.gamma_api_base}/markets/{market_id}/orderbook"
        
        result = await self._request_with_resilience("GET", url, "get_orderbook")
        
        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
                operation="get_orderbook",
            )
        
        return OperationResult.ok(
            self._to_venue_orderbook(result.data, market_id, outcome_id),
            latency_ms=result.latency_ms,
            retries=result.retries,
            operation="get_orderbook",
        )
    
    async def get_positions_result(self) -> OperationResult[List[VenuePosition]]:
        """Get positions with explicit OperationResult return."""
        if not self.config.wallet_address:
            return OperationResult.fail(
                ValueError("No wallet address configured"),
                operation="get_positions",
            )
        
        query = """
        query GetPositions($address: String!) {
            user(address: $address) {
                positions {
                    id
                    market { id question }
                    outcome
                    size
                    averagePrice
                    unrealizedPnl
                    realizedPnl
                    createdAt
                }
            }
        }
        """
        
        result = await self._request_with_resilience(
            "POST",
            self.config.graphql_url,
            "get_positions",
            json_data={"query": query, "variables": {"address": self.config.wallet_address}},
        )
        
        if not result.success:
            return OperationResult.fail(
                result.error,
                latency_ms=result.latency_ms,
                retries=result.retries,
                operation="get_positions",
            )
        
        return OperationResult.ok(
            self._parse_positions(result.data),
            latency_ms=result.latency_ms,
            retries=result.retries,
            operation="get_positions",
        )
    
    # ------------------------------------------------------------------------
    # Market Data (backward-compatible methods)
    # ------------------------------------------------------------------------
    
    async def list_markets(self, filter_params: Optional[MarketFilter] = None) -> List[EventMarket]:
        """List markets from Gamma API."""
        filter_params = filter_params or MarketFilter()
        url = f"{self.config.gamma_api_base}/markets"
        params = {"limit": filter_params.limit}
        
        if filter_params.active_only:
            params["active"] = "true"
        if filter_params.category:
            params["category"] = filter_params.category
        if filter_params.search:
            params["search"] = filter_params.search
        
        try:
            async with self._http_client.get(url, params=params) as response:
                if response.status != 200:
                    logger.error(f"Gamma API returned {response.status}")
                    return []
                
                data = await response.json()
                items = data if isinstance(data, list) else data.get("data", data.get("markets", []))
                
                markets = []
                for item in items:
                    if isinstance(item, str):
                        try:
                            item = json.loads(item)
                        except (json.JSONDecodeError, ValueError):
                            continue
                    if not isinstance(item, dict):
                        continue
                    
                    market = self._parse_market(item)
                    if market:
                        markets.append(self._to_event_market(market))
                
                return markets
                
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Failed to fetch markets: {e}")
            return []
    
    async def get_market(self, market_id: str) -> Optional[EventMarket]:
        """Get market details."""
        url = f"{self.config.gamma_api_base}/markets/{market_id}"
        
        try:
            async with self._http_client.get(url) as response:
                if response.status != 200:
                    return None
                data = await response.json()
                market = self._parse_market(data)
                return self._to_event_market(market) if market else None
                
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Failed to fetch market: {e}")
            return None
    
    async def get_orderbook(self, market_id: str, outcome_id: Optional[str] = None) -> Optional[VenueOrderBook]:
        """Get order book."""
        url = f"{self.config.gamma_api_base}/markets/{market_id}/orderbook"
        
        try:
            async with self._http_client.get(url) as response:
                if response.status != 200:
                    return None
                data = await response.json()
                return self._to_venue_orderbook(data, market_id, outcome_id)
                
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Failed to fetch orderbook: {e}")
            return None
    
    # ------------------------------------------------------------------------
    # Trading
    # ------------------------------------------------------------------------
    
    async def place_order(self, order: VenueOrder) -> Optional[PlacedOrder]:
        """Place order via CLOB."""
        if not self._clob_client:
            logger.error("CLOB client not initialized")
            return None
        
        try:
            result = await self._clob_client.place_order(
                market_id=order.market_id,
                outcome=order.outcome_id or "",
                side=order.side,
                size=order.size,
                price=order.price or Decimal("0"),
                order_type=order.order_type
            )
            return self._to_placed_order(result)
            
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Failed to place order: {e}")
            return None
    
    async def cancel_order(self, order_id: str, market_id: Optional[str] = None) -> bool:
        """Cancel order."""
        if not self._clob_client:
            return False
        
        try:
            await self._clob_client.cancel_order(order_id)
            return True
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Failed to cancel order: {e}")
            return False
    
    async def get_order(self, order_id: str, market_id: Optional[str] = None) -> Optional[PlacedOrder]:
        """Get order status."""
        if not self._clob_client:
            return None
        
        try:
            orders = await self._clob_client.get_open_orders()
            for order in orders:
                if order.get("id") == order_id:
                    return self._to_placed_order(order)
            return None
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Failed to get order: {e}")
            return None
    
    async def get_open_orders(self, market_id: Optional[str] = None) -> List[PlacedOrder]:
        """Get open orders."""
        if not self._clob_client:
            return []
        
        try:
            orders = await self._clob_client.get_open_orders()
            return [self._to_placed_order(o) for o in orders]
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Failed to fetch orders: {e}")
            return []
    
    # ------------------------------------------------------------------------
    # Account Data
    # ------------------------------------------------------------------------
    
    async def get_positions(self) -> List[VenuePosition]:
        """Get positions via GraphQL."""
        if not self.config.wallet_address:
            logger.error("No wallet address configured")
            return []
        
        query = """
        query GetPositions($address: String!) {
            user(address: $address) {
                positions {
                    id
                    market { id question }
                    outcome
                    size
                    averagePrice
                    unrealizedPnl
                    realizedPnl
                    createdAt
                }
            }
        }
        """
        
        try:
            async with self._http_client.post(
                self.config.graphql_url,
                json={"query": query, "variables": {"address": self.config.wallet_address}}
            ) as response:
                if response.status != 200:
                    return []
                data = await response.json()
                return self._parse_positions(data)
                
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Failed to fetch positions: {e}")
            return []
    
    async def get_trades(self, limit: int = 100) -> List[VenueTrade]:
        """Get trade history."""
        if not self.config.wallet_address:
            return []
        
        url = f"{self.config.data_api_base}/trades"
        params = {"address": self.config.wallet_address, "limit": limit}
        
        try:
            async with self._http_client.get(url, params=params) as response:
                if response.status != 200:
                    return []
                data = await response.json()
                return self._parse_trades(data)
                
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Failed to fetch trades: {e}")
            return []
    
    async def get_balance(self) -> Dict[str, Decimal]:
        """Get account balance."""
        # Polymarket uses USDC on Polygon
        # Would need to query token balance
        return {"USDC": Decimal("0")}  # Placeholder
    
    # ------------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------------
    
    def _parse_market(self, data: Dict[str, Any]) -> Optional[Market]:
        """Parse market from API."""
        from datetime import datetime, timezone
        
        try:
            outcomes = []
            for outcome_data in data.get("outcomes", []):
                price = Decimal(str(outcome_data.get("price", 0)))
                outcomes.append(MarketOutcome(
                    outcome=outcome_data.get("outcome", ""),
                    price=price,
                    probability=price * 100,
                    best_ask_price=Decimal(str(outcome_data.get("bestAskPrice", 0))),
                    best_bid_price=Decimal(str(outcome_data.get("bestBidPrice", 0)))
                ))
            
            end_date = None
            if data.get("endDate"):
                end_date = datetime.fromisoformat(data["endDate"].replace("Z", "+00:00"))
            
            created_at = None
            if data.get("createdAt"):
                created_at = datetime.fromisoformat(data["createdAt"].replace("Z", "+00:00"))
            
            return Market(
                id=data.get("id", ""),
                question=data.get("question", ""),
                description=data.get("description", ""),
                outcomes=outcomes,
                end_date=end_date,
                active=data.get("active", True),
                volume=Decimal(str(data.get("volume", 0))),
                liquidity=Decimal(str(data.get("liquidity", 0))),
                category=data.get("category"),
                tags=data.get("tags", []),
                created_at=created_at,
                resolution=data.get("resolution"),
                resolved_at=datetime.fromisoformat(data["resolvedAt"].replace("Z", "+00:00")) if data.get("resolvedAt") else None
            )
        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"Failed to parse market: {e}")
            return None
    
    def _to_event_market(self, market: Market) -> EventMarket:
        """Convert to venue-agnostic EventMarket."""
        from datetime import timezone
        
        return EventMarket(
            market_id=market.id,
            venue="polymarket",
            question=market.question,
            description=market.description,
            outcomes=[
                EventOutcome(
                    outcome_id=o.outcome,
                    outcome_name=o.outcome,
                    price=o.price,
                    probability=o.probability,
                    best_ask=o.best_ask_price,
                    best_bid=o.best_bid_price
                )
                for o in market.outcomes
            ],
            category=market.category,
            tags=market.tags,
            end_date=market.end_date,
            active=market.active,
            volume=market.volume,
            liquidity=market.liquidity,
            created_at=market.created_at,
            resolved=bool(market.resolution),
            resolution=market.resolution,
            resolved_at=market.resolved_at
        )
    
    def _to_venue_orderbook(self, data: Dict[str, Any], market_id: str, outcome_id: Optional[str]) -> VenueOrderBook:
        """Convert to VenueOrderBook."""
        
        bids = [(Decimal(str(b[0])), Decimal(str(b[1]))) for b in data.get("bids", [])]
        asks = [(Decimal(str(a[0])), Decimal(str(a[1]))) for a in data.get("asks", [])]
        
        return VenueOrderBook(
            market_id=market_id,
            outcome_id=outcome_id,
            bids=bids,
            asks=asks,
            timestamp=datetime.now(timezone.utc),
            venue="polymarket"
        )
    
    def _to_placed_order(self, data: Dict[str, Any]) -> PlacedOrder:
        """Convert to PlacedOrder."""
        
        return PlacedOrder(
            order_id=data.get("id", ""),
            market_id=data.get("marketId", ""),
            side=data.get("side", ""),
            size=Decimal(str(data.get("size", 0))),
            price=Decimal(str(data.get("price", 0))) if data.get("price") else None,
            filled_size=Decimal(str(data.get("filled", 0))),
            remaining_size=Decimal(str(data.get("remaining", 0))),
            status=data.get("status", "pending"),
            venue="polymarket",
            created_at=datetime.fromisoformat(data.get("createdAt", "").replace("Z", "+00:00")) if data.get("createdAt") else None
        )
    
    def _parse_positions(self, data: Dict[str, Any]) -> List[VenuePosition]:
        """Parse positions from GraphQL."""
        from datetime import datetime
        positions = []
        for pos_data in data.get("data", {}).get("user", {}).get("positions", []):
            positions.append(VenuePosition(
                market_id=pos_data.get("market", {}).get("id", ""),
                outcome_id=pos_data.get("outcome"),
                size=Decimal(str(pos_data.get("size", 0))),
                average_entry_price=Decimal(str(pos_data.get("averagePrice", 0))),
                unrealized_pnl=Decimal(str(pos_data.get("unrealizedPnl", 0))),
                realized_pnl=Decimal(str(pos_data.get("realizedPnl", 0))),
                venue="polymarket",
                created_at=datetime.fromisoformat(pos_data.get("createdAt", "").replace("Z", "+00:00")) if pos_data.get("createdAt") else None
            ))
        return positions
    
    def _parse_trades(self, data: Dict[str, Any]) -> List[VenueTrade]:
        """Parse trades from Data API."""
        trades = []
        for trade_data in data.get("trades", []):
            trades.append(VenueTrade(
                trade_id=trade_data.get("id", ""),
                market_id=trade_data.get("marketId", ""),
                order_id=trade_data.get("orderId", ""),
                side=trade_data.get("side", ""),
                size=Decimal(str(trade_data.get("size", 0))),
                price=Decimal(str(trade_data.get("price", 0))),
                fee=Decimal(str(trade_data.get("fee", 0))),
                timestamp=datetime.fromisoformat(trade_data.get("timestamp", "").replace("Z", "+00:00")),
                venue="polymarket"
            ))
        return trades
