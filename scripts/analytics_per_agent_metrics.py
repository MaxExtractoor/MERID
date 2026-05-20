#!/usr/bin/env python3
"""Per-agent metrics analysis.

This script computes per-agent and per-asset metrics:
- Win rate, average P&L per trade
- Sharpe-like ratio (simplified)
- Utilization of available entry windows

Usage::

    python scripts/analytics_per_agent_metrics.py --trades data/trades.jsonl --orders data/order_logs.jsonl
"""

import argparse
import json
import sys
import math
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


def extract_asset_from_ticker(ticker: str) -> str:
    """Extract asset from ticker.
    
    Args:
        ticker: Kalshi market ticker
        
    Returns:
        Asset symbol (BTC, ETH, SOL, XRP, DOGE, or UNKNOWN)
    """
    ticker_upper = ticker.upper()
    if 'BTC' in ticker_upper:
        return 'BTC'
    elif 'ETH' in ticker_upper:
        return 'ETH'
    elif 'SOL' in ticker_upper:
        return 'SOL'
    elif 'XRP' in ticker_upper:
        return 'XRP'
    elif 'DOGE' in ticker_upper:
        return 'DOGE'
    else:
        return 'UNKNOWN'


def analyze_per_agent_metrics(
    trades: List[Dict[str, Any]],
    orders: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Analyze per-agent metrics.
    
    Args:
        trades: Trade log entries
        orders: Order log entries
        
    Returns:
        Dict with per-agent analytics
    """
    # Build agent lookup by intent_id
    agent_by_intent = {}
    for order in orders:
        intent_id = order.get('intent_id')
        agent_id = order.get('agent_id')
        ticker = order.get('ticker')
        if intent_id and agent_id:
            agent_by_intent[intent_id] = {
                'agent_id': agent_id,
                'ticker': ticker,
            }
    
    # Group by agent and asset
    agent_asset_stats = defaultdict(lambda: defaultdict(lambda: {
        'total': 0,
        'wins': 0,
        'total_pnl_cents': 0,
        'total_contracts': 0,
        'pnl_values': [],
    }))
    
    # Track entry window utilization (simplified)
    agent_window_stats = defaultdict(lambda: {
        'signals_generated': 0,
        'orders_placed': 0,
    })
    
    for order in orders:
        agent_id = order.get('agent_id')
        if agent_id:
            agent_window_stats[agent_id]['signals_generated'] += 1
            if order.get('mode') in ['live', 'paper']:
                agent_window_stats[agent_id]['orders_placed'] += 1
    
    # Analyze trades
    for trade in trades:
        intent_id = trade.get('intent_id') or trade.get('trade_id')
        market_result = trade.get('market_result')
        position_side = trade.get('position_side_at_close')
        pnl_cents = trade.get('realized_pnl_cents', 0)
        filled_size = trade.get('filled_size', 0)
        ticker = trade.get('ticker')
        
        if not intent_id or intent_id not in agent_by_intent:
            continue
        
        agent_info = agent_by_intent[intent_id]
        agent_id = agent_info['agent_id']
        asset = extract_asset_from_ticker(ticker)
        
        # Update stats
        agent_asset_stats[agent_id][asset]['total'] += 1
        agent_asset_stats[agent_id][asset]['total_contracts'] += filled_size
        agent_asset_stats[agent_id][asset]['total_pnl_cents'] += pnl_cents
        agent_asset_stats[agent_id][asset]['pnl_values'].append(pnl_cents)
        
        # Determine if win
        if market_result and position_side:
            if market_result == 'yes' and position_side == 'yes':
                agent_asset_stats[agent_id][asset]['wins'] += 1
            elif market_result == 'no' and position_side == 'no':
                agent_asset_stats[agent_id][asset]['wins'] += 1
    
    # Calculate metrics per agent/asset
    for agent_id in agent_asset_stats:
        for asset in agent_asset_stats[agent_id]:
            stats = agent_asset_stats[agent_id][asset]
            
            if stats['total'] > 0:
                stats['win_rate'] = stats['wins'] / stats['total']
                stats['avg_pnl_per_trade'] = stats['total_pnl_cents'] / stats['total']
                stats['avg_pnl_per_contract'] = stats['total_pnl_cents'] / stats['total_contracts'] if stats['total_contracts'] > 0 else 0
                
                # Simplified Sharpe ratio (std dev of returns)
                if len(stats['pnl_values']) > 1:
                    mean_pnl = sum(stats['pnl_values']) / len(stats['pnl_values'])
                    variance = sum((x - mean_pnl) ** 2 for x in stats['pnl_values']) / (len(stats['pnl_values']) - 1)
                    std_dev = math.sqrt(variance)
                    if std_dev > 0:
                        stats['sharpe_ratio'] = mean_pnl / std_dev
                    else:
                        stats['sharpe_ratio'] = 0
                else:
                    stats['sharpe_ratio'] = 0
            else:
                stats['win_rate'] = 0
                stats['avg_pnl_per_trade'] = 0
                stats['avg_pnl_per_contract'] = 0
                stats['sharpe_ratio'] = 0
    
    # Calculate window utilization
    for agent_id in agent_window_stats:
        stats = agent_window_stats[agent_id]
        if stats['signals_generated'] > 0:
            stats['utilization'] = stats['orders_placed'] / stats['signals_generated']
        else:
            stats['utilization'] = 0
    
    return {
        'by_agent_asset': dict(agent_asset_stats),
        'window_utilization': dict(agent_window_stats),
        'total_trades_analyzed': len(trades),
    }


def main():
    parser = argparse.ArgumentParser(description="Per-agent metrics analysis")
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
    print("\nAnalyzing per-agent metrics...")
    analytics = analyze_per_agent_metrics(trades, orders)
    
    # Display results
    print(f"\n{'='*70}")
    print(f"PER-AGENT METRICS ANALYSIS")
    print(f"{'='*70}")
    print(f"Total trades analyzed: {analytics['total_trades_analyzed']}")
    
    print(f"\nEntry Window Utilization:")
    print("-" * 70)
    for agent_id, stats in sorted(analytics['window_utilization'].items()):
        print(f"  {agent_id:30s}: {stats['utilization']:.1%} ({stats['orders_placed']}/{stats['signals_generated']})")
    
    print(f"\nBy Agent and Asset:")
    print("-" * 70)
    for agent_id in sorted(analytics['by_agent_asset'].keys()):
        print(f"\n  {agent_id}:")
        for asset in sorted(analytics['by_agent_asset'][agent_id].keys()):
            stats = analytics['by_agent_asset'][agent_id][asset]
            if stats['total'] > 0:
                print(f"    {asset}:")
                print(f"      Total trades: {stats['total']}")
                print(f"      Win rate: {stats['win_rate']:.1%}")
                print(f"      Avg P&L per trade: ${stats['avg_pnl_per_trade'] / 100:.2f}")
                print(f"      Sharpe ratio: {stats['sharpe_ratio']:.2f}")
    
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
