#!/usr/bin/env python3
"""Validate order construction invariants against canonical YES/NO manifest.

This script pulls sample order logs from the order_router and verifies that:
- Side/action/mode correctly encode economic exposure
- Strategy intent aligns with YES/NO conditions from manifest
- edge_pct and price are consistent with signal-time state

Usage::

    python scripts/validate_order_construction.py --manifest data/kalshi_yes_no_manifest.json --logs data/order_logs.jsonl

Expected log format (from order_router.py structured logging):
{
    "intent_id": "...",
    "ticker": "KXBTC15M-26MAY120000-00",
    "side": "yes",
    "action": "buy",
    "price_cents": 55,
    "count": 10,
    "agent_id": "BTC_15M",
    "source": "kalshi_continuous_trader",
    "rationale": "BTC up momentum signal",
    "edge_pct": 0.05,
    "mode": "live",
    "snapshot_age": 1.2
}
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_manifest(manifest_path: str) -> Dict[str, Dict[str, Any]]:
    """Load canonical YES/NO manifest.
    
    Args:
        manifest_path: Path to kalshi_yes_no_manifest.json
        
    Returns:
        Dict mapping ticker -> manifest entry
    """
    with open(manifest_path, 'r') as f:
        data = json.load(f)
    
    manifest_by_ticker = {}
    for market in data.get('markets', []):
        ticker = market.get('ticker')
        if ticker:
            manifest_by_ticker[ticker] = market
    
    return manifest_by_ticker


def load_order_logs(logs_path: str) -> List[Dict[str, Any]]:
    """Load order logs from JSONL file.
    
    Args:
        logs_path: Path to order logs file (JSONL format)
        
    Returns:
        List of order log entries
    """
    orders = []
    with open(logs_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    orders.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"Warning: Failed to parse log line: {e}", file=sys.stderr)
    return orders


def infer_economic_intent(rationale: str) -> Optional[str]:
    """Infer economic intent from rationale text.
    
    Args:
        rationale: Strategy rationale text
        
    Returns:
        "long_up", "short_down", "neutral", or None if unclear
    """
    rationale_lower = rationale.lower()
    
    # Long up patterns
    if any(word in rationale_lower for word in ['up', 'higher', 'bullish', 'momentum', 'breakout']):
        return "long_up"
    
    # Short down patterns  
    if any(word in rationale_lower for word in ['down', 'lower', 'bearish', 'fade', 'short']):
        return "short_down"
    
    if any(word in rationale_lower for word in ['neutral', 'sideways', 'range']):
        return "neutral"
    
    return None


def check_order_invariants(
    order: Dict[str, Any],
    manifest_entry: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Check order construction invariants for a single order.
    
    Args:
        order: Order log entry
        manifest_entry: Manifest entry for this ticker (if available)
        
    Returns:
        Dict with check results
    """
    results = {
        'ticker': order.get('ticker'),
        'intent_id': order.get('intent_id'),
        'checks': [],
        'errors': [],
        'warnings': [],
    }
    
    ticker = order.get('ticker')
    side = order.get('side')
    action = order.get('action')
    mode = order.get('mode')
    rationale = order.get('rationale', '')
    edge_pct = order.get('edge_pct')
    price_cents = order.get('price_cents')
    snapshot_age = order.get('snapshot_age')
    
    # Check 1: Manifest exists for ticker
    if not manifest_entry:
        results['errors'].append(f"No manifest entry for ticker {ticker}")
        return results
    
    yes_condition = manifest_entry.get('yes_condition')
    no_condition = manifest_entry.get('no_condition')
    asset = manifest_entry.get('asset')
    
    results['checks'].append(f"Manifest found: {yes_condition}")
    
    # Check 2: Infer economic intent from rationale
    economic_intent = infer_economic_intent(rationale)
    if economic_intent:
        results['checks'].append(f"Inferred economic intent: {economic_intent}")
    else:
        results['warnings'].append(f"Could not infer economic intent from rationale: {rationale}")
    
    # Check 3: Verify side/action consistency with economic intent
    if economic_intent == "long_up":
        # Should be long YES or short NO (economically equivalent)
        if side == "yes" and action == "buy":
            results['checks'].append("✓ Long up intent → buy YES (correct)")
        elif side == "no" and action == "sell":
            results['checks'].append("✓ Long up intent → sell NO (economically equivalent)")
        elif side == "yes" and action == "sell":
            results['errors'].append(f"Long up intent but sell YES (inverted exposure)")
        elif side == "no" and action == "buy":
            results['errors'].append(f"Long up intent but buy NO (inverted exposure)")
        else:
            results['warnings'].append(f"Long up intent with unusual side/action: {side}/{action}")
    
    elif economic_intent == "short_down":
        # Should be long NO or short YES
        if side == "no" and action == "buy":
            results['checks'].append("✓ Short down intent → buy NO (correct)")
        elif side == "yes" and action == "sell":
            results['checks'].append("✓ Short down intent → sell YES (economically equivalent)")
        elif side == "yes" and action == "buy":
            results['errors'].append(f"Short down intent but buy YES (inverted exposure)")
        elif side == "no" and action == "sell":
            results['errors'].append(f"Short down intent but sell NO (inverted exposure)")
        else:
            results['warnings'].append(f"Short down intent with unusual side/action: {side}/{action}")
    
    # Check 4: Mode consistency
    if mode == "live":
        results['checks'].append(f"Live mode (no simulation)")
    elif mode in ["paper", "mock"]:
        results['checks'].append(f"Simulation mode: {mode}")
    else:
        results['warnings'].append(f"Unknown mode: {mode}")
    
    # Check 5: Edge_pct sanity
    if edge_pct is not None:
        if edge_pct < 0:
            results['errors'].append(f"Negative edge_pct: {edge_pct}")
        elif edge_pct > 1:
            results['warnings'].append(f"Very high edge_pct: {edge_pct}")
        else:
            results['checks'].append(f"Edge pct: {edge_pct:.1%}")
    
    # Check 6: Snapshot age sanity
    if snapshot_age is not None:
        if snapshot_age > 90:
            results['errors'].append(f"Stale snapshot: {snapshot_age:.1f}s > 90s")
        elif snapshot_age > 30:
            results['warnings'].append(f"Old snapshot: {snapshot_age:.1f}s")
        else:
            results['checks'].append(f"Snapshot age: {snapshot_age:.1f}s")
    
    # Check 7: Price sanity
    if price_cents is not None:
        if price_cents <= 0 or price_cents >= 100:
            results['errors'].append(f"Invalid price_cents: {price_cents}")
        else:
            results['checks'].append(f"Price: {price_cents}c")
    
    return results


def main():
    parser = argparse.ArgumentParser(description="Validate order construction invariants")
    parser.add_argument(
        "--manifest",
        required=True,
        help="Path to kalshi_yes_no_manifest.json"
    )
    parser.add_argument(
        "--logs",
        required=True,
        help="Path to order logs file (JSONL format)"
    )
    parser.add_argument(
        "--output",
        help="Output validation report to file"
    )
    
    args = parser.parse_args()
    
    # Load manifest
    print(f"Loading manifest from {args.manifest}...")
    manifest = load_manifest(args.manifest)
    print(f"Loaded {len(manifest)} ticker entries from manifest")
    
    # Load order logs
    print(f"Loading order logs from {args.logs}...")
    orders = load_order_logs(args.logs)
    print(f"Loaded {len(orders)} order log entries")
    
    # Validate each order
    print("\nValidating orders...")
    validation_results = []
    
    for order in orders:
        ticker = order.get('ticker')
        manifest_entry = manifest.get(ticker)
        result = check_order_invariants(order, manifest_entry)
        validation_results.append(result)
    
    # Summary statistics
    total = len(validation_results)
    errors = sum(1 for r in validation_results if r['errors'])
    warnings = sum(1 for r in validation_results if r['warnings'])
    clean = total - errors
    
    print(f"\n{'='*70}")
    print(f"VALIDATION SUMMARY")
    print(f"{'='*70}")
    print(f"Total orders: {total}")
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
                print(f"\nTicker: {result['ticker']}")
                print(f"Intent ID: {result['intent_id']}")
                for error in result['errors']:
                    print(f"  ✗ {error}")
    
    # Show warnings
    if warnings > 0:
        print(f"\nWARNINGS ({warnings}):")
        print("-" * 70)
        for result in validation_results:
            if result['warnings']:
                print(f"\nTicker: {result['ticker']}")
                print(f"Intent ID: {result['intent_id']}")
                for warning in result['warnings']:
                    print(f"  ⚠ {warning}")
    
    # Show clean sample
    if clean > 0:
        print(f"\nCLEAN ORDERS (showing first 5):")
        print("-" * 70)
        for result in validation_results[:5]:
            if not result['errors']:
                print(f"\nTicker: {result['ticker']}")
                for check in result['checks']:
                    print(f"  ✓ {check}")
    
    # Write output if requested
    if args.output:
        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "manifest_path": args.manifest,
            "logs_path": args.logs,
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
