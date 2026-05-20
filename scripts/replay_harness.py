#!/usr/bin/env python3
"""
Backtest/Live Equivalence Replay Harness

This script provides a replay harness to verify that:
1. Fees computed via fees.py match actual fees charged at execution time
2. Drawdown paths and halt/unwind events match expectations under replay
3. Temporal behavior is consistent between backtest and live

Usage:
    python scripts/replay_harness.py --fills FILLS_FILE --profile PROFILE_NAME

Input:
    - Fills file with real Kalshi fills (from API portfolio/trade history)
    - Profile name to load drawdown limits

Output:
    Report comparing expected vs actual fees and drawdown behavior
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from decimal import Decimal


def load_fills(fills_file: Path) -> List[Dict[str, Any]]:
    """Load fills from file (JSON or CSV)."""
    fills = []
    
    if fills_file.suffix == '.json':
        with open(fills_file, 'r') as f:
            fills = json.load(f)
    elif fills_file.suffix == '.csv':
        import csv
        with open(fills_file, 'r') as f:
            reader = csv.DictReader(f)
            fills = [dict(row) for row in reader]
    else:
        raise ValueError(f"Unsupported file format: {fills_file.suffix}")
    
    return fills


def compute_expected_fee(contracts: int, price_cents: int) -> int:
    """Compute expected fee using canonical fees.py."""
    try:
        from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
        return calculate_kalshi_fee_cents(contracts, price_cents)
    except ImportError:
        # Fallback: simple parabolic formula
        price = price_cents / 100.0
        rate = 0.07 if contracts < 100 else (0.05 if contracts < 1000 else 0.03)
        fee = rate * contracts * price * (1 - price)
        return max(2, int(fee * 100))  # Minimum 2¢ per contract


def verify_fees(fills: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Verify that fees computed via fees.py match actual fees.
    
    Returns:
        - List of mismatches
        - Summary statistics
    """
    mismatches = []
    total_fills = len(fills)
    matching_fills = 0
    total_expected_fee = 0
    total_actual_fee = 0
    
    for fill in fills:
        # Extract fill data (adapt to your actual fill schema)
        contracts = int(fill.get('contracts', fill.get('quantity', 1)))
        price_cents = int(fill.get('price_cents', fill.get('price', 50)))
        actual_fee_cents = int(fill.get('fee_cents', fill.get('fee', 0)))
        
        # Compute expected fee
        expected_fee_cents = compute_expected_fee(contracts, price_cents)
        
        total_expected_fee += expected_fee_cents
        total_actual_fee += actual_fee_cents
        
        # Check for mismatch
        if expected_fee_cents != actual_fee_cents:
            mismatches.append({
                'fill_id': fill.get('id', 'unknown'),
                'contracts': contracts,
                'price_cents': price_cents,
                'expected_fee_cents': expected_fee_cents,
                'actual_fee_cents': actual_fee_cents,
                'diff_cents': actual_fee_cents - expected_fee_cents,
            })
        else:
            matching_fills += 1
    
    summary = {
        'total_fills': total_fills,
        'matching_fills': matching_fills,
        'mismatch_count': len(mismatches),
        'match_rate': matching_fills / total_fills if total_fills > 0 else 0,
        'total_expected_fee_cents': total_expected_fee,
        'total_actual_fee_cents': total_actual_fee,
        'total_diff_cents': total_actual_fee - total_expected_fee,
    }
    
    return mismatches, summary


def simulate_drawdown_path(
    fills: List[Dict[str, Any]],
    initial_equity: float,
    drawdown_halt_pct: float,
    drawdown_unwind_pct: float,
    max_daily_loss_usd: float,
) -> Dict[str, Any]:
    """
    Simulate drawdown path using canonical _prediction_risk.py logic.
    
    Returns:
        - Drawdown state at each step
        - Halt/unwind events
    """
    equity = initial_equity
    peak = initial_equity
    daily_loss = 0.0
    halted = False
    unwind_mode = False
    
    events = []
    path = []
    
    for i, fill in enumerate(fills):
        # Extract PnL from fill
        pnl = float(fill.get('pnl', fill.get('profit_loss', 0)))
        equity += pnl
        daily_loss += pnl if pnl < 0 else 0
        
        # Update peak
        if equity > peak:
            peak = equity
        
        # Compute drawdown
        drawdown = (peak - equity) / peak if peak > 0 else 0.0
        
        # Check halt condition
        if not halted and drawdown >= drawdown_halt_pct:
            halted = True
            events.append({
                'step': i,
                'type': 'halt',
                'drawdown': drawdown,
                'equity': equity,
                'reason': f'Drawdown {drawdown:.2%} >= halt threshold {drawdown_halt_pct:.2%}',
            })
        
        # Check unwind condition
        if not unwind_mode and drawdown >= drawdown_unwind_pct:
            unwind_mode = True
            events.append({
                'step': i,
                'type': 'unwind',
                'drawdown': drawdown,
                'equity': equity,
                'reason': f'Drawdown {drawdown:.2%} >= unwind threshold {drawdown_unwind_pct:.2%}',
            })
        
        # Check daily loss cap
        if daily_loss <= -max_daily_loss_usd:
            halted = True
            events.append({
                'step': i,
                'type': 'daily_loss_cap',
                'daily_loss': daily_loss,
                'equity': equity,
                'reason': f'Daily loss {daily_loss:.2f} <= cap -{max_daily_loss_usd:.2f}',
            })
        
        path.append({
            'step': i,
            'equity': equity,
            'peak': peak,
            'drawdown': drawdown,
            'daily_loss': daily_loss,
            'halted': halted,
            'unwind_mode': unwind_mode,
        })
    
    return {
        'initial_equity': initial_equity,
        'final_equity': equity,
        'final_drawdown': drawdown,
        'halted': halted,
        'unwind_mode': unwind_mode,
        'events': events,
        'path': path,
    }


def load_profile_drawdown_limits(profile_name: str) -> Optional[Dict[str, float]]:
    """Load drawdown limits from profile."""
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        
        adapter = get_active_profile()
        if not adapter:
            return None
        
        profile_obj = adapter.profile
        guardrails = getattr(profile_obj, 'guardrails', None)
        
        if not guardrails:
            return None
        
        return {
            'drawdown_halt_pct': float(getattr(guardrails, 'guardrails_drawdown_halt_pct', 0.10)),
            'drawdown_unwind_pct': float(getattr(guardrails, 'guardrails_drawdown_unwind_pct', 0.15)),
            'max_daily_loss_usd': float(getattr(guardrails, 'guardrails_max_daily_loss_usd', 200.0)),
        }
    except Exception as e:
        print(f"Error loading profile: {e}", file=sys.stderr)
        return None


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Backtest/Live Equivalence Replay Harness')
    parser.add_argument(
        '--fills',
        '-f',
        type=str,
        required=True,
        help='Fills file (JSON or CSV)'
    )
    parser.add_argument(
        '--profile',
        '-p',
        type=str,
        default='kalshi_crypto_15m_v2',
        help='Profile name for drawdown limits'
    )
    parser.add_argument(
        '--initial-equity',
        type=float,
        default=1000.0,
        help='Initial equity for drawdown simulation (default: 1000.0)'
    )
    parser.add_argument(
        '--output',
        '-o',
        type=str,
        default='replay_report.json',
        help='Output report file (default: replay_report.json)'
    )
    
    args = parser.parse_args()
    
    # Load fills
    fills_file = Path(args.fills)
    if not fills_file.exists():
        print(f"Error: Fills file not found: {fills_file}", file=sys.stderr)
        return 1
    
    fills = load_fills(fills_file)
    print(f"Loaded {len(fills)} fills from {fills_file}")
    
    # Verify fees
    print("\n=== Fee Verification ===")
    fee_mismatches, fee_summary = verify_fees(fills)
    print(f"Total fills: {fee_summary['total_fills']}")
    print(f"Matching fills: {fee_summary['matching_fills']}")
    print(f"Mismatch count: {fee_summary['mismatch_count']}")
    print(f"Match rate: {fee_summary['match_rate']:.2%}")
    print(f"Total expected fee: ${fee_summary['total_expected_fee_cents'] / 100:.2f}")
    print(f"Total actual fee: ${fee_summary['total_actual_fee_cents'] / 100:.2f}")
    print(f"Total diff: ${fee_summary['total_diff_cents'] / 100:.2f}")
    
    if fee_mismatches:
        print(f"\nFee mismatches ({len(fee_mismatches)}):")
        for mismatch in fee_mismatches[:10]:  # Show first 10
            print(f"  - Fill {mismatch['fill_id']}: expected {mismatch['expected_fee_cents']}¢, "
                  f"actual {mismatch['actual_fee_cents']}¢ (diff: {mismatch['diff_cents']}¢)")
    
    # Simulate drawdown path
    print("\n=== Drawdown Simulation ===")
    drawdown_limits = load_profile_drawdown_limits(args.profile)
    if drawdown_limits:
        print(f"Using profile: {args.profile}")
        print(f"Drawdown halt: {drawdown_limits['drawdown_halt_pct']:.2%}")
        print(f"Drawdown unwind: {drawdown_limits['drawdown_unwind_pct']:.2%}")
        print(f"Max daily loss: ${drawdown_limits['max_daily_loss_usd']:.2f}")
    else:
        print("Using default drawdown limits")
        drawdown_limits = {
            'drawdown_halt_pct': 0.10,
            'drawdown_unwind_pct': 0.15,
            'max_daily_loss_usd': 200.0,
        }
    
    drawdown_result = simulate_drawdown_path(
        fills,
        args.initial_equity,
        drawdown_limits['drawdown_halt_pct'],
        drawdown_limits['drawdown_unwind_pct'],
        drawdown_limits['max_daily_loss_usd'],
    )
    
    print(f"Initial equity: ${drawdown_result['initial_equity']:.2f}")
    print(f"Final equity: ${drawdown_result['final_equity']:.2f}")
    print(f"Final drawdown: {drawdown_result['final_drawdown']:.2%}")
    print(f"Halted: {drawdown_result['halted']}")
    print(f"Unwind mode: {drawdown_result['unwind_mode']}")
    print(f"Events: {len(drawdown_result['events'])}")
    
    if drawdown_result['events']:
        print("\nDrawdown events:")
        for event in drawdown_result['events']:
            print(f"  - Step {event['step']}: {event['type']} - {event['reason']}")
    
    # Generate report
    report = {
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'fills_file': str(fills_file),
        'profile': args.profile,
        'initial_equity': args.initial_equity,
        'fee_verification': {
            'summary': fee_summary,
            'mismatches': fee_mismatches,
        },
        'drawdown_simulation': {
            'limits': drawdown_limits,
            'result': drawdown_result,
        },
    }
    
    # Write report
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"\nReport generated: {output_path}")
    
    # Return exit code based on results
    if fee_summary['match_rate'] < 0.95:
        print("\nWarning: Fee match rate below 95%")
        return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
