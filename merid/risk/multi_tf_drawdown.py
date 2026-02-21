"""
Multi-timeframe drawdown guard.

Tracks equity and peak separately for each lane/timeframe key and for a
shared GLOBAL key.  Before placing any trade, the lane checks both its
own per-timeframe DD limit and the global aggregate limit.

Usage:
    guard = get_multi_tf_drawdown_guard()

    # After each fill:
    guard.update_equity("BTC:15m", lane_equity)
    guard.update_equity("GLOBAL", total_equity)

    # Before placing a trade:
    if not guard.allowed("BTC:15m") or not guard.global_allowed():
        return blocked

Default limits (conservative; override via constructor or set_limit()):
    BTC:15m   → 10% max drawdown
    BTC:1h    → 12%
    ETH:15m   → 12%
    BTC:4h    → 15%
    SOL:15m   → 15%
    GLOBAL    → 20%
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-lane state
# ---------------------------------------------------------------------------

@dataclass
class DDState:
    """Tracks equity and peak for a single lane/timeframe key."""
    equity: float
    peak: float

    @property
    def drawdown(self) -> float:
        """Current peak-to-trough drawdown (0..1)."""
        if self.peak <= 0:
            return 0.0
        return (self.peak - self.equity) / self.peak

    def update(self, new_equity: float) -> None:
        self.equity = new_equity
        if new_equity > self.peak:
            self.peak = new_equity


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------

# Default per-key DD limits (fraction, 0..1)
DEFAULT_LIMITS: Dict[str, float] = {
    "BTC:15m":  0.10,
    "BTC:1h":   0.12,
    "ETH:15m":  0.12,
    "BTC:4h":   0.15,
    "ETH:1h":   0.15,
    "SOL:15m":  0.15,
    "GLOBAL":   0.20,
}


class MultiTFDrawdownGuard:
    """
    Per-timeframe and global drawdown brakes.

    Keys follow the "ASSET:TIMEFRAME" convention used by LaneOrchestrator
    (e.g. "BTC:15m", "ETH:1h") plus the special "GLOBAL" key.
    """

    def __init__(self, tf_limits: Optional[Dict[str, float]] = None) -> None:
        self.tf_limits: Dict[str, float] = dict(DEFAULT_LIMITS)
        if tf_limits:
            self.tf_limits.update(tf_limits)
        self._states: Dict[str, DDState] = {}

    # ── Public API ────────────────────────────────────────────────────────

    def set_limit(self, key: str, max_dd: float) -> None:
        """Override the DD limit for a specific key."""
        self.tf_limits[key] = max(0.0, min(1.0, max_dd))

    def update_equity(self, key: str, new_equity: float) -> None:
        """
        Record a new equity value for `key`.

        Creates the state entry on first call using new_equity as the
        initial peak (assumes the lane starts at a high-water mark).
        """
        if key not in self._states:
            self._states[key] = DDState(equity=new_equity, peak=new_equity)
        else:
            self._states[key].update(new_equity)

    def allowed(self, key: str) -> bool:
        """
        Return True if the per-key drawdown is within its limit.

        Returns True if the key has never been updated (no data = no block).
        """
        state = self._states.get(key)
        if state is None:
            return True
        limit = self.tf_limits.get(key, 1.0)
        ok = state.drawdown <= limit
        if not ok:
            logger.warning(
                "MultiTFDrawdownGuard: %s BLOCKED — dd=%.1f%% > limit=%.1f%%",
                key, state.drawdown * 100, limit * 100,
            )
        return ok

    def global_allowed(self) -> bool:
        """Return True if the GLOBAL drawdown is within its limit."""
        return self.allowed("GLOBAL")

    def can_trade(self, key: str) -> tuple[bool, str]:
        """
        Combined check: per-key AND global.

        Returns (allowed, reason).
        """
        if not self.global_allowed():
            state = self._states.get("GLOBAL")
            dd = state.drawdown if state else 0.0
            limit = self.tf_limits.get("GLOBAL", 1.0)
            return False, f"global_dd={dd:.1%} > {limit:.1%}"

        if not self.allowed(key):
            state = self._states.get(key)
            dd = state.drawdown if state else 0.0
            limit = self.tf_limits.get(key, 1.0)
            return False, f"{key}_dd={dd:.1%} > {limit:.1%}"

        return True, "ok"

    def get_status(self) -> Dict:
        return {
            key: {
                "equity": st.equity,
                "peak": st.peak,
                "drawdown": round(st.drawdown, 4),
                "limit": self.tf_limits.get(key, 1.0),
                "allowed": self.allowed(key),
            }
            for key, st in self._states.items()
        }

    def reset_key(self, key: str) -> None:
        """Reset a single key's state (e.g. after a deliberate pause)."""
        if key in self._states:
            st = self._states[key]
            self._states[key] = DDState(equity=st.equity, peak=st.equity)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_guard: Optional[MultiTFDrawdownGuard] = None


def get_multi_tf_drawdown_guard(
    tf_limits: Optional[Dict[str, float]] = None,
) -> MultiTFDrawdownGuard:
    """Get (or create) the singleton MultiTFDrawdownGuard."""
    global _guard
    if _guard is None:
        _guard = MultiTFDrawdownGuard(tf_limits=tf_limits)
    return _guard
