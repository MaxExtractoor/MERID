"""Exit-fill markout telemetry.

Post-exit counterpart to ``entry_markout``: for every executed exit fill,
record the held-side mid at +5s/+15s/+60s so exit timing can be scored
against what the market did next.  The ledger's exit-value metric
(realized exit - hold-to-settlement) answers "was exiting right"; these
markouts answer "was the exit *timed* right" — a positive markout means the
held-side price fell after the exit (the exit avoided further downside).

Sign convention: ``markout_cents = exit_exec_price - held_side_mid_later``.
Positive = the market dropped after we sold (exit added value); negative =
the market recovered (exit left value on the table).

Records are appended to ``logs/exit_markouts.jsonl``:

  event=fill     -> baseline at exit fill (mid + trigger + horizon schedule)
  event=markout  -> one row per horizon per exit with markout_cents
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

logger = get_logger("merid.observability.exit_markout")

_HORIZONS_S = (5.0, 15.0, 60.0)
# Same stale-market bound as the entry tracker: near expiry the book
# disappears and marks would record junk.
_MAX_TRACK_AGE_S = 300.0


def _log_path() -> Path:
    base = os.environ.get("MERID_EXIT_MARKOUT_LOG", "").strip()
    if base:
        return Path(base)
    return Path("logs") / "exit_markouts.jsonl"


@dataclass
class _TrackedExit:
    ticker: str
    position_id: str
    asset: str
    side: str  # canonical held side: "yes" | "no"
    exit_price_cents: float
    count: float
    exit_ts: float
    reason: Optional[str]
    entry_price_cents: Optional[float]
    mid_at_exit_cents: Optional[float]  # YES mid at exit
    emitted: set = field(default_factory=set)


class ExitMarkoutTracker:
    """Records exit fills and emits post-exit held-side markouts."""

    def __init__(self, horizons_s=_HORIZONS_S) -> None:
        self._horizons = tuple(horizons_s)
        self._lock = threading.Lock()
        self._tracked: Dict[str, _TrackedExit] = {}  # key: f"{ticker}|{position_id}|{exit_ts_bucket}"

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
            logger.debug("[EXIT-MARKOUT] persist failed: %s", exc)

    def record_exit_fill(
        self,
        *,
        ticker: str,
        position_id: str,
        asset: str,
        side: str,
        exit_price_cents: float,
        count: float,
        reason: Optional[str] = None,
        entry_price_cents: Optional[float] = None,
        exit_ts: Optional[float] = None,
    ) -> None:
        """Register an exit fill for markout tracking.  Idempotent per key."""
        if not ticker or not side or exit_price_cents is None:
            return
        side_norm = side.strip().lower()
        if side_norm not in ("yes", "no"):
            return
        now = exit_ts if exit_ts is not None else time.time()
        # remove_position can run long after the actual exit (restart recon,
        # deferred cleanup).  Registering then would fire every horizon
        # immediately with elapsed >> horizon — garbage marks.  Skip exits
        # already older than the longest horizon.
        if time.time() - now > max(self._horizons):
            return
        mid = self._yes_mid_cents(ticker)
        key = f"{ticker}|{position_id}|{int(now)}"
        with self._lock:
            if key in self._tracked:
                return
            self._tracked[key] = _TrackedExit(
                ticker=ticker,
                position_id=position_id,
                asset=asset,
                side=side_norm,
                exit_price_cents=float(exit_price_cents),
                count=float(count),
                exit_ts=now,
                reason=reason,
                entry_price_cents=entry_price_cents,
                mid_at_exit_cents=mid,
            )
        self._emit({
            "event": "exit_fill",
            "ts": now,
            "ticker": ticker,
            "position_id": position_id,
            "asset": asset,
            "side": side_norm,
            "exit_price_cents": float(exit_price_cents),
            "entry_price_cents": entry_price_cents,
            "count": float(count),
            "reason": reason,
            "yes_mid_at_exit_cents": mid,
            "horizons_s": list(self._horizons),
        })

    def poll(self, now: Optional[float] = None) -> int:
        """Emit due horizon markouts.  Called from the position-monitor poll loop."""
        now = time.time() if now is None else now
        due: list = []
        with self._lock:
            for key, tr in list(self._tracked.items()):
                age = now - tr.exit_ts
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
            held_mid = None if yes_mid is None else (
                yes_mid if tr.side == "yes" else 100.0 - yes_mid
            )
            markout = None if held_mid is None else tr.exit_price_cents - held_mid
            self._emit({
                "event": "exit_markout",
                "ts": now,
                "ticker": tr.ticker,
                "position_id": tr.position_id,
                "asset": tr.asset,
                "side": tr.side,
                "exit_price_cents": tr.exit_price_cents,
                "entry_price_cents": tr.entry_price_cents,
                "count": tr.count,
                "reason": tr.reason,
                "exit_ts": tr.exit_ts,
                "yes_mid_at_exit_cents": tr.mid_at_exit_cents,
                "horizon_s": h,
                "elapsed_s": now - tr.exit_ts,
                "yes_mid_cents": yes_mid,
                "held_mid_cents": held_mid,
                "markout_cents": markout,
            })
            emitted += 1
        return emitted

    def tracked_count(self) -> int:
        with self._lock:
            return len(self._tracked)


_tracker: Optional[ExitMarkoutTracker] = None
_tracker_lock = threading.Lock()


def get_exit_markout_tracker() -> ExitMarkoutTracker:
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = ExitMarkoutTracker()
    return _tracker
