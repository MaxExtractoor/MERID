#!/usr/bin/env python3
"""Generate weekly risk and performance report from analytics scripts.

This script runs all analytics scripts and compiles results into a
comprehensive weekly report suitable for internal review.

Usage::

    python scripts/generate_weekly_report.py --week 2026-W20 --data-dir data/weekly_logs/2026-W20 --output reports/weekly_report_2026-W20.md
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List


def run_analytics_script(script_name: str, args: List[str]) -> Dict[str, Any]:
    """Run an analytics script and return its output.
    
    Args:
        script_name: Name of script to run
        args: Arguments to pass to script
        
    Returns:
        Parsed JSON output from script
    """
    script_path = f"scripts/{script_name}"
    cmd = ["py", script_path] + args
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        # Try to parse JSON output if --output was used
        if "--output" in args:
            output_file = args[args.index("--output") + 1]
            with open(output_file, 'r') as f:
                return json.load(f)
        
        return {"stdout": result.stdout, "stderr": result.stderr}
    except subprocess.CalledProcessError as e:
        return {"error": str(e), "stdout": e.stdout, "stderr": e.stderr}


def generate_markdown_report(
    week: str,
    data_dir: str,
    analytics_results: Dict[str, Any]
) -> str:
    """Generate markdown report from analytics results.
    
    Args:
        week: Week identifier (e.g., 2026-W20)
        data_dir: Data directory path
        analytics_results: Dict of script_name -> results
        
    Returns:
        Markdown report string
    """
    lines = []
    
    # Header
    lines.append(f"# Kalshi 15m Crypto - Weekly Risk & Performance Report")
    lines.append(f"\n**Week:** {week}")
    lines.append(f"**Generated:** {datetime.utcnow().isoformat()}")
    lines.append(f"**Data Directory:** {data_dir}")
    lines.append("\n---\n")
    
    # Executive Summary
    lines.append("## Executive Summary")
    lines.append("\n*Run on production data for the specified week.*")
    lines.append("\n---\n")
    
    # Order Construction Validation
    if "validate_order_construction" in analytics_results:
        lines.append("## Order Construction Validation")
        results = analytics_results["validate_order_construction"]
        
        if "summary" in results:
            summary = results["summary"]
            lines.append(f"\n- **Total orders:** {summary['total']}")
            lines.append(f"- **Clean:** {summary['clean']}")
            lines.append(f"- **Errors:** {summary['errors']}")
            lines.append(f"- **Warnings:** {summary['warnings']}")
        
        if summary.get("errors", 0) > 0:
            lines.append("\n⚠️ **CRITICAL:** Order construction errors detected. Review required.")
        elif summary.get("warnings", 0) > 0:
            lines.append("\n⚠️ **WARNING:** Order construction warnings detected.")
        else:
            lines.append("\n✅ **PASS:** No order construction issues detected.")
        
        lines.append("\n---\n")
    
    # Settlement Validation
    if "validate_settlement_truth" in analytics_results:
        lines.append("## Settlement vs P&L Truth Validation")
        results = analytics_results["validate_settlement_truth"]
        
        if "summary" in results:
            summary = results["summary"]
            lines.append(f"\n- **Total trades:** {summary['total']}")
            lines.append(f"- **Clean:** {summary['clean']}")
            lines.append(f"- **Errors:** {summary['errors']}")
            lines.append(f"- **Warnings:** {summary['warnings']}")
        
        if summary.get("errors", 0) > 0:
            lines.append("\n⚠️ **CRITICAL:** Settlement truth errors detected. Review required.")
        elif summary.get("warnings", 0) > 0:
            lines.append("\n⚠️ **WARNING:** Settlement warnings detected.")
        else:
            lines.append("\n✅ **PASS:** No settlement truth issues detected.")
        
        lines.append("\n---\n")
    
    # Lifecycle Funnel
    if "analytics_lifecycle_funnel" in analytics_results:
        lines.append("## Lifecycle Funnel")
        results = analytics_results["analytics_lifecycle_funnel"]
        
        if "analytics" in results:
            analytics = results["analytics"]
            lines.append(f"\n- **Total unique trades:** {analytics['total_trades']}")
            lines.append("\n**Stage Counts:**")
            
            stage_sequence = [
                'SIGNAL_GENERATED',
                'STRATEGY_GATED',
                'RISK_APPROVED',
                'ORDER_PLACED',
                'FILL_RECEIVED',
                'SETTLED'
            ]
            
            for stage in stage_sequence:
                count = analytics['stage_counts'].get(stage, 0)
                lines.append(f"  - {stage}: {count}")
            
            lines.append("\n**Drop-off Rates:**")
            for transition, metrics in analytics['drop_off_rates'].items():
                lines.append(f"  - {transition}: {metrics['drop_off_rate']:.1%} ({metrics['drop_off_count']} dropped)")
        
        lines.append("\n---\n")
    
    # Side-Specific Outcomes
    if "analytics_side_specific_outcomes" in analytics_results:
        lines.append("## Side-Specific Outcomes")
        results = analytics_results["analytics_side_specific_outcomes"]
        
        if "analytics" in results:
            analytics = results["analytics"]
            lines.append(f"\n- **Total trades:** {analytics['total_trades']}")
            
            lines.append("\n**Overall Performance:**")
            for side in ['long_yes', 'long_no']:
                stats = analytics['overall'][side]
                lines.append(f"\n  **{side.upper()}:**")
                lines.append(f"  - Total trades: {stats['total']}")
                lines.append(f"  - Win rate: {stats['win_rate']:.1%}")
                lines.append(f"  - Avg P&L per trade: ${stats['avg_pnl_per_trade'] / 100:.2f}")
            
            lines.append("\n**By Asset:**")
            for asset in sorted(analytics['by_asset'].keys()):
                lines.append(f"\n  **{asset}:**")
                for side in ['yes', 'no']:
                    stats = analytics['by_asset'][asset][side]
                    if stats['total'] > 0:
                        lines.append(f"    {side.upper()}: win rate {stats['win_rate']:.1%}, avg P&L ${stats['avg_pnl_per_trade'] / 100:.2f}")
        
        lines.append("\n---\n")
    
    # Kill-Switch Analysis
    if "analytics_kill_switch_risk" in analytics_results:
        lines.append("## Kill-Switch / Risk Interaction")
        results = analytics_results["analytics_kill_switch_risk"]
        
        if "analytics" in results:
            analytics = results["analytics"]
            kill_stats = analytics['kill_stats']
            lines.append(f"\n- **Total killed trades:** {kill_stats['total_killed']}")
            lines.append(f"- **Would have won:** {kill_stats['would_have_won']} ({kill_stats['would_have_won_pct']:.1%})")
            lines.append(f"- **Would have lost:** {kill_stats['would_have_lost']} ({kill_stats['would_have_lost_pct']:.1%})")
            
            lines.append("\n**Killed by Reason:**")
            for reason, count in sorted(kill_stats['by_reason'].items(), key=lambda x: -x[1]):
                lines.append(f"  - {reason}: {count}")
        
        lines.append("\n---\n")
    
    # Edge Calibration
    if "analytics_edge_vs_outcomes" in analytics_results:
        lines.append("## Edge Calibration vs Realized Outcomes")
        results = analytics_results["analytics_edge_vs_outcomes"]
        
        if "analytics" in results:
            analytics = results["analytics"]
            lines.append(f"\n- **Total trades analyzed:** {analytics['total_trades_analyzed']}")
            
            lines.append("\n**By Edge Bucket:**")
            bucket_stats = analytics['bucket_stats']
            for label in ["0-2%", "2-4%", "4-6%", "6-8%", "8-10%", "10%+"]:
                stats = bucket_stats[label]
                if stats['total'] > 0:
                    lines.append(f"\n  **{label}:**")
                    lines.append(f"  - Total trades: {stats['total']}")
                    lines.append(f"  - Win rate: {stats['win_rate']:.1%}")
                    lines.append(f"  - Avg P&L per trade: ${stats['avg_pnl_per_trade'] / 100:.2f}")
        
        lines.append("\n---\n")
    
    # Per-Agent Metrics
    if "analytics_per_agent_metrics" in analytics_results:
        lines.append("## Per-Agent Metrics")
        results = analytics_results["analytics_per_agent_metrics"]
        
        if "analytics" in results:
            analytics = results["analytics"]
            lines.append(f"\n- **Total trades analyzed:** {analytics['total_trades_analyzed']}")
            
            lines.append("\n**Entry Window Utilization:**")
            for agent_id, stats in sorted(analytics['window_utilization'].items()):
                lines.append(f"  - {agent_id}: {stats['utilization']:.1%} ({stats['orders_placed']}/{stats['signals_generated']})")
            
            lines.append("\n**By Agent and Asset:**")
            for agent_id in sorted(analytics['by_agent_asset'].keys()):
                lines.append(f"\n  **{agent_id}:**")
                for asset in sorted(analytics['by_agent_asset'][agent_id].keys()):
                    stats = analytics['by_agent_asset'][agent_id][asset]
                    if stats['total'] > 0:
                        lines.append(f"    {asset}: win rate {stats['win_rate']:.1%}, Sharpe {stats['sharpe_ratio']:.2f}")
        
        lines.append("\n---\n")
    
    # Internal Mapping Check
    if "validate_internal_mapping" in analytics_results:
        lines.append("## Internal Mapping Check")
        results = analytics_results["validate_internal_mapping"]
        
        if "summary" in results:
            summary = results["summary"]
            lines.append(f"\n- **Total in manifest:** {summary['total_in_manifest']}")
            lines.append(f"- **Total traded:** {summary['total_traded']}")
            lines.append(f"- **Missing from manifest:** {summary['missing_from_manifest']}")
            lines.append(f"- **Never traded:** {summary['never_traded']}")
        
        if summary.get("missing_from_manifest", 0) > 0:
            lines.append("\n⚠️ **WARNING:** Tickers traded but missing from manifest. Update required.")
        else:
            lines.append("\n✅ **PASS:** All traded tickers in manifest.")
        
        lines.append("\n---\n")
    
    # Recommendations
    lines.append("## Recommendations")
    lines.append("\n*Based on the above analysis, consider the following actions:*")
    lines.append("\n1. Review any critical or high-severity alerts")
    lines.append("2. Investigate significant drop-offs in lifecycle funnel")
    lines.append("3. Adjust edge calibration if win rates deviate from expectations")
    lines.append("4. Review kill-switch decisions if would-have-won rate is high")
    lines.append("5. Update manifest if new tickers are being traded")
    lines.append("\n---\n")
    lines.append("*End of Report*")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate weekly risk and performance report")
    parser.add_argument(
        "--week",
        required=True,
        help="Week identifier (e.g., 2026-W20)"
    )
    parser.add_argument(
        "--data-dir",
        required=True,
        help="Directory containing log files for the week"
    )
    parser.add_argument(
        "--output",
        help="Output report file path"
    )
    
    args = parser.parse_args()
    
    # Create temp directory for intermediate outputs
    import tempfile
    temp_dir = tempfile.mkdtemp()
    
    analytics_results = {}
    
    # Run analytics scripts
    scripts_to_run = [
        ("validate_order_construction.py", [
            "--manifest", "data/kalshi_yes_no_manifest.json",
            "--logs", f"{args.data_dir}/order_logs.jsonl",
            "--output", f"{temp_dir}/order_validation.json"
        ]),
        ("validate_settlement_truth.py", [
            "--trades", f"{args.data_dir}/trades.jsonl",
            "--output", f"{temp_dir}/settlement_validation.json"
        ]),
        ("analytics_lifecycle_funnel.py", [
            "--logs", f"{args.data_dir}/lifecycle_logs.jsonl",
            "--output", f"{temp_dir}/lifecycle_funnel.json"
        ]),
        ("analytics_side_specific_outcomes.py", [
            "--trades", f"{args.data_dir}/trades.jsonl",
            "--output", f"{temp_dir}/side_outcomes.json"
        ]),
        ("validate_internal_mapping.py", [
            "--manifest", "data/kalshi_yes_no_manifest.json",
            "--logs", f"{args.data_dir}/order_logs.jsonl",
            "--output", f"{temp_dir}/internal_mapping.json"
        ]),
        ("analytics_kill_switch_risk.py", [
            "--trades", f"{args.data_dir}/trades.jsonl",
            "--killed", f"{args.data_dir}/killed_trades.jsonl",
            "--output", f"{temp_dir}/kill_switch.json"
        ]),
        ("analytics_edge_vs_outcomes.py", [
            "--trades", f"{args.data_dir}/trades.jsonl",
            "--orders", f"{args.data_dir}/order_logs.jsonl",
            "--output", f"{temp_dir}/edge_calibration.json"
        ]),
        ("analytics_per_agent_metrics.py", [
            "--trades", f"{args.data_dir}/trades.jsonl",
            "--orders", f"{args.data_dir}/order_logs.jsonl",
            "--output", f"{temp_dir}/per_agent.json"
        ]),
    ]
    
    print(f"Generating weekly report for week {args.week}")
    print(f"Data directory: {args.data_dir}")
    print()
    
    for script_name, script_args in scripts_to_run:
        script_key = script_name.replace(".py", "")
        print(f"Running {script_name}...")
        
        # Check if required data files exist
        required_file = None
        if "order_logs" in script_args:
            required_file = f"{args.data_dir}/order_logs.jsonl"
        elif "trades" in script_args:
            required_file = f"{args.data_dir}/trades.jsonl"
        elif "lifecycle_logs" in script_args:
            required_file = f"{args.data_dir}/lifecycle_logs.jsonl"
        elif "killed" in script_args:
            required_file = f"{args.data_dir}/killed_trades.jsonl"
        
        if required_file and not Path(required_file).exists():
            print(f"  Skipping - {required_file} not found")
            analytics_results[script_key] = {"error": f"Data file not found: {required_file}"}
            continue
        
        result = run_analytics_script(script_name, script_args)
        analytics_results[script_key] = result
        
        if "error" in result:
            print(f"  Error: {result['error']}")
        else:
            print(f"  Success")
    
    # Generate markdown report
    print("\nGenerating markdown report...")
    report = generate_markdown_report(args.week, args.data_dir, analytics_results)
    
    # Write output
    if args.output:
        with open(args.output, 'w') as f:
            f.write(report)
        print(f"Report written to {args.output}")
    else:
        print(report)
    
    # Cleanup temp directory
    import shutil
    shutil.rmtree(temp_dir)


if __name__ == "__main__":
    main()
