"""§H2 WebSocket Price Feed — real-time price streaming into the signal layer.

Connects to the Coinbase WebSocket API (free, no auth required for ticker)
and streams price updates into the feature services.

Supported channels:
  - ticker: real-time last trade price, volume, bid/ask
  - matches: individual trades

Usage:
    feed = CoinbasePriceFeed(["BTC-USD", "ETH-USD", "SOL-USD"])
    await feed.connect()
    # Prices are now flowing into the feature service automatically
    await feed.disconnect()

    # Or use the manager for loop integration:
    mgr = get_ws_feed_manager()
    await mgr.start(["BTC", "ETH", "SOL"])
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger("merid.signals.ws_price_feed")


# ── Price update model ────────────────────────────────────────────────

@dataclass
class PriceUpdate:
    """A single price tick from a WebSocket feed."""
    symbol: str                    # MERID symbol (e.g. "BTC")
    venue: str = "coinbase"
    price: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    volume_24h: float = 0.0
    timestamp: float = field(default_factory=time.time)
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def spread(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return self.ask - self.bid
        return 0.0

    @property
    def spread_bps(self) -> float:
        if self.price > 0:
            return (self.spread / self.price) * 10000
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "venue": self.venue,
            "price": self.price,
            "bid": self.bid,
            "ask": self.ask,
            "spread_bps": round(self.spread_bps, 2),
            "volume_24h": self.volume_24h,
            "timestamp": self.timestamp,
        }


# ── Symbol mapping ────────────────────────────────────────────────────

MERID_TO_COINBASE = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
    "AVAX": "AVAX-USD",
    "LINK": "LINK-USD",
    "MATIC": "MATIC-USD",
    "DOGE": "DOGE-USD",
}

COINBASE_TO_MERID = {v: k for k, v in MERID_TO_COINBASE.items()}


# ── Coinbase WebSocket feed ───────────────────────────────────────────

class CoinbasePriceFeed:
    """Connects to Coinbase WebSocket for real-time price data.

    Uses the public `wss://ws-feed.exchange.coinbase.com` endpoint
    which requires no authentication.
    """

    WS_URL = "wss://ws-feed.exchange.coinbase.com"

    def __init__(self, product_ids: Optional[List[str]] = None):
        self._product_ids = product_ids or ["BTC-USD", "ETH-USD", "SOL-USD"]
        self._ws = None
        self._running = False
        self._subscribers: Set[Callable] = set()
        self._latest_prices: Dict[str, PriceUpdate] = {}
        self._message_count = 0
        self._error_count = 0
        self._connected_at: Optional[float] = None
        self._task: Optional[asyncio.Task] = None

    # ── Connection lifecycle ──────────────────────────────────────────

    async def connect(self):
        """Connect to the Coinbase WebSocket and start receiving data."""
        try:
            import websockets
        except ImportError:
            logger.warning("websockets package not installed — WS feed unavailable")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"Coinbase WS feed starting for {self._product_ids}")

    async def disconnect(self):
        """Gracefully disconnect."""
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Coinbase WS feed disconnected")

    async def _run_loop(self):
        """Main WS loop with auto-reconnect."""
        import websockets

        while self._running:
            try:
                async with websockets.connect(self.WS_URL) as ws:
                    self._ws = ws
                    self._connected_at = time.time()
                    await self._subscribe(ws)
                    logger.info(f"Coinbase WS connected, subscribed to {len(self._product_ids)} products")

                    async for message in ws:
                        if not self._running:
                            break
                        try:
                            data = json.loads(message)
                            self._handle_message(data)
                        except json.JSONDecodeError:
                            self._error_count += 1

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._error_count += 1
                logger.warning(f"Coinbase WS error: {e}, reconnecting in 5s...")
                await asyncio.sleep(5)

    async def _subscribe(self, ws):
        """Send subscription message for ticker channel."""
        sub_msg = {
            "type": "subscribe",
            "product_ids": self._product_ids,
            "channels": ["ticker"],
        }
        await ws.send(json.dumps(sub_msg))

    def _handle_message(self, data: Dict[str, Any]):
        """Process a WebSocket message and emit PriceUpdate."""
        msg_type = data.get("type")
        if msg_type != "ticker":
            return

        product_id = data.get("product_id", "")
        symbol = COINBASE_TO_MERID.get(product_id, product_id.replace("-USD", ""))

        try:
            update = PriceUpdate(
                symbol=symbol,
                venue="coinbase",
                price=float(data.get("price", 0)),
                bid=float(data.get("best_bid", 0)),
                ask=float(data.get("best_ask", 0)),
                volume_24h=float(data.get("volume_24h", 0)),
                timestamp=time.time(),
                raw=data,
            )
        except (ValueError, TypeError):
            self._error_count += 1
            return

        self._latest_prices[symbol] = update
        self._message_count += 1
        self._notify_subscribers(update)

    # ── Subscriber pattern ────────────────────────────────────────────

    def subscribe(self, callback: Callable[[PriceUpdate], None]):
        self._subscribers.add(callback)

    def unsubscribe(self, callback: Callable):
        self._subscribers.discard(callback)

    def _notify_subscribers(self, update: PriceUpdate):
        for cb in self._subscribers:
            try:
                cb(update)
            except Exception as e:
                logger.warning(f"WS subscriber error: {e}")

    # ── Accessors ─────────────────────────────────────────────────────

    def latest(self, symbol: str) -> Optional[PriceUpdate]:
        return self._latest_prices.get(symbol)

    def all_latest(self) -> Dict[str, PriceUpdate]:
        return dict(self._latest_prices)

    def status(self) -> Dict[str, Any]:
        return {
            "connected": self._ws is not None and self._running,
            "products": self._product_ids,
            "message_count": self._message_count,
            "error_count": self._error_count,
            "connected_at": self._connected_at,
            "uptime_seconds": round(time.time() - self._connected_at, 1) if self._connected_at else 0,
            "latest_prices": {k: v.to_dict() for k, v in self._latest_prices.items()},
        }


# ── Feed Manager (loop integration) ──────────────────────────────────

class WSFeedManager:
    """Manages WebSocket feeds and ingests prices into the feature service.

    The MeridLoop calls `start()` once; prices flow into the onchain
    feature service automatically via the subscriber callback.
    """

    def __init__(self):
        self._feed: Optional[CoinbasePriceFeed] = None
        self._active = False

    async def start(self, symbols: List[str]):
        """Start the WebSocket feed for the given symbols."""
        product_ids = [
            MERID_TO_COINBASE[s] for s in symbols
            if s in MERID_TO_COINBASE
        ]
        if not product_ids:
            logger.info("No mappable symbols for WS feed")
            return

        self._feed = CoinbasePriceFeed(product_ids)
        self._feed.subscribe(self._on_price_update)
        await self._feed.connect()
        self._active = True

    async def stop(self):
        if self._feed:
            await self._feed.disconnect()
        self._active = False

    def _on_price_update(self, update: PriceUpdate):
        """Ingest price data into the onchain feature service."""
        try:
            from merid.signals.features import get_feature_service
            svc = get_feature_service()
            chain = "solana" if update.symbol in ("SOL", "BONK", "WIF") else "ethereum"
            svc.onchain.ingest(chain, update.symbol, {
                "price_usd": update.price,
                "bid": update.bid,
                "ask": update.ask,
                "spread_bps": update.spread_bps,
                "volume_24h_usd": update.volume_24h,
            }, ts=update.timestamp)
        except Exception as e:
            logger.warning(f"Failed to ingest WS price for {update.symbol}: {e}")

    @property
    def is_active(self) -> bool:
        return self._active

    def status(self) -> Dict[str, Any]:
        if self._feed:
            return {"active": self._active, **self._feed.status()}
        return {"active": False}


# ── Singleton ─────────────────────────────────────────────────────────

_ws_mgr: Optional[WSFeedManager] = None


def get_ws_feed_manager() -> WSFeedManager:
    global _ws_mgr
    if _ws_mgr is None:
        _ws_mgr = WSFeedManager()
    return _ws_mgr
