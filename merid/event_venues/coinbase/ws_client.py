"""Coinbase WebSocket client for spot price data.

This module provides real-time spot price feeds from Coinbase
to use as lead indicators for Kalshi 15-minute crypto contracts.

Based on Turbine research: Coinbase spot velocity is the dominant edge
for Kalshi 15-minute BTC trading (+$19,451 P&L over 30 days).
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Callable
import websockets
from utils.logger import get_logger

logger = get_logger("merid.event_venues.coinbase.ws_client")


class CoinbaseAsset(Enum):
    """Supported Coinbase assets for Kalshi crypto trading."""
    BTC = "BTC-USD"
    ETH = "ETH-USD"
    SOL = "SOL-USD"
    XRP = "XRP-USD"
    DOGE = "DOGE-USD"


@dataclass
class SpotPrice:
    """Spot price snapshot from Coinbase."""
    asset: str
    price: float
    timestamp: float  # Unix epoch
    sequence: int = 0


@dataclass
class VelocitySignal:
    """Velocity signal calculated from spot price movement."""
    asset: str
    velocity: float  # Price change rate (per second)
    window_seconds: int  # Time window for velocity calculation
    timestamp: float
    signal_type: str  # "positive" or "negative"


class CoinbaseWebSocketClient:
    """Coinbase WebSocket client for real-time spot price feeds.
    
    This client connects to Coinbase's WebSocket API to receive
    real-time spot price updates for crypto assets, which are then
    used to calculate velocity signals for Kalshi trading.
    
    Based on Turbine research: 1-minute Coinbase velocity was the
    top-performing strategy for Kalshi BTC 15-minute markets.
    """
    
    # Coinbase WebSocket endpoint
    WS_URL = "wss://ws-feed.exchange.coinbase.com"
    
    def __init__(
        self,
        assets: Optional[List[CoinbaseAsset]] = None,
        on_price_update: Optional[Callable[[SpotPrice], None]] = None,
        on_velocity_signal: Optional[Callable[[VelocitySignal], None]] = None,
    ):
        """Initialize Coinbase WebSocket client.
        
        Args:
            assets: List of assets to subscribe to (default: all 5 crypto assets)
            on_price_update: Callback for price updates
            on_velocity_signal: Callback for velocity signals
        """
        self.assets = assets or [
            CoinbaseAsset.BTC,
            CoinbaseAsset.ETH,
            CoinbaseAsset.SOL,
            CoinbaseAsset.XRP,
            CoinbaseAsset.DOGE,
        ]
        self.on_price_update = on_price_update
        self.on_velocity_signal = on_velocity_signal
        
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._price_history: Dict[str, List[SpotPrice]] = {
            asset.value: [] for asset in self.assets
        }
        self._last_sequence: Dict[str, int] = {}
        
        # Velocity calculation parameters
        self._velocity_window_seconds = 60  # 1-minute window (per Turbine research)
        self._velocity_threshold = 0.0005  # 0.05% threshold (lowered per research)
    
    async def connect(self) -> None:
        """Connect to Coinbase WebSocket and subscribe to price feeds."""
        logger.info(f"[COINBASE-WS] Connecting to {self.WS_URL}")
        
        try:
            self._ws = await websockets.connect(
                self.WS_URL,
                ping_interval=20,
                ping_timeout=20,
            )
            logger.info("[COINBASE-WS] Connected successfully")
            
            # Subscribe to price feeds
            await self._subscribe()
            
            self._running = True
            logger.info(f"[COINBASE-WS] Subscribed to {len(self.assets)} assets")
            
        except Exception as e:
            logger.error(f"[COINBASE-WS] Connection failed: {e}")
            raise
    
    async def _subscribe(self) -> None:
        """Subscribe to Coinbase price feeds for configured assets."""
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
        
        # Build subscription message
        subscribe_msg = {
            "type": "subscribe",
            "product_ids": [asset.value for asset in self.assets],
            "channels": ["ticker"],
        }
        
        await self._ws.send(json.dumps(subscribe_msg))
        logger.info(f"[COINBASE-WS] Sent subscription: {subscribe_msg}")
    
    async def listen(self) -> None:
        """Listen for WebSocket messages and process price updates."""
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
        
        logger.info("[COINBASE-WS] Starting message listener")
        
        try:
            async for message in self._ws:
                if not self._running:
                    break
                
                await self._process_message(message)
                
        except websockets.exceptions.ConnectionClosed:
            logger.warning("[COINBASE-WS] Connection closed, will reconnect")
        except Exception as e:
            logger.error(f"[COINBASE-WS] Error in listener: {e}")
    
    async def _process_message(self, message: str) -> None:
        """Process incoming WebSocket message."""
        try:
            data = json.loads(message)
            msg_type = data.get("type")
            
            if msg_type == "ticker":
                await self._process_ticker(data)
            elif msg_type == "subscriptions":
                logger.info(f"[COINBASE-WS] Subscription confirmed: {data}")
            elif msg_type == "error":
                logger.error(f"[COINBASE-WS] Error message: {data}")
                
        except json.JSONDecodeError as e:
            logger.error(f"[COINBASE-WS] JSON decode error: {e}")
        except Exception as e:
            logger.error(f"[COINBASE-WS] Error processing message: {e}")
    
    async def _process_ticker(self, data: dict) -> None:
        """Process ticker message with price update."""
        product_id = data.get("product_id")
        price_str = data.get("price")
        sequence = data.get("sequence", 0)
        
        if not product_id or not price_str:
            return
        
        try:
            price = float(price_str)
            timestamp = time.time()
            
            # Create spot price snapshot
            spot_price = SpotPrice(
                asset=product_id,
                price=price,
                timestamp=timestamp,
                sequence=sequence,
            )
            
            # Update price history
            self._price_history[product_id].append(spot_price)
            
            # Keep only last 5 minutes of history
            cutoff_time = timestamp - 300
            self._price_history[product_id] = [
                p for p in self._price_history[product_id]
                if p.timestamp > cutoff_time
            ]
            
            # Update last sequence
            self._last_sequence[product_id] = sequence
            
            # Calculate velocity if we have enough history
            await self._calculate_velocity(product_id)
            
            # Callback for price update
            if self.on_price_update:
                self.on_price_update(spot_price)
                
        except (ValueError, TypeError) as e:
            logger.error(f"[COINBASE-WS] Error processing ticker: {e}")
    
    async def _calculate_velocity(self, asset: str) -> None:
        """Calculate velocity from price history."""
        history = self._price_history[asset]
        
        if len(history) < 2:
            return
        
        # Get price from velocity window ago
        window_ago = time.time() - self._velocity_window_seconds
        
        # Find oldest price within window
        oldest_price = None
        for price in reversed(history):
            if price.timestamp <= window_ago:
                oldest_price = price
                break
        
        if not oldest_price:
            return
        
        # Get current price
        current_price = history[-1]
        
        # Calculate velocity (price change rate per second)
        time_diff = current_price.timestamp - oldest_price.timestamp
        if time_diff <= 0:
            return
        
        price_change = (current_price.price - oldest_price.price) / oldest_price.price
        velocity = price_change / time_diff  # Velocity per second
        
        # Check if velocity exceeds threshold
        if abs(velocity) >= self._velocity_threshold:
            signal_type = "positive" if velocity > 0 else "negative"
            
            velocity_signal = VelocitySignal(
                asset=asset,
                velocity=velocity,
                window_seconds=self._velocity_window_seconds,
                timestamp=time.time(),
                signal_type=signal_type,
            )
            
            # Callback for velocity signal
            if self.on_velocity_signal:
                self.on_velocity_signal(velocity_signal)
    
    async def disconnect(self) -> None:
        """Disconnect from WebSocket."""
        logger.info("[COINBASE-WS] Disconnecting")
        self._running = False
        
        if self._ws:
            await self._ws.close()
            self._ws = None
        
        logger.info("[COINBASE-WS] Disconnected")
    
    def get_latest_price(self, asset: str) -> Optional[SpotPrice]:
        """Get latest spot price for an asset."""
        history = self._price_history.get(asset, [])
        return history[-1] if history else None
    
    def get_velocity(self, asset: str) -> Optional[float]:
        """Get current velocity for an asset."""
        history = self._price_history.get(asset, [])
        
        if len(history) < 2:
            return None
        
        # Calculate velocity from last two prices
        current = history[-1]
        previous = history[-2]
        
        time_diff = current.timestamp - previous.timestamp
        if time_diff <= 0:
            return None
        
        price_change = (current.price - previous.price) / previous.price
        return price_change / time_diff


# Singleton instance
_coinbase_client: Optional[CoinbaseWebSocketClient] = None


def get_coinbase_client() -> CoinbaseWebSocketClient:
    """Get singleton Coinbase WebSocket client instance."""
    global _coinbase_client
    
    if _coinbase_client is None:
        _coinbase_client = CoinbaseWebSocketClient()
    
    return _coinbase_client
