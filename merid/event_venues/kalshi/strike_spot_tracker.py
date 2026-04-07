"""Strike vs Spot Tracker — Audit log for strike/spot alignment per decision.

Logs every trading decision with detailed strike vs spot price context to enable
analysis of market selection quality, staleness detection, and mis-mapped strikes.

Usage::

    from merid.event_venues.kalshi.strike_spot_tracker import (
        get_strike_spot_tracker,
        StrikeSpotSnapshot,
    )

    tracker = get_strike_spot_tracker()

    snapshot = StrikeSpotSnapshot(
        timestamp=datetime.now(timezone.utc),
        asset="BTC",
        timeframe="15m",
        ticker="KXBTC15M-25DEC262200",
        spot_price_at_decision=49800.0,
        kalshi_strike=50000.0,
        spot_minus_strike=-200.0,
        spot_pct_diff=-0.4,
        decision="yes",
        reason="bullish_momentum"
    )
    tracker.record_decision(snapshot)
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Deque, Dict, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.strike_spot_tracker")


@dataclass
class StrikeSpotSnapshot:
    """Per-decision snapshot of strike vs spot alignment."""

    timestamp: datetime
    asset: str
    timeframe: str
    ticker: str
    spot_price_at_decision: float
    kalshi_strike: float
    spot_minus_strike: float  # spot - strike (signed)
    spot_pct_diff: float      # (spot - strike) / strike * 100
    decision: str             # "yes", "no", or "skip"
    reason: str               # Why this decision was made
    market_direction: Optional[str] = None  # "up" or "down"
    forecast_signal: Optional[float] = None


class StrikeSpotTracker:
    """Logs and validates strike vs spot alignment for all decisions.

    Maintains a rolling history of recent decisions for analysis and
    provides staleness checks to guard against mispriced or outdated markets.
    """

    def __init__(self, max_history: int = 1000):
        """Initialize tracker.

        Args:
            max_history: Maximum number of snapshots to retain in memory.
        """
        self._history: Deque[StrikeSpotSnapshot] = deque(maxlen=max_history)
        self._lock = threading.Lock()
        self._stats: Dict[str, int] = {
            "total_decisions": 0,
            "yes_decisions": 0,
            "no_decisions": 0,
            "skip_decisions": 0,
            "stale_strikes": 0,
        }

    def record_decision(self, snapshot: StrikeSpotSnapshot) -> None:
        """Log snapshot to structured log and in-memory history.

        Args:
            snapshot: Decision snapshot with strike/spot context.
        """
        with self._lock:
            self._history.append(snapshot)
            self._stats["total_decisions"] += 1

            if snapshot.decision == "yes":
                self._stats["yes_decisions"] += 1
            elif snapshot.decision == "no":
                self._stats["no_decisions"] += 1
            elif snapshot.decision == "skip":
                self._stats["skip_decisions"] += 1

        # Structured log for analysis
        logger.info(
            "STRIKE_SPOT_DECISION: asset=%s timeframe=%s ticker=%s "
            "spot=%.2f strike=%.2f spot_minus_strike=%.2f spot_pct_diff=%.2f%% "
            "decision=%s reason=%s market_direction=%s forecast_signal=%s",
            snapshot.asset,
            snapshot.timeframe,
            snapshot.ticker,
            snapshot.spot_price_at_decision,
            snapshot.kalshi_strike,
            snapshot.spot_minus_strike,
            snapshot.spot_pct_diff,
            snapshot.decision,
            snapshot.reason,
            snapshot.market_direction or "unknown",
            f"{snapshot.forecast_signal:.4f}" if snapshot.forecast_signal is not None else "n/a"
        )

    def check_staleness(
        self,
        spot: float,
        strike: float,
        max_pct_deviation: float = 10.0,
    ) -> Tuple[bool, str]:
        """Return (is_stale, reason) if spot is far from strike.

        Guards against stale markets or mis-mapped strikes by flagging
        cases where spot price has moved significantly away from the strike.

        Args:
            spot: Current spot price.
            strike: Kalshi strike price from market metadata.
            max_pct_deviation: Maximum allowed percentage deviation.

        Returns:
            (is_stale, reason) tuple.
                is_stale: True if deviation exceeds threshold.
                reason: Human-readable explanation.

        Examples:
            >>> tracker = StrikeSpotTracker()
            >>> tracker.check_staleness(55000.0, 50000.0, max_pct_deviation=5.0)
            (True, 'Spot 10.0% above strike (max 5.0%)')

            >>> tracker.check_staleness(50500.0, 50000.0, max_pct_deviation=5.0)
            (False, '')
        """
        if strike <= 0:
            return True, "Invalid strike price (≤ 0)"

        if spot <= 0:
            return True, "Invalid spot price (≤ 0)"

        pct_diff = abs((spot - strike) / strike * 100.0)

        if pct_diff > max_pct_deviation:
            direction = "above" if spot > strike else "below"
            with self._lock:
                self._stats["stale_strikes"] += 1
            return True, f"Spot {pct_diff:.1f}% {direction} strike (max {max_pct_deviation:.1f}%)"

        return False, ""

    def get_stats(self) -> Dict[str, Any]:
        """Return tracker statistics."""
        with self._lock:
            return {
                **self._stats,
                "history_size": len(self._history),
            }

    def get_recent_history(self, n: int = 100) -> list[StrikeSpotSnapshot]:
        """Return the most recent n snapshots."""
        with self._lock:
            return list(self._history)[-n:]

    def clear_history(self) -> None:
        """Clear all history (primarily for tests)."""
        with self._lock:
            self._history.clear()
            self._stats = {
                "total_decisions": 0,
                "yes_decisions": 0,
                "no_decisions": 0,
                "skip_decisions": 0,
                "stale_strikes": 0,
            }


# Module-level singleton
_tracker: Optional[StrikeSpotTracker] = None
_tracker_lock = threading.Lock()


def get_strike_spot_tracker() -> StrikeSpotTracker:
    """Get or create the singleton StrikeSpotTracker instance."""
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = StrikeSpotTracker()
    return _tracker
