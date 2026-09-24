"""Post-loss / post-close re-entry guard for 15-minute Kalshi markets.

2026-09-24: Live incident — the system entered XRP YES@58, trail-exited at a
loss, then re-entered the SAME market 2.4 minutes later on the OPPOSITE side
(NO@61, chased +23c from the decision price), which also lost.  Anti-tilt
research on per-instrument cooldowns is unambiguous: re-entries immediately
after a loss on the same instrument win materially less often and account for
an outsized share of drawdown.

Policy (env-tunable, defaults chosen for 15m markets):

1. Same-market lock (``MERID_REENTRY_SAME_MARKET_LOCK``, default 1): once a
   position on a ticker has closed, that ticker is ineligible for new entries
   for the remainder of its lifetime.  A 15m market expires minutes later — a
   second entry is economically the same trade with worse information.

2. Asset post-loss cooldown (``MERID_POST_LOSS_COOLDOWN_S``, default 120s):
   after a position closes with a KNOWN negative realized PnL, all new entries
   on that asset are blocked until the cooldown elapses.  Unknown-PnL closes
   (e.g. settlement cleanup paths that never saw an exit price) apply the
   same-market lock but not the cooldown.

3. Same-side re-entry on the same asset is allowed once the cooldown lapses —
   the next window is a genuinely new market with fresh information.

All state is process-local; a restart rebuilds it from fills/settlement
reconciliation before entries are enabled.
"""

import os
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass
class _CloseRecord:
    ticker: str
    asset: str
    side: Optional[str]
    realized_pnl_cents: Optional[float]
    closed_ts: float


class ReentryGuard:
    """Tracks recently closed positions and vets new entries against them."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._closed_by_ticker: Dict[str, _CloseRecord] = {}
        self._last_close_by_asset: Dict[str, _CloseRecord] = {}

    @staticmethod
    def _same_market_lock_enabled() -> bool:
        return os.environ.get("MERID_REENTRY_SAME_MARKET_LOCK", "1") == "1"

    @staticmethod
    def _cooldown_seconds() -> float:
        try:
            return float(os.environ.get("MERID_POST_LOSS_COOLDOWN_S", "120"))
        except (TypeError, ValueError):
            return 120.0

    @staticmethod
    def _asset_from_ticker(ticker: str) -> str:
        try:
            from merid.event_venues.kalshi.market_filter import extract_asset_from_ticker

            return (extract_asset_from_ticker(ticker) or "").upper()
        except Exception:
            return ""

    def record_close(
        self,
        ticker: str,
        side: Optional[str],
        realized_pnl_cents: Optional[float],
        closed_ts: Optional[float] = None,
    ) -> None:
        """Record that a position on ``ticker`` has closed.

        ``realized_pnl_cents`` may be None when the close path cannot attribute
        PnL (e.g. settlement cleanup); unknown closes still trigger the
        same-market lock.
        """
        if not ticker:
            return
        asset = self._asset_from_ticker(ticker)
        record = _CloseRecord(
            ticker=ticker,
            asset=asset,
            side=(side or "").lower() or None,
            realized_pnl_cents=realized_pnl_cents,
            closed_ts=closed_ts if closed_ts is not None else time.time(),
        )
        with self._lock:
            prior = self._closed_by_ticker.get(ticker)
            if prior is not None:
                # Idempotent re-records (settlement re-sweep, monitor remove,
                # reconciliation): keep the ORIGINAL close timestamp — the
                # cooldown must age from when the position actually closed, not
                # reset on every duplicate close event (2026-09-24: perpetual
                # cooldown bug — every re-record refreshed closed_ts and
                # post_loss_cooldown never expired).
                record.closed_ts = prior.closed_ts
                # A close event with unknown PnL (e.g. settlement cleanup in
                # the monitor) must not clobber a record that already carries
                # the authoritative realized PnL for the same ticker.
                if record.realized_pnl_cents is None:
                    record.realized_pnl_cents = prior.realized_pnl_cents
            self._closed_by_ticker[ticker] = record
            # Only advance the asset's last-close marker when this record is a
            # genuinely newer close — a re-recorded old ticker must not
            # overwrite a fresher close's timestamp or PnL.
            prev_asset = self._last_close_by_asset.get(asset)
            if prev_asset is None or record.closed_ts >= prev_asset.closed_ts:
                self._last_close_by_asset[asset] = record

    def check_entry(
        self,
        ticker: str,
        now: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """Return (allowed, reason) for a prospective entry on ``ticker``."""
        now = now if now is not None else time.time()
        with self._lock:
            prior = self._closed_by_ticker.get(ticker)
            asset = self._asset_from_ticker(ticker)
            last_asset_close = self._last_close_by_asset.get(asset)

        if self._same_market_lock_enabled() and prior is not None:
            pnl = prior.realized_pnl_cents
            return False, (
                f"same_market_reentry:ticker={ticker}:prior_pnl="
                f"{'unknown' if pnl is None else f'{pnl:.0f}c'}"
            )

        if last_asset_close is not None:
            pnl = last_asset_close.realized_pnl_cents
            cooldown = self._cooldown_seconds()
            age = now - last_asset_close.closed_ts
            if pnl is not None and pnl < 0 and age < cooldown:
                return False, (
                    f"post_loss_cooldown:asset={asset}:pnl={pnl:.0f}c:"
                    f"age={age:.0f}s:cooldown={cooldown:.0f}s"
                )

        return True, "reentry_ok"

    def reset(self) -> None:
        with self._lock:
            self._closed_by_ticker.clear()
            self._last_close_by_asset.clear()


_guard: Optional[ReentryGuard] = None
_guard_lock = threading.Lock()


def get_reentry_guard() -> ReentryGuard:
    global _guard
    if _guard is None:
        with _guard_lock:
            if _guard is None:
                _guard = ReentryGuard()
    return _guard
