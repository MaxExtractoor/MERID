"""
QuorumFailureTracker — throttle-and-surface repeated quorum failures.

Design notes
============
* Tracks QUORUM_FAILED outcomes per (asset, timeframe) with a sliding time
  window so alert/event storms are suppressed at the *emission* layer, not at
  the safety action layer.
* Throttling NEVER blocks the underlying safety response (e.g. halting trading
  or triggering governance).  It only gates *additional* alert/event emissions.
* Suppressed events remain observable: every suppressed failure is counted and
  exposed via ``get_metrics()`` and ``get_status()``.
* Thresholds and windows are configured in one place (constructor) and may be
  overridden via a centralised config dict; callers must not re-hardcode them.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("agents.quorum_failure_tracker")

# ── Configuration defaults ────────────────────────────────────────────────────

DEFAULT_WINDOW_S: float = 300.0          # 5-minute sliding window
DEFAULT_THRESHOLD: int = 3               # suppress after this many failures in window
DEFAULT_COOLDOWN_S: float = 60.0         # min gap between emitting the same key again

# ── Status ────────────────────────────────────────────────────────────────────


@dataclass
class QuorumFailureStatus:
    """Current tracker status for a single (asset, timeframe) key."""

    asset: Optional[str]
    timeframe: Optional[str]
    failure_count_in_window: int
    suppressed_count: int
    throttled: bool
    last_failure_at: float
    first_failure_at: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "failure_count_in_window": self.failure_count_in_window,
            "suppressed_count": self.suppressed_count,
            "throttled": self.throttled,
            "last_failure_at": self.last_failure_at,
            "first_failure_at": self.first_failure_at,
        }


# ── Tracker ───────────────────────────────────────────────────────────────────


class QuorumFailureTracker:
    """Tracks quorum failures and decides whether to emit alerts / events.

    Usage
    -----
    Call ``record_failure()`` on every QUORUM_FAILED outcome.  The return value
    indicates whether the caller should *emit* a downstream alert/event.
    The caller MUST still apply the safety action (halt, governance) regardless
    of the return value.

    Example::

        tracker = get_quorum_failure_tracker()

        # Always apply safety action first.
        halt_trading(asset, timeframe)

        # Then decide on alert / event emission.
        should_emit = tracker.record_failure(asset="BTC", timeframe="15m")
        if should_emit:
            alert_manager.fire(...)
            event_bus.publish(...)
    """

    def __init__(
        self,
        window_s: float = DEFAULT_WINDOW_S,
        threshold: int = DEFAULT_THRESHOLD,
        cooldown_s: float = DEFAULT_COOLDOWN_S,
    ) -> None:
        self._window_s = window_s
        self._threshold = threshold
        self._cooldown_s = cooldown_s

        # Per-key ring of failure timestamps (for window counting).
        self._timestamps: Dict[str, Deque[float]] = defaultdict(
            lambda: deque(maxlen=1_000)
        )
        # Per-key suppression counters.
        self._suppressed: Dict[str, int] = defaultdict(int)
        # Per-key last-emitted time.
        self._last_emitted: Dict[str, float] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def record_failure(
        self,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
        reason: str = "",
    ) -> bool:
        """Record a quorum failure and return ``True`` if emission is allowed.

        Parameters
        ----------
        asset, timeframe:
            Canonical values from ``config.crypto_universe``.  Pass ``None``
            for system-wide failures.
        reason:
            Short description of why quorum failed (for structured logging).

        Returns
        -------
        bool
            ``True``  — caller should emit alert / governance event.
            ``False`` — emission throttled; caller should only apply safety action.
        """
        now = time.time()
        key = self._make_key(asset, timeframe)

        # Record this failure.
        self._timestamps[key].append(now)

        # Count failures within the sliding window.
        cutoff = now - self._window_s
        recent = [t for t in self._timestamps[key] if t >= cutoff]
        count_in_window = len(recent)

        should_emit = True

        # Throttle if we have exceeded the threshold and are within cooldown.
        last_emitted = self._last_emitted.get(key)
        if count_in_window > self._threshold and last_emitted is not None:
            time_since_emit = now - last_emitted
            if time_since_emit < self._cooldown_s:
                self._suppressed[key] += 1
                logger.info(
                    "quorum_failure_tracker: suppressing emission for key=%s "
                    "(failures_in_window=%d, threshold=%d, suppressed_total=%d, "
                    "next_emit_in=%.0fs, asset=%s, tf=%s)",
                    key,
                    count_in_window,
                    self._threshold,
                    self._suppressed[key],
                    self._cooldown_s - time_since_emit,
                    asset,
                    timeframe,
                )
                should_emit = False

        if should_emit:
            self._last_emitted[key] = now
            logger.warning(
                "quorum_failure_tracker: QUORUM_FAILED — emitting (key=%s, "
                "count_in_window=%d, asset=%s, tf=%s, reason=%r)",
                key,
                count_in_window,
                asset,
                timeframe,
                reason,
            )

        return should_emit

    def get_status(
        self,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> QuorumFailureStatus:
        """Return current failure status for a specific (asset, timeframe) key."""
        now = time.time()
        key = self._make_key(asset, timeframe)
        timestamps = list(self._timestamps.get(key, []))
        cutoff = now - self._window_s
        recent = [t for t in timestamps if t >= cutoff]
        count_in_window = len(recent)

        last_emitted = self._last_emitted.get(key)
        throttled = False
        if count_in_window > self._threshold and last_emitted is not None:
            throttled = (now - last_emitted) < self._cooldown_s

        return QuorumFailureStatus(
            asset=asset,
            timeframe=timeframe,
            failure_count_in_window=count_in_window,
            suppressed_count=self._suppressed.get(key, 0),
            throttled=throttled,
            last_failure_at=timestamps[-1] if timestamps else 0.0,
            first_failure_at=timestamps[0] if timestamps else 0.0,
        )

    def get_metrics(self) -> Dict[str, Any]:
        """Return aggregate metrics for dashboards and health checks."""
        now = time.time()
        cutoff = now - self._window_s

        per_key: Dict[str, Dict[str, Any]] = {}
        for key, ts_deque in self._timestamps.items():
            timestamps = list(ts_deque)
            recent = [t for t in timestamps if t >= cutoff]
            last_emitted = self._last_emitted.get(key)
            throttled = (
                len(recent) > self._threshold
                and last_emitted is not None
                and (now - last_emitted) < self._cooldown_s
            )
            per_key[key] = {
                "count_in_window": len(recent),
                "suppressed_total": self._suppressed.get(key, 0),
                "throttled": throttled,
                "last_failure_at": timestamps[-1] if timestamps else None,
            }

        return {
            "window_s": self._window_s,
            "threshold": self._threshold,
            "cooldown_s": self._cooldown_s,
            "total_keys": len(per_key),
            "throttled_keys": sum(1 for v in per_key.values() if v["throttled"]),
            "per_key": per_key,
        }

    def reset(
        self,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> None:
        """Reset counters for a key (use after confirmed recovery)."""
        key = self._make_key(asset, timeframe)
        self._timestamps.pop(key, None)
        self._suppressed.pop(key, None)
        self._last_emitted.pop(key, None)
        logger.info(
            "quorum_failure_tracker: reset key=%s (asset=%s, tf=%s)",
            key,
            asset,
            timeframe,
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _make_key(asset: Optional[str], timeframe: Optional[str]) -> str:
        # Use empty string markers that are unambiguous — real asset/timeframe
        # values never contain "<>" so there is no collision risk.
        a = asset if asset is not None else "<none>"
        tf = timeframe if timeframe is not None else "<none>"
        return f"{a}:{tf}"


# ── Singleton ─────────────────────────────────────────────────────────────────

_quorum_failure_tracker: Optional[QuorumFailureTracker] = None


def get_quorum_failure_tracker() -> QuorumFailureTracker:
    """Return the process-wide QuorumFailureTracker (lazy singleton)."""
    global _quorum_failure_tracker
    if _quorum_failure_tracker is None:
        _quorum_failure_tracker = QuorumFailureTracker()
    return _quorum_failure_tracker
