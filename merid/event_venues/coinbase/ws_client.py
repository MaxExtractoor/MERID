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
    velocity: float  # Total price change over the lookback window (not per-second)
    window_seconds: int  # Time window for velocity calculation
    timestamp: float
    signal_type: str  # "positive", "negative", or "neutral"


class CoinbaseWebSocketClient:
    """Coinbase WebSocket client for real-time spot price feeds.

    Connects to Coinbase's public WebSocket API, records price history,
    and publishes a velocity signal on every accepted ticker.  The signal
    is always published (type=positive/negative/neutral) so downstream
    consumers can use it as a fresh external velocity snapshot even when
    no directional threshold is crossed.

    Includes automatic reconnection with exponential backoff and
    structured lifecycle logging for observability.
    """

    # Coinbase public WebSocket endpoint
    WS_URL = "wss://ws-feed.exchange.coinbase.com"

    # Reconnection policy
    _RECONNECT_MIN_SECONDS = 1.0
    _RECONNECT_MAX_SECONDS = 60.0
    _RECONNECT_BACKOFF = 2.0
    _MAX_RECONNECTS = 100

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
        self._connection_state = "disconnected"
        self._reconnect_count = 0
        self._last_message_at: Optional[float] = None

        # Message and velocity diagnostics (never reset, monotonically increasing)
        self._messages_received = 0
        self._ticks_accepted = 0
        self._ticks_rejected = 0
        self._velocity_published = 0

        self._price_history: Dict[str, List[SpotPrice]] = {
            asset.value: [] for asset in self.assets
        }
        self._last_sequence: Dict[str, int] = {}

        # Velocity calculation parameters
        self._velocity_window_seconds = 60  # 1-minute window (per Turbine research)
        self._velocity_threshold = 0.00015  # 0.015% threshold for 60-second return classification

    @property
    def connection_state(self) -> str:
        return self._connection_state

    @property
    def reconnect_count(self) -> int:
        return self._reconnect_count

    @property
    def last_message_at(self) -> Optional[float]:
        return self._last_message_at

    def _health_summary(self) -> Dict[str, any]:
        """Return a snapshot of feed health and message counts."""
        return {
            "connection_state": self._connection_state,
            "reconnect_count": self._reconnect_count,
            "last_message_at": self._last_message_at,
            "messages_received": self._messages_received,
            "ticks_accepted": self._ticks_accepted,
            "ticks_rejected": self._ticks_rejected,
            "velocity_published": self._velocity_published,
            "products": [asset.value for asset in self.assets],
        }

    async def run(self) -> None:
        """Run the WebSocket connection with automatic reconnection.

        This is the main entry point for production use.  It loops
        connect -> listen -> reconnect on disconnect/failure.
        """
        self._running = True
        delay = self._RECONNECT_MIN_SECONDS

        while self._running and self._reconnect_count < self._MAX_RECONNECTS:
            try:
                logger.info(
                    "[COINBASE-WS-CONNECT-ATTEMPT] products=%s attempt=%d",
                    [asset.value for asset in self.assets],
                    self._reconnect_count + 1,
                )
                await self.connect()

                # Reset delay on successful connection
                delay = self._RECONNECT_MIN_SECONDS

                logger.info("[COINBASE-WS-MESSAGE-LISTENER-START]")
                await self.listen()

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(
                    "[COINBASE-WS-DISCONNECTED] code=%s reason=%s",
                    e.code, e.reason,
                )
            except Exception as e:
                logger.error("[COINBASE-WS-ERROR] %s", e, exc_info=True)

            if not self._running:
                break

            self._reconnect_count += 1
            logger.info(
                "[COINBASE-WS-RECONNECT-SCHEDULED] attempt=%d delay=%.1fs",
                self._reconnect_count, delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * self._RECONNECT_BACKOFF, self._RECONNECT_MAX_SECONDS)

        logger.info(
            "[COINBASE-WS-RUN-STOPPED] reconnects=%d running=%s",
            self._reconnect_count, self._running,
        )

    async def connect(self) -> None:
        """Connect to Coinbase WebSocket and subscribe to price feeds."""
        self._connection_state = "connecting"
        logger.info("[COINBASE-WS-CONNECT] url=%s products=%s",
                    self.WS_URL, [asset.value for asset in self.assets])

        try:
            self._ws = await websockets.connect(
                self.WS_URL,
                ping_interval=20,
                ping_timeout=20,
            )
            self._connection_state = "connected"
            logger.info("[COINBASE-WS-CONNECTED] url=%s", self.WS_URL)

            await self._subscribe()

            self._connection_state = "subscribed"
            logger.info(
                "[COINBASE-WS-SUBSCRIBE-SENT] products=%s channels=%s",
                [asset.value for asset in self.assets], ["ticker"],
            )

        except Exception as e:
            self._connection_state = "failed"
            logger.error("[COINBASE-WS-CONNECT-FAILED] %s", e)
            raise

    async def _subscribe(self) -> None:
        """Subscribe to Coinbase price feeds for configured assets."""
        if not self._ws:
            raise RuntimeError("WebSocket not connected")

        subscribe_msg = {
            "type": "subscribe",
            "product_ids": [asset.value for asset in self.assets],
            "channels": ["ticker"],
        }

        await self._ws.send(json.dumps(subscribe_msg))

    async def listen(self) -> None:
        """Listen for WebSocket messages and process price updates."""
        if not self._ws:
            raise RuntimeError("WebSocket not connected")

        logger.info("[COINBASE-WS-LISTEN-START]")

        try:
            async for message in self._ws:
                if not self._running:
                    break

                self._messages_received += 1
                self._last_message_at = time.time()
                await self._process_message(message)

        except websockets.exceptions.ConnectionClosed:
            logger.warning("[COINBASE-WS-CONNECTION-CLOSED]")
            raise
        except Exception as e:
            logger.error("[COINBASE-WS-LISTEN-ERROR] %s", e)
            raise

    async def _process_message(self, message: str) -> None:
        """Process incoming WebSocket message."""
        try:
            data = json.loads(message)
        except json.JSONDecodeError as e:
            self._ticks_rejected += 1
            logger.error("[COINBASE-WS-PARSE-REJECTED] json_error=%s", e)
            return
        except Exception as e:
            self._ticks_rejected += 1
            logger.error("[COINBASE-WS-PARSE-REJECTED] %s", e)
            return

        msg_type = data.get("type")

        if msg_type == "ticker":
            await self._process_ticker(data)
        elif msg_type == "subscriptions":
            products = data.get("channels", [{}])[0].get("product_ids", [])
            logger.info(
                "[COINBASE-WS-SUBSCRIBE-ACK] products=%s channels=%s",
                products, [ch.get("name") for ch in data.get("channels", [])],
            )
        elif msg_type == "error":
            logger.error("[COINBASE-WS-ERROR-MESSAGE] %s", data)
        else:
            logger.debug("[COINBASE-WS-MESSAGE] type=%s", msg_type)

    async def _process_ticker(self, data: dict) -> None:
        """Process ticker message with price update."""
        product_id = data.get("product_id")
        price_str = data.get("price")
        sequence = data.get("sequence", 0)

        if not product_id:
            self._ticks_rejected += 1
            logger.warning("[COINBASE-WS-TICK-REJECTED] missing product_id data=%s", data)
            return

        if not price_str:
            self._ticks_rejected += 1
            logger.warning("[COINBASE-WS-TICK-REJECTED] missing price product_id=%s", product_id)
            return

        try:
            price = float(price_str)
        except (ValueError, TypeError) as e:
            self._ticks_rejected += 1
            logger.error("[COINBASE-WS-TICK-REJECTED] product_id=%s price=%s error=%s", product_id, price_str, e)
            return

        # Sequence should generally increase; a stale/out-of-order tick is still
        # a data point but we log it for diagnostics.
        last_sequence = self._last_sequence.get(product_id, 0)
        if sequence < last_sequence:
            logger.debug(
                "[COINBASE-WS-TICK-OUT-OF-ORDER] product_id=%s sequence=%d last=%d",
                product_id, sequence, last_sequence,
            )

        self._ticks_accepted += 1
        timestamp = time.time()

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

        self._last_sequence[product_id] = sequence

        logger.debug(
            "[COINBASE-WS-TICK-ACCEPTED] product_id=%s price=%.6f sequence=%d history_len=%d",
            product_id, price, sequence, len(self._price_history[product_id]),
        )

        # Calculate and publish velocity on every accepted tick so the grid
        # always has a fresh external velocity to use, even when no threshold
        # is crossed.
        await self._calculate_velocity(product_id)

        if self.on_price_update:
            self.on_price_update(spot_price)

    async def _calculate_velocity(self, asset: str) -> None:
        """Calculate velocity from price history and publish a signal.

        A VelocitySignal is published on every accepted tick once a full
        lookback window exists.  signal_type reflects whether the total price
        change over the window is above the internal positive/negative
        threshold, or "neutral" if it is below.  The velocity value itself is
        the total window return, not a per-second rate, so it can be compared
        directly against the agent's per-asset velocity thresholds.
        """
        history = self._price_history[asset]

        if len(history) < 2:
            return

        # Current wall time is only used for the signal publish timestamp.
        # The window is measured from the most recent *sample* timestamp so
        # an out-of-order late tick cannot shift the reference point, and the
        # calculation stays tied to the feed's actual clock.
        current_time = max(p.timestamp for p in history)
        current_price = next(
            p for p in reversed(history) if p.timestamp == current_time
        )

        # Use the most recent price that is at least one full window old.
        # Falling back to a shorter lookback would produce a per-second rate
        # that is orders of magnitude smaller than the thresholds, so we
        # require the full window and skip publication until it is available.
        window_ago = current_time - self._velocity_window_seconds

        oldest_price = None
        for price in reversed(history):
            if price.timestamp <= window_ago:
                oldest_price = price
                break

        if oldest_price is None:
            logger.debug(
                "[COINBASE-WS-VELOCITY-WARMUP] product_id=%s not enough history for %ss window",
                asset, self._velocity_window_seconds,
            )
            return

        time_diff = current_price.timestamp - oldest_price.timestamp
        if time_diff <= 0:
            return

        # Total price change over the window.  Thresholds are calibrated for
        # a 60-second return (e.g. 0.015% - 0.03%), not a per-second rate.
        velocity = (current_price.price - oldest_price.price) / oldest_price.price

        # Classify the signal type.  "neutral" means the magnitude is below
        # the client's own threshold, not that the signal is unusable.
        if velocity > self._velocity_threshold:
            signal_type = "positive"
        elif velocity < -self._velocity_threshold:
            signal_type = "negative"
        else:
            signal_type = "neutral"

        velocity_signal = VelocitySignal(
            asset=asset,
            velocity=velocity,
            window_seconds=self._velocity_window_seconds,
            timestamp=time.time(),
            signal_type=signal_type,
        )

        self._velocity_published += 1

        logger.debug(
            "[COINBASE-WS-VELOCITY-PUBLISHED] product_id=%s velocity=%.8f type=%s window=%.1fs",
            asset, velocity, signal_type, time_diff,
        )

        if self.on_velocity_signal:
            self.on_velocity_signal(velocity_signal)

    async def disconnect(self) -> None:
        """Disconnect from WebSocket."""
        logger.info("[COINBASE-WS-DISCONNECT]")
        self._running = False
        self._connection_state = "disconnected"

        if self._ws:
            await self._ws.close()
            self._ws = None

        logger.info("[COINBASE-WS-DISCONNECTED]")

    def get_latest_price(self, asset: str) -> Optional[SpotPrice]:
        """Get latest spot price for an asset."""
        history = self._price_history.get(asset, [])
        if not history:
            return None
        current_time = max(p.timestamp for p in history)
        for price in reversed(history):
            if price.timestamp == current_time:
                return price
        return None

    def get_velocity(self, asset: str) -> Optional[float]:
        """Get current 60s-window velocity for an asset (total return, not per-second)."""
        history = self._price_history.get(asset, [])

        if len(history) < 2:
            return None

        current_time = max(p.timestamp for p in history)
        current = next(
            p for p in reversed(history) if p.timestamp == current_time
        )

        window_ago = current_time - self._velocity_window_seconds

        oldest_price = None
        for price in reversed(history):
            if price.timestamp <= window_ago:
                oldest_price = price
                break

        if oldest_price is None:
            return None

        time_diff = current.timestamp - oldest_price.timestamp
        if time_diff <= 0:
            return None

        return (current.price - oldest_price.price) / oldest_price.price


# Singleton instance
_coinbase_client: Optional[CoinbaseWebSocketClient] = None


def get_coinbase_client() -> CoinbaseWebSocketClient:
    """Get singleton Coinbase WebSocket client instance."""
    global _coinbase_client

    if _coinbase_client is None:
        _coinbase_client = CoinbaseWebSocketClient()

    return _coinbase_client
