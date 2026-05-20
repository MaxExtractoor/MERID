#!/usr/bin/env python3
"""Exhaustive internal mapping check vs canonical manifest.

This script performs a comprehensive check of internal side mappings
against the canonical YES/NO manifest to detect semantic drift.

Usage::

    python scripts/validate_internal_mapping.py --manifest data/kalshi_yes_no_manifest.json --logs data/order_logs.jsonl
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Set


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


def check_internal_mapping(
    manifest: Dict[str, Dict[str, Any]],
    orders: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Perform exhaustive internal mapping check.
    
    Args:
        manifest: Canonical YES/NO manifest
        orders: Order log entries
        
    Returns:
        Dict with check results
    """
    results = {
        'tickers_in_logs_not_in_manifest': [],
        'manifest_entries_never_traded': [],
        'side_distribution': {},
        'asset_coverage': {},
        'warnings': [],
    }
    
    # Get all tickers from logs
    tickers_in_logs = set()
    side_counts = {}
    asset_counts = {}
    
    for order in orders:
        ticker = order.get('ticker')
        side = order.get('side')
        agent_id = order.get('agent_id', '')
        
        if ticker:
            tickers_in_logs.add(ticker)
            
            # Track side distribution
            if ticker not in side_counts:
                side_counts[ticker] = {'yes': 0, 'no': 0}
            if side:
                side_counts[ticker][side] = side_counts[ticker].get(side, 0) + 1
            
            # Track asset coverage (extract from ticker)
            if 'BTC' in ticker.upper():
                asset = 'BTC'
            elif 'ETH' in ticker.upper():
                asset = 'ETH'
            elif 'SOL' in ticker.upper():
                asset = 'SOL'
            elif 'XRP' in ticker.upper():
                asset = 'XRP'
            elif 'DOGE' in ticker.upper():
                asset = 'DOGE'
            else:
                asset = 'UNKNOWN'
            
            if asset not in asset_counts:
                asset_counts[asset] = 0
            asset_counts[asset] += 1
    
    # Check 1: Tickers in logs but missing from manifest
    for ticker in tickers_in_logs:
        if ticker not in manifest:
            results['tickers_in_logs_not_in_manifest'].append(ticker)
            results['warnings'].append(f"Ticker {ticker} traded but missing from manifest")
    
    # Check 2: Manifest entries never traded
    for ticker in manifest:
        if ticker not in tickers_in_logs:
            results['manifest_entries_never_traded'].append(ticker)
    
    results['side_distribution'] = side_counts
    results['asset_coverage'] = asset_counts
    
    return results


def main():
    parser = argparse.ArgumentParser(description="Exhaustive internal mapping check")
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
    
    # Run check
    print("\nRunning internal mapping check...")
    results = check_internal_mapping(manifest, orders)
    
    # Summary
    print(f"\n{'='*70}")
    print(f"INTERNAL MAPPING CHECK SUMMARY")
    print(f"{'='*70}")
    print(f"Total tickers in manifest: {len(manifest)}")
    print(f"Total tickers traded: {len(set(o.get('ticker') for o in orders if o.get('ticker')))}")
    print(f"Tickers in logs but not in manifest: {len(results['tickers_in_logs_not_in_manifest'])}")
    print(f"Manifest entries never traded: {len(results['manifest_entries_never_traded'])}")
    print(f"Warnings: {len(results['warnings'])}")
    print(f"{'='*70}")
    
    # Show warnings
    if results['warnings']:
        print(f"\nWARNINGS:")
        print("-" * 70)
        for warning in results['warnings']:
            print(f"  ⚠ {warning}")
    
    # Show missing tickers
    if results['tickers_in_logs_not_in_manifest']:
        print(f"\nTICKERS IN LOGS BUT MISSING FROM MANIFEST ({len(results['tickers_in_logs_not_in_manifest'])}):")
        print("-" * 70)
        for ticker in results['tickers_in_logs_not_in_manifest'][:20]:  # Show first 20
            print(f"  - {ticker}")
        if len(results['tickers_in_logs_not_in_manifest']) > 20:
            print(f"  ... and {len(results['tickers_in_logs_not_in_manifest']) - 20} more")
    
    # Show unused manifest entries
    if results['manifest_entries_never_traded']:
        print(f"\nMANIFEST ENTRIES NEVER TRADED ({len(results['manifest_entries_never_traded'])}):")
        print("-" * 70)
        for ticker in results['manifest_entries_never_traded'][:20]:  # Show first 20
            print(f"  - {ticker}")
        if len(results['manifest_entries_never_traded']) > 20:
            print(f"  ... and {len(results['manifest_entries_never_traded']) - 20} more")
    
    # Show asset coverage
    print(f"\nASSET COVERAGE:")
    print("-" * 70)
    for asset, count in sorted(results['asset_coverage'].items()):
        print(f"  {asset}: {count} orders")
    
    # Show side distribution sample
    print(f"\nSIDE DISTRIBUTION (showing first 10 tickers):")
    print("-" * 70)
    for ticker, counts in list(results['side_distribution'].items())[:10]:
        print(f"  {ticker}: YES={counts['yes']}, NO={counts['no']}")
    
    # Write output if requested
    if args.output:
        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "manifest_path": args.manifest,
            "logs_path": args.logs,
            "summary": {
                "total_in_manifest": len(manifest),
                "total_traded": len(set(o.get('ticker') for o in orders if o.get('ticker'))),
                "missing_from_manifest": len(results['tickers_in_logs_not_in_manifest']),
                "never_traded": len(results['manifest_entries_never_traded']),
                "warnings": len(results['warnings']),
            },
            "tickers_in_logs_not_in_manifest": results['tickers_in_logs_not_in_manifest'],
            "manifest_entries_never_traded": results['manifest_entries_never_traded'],
            "side_distribution": results['side_distribution'],
            "asset_coverage": results['asset_coverage'],
        }
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"\nReport written to {args.output}")
    
    # Exit with error code if there are missing tickers
    sys.exit(1 if results['tickers_in_logs_not_in_manifest'] else 0)


if __name__ == "__main__":
    main()
