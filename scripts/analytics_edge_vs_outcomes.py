#!/usr/bin/env python3
"""Edge gating vs realized outcomes calibration.

This script buckets trades by edge_pct at decision time and computes
realized win rate and average P&L per contract for each bucket.

Usage::

    python scripts/analytics_edge_vs_outcomes.py --trades data/trades.jsonl --orders data/order_logs.jsonl
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def load_trade_logs(trades_path: str) -> List[Dict[str, Any]]:
    """Load trade logs from JSONL file.
    
    Args:
        trades_path: Path to trade logs file (JSONL format)
        
    Returns:
        List of trade log entries
    """
    trades = []
    with open(trades_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    trades.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"Warning: Failed to parse log line: {e}", file=sys.stderr)
    return trades


def load_order_logs(orders_path: str) -> List[Dict[str, Any]]:
    """Load order logs from JSONL file.
    
    Args:
        orders_path: Path to order logs file (JSONL format)
        
    Returns:
        List of order log entries
    """
    orders = []
    with open(orders_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    orders.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"Warning: Failed to parse log line: {e}", file=sys.stderr)
    return orders


def analyze_edge_vs_outcomes(
    trades: List[Dict[str, Any]],
    orders: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Analyze edge gating vs realized outcomes.
    
    Args:
        trades: Trade log entries
        orders: Order log entries
        
    Returns:
        Dict with edge calibration analytics
    """
    # Build edge_pct lookup by intent_id
    edge_by_intent = {}
    for order in orders:
        intent_id = order.get('intent_id')
        edge_pct = order.get('edge_pct')
        ticker = order.get('ticker')
        if intent_id and edge_pct is not None:
            edge_by_intent[intent_id] = {
                'edge_pct': edge_pct,
                'ticker': ticker,
            }
    
    # Define edge buckets
    edge_buckets = [
        (0.0, 0.02, "0-2%"),
        (0.02, 0.04, "2-4%"),
        (0.04, 0.06, "4-6%"),
        (0.06, 0.08, "6-8%"),
        (0.08, 0.10, "8-10%"),
        (0.10, 1.0, "10%+"),
    ]
    
    bucket_stats = {}
    for low, high, label in edge_buckets:
        bucket_stats[label] = {
            'total': 0,
            'wins': 0,
            'total_pnl_cents': 0,
            'total_contracts': 0,
        }
    
    # Analyze trades
    for trade in trades:
        intent_id = trade.get('intent_id') or trade.get('trade_id')
        market_result = trade.get('market_result')
        position_side = trade.get('position_side_at_close')
        pnl_cents = trade.get('realized_pnl_cents', 0)
        filled_size = trade.get('filled_size', 0)
        
        if not intent_id or intent_id not in edge_by_intent:
            continue
        
        edge_info = edge_by_intent[intent_id]
        edge_pct = edge_info['edge_pct']
        
        # Determine bucket
        bucket_label = None
        for low, high, label in edge_buckets:
            if low <= edge_pct < high:
                bucket_label = label
                break
        if not bucket_label:
            bucket_label = "10%+"
        
        # Update bucket stats
        bucket_stats[bucket_label]['total'] += 1
        bucket_stats[bucket_label]['total_contracts'] += filled_size
        bucket_stats[bucket_label]['total_pnl_cents'] += pnl_cents
        
        # Determine if win
        if market_result and position_side:
            if market_result == 'yes' and position_side == 'yes':
                bucket_stats[bucket_label]['wins'] += 1
            elif market_result == 'no' and position_side == 'no':
                bucket_stats[bucket_label]['wins'] += 1
    
    # Calculate metrics per bucket
    for label in bucket_stats:
        stats = bucket_stats[label]
        if stats['total'] > 0:
            stats['win_rate'] = stats['wins'] / stats['total']
            stats['avg_pnl_per_trade'] = stats['total_pnl_cents'] / stats['total']
            stats['avg_pnl_per_contract'] = stats['total_pnl_cents'] / stats['total_contracts'] if stats['total_contracts'] > 0 else 0
        else:
            stats['win_rate'] = 0
            stats['avg_pnl_per_trade'] = 0
            stats['avg_pnl_per_contract'] = 0
    
    return {
        'bucket_stats': bucket_stats,
        'total_trades_analyzed': sum(stats['total'] for stats in bucket_stats.values()),
    }


def main():
    parser = argparse.ArgumentParser(description="Edge gating vs outcomes calibration")
    parser.add_argument(
        "--trades",
        required=True,
        help="Path to trade logs file (JSONL format)"
    )
    parser.add_argument(
        "--orders",
        required=True,
        help="Path to order logs file (JSONL format)"
    )
    parser.add_argument(
        "--output",
        help="Output analytics report to file"
    )
    
    args = parser.parse_args()
    
    # Load trades
    print(f"Loading trade logs from {args.trades}...")
    trades = load_trade_logs(args.trades)
    print(f"Loaded {len(trades)} trade log entries")
    
    # Load orders
    print(f"Loading order logs from {args.orders}...")
    orders = load_order_logs(args.orders)
    print(f"Loaded {len(orders)} order log entries")
    
    # Analyze
    print("\nAnalyzing edge gating vs outcomes...")
    analytics = analyze_edge_vs_outcomes(trades, orders)
    
    # Display results
    print(f"\n{'='*70}")
    print(f"EDGE GATING VS OUTCOMES CALIBRATION")
    print(f"{'='*70}")
    print(f"Total trades analyzed: {analytics['total_trades_analyzed']}")
    
    print(f"\nBy Edge Bucket:")
    print("-" * 70)
    for label in ["0-2%", "2-4%", "4-6%", "6-8%", "8-10%", "10%+"]:
        stats = analytics['bucket_stats'][label]
        if stats['total'] > 0:
            print(f"\n  {label}:")
            print(f"    Total trades: {stats['total']}")
            print(f"    Wins: {stats['wins']}")
            print(f"    Win rate: {stats['win_rate']:.1%}")
            print(f"    Avg P&L per trade: ${stats['avg_pnl_per_trade'] / 100:.2f}")
            print(f"    Avg P&L per contract: ${stats['avg_pnl_per_contract'] / 100:.2f}")
    
    # Write output if requested
    if args.output:
        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "trades_path": args.trades,
            "orders_path": args.orders,
            "analytics": analytics,
        }
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"\nReport written to {args.output}")


if __name__ == "__main__":
    main()
