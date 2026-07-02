#!/usr/bin/env python3
"""
Shadow mode for unified edge - observe only, no actual routing.

This script runs unified edge in "observe only" mode for a few hours,
logging what the router would have allocated vs what production actually does.

Usage:
    python scripts/shadow_unified_edge.py --log-dir /path/to/logs --hours 2
"""

import argparse
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple


def parse_log_line(line: str) -> Tuple[str, str, Dict]:
    """Parse log line and extract tag, asset, and fields."""
    tag_match = re.search(r'\[([A-Z-]+)\]', line)
    tag = tag_match.group(1) if tag_match else "UNKNOWN"
    
    asset_match = re.search(r'asset=(BTC|ETH|SOL|XRP|DOGE)', line)
    asset = asset_match.group(1) if asset_match else "UNKNOWN"
    
    fields = {}
    for match in re.finditer(r'(\w+)=([^\s]+)', line):
        key, value = match.groups()
        fields[key] = value
    
    return tag, asset, fields


def analyze_shadow_mode(log_dir: Path, hours: int) -> Dict:
    """
    Analyze logs for shadow mode comparison.
    
    Returns:
        Dict with shadow vs production comparison
    """
    print(f"Analyzing logs from {log_dir} (last {hours} hours)...")
    
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
    
    # Track unified edge decisions
    unified_edge_decisions = defaultdict(list)
    production_decisions = defaultdict(list)
    
    # Process log files
    log_files = list(log_dir.glob("*.log")) + list(log_dir.glob("*.txt"))
    
    for log_file in log_files:
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    # Parse line
                    tag, asset, fields = parse_log_line(line)
                    
                    if asset not in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                        continue
                    
                    # Extract timestamp
                    ts_match = re.search(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', line)
                    if not ts_match:
                        continue
                    
                    try:
                        line_time = datetime.fromisoformat(ts_match.group(1))
                        if line_time < cutoff_time:
                            continue
                    except:
                        continue
                    
                    # Track unified edge decisions
                    if tag == "UNIFIED-EDGE-APPLIED":
                        edge = float(fields.get('edge', 0))
                        edge_r = float(fields.get('edge_r', 0))
                        unified_edge_decisions[asset].append({
                            'edge': edge,
                            'edge_r': edge_r,
                            'timestamp': line_time,
                        })
                    
                    # Track production decisions
                    if tag == "SIGNAL":
                        edge = float(fields.get('edge', 0))
                        production_decisions[asset].append({
                            'edge': edge,
                            'timestamp': line_time,
                        })
                    
                    # Track shadow routing decisions
                    if tag == "DYNAMIC-RISK-ROUTING-SHADOW":
                        edge_r = float(fields.get('edge_R', 0))
                        unified_edge_decisions[asset].append({
                            'edge_r': edge_r,
                            'timestamp': line_time,
                            'shadow_routing': True,
                        })
                    
        except Exception as e:
            print(f"Error processing {log_file}: {e}")
    
    return {
        'unified_edge': dict(unified_edge_decisions),
        'production': dict(production_decisions),
    }


def print_shadow_comparison(results: Dict):
    """Print shadow mode comparison."""
    print("\n" + "=" * 80)
    print("SHADOW MODE COMPARISON")
    print("=" * 80)
    
    for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
        unified = results['unified_edge'].get(asset, [])
        production = results['production'].get(asset, [])
        
        print(f"\n{asset}:")
        print(f"  Unified edge decisions: {len(unified)}")
        print(f"  Production decisions: {len(production)}")
        
        if unified:
            avg_edge_r = sum(d.get('edge_r', 0) for d in unified) / len(unified)
            max_edge_r = max(d.get('edge_r', 0) for d in unified)
            print(f"  Avg edge_R: {avg_edge_r:.3f}")
            print(f"  Max edge_R: {max_edge_r:.3f}")
        
        if production:
            avg_edge = sum(d['edge'] for d in production) / len(production)
            print(f"  Avg production edge: {avg_edge:.3f}")
        
        # Check for pathological cases
        if unified:
            # Check for huge edge_R with no book depth
            huge_edge_r = [d for d in unified if d.get('edge_r', 0) > 5.0]
            if huge_edge_r:
                print(f"  ⚠️  PATHOLOGICAL: {len(huge_edge_r)} decisions with edge_R > 5.0")
            
            # Check for negative edge_R
            negative_edge_r = [d for d in unified if d.get('edge_r', 0) < 0]
            if negative_edge_r:
                print(f"  ⚠️  PATHOLOGICAL: {len(negative_edge_r)} decisions with edge_R < 0")
        
        # Check for divergence
        if unified and production:
            unified_count = len(unified)
            production_count = len(production)
            if abs(unified_count - production_count) > 10:
                print(f"  ⚠️  DIVERGENCE: Unified ({unified_count}) vs Production ({production_count})")


def main():
    parser = argparse.ArgumentParser(description="Shadow mode for unified edge")
    parser.add_argument("--log-dir", type=Path, required=True, help="Directory containing log files")
    parser.add_argument("--hours", type=int, default=2, help="Hours of logs to analyze (default: 2)")
    
    args = parser.parse_args()
    
    if not args.log_dir.exists():
        print(f"Error: Log directory {args.log_dir} does not exist")
        return 1
    
    results = analyze_shadow_mode(args.log_dir, args.hours)
    print_shadow_comparison(results)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
