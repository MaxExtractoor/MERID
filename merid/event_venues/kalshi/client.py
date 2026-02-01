"""Kalshi REST client - Implements EventVenueClient interface."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

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
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.client")


class KalshiVenueClient(EventVenueClient):
    """
    Kalshi implementation of EventVenueClient.
    
    Uses Kalshi REST API (v2) for trading operations.
    Supports both email/password auth and RSA key auth.
    """
    
    def __init__(self, config: Optional[KalshiConfig] = None):
        self.config = config or KalshiConfig()
        self._http_client: Optional[httpx.AsyncClient] = None
        self._auth_token: Optional[str] = None
        self._member_id: Optional[str] = None
        
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
    # Market Data
    # ------------------------------------------------------------------------
    
    async def list_markets(self, filter_params: Optional[MarketFilter] = None) -> List[EventMarket]:
        """List Kalshi markets."""
        filter_params = filter_params or MarketFilter()
        
        try:
            url = f"{self.config.base_url}/markets"
            params = {"limit": filter_params.limit, "status": "active" if filter_params.active_only else None}
            
            if filter_params.category:
                params["category"] = filter_params.category
            
            response = await self._http_client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            markets = []
            for market_data in data.get("markets", []):
                market = self._parse_market(market_data)
                if market:
                    markets.append(self._to_event_market(market))
            
            return markets
            
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Failed to list Kalshi markets: {e}")
            return []
    
    async def get_market(self, market_id: str) -> Optional[EventMarket]:
        """Get market details by ticker."""
        try:
            url = f"{self.config.base_url}/markets/{market_id}"
            response = await self._http_client.get(url)
            response.raise_for_status()
            data = response.json()
            
            market = self._parse_market(data.get("market", data))
            return self._to_event_market(market) if market else None
            
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Failed to get Kalshi market {market_id}: {e}")
            return None
    
    async def get_orderbook(self, market_id: str, outcome_id: Optional[str] = None) -> Optional[VenueOrderBook]:
        """Get order book for a market."""
        try:
            url = f"{self.config.base_url}/markets/{market_id}/orderbook"
            response = await self._http_client.get(url)
            response.raise_for_status()
            data = response.json()
            
            return self._to_venue_orderbook(data, market_id)
            
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Failed to get Kalshi orderbook: {e}")
            return None
    
    # ------------------------------------------------------------------------
    # Trading
    # ------------------------------------------------------------------------
    
    async def place_order(self, order: VenueOrder) -> Optional[PlacedOrder]:
        """Place order on Kalshi."""
        try:
            url = f"{self.config.base_url}/orders"
            
            # Convert to Kalshi format
            kalshi_order = {
                "ticker": order.market_id,
                "action": order.side,  # "buy" or "sell"
                "side": order.outcome_id or "yes",  # "yes" or "no"
                "count": int(order.size),
                "type": order.order_type,  # "limit" or "market"
                "client_order_id": order.client_order_id or f"merid_{datetime.now().timestamp()}"
            }
            
            if order.order_type == "limit" and order.price:
                # Kalshi prices are in cents (0-100)
                kalshi_order["price"] = int(order.price * 100)
            
            response = await self._http_client.post(url, json=kalshi_order)
            response.raise_for_status()
            data = response.json()
            
            return self._to_placed_order(data.get("order", data))
            
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Failed to place Kalshi order: {e}")
            return None
    
    async def cancel_order(self, order_id: str, market_id: Optional[str] = None) -> bool:
        """Cancel an order."""
        try:
            url = f"{self.config.base_url}/orders/{order_id}"
            response = await self._http_client.delete(url)
            response.raise_for_status()
            return True
            
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Failed to cancel Kalshi order: {e}")
            return False
    
    async def get_order(self, order_id: str, market_id: Optional[str] = None) -> Optional[PlacedOrder]:
        """Get order status."""
        try:
            url = f"{self.config.base_url}/orders/{order_id}"
            response = await self._http_client.get(url)
            response.raise_for_status()
            data = response.json()
            
            return self._to_placed_order(data.get("order", data))
            
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Failed to get Kalshi order: {e}")
            return None
    
    async def get_open_orders(self, market_id: Optional[str] = None) -> List[PlacedOrder]:
        """Get open orders."""
        try:
            url = f"{self.config.base_url}/orders"
            params = {"status": "open"}
            if market_id:
                params["ticker"] = market_id
                
            response = await self._http_client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            orders = []
            for order_data in data.get("orders", []):
                order = self._to_placed_order(order_data)
                if order:
                    orders.append(order)
            
            return orders
            
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Failed to get Kalshi open orders: {e}")
            return []
    
    # ------------------------------------------------------------------------
    # Account Data
    # ------------------------------------------------------------------------
    
    async def get_positions(self) -> List[VenuePosition]:
        """Get positions."""
        try:
            url = f"{self.config.base_url}/portfolio/positions"
            response = await self._http_client.get(url)
            response.raise_for_status()
            data = response.json()
            
            positions = []
            for pos_data in data.get("positions", []):
                position = self._parse_position(pos_data)
                if position:
                    positions.append(self._to_venue_position(position))
            
            return positions
            
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Failed to get Kalshi positions: {e}")
            return []
    
    async def get_trades(self, limit: int = 100) -> List[VenueTrade]:
        """Get trade history."""
        try:
            url = f"{self.config.base_url}/portfolio/trades"
            params = {"limit": limit}
            
            response = await self._http_client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            trades = []
            for trade_data in data.get("trades", []):
                trade = self._parse_trade(trade_data)
                if trade:
                    trades.append(self._to_venue_trade(trade))
            
            return trades
            
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Failed to get Kalshi trades: {e}")
            return []
    
    async def get_balance(self) -> Dict[str, Decimal]:
        """Get account balance."""
        try:
            url = f"{self.config.base_url}/portfolio/balance"
            response = await self._http_client.get(url)
            response.raise_for_status()
            data = response.json()
            
            balance = data.get("balance", {})
            return {
                "USD": Decimal(str(balance.get("balance", 0))) / 100,  # Convert cents to dollars
                "locked": Decimal(str(balance.get("locked_balance", 0))) / 100
            }
            
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Failed to get Kalshi balance: {e}")
            return {"USD": Decimal("0"), "locked": Decimal("0")}
    
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
