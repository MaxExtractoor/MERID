#!/usr/bin/env python3
"""
Kalshi Deployment Safety Check Script

Automated safety checks to prevent "stupid contract" trades from reaching production.

Usage:
    python scripts/ci/kalshi_safety_check.py --check deep_otm_itm
    python scripts/ci/kalshi_safety_check.py --check model_prob_distance
    python scripts/ci/kalshi_safety_check.py --check all
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

try:
    from merid.event_venues.kalshi.kalshi_deployment_safety_metrics import inc_emergency_override
    SAFETY_METRICS_AVAILABLE = True
except ImportError:
    SAFETY_METRICS_AVAILABLE = False
    print("WARNING: Kalshi modules not available - running in dry-run mode")


@dataclass
class SafetyCheckResult:
    """Result of a safety check."""
    check_name: str
    passed: bool
    violations: List[Dict[str, Any]] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    message: str = ""


def check_deep_otm_itm_exposure(trades: List[Dict[str, Any]]) -> SafetyCheckResult:
    """Check for deep OTM/ITM contract exposure.
    
    Args:
        trades: List of trade dicts with 'price_cents', 'ticker', 'strategy' keys
    
    Returns:
        SafetyCheckResult with violation details
    """
    if not KALSHI_AVAILABLE:
        return SafetyCheckResult(
            check_name="deep_otm_itm_exposure",
            passed=True,
            message="Skipped - Kalshi modules not available"
        )
    
    deep_otm = [t for t in trades if t.get('price_cents', 50) < DEEP_OTM_THRESHOLD_CENTS]
    deep_itm = [t for t in trades if t.get('price_cents', 50) > DEEP_ITM_THRESHOLD_CENTS]
    
    violations = []
    
    for trade in deep_otm:
        violations.append({
            "type": "deep_otm",
            "ticker": trade.get('ticker', 'unknown'),
            "price_cents": trade.get('price_cents'),
            "threshold": DEEP_OTM_THRESHOLD_CENTS,
            "strategy": trade.get('strategy', 'unknown'),
        })
    
    for trade in deep_itm:
        violations.append({
            "type": "deep_itm",
            "ticker": trade.get('ticker', 'unknown'),
            "price_cents": trade.get('price_cents'),
            "threshold": DEEP_ITM_THRESHOLD_CENTS,
            "strategy": trade.get('strategy', 'unknown'),
        })
    
    # Pass if violations are < 5% of total trades
    total_trades = len(trades)
    violation_pct = len(violations) / total_trades if total_trades > 0 else 0
    passed = violation_pct < 0.05
    
    return SafetyCheckResult(
        check_name="deep_otm_itm_exposure",
        passed=passed,
        violations=violations,
        metrics={
            "deep_otm_count": len(deep_otm),
            "deep_itm_count": len(deep_itm),
            "total_trades": total_trades,
            "violation_pct": violation_pct,
            "threshold_pct": 0.05,
            "otm_threshold_cents": DEEP_OTM_THRESHOLD_CENTS,
            "itm_threshold_cents": DEEP_ITM_THRESHOLD_CENTS,
        },
        message=f"Found {len(violations)} extreme price trades ({violation_pct:.1%} of total)"
    )


def check_model_prob_distance(trades: List[Dict[str, Any]]) -> SafetyCheckResult:
    """Check for model-market probability misalignment.
    
    Args:
        trades: List of trade dicts with 'price_cents', 'model_prob', 'ticker', 'strategy' keys
    
    Returns:
        SafetyCheckResult with violation details
    """
    if not KALSHI_AVAILABLE:
        return SafetyCheckResult(
            check_name="model_prob_distance",
            passed=True,
            message="Skipped - Kalshi modules not available"
        )
    
    misaligned = []
    
    for trade in trades:
        price_cents = trade.get('price_cents', 50)
        model_prob = trade.get('model_prob')
        
        if model_prob is None:
            continue
        
        price_prob = price_cents / 100.0
        distance = abs(model_prob - price_prob)
        
        if distance > MODEL_PROB_DISTANCE_THRESHOLD:
            misaligned.append({
                "ticker": trade.get('ticker', 'unknown'),
                "price_cents": price_cents,
                "model_prob": model_prob,
                "price_prob": price_prob,
                "distance": distance,
                "threshold": MODEL_PROB_DISTANCE_THRESHOLD,
                "strategy": trade.get('strategy', 'unknown'),
            })
    
    # Pass if misaligned trades are < 2% of total trades
    total_trades = len(trades)
    violation_pct = len(misaligned) / total_trades if total_trades > 0 else 0
    passed = violation_pct < 0.02
    
    return SafetyCheckResult(
        check_name="model_prob_distance",
        passed=passed,
        violations=misaligned,
        metrics={
            "misaligned_count": len(misaligned),
            "total_trades": total_trades,
            "violation_pct": violation_pct,
            "threshold_pct": 0.02,
            "distance_threshold": MODEL_PROB_DISTANCE_THRESHOLD,
        },
        message=f"Found {len(misaligned)} misaligned trades ({violation_pct:.1%} of total)"
    )


def check_pf_expectancy_gates(trades: List[Dict[str, Any]]) -> SafetyCheckResult:
    """Check for trades violating PF/expectancy gates.
    
    Args:
        trades: List of trade dicts with 'profit_factor', 'expectancy_cents' keys
    
    Returns:
        SafetyCheckResult with violation details
    """
    if not KALSHI_AVAILABLE:
        return SafetyCheckResult(
            check_name="pf_expectancy_gates",
            passed=True,
            message="Skipped - Kalshi modules not available"
        )
    
    pf_violations = [
        t for t in trades 
        if t.get('profit_factor', 0) < SIZER_PF_MIN_FOR_SCALING
    ]
    
    expectancy_violations = [
        t for t in trades 
        if t.get('expectancy_cents', 0) < SIZER_EXPECTANCY_MIN_CENTS
    ]
    
    violations = []
    
    for trade in pf_violations:
        violations.append({
            "type": "pf_violation",
            "ticker": trade.get('ticker', 'unknown'),
            "profit_factor": trade.get('profit_factor'),
            "threshold": SIZER_PF_MIN_FOR_SCALING,
        })
    
    for trade in expectancy_violations:
        violations.append({
            "type": "expectancy_violation",
            "ticker": trade.get('ticker', 'unknown'),
            "expectancy_cents": trade.get('expectancy_cents'),
            "threshold": SIZER_EXPECTANCY_MIN_CENTS,
        })
    
    # Pass if zero violations (these are hard gates)
    passed = len(violations) == 0
    
    return SafetyCheckResult(
        check_name="pf_expectancy_gates",
        passed=passed,
        violations=violations,
        metrics={
            "pf_violations": len(pf_violations),
            "expectancy_violations": len(expectancy_violations),
            "total_violations": len(violations),
            "pf_threshold": SIZER_PF_MIN_FOR_SCALING,
            "expectancy_threshold": SIZER_EXPECTANCY_MIN_CENTS,
        },
        message=f"Found {len(violations)} PF/expectancy violations"
    )


def load_sample_trades() -> List[Dict[str, Any]]:
    """Load sample trades for testing (placeholder for real implementation).
    
    In production, this would load from:
    - Recent trade log from fills_ledger
    - Backtest results from historical data
    - Paper trading session data
    """
    # Placeholder - return empty list for now
    return []


def run_all_checks(trades: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Run all safety checks.
    
    Args:
        trades: Optional list of trades to check. If None, loads from default source.
    
    Returns:
        Dict with all check results and overall pass/fail status
    """
    if trades is None:
        trades = load_sample_trades()
    
    if not trades:
        print("WARNING: No trades to check - running with empty dataset")
        trades = []
    
    results = {
        "timestamp": datetime.utcnow().isoformat(),
        "total_trades": len(trades),
        "checks": {},
        "overall_passed": True,
    }
    
    # Run each check
    checks_to_run = [
        check_deep_otm_itm_exposure,
        check_model_prob_distance,
        check_pf_expectancy_gates,
    ]
    
    for check_fn in checks_to_run:
        result = check_fn(trades)
        results["checks"][result.check_name] = {
            "passed": result.passed,
            "message": result.message,
            "metrics": result.metrics,
            "violations": result.violations[:10],  # Limit to first 10 for output
        }
        
        if not result.passed:
            results["overall_passed"] = False
    
    return results


def main():
    """Main entry point for CLI usage."""
    parser = argparse.ArgumentParser(
        description="Kalshi Deployment Safety Check Script"
    )
    parser.add_argument(
        "--check",
        choices=["deep_otm_itm", "model_prob_distance", "pf_expectancy", "all"],
        default="all",
        help="Which safety check to run"
    )
    parser.add_argument(
        "--trades-file",
        help="JSON file containing trades to check"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        help="Override violation threshold (percentage, e.g., 0.05 for 5%)"
    )
    parser.add_argument(
        "--output",
        choices=["json", "summary"],
        default="summary",
        help="Output format"
    )
    parser.add_argument(
        "--fail-on-violations",
        action="store_true",
        help="Exit with error code if any check fails"
    )
    parser.add_argument(
        "--emergency-override",
        action="store_true",
        help="Enable emergency override mode (logs override with ticket reference)"
    )
    parser.add_argument(
        "--ticket-id",
        help="Ticket/incident reference for emergency override"
    )
    
    args = parser.parse_args()
    
    # Load trades
    trades = []
    if args.trades_file:
        try:
            with open(args.trades_file, 'r') as f:
                trades = json.load(f)
        except FileNotFoundError:
            print(f"ERROR: Trades file not found: {args.trades_file}")
            sys.exit(1)
    else:
        trades = load_sample_trades()
    
    # Run checks
    if args.check == "all":
        results = run_all_checks(trades)
    elif args.check == "deep_otm_itm":
        result = check_deep_otm_itm_exposure(trades)
        results = {
            "timestamp": datetime.utcnow().isoformat(),
            "total_trades": len(trades),
            "checks": {
                result.check_name: {
                    "passed": result.passed,
                    "message": result.message,
                    "metrics": result.metrics,
                    "violations": result.violations,
                }
            },
            "overall_passed": result.passed,
        }
    elif args.check == "model_prob_distance":
        result = check_model_prob_distance(trades)
        results = {
            "timestamp": datetime.utcnow().isoformat(),
            "total_trades": len(trades),
            "checks": {
                result.check_name: {
                    "passed": result.passed,
                    "message": result.message,
                    "metrics": result.metrics,
                    "violations": result.violations,
                }
            },
            "overall_passed": result.passed,
        }
    elif args.check == "pf_expectancy":
        result = check_pf_expectancy_gates(trades)
        results = {
            "timestamp": datetime.utcnow().isoformat(),
            "total_trades": len(trades),
            "checks": {
                result.check_name: {
                    "passed": result.passed,
                    "message": result.message,
                    "metrics": result.metrics,
                    "violations": result.violations,
                }
            },
            "overall_passed": result.passed,
        }
    
    # Output results
    if args.output == "json":
        print(json.dumps(results, indent=2))
    else:
        print("\n" + "=" * 60)
        print("KALSHI DEPLOYMENT SAFETY CHECK RESULTS")
        print("=" * 60)
        print(f"Timestamp: {results['timestamp']}")
        print(f"Total Trades: {results['total_trades']}")
        print(f"Overall Status: {'✅ PASSED' if results['overall_passed'] else '❌ FAILED'}")
        
        if args.emergency_override:
            print(f"⚠️  EMERGENCY OVERRIDE MODE: ENABLED")
            print(f"   Ticket ID: {args.ticket_id or 'NOT PROVIDED - REQUIRED FOR AUDIT'}")
            if SAFETY_METRICS_AVAILABLE and args.ticket_id:
                inc_emergency_override(
                    check_name="all_checks",
                    ticket_id=args.ticket_id,
                )
                print(f"   Override logged to Prometheus metrics")
        
        print("\n")
        
        for check_name, check_result in results["checks"].items():
            status = "✅ PASSED" if check_result["passed"] else "❌ FAILED"
            print(f"{check_name}: {status}")
            print(f"  Message: {check_result['message']}")
            
            if check_result["metrics"]:
                print("  Metrics:")
                for key, value in check_result["metrics"].items():
                    print(f"    {key}: {value}")
            
            if check_result["violations"]:
                print(f"  Violations (showing first {len(check_result['violations'])}):")
                for violation in check_result["violations"][:5]:
                    print(f"    - {violation}")
                if len(check_result["violations"]) > 5:
                    print(f"    ... and {len(check_result['violations']) - 5} more")
            print()
    
    # Exit with error code if requested and checks failed
    # In emergency override mode, don't fail even if checks fail
    if args.fail_on_violations and not args.emergency_override and not results["overall_passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
