"""
ForwardTester — validates live paper-trading performance before lifting clamps.

After a backtest passes validate_before_lift(), the lane enters FORWARD_PAPER
state and accumulates real-time paper fills.  ForwardTester.is_valid() must
return True before KalshiBotLifecycle advances to LIVE_RESTRICTED.

Usage:
    tester = ForwardTester()
    stats  = lane.get_forward_stats()   # built from live paper fills
    if tester.is_valid(stats):
        lifecycle.on_forward_update(stats)
"""

from __future__ import annotations
import logging

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


# ---------------------------------------------------------------------------
# Forward stats snapshot
# ---------------------------------------------------------------------------

@dataclass
class ForwardStats:
    """Accumulated paper-trading metrics since forward test began."""
    start_time: datetime
    equity: float               # current paper equity
    initial_equity: float       # equity at forward-test start
    max_drawdown: float         # 0..1 peak-to-trough
    sharpe: float               # rolling annualised Sharpe
    trades: int                 # completed paper fills
    days: int                   # calendar days since start_time

    # Optional detail
    win_rate: float = 0.0
    pnl_history: List[float] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Tester
# ---------------------------------------------------------------------------

class ForwardTester:
    """
    Validates forward (paper) performance against configurable thresholds.

    All thresholds have conservative defaults; relax them only after
    reviewing actual forward results.
    """

    def __init__(
        self,
        min_days: int = 7,
        min_trades: int = 30,
        max_dd: float = 0.25,
        min_sharpe: float = 0.3,
        min_win_rate: float = 0.0,   # 0 = disabled
    ) -> None:
        self.min_days = min_days
        self.min_trades = min_trades
        self.max_dd = max_dd
        self.min_sharpe = min_sharpe
        self.min_win_rate = min_win_rate

    def is_valid(self, stats: ForwardStats) -> bool:
        """Return True only when all forward criteria are satisfied."""
        _, reason = self.check(stats)
        return reason == "ok"

    def check(self, stats: ForwardStats) -> tuple[bool, str]:
        """Return (passed, reason) for detailed logging."""
        if stats.days < self.min_days:
            return False, f"forward_days: {stats.days} < {self.min_days}"
        if stats.trades < self.min_trades:
            return False, f"forward_trades: {stats.trades} < {self.min_trades}"
        if stats.max_drawdown > self.max_dd:
            return False, f"forward_dd: {stats.max_drawdown:.1%} > {self.max_dd:.1%}"
        if stats.sharpe < self.min_sharpe:
            return False, f"forward_sharpe: {stats.sharpe:.2f} < {self.min_sharpe}"
        if self.min_win_rate > 0 and stats.win_rate < self.min_win_rate:
            return False, f"forward_win_rate: {stats.win_rate:.1%} < {self.min_win_rate:.1%}"
        return True, "ok"


# ---------------------------------------------------------------------------
# ForwardTracker — accumulates fills and builds ForwardStats on demand
# ---------------------------------------------------------------------------

class ForwardTracker:
    """
    Stateful tracker that accumulates paper fills and computes ForwardStats.

    Attach to a BTC15MLane by calling lane.set_forward_tracker(tracker)
    before start().  The lane calls tracker.record_fill(pnl) after each
    paper trade.
    """

    def __init__(self, initial_equity: float) -> None:
        self.initial_equity = initial_equity
        self._equity = initial_equity
        self._peak = initial_equity
        self._max_dd = 0.0
        self._pnl_history: List[float] = []
        self._start_time = datetime.now(timezone.utc)

    def record_fill(self, pnl: float) -> None:
        """Call after each completed paper fill."""
        self._equity = max(0.01, self._equity + pnl)
        self._pnl_history.append(pnl)

        # Trim to prevent unbounded growth in long-running forward tests
        if len(self._pnl_history) > 10_000:
            self._pnl_history = self._pnl_history[-5_000:]

        if self._equity > self._peak:
            self._peak = self._equity
        dd = (self._peak - self._equity) / max(self._peak, 1e-9)
        if dd > self._max_dd:
            self._max_dd = dd

    def get_stats(self) -> ForwardStats:
        """Build a ForwardStats snapshot from accumulated fills."""
        now = datetime.now(timezone.utc)
        days = max(0, (now - self._start_time).days)
        trades = len(self._pnl_history)

        # Rolling Sharpe (~96 15m bars/day, 252 trading days)
        sharpe = 0.0
        if trades >= 5:
            n = trades
            mean = sum(self._pnl_history) / n
            variance = sum((x - mean) ** 2 for x in self._pnl_history) / n
            std = math.sqrt(variance) if variance > 0 else 1e-9
            sharpe = (mean / std) * math.sqrt(96 * 252)

        win_rate = (
            sum(1 for p in self._pnl_history if p > 0) / trades
            if trades > 0 else 0.0
        )

        return ForwardStats(
            start_time=self._start_time,
            equity=self._equity,
            initial_equity=self.initial_equity,
            max_drawdown=self._max_dd,
            sharpe=sharpe,
            trades=trades,
            days=days,
            win_rate=win_rate,
            pnl_history=list(self._pnl_history),
        )

    def reset(self) -> None:
        """Reset tracker (e.g. after a fresh-start)."""
        self._equity = self.initial_equity
        self._peak = self.initial_equity
        self._max_dd = 0.0
        self._pnl_history = []
        self._start_time = datetime.now(timezone.utc)
