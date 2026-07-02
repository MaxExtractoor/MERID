#!/usr/bin/env python3
"""Run Comparison Script (P2 Task C1).

Compares two run-summary JSON files and prints a diff of key metrics.

Usage:
    python scripts/run_compare.py --baseline data/run_summaries/run_summary_abc.json \
                                  --target data/run_summaries/run_summary_def.json

    python scripts/run_compare.py --baseline data/run_summaries/run_summary_abc.json \
                                  --target data/run_summaries/run_summary_def.json \
                                  --metric edge_gap percentile_50
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def load_run_summary(filepath: Path) -> Dict[str, Any]:
    """Load run summary JSON file."""
    if not filepath.exists():
        print(f"Error: File not found: {filepath}", file=sys.stderr)
        sys.exit(1)
    with open(filepath) as f:
        return json.load(f)


def extract_metrics(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key metrics from run summary for comparison."""
    metrics = {
        "run_id": summary.get("timestamp", "unknown"),
        "profile_version": "unknown",  # Not currently in summary
        "execution_mode": "unknown",  # Not currently in summary
    }

    # Loop metrics
    loop = summary.get("loop", {})
    metrics.update({
        "cycles_completed": loop.get("cycle_count", 0),
        "error_count": loop.get("error_count", 0),
        "uptime_seconds": loop.get("uptime_seconds", 0),
        "halted_due_to_drawdown": loop.get("halted_due_to_drawdown", False),
    })

    # PnL metrics
    pnl = summary.get("pnl", {})
    metrics.update({
        "current_equity_usd": pnl.get("current_equity_usd", 0.0),
    })

    # Risk envelope (if available)
    loop_summary = summary.get("loop", {})
    if "risk_envelope" in loop_summary:
        env = loop_summary["risk_envelope"]
        metrics.update({
            "current_drawdown_pct": env.get("current_drawdown_pct", 0.0) * 100,
            "risk_band": env.get("current_risk_band", "unknown"),
            "is_halted": env.get("is_halted", False),
            "risk_multiplier": env.get("per_trade_risk_multiplier", 1.0),
        })

    # Order metrics (placeholder - not currently exposed in summary)
    orders = summary.get("orders", {})
    metrics.update({
        "orders_submitted": orders.get("orders_submitted", 0),
        "orders_filled": orders.get("orders_filled", 0),
        "fill_rate": 0.0,  # Calculated below
    })

    # Calculate fill rate
    if metrics["orders_submitted"] > 0:
        metrics["fill_rate"] = (metrics["orders_filled"] / metrics["orders_submitted"]) * 100

    # Edge rejection metrics (placeholder - not currently exposed in summary)
    rejections = summary.get("edge_rejections", {})
    metrics.update({
        "no_valid_contract_rejections": rejections.get("no_valid_contract_rejections", 0),
    })

    return metrics


def print_comparison(baseline: Dict[str, Any], target: Dict[str, Any], metric_filter: Optional[str] = None) -> None:
    """Print comparison table."""
    print("=" * 80)
    print("RUN COMPARISON")
    print("=" * 80)
    print(f"Baseline: {baseline['run_id']}")
    print(f"Target:   {target['run_id']}")
    print("=" * 80)
    print()

    # Define metrics to compare
    metrics_to_compare = [
        ("cycles_completed", "Cycles", int),
        ("error_count", "Errors", int),
        ("uptime_seconds", "Uptime (s)", float),
        ("current_equity_usd", "Equity ($)", float),
        ("current_drawdown_pct", "Drawdown (%)", float),
        ("risk_multiplier", "Risk Multiplier", float),
        ("orders_submitted", "Orders Submitted", int),
        ("orders_filled", "Orders Filled", int),
        ("fill_rate", "Fill Rate (%)", float),
        ("no_valid_contract_rejections", "NO_VALID_CONTRACT", int),
    ]

    # Filter if specific metric requested
    if metric_filter:
        metrics_to_compare = [(k, n, t) for k, n, t in metrics_to_compare if k == metric_filter]
        if not metrics_to_compare:
            print(f"Error: Unknown metric '{metric_filter}'", file=sys.stderr)
            print(f"Available metrics: {', '.join(k for k, _, _ in metrics_to_compare)}", file=sys.stderr)
            sys.exit(1)

    # Print header
    print(f"{'Metric':<30} {'Baseline':<15} {'Target':<15} {'Delta':<15} {'% Change':<10}")
    print("-" * 85)

    # Print each metric
    for key, name, dtype in metrics_to_compare:
        baseline_val = baseline.get(key, 0)
        target_val = target.get(key, 0)

        # Calculate delta
        if dtype in (int, float):
            delta = target_val - baseline_val
            if baseline_val != 0:
                pct_change = (delta / baseline_val) * 100
            else:
                pct_change = 0.0
        else:
            delta = 0
            pct_change = 0.0

        # Format values
        if dtype == int:
            baseline_str = f"{int(baseline_val)}"
            target_str = f"{int(target_val)}"
            delta_str = f"{int(delta)}"
        else:
            baseline_str = f"{float(baseline_val):.2f}"
            target_str = f"{float(target_val):.2f}"
            delta_str = f"{float(delta):.2f}"

        pct_str = f"{pct_change:.1f}%"

        # Color coding for significant changes
        if abs(pct_change) > 10:
            delta_str = f"!{delta_str}"
            pct_str = f"!{pct_str}"

        print(f"{name:<30} {baseline_str:<15} {target_str:<15} {delta_str:<15} {pct_str:<10}")

    print("=" * 80)
    print()

    # Print qualitative assessment
    print("QUALITATIVE ASSESSMENT")
    print("-" * 80)

    # Fill rate assessment
    baseline_fill = baseline.get("fill_rate", 0)
    target_fill = target.get("fill_rate", 0)
    if target_fill > baseline_fill + 5:
        print("✓ Fill rate improved significantly (>5%)")
    elif target_fill < baseline_fill - 5:
        print("✗ Fill rate degraded significantly (>5%)")
    else:
        print("→ Fill rate stable (±5%)")

    # Drawdown assessment
    baseline_dd = baseline.get("current_drawdown_pct", 0)
    target_dd = target.get("current_drawdown_pct", 0)
    if target_dd > baseline_dd + 2:
        print("✗ Drawdown increased significantly (>2%)")
    elif target_dd < baseline_dd - 2:
        print("✓ Drawdown decreased significantly (>2%)")
    else:
        print("→ Drawdown stable (±2%)")

    # Error assessment
    baseline_err = baseline.get("error_count", 0)
    target_err = target.get("error_count", 0)
    if target_err > baseline_err:
        print(f"✗ Error count increased ({baseline_err} → {target_err})")
    elif target_err < baseline_err:
        print(f"✓ Error count decreased ({baseline_err} → {target_err})")
    else:
        print("→ Error count stable")

    # Halt assessment
    if target.get("halted_due_to_drawdown", False) and not baseline.get("halted_due_to_drawdown", False):
        print("✗ Target run halted due to drawdown (baseline did not)")
    elif not target.get("halted_due_to_drawdown", False) and baseline.get("halted_due_to_drawdown", False):
        print("✓ Target run did not halt (baseline did)")

    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Compare two run-summary JSON files")
    parser.add_argument("--baseline", required=True, type=Path, help="Baseline run summary JSON")
    parser.add_argument("--target", required=True, type=Path, help="Target run summary JSON")
    parser.add_argument("--metric", type=str, help="Filter to specific metric (e.g., fill_rate)")

    args = parser.parse_args()

    # Load summaries
    baseline_summary = load_run_summary(args.baseline)
    target_summary = load_run_summary(args.target)

    # Extract metrics
    baseline_metrics = extract_metrics(baseline_summary)
    target_metrics = extract_metrics(target_summary)

    # Print comparison
    print_comparison(baseline_metrics, target_metrics, args.metric)


if __name__ == "__main__":
    main()
