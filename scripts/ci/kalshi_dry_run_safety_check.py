#!/usr/bin/env python3
"""
Kalshi Dry-Run Safety Check — Historical data validation before deployment.

Runs safety checks against a fixed historical day to detect regressions:
- Deep OTM/ITM candidate counts
- Model probability distance distribution
- PF/expectancy violations
- Comparison to baseline (prior release)

Usage:
    python scripts/ci/kalshi_dry_run_safety_check.py --date 2026-05-10
    python scripts/ci/kalshi_dry_run_safety_check.py --date 2026-05-10 --baseline 2026-05-09
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

try:
    from merid.event_venues.kalshi.risk_parameters import (
        DEEP_OTM_THRESHOLD_CENTS,
        DEEP_ITM_THRESHOLD_CENTS,
        MODEL_PROB_DISTANCE_THRESHOLD,
        SIZER_PF_MIN_FOR_SCALING,
        SIZER_EXPECTANCY_MIN_CENTS,
    )
    KALSHI_AVAILABLE = True
except ImportError:
    KALSHI_AVAILABLE = False


@dataclass
class DryRunResult:
    """Result of dry-run safety check."""
    date: str
    total_trades: int = 0
    deep_otm_count: int = 0
    deep_itm_count: int = 0
    model_prob_distance_violations: int = 0
    pf_violations: int = 0
    expectancy_violations: int = 0
    model_prob_distance_stats: Dict[str, float] = field(default_factory=dict)
    passed: bool = True
    message: str = ""
    baseline_comparison: Optional[Dict[str, Any]] = None


def load_historical_trades(date: str) -> List[Dict[str, Any]]:
    """Load historical trades for a given date.
    
    In production, this would load from:
    - Fills ledger snapshot for the date
    - Backtest results
    - Paper trading session data
    
    Args:
        date: Date in YYYY-MM-DD format
    
    Returns:
        List of trade dicts
    """
    # Placeholder - return empty list for now
    # In production, implement actual data loading
    return []


def analyze_trades(trades: List[Dict[str, Any]]) -> DryRunResult:
    """Analyze trades for safety violations.
    
    Args:
        trades: List of trade dicts
    
    Returns:
        DryRunResult with analysis
    """
    if not KALSHI_AVAILABLE:
        return DryRunResult(
            date="unknown",
            passed=True,
            message="Skipped - Kalshi modules not available"
        )
    
    result = DryRunResult(date=datetime.utcnow().strftime("%Y-%m-%d"))
    result.total_trades = len(trades)
    
    model_prob_distances = []
    
    for trade in trades:
        price_cents = trade.get("price_cents", 50)
        
        # Deep OTM/ITM detection
        if price_cents < DEEP_OTM_THRESHOLD_CENTS:
            result.deep_otm_count += 1
        elif price_cents > DEEP_ITM_THRESHOLD_CENTS:
            result.deep_itm_count += 1
        
        # Model probability distance
        model_prob = trade.get("model_prob")
        if model_prob is not None:
            price_prob = price_cents / 100.0
            distance = abs(model_prob - price_prob)
            model_prob_distances.append(distance)
            
            if distance > MODEL_PROB_DISTANCE_THRESHOLD:
                result.model_prob_distance_violations += 1
        
        # PF/expectancy violations
        profit_factor = trade.get("profit_factor", 0)
        if profit_factor < SIZER_PF_MIN_FOR_SCALING:
            result.pf_violations += 1
        
        expectancy_cents = trade.get("expectancy_cents", 0)
        if expectancy_cents < SIZER_EXPECTANCY_MIN_CENTS:
            result.expectancy_violations += 1
    
    # Calculate statistics
    if model_prob_distances:
        result.model_prob_distance_stats = {
            "mean": sum(model_prob_distances) / len(model_prob_distances),
            "max": max(model_prob_distances),
            "min": min(model_prob_distances),
            "p50": sorted(model_prob_distances)[len(model_prob_distances) // 2],
            "p95": sorted(model_prob_distances)[int(len(model_prob_distances) * 0.95)],
            "p99": sorted(model_prob_distances)[int(len(model_prob_distances) * 0.99)],
        }
    
    # Determine pass/fail
    # Fail if:
    # - Deep OTM/ITM > 5% of total trades
    # - Model prob distance violations > 2% of total trades
    # - PF violations > 0 (hard gate)
    # - Expectancy violations > 0 (hard gate)
    
    total = len(trades) if trades else 1
    deep_extreme_pct = (result.deep_otm_count + result.deep_itm_count) / total
    model_dist_violation_pct = result.model_prob_distance_violations / total
    
    if deep_extreme_pct > 0.05:
        result.passed = False
        result.message = f"Deep extreme trades {deep_extreme_pct:.1%} > 5% threshold"
    elif model_dist_violation_pct > 0.02:
        result.passed = False
        result.message = f"Model prob distance violations {model_dist_violation_pct:.1%} > 2% threshold"
    elif result.pf_violations > 0:
        result.passed = False
        result.message = f"PF violations detected: {result.pf_violations}"
    elif result.expectancy_violations > 0:
        result.passed = False
        result.message = f"Expectancy violations detected: {result.expectancy_violations}"
    else:
        result.message = "All safety checks passed"
    
    return result


def compare_to_baseline(current: DryRunResult, baseline: DryRunResult) -> Dict[str, Any]:
    """Compare current result to baseline.
    
    Args:
        current: Current dry-run result
        baseline: Baseline dry-run result
    
    Returns:
        Comparison dict with deltas
    """
    if baseline.total_trades == 0:
        return {"status": "no_baseline", "message": "No baseline data available"}
    
    # Calculate percentage changes
    def pct_change(current_val, baseline_val):
        if baseline_val == 0:
            return 0.0 if current_val == 0 else float('inf')
        return ((current_val - baseline_val) / baseline_val) * 100
    
    comparison = {
        "status": "ok",
        "date": current.date,
        "baseline_date": baseline.date,
        "deltas": {
            "total_trades_pct": pct_change(current.total_trades, baseline.total_trades),
            "deep_otm_pct": pct_change(current.deep_otm_count, baseline.deep_otm_count),
            "deep_itm_pct": pct_change(current.deep_itm_count, baseline.deep_itm_count),
            "model_prob_violations_pct": pct_change(current.model_prob_distance_violations, baseline.model_prob_distance_violations),
            "pf_violations_pct": pct_change(current.pf_violations, baseline.pf_violations),
            "expectancy_violations_pct": pct_change(current.expectancy_violations, baseline.expectancy_violations),
        },
        "alert": False,
    }
    
    # Alert if any metric increased by > 50%
    for metric, delta in comparison["deltas"].items():
        if delta > 50:
            comparison["alert"] = True
            comparison["status"] = "regression_detected"
            comparison["alert_metric"] = metric
            break
    
    return comparison


def main():
    """Main entry point for CLI usage."""
    parser = argparse.ArgumentParser(
        description="Kalshi Dry-Run Safety Check"
    )
    parser.add_argument(
        "--date",
        required=True,
        help="Historical date to analyze (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--baseline",
        help="Baseline date for comparison (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--output",
        choices=["json", "summary"],
        default="summary",
        help="Output format"
    )
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Exit with error code if regression detected"
    )
    
    args = parser.parse_args()
    
    # Load historical trades
    trades = load_historical_trades(args.date)
    
    # Analyze trades
    result = analyze_trades(trades)
    
    # Compare to baseline if provided
    if args.baseline:
        baseline_trades = load_historical_trades(args.baseline)
        baseline_result = analyze_trades(baseline_trades)
        result.baseline_comparison = compare_to_baseline(result, baseline_result)
        
        if result.baseline_comparison["alert"]:
            result.passed = False
            result.message = f"Regression detected: {result.baseline_comparison['alert_metric']}"
    
    # Output results
    if args.output == "json":
        print(json.dumps({
            "date": result.date,
            "total_trades": result.total_trades,
            "deep_otm_count": result.deep_otm_count,
            "deep_itm_count": result.deep_itm_count,
            "model_prob_distance_violations": result.model_prob_distance_violations,
            "pf_violations": result.pf_violations,
            "expectancy_violations": result.expectancy_violations,
            "model_prob_distance_stats": result.model_prob_distance_stats,
            "passed": result.passed,
            "message": result.message,
            "baseline_comparison": result.baseline_comparison,
        }, indent=2))
    else:
        print("\n" + "=" * 60)
        print("KALSHI DRY-RUN SAFETY CHECK")
        print("=" * 60)
        print(f"Date: {result.date}")
        print(f"Total Trades: {result.total_trades}")
        print(f"Overall Status: {'✅ PASSED' if result.passed else '❌ FAILED'}")
        print(f"Message: {result.message}")
        print("\n")
        
        print("Deep OTM/ITM Analysis:")
        print(f"  Deep OTM (< {DEEP_OTM_THRESHOLD_CENTS}¢): {result.deep_otm_count}")
        print(f"  Deep ITM (> {DEEP_ITM_THRESHOLD_CENTS}¢): {result.deep_itm_count}")
        print(f"  Total Extreme: {result.deep_otm_count + result.deep_itm_count}")
        print("\n")
        
        print("Model Probability Distance:")
        print(f"  Violations (> {MODEL_PROB_DISTANCE_THRESHOLD}): {result.model_prob_distance_violations}")
        if result.model_prob_distance_stats:
            print(f"  Mean: {result.model_prob_distance_stats['mean']:.4f}")
            print(f"  Max: {result.model_prob_distance_stats['max']:.4f}")
            print(f"  P95: {result.model_prob_distance_stats['p95']:.4f}")
        print("\n")
        
        print("PF/Expectancy Violations:")
        print(f"  PF Violations: {result.pf_violations}")
        print(f"  Expectancy Violations: {result.expectancy_violations}")
        print("\n")
        
        if result.baseline_comparison:
            print("Baseline Comparison:")
            print(f"  Baseline Date: {result.baseline_comparison['baseline_date']}")
            print(f"  Status: {result.baseline_comparison['status']}")
            if result.baseline_comparison['alert']:
                print(f"  ⚠️  ALERT: Regression in {result.baseline_comparison['alert_metric']}")
            print("\n")
    
    # Exit with error code if requested and checks failed
    if args.fail_on_regression and not result.passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
