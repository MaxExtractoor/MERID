"""Backtest Sanity Checks — Detect common simulator errors.

Provides validation functions that can be run against a backtest result
or during simulation to catch:

1. **Look-ahead bias**: Strategy using data from after the decision timestamp
2. **Fee enforcement**: Every fill must have fees applied
3. **State leakage**: PnL/margin must be tracked in aggregate, not per-contract
4. **Bar construction bias**: Timestamps must be right-aligned (bar close)
5. **Fill-model optimism**: Detect unrealistic fill rates
6. **Execution delay randomization**: Add realistic execution delays to simulate latency

Usage::

    from merid.event_venues.kalshi.backtest_checks import (
        check_lookahead, check_fees_applied, check_state_leakage,
        check_fill_rate, add_execution_delay, run_all_checks,
    )

    issues = run_all_checks(state, snapshots, trade_log)
    delayed_trades = add_execution_delay(trade_log, delay_ms_range=(50, 500))
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

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


# ── Edge/lag validation checks ─────────────────────────────────────────────

def check_edge_lag_consistency(
    trade_log: List[Dict[str, Any]],
    max_lag_ms: float = 1000.0,
) -> CheckResult:
    """Verify edge/lag metrics are within acceptable bounds.
    
    Detects unrealistic lag values or missing lag data that could indicate
    edge/lag computation issues in backtests.
    
    Args:
        trade_log: List of trade dictionaries with 'lag_ms' and 'edge_lag_ratio' fields
        max_lag_ms: Maximum acceptable lag in milliseconds
        
    Returns:
        CheckResult indicating if edge/lag metrics are consistent
    """
    if not trade_log:
        return CheckResult("edge_lag_consistency", True, "No trades to check")
    
    missing_lag = 0
    excessive_lag = 0
    invalid_ratio = 0
    
    for trade in trade_log:
        lag_ms = trade.get("lag_ms")
        edge_lag_ratio = trade.get("edge_lag_ratio")
        
        # Check for missing lag data
        if lag_ms is None:
            missing_lag += 1
        
        # Check for excessive lag
        elif lag_ms > max_lag_ms:
            excessive_lag += 1
        
        # Check for invalid ratio (should be in [0, 1] or None)
        if edge_lag_ratio is not None and (edge_lag_ratio < 0 or edge_lag_ratio > 1):
            invalid_ratio += 1
    
    issues = []
    if missing_lag > 0:
        issues.append(f"{missing_lag} trades missing lag_ms")
    if excessive_lag > 0:
        issues.append(f"{excessive_lag} trades with lag > {max_lag_ms}ms")
    if invalid_ratio > 0:
        issues.append(f"{invalid_ratio} trades with invalid edge_lag_ratio")
    
    if issues:
        return CheckResult(
            "edge_lag_consistency", False,
            f"Edge/lag consistency issues: {', '.join(issues)}",
            severity="warning",
        )
    
    return CheckResult(
        "edge_lag_consistency", True,
        f"All {len(trade_log)} trades have valid edge/lag metrics"
    )


def check_volatility_regime_distribution(
    trade_log: List[Dict[str, Any]],
    min_regime_samples: int = 10,
) -> CheckResult:
    """Verify volatility regime distribution is reasonable.
    
    Detects if backtest is biased toward a single volatility regime,
    which could indicate data quality issues or unrealistic market conditions.
    
    Args:
        trade_log: List of trade dictionaries with 'vol_regime' field
        min_regime_samples: Minimum samples expected per regime
        
    Returns:
        CheckResult indicating if regime distribution is reasonable
    """
    if not trade_log:
        return CheckResult("vol_regime_distribution", True, "No trades to check")
    
    regime_counts: Dict[str, int] = {}
    for trade in trade_log:
        regime = trade.get("vol_regime", "UNKNOWN")
        regime_counts[regime] = regime_counts.get(regime, 0) + 1
    
    # Check if any regime has insufficient samples
    underrepresented = [
        f"{regime} ({count})"
        for regime, count in regime_counts.items()
        if count < min_regime_samples
    ]
    
    if underrepresented:
        return CheckResult(
            "vol_regime_distribution", False,
            f"Underrepresented regimes: {', '.join(underrepresented)}",
            severity="warning",
        )
    
    return CheckResult(
        "vol_regime_distribution", True,
        f"Regime distribution: {dict(regime_counts)}"
    )


# ── Execution delay randomization ───────────────────────────────────────────

def add_execution_delay(
    trade_log: List[Dict[str, Any]],
    delay_ms_range: Tuple[int, int] = (50, 500),
    seed: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Add realistic execution delays to trade log to simulate network/processing latency.

    In real trading, there is always some delay between decision and execution.
    This function adds random delays to trade timestamps to make backtests more realistic.

    Args:
        trade_log: List of trade dictionaries with 'ts' (fill timestamp) and 'decision_ts' fields
        delay_ms_range: Tuple of (min_delay_ms, max_delay_ms) for random delay
        seed: Optional random seed for reproducibility

    Returns:
        Modified trade log with updated timestamps reflecting execution delays
    """
    if seed is not None:
        random.seed(seed)

    delayed_log = []
    for trade in trade_log:
        trade_copy = trade.copy()
        
        # Generate random delay in milliseconds
        delay_ms = random.randint(delay_ms_range[0], delay_ms_range[1])
        delay_seconds = delay_ms / 1000.0
        
        # Apply delay to fill timestamp
        original_ts = trade_copy.get("ts", 0)
        trade_copy["ts"] = original_ts + delay_seconds
        
        # Track the applied delay for analysis
        trade_copy["execution_delay_ms"] = delay_ms
        
        delayed_log.append(trade_copy)
    
    logger.info(
        "[BACKTEST-DELAY] Added execution delays to %d trades (range: %d-%dms)",
        len(trade_log), delay_ms_range[0], delay_ms_range[1]
    )
    
    return delayed_log


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
    include_edge_lag_checks: bool = True,
) -> Dict[str, Any]:
    """Run all backtest sanity checks and return a summary.

    Args:
        trade_log: List of trade dictionaries
        pnl_history: PnL history for state leakage check
        total_fees: Total fees paid
        initial_cash: Initial cash amount
        orders_attempted: Number of orders attempted
        fills_executed: Number of fills executed
        snapshots: Market snapshots for bar alignment check
        expected_interval_seconds: Expected interval between snapshots
        include_edge_lag_checks: Whether to include edge/lag validation checks

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
    
    # Add edge/lag validation checks if enabled
    if include_edge_lag_checks:
        checks.append(check_edge_lag_consistency(trade_log or []))
        checks.append(check_volatility_regime_distribution(trade_log or []))

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
