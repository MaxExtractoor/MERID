"""TickerCollector — Accumulates Kalshi WS ticker data into a pandas DataFrame.

Subscribes to ``kalshi:price_update`` events on the MERID event bus and
appends each tick into an in-memory DataFrame that can be:
  - Resampled into OHLCV bars for analytics
  - Fed into LiquidityMonitor / VolumeMonitor
  - Queried via API for chart data

Usage::

    collector = get_ticker_collector()
    await collector.start()          # begins listening on event bus
    df = collector.snapshot()         # current DataFrame copy
    df_5m = collector.resample("5T") # 5-minute OHLCV bars
    await collector.stop()
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.ticker_collector")

try:
    import pandas as pd
    _HAS_PANDAS = True
except ImportError:
    pd = None  # type: ignore
    _HAS_PANDAS = False


# ── Data model ──────────────────────────────────────────────────────────────

@dataclass
class TickRecord:
    """A single ticker snapshot from the WS stream."""
    ts: float                     # unix epoch
    market_id: str
    yes_bid: Optional[float] = None
    yes_ask: Optional[float] = None
    last_price: Optional[float] = None
    volume: Optional[float] = None
    spread: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ts": self.ts,
            "market_id": self.market_id,
            "yes_bid": self.yes_bid,
            "yes_ask": self.yes_ask,
            "last_price": self.last_price,
            "volume": self.volume,
            "spread": self.spread,
        }


# ── Collector ───────────────────────────────────────────────────────────────

_COLS = ["ts", "market_id", "yes_bid", "yes_ask", "last_price", "volume", "spread"]

# Default max rows kept in memory (≈ 100k ticks ≈ 10-20 MB)
_MAX_ROWS = 100_000


class TickerCollector:
    """Accumulates WS ticker events into a DataFrame.

    Parameters
    ----------
    max_rows : int
        Maximum rows retained in memory.  When exceeded the oldest
        rows are dropped (ring-buffer behaviour).
    """

    def __init__(self, max_rows: int = _MAX_ROWS):
        self._max_rows = max_rows
        self._buffer: Deque[Dict[str, Any]] = deque(maxlen=max_rows)
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._ticks_ingested: int = 0
        self._ticks_dropped: int = 0
        self._last_tick_ts: float = 0.0

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Subscribe to ``kalshi:price_update`` on the event bus."""
        if self._running:
            return
        self._running = True
        try:
            from core.event_bus import event_stream
            await event_stream.subscribe(
                "kalshi:price_update",
                self._on_price_update,
            )
            logger.info("TickerCollector started — listening for price updates")
        except Exception as exc:
            self._running = False
            logger.error(f"TickerCollector failed to start: {exc}")

    async def stop(self) -> None:
        """Unsubscribe and stop collecting."""
        self._running = False
        try:
            from core.event_bus import event_stream
            await event_stream.unsubscribe(
                "kalshi:price_update",
                self._on_price_update,
            )
        except Exception:
            pass
        logger.info(
            f"TickerCollector stopped — {self._ticks_ingested} ticks ingested, "
            f"{self._ticks_dropped} dropped"
        )

    # ── Event handler ──────────────────────────────────────────────────────

    async def _on_price_update(self, event: Dict[str, Any]) -> None:
        """Process a ``kalshi:price_update`` event from the bus."""
        if not self._running:
            return

        payload = event.get("payload", {})
        bid = payload.get("bid")
        ask = payload.get("ask")

        spread = None
        if bid is not None and ask is not None:
            spread = round(ask - bid, 4)

        record = TickRecord(
            ts=time.time(),
            market_id=payload.get("market_id", ""),
            yes_bid=bid,
            yes_ask=ask,
            last_price=payload.get("last"),
            volume=payload.get("volume"),
            spread=spread,
        )

        self._buffer.append(record.to_dict())
        self._ticks_ingested += 1
        self._last_tick_ts = record.ts

    # ── Query interface ────────────────────────────────────────────────────

    def snapshot(self, market_id: Optional[str] = None) -> Any:
        """Return a **copy** of the current tick DataFrame.

        Parameters
        ----------
        market_id : str, optional
            Filter to a single market.

        Returns
        -------
        pd.DataFrame  (or list[dict] if pandas unavailable)
        """
        rows = list(self._buffer)
        if market_id:
            rows = [r for r in rows if r["market_id"] == market_id]

        if _HAS_PANDAS:
            df = pd.DataFrame(rows, columns=_COLS)
            if not df.empty and "ts" in df.columns:
                df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
                df = df.set_index("ts")
            return df

        return rows

    def resample(
        self,
        rule: str = "5min",
        market_id: Optional[str] = None,
    ) -> Any:
        """Resample ticks into OHLCV-style bars.

        Parameters
        ----------
        rule : str
            Pandas offset alias (e.g. ``"1min"``, ``"5min"``, ``"1h"``).
        market_id : str, optional
            Filter to a single market.

        Returns
        -------
        pd.DataFrame with columns [open, high, low, close, volume, tick_count]
        """
        if not _HAS_PANDAS:
            logger.warning("pandas not installed — resample unavailable")
            return []

        df = self.snapshot(market_id)
        if df.empty:
            return df

        # Use last_price for OHLC; fall back to midpoint of bid/ask
        if "last_price" in df.columns:
            price = df["last_price"].combine_first(
                (df["yes_bid"] + df["yes_ask"]) / 2
            )
        else:
            price = (df["yes_bid"] + df["yes_ask"]) / 2

        bars = price.resample(rule).ohlc()
        bars.columns = ["open", "high", "low", "close"]
        bars["volume"] = df["volume"].resample(rule).last()
        bars["tick_count"] = price.resample(rule).count()
        bars["spread_mean"] = df["spread"].resample(rule).mean()

        return bars.dropna(subset=["close"])

    def latest(self, n: int = 20) -> List[Dict[str, Any]]:
        """Return the ``n`` most recent ticks as dicts (for API)."""
        items = list(self._buffer)
        return items[-n:]

    def market_ids(self) -> List[str]:
        """Return unique market IDs seen so far."""
        seen: set = set()
        for r in self._buffer:
            seen.add(r["market_id"])
        return sorted(seen)

    # ── Observability ──────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """Health stats for dashboards."""
        return {
            "running": self._running,
            "ticks_ingested": self._ticks_ingested,
            "buffer_size": len(self._buffer),
            "buffer_max": self._max_rows,
            "unique_markets": len(self.market_ids()),
            "last_tick_ts": self._last_tick_ts,
        }


# ── Singleton ────────────────────────────────────────────────────────────────

_collector: Optional[TickerCollector] = None


def get_ticker_collector() -> TickerCollector:
    """Get or create the singleton TickerCollector."""
    global _collector
    if _collector is None:
        _collector = TickerCollector()
    return _collector
