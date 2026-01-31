"""
MERID Polymarket Client Integration

Provides a unified, typed interface for Polymarket operations:
- Market discovery and details via Gamma API
- Trading operations via CLOB client
- User data via Data API and GraphQL
- Real-time streaming via WebSockets

Environment Variables Required:
- POLYMARKET_API_KEY: CLOB API key for trading
- POLYMARKET_API_SECRET: CLOB API secret
- POLYMARKET_WALLET_ADDRESS: Wallet for trading
- POLYMARKET_PRIVATE_KEY: Private key for signing (optional)
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
from decimal import Decimal

import aiohttp
import httpx
from pydantic import BaseModel, Field

from utils.logger import get_logger

logger = get_logger("merid.polymarket_client")


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class MarketOutcome:
    """Represents a market outcome."""
    outcome: str
    price: Decimal
    probability: Decimal
    best_ask_price: Optional[Decimal] = None
    best_bid_price: Optional[Decimal] = None


@dataclass
class Market:
    """Represents a Polymarket market."""
    id: str
    question: str
    description: str
    outcomes: List[MarketOutcome]
    end_date: Optional[datetime] = None
    active: bool = True
    volume: Optional[Decimal] = None
    liquidity: Optional[Decimal] = None
    category: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    created_at: Optional[datetime] = None
    resolution: Optional[str] = None
    resolved_at: Optional[datetime] = None


@dataclass
class Order:
    """Represents a trading order."""
    id: str
    market_id: str
    outcome: str
    side: str  # "buy" or "sell"
    size: Decimal
    price: Decimal
    filled: Decimal = Decimal("0")
    remaining: Optional[Decimal] = None
    status: str = "pending"  # pending, filled, cancelled
    created_at: Optional[datetime] = None


@dataclass
class Position:
    """Represents a user position."""
    market_id: str
    outcome: str
    size: Decimal
    average_price: Decimal
    unrealized_pnl: Optional[Decimal] = None
    realized_pnl: Optional[Decimal] = None
    created_at: Optional[datetime] = None


@dataclass
class Trade:
    """Represents a trade execution."""
    id: str
    market_id: str
    outcome: str
    side: str
    size: Decimal
    price: Decimal
    fee: Decimal
    timestamp: datetime


@dataclass
class OrderBook:
    """Represents market order book."""
    market_id: str
    outcome: str
    bids: List[Tuple[Decimal, Decimal]]  # (price, size)
    asks: List[Tuple[Decimal, Decimal]]  # (price, size)
    timestamp: datetime


# ============================================================================
# Configuration
# ============================================================================

class PolymarketConfig:
    """Configuration for Polymarket client."""
    
    def __init__(self):
        self.gamma_api_base = "https://gamma-api.polymarket.com"
        self.clob_api_base = "https://clob.polymarket.com"
        self.data_api_base = "https://data.polymarket.com"
        self.graphql_url = "https://polymarket.com/graphql"
        self.ws_url = "wss://ws.polymarket.com"
        
        # Authentication
        self.api_key = os.getenv("POLYMARKET_API_KEY")
        self.api_secret = os.getenv("POLYMARKET_API_SECRET")
        self.wallet_address = os.getenv("POLYMARKET_WALLET_ADDRESS")
        self.private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
        
        # Request timeouts
        self.timeout = 30.0
        self.ws_timeout = 60.0


# ============================================================================
# Main Client Class
# ============================================================================

class PolymarketClient:
    """Unified Polymarket client for MERID integration."""
    
    def __init__(self, config: Optional[PolymarketConfig] = None):
        self.config = config or PolymarketConfig()
        self._http_client: Optional[aiohttp.ClientSession] = None
        self._clob_client = None
        self._session = None
        
    async def __aenter__(self):
        """Async context manager entry."""
        await self._initialize_clients()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
        
    async def _initialize_clients(self):
        """Initialize HTTP clients."""
        # Main HTTP client for Gamma and Data APIs
        self._http_client = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.config.timeout),
            headers={
                "User-Agent": "MERID-Polymarket-Client/1.0"
            }
        )
        
        # CLOB client for trading
        if self.config.api_key and self.config.api_secret:
            try:
                from polymarket_clob import ClobClient
                self._clob_client = ClobClient(
                    api_key=self.config.api_key,
                    api_secret=self.config.api_secret,
                    chain_id="polygon"  # Polygon POS network
                )
                logger.info("CLOB client initialized for trading")
            except ImportError:
                logger.warning("polymarket-clob package not installed, trading disabled")
        else:
            logger.info("CLOB credentials not provided, trading disabled")
    
    async def close(self):
        """Close all clients."""
        if self._http_client:
            await self._http_client.close()
        if self._session:
            await self._session.close()
    
    # ============================================================================
    # Market Discovery & Details
    # ============================================================================
    
    async def list_markets(
        self,
        active: bool = True,
        limit: int = 100,
        category: Optional[str] = None,
        search: Optional[str] = None
    ) -> List[Market]:
        """
        List markets from Gamma API.
        
        Args:
            active: Filter for active markets only
            limit: Maximum number of markets to return
            category: Filter by category
            search: Search term for market questions
            
        Returns:
            List of Market objects
        """
        url = f"{self.config.gamma_api_base}/markets"
        params = {"limit": limit}
        
        if active:
            params["active"] = "true"
        if category:
            params["category"] = category
        if search:
            params["search"] = search
            
        try:
            async with self._http_client.get(url, params=params) as response:
                if response.status != 200:
                    logger.error(f"Gamma API returned {response.status}")
                    return []
                    
                data = await response.json()
                markets = []
                
                # Handle both list and dict responses
                items = data if isinstance(data, list) else data.get("data", data.get("markets", []))
                
                # Add parsing guard to handle string responses
                if not items:
                    logger.warning("Empty or invalid response from Gamma API")
                    return []
                
                # Log first few items for debugging
                logger.debug(f"Polymarket raw items sample: {items[:3]}")
                
                for item in items:
                    # Guard against string items
                    if isinstance(item, str):
                        try:
                            # Try to parse as JSON
                            item = json.loads(item)
                        except Exception:
                            logger.warning(f"Skipping non-dict market entry: {item!r}")
                            continue
                    
                    # Ensure we have a dict
                    if not isinstance(item, dict):
                        logger.warning(f"Skipping invalid market entry type: {type(item)}")
                        continue
                    
                    market = self._parse_market(item)
                    if market:
                        markets.append(market)
                        
                logger.info(f"Fetched {len(markets)} markets from Gamma API")
                return markets
                
        except Exception as e:
            logger.error(f"Failed to fetch markets: {e}")
            return []
    
    async def get_market_details(self, market_id: str) -> Optional[Market]:
        """
        Get detailed information about a specific market.
        
        Args:
            market_id: Market identifier
            
        Returns:
            Market object or None if not found
        """
        url = f"{self.config.gamma_api_base}/markets/{market_id}"
        
        try:
            async with self._http_client.get(url) as response:
                if response.status != 200:
                    logger.error(f"Market details API returned {response.status}")
                    return None
                    
                data = await response.json()
                return self._parse_market(data)
                
        except Exception as e:
            logger.error(f"Failed to fetch market details: {e}")
            return None
    
    async def get_orderbook(self, market_id: str) -> Optional[OrderBook]:
        """
        Get order book for a market.
        
        Args:
            market_id: Market identifier
            
        Returns:
            OrderBook object or None if not available
        """
        url = f"{self.config.gamma_api_base}/markets/{market_id}/orderbook"
        
        try:
            async with self._http_client.get(url) as response:
                if response.status != 200:
                    logger.error(f"Orderbook API returned {response.status}")
                    return None
                    
                data = await response.json()
                return self._parse_orderbook(data, market_id)
                
        except Exception as e:
            logger.error(f"Failed to fetch orderbook: {e}")
            return None
    
    # ============================================================================
    # User Data / Positions
    # ============================================================================
    
    async def get_positions(self, wallet_address: Optional[str] = None) -> List[Position]:
        """
        Get user positions.
        
        Args:
            wallet_address: User wallet address (defaults to config)
            
        Returns:
            List of Position objects
        """
        address = wallet_address or self.config.wallet_address
        if not address:
            logger.error("No wallet address provided")
            return []
            
        # Use GraphQL for positions
        query = """
        query GetPositions($address: String!) {
            user(address: $address) {
                positions {
                    id
                    market {
                        id
                        question
                    }
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
                json={"query": query, "variables": {"address": address}}
            ) as response:
                if response.status != 200:
                    logger.error(f"GraphQL API returned {response.status}")
                    return []
                    
                data = await response.json()
                return self._parse_positions(data)
                
        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}")
            return []
    
    async def get_trades(
        self,
        wallet_address: Optional[str] = None,
        limit: int = 100
    ) -> List[Trade]:
        """
        Get user trade history.
        
        Args:
            wallet_address: User wallet address
            limit: Maximum number of trades to return
            
        Returns:
            List of Trade objects
        """
        address = wallet_address or self.config.wallet_address
        if not address:
            logger.error("No wallet address provided")
            return []
            
        # Use Data API for trades
        url = f"{self.config.data_api_base}/trades"
        params = {"address": address, "limit": limit}
        
        try:
            async with self._http_client.get(url, params=params) as response:
                if response.status != 200:
                    logger.error(f"Data API returned {response.status}")
                    return []
                    
                data = await response.json()
                return self._parse_trades(data)
                
        except Exception as e:
            logger.error(f"Failed to fetch trades: {e}")
            return []
    
    async def get_activity(self, wallet_address: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get user activity feed.
        
        Args:
            wallet_address: User wallet address
            
        Returns:
            List of activity items
        """
        address = wallet_address or self.config.wallet_address
        if not address:
            logger.error("No wallet address provided")
            return []
            
        url = f"{self.config.data_api_base}/activity"
        params = {"address": address}
        
        try:
            async with self._http_client.get(url, params=params) as response:
                if response.status != 200:
                    logger.error(f"Activity API returned {response.status}")
                    return []
                    
                data = await response.json()
                return data.get("activity", [])
                
        except Exception as e:
            logger.error(f"Failed to fetch activity: {e}")
            return []
    
    # ============================================================================
    # Trading Operations (CLOB)
    # ============================================================================
    
    async def place_order(
        self,
        market_id: str,
        outcome: str,
        side: str,
        size: Union[str, Decimal],
        price: Union[str, Decimal],
        order_type: str = "limit"
    ) -> Optional[Order]:
        """
        Place a trading order.
        
        Args:
            market_id: Market identifier
            outcome: Market outcome
            side: "buy" or "sell"
            size: Order size
            price: Order price
            order_type: Order type (limit, market)
            
        Returns:
            Order object or None if failed
        """
        if not self._clob_client:
            logger.error("CLOB client not initialized")
            return None
            
        try:
            # Convert to proper types
            size_decimal = Decimal(str(size))
            price_decimal = Decimal(str(price))
            
            # Place order via CLOB client
            result = await self._clob_client.place_order(
                market_id=market_id,
                outcome=outcome,
                side=side,
                size=size_decimal,
                price=price_decimal,
                order_type=order_type
            )
            
            return self._parse_order(result)
            
        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            return None
    
    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order.
        
        Args:
            order_id: Order identifier
            
        Returns:
            True if successful, False otherwise
        """
        if not self._clob_client:
            logger.error("CLOB client not initialized")
            return False
            
        try:
            await self._clob_client.cancel_order(order_id)
            return True
            
        except Exception as e:
            logger.error(f"Failed to cancel order: {e}")
            return False
    
    async def get_open_orders(self, wallet_address: Optional[str] = None) -> List[Order]:
        """
        Get open orders.
        
        Args:
            wallet_address: User wallet address
            
        Returns:
            List of Order objects
        """
        if not self._clob_client:
            logger.error("CLOB client not initialized")
            return []
            
        try:
            orders = await self._clob_client.get_open_orders()
            return [self._parse_order(order) for order in orders]
            
        except Exception as e:
            logger.error(f"Failed to fetch open orders: {e}")
            return []
    
    # ============================================================================
    # Helper Methods
    # ============================================================================
    
    def _parse_market(self, data: Dict[str, Any]) -> Optional[Market]:
        """Parse market data from API response."""
        try:
            outcomes = []
            for outcome_data in data.get("outcomes", []):
                price = Decimal(str(outcome_data.get("price", 0)))
                outcomes.append(MarketOutcome(
                    outcome=outcome_data.get("outcome", ""),
                    price=price,
                    probability=price * 100,  # Convert to percentage
                    best_ask_price=Decimal(str(outcome_data.get("bestAskPrice", 0))),
                    best_bid_price=Decimal(str(outcome_data.get("bestBidPrice", 0)))
                ))
            
            # Parse timestamps
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
            
        except Exception as e:
            logger.error(f"Failed to parse market data: {e}")
            return None
    
    def _parse_orderbook(self, data: Dict[str, Any], market_id: str) -> Optional[OrderBook]:
        """Parse orderbook data from API response."""
        try:
            bids = []
            asks = []
            
            for bid in data.get("bids", []):
                bids.append((Decimal(str(bid[0])), Decimal(str(bid[1]))))
                
            for ask in data.get("asks", []):
                asks.append((Decimal(str(ask[0])), Decimal(str(ask[1]))))
            
            return OrderBook(
                market_id=market_id,
                outcome=data.get("outcome", ""),
                bids=bids,
                asks=asks,
                timestamp=datetime.now(timezone.utc)
            )
            
        except Exception as e:
            logger.error(f"Failed to parse orderbook data: {e}")
            return None
    
    def _parse_positions(self, data: Dict[str, Any]) -> List[Position]:
        """Parse positions from GraphQL response."""
        try:
            positions = []
            for pos_data in data.get("data", {}).get("user", {}).get("positions", []):
                positions.append(Position(
                    market_id=pos_data.get("market", {}).get("id", ""),
                    outcome=pos_data.get("outcome", ""),
                    size=Decimal(str(pos_data.get("size", 0))),
                    average_price=Decimal(str(pos_data.get("averagePrice", 0))),
                    unrealized_pnl=Decimal(str(pos_data.get("unrealizedPnl", 0))),
                    realized_pnl=Decimal(str(pos_data.get("realizedPnl", 0))),
                    created_at=datetime.fromisoformat(pos_data.get("createdAt", "").replace("Z", "+00:00"))
                ))
            return positions
            
        except Exception as e:
            logger.error(f"Failed to parse positions: {e}")
            return []
    
    def _parse_trades(self, data: Dict[str, Any]) -> List[Trade]:
        """Parse trades from Data API response."""
        try:
            trades = []
            for trade_data in data.get("trades", []):
                trades.append(Trade(
                    id=trade_data.get("id", ""),
                    market_id=trade_data.get("marketId", ""),
                    outcome=trade_data.get("outcome", ""),
                    side=trade_data.get("side", ""),
                    size=Decimal(str(trade_data.get("size", 0))),
                    price=Decimal(str(trade_data.get("price", 0))),
                    fee=Decimal(str(trade_data.get("fee", 0))),
                    timestamp=datetime.fromisoformat(trade_data.get("timestamp", "").replace("Z", "+00:00"))
                ))
            return trades
            
        except Exception as e:
            logger.error(f"Failed to parse trades: {e}")
            return []
    
    def _parse_order(self, data: Dict[str, Any]) -> Order:
        """Parse order from CLOB response."""
        try:
            return Order(
                id=data.get("id", ""),
                market_id=data.get("marketId", ""),
                outcome=data.get("outcome", ""),
                side=data.get("side", ""),
                size=Decimal(str(data.get("size", 0))),
                price=Decimal(str(data.get("price", 0))),
                filled=Decimal(str(data.get("filled", 0))),
                remaining=Decimal(str(data.get("remaining", 0))),
                status=data.get("status", "pending"),
                created_at=datetime.fromisoformat(data.get("createdAt", "").replace("Z", "+00:00"))
            )
            
        except Exception as e:
            logger.error(f"Failed to parse order: {e}")
            raise


# ============================================================================
# WebSocket Streaming
# ============================================================================

class PolymarketWebSocket:
    """WebSocket client for real-time Polymarket data."""
    
    def __init__(self, client: PolymarketClient):
        self.client = client
        self._ws = None
        self._subscriptions = set()
        
    async def connect(self):
        """Connect to WebSocket."""
        try:
            import websockets
            
            self._ws = await websockets.connect(
                self.client.config.ws_url,
                timeout=self.client.config.ws_timeout
            )
            logger.info("Connected to Polymarket WebSocket")
            
        except Exception as e:
            logger.error(f"Failed to connect to WebSocket: {e}")
            raise
    
    async def subscribe_markets(self, market_ids: List[str]):
        """Subscribe to market updates."""
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
            
        message = {
            "type": "subscribe",
            "channel": "markets",
            "market_ids": market_ids
        }
        
        await self._ws.send(json.dumps(message))
        self._subscriptions.update(market_ids)
        logger.info(f"Subscribed to {len(market_ids)} markets")
    
    async def subscribe_orderbook(self, market_id: str):
        """Subscribe to orderbook updates."""
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
            
        message = {
            "type": "subscribe",
            "channel": "orderbook",
            "market_id": market_id
        }
        
        await self._ws.send(json.dumps(message))
        self._subscriptions.add(f"orderbook:{market_id}")
        logger.info(f"Subscribed to orderbook for {market_id}")
    
    async def listen(self, callback):
        """Listen for WebSocket messages."""
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
            
        async for message in self._ws:
            try:
                data = json.loads(message)
                await callback(data)
            except Exception as e:
                logger.error(f"Failed to process WebSocket message: {e}")
    
    async def close(self):
        """Close WebSocket connection."""
        if self._ws:
            await self._ws.close()
            self._ws = None
            self._subscriptions.clear()
            logger.info("WebSocket connection closed")
