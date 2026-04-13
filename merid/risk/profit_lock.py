"""ProfitLockEngine — session-level realized P&L tracking and profit protection.

Implements the "exponential money loop + don't give it back" rule:

1. Track ``realized_pnl_total`` and ``realized_pnl_session_high`` (peak
   realized P&L for this session).

2. Define a "locked profit":
   ``locked_profit = realized_pnl_session_high × LOCK_FRACTION``
   (e.g. 60% of the session peak is considered "locked in").

3. Compute ``max_drawback`` — the maximum allowed give-back from peak:
   ``max_drawback = locked_profit``
   i.e. we are willing to give back at most the *un-locked* fraction.

4. Step down risk when we approach the give-back limit:
   - SAFE   (well above limit): full multiplier (1.0)
   - CAUTION (within 50% of limit): reduced multiplier (0.5)
   - FROZEN (at/below limit):  no new risk-adding entries (0.0)

5. On a daily-close / compounding trigger, promote locked profits into the
   core bankroll and reset the session tracker.

Usage::

    from merid.risk.profit_lock import ProfitLockEngine, ProfitLockState

    engine = ProfitLockEngine(lock_fraction=0.60)
    engine.record_pnl(+50.0)   # session realized pnl += 50
    engine.record_pnl(+30.0)   # session peak is now 80
    mult = engine.size_multiplier()  # 1.0 — well above limit
    locked = engine.locked_profit    # 80 * 0.60 = 48
    engine.record_pnl(-20.0)         # current = 60, peak = 80
    mult = engine.size_multiplier()  # 1.0 — 60 > 80 - 48 = 32, still safe
    engine.record_pnl(-50.0)         # current = 10, peak = 80
    mult = engine.size_multiplier()  # 0.0 — 10 < 80 - 48 = 32 → FROZEN
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from merid.risk.drawdown_zones import LOCK_FRACTION, MAX_GIVEBACK_FRACTION

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Profit-lock state enum
# ---------------------------------------------------------------------------

class ProfitLockState(str, Enum):
    """State of the profit-lock engine.

    SAFE    — Current realized P&L is comfortably above the give-back limit.
              Full sizing allowed.
    CAUTION — Approaching the give-back limit; reduce sizes by 50%.
    FROZEN  — At or below the give-back limit; no new risk-adding entries for
              the rest of the session.
    """
    SAFE = "safe"
    CAUTION = "caution"
    FROZEN = "frozen"


# Multipliers for each state
_STATE_MULTIPLIERS = {
    ProfitLockState.SAFE: 1.0,
    ProfitLockState.CAUTION: 0.5,
    ProfitLockState.FROZEN: 0.0,
}

# Fraction of ``max_drawback`` at which CAUTION kicks in.
# i.e. when remaining headroom < CAUTION_THRESHOLD × max_drawback → CAUTION.
_CAUTION_THRESHOLD: float = 0.5


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

@dataclass
class ProfitLockEngine:
    """Session-level realized P&L tracker with profit-lock enforcement.

    Thread-safety: not thread-safe; intended for single-threaded async loops.
    Use one instance per session (or one shared instance protected externally).
    """

    lock_fraction: float = LOCK_FRACTION
    """Fraction of session-peak realized P&L that is considered "locked in"."""

    max_giveback_fraction: float = MAX_GIVEBACK_FRACTION
    """Maximum fraction of locked profit that can be given back before freeze.

    Effectively: the *unlocked* fraction (1 - lock_fraction) determines how
    much we can give back.  This param is an explicit override; if zero (the
    default) we derive it as ``1 - lock_fraction``.
    """

    caution_threshold: float = _CAUTION_THRESHOLD
    """Fraction of max_drawback headroom remaining that triggers CAUTION."""

    # ── Internal state ────────────────────────────────────────────────────

    _realized_pnl: float = field(default=0.0, init=False, repr=False)
    _session_high: float = field(default=0.0, init=False, repr=False)
    _state: ProfitLockState = field(default=ProfitLockState.SAFE, init=False, repr=False)
    _core_bankroll_addition: float = field(default=0.0, init=False, repr=False)
    _last_compound_ts: Optional[datetime] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        # Validate
        if not (0.0 < self.lock_fraction <= 1.0):
            raise ValueError(f"lock_fraction must be in (0, 1]; got {self.lock_fraction}")
        # Derive max_giveback_fraction if not explicitly set (non-zero)
        if self.max_giveback_fraction <= 0.0:
            self.max_giveback_fraction = 1.0 - self.lock_fraction

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def realized_pnl(self) -> float:
        """Current session realized P&L."""
        return self._realized_pnl

    @property
    def realized_pnl_session_high(self) -> float:
        """Peak session realized P&L (high-water mark)."""
        return self._session_high

    @property
    def locked_profit(self) -> float:
        """Amount of session peak profits that is "locked in".

        ``locked_profit = session_high × lock_fraction``

        Only meaningful when session_high > 0.
        """
        return max(0.0, self._session_high) * self.lock_fraction

    @property
    def max_drawback(self) -> float:
        """Maximum allowed give-back from session peak before freeze.

        ``max_drawback = locked_profit``
        i.e. the locked fraction IS the max give-back in absolute terms.
        We allow giving back everything *except* the locked portion.
        """
        return self.locked_profit

    @property
    def give_back_limit(self) -> float:
        """Realized P&L floor below which the engine freezes new entries.

        ``give_back_limit = session_high - max_drawback``
        """
        return self._session_high - self.max_drawback

    @property
    def headroom(self) -> float:
        """Remaining P&L headroom before the give-back limit is breached.

        Positive means we can still give back this much before freezing.
        """
        return self._realized_pnl - self.give_back_limit

    @property
    def profit_lock_state(self) -> ProfitLockState:
        """Current profit-lock state (SAFE / CAUTION / FROZEN)."""
        return self._state

    # ── Core API ──────────────────────────────────────────────────────────

    def record_pnl(self, pnl_delta: float) -> ProfitLockState:
        """Record a realized P&L increment (positive = profit, negative = loss).

        Updates the session high-water mark and re-evaluates the state.
        Returns the new state.
        """
        self._realized_pnl += pnl_delta
        if self._realized_pnl > self._session_high:
            self._session_high = self._realized_pnl

        prev_state = self._state
        self._state = self._compute_state()

        if self._state != prev_state:
            logger.warning(
                "[ProfitLock] State: %s → %s  "
                "(realized_pnl=%.2f  session_high=%.2f  "
                "locked=%.2f  max_drawback=%.2f  limit=%.2f  headroom=%.2f)",
                prev_state.value, self._state.value,
                self._realized_pnl, self._session_high,
                self.locked_profit, self.max_drawback,
                self.give_back_limit, self.headroom,
            )

        return self._state

    def size_multiplier(self) -> float:
        """Return the profit-lock size multiplier for the current state.

        - SAFE    → 1.0
        - CAUTION → 0.5
        - FROZEN  → 0.0
        """
        return _STATE_MULTIPLIERS[self._state]

    def compound(self, core_bankroll: float) -> float:
        """Promote locked profits into the core bankroll.

        Call on a schedule (e.g. daily close or when profits exceed a threshold).
        After compounding:
          - ``core_bankroll`` is updated by ``locked_profit``.
          - ``realized_pnl_session_high`` and ``_core_bankroll_addition`` are reset.
          - The engine enters a fresh session.

        Returns:
            Updated core_bankroll.
        """
        addition = self.locked_profit
        new_bankroll = core_bankroll + addition
        logger.info(
            "[ProfitLock] Compound: locked_profit=%.2f added to bankroll=%.2f → %.2f",
            addition, core_bankroll, new_bankroll,
        )
        self._core_bankroll_addition += addition
        self._last_compound_ts = datetime.now(timezone.utc)
        # Reset session tracker for new session
        self._realized_pnl = max(0.0, self._realized_pnl - self._session_high)
        self._session_high = max(0.0, self._realized_pnl)
        self._state = self._compute_state()
        return new_bankroll

    def reset_session(self) -> None:
        """Manually reset the session tracker (e.g. start of trading day)."""
        self._realized_pnl = 0.0
        self._session_high = 0.0
        self._state = ProfitLockState.SAFE
        logger.info("[ProfitLock] Session reset.")

    def get_status(self) -> dict:
        """Return a status dict suitable for dashboards."""
        return {
            "state": self._state.value,
            "size_multiplier": self.size_multiplier(),
            "realized_pnl": round(self._realized_pnl, 4),
            "session_high": round(self._session_high, 4),
            "locked_profit": round(self.locked_profit, 4),
            "max_drawback": round(self.max_drawback, 4),
            "give_back_limit": round(self.give_back_limit, 4),
            "headroom": round(self.headroom, 4),
            "lock_fraction": self.lock_fraction,
            "max_giveback_fraction": self.max_giveback_fraction,
            "core_bankroll_additions": round(self._core_bankroll_addition, 4),
            "last_compound_ts": (
                self._last_compound_ts.isoformat() if self._last_compound_ts else None
            ),
        }

    # ── Internal helpers ──────────────────────────────────────────────────

    def _compute_state(self) -> ProfitLockState:
        """Derive the current state from realized_pnl and session high."""
        # When session_high ≤ 0 (no profits yet) we stay SAFE — nothing to lock
        if self._session_high <= 0.0:
            return ProfitLockState.SAFE

        limit = self.give_back_limit
        headroom = self._realized_pnl - limit

        if headroom <= 0.0:
            return ProfitLockState.FROZEN

        # CAUTION when headroom < caution_threshold × max_drawback
        threshold = self.caution_threshold * self.max_drawback
        if headroom < threshold:
            return ProfitLockState.CAUTION

        return ProfitLockState.SAFE


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine: Optional[ProfitLockEngine] = None


def get_profit_lock_engine() -> ProfitLockEngine:
    """Return the process-level ProfitLockEngine singleton."""
    global _engine
    if _engine is None:
        _engine = ProfitLockEngine()
    return _engine
