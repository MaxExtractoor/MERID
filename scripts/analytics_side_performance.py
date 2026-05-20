#!/usr/bin/env python3
"""Side-specific performance analysis by regime.

This script compares YES-leaning vs NO-leaning strategies by asset
and time-of-day regime to detect structural microstructure effects.

Usage::

    python scripts/analytics_side_performance.py --trades data/trades.jsonl --orders data/order_logs.jsonl
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


def get_time_regime(timestamp: str) -> str:
    """Determine time-of-day regime from timestamp.
    
    Args:
        timestamp: ISO8601 timestamp
        
    Returns:
        Time regime: "US_OVERLAP", "ASIAN_SESSION", "EUROPEAN_SESSION", or "UNKNOWN"
    """
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        hour = dt.hour
        
        # Simplified time zones (UTC-based)
        # US market hours: 13:00-20:00 UTC (9am-4pm ET)
        if 13 <= hour < 20:
            return "US_OVERLAP"
        # European session: 7:00-13:00 UTC
        elif 7 <= hour < 13:
            return "EUROPEAN_SESSION"
        # Asian session: 20:00-7:00 UTC
        elif hour >= 20 or hour < 7:
            return "ASIAN_SESSION"
        else:
            return "UNKNOWN"
    except:
        return "UNKNOWN"


def infer_strategy_leaning(rationale: str, side: str) -> str:
    """Infer strategy leaning from rationale and side.
    
    Args:
        rationale: Strategy rationale text
        side: Order side (yes/no)
        
    Returns:
        "YES_LEANING", "NO_LEANING", or "NEUTRAL"
    """
    rationale_lower = rationale.lower()
    
    # Check for directional intent
    if any(word in rationale_lower for word in ['up', 'higher', 'bullish', 'momentum', 'breakout']):
        if side == 'yes':
            return "YES_LEANING"
        elif side == 'no':
            return "NO_LEANING"
    
    if any(word in rationale_lower for word in ['down', 'lower', 'bearish', 'fade', 'short']):
        if side == 'no':
            return "NO_LEANING"
        elif side == 'yes':
            return "YES_LEANING"
    
    # Default to side-based classification
    if side == 'yes':
        return "YES_LEANING"
    elif side == 'no':
        return "NO_LEANING"
    
    return "NEUTRAL"


def analyze_side_performance(
    trades: List[Dict[str, Any]],
    orders: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Analyze side-specific performance by regime.
    
    Args:
        trades: Trade log entries
        orders: Order log entries
        
    Returns:
        Dict with side-specific performance analytics
    """
    # Build order lookup
    order_by_intent = {}
    for order in orders:
        intent_id = order.get('intent_id')
        if intent_id:
            order_by_intent[intent_id] = order
    
    # Group by asset, time regime, and strategy leaning
    stats = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {
        'total': 0,
        'wins': 0,
        'total_pnl_cents': 0,
        'total_contracts': 0,
    })))
    
    for trade in trades:
        intent_id = trade.get('intent_id') or trade.get('trade_id')
        market_result = trade.get('market_result')
        position_side = trade.get('position_side_at_close')
        pnl_cents = trade.get('realized_pnl_cents', 0)
        filled_size = trade.get('filled_size', 0)
        ticker = trade.get('ticker')
        settlement_timestamp = trade.get('settlement_timestamp')
        
        if not intent_id or intent_id not in order_by_intent:
            continue
        
        order = order_by_intent[intent_id]
        rationale = order.get('rationale', '')
        order_side = order.get('side')
        
        asset = extract_asset_from_ticker(ticker)
        time_regime = get_time_regime(settlement_timestamp) if settlement_timestamp else "UNKNOWN"
        strategy_leaning = infer_strategy_leaning(rationale, order_side)
        
        # Update stats
        stats[asset][time_regime][strategy_leaning]['total'] += 1
        stats[asset][time_regime][strategy_leaning]['total_contracts'] += filled_size
        stats[asset][time_regime][strategy_leaning]['total_pnl_cents'] += pnl_cents
        
        # Determine if win
        if market_result and position_side:
            if market_result == 'yes' and position_side == 'yes':
                stats[asset][time_regime][strategy_leaning]['wins'] += 1
            elif market_result == 'no' and position_side == 'no':
                stats[asset][time_regime][strategy_leaning]['wins'] += 1
    
    # Calculate metrics
    for asset in stats:
        for time_regime in stats[asset]:
            for leaning in stats[asset][time_regime]:
                s = stats[asset][time_regime][leaning]
                if s['total'] > 0:
                    s['win_rate'] = s['wins'] / s['total']
                    s['avg_pnl_per_trade'] = s['total_pnl_cents'] / s['total']
                    s['avg_pnl_per_contract'] = s['total_pnl_cents'] / s['total_contracts'] if s['total_contracts'] > 0 else 0
                else:
                    s['win_rate'] = 0
                    s['avg_pnl_per_trade'] = 0
                    s['avg_pnl_per_contract'] = 0
    
    return {
        'stats': dict(stats),
        'total_trades_analyzed': len(trades),
    }


def main():
    parser = argparse.ArgumentParser(description="Side-specific performance analysis")
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
    print("\nAnalyzing side-specific performance...")
    analytics = analyze_side_performance(trades, orders)
    
    # Display results
    print(f"\n{'='*70}")
    print(f"SIDE-SPECIFIC PERFORMANCE ANALYSIS")
    print(f"{'='*70}")
    print(f"Total trades analyzed: {analytics['total_trades_analyzed']}")
    
    print(f"\nBy Asset, Time Regime, and Strategy Leaning:")
    print("-" * 70)
    for asset in sorted(analytics['stats'].keys()):
        print(f"\n  {asset}:")
        for time_regime in sorted(analytics['stats'][asset].keys()):
            print(f"    {time_regime}:")
            for leaning in ['YES_LEANING', 'NO_LEANING']:
                s = analytics['stats'][asset][time_regime][leaning]
                if s['total'] > 0:
                    print(f"      {leaning}:")
                    print(f"        Total trades: {s['total']}")
                    print(f"        Win rate: {s['win_rate']:.1%}")
                    print(f"        Avg P&L per trade: ${s['avg_pnl_per_trade'] / 100:.2f}")
    
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
