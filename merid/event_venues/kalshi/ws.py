"""Kalshi WebSocket client - Real-time streaming."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from merid.event_venues.base import EventVenueStream, QuoteEvent
from merid.event_venues.kalshi.models import KalshiConfig
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.ws")


class KalshiWebSocket(EventVenueStream):
    """
    WebSocket client for real-time Kalshi data.
    Implements EventVenueStream interface.
    """
    
    def __init__(self, config: Optional[KalshiConfig] = None):
        self.config = config or KalshiConfig()
        self._ws = None
        self._subscriptions: set = set()
        self._running = False
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0
        self._auth_token: Optional[str] = None
        
    @property
    def venue_name(self) -> str:
        return "kalshi"
    
    async def connect(self) -> None:
        """Connect to Kalshi WebSocket."""
        try:
            import websockets
            
            # Headers for authentication
            headers = {}
            if self._auth_token:
                headers["Authorization"] = f"Bearer {self._auth_token}"
            
            self._ws = await websockets.connect(
                self.config.ws_url,
                extra_headers=headers if headers else None,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5
            )
            self._running = True
            self._reconnect_delay = 1.0
            logger.info("Connected to Kalshi WebSocket")
            
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Failed to connect to Kalshi WebSocket: {e}")
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
        logger.info("Kalshi WebSocket connection closed")
    
    async def subscribe_quotes(self, market_ids: List[str]) -> None:
        """Subscribe to market quote updates."""
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
        
        message = {
            "type": "subscribe",
            "channel": "ticker",
            "tickers": market_ids
        }
        
        await self._ws.send(json.dumps(message))
        self._subscriptions.update(market_ids)
        logger.info(f"Subscribed to {len(market_ids)} Kalshi markets")
    
    async def subscribe_trades(self, market_ids: Optional[List[str]] = None) -> None:
        """Subscribe to trade updates."""
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
        
        message = {
            "type": "subscribe",
            "channel": "trades"
        }
        
        if market_ids:
            message["tickers"] = market_ids
            
        await self._ws.send(json.dumps(message))
        logger.info(f"Subscribed to Kalshi trades")
    
    async def subscribe_orderbook(self, market_id: str, outcome_id: Optional[str] = None) -> None:
        """Subscribe to orderbook updates."""
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
        
        message = {
            "type": "subscribe",
            "channel": "orderbook",
            "ticker": market_id
        }
        
        await self._ws.send(json.dumps(message))
        self._subscriptions.add(f"orderbook:{market_id}")
        logger.info(f"Subscribed to Kalshi orderbook for {market_id}")
    
    async def listen(self, callback: Callable[[Any], None]) -> None:
        """Listen for WebSocket messages."""
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
                        logger.warning(f"Failed to decode Kalshi WS message: {e}")
                    except (ValueError, TypeError, RuntimeError) as e:
                        logger.error(f"Error processing Kalshi WS message: {e}")
                        
            except (ConnectionError, RuntimeError, ValueError) as e:
                if self._running:
                    logger.error(f"Kalshi WebSocket error: {e}")
                    await self._reconnect()
    
    async def _reconnect(self) -> None:
        """Reconnect with exponential backoff."""
        if not self._running:
            return
            
        logger.info(f"Reconnecting to Kalshi in {self._reconnect_delay}s...")
        await asyncio.sleep(self._reconnect_delay)
        
        self._reconnect_delay = min(
            self._reconnect_delay * 2,
            self._max_reconnect_delay
        )
        
        try:
            await self.connect()
            if self._subscriptions:
                market_ids = [s for s in self._subscriptions if not s.startswith("orderbook:")]
                if market_ids:
                    await self.subscribe_quotes(market_ids)
        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.error(f"Kalshi reconnection failed: {e}")
    
    def _parse_message(self, data: Dict[str, Any]) -> Optional[Any]:
        """Parse WebSocket message into venue-agnostic event."""
        from datetime import datetime, timezone
        
        channel = data.get("channel") or data.get("type")
        
        if channel == "ticker":
            # Market quote update
            return QuoteEvent(
                market_id=data.get("ticker", ""),
                outcome_id=None,
                bid_price=Decimal(str(data.get("bid", 0))) / 100 if data.get("bid") else None,
                ask_price=Decimal(str(data.get("ask", 0))) / 100 if data.get("ask") else None,
                last_price=Decimal(str(data.get("last_price", 0))) / 100 if data.get("last_price") else None,
                volume=Decimal(str(data.get("volume", 0))) if data.get("volume") else None,
                timestamp=datetime.now(timezone.utc),
                venue="kalshi",
                raw_data=data
            )
        
        elif channel == "trade":
            # Trade update
            from merid.event_venues.base import VenueTrade
            return VenueTrade(
                trade_id=data.get("trade_id", ""),
                market_id=data.get("ticker", ""),
                order_id=data.get("order_id", ""),
                side=data.get("side", ""),
                size=Decimal(str(data.get("count", 0))),
                price=Decimal(str(data.get("price", 0))) / 100,
                fee=Decimal(str(data.get("fee", 0))) / 100,
                timestamp=datetime.fromisoformat(data.get("created_at", "").replace("Z", "+00:00")) if data.get("created_at") else datetime.now(timezone.utc),
                venue="kalshi"
            )
        
        return None
