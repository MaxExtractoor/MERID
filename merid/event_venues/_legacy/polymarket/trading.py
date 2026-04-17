"""Polymarket trading utilities - High-level trading operations."""

from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from merid.event_venues.base import (
    EventMarket,
    MarketFilter,
    PlacedOrder,
    VenueOrder,
)
from merid.event_venues._legacy.polymarket.client import PolymarketVenueClient
from merid.event_venues._legacy.polymarket.models import PolymarketConfig
from utils.logger import get_logger

logger = get_logger("merid.event_venues.polymarket.trading")


class PolymarketTrader:
    """
    High-level trading interface for Polymarket.
    
    Provides convenient methods for common trading operations
    like market orders, position management, etc.
    """
    
    def __init__(self, client: Optional[PolymarketVenueClient] = None, config: Optional[PolymarketConfig] = None):
        self.client = client or PolymarketVenueClient(config)
        
    async def connect(self) -> None:
        """Initialize connections."""
        await self.client.connect()
    
    async def close(self) -> None:
        """Close connections."""
        await self.client.close()
    
    async def buy_yes(self, market_id: str, size: Decimal, price: Optional[Decimal] = None) -> Optional[PlacedOrder]:
        """
        Buy YES shares in a market.
        
        Args:
            market_id: Market to trade
            size: Number of shares to buy
            price: Max price to pay (None for market order)
            
        Returns:
            PlacedOrder or None if failed
        """
        order = VenueOrder(
            market_id=market_id,
            side="buy",
            size=size,
            price=price,
            order_type="limit" if price else "market",
            outcome_id="Yes"
        )
        return await self.client.place_order(order)
    
    async def buy_no(self, market_id: str, size: Decimal, price: Optional[Decimal] = None) -> Optional[PlacedOrder]:
        """Buy NO shares in a market."""
        order = VenueOrder(
            market_id=market_id,
            side="buy",
            size=size,
            price=price,
            order_type="limit" if price else "market",
            outcome_id="No"
        )
        return await self.client.place_order(order)
    
    async def sell_yes(self, market_id: str, size: Decimal, price: Optional[Decimal] = None) -> Optional[PlacedOrder]:
        """Sell YES shares in a market."""
        order = VenueOrder(
            market_id=market_id,
            side="sell",
            size=size,
            price=price,
            order_type="limit" if price else "market",
            outcome_id="Yes"
        )
        return await self.client.place_order(order)
    
    async def sell_no(self, market_id: str, size: Decimal, price: Optional[Decimal] = None) -> Optional[PlacedOrder]:
        """Sell NO shares in a market."""
        order = VenueOrder(
            market_id=market_id,
            side="sell",
            size=size,
            price=price,
            order_type="limit" if price else "market",
            outcome_id="No"
        )
        return await self.client.place_order(order)
    
    async def close_position(self, market_id: str) -> List[PlacedOrder]:
        """
        Close all positions in a market by placing offsetting orders.
        
        Args:
            market_id: Market to close position in
            
        Returns:
            List of placed orders
        """
        from merid.event_venues.base import VenuePosition
        
        positions = await self.client.get_positions()
        market_positions = [p for p in positions if p.market_id == market_id]
        
        orders = []
        for pos in market_positions:
            if pos.size == 0:
                continue
                
            # Determine side and outcome
            side = "sell" if pos.size > 0 else "buy"
            size = abs(pos.size)
            
            order = VenueOrder(
                market_id=market_id,
                side=side,
                size=size,
                price=None,  # Market order
                order_type="market",
                outcome_id=pos.outcome_id
            )
            
            placed = await self.client.place_order(order)
            if placed:
                orders.append(placed)
                
        return orders
    
    async def get_market_by_slug(self, slug: str) -> Optional[EventMarket]:
        """
        Find a market by its slug/question.
        
        Args:
            slug: Market slug or partial question text
            
        Returns:
            EventMarket or None
        """
        markets = await self.client.list_markets(MarketFilter(search=slug, limit=10))
        
        # Try exact match first
        for market in markets:
            if slug.lower() in market.question.lower():
                return market
                
        return markets[0] if markets else None
    
    async def get_best_price(self, market_id: str, outcome: str = "Yes", side: str = "buy") -> Optional[Decimal]:
        """
        Get best available price for a market outcome.
        
        Args:
            market_id: Market ID
            outcome: Outcome to check (Yes/No)
            side: "buy" or "sell"
            
        Returns:
            Best price or None
        """
        orderbook = await self.client.get_orderbook(market_id, outcome)
        
        if not orderbook:
            return None
            
        if side == "buy" and orderbook.asks:
            return orderbook.asks[0][0]  # Best ask
        elif side == "sell" and orderbook.bids:
            return orderbook.bids[0][0]  # Best bid
            
        return None
