#!/usr/bin/env python3
"""
Unified Edge vs Legacy Backtest Comparison

Compares the performance of unified edge vs legacy edge computation methods.
This can be done by:
1. Analyzing shadow mode logs (when both are computed)
2. Running a backtest with each method
3. Comparing signal quality and PnL outcomes

For now, this provides a framework for comparison based on log analysis.
"""
import re
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple

def parse_shadow_mode_logs(log_file: Path) -> Dict[str, List[Dict]]:
    """Parse shadow mode comparison logs to extract edge differences.
    
    Expected log format:
    [SHADOW-MODE-COMPARISON] {agent} asset={asset} ticker={ticker} 
    LEGACY: edge={edge} conf={conf} implied={imp} model={mod} side={side} | 
    UNIFIED: edge={edge} conf={conf} implied={imp} model={mod} side={side} | 
    EDGE_DIFF={diff} SIDE_MATCH={match}
    """
    if not log_file.exists():
        print(f"Log file not found: {log_file}")
        return {}
    
    comparisons = defaultdict(list)
    
    # Pattern to match shadow mode comparison logs
    pattern = re.compile(
        r'\[SHADOW-MODE-COMPARISON\] (\S+) asset=(\S+) ticker=(\S+) '
        r'LEGACY: edge=([\d.]+) conf=([\d.]+) implied=([\d.]+) model=([\d.]+) side=(\w+) \| '
        r'UNIFIED: edge=([\d.]+) conf=([\d.]+) implied=([\d.]+) model=([\d.]+) side=(\w+) \| '
        r'EDGE_DIFF=([\d.]+) SIDE_MATCH=(True|False)'
    )
    
    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            match = pattern.search(line)
            if match:
                comparison = {
                    'agent': match.group(1),
                    'asset': match.group(2),
                    'ticker': match.group(3),
                    'legacy_edge': float(match.group(4)),
                    'legacy_conf': float(match.group(5)),
                    'legacy_implied': float(match.group(6)),
                    'legacy_model': float(match.group(7)),
                    'legacy_side': match.group(8),
                    'unified_edge': float(match.group(9)),
                    'unified_conf': float(match.group(10)),
                    'unified_implied': float(match.group(11)),
                    'unified_model': float(match.group(12)),
                    'unified_side': match.group(13),
                    'edge_diff': float(match.group(14)),
                    'side_match': match.group(15) == 'True',
                }
                comparisons[comparison['asset']].append(comparison)
    
    return comparisons

def analyze_edge_differences(comparisons: Dict[str, List[Dict]]) -> Dict[str, Dict]:
    """Analyze edge differences between legacy and unified methods."""
    results = {}
    
    for asset, comps in comparisons.items():
        if not comps:
            continue
        
        # Calculate statistics
        edge_diffs = [c['edge_diff'] for c in comps]
        side_matches = [c['side_match'] for c in comps]
        legacy_edges = [c['legacy_edge'] for c in comps]
        unified_edges = [c['unified_edge'] for c in comps]
        
        results[asset] = {
            'count': len(comps),
            'avg_edge_diff': sum(edge_diffs) / len(edge_diffs),
            'max_edge_diff': max(edge_diffs),
            'min_edge_diff': min(edge_diffs),
            'side_match_rate': sum(side_matches) / len(side_matches),
            'avg_legacy_edge': sum(legacy_edges) / len(legacy_edges),
            'avg_unified_edge': sum(unified_edges) / len(unified_edges),
        }
    
    return results

def print_comparison_report(results: Dict[str, Dict]):
    """Print comparison report."""
    print("\n" + "="*80)
    print("UNIFIED EDGE VS LEGACY EDGE COMPARISON")
    print("="*80)
    
    if not results:
        print("No shadow mode comparison data found")
        print("\nTo generate comparison data:")
        print("1. Enable shadow mode in agent_grid_15m.py (shadow_mode=True)")
        print("2. Run a trading session")
        print("3. Parse the logs with this script")
        return
    
    print("\n--- Per-Asset Edge Differences ---")
    for asset, stats in sorted(results.items()):
        print(f"\n{asset}:")
        print(f"  Comparisons: {stats['count']}")
        print(f"  Avg Edge Diff: {stats['avg_edge_diff']:.4f}")
        print(f"  Max Edge Diff: {stats['max_edge_diff']:.4f}")
        print(f"  Min Edge Diff: {stats['min_edge_diff']:.4f}")
        print(f"  Side Match Rate: {stats['side_match_rate']:.1%}")
        print(f"  Avg Legacy Edge: {stats['avg_legacy_edge']:.4f}")
        print(f"  Avg Unified Edge: {stats['avg_unified_edge']:.4f}")
    
    # Overall statistics
    all_counts = [s['count'] for s in results.values()]
    all_diffs = [s['avg_edge_diff'] for s in results.values()]
    all_matches = [s['side_match_rate'] for s in results.values()]
    
    print("\n--- Overall Statistics ---")
    print(f"Total Comparisons: {sum(all_counts)}")
    print(f"Mean Edge Diff: {sum(all_diffs) / len(all_diffs):.4f}")
    print(f"Mean Side Match Rate: {sum(all_matches) / len(all_matches):.1%}")
    
    print("\n--- Interpretation ---")
    print("Edge Diff < 0.01 (1%): Methods are similar")
    print("Edge Diff > 0.05 (5%): Methods differ significantly")
    print("Side Match Rate > 90%: Methods agree on direction")
    print("Side Match Rate < 70%: Methods disagree on direction frequently")

def enable_shadow_mode_instructions():
    """Print instructions for enabling shadow mode."""
    print("\n" + "="*80)
    print("SHADOW MODE SETUP INSTRUCTIONS")
    print("="*80)
    print("""
To enable shadow mode comparison in agent_grid_15m.py:

1. Add shadow_mode parameter to agent config or environment:
   export MERID_SHADOW_MODE=true

2. In agent_grid_15m.py _generate_signal method:
   - Set shadow_mode = os.environ.get('MERID_SHADOW_MODE', '').lower() == 'true'
   - The shadow mode comparison logging is already implemented (lines ~4782-4802)

3. Run a trading session:
   - Both legacy and unified edge will be computed
   - Legacy edge will be used for actual trading (safe fallback)
   - Comparison logs will be generated

4. After the session, run this script to analyze:
   python unified_vs_legacy_comparison.py --log-file /path/to/merid.log
    """)

def main():
    """Main function."""
    import sys
    
    # Check for log file argument
    log_file = None
    if len(sys.argv) > 1:
        log_file = Path(sys.argv[1])
    else:
        # Try to find default log file
        for possible_log in [
            Path("c:/Dev/MERID/logs/merid.log"),
            Path("c:/Dev/MERID/merid.log"),
            Path("logs/merid.log"),
        ]:
            if possible_log.exists():
                log_file = possible_log
                break
    
    if log_file:
        print(f"Analyzing log file: {log_file}")
        comparisons = parse_shadow_mode_logs(log_file)
        results = analyze_edge_differences(comparisons)
        print_comparison_report(results)
    else:
        print("No log file specified or found")
        enable_shadow_mode_instructions()

if __name__ == "__main__":
    main()
