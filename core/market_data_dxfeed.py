"""
dxFeed Market Data Adapter for MERID.

Provides a normalized interface to dxFeed market data APIs.
Currently a stub that falls back to the existing live_price_feed;
swap in real dxFeed connectivity when credentials are available.

Usage:
    from core.market_data_dxfeed import get_dxfeed_adapter
    adapter = get_dxfeed_adapter()
    snapshot = adapter.get_snapshot("BTC/USDT")
    watchlist = adapter.get_watchlist()
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.market_data_dxfeed")


@dataclass
class TickData:
    """Normalized tick/quote from any market data source."""
    symbol: str
    price: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    volume_24h: float = 0.0
    change_24h: float = 0.0
    change_pct_24h: float = 0.0
    timestamp: float = field(default_factory=time.time)
    source: str = "live_price_feed"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "bid": self.bid,
            "ask": self.ask,
            "last": self.last,
            "volume_24h": self.volume_24h,
            "change_24h": self.change_24h,
            "change_pct_24h": self.change_pct_24h,
            "timestamp": self.timestamp,
            "source": self.source,
        }


# Default watchlist symbols
DEFAULT_WATCHLIST = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT", "MATIC/USDT",
    "LINK/USDT", "UNI/USDT", "AAVE/USDT", "ARB/USDT", "OP/USDT",
    "DOGE/USDT", "DOT/USDT",
]


class DxFeedAdapter:
    """
    Market data adapter with dxFeed-compatible interface.

    Currently wraps MERID's existing live_price_feed. When dxFeed
    credentials are configured, this will connect via their WebSocket
    or REST API instead.
    """

    def __init__(
        self,
        watchlist: Optional[List[str]] = None,
        throttle_hz: float = 2.0,
    ):
        self.watchlist_symbols = watchlist or DEFAULT_WATCHLIST
        self.throttle_interval = 1.0 / throttle_hz
        self._last_fetch: Dict[str, float] = {}
        self._cache: Dict[str, TickData] = {}
        self._price_feed = None
        self._initialized = False

    def _ensure_feed(self) -> None:
        """Lazy-init the underlying price feed."""
        if self._initialized:
            return
        try:
            from data.live_price_feed import get_live_price_feed
            self._price_feed = get_live_price_feed()
            self._initialized = True
            logger.info(f"dxfeed_adapter_initialized symbols={len(self.watchlist_symbols)}")
        except Exception as exc:
            logger.warning(f"dxfeed_adapter_init_failed error={exc}")
            self._initialized = True  # Don't retry every call

    def get_snapshot(self, symbol: str) -> TickData:
        """
        Get a single instrument snapshot.

        Respects throttle_hz to avoid hammering the upstream feed.
        """
        self._ensure_feed()

        now = time.time()
        last = self._last_fetch.get(symbol, 0)

        # Return cached if within throttle window
        if now - last < self.throttle_interval and symbol in self._cache:
            return self._cache[symbol]

        tick = TickData(symbol=symbol)

        if self._price_feed:
            try:
                data = self._price_feed.get_current_price(symbol)
                if data:
                    tick.price = data.get("price", 0)
                    tick.last = data.get("price", 0)
                    tick.bid = data.get("bid", tick.price * 0.999)
                    tick.ask = data.get("ask", tick.price * 1.001)
                    tick.volume_24h = data.get("volume_24h", 0)
                    tick.change_24h = data.get("change_24h", 0)
                    tick.change_pct_24h = data.get("change_pct_24h", 0)
                    tick.timestamp = now
            except Exception as exc:
                logger.debug(f"dxfeed_snapshot_error symbol={symbol} error={exc}")

        self._cache[symbol] = tick
        self._last_fetch[symbol] = now
        return tick

    def get_watchlist(self) -> List[TickData]:
        """Get snapshots for all watchlist symbols."""
        return [self.get_snapshot(s) for s in self.watchlist_symbols]

    def add_symbol(self, symbol: str) -> None:
        """Add a symbol to the watchlist."""
        if symbol not in self.watchlist_symbols:
            self.watchlist_symbols.append(symbol)

    def remove_symbol(self, symbol: str) -> None:
        """Remove a symbol from the watchlist."""
        if symbol in self.watchlist_symbols:
            self.watchlist_symbols.remove(symbol)
            self._cache.pop(symbol, None)


# ── Singleton ─────────────────────────────────────────────────────────

_adapter_instance: Optional[DxFeedAdapter] = None


def get_dxfeed_adapter() -> DxFeedAdapter:
    """Get or create the singleton dxFeed adapter."""
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = DxFeedAdapter()
    return _adapter_instance
