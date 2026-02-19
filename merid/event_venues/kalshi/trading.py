"""Kalshi trading utilities - High-level trading operations."""

from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from merid.event_venues.base import (
    EventMarket,
    MarketFilter,
    PlacedOrder,
    VenueOrder,
)
from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.models import KalshiConfig
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.trading")


class KalshiTrader:
    """
    High-level trading interface for Kalshi.
    
    Provides convenient methods for common trading operations
    like buying/selling yes/no contracts, position management, etc.
    """
    
    def __init__(self, client: Optional[KalshiVenueClient] = None, config: Optional[KalshiConfig] = None):
        self.client = client or KalshiVenueClient(config)
        
    async def connect(self) -> None:
        """Initialize connections."""
        await self.client.connect()
    
    async def close(self) -> None:
        """Close connections."""
        await self.client.close()
    
    async def buy_yes(self, ticker: str, count: int, price: Optional[int] = None) -> Optional[PlacedOrder]:
        """Buy YES contracts in a market."""
        order = VenueOrder(
            market_id=ticker,
            side="buy",
            size=Decimal(count),
            price=Decimal(price) / 100 if price else None,
            order_type="limit" if price else "market",
            outcome_id="yes"
        )
        logger.debug(f"buy_yes: {ticker} count={count} price={price}")
        return await self.client.place_order(order)
    
    async def buy_no(self, ticker: str, count: int, price: Optional[int] = None) -> Optional[PlacedOrder]:
        """Buy NO contracts in a market."""
        order = VenueOrder(
            market_id=ticker,
            side="buy",
            size=Decimal(count),
            price=Decimal(price) / 100 if price else None,
            order_type="limit" if price else "market",
            outcome_id="no"
        )
        return await self.client.place_order(order)
    
    async def sell_yes(self, ticker: str, count: int, price: Optional[int] = None) -> Optional[PlacedOrder]:
        """Sell YES contracts (or close YES position)."""
        order = VenueOrder(
            market_id=ticker,
            side="sell",
            size=Decimal(count),
            price=Decimal(price) / 100 if price else None,
            order_type="limit" if price else "market",
            outcome_id="yes"
        )
        return await self.client.place_order(order)
    
    async def sell_no(self, ticker: str, count: int, price: Optional[int] = None) -> Optional[PlacedOrder]:
        """Sell NO contracts (or close NO position)."""
        order = VenueOrder(
            market_id=ticker,
            side="sell",
            size=Decimal(count),
            price=Decimal(price) / 100 if price else None,
            order_type="limit" if price else "market",
            outcome_id="no"
        )
        return await self.client.place_order(order)
    
    async def close_position(self, ticker: str) -> List[PlacedOrder]:
        """
        Close all positions in a market by placing offsetting orders.
        
        Args:
            ticker: Market ticker to close position in
            
        Returns:
            List of placed orders
        """
        positions = await self.client.get_positions()
        market_positions = [p for p in positions if p.market_id == ticker]
        
        orders = []
        for pos in market_positions:
            if pos.size == 0:
                continue
            
            # Close by selling the held side
            side = "sell" if pos.size > 0 else "buy"
            size = abs(pos.size)
            outcome = pos.outcome_id or "yes"
            
            order = VenueOrder(
                market_id=ticker,
                side=side,
                size=size,
                price=None,  # Market order
                order_type="market",
                outcome_id=outcome
            )
            
            placed = await self.client.place_order(order)
            if placed:
                orders.append(placed)
        
        return orders
    
    async def get_market_by_ticker(self, ticker: str) -> Optional[EventMarket]:
        """
        Get a market by its ticker.
        
        Args:
            ticker: Full ticker symbol (e.g., "FED-25DEC-T3.00")
            
        Returns:
            EventMarket or None
        """
        return await self.client.get_market(ticker)
    
    async def search_markets(self, query: str, limit: int = 10) -> List[EventMarket]:
        """
        Search markets by keyword.
        
        Args:
            query: Search query
            limit: Max results
            
        Returns:
            List of matching markets
        """
        return await self.client.list_markets(MarketFilter(search=query, limit=limit))
    
    async def get_best_price(self, ticker: str, side: str = "yes", action: str = "buy") -> Optional[Decimal]:
        """
        Get best available price for a market outcome.
        
        Args:
            ticker: Market ticker
            side: "yes" or "no"
            action: "buy" or "sell"
            
        Returns:
            Best price in dollars (0-1) or None
        """
        orderbook = await self.client.get_orderbook(ticker)
        
        if not orderbook:
            return None
        
        # Kalshi orderbook structure is simplified
        # Prices are already in dollars from the conversion
        if action == "buy":
            return orderbook.asks[0][0] if orderbook.asks else None
        else:
            return orderbook.bids[0][0] if orderbook.bids else None
    
    async def get_account_summary(self) -> dict:
        """
        Get account summary including balance and positions.
        
        Returns:
            Dictionary with balance, positions, and open orders
        """
        balance = await self.client.get_balance()
        positions = await self.client.get_positions()
        open_orders = await self.client.get_open_orders()
        
        return {
            "balance": balance,
            "positions": positions,
            "open_orders": open_orders,
            "position_count": len(positions),
            "open_order_count": len(open_orders)
        }
