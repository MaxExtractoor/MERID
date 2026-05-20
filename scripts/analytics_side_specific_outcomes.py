#!/usr/bin/env python3
"""Side-specific outcomes dashboard - win rate and P&L by asset and side.

This script analyzes settlement logs to produce side-specific performance:
- Win rate for economically long YES vs long NO positions
- Average P&L by asset (BTC/ETH/SOL/XRP/DOGE)
- Side-specific win rate breakdown by asset

Usage::

    python scripts/analytics_side_specific_outcomes.py --trades data/trades.jsonl
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


def analyze_side_specific_outcomes(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze side-specific outcomes.
    
    Args:
        trades: Trade log entries
        
    Returns:
        Dict with side-specific analytics
    """
    # Group by asset and side
    asset_side_stats = defaultdict(lambda: defaultdict(lambda: {
        'total': 0,
        'wins': 0,
        'total_pnl_cents': 0,
        'total_contracts': 0,
    }))
    
    overall_stats = {
        'long_yes': {'total': 0, 'wins': 0, 'total_pnl_cents': 0, 'total_contracts': 0},
        'long_no': {'total': 0, 'wins': 0, 'total_pnl_cents': 0, 'total_contracts': 0},
    }
    
    for trade in trades:
        ticker = trade.get('ticker')
        position_side = trade.get('position_side_at_close')
        market_result = trade.get('market_result')
        pnl_cents = trade.get('realized_pnl_cents', 0)
        filled_size = trade.get('filled_size', 0)
        
        if not ticker or not position_side or not market_result:
            continue
        
        asset = extract_asset_from_ticker(ticker)
        
        # Determine if this is a win
        is_win = False
        if market_result == 'yes' and position_side == 'yes':
            is_win = True
        elif market_result == 'no' and position_side == 'no':
            is_win = True
        
        # Update asset-side stats
        asset_side_stats[asset][position_side]['total'] += 1
        asset_side_stats[asset][position_side]['total_contracts'] += filled_size
        asset_side_stats[asset][position_side]['total_pnl_cents'] += pnl_cents
        if is_win:
            asset_side_stats[asset][position_side]['wins'] += 1
        
        # Update overall stats
        if position_side == 'yes':
            overall_stats['long_yes']['total'] += 1
            overall_stats['long_yes']['total_contracts'] += filled_size
            overall_stats['long_yes']['total_pnl_cents'] += pnl_cents
            if is_win:
                overall_stats['long_yes']['wins'] += 1
        elif position_side == 'no':
            overall_stats['long_no']['total'] += 1
            overall_stats['long_no']['total_contracts'] += filled_size
            overall_stats['long_no']['total_pnl_cents'] += pnl_cents
            if is_win:
                overall_stats['long_no']['wins'] += 1
    
    # Calculate win rates and average P&L
    for asset in asset_side_stats:
        for side in asset_side_stats[asset]:
            stats = asset_side_stats[asset][side]
            if stats['total'] > 0:
                stats['win_rate'] = stats['wins'] / stats['total']
                stats['avg_pnl_per_trade'] = stats['total_pnl_cents'] / stats['total']
                stats['avg_pnl_per_contract'] = stats['total_pnl_cents'] / stats['total_contracts'] if stats['total_contracts'] > 0 else 0
            else:
                stats['win_rate'] = 0
                stats['avg_pnl_per_trade'] = 0
                stats['avg_pnl_per_contract'] = 0
    
    for side in overall_stats:
        stats = overall_stats[side]
        if stats['total'] > 0:
            stats['win_rate'] = stats['wins'] / stats['total']
            stats['avg_pnl_per_trade'] = stats['total_pnl_cents'] / stats['total']
            stats['avg_pnl_per_contract'] = stats['total_pnl_cents'] / stats['total_contracts'] if stats['total_contracts'] > 0 else 0
        else:
            stats['win_rate'] = 0
            stats['avg_pnl_per_trade'] = 0
            stats['avg_pnl_per_contract'] = 0
    
    return {
        'by_asset': dict(asset_side_stats),
        'overall': overall_stats,
        'total_trades': len(trades),
    }


def main():
    parser = argparse.ArgumentParser(description="Side-specific outcomes dashboard")
    parser.add_argument(
        "--trades",
        required=True,
        help="Path to trade logs file (JSONL format)"
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
    
    # Analyze
    print("\nAnalyzing side-specific outcomes...")
    analytics = analyze_side_specific_outcomes(trades)
    
    # Display results
    print(f"\n{'='*70}")
    print(f"SIDE-SPECIFIC OUTCOMES ANALYTICS")
    print(f"{'='*70}")
    print(f"Total trades: {analytics['total_trades']}")
    
    print(f"\nOverall Performance:")
    print("-" * 70)
    for side in ['long_yes', 'long_no']:
        stats = analytics['overall'][side]
        print(f"\n  {side.upper()}:")
        print(f"    Total trades: {stats['total']}")
        print(f"    Wins: {stats['wins']}")
        print(f"    Win rate: {stats['win_rate']:.1%}")
        print(f"    Total P&L: ${stats['total_pnl_cents'] / 100:.2f}")
        print(f"    Avg P&L per trade: ${stats['avg_pnl_per_trade'] / 100:.2f}")
        print(f"    Avg P&L per contract: ${stats['avg_pnl_per_contract'] / 100:.2f}")
    
    print(f"\nBy Asset:")
    print("-" * 70)
    for asset in sorted(analytics['by_asset'].keys()):
        print(f"\n  {asset}:")
        for side in ['yes', 'no']:
            stats = analytics['by_asset'][asset][side]
            if stats['total'] > 0:
                print(f"    {side.upper()}:")
                print(f"      Total trades: {stats['total']}")
                print(f"      Win rate: {stats['win_rate']:.1%}")
                print(f"      Avg P&L per trade: ${stats['avg_pnl_per_trade'] / 100:.2f}")
    
    # Write output if requested
    if args.output:
        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "trades_path": args.trades,
            "analytics": analytics,
        }
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"\nReport written to {args.output}")


if __name__ == "__main__":
    main()
