#!/usr/bin/env python3
"""Validate settlement vs P&L truth alignment.

This script verifies that official Kalshi settlement outcomes align with
internal Outcome enum and realized P&L direction.

Usage::

    python scripts/validate_settlement_truth.py --trades data/trades.jsonl

Expected trade format (from fills_poller + settlement logs):
{
    "trade_id": "...",
    "ticker": "KXBTC15M-26MAY120000-00",
    "position_side_at_close": "yes",
    "filled_size": 10,
    "average_price_cents": 55,
    "fees_cents": 5,
    "market_result": "yes",  # Official Kalshi API result
    "internal_outcome": "YES_WON",  # Internal Outcome enum
    "realized_pnl_cents": 450,  # Positive = profit
    "settlement_timestamp": "2026-05-12T04:00:00Z"
}
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


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


def check_settlement_invariants(trade: Dict[str, Any]) -> Dict[str, Any]:
    """Check settlement invariants for a single trade.
    
    Args:
        trade: Trade log entry
        
    Returns:
        Dict with check results
    """
    results = {
        'trade_id': trade.get('trade_id'),
        'ticker': trade.get('ticker'),
        'checks': [],
        'errors': [],
        'warnings': [],
    }
    
    trade_id = trade.get('trade_id')
    ticker = trade.get('ticker')
    position_side = trade.get('position_side_at_close')
    filled_size = trade.get('filled_size')
    avg_price = trade.get('average_price_cents')
    fees = trade.get('fees_cents')
    market_result = trade.get('market_result')  # Official Kalshi result
    internal_outcome = trade.get('internal_outcome')  # Our Outcome enum
    pnl = trade.get('realized_pnl_cents')
    
    # Check 1: Required fields present
    required_fields = ['trade_id', 'ticker', 'position_side_at_close', 'market_result']
    for field in required_fields:
        if not trade.get(field):
            results['errors'].append(f"Missing required field: {field}")
    
    if results['errors']:
        return results
    
    # Check 2: market_result is present (with strict settlement mode)
    if not market_result:
        results['errors'].append("No market_result from Kalshi API (should fail with strict mode)")
        return results
    
    results['checks'].append(f"Official Kalshi result: {market_result}")
    
    # Check 3: internal_outcome is present
    if internal_outcome:
        results['checks'].append(f"Internal outcome: {internal_outcome}")
    else:
        results['warnings'].append("No internal_outcome classified")
    
    # Check 4: Economic exposure determination
    # Long YES (buy YES) or Short NO (sell NO) = economically long YES
    # Long NO (buy NO) or Short YES (sell YES) = economically long NO
    # For simplicity, we use position_side_at_close directly
    economic_side = position_side  # Could be "yes" or "no"
    results['checks'].append(f"Economic exposure: {economic_side}")
    
    # Check 5: Market result vs P&L direction
    if pnl is not None:
        results['checks'].append(f"Realized P&L: {pnl}c")
        
        if market_result == "yes":
            # YES won: long YES should have non-negative P&L
            if economic_side == "yes":
                if pnl >= -fees:  # Allow for fees
                    results['checks'].append("✓ YES won, long YES exposure, non-negative P&L")
                else:
                    results['errors'].append(f"YES won but long YES has negative P&L: {pnl}c")
            elif economic_side == "no":
                if pnl <= fees:  # Short NO should lose when YES wins
                    results['checks'].append("✓ YES won, long NO exposure, P&L ≤ fees (expected loss)")
                else:
                    results['errors'].append(f"YES won but long NO has unexpected profit: {pnl}c")
        
        elif market_result == "no":
            # NO won: long NO should have non-negative P&L
            if economic_side == "no":
                if pnl >= -fees:
                    results['checks'].append("✓ NO won, long NO exposure, non-negative P&L")
                else:
                    results['errors'].append(f"NO won but long NO has negative P&L: {pnl}c")
            elif economic_side == "yes":
                if pnl <= fees:
                    results['checks'].append("✓ NO won, long YES exposure, P&L ≤ fees (expected loss)")
                else:
                    results['errors'].append(f"NO won but long YES has unexpected profit: {pnl}c")
    
    # Check 6: Internal outcome vs market result
    if internal_outcome and market_result:
        if market_result == "yes" and internal_outcome == "YES_WON":
            results['checks'].append("✓ Market result 'yes' matches internal 'YES_WON'")
        elif market_result == "no" and internal_outcome == "NO_WON":
            results['checks'].append("✓ Market result 'no' matches internal 'NO_WON'")
        elif market_result == "yes" and internal_outcome == "NO_WON":
            results['errors'].append(f"Market result 'yes' but internal says 'NO_WON' (mismatch)")
        elif market_result == "no" and internal_outcome == "YES_WON":
            results['errors'].append(f"Market result 'no' but internal says 'YES_WON' (mismatch)")
        elif internal_outcome == "UNKNOWN":
            results['errors'].append(f"Market result '{market_result}' but internal is 'UNKNOWN' (should be classified)")
        else:
            results['warnings'].append(f"Unexpected combination: market_result={market_result}, internal_outcome={internal_outcome}")
    
    # Check 7: Non-zero P&L with UNKNOWN internal outcome
    if pnl and abs(pnl) > 0 and internal_outcome == "UNKNOWN":
        results['errors'].append(f"Non-zero P&L ({pnl}c) but internal outcome is UNKNOWN")
    
    # Check 8: Settlement failure due to missing API result (should not happen with strict mode)
    if trade.get('settlement_failed') and not market_result:
        results['errors'].append("Settlement failed with no API result (verify market was unsettled)")
    
    return results


def main():
    parser = argparse.ArgumentParser(description="Validate settlement vs P&L truth")
    parser.add_argument(
        "--trades",
        required=True,
        help="Path to trade logs file (JSONL format)"
    )
    parser.add_argument(
        "--output",
        help="Output validation report to file"
    )
    
    args = parser.parse_args()
    
    # Load trade logs
    print(f"Loading trade logs from {args.trades}...")
    trades = load_trade_logs(args.trades)
    print(f"Loaded {len(trades)} trade log entries")
    
    # Validate each trade
    print("\nValidating trades...")
    validation_results = []
    
    for trade in trades:
        result = check_settlement_invariants(trade)
        validation_results.append(result)
    
    # Summary statistics
    total = len(validation_results)
    errors = sum(1 for r in validation_results if r['errors'])
    warnings = sum(1 for r in validation_results if r['warnings'])
    clean = total - errors
    
    print(f"\n{'='*70}")
    print(f"VALIDATION SUMMARY")
    print(f"{'='*70}")
    print(f"Total trades: {total}")
    print(f"Clean: {clean}")
    print(f"Errors: {errors}")
    print(f"Warnings: {warnings}")
    print(f"{'='*70}")
    
    # Show errors first
    if errors > 0:
        print(f"\nERRORS ({errors}):")
        print("-" * 70)
        for result in validation_results:
            if result['errors']:
                print(f"\nTrade ID: {result['trade_id']}")
                print(f"Ticker: {result['ticker']}")
                for error in result['errors']:
                    print(f"  ✗ {error}")
    
    # Show warnings
    if warnings > 0:
        print(f"\nWARNINGS ({warnings}):")
        print("-" * 70)
        for result in validation_results:
            if result['warnings']:
                print(f"\nTrade ID: {result['trade_id']}")
                print(f"Ticker: {result['ticker']}")
                for warning in result['warnings']:
                    print(f"  ⚠ {warning}")
    
    # Show clean sample
    if clean > 0:
        print(f"\nCLEAN TRADES (showing first 5):")
        print("-" * 70)
        for result in validation_results[:5]:
            if not result['errors']:
                print(f"\nTrade ID: {result['trade_id']}")
                print(f"Ticker: {result['ticker']}")
                for check in result['checks']:
                    print(f"  ✓ {check}")
    
    # Write output if requested
    if args.output:
        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "trades_path": args.trades,
            "summary": {
                "total": total,
                "clean": clean,
                "errors": errors,
                "warnings": warnings,
            },
            "results": validation_results,
        }
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"\nReport written to {args.output}")
    
    # Exit with error code if there are errors
    sys.exit(1 if errors > 0 else 0)


if __name__ == "__main__":
    main()
