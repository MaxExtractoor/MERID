#!/usr/bin/env python3
"""Kill-switch / risk interaction analysis.

This script analyzes trades that were killed by risk or kill-switch conditions
to determine what would have happened using actual market results.

Usage::

    python scripts/analytics_kill_switch_risk.py --trades data/trades.jsonl --killed data/killed_trades.jsonl
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


def load_killed_logs(killed_path: str) -> List[Dict[str, Any]]:
    """Load killed trade logs from JSONL file.
    
    Args:
        killed_path: Path to killed trade logs file (JSONL format)
        
    Returns:
        List of killed trade log entries
    """
    killed = []
    with open(killed_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    killed.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"Warning: Failed to parse log line: {e}", file=sys.stderr)
    return killed


def analyze_kill_switch_risk(
    trades: List[Dict[str, Any]],
    killed: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Analyze kill-switch/risk interaction.
    
    Args:
        trades: Completed trade log entries
        killed: Killed trade log entries
        
    Returns:
        Dict with kill-switch analytics
    """
    # Build lookup of market results by ticker
    market_results = {}
    for trade in trades:
        ticker = trade.get('ticker')
        market_result = trade.get('market_result')
        if ticker and market_result:
            market_results[ticker] = market_result
    
    # Analyze killed trades
    kill_stats = {
        'total_killed': len(killed),
        'by_reason': defaultdict(int),
        'by_asset': defaultdict(int),
        'would_have_won': 0,
        'would_have_lost': 0,
        'would_have_breakeven': 0,
        'unknown_outcome': 0,
    }
    
    for killed_trade in killed:
        reason = killed_trade.get('reason', 'UNKNOWN')
        ticker = killed_trade.get('ticker')
        
        # Track by reason
        kill_stats['by_reason'][reason] += 1
        
        # Track by asset
        if ticker:
            if 'BTC' in ticker.upper():
                kill_stats['by_asset']['BTC'] += 1
            elif 'ETH' in ticker.upper():
                kill_stats['by_asset']['ETH'] += 1
            elif 'SOL' in ticker.upper():
                kill_stats['by_asset']['SOL'] += 1
            elif 'XRP' in ticker.upper():
                kill_stats['by_asset']['XRP'] += 1
            elif 'DOGE' in ticker.upper():
                kill_stats['by_asset']['DOGE'] += 1
        
        # Determine what would have happened
        if ticker and ticker in market_results:
            market_result = market_results[ticker]
            position_side = killed_trade.get('position_side')
            
            if position_side:
                # Determine if this would have been a win
                if market_result == 'yes' and position_side == 'yes':
                    kill_stats['would_have_won'] += 1
                elif market_result == 'no' and position_side == 'no':
                    kill_stats['would_have_won'] += 1
                else:
                    kill_stats['would_have_lost'] += 1
            else:
                kill_stats['unknown_outcome'] += 1
        else:
            kill_stats['unknown_outcome'] += 1
    
    # Calculate percentages
    total_analyzed = kill_stats['would_have_won'] + kill_stats['would_have_lost']
    if total_analyzed > 0:
        kill_stats['would_have_won_pct'] = kill_stats['would_have_won'] / total_analyzed
        kill_stats['would_have_lost_pct'] = kill_stats['would_have_lost'] / total_analyzed
    else:
        kill_stats['would_have_won_pct'] = 0
        kill_stats['would_have_lost_pct'] = 0
    
    return {
        'kill_stats': dict(kill_stats),
        'completed_trades': len(trades),
    }


def main():
    parser = argparse.ArgumentParser(description="Kill-switch/risk interaction analysis")
    parser.add_argument(
        "--trades",
        required=True,
        help="Path to completed trade logs file (JSONL format)"
    )
    parser.add_argument(
        "--killed",
        required=True,
        help="Path to killed trade logs file (JSONL format)"
    )
    parser.add_argument(
        "--output",
        help="Output analytics report to file"
    )
    
    args = parser.parse_args()
    
    # Load trades
    print(f"Loading completed trades from {args.trades}...")
    trades = load_trade_logs(args.trades)
    print(f"Loaded {len(trades)} completed trade log entries")
    
    # Load killed trades
    print(f"Loading killed trades from {args.killed}...")
    killed = load_killed_logs(args.killed)
    print(f"Loaded {len(killed)} killed trade log entries")
    
    # Analyze
    print("\nAnalyzing kill-switch/risk interaction...")
    analytics = analyze_kill_switch_risk(trades, killed)
    
    # Display results
    print(f"\n{'='*70}")
    print(f"KILL-SWITCH / RISK INTERACTION ANALYTICS")
    print(f"{'='*70}")
    print(f"Total killed trades: {analytics['kill_stats']['total_killed']}")
    print(f"Total completed trades: {analytics['completed_trades']}")
    
    print(f"\nKilled by Reason:")
    print("-" * 70)
    for reason, count in sorted(analytics['kill_stats']['by_reason'].items(), key=lambda x: -x[1]):
        print(f"  {reason:40s}: {count}")
    
    print(f"\nKilled by Asset:")
    print("-" * 70)
    for asset, count in sorted(analytics['kill_stats']['by_asset'].items(), key=lambda x: -x[1]):
        print(f"  {asset:10s}: {count}")
    
    print(f"\nWhat Would Have Happened:")
    print("-" * 70)
    print(f"  Would have won: {analytics['kill_stats']['would_have_won']} ({analytics['kill_stats']['would_have_won_pct']:.1%})")
    print(f"  Would have lost: {analytics['kill_stats']['would_have_lost']} ({analytics['kill_stats']['would_have_lost_pct']:.1%})")
    print(f"  Unknown outcome: {analytics['kill_stats']['unknown_outcome']}")
    
    # Write output if requested
    if args.output:
        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "trades_path": args.trades,
            "killed_path": args.killed,
            "analytics": analytics,
        }
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"\nReport written to {args.output}")


if __name__ == "__main__":
    main()
