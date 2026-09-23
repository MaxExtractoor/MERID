"""Entry-fill markout telemetry.

A markout is the standard execution-quality measurement for fills: the signed
difference between the fill price and the market mid ``tau`` seconds later.
Positive = the market moved in the fill's favor; persistently negative markouts
mean fills are adversely selected (the counterparty knew something).

This tracker exists because the 2026-09-23 audit showed resting maker entries
filling at a 41% settlement win rate vs 67% for unfilled orders — fills were
conditioned on the market moving through the limit.  Per-fill markouts at
+10s/+30s/+60s quantify that toxicity continuously so execution-policy changes
can be measured instead of inferred from settlement outcomes.

Records are appended to ``logs/entry_markouts.jsonl``:

  event=fill     -> baseline snapshot at fill time (mid + horizon schedule)
  event=markout  -> one row per horizon per fill with markout_cents
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from utils.logger import get_logger

logger = get_logger("merid.observability.entry_markout")

_HORIZONS_S = (10.0, 30.0, 60.0)
# Give up on a fill's remaining horizons once the market is this stale/gone —
# near expiry the book disappears and the markout would record junk.
_MAX_TRACK_AGE_S = 300.0


def _log_path() -> Path:
    base = os.environ.get("MERID_ENTRY_MARKOUT_LOG", "").strip()
    if base:
        return Path(base)
    return Path("logs") / "entry_markouts.jsonl"


@dataclass
class _TrackedFill:
    ticker: str
    position_id: str
    asset: str
    side: str  # canonical held side: "yes" | "no"
    fill_price_cents: float
    count: float
    fill_ts: float
    mid_at_fill_cents: Optional[float]  # YES mid at fill
    emitted: set = field(default_factory=set)


class EntryMarkoutTracker:
    """Records entry fills and emits held-side markouts at fixed horizons."""

    def __init__(self, horizons_s=_HORIZONS_S) -> None:
        self._horizons = tuple(horizons_s)
        self._lock = threading.Lock()
        self._tracked: Dict[str, _TrackedFill] = {}  # key: f"{ticker}|{position_id}"

    @staticmethod
    def _yes_mid_cents(ticker: str) -> Optional[float]:
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store

            state = get_kalshi_market_state_store().get(ticker)
            if state is None:
                return None
            bid = getattr(state, "best_bid_cents", None)
            ask = getattr(state, "best_ask_cents", None)
            if bid is None or ask is None or bid <= 0 or ask <= 0:
                return None
            return (float(bid) + float(ask)) / 2.0
        except Exception:
            return None

    def _emit(self, record: dict) -> None:
        try:
            path = _log_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
        except Exception as exc:
            logger.debug("[ENTRY-MARKOUT] persist failed: %s", exc)

    def record_entry_fill(
        self,
        *,
        ticker: str,
        position_id: str,
        asset: str,
        side: str,
        fill_price_cents: float,
        count: float,
        fill_ts: Optional[float] = None,
    ) -> None:
        """Register an entry fill for markout tracking.  Idempotent per key."""
        if not ticker or not side:
            return
        side_norm = side.strip().lower()
        if side_norm not in ("yes", "no"):
            return
        key = f"{ticker}|{position_id}"
        now = fill_ts if fill_ts is not None else time.time()
        mid = self._yes_mid_cents(ticker)
        with self._lock:
            if key in self._tracked:
                return
            self._tracked[key] = _TrackedFill(
                ticker=ticker,
                position_id=position_id,
                asset=asset,
                side=side_norm,
                fill_price_cents=float(fill_price_cents),
                count=float(count),
                fill_ts=now,
                mid_at_fill_cents=mid,
            )
        self._emit({
            "event": "fill",
            "ts": now,
            "ticker": ticker,
            "position_id": position_id,
            "asset": asset,
            "side": side_norm,
            "fill_price_cents": float(fill_price_cents),
            "count": float(count),
            "yes_mid_at_fill_cents": mid,
            "horizons_s": list(self._horizons),
        })

    def poll(self, now: Optional[float] = None) -> int:
        """Emit due horizon markouts.  Called from the position-monitor poll loop."""
        now = time.time() if now is None else now
        due: list = []
        with self._lock:
            for key, tr in list(self._tracked.items()):
                age = now - tr.fill_ts
                for h in self._horizons:
                    if h in tr.emitted or age < h:
                        continue
                    due.append((key, tr, h))
                    tr.emitted.add(h)
                if age > _MAX_TRACK_AGE_S or len(tr.emitted) == len(self._horizons):
                    del self._tracked[key]
        emitted = 0
        for key, tr, h in due:
            yes_mid = self._yes_mid_cents(tr.ticker)
            # Held-side mid: YES-held uses the YES mid; NO-held uses the
            # complement (NO mid = 100 - YES mid by Kalshi duality).
            held_mid = None if yes_mid is None else (
                yes_mid if tr.side == "yes" else 100.0 - yes_mid
            )
            markout = None if held_mid is None else held_mid - tr.fill_price_cents
            self._emit({
                "event": "markout",
                "ts": now,
                "ticker": tr.ticker,
                "position_id": tr.position_id,
                "asset": tr.asset,
                "side": tr.side,
                "fill_price_cents": tr.fill_price_cents,
                "count": tr.count,
                "fill_ts": tr.fill_ts,
                "yes_mid_at_fill_cents": tr.mid_at_fill_cents,
                "horizon_s": h,
                "elapsed_s": now - tr.fill_ts,
                "yes_mid_cents": yes_mid,
                "held_mid_cents": held_mid,
                "markout_cents": markout,
            })
            emitted += 1
        return emitted

    def tracked_count(self) -> int:
        with self._lock:
            return len(self._tracked)


_tracker: Optional[EntryMarkoutTracker] = None
_tracker_lock = threading.Lock()


def get_entry_markout_tracker() -> EntryMarkoutTracker:
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = EntryMarkoutTracker()
    return _tracker
