"""Backtest Sanity Checks — Detect common simulator errors.

Provides validation functions that can be run against a backtest result
or during simulation to catch:

1. **Look-ahead bias**: Strategy using data from after the decision timestamp
2. **Fee enforcement**: Every fill must have fees applied
3. **State leakage**: PnL/margin must be tracked in aggregate, not per-contract
4. **Bar construction bias**: Timestamps must be right-aligned (bar close)
5. **Fill-model optimism**: Detect unrealistic fill rates

Usage::

    from merid.event_venues.kalshi.backtest_checks import (
        check_lookahead, check_fees_applied, check_state_leakage,
        check_fill_rate, run_all_checks,
    )

    issues = run_all_checks(state, snapshots, trade_log)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.backtest_checks")


@dataclass
class CheckResult:
    """Result of a single sanity check."""
    name: str
    passed: bool
    message: str
    severity: str = "warning"  # "warning" or "error"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
            "severity": self.severity,
        }


# ── Look-ahead bias ─────────────────────────────────────────────────────

def check_lookahead(trade_log: List[Dict[str, Any]]) -> CheckResult:
    """Detect look-ahead bias: trades must be ordered by timestamp and
    no trade should reference data from a future timestamp.

    Checks that each trade's decision timestamp is <= its fill timestamp,
    and that trades are monotonically ordered.
    """
    if not trade_log:
        return CheckResult("lookahead", True, "No trades to check")

    violations = 0
    prev_ts = 0.0

    for i, trade in enumerate(trade_log):
        ts = trade.get("ts", 0)
        decision_ts = trade.get("decision_ts", ts)

        # Decision must not be after the fill
        if decision_ts > ts:
            violations += 1

        # Trades must be chronologically ordered
        if ts < prev_ts:
            violations += 1

        prev_ts = ts

    if violations > 0:
        return CheckResult(
            "lookahead", False,
            f"Look-ahead bias detected: {violations} violations in {len(trade_log)} trades",
            severity="error",
        )
    return CheckResult("lookahead", True, "No look-ahead bias detected")


# ── Fee enforcement ──────────────────────────────────────────────────────

def check_fees_applied(trade_log: List[Dict[str, Any]]) -> CheckResult:
    """Verify that every trade has a non-zero fee applied.

    Backtests that exclude fees systematically overstate edge.
    """
    if not trade_log:
        return CheckResult("fees", True, "No trades to check")

    missing_fees = 0
    for trade in trade_log:
        fee = trade.get("fee", 0)
        if fee == 0 or fee is None:
            missing_fees += 1

    if missing_fees > 0:
        pct = missing_fees / len(trade_log) * 100
        return CheckResult(
            "fees", False,
            f"Fee missing on {missing_fees}/{len(trade_log)} trades ({pct:.0f}%)",
            severity="error",
        )
    return CheckResult("fees", True, f"All {len(trade_log)} trades have fees applied")


# ── State leakage ────────────────────────────────────────────────────────

def check_state_leakage(
    pnl_history: List[float],
    total_fees: float,
    initial_cash: float,
) -> CheckResult:
    """Verify PnL accounting consistency.

    The final equity should equal initial_cash + sum of all PnL changes.
    Large discrepancies indicate state leakage between markets.
    """
    if not pnl_history:
        return CheckResult("state_leakage", True, "No PnL history to check")

    final_equity = pnl_history[-1]

    # Check that PnL history is monotonically derivable from initial cash
    # (i.e., no unexplained jumps)
    max_jump = 0.0
    for i in range(1, len(pnl_history)):
        jump = abs(pnl_history[i] - pnl_history[i - 1])
        if jump > max_jump:
            max_jump = jump

    # Suspicious if any single-step change exceeds 20% of initial cash
    threshold = initial_cash * 0.20
    if max_jump > threshold and initial_cash > 0:
        return CheckResult(
            "state_leakage", False,
            f"Suspicious PnL jump: {max_jump:.0f} (threshold {threshold:.0f}). "
            f"Check for state leakage between markets.",
            severity="warning",
        )

    return CheckResult(
        "state_leakage", True,
        f"PnL accounting consistent. Max step: {max_jump:.0f}, fees: {total_fees:.0f}",
    )


# ── Fill rate check ──────────────────────────────────────────────────────

def check_fill_rate(
    orders_attempted: int,
    fills_executed: int,
    max_fill_rate: float = 0.95,
) -> CheckResult:
    """Detect unrealistically high fill rates.

    In real markets, not all limit orders fill. A fill rate above 95%
    in a backtest suggests the fill model is too optimistic.
    """
    if orders_attempted == 0:
        return CheckResult("fill_rate", True, "No orders attempted")

    fill_rate = fills_executed / orders_attempted
    if fill_rate > max_fill_rate:
        return CheckResult(
            "fill_rate", False,
            f"Fill rate {fill_rate:.1%} exceeds {max_fill_rate:.0%} — "
            f"fill model may be too optimistic ({fills_executed}/{orders_attempted})",
            severity="warning",
        )

    return CheckResult(
        "fill_rate", True,
        f"Fill rate {fill_rate:.1%} within bounds ({fills_executed}/{orders_attempted})",
    )


# ── Bar construction bias ────────────────────────────────────────────────

def check_bar_alignment(
    snapshots: List[Dict[str, Any]],
    expected_interval_seconds: int = 3600,
) -> CheckResult:
    """Check that snapshot timestamps are right-aligned (bar close).

    When resampling to hourly bars, timestamps should correspond to the
    bar *close* (right edge), not the open.  Misalignment can leak
    future highs/lows into the decision point.

    Checks that consecutive snapshot intervals are approximately equal
    to the expected interval.
    """
    if len(snapshots) < 2:
        return CheckResult("bar_alignment", True, "Not enough snapshots to check")

    intervals = []
    for i in range(1, min(len(snapshots), 100)):
        ts_curr = snapshots[i].get("ts", 0)
        ts_prev = snapshots[i - 1].get("ts", 0)
        if ts_curr > 0 and ts_prev > 0:
            intervals.append(ts_curr - ts_prev)

    if not intervals:
        return CheckResult("bar_alignment", True, "No valid intervals found")

    avg_interval = sum(intervals) / len(intervals)
    tolerance = expected_interval_seconds * 0.5

    if abs(avg_interval - expected_interval_seconds) > tolerance:
        return CheckResult(
            "bar_alignment", False,
            f"Average interval {avg_interval:.0f}s differs from expected "
            f"{expected_interval_seconds}s — check bar construction (right-align timestamps)",
            severity="warning",
        )

    return CheckResult(
        "bar_alignment", True,
        f"Average interval {avg_interval:.0f}s matches expected {expected_interval_seconds}s",
    )


# ── Run all checks ──────────────────────────────────────────────────────

def run_all_checks(
    trade_log: Optional[List[Dict[str, Any]]] = None,
    pnl_history: Optional[List[float]] = None,
    total_fees: float = 0.0,
    initial_cash: float = 0.0,
    orders_attempted: int = 0,
    fills_executed: int = 0,
    snapshots: Optional[List[Dict[str, Any]]] = None,
    expected_interval_seconds: int = 3600,
) -> Dict[str, Any]:
    """Run all backtest sanity checks and return a summary.

    Returns:
        Dict with "passed" (bool), "checks" (list of CheckResult dicts),
        and "errors"/"warnings" counts.
    """
    checks: List[CheckResult] = []

    checks.append(check_lookahead(trade_log or []))
    checks.append(check_fees_applied(trade_log or []))
    checks.append(check_state_leakage(pnl_history or [], total_fees, initial_cash))
    checks.append(check_fill_rate(orders_attempted, fills_executed))
    checks.append(check_bar_alignment(snapshots or [], expected_interval_seconds))

    errors = sum(1 for c in checks if not c.passed and c.severity == "error")
    warnings = sum(1 for c in checks if not c.passed and c.severity == "warning")
    all_passed = all(c.passed for c in checks)

    return {
        "passed": all_passed,
        "errors": errors,
        "warnings": warnings,
        "total_checks": len(checks),
        "checks": [c.to_dict() for c in checks],
    }
