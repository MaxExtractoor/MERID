#!/usr/bin/env python3
"""
Offline analysis script to parse LIQUIDITY-LIFECYCLE and LIQUIDITY-ASSET-SUMMARY logs
and generate per-asset liquidity statistics table.

Usage:
    python scripts/analyze_liquidity_lifecycle.py --log-file logs/full.log
    python scripts/analyze_liquidity_lifecycle.py --log-file logs/full.log --output csv
"""

import argparse
import json
import re
import csv
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class AssetLiquidityStats:
    """Per-asset liquidity statistics."""
    asset: str
    total_windows: int = 0
    one_sided_windows: int = 0
    ever_two_sided_windows: int = 0
    one_sided_rate: float = 0.0
    two_sided_rate: float = 0.0
    
    # Track per-window details
    window_details: List[Dict] = field(default_factory=list)
    
    def add_window(self, one_sided: int, ever_two_sided: int, total_windows: int):
        """Add a window's liquidity data."""
        self.total_windows += total_windows
        self.one_sided_windows += one_sided
        self.ever_two_sided_windows += ever_two_sided
        
        self.one_sided_rate = (self.one_sided_windows / self.total_windows * 100) if self.total_windows > 0 else 0.0
        self.two_sided_rate = (self.ever_two_sided_windows / self.total_windows * 100) if self.total_windows > 0 else 0.0
        
        self.window_details.append({
            'one_sided': one_sided,
            'ever_two_sided': ever_two_sided,
            'total_windows': total_windows,
            'one_sided_rate': self.one_sided_rate,
            'two_sided_rate': self.two_sided_rate
        })


def parse_log_file(log_path: Path) -> Dict[str, AssetLiquidityStats]:
    """Parse log file and extract liquidity lifecycle data."""
    asset_stats: Dict[str, AssetLiquidityStats] = {}
    
    # Patterns to match
    lifecycle_pattern = re.compile(
        r'\[LIQUIDITY-LIFECYCLE\] tick=(\d+) markets_tracked=(\d+) ever_two_sided=(\d+) never_two_sided=(\d+) two_sided_rate=([\d.]+)%'
    )
    asset_summary_pattern = re.compile(
        r'\[LIQUIDITY-ASSET-SUMMARY\] asset=(\w+) windows=(\d+) one_sided=(\d+) ever_two_sided=(\d+) one_sided_rate=([\d.]+)%'
    )
    
    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            # Try to parse LIQUIDITY-ASSET-SUMMARY (per-asset data)
            asset_match = asset_summary_pattern.search(line)
            if asset_match:
                asset = asset_match.group(1)
                windows = int(asset_match.group(2))
                one_sided = int(asset_match.group(3))
                ever_two_sided = int(asset_match.group(4))
                one_sided_rate = float(asset_match.group(5))
                
                if asset not in asset_stats:
                    asset_stats[asset] = AssetLiquidityStats(asset=asset)
                
                # Update stats from this summary line
                asset_stats[asset].total_windows = windows
                asset_stats[asset].one_sided_windows = one_sided
                asset_stats[asset].ever_two_sided_windows = ever_two_sided
                asset_stats[asset].one_sided_rate = one_sided_rate
                asset_stats[asset].two_sided_rate = 100.0 - one_sided_rate
                
                continue
            
            # Try to parse LIQUIDITY-LIFECYCLE (aggregate data)
            lifecycle_match = lifecycle_pattern.search(line)
            if lifecycle_match:
                tick = int(lifecycle_match.group(1))
                markets_tracked = int(lifecycle_match.group(2))
                ever_two_sided = int(lifecycle_match.group(3))
                never_two_sided = int(lifecycle_match.group(4))
                two_sided_rate = float(lifecycle_match.group(5))
                
                # This is aggregate data, not per-asset, so we skip it for now
                # The per-asset data comes from LIQUIDITY-ASSET-SUMMARY
                continue
    
    return asset_stats


def print_table(asset_stats: Dict[str, AssetLiquidityStats]):
    """Print formatted table of asset liquidity statistics."""
    print("\n" + "=" * 100)
    print("LIQUIDITY LIFECYCLE ANALYSIS - PER-ASSET SUMMARY")
    print("=" * 100)
    print(f"{'Asset':<10} {'Total Windows':<15} {'One-Sided':<12} {'Ever Two-Sided':<17} {'One-Sided %':<12} {'Two-Sided %':<12}")
    print("-" * 100)
    
    # Sort by asset name
    for asset in sorted(asset_stats.keys()):
        stats = asset_stats[asset]
        print(
            f"{asset:<10} "
            f"{stats.total_windows:<15} "
            f"{stats.one_sided_windows:<12} "
            f"{stats.ever_two_sided_windows:<17} "
            f"{stats.one_sided_rate:<12.2f} "
            f"{stats.two_sided_rate:<12.2f}"
        )
    
    print("=" * 100)
    
    # Print summary comparison
    print("\nSUMMARY COMPARISON:")
    print("-" * 100)
    
    high_volatility = ['BTC', 'ETH']
    low_volatility = ['SOL', 'XRP', 'DOGE']
    
    high_one_sided = sum(s.one_sided_rate for s in asset_stats.values() if s.asset in high_volatility) / len(high_volatility) if high_volatility else 0
    low_one_sided = sum(s.one_sided_rate for s in asset_stats.values() if s.asset in low_volatility) / len(low_volatility) if low_volatility else 0
    
    print(f"High Volatility (BTC/ETH) - Avg One-Sided Rate: {high_one_sided:.2f}%")
    print(f"Low Volatility (SOL/XRP/DOGE) - Avg One-Sided Rate: {low_one_sided:.2f}%")
    print(f"Difference: {abs(high_one_sided - low_one_sided):.2f}%")
    
    if abs(high_one_sided - low_one_sided) > 5.0:
        print("⚠️  SIGNIFICANT DIFFERENCE: High volatility assets show different liquidity patterns")
    else:
        print("✓ Similar liquidity patterns across volatility tiers")


def export_csv(asset_stats: Dict[str, AssetLiquidityStats], output_path: Path):
    """Export asset statistics to CSV."""
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Asset', 'Total Windows', 'One-Sided Windows', 'Ever Two-Sided Windows', 'One-Sided Rate %', 'Two-Sided Rate %'])
        
        for asset in sorted(asset_stats.keys()):
            stats = asset_stats[asset]
            writer.writerow([
                asset,
                stats.total_windows,
                stats.one_sided_windows,
                stats.ever_two_sided_windows,
                f"{stats.one_sided_rate:.2f}",
                f"{stats.two_sided_rate:.2f}"
            ])
    
    print(f"\n✓ CSV exported to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Analyze liquidity lifecycle logs')
    parser.add_argument('--log-file', type=Path, required=True, help='Path to log file')
    parser.add_argument('--output', choices=['table', 'csv', 'both'], default='table', help='Output format')
    parser.add_argument('--csv-path', type=Path, default=Path('liquidity_analysis.csv'), help='CSV output path')
    
    args = parser.parse_args()
    
    if not args.log_file.exists():
        print(f"Error: Log file not found: {args.log_file}")
        return
    
    print(f"Parsing log file: {args.log_file}")
    asset_stats = parse_log_file(args.log_file)
    
    if not asset_stats:
        print("No liquidity data found in log file")
        return
    
    print(f"Found {len(asset_stats)} assets with liquidity data")
    
    if args.output in ['table', 'both']:
        print_table(asset_stats)
    
    if args.output in ['csv', 'both']:
        export_csv(asset_stats, args.csv_path)


if __name__ == '__main__':
    main()
