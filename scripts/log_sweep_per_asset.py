#!/usr/bin/env python3
"""
Focused log-sweep for BTC vs others (24-72h retrospective per asset).

This script analyzes logs to:
- Count [SIGNAL], [SCHEDULER-REJECTION], [RISK-DECISION], [ORDER-SUBMIT], [FILL] per asset
- Derive funnel conversion (signal→order→fill)
- Rank rejection reasons for BTC vs other assets

Usage:
    python scripts/log_sweep_per_asset.py --log-dir /path/to/logs --hours 24
"""

import argparse
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple


def parse_log_line(line: str) -> Tuple[str, str, Dict[str, str]]:
    """
    Parse a log line and extract tag, asset, and fields.
    
    Returns:
        (tag, asset, fields_dict)
    """
    # Extract log tag (e.g., [SIGNAL], [SCHEDULER-REJECTION])
    tag_match = re.search(r'\[([A-Z-]+)\]', line)
    tag = tag_match.group(1) if tag_match else "UNKNOWN"
    
    # Extract asset (BTC, ETH, SOL, XRP, DOGE)
    asset_match = re.search(r'asset=(BTC|ETH|SOL|XRP|DOGE)', line)
    asset = asset_match.group(1) if asset_match else "UNKNOWN"
    
    # Extract key-value pairs
    fields = {}
    for match in re.finditer(r'(\w+)=([^\s]+)', line):
        key, value = match.groups()
        fields[key] = value
    
    return tag, asset, fields


def analyze_logs(log_dir: Path, hours: int) -> Dict[str, Dict]:
    """
    Analyze logs for per-asset tradeability metrics.
    
    Returns:
        Dict with analysis results per asset
    """
    print(f"Analyzing logs from {log_dir} (last {hours} hours)...")
    
    # Initialize counters
    assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    tag_counts = {asset: defaultdict(int) for asset in assets}
    rejection_reasons = {asset: Counter() for asset in assets}
    
    # Calculate cutoff time
    cutoff_time = datetime.now() - timedelta(hours=hours)
    
    # Process log files
    log_files = list(log_dir.glob("*.log")) + list(log_dir.glob("*.txt"))
    print(f"Found {len(log_files)} log files")
    
    for log_file in log_files:
        print(f"  Processing {log_file.name}...")
        
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    # Skip lines without relevant tags
                    if not any(tag in line for tag in ["SIGNAL", "SCHEDULER-REJECTION", "RISK-DECISION", "ORDER-SUBMIT", "FILL"]):
                        continue
                    
                    # Parse line
                    tag, asset, fields = parse_log_line(line)
                    
                    if asset not in assets:
                        continue
                    
                    # Count tag
                    tag_counts[asset][tag] += 1
                    
                    # Track rejection reasons
                    if tag == "SCHEDULER-REJECTION":
                        reason = fields.get("reason", "unknown")
                        rejection_reasons[asset][reason] += 1
                    elif tag == "RISK-DECISION":
                        reason = fields.get("reason", "unknown")
                        rejection_reasons[asset][reason] += 1
        except Exception as e:
            print(f"  Error processing {log_file}: {e}")
    
    # Compute funnel metrics
    results = {}
    for asset in assets:
        signals = tag_counts[asset].get("SIGNAL", 0)
        orders = tag_counts[asset].get("ORDER-SUBMIT", 0)
        fills = tag_counts[asset].get("FILL", 0)
        scheduler_rejections = tag_counts[asset].get("SCHEDULER-REJECTION", 0)
        risk_rejections = tag_counts[asset].get("RISK-DECISION", 0)
        
        # Funnel conversion rates
        signal_to_order_rate = (orders / signals * 100) if signals > 0 else 0
        order_to_fill_rate = (fills / orders * 100) if orders > 0 else 0
        signal_to_fill_rate = (fills / signals * 100) if signals > 0 else 0
        
        results[asset] = {
            "signals": signals,
            "orders": orders,
            "fills": fills,
            "scheduler_rejections": scheduler_rejections,
            "risk_rejections": risk_rejections,
            "signal_to_order_rate": signal_to_order_rate,
            "order_to_fill_rate": order_to_fill_rate,
            "signal_to_fill_rate": signal_to_fill_rate,
            "scheduler_rejection_reasons": dict(rejection_reasons[asset].most_common(5)),
            "risk_rejection_reasons": dict(rejection_reasons[asset].most_common(5)),
        }
    
    return results


def print_results(results: Dict[str, Dict]):
    """Print analysis results in a readable format."""
    print("\n" + "=" * 80)
    print("PER-ASSET TRADEABILITY ANALYSIS")
    print("=" * 80)
    
    # Summary table
    print("\n┌──────┬─────────┬────────┬───────┬─────────────┬──────────────┬──────────────┐")
    print("│ Asset│ Signals │ Orders │ Fills │ Sig→Order% │ Order→Fill%  │ Sig→Fill%    │")
    print("├──────┼─────────┼────────┼───────┼─────────────┼──────────────┼──────────────┤")
    
    for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
        data = results[asset]
        print(f"│ {asset:4s} │ {data['signals']:7d} │ {data['orders']:6d} │ {data['fills']:5d} │ "
              f"{data['signal_to_order_rate']:11.1f} │ {data['order_to_fill_rate']:12.1f} │ "
              f"{data['signal_to_fill_rate']:12.1f} │")
    
    print("└──────┴─────────┴────────┴───────┴─────────────┴──────────────┴──────────────┘")
    
    # Rejection analysis
    print("\n" + "=" * 80)
    print("REJECTION ANALYSIS")
    print("=" * 80)
    
    for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
        data = results[asset]
        print(f"\n{asset}:")
        print(f"  Scheduler rejections: {data['scheduler_rejections']}")
        if data['scheduler_rejection_reasons']:
            print("  Top reasons:")
            for reason, count in data['scheduler_rejection_reasons'].items():
                print(f"    - {reason}: {count}")
        
        print(f"  Risk rejections: {data['risk_rejections']}")
        if data['risk_rejection_reasons']:
            print("  Top reasons:")
            for reason, count in data['risk_rejection_reasons'].items():
                print(f"    - {reason}: {count}")
    
    # Bottleneck identification
    print("\n" + "=" * 80)
    print("BOTTLENECK IDENTIFICATION")
    print("=" * 80)
    
    for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
        data = results[asset]
        
        if data['signals'] == 0:
            bottleneck = "NO SIGNALS"
        elif data['scheduler_rejections'] > data['orders']:
            bottleneck = "SCHEDULER REJECTION"
        elif data['risk_rejections'] > data['orders']:
            bottleneck = "RISK REJECTION"
        elif data['orders'] == 0:
            bottleneck = "NO ORDERS"
        elif data['order_to_fill_rate'] < 50:
            bottleneck = "LOW FILL RATE"
        else:
            bottleneck = "NONE"
        
        print(f"  {asset}: {bottleneck}")
    
    # BTC vs ETH comparison
    print("\n" + "=" * 80)
    print("BTC VS ETH COMPARISON")
    print("=" * 80)
    
    btc = results["BTC"]
    eth = results["ETH"]
    
    print(f"\nBTC signals: {btc['signals']}, ETH signals: {eth['signals']}")
    print(f"BTC orders: {btc['orders']}, ETH orders: {eth['orders']}")
    print(f"BTC fills: {btc['fills']}, ETH fills: {eth['fills']}")
    
    if btc['signals'] == 0 and eth['signals'] > 0:
        print("\n⚠️  BTC NOT GENERATING SIGNALS - Check signal generation logic")
    elif btc['scheduler_rejections'] > eth['scheduler_rejections'] * 2:
        print("\n⚠️  BTC HAS HIGH SCHEDULER REJECTIONS - Check time window / MD health")
    elif btc['risk_rejections'] > eth['risk_rejections'] * 2:
        print("\n⚠️  BTC HAS HIGH RISK REJECTIONS - Check risk limits / sizing")
    elif btc['orders'] == 0 and eth['orders'] > 0:
        print("\n⚠️  BTC NOT SUBMITTING ORDERS - Check order routing")
    elif btc['fills'] == 0 and eth['fills'] > 0:
        print("\n⚠️  BTC NOT FILLING - Check order book / execution")


def main():
    parser = argparse.ArgumentParser(description="Analyze logs for per-asset tradeability")
    parser.add_argument("--log-dir", type=Path, required=True, help="Directory containing log files")
    parser.add_argument("--hours", type=int, default=24, help="Hours of logs to analyze (default: 24)")
    
    args = parser.parse_args()
    
    if not args.log_dir.exists():
        print(f"Error: Log directory {args.log_dir} does not exist")
        return 1
    
    results = analyze_logs(args.log_dir, args.hours)
    print_results(results)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
