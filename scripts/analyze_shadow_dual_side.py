"""
Shadow Dual-Side Analysis Script

Analyzes shadow dual-side metrics to quantify the opportunity cost of
expected_side gating in the 15m Kalshi crypto trading system.

Usage:
    python scripts/analyze_shadow_dual_side.py [--hours 24] [--verbose]

Options:
    --hours: Time window in hours to analyze (default: 24)
    --verbose: Print detailed per-asset and per-regime breakdowns
"""

import argparse
import sys
from datetime import datetime


def main():
    parser = argparse.ArgumentParser(description="Analyze shadow dual-side metrics")
    parser.add_argument("--hours", type=float, default=24.0, help="Time window in hours")
    parser.add_argument("--verbose", action="store_true", help="Print detailed breakdowns")
    args = parser.parse_args()
    
    try:
        from merid.metrics.shadow_dual_side_metrics import get_shadow_dual_side_monitor
        
        monitor = get_shadow_dual_side_monitor()
        analysis = monitor.get_analysis(time_window_hours=args.hours)
        
        print("=" * 80)
        print("SHADOW DUAL-SIDE ANALYSIS")
        print("=" * 80)
        print(f"Time window: {analysis.time_window[0]} to {analysis.time_window[1]}")
        print(f"Total evaluations: {analysis.total_evaluations}")
        print()
        
        if analysis.total_evaluations == 0:
            print("No data available in the specified time window.")
            return
        
        print("OVERALL METRICS")
        print("-" * 80)
        print(f"Missed opportunities: {analysis.missed_opportunities} / {analysis.total_evaluations}")
        print(f"Missed opportunity rate: {analysis.missed_opportunity_rate:.2%}")
        print(f"Average missed edge: {analysis.avg_missed_edge:.4f} ({analysis.avg_missed_edge*100:.2f}%)")
        print(f"Max missed edge: {analysis.max_missed_edge:.4f} ({analysis.max_missed_edge*100:.2f}%)")
        print(f"Total missed edge: {analysis.total_missed_edge:.4f}")
        print()
        
        print("VELOCITY CORRELATION")
        print("-" * 80)
        print(f"Low velocity (<0.005): {analysis.velocity_correlation['low_velocity_missed_rate']:.2%} "
              f"({analysis.velocity_correlation['low_velocity_count']} evaluations)")
        print(f"Medium velocity (0.005-0.015): {analysis.velocity_correlation['medium_velocity_missed_rate']:.2%} "
              f"({analysis.velocity_correlation['medium_velocity_count']} evaluations)")
        print(f"High velocity (>0.015): {analysis.velocity_correlation['high_velocity_missed_rate']:.2%} "
              f"({analysis.velocity_correlation['high_velocity_count']} evaluations)")
        print()
        
        if args.verbose:
            print("PER-ASSET BREAKDOWN")
            print("-" * 80)
            for asset, metrics in analysis.per_asset_breakdown.items():
                if metrics["total_evaluations"] > 0:
                    missed_rate = metrics["missed_opportunities"] / metrics["total_evaluations"]
                    avg_missed = metrics["total_missed_edge"] / metrics["missed_opportunities"] if metrics["missed_opportunities"] > 0 else 0.0
                    print(f"{asset}:")
                    print(f"  Evaluations: {metrics['total_evaluations']}")
                    print(f"  Missed: {metrics['missed_opportunities']} ({missed_rate:.2%})")
                    print(f"  Avg missed edge: {avg_missed:.4f} ({avg_missed*100:.2f}%)")
                    print(f"  Max missed edge: {metrics['max_missed_edge']:.4f} ({metrics['max_missed_edge']*100:.2f}%)")
                    print()
            
            print("PER-REGIME BREAKDOWN")
            print("-" * 80)
            for regime, metrics in analysis.per_regime_breakdown.items():
                if metrics["total_evaluations"] > 0:
                    missed_rate = metrics["missed_opportunities"] / metrics["total_evaluations"]
                    avg_missed = metrics["total_missed_edge"] / metrics["missed_opportunities"] if metrics["missed_opportunities"] > 0 else 0.0
                    print(f"{regime}:")
                    print(f"  Evaluations: {metrics['total_evaluations']}")
                    print(f"  Missed: {metrics['missed_opportunities']} ({missed_rate:.2%})")
                    print(f"  Avg missed edge: {avg_missed:.4f} ({avg_missed*100:.2f}%)")
                    print(f"  Max missed edge: {metrics['max_missed_edge']:.4f} ({metrics['max_missed_edge']*100:.2f}%)")
                    print()
            
            print("MISSED EDGE DISTRIBUTION")
            print("-" * 80)
            distribution = monitor.get_missed_edge_distribution(bins=10)
            if distribution:
                print("Bin Start | Bin End | Count")
                print("-" * 40)
                for bin_start, bin_end, count in distribution:
                    print(f"{bin_start:.4f}    | {bin_end:.4f}  | {count}")
            else:
                print("No missed edge data available.")
            print()
        
        print("RECOMMENDATIONS")
        print("-" * 80)
        if analysis.missed_opportunity_rate > 0.30:
            print("HIGH: Missed opportunity rate > 30%. Consider Phase 2 (edge dominance override).")
        elif analysis.missed_opportunity_rate > 0.15:
            print("MEDIUM: Missed opportunity rate > 15%. Monitor and consider Phase 2 if avg missed edge is significant.")
        else:
            print("LOW: Missed opportunity rate < 15%. Current gating is acceptable.")
        
        if analysis.avg_missed_edge > 0.05:
            print(f"WARNING: Average missed edge is {analysis.avg_missed_edge*100:.2f}% - significant opportunity cost.")
        elif analysis.avg_missed_edge > 0.02:
            print(f"INFO: Average missed edge is {analysis.avg_missed_edge*100:.2f}% - moderate opportunity cost.")
        else:
            print(f"INFO: Average missed edge is {analysis.avg_missed_edge*100:.2f}% - low opportunity cost.")
        
        print()
        print("=" * 80)
        
    except ImportError as e:
        print(f"Error importing shadow dual-side metrics: {e}")
        print("Make sure merid.metrics.shadow_dual_side_metrics is available.")
        sys.exit(1)
    except Exception as e:
        print(f"Error during analysis: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
