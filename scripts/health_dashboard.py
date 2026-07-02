#!/usr/bin/env python3
"""
Minimal live health dashboard view.

This script provides a 1-screen readout for the restart window:
- Per-asset: last 15m counts of signals, scheduler rejections, risk rejections, orders, fills, net PnL
- Highlight assets with signals but zero orders or zero fills
- API health: recent error codes from Kalshi endpoints

Usage:
    python scripts/health_dashboard.py --log-dir /path/to/logs
"""

import argparse
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List


def parse_log_line(line: str) -> tuple:
    """Parse log line and extract tag, asset, timestamp, and fields."""
    tag_match = re.search(r'\[([A-Z-]+)\]', line)
    tag = tag_match.group(1) if tag_match else "UNKNOWN"
    
    asset_match = re.search(r'asset=(BTC|ETH|SOL|XRP|DOGE)', line)
    asset = asset_match.group(1) if asset_match else "UNKNOWN"
    
    # Extract timestamp (ISO format)
    ts_match = re.search(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', line)
    timestamp = ts_match.group(1) if ts_match else None
    
    # Extract PnL if present
    pnl_match = re.search(r'pnl_cents=(-?\d+)', line)
    pnl_cents = int(pnl_match.group(1)) if pnl_match else 0
    
    return tag, asset, timestamp, pnl_cents


def analyze_recent_metrics(log_dir: Path, minutes: int = 15) -> Dict:
    """Analyze logs for recent metrics per asset."""
    print(f"Analyzing logs from {log_dir} (last {minutes} minutes)...")
    
    cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    
    # Initialize counters
    assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    metrics = {
        asset: {
            "signals": 0,
            "scheduler_rejections": 0,
            "risk_rejections": 0,
            "orders": 0,
            "fills": 0,
            "pnl_cents": 0,
        }
        for asset in assets
    }
    
    # API error tracking
    api_errors = defaultdict(int)
    
    # Process log files
    log_files = list(log_dir.glob("*.log")) + list(log_dir.glob("*.txt"))
    
    for log_file in log_files:
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    tag, asset, timestamp, pnl_cents = parse_log_line(line)
                    
                    if asset not in assets:
                        continue
                    
                    # Track API errors
                    if "API" in line or "Kalshi" in line:
                        if "error" in line.lower() or "fail" in line.lower():
                            error_code_match = re.search(r'(4\d\d|5\d\d)', line)
                            if error_code_match:
                                api_errors[error_code_match.group(1)] += 1
                    
                    # Skip if no timestamp
                    if not timestamp:
                        continue
                    
                    # Parse timestamp
                    try:
                        line_time = datetime.fromisoformat(timestamp)
                        if line_time < cutoff_time:
                            continue
                    except:
                        continue
                    
                    # Count metrics
                    if tag == "SIGNAL":
                        metrics[asset]["signals"] += 1
                    elif tag == "SCHEDULER-REJECTION":
                        metrics[asset]["scheduler_rejections"] += 1
                    elif tag == "RISK-DECISION":
                        metrics[asset]["risk_rejections"] += 1
                    elif tag == "ORDER-SUBMIT":
                        metrics[asset]["orders"] += 1
                    elif tag == "FILL":
                        metrics[asset]["fills"] += 1
                        metrics[asset]["pnl_cents"] += pnl_cents
        except Exception as e:
            print(f"Error processing {log_file}: {e}")
    
    return metrics, api_errors


def print_dashboard(metrics: Dict, api_errors: Dict):
    """Print the health dashboard."""
    print("\n" + "=" * 100)
    print("LIVE HEALTH DASHBOARD")
    print("=" * 100)
    print(f"Last 15 minutes | {datetime.now(timezone.utc).isoformat()}")
    print()
    
    # Per-asset metrics table
    print("┌──────┬─────────┬──────────────┬──────────────┬────────┬───────┬────────────┐")
    print("│ Asset│ Signals │ Sched Rej    │ Risk Rej     │ Orders │ Fills │ Net PnL ($) │")
    print("├──────┼─────────┼──────────────┼──────────────┼────────┼───────┼────────────┤")
    
    for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
        data = metrics[asset]
        pnl_usd = data["pnl_cents"] / 100.0
        
        # Highlight broken pipes
        asset_str = asset
        if data["signals"] > 0 and data["orders"] == 0:
            asset_str = f"{asset}*"
        elif data["orders"] > 0 and data["fills"] == 0:
            asset_str = f"{asset}**"
        
        print(f"│ {asset_str:4s} │ {data['signals']:7d} │ "
              f"{data['scheduler_rejections']:12d} │ {data['risk_rejections']:12d} │ "
              f"{data['orders']:6d} │ {data['fills']:5d} │ {pnl_usd:10.2f} │")
    
    print("└──────┴─────────┴──────────────┴──────────────┴────────┴───────┴────────────┘")
    print("\n* = Signals but no orders (broken pipe)")
    print("** = Orders but no fills (execution issue)")
    
    # API health
    print("\n" + "=" * 100)
    print("API HEALTH")
    print("=" * 100)
    
    if api_errors:
        print("\nRecent API errors:")
        for code, count in sorted(api_errors.items()):
            print(f"  {code}: {count} errors")
    else:
        print("\n✅ No recent API errors")
    
    # Broken pipe summary
    print("\n" + "=" * 100)
    print("BROKEN PIPE DETECTION")
    print("=" * 100)
    
    broken_pipes = []
    for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
        data = metrics[asset]
        if data["signals"] > 0 and data["orders"] == 0:
            broken_pipes.append(f"{asset}: signals={data['signals']}, orders=0")
        elif data["orders"] > 0 and data["fills"] == 0:
            broken_pipes.append(f"{asset}: orders={data['orders']}, fills=0")
    
    if broken_pipes:
        print("\n⚠️  BROKEN PIPES DETECTED:")
        for pipe in broken_pipes:
            print(f"  - {pipe}")
    else:
        print("\n✅ No broken pipes detected")


def main():
    parser = argparse.ArgumentParser(description="Live health dashboard")
    parser.add_argument("--log-dir", type=Path, required=True, help="Directory containing log files")
    parser.add_argument("--minutes", type=int, default=15, help="Minutes of logs to analyze (default: 15)")
    
    args = parser.parse_args()
    
    if not args.log_dir.exists():
        print(f"Error: Log directory {args.log_dir} does not exist")
        return 1
    
    metrics, api_errors = analyze_recent_metrics(args.log_dir, args.minutes)
    print_dashboard(metrics, api_errors)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
