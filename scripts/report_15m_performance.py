#!/usr/bin/env python3
"""
Minimal 15m performance dashboard - offline text/markdown report.

Generates a concise per-asset summary showing:
- Trades, win rate, EV per dollar
- Top 2-3 best/worst buckets by EV
- Most common guard reasons

Usage:
    python scripts/report_15m_performance.py --forensics-dir data/forensics/15m --output report.md
"""

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class AssetPerformance:
    """Performance summary for a single asset."""
    asset: str
    total_trades: int
    total_notional: float
    win_rate: float
    avg_edge: float
    ev_per_dollar: float
    best_buckets: List[Dict]
    worst_buckets: List[Dict]
    guard_reasons: Dict[str, int]


def load_latest_forensics(forensics_dir: Path) -> Optional[Dict]:
    """Load the latest forensics analysis JSON."""
    if not forensics_dir.exists():
        print(f"Forensics directory not found: {forensics_dir}")
        return None
    
    json_files = sorted(forensics_dir.glob("*.json"), reverse=True)
    if not json_files:
        print(f"No JSON files found in {forensics_dir}")
        return None
    
    latest_file = json_files[0]
    print(f"Loading forensics from: {latest_file}")
    
    with open(latest_file) as f:
        return json.load(f)


def compute_asset_performance(asset: str, forensics_data: Dict) -> AssetPerformance:
    """Compute performance summary for a single asset."""
    by_asset = forensics_data.get("by_asset", {})
    summary = forensics_data.get("summary", {})
    
    if asset not in by_asset:
        return AssetPerformance(
            asset=asset,
            total_trades=0,
            total_notional=0.0,
            win_rate=0.0,
            avg_edge=0.0,
            ev_per_dollar=0.0,
            best_buckets=[],
            worst_buckets=[],
            guard_reasons={}
        )
    
    asset_data = by_asset[asset]
    
    # Aggregate stats
    total_trades = summary.get("trades_by_asset", {}).get(asset, 0)
    total_notional = summary.get("notional_by_asset", {}).get(asset, 0.0)
    
    # Compute overall win rate and edge from combined buckets
    combined = asset_data.get("combined", {})
    total_wins = 0
    total_edge_sum = 0.0
    
    for bucket_stats in combined.values():
        if bucket_stats.get("trade_count", 0) > 0:
            total_wins += bucket_stats.get("wins", 0)
            total_edge_sum += bucket_stats.get("total_edge", 0.0)
    
    win_rate = total_wins / total_trades if total_trades > 0 else 0.0
    avg_edge = total_edge_sum / total_trades if total_trades > 0 else 0.0
    
    # Simplified EV calculation (avg_edge * notional / notional = avg_edge)
    ev_per_dollar = avg_edge
    
    # Find best and worst buckets by EV
    bucket_evs = []
    for bucket_key, bucket_stats in combined.items():
        if bucket_stats.get("trade_count", 0) >= 5:  # Minimum sample size
            ev = bucket_stats.get("ev_per_dollar", 0.0)
            bucket_evs.append({
                "bucket": bucket_key,
                "ev": ev,
                "trades": bucket_stats.get("trade_count", 0),
                "win_rate": bucket_stats.get("win_rate", 0.0)
            })
    
    # Sort by EV
    bucket_evs.sort(key=lambda x: x["ev"], reverse=True)
    best_buckets = bucket_evs[:3]
    worst_buckets = bucket_evs[-3:] if len(bucket_evs) >= 3 else []
    
    # Get guard reasons
    guard_reasons = dict(summary.get("guard_reasons_by_asset", {}).get(asset, {}))
    
    return AssetPerformance(
        asset=asset,
        total_trades=total_trades,
        total_notional=total_notional,
        win_rate=win_rate,
        avg_edge=avg_edge,
        ev_per_dollar=ev_per_dollar,
        best_buckets=best_buckets,
        worst_buckets=worst_buckets,
        guard_reasons=guard_reasons
    )


def generate_markdown_report(performances: List[AssetPerformance], output_path: Path) -> None:
    """Generate markdown performance report."""
    lines = [
        "# 15m Crypto Performance Report",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "---",
        ""
    ]
    
    for perf in performances:
        lines.append(f"## {perf.asset}")
        lines.append("")
        lines.append(f"**Trades:** {perf.total_trades}")
        lines.append(f"**Notional:** ${perf.total_notional:.2f}")
        lines.append(f"**Win Rate:** {perf.win_rate:.2%}")
        lines.append(f"**Avg Edge:** {perf.avg_edge:.4f}")
        lines.append(f"**EV per Dollar:** {perf.ev_per_dollar:.4f}")
        lines.append("")
        
        # Best buckets
        if perf.best_buckets:
            lines.append("### Best Buckets (by EV)")
            lines.append("")
            for bucket in perf.best_buckets:
                lines.append(f"- `{bucket['bucket']}`: EV={bucket['ev']:.4f}, Trades={bucket['trades']}, Win Rate={bucket['win_rate']:.2%}")
            lines.append("")
        
        # Worst buckets
        if perf.worst_buckets:
            lines.append("### Worst Buckets (by EV)")
            lines.append("")
            for bucket in perf.worst_buckets:
                lines.append(f"- `{bucket['bucket']}`: EV={bucket['ev']:.4f}, Trades={bucket['trades']}, Win Rate={bucket['win_rate']:.2%}")
            lines.append("")
        
        # Guard reasons
        if perf.guard_reasons:
            lines.append("### Guard Reasons (rejection counts)")
            lines.append("")
            sorted_reasons = sorted(perf.guard_reasons.items(), key=lambda x: x[1], reverse=True)
            for reason, count in sorted_reasons:
                lines.append(f"- `{reason}`: {count}")
            lines.append("")
        
        lines.append("---")
        lines.append("")
    
    # Write report
    with open(output_path, 'w') as f:
        f.write('\n'.join(lines))
    
    print(f"Report written to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Generate 15m performance report")
    parser.add_argument(
        "--forensics-dir",
        type=Path,
        default=Path("data/forensics/15m"),
        help="Directory containing forensics JSON files"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/forensics/15m_performance_report.md"),
        help="Output markdown file"
    )
    args = parser.parse_args()
    
    # Load forensics data
    forensics_data = load_latest_forensics(args.forensics_dir)
    if forensics_data is None:
        print("No forensics data available")
        return
    
    # Compute performance for each asset
    assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    performances = []
    
    for asset in assets:
        perf = compute_asset_performance(asset, forensics_data)
        performances.append(perf)
    
    # Generate report
    args.output.parent.mkdir(parents=True, exist_ok=True)
    generate_markdown_report(performances, args.output)
    
    # Print console summary
    print("\n" + "=" * 80)
    print("15m PERFORMANCE SUMMARY")
    print("=" * 80)
    for perf in performances:
        print(f"\n{perf.asset}: {perf.total_trades} trades, Win Rate: {perf.win_rate:.2%}, EV: {perf.ev_per_dollar:.4f}")
        if perf.guard_reasons:
            top_reason = max(perf.guard_reasons.items(), key=lambda x: x[1])
            print(f"  Top guard: {top_reason[0]} ({top_reason[1]} rejections)")


if __name__ == "__main__":
    main()
