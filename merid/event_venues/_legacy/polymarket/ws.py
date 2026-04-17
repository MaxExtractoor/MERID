"""Polymarket WebSocket client - Real-time streaming."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Set

from merid.event_venues.base import EventVenueStream, QuoteEvent
from merid.event_venues._legacy.polymarket.models import PolymarketConfig
from utils.logger import get_logger

logger = get_logger("merid.event_venues.polymarket.ws")


class PolymarketWebSocket(EventVenueStream):
    """
    WebSocket client for real-time Polymarket data.
    Implements EventVenueStream interface.
    """
    
    def __init__(self, config: Optional[PolymarketConfig] = None):
        self.config = config or PolymarketConfig()
        self._ws = None
        self._subscriptions: Set[str] = set()
        self._running = False
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0
        
    @property
    def venue_name(self) -> str:
        return "polymarket"
    
    async def connect(self) -> None:
        """Connect to WebSocket."""
        try:
            import websockets
            
            self._ws = await websockets.connect(
                self.config.ws_url,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5
            )
            self._running = True
            self._reconnect_delay = 1.0  # Reset on successful connect
            logger.info("Connected to Polymarket WebSocket")
            
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Failed to connect to WebSocket: {e}")
            raise
    
    async def close(self) -> None:
        """Close WebSocket connection."""
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except (ConnectionError, RuntimeError):
                pass
            self._ws = None
        self._subscriptions.clear()
        logger.info("WebSocket connection closed")
    
    async def subscribe_quotes(self, market_ids: List[str]) -> None:
        """Subscribe to market quote updates."""
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
    
    async def subscribe_trades(self, market_ids: Optional[List[str]] = None) -> None:
        """Subscribe to trade updates."""
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
        
        message = {
            "type": "subscribe",
            "channel": "trades"
        }
        
        if market_ids:
            message["market_ids"] = market_ids
            
        await self._ws.send(json.dumps(message))
        logger.info(f"Subscribed to trades" + (f" for {len(market_ids)} markets" if market_ids else ""))
    
    async def subscribe_orderbook(self, market_id: str, outcome_id: Optional[str] = None) -> None:
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
    
    async def listen(self, callback: Callable[[Any], None]) -> None:
        """
        Listen for WebSocket messages and call callback with parsed events.
        
        Args:
            callback: Async callback receiving QuoteEvent, VenueTrade, etc.
        """
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
        
        while self._running:
            try:
                async for message in self._ws:
                    if not self._running:
                        break
                    
                    try:
                        data = json.loads(message)
                        event = self._parse_message(data)
                        if event:
                            await callback(event)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to decode WebSocket message: {e}")
                    except (ValueError, TypeError, RuntimeError) as e:
                        logger.error(f"Error processing WebSocket message: {e}")
                        
            except (ConnectionError, RuntimeError, ValueError) as e:
                if self._running:
                    logger.error(f"WebSocket error: {e}")
                    await self._reconnect()
    
    async def _reconnect(self) -> None:
        """Reconnect with exponential backoff."""
        if not self._running:
            return
            
        logger.info(f"Reconnecting in {self._reconnect_delay}s...")
        await asyncio.sleep(self._reconnect_delay)
        
        # Exponential backoff
        self._reconnect_delay = min(
            self._reconnect_delay * 2,
            self._max_reconnect_delay
        )
        
        try:
            await self.connect()
            # Resubscribe to previous channels
            if self._subscriptions:
                market_ids = [s for s in self._subscriptions if not s.startswith("orderbook:")]
                if market_ids:
                    await self.subscribe_quotes(market_ids)
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Reconnection failed: {e}")
    
    def _parse_message(self, data: Dict[str, Any]) -> Optional[Any]:
        """Parse WebSocket message into venue-agnostic event."""
        from datetime import datetime, timezone
        
        channel = data.get("channel")
        
        if channel == "markets":
            # Market quote update
            return QuoteEvent(
                market_id=data.get("market_id", ""),
                outcome_id=data.get("outcome_id"),
                bid_price=Decimal(str(data.get("bid", 0))) if data.get("bid") else None,
                ask_price=Decimal(str(data.get("ask", 0))) if data.get("ask") else None,
                last_price=Decimal(str(data.get("last_price", 0))) if data.get("last_price") else None,
                volume=Decimal(str(data.get("volume", 0))) if data.get("volume") else None,
                timestamp=datetime.now(timezone.utc),
                venue="polymarket",
                raw_data=data
            )
        
        elif channel == "trades":
            # Trade update
            from merid.event_venues.base import VenueTrade
            return VenueTrade(
                trade_id=data.get("trade_id", ""),
                market_id=data.get("market_id", ""),
                order_id=data.get("order_id", ""),
                side=data.get("side", ""),
                size=Decimal(str(data.get("size", 0))),
                price=Decimal(str(data.get("price", 0))),
                fee=Decimal(str(data.get("fee", 0))),
                timestamp=datetime.fromisoformat(data.get("timestamp", "").replace("Z", "+00:00")) if data.get("timestamp") else datetime.now(timezone.utc),
                venue="polymarket"
            )
        
        return None
