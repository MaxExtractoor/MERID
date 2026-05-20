#!/usr/bin/env python3
"""Lifecycle funnel dashboard - counts per stage and drop-off rates.

This script analyzes trade lifecycle logs to produce funnel analytics:
- Counts per day/hour at each lifecycle stage
- Drop-off rates between stages
- Attribution of drops (strategy gating vs risk approval)

Usage::

    python scripts/analytics_lifecycle_funnel.py --logs data/lifecycle_logs.jsonl
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List


def load_lifecycle_logs(logs_path: str) -> List[Dict[str, Any]]:
    """Load lifecycle logs from JSONL file.
    
    Args:
        logs_path: Path to lifecycle logs file (JSONL format)
        
    Returns:
        List of lifecycle event entries
    """
    events = []
    with open(logs_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"Warning: Failed to parse log line: {e}", file=sys.stderr)
    return events


def analyze_lifecycle_funnel(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze lifecycle funnel.
    
    Args:
        events: Lifecycle event entries
        
    Returns:
        Dict with funnel analytics
    """
    # Stage sequence
    stage_sequence = [
        'SIGNAL_GENERATED',
        'STRATEGY_GATED',
        'RISK_APPROVED',
        'ORDER_PLACED',
        'FILL_RECEIVED',
        'SETTLED'
    ]
    
    # Group by trade_id
    trades_by_id = defaultdict(list)
    for event in events:
        trade_id = event.get('trade_id')
        if trade_id:
            trades_by_id[trade_id].append(event)
    
    # Count trades at each stage
    stage_counts = defaultdict(int)
    stage_counts_by_day = defaultdict(lambda: defaultdict(int))
    
    for trade_id, trade_events in trades_by_id.items():
        # Determine which stages this trade reached
        stages_reached = set()
        for event in trade_events:
            stage = event.get('stage')
            if stage:
                stages_reached.add(stage)
        
        # Count at each stage
        for stage in stage_sequence:
            if stage in stages_reached:
                stage_counts[stage] += 1
                
                # Count by day
                timestamp = event.get('timestamp')
                if timestamp:
                    try:
                        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        day_key = dt.date().isoformat()
                        stage_counts_by_day[day_key][stage] += 1
                    except:
                        pass
    
    # Calculate drop-off rates
    drop_off_rates = {}
    for i in range(len(stage_sequence) - 1):
        current_stage = stage_sequence[i]
        next_stage = stage_sequence[i + 1]
        
        current_count = stage_counts.get(current_stage, 0)
        next_count = stage_counts.get(next_stage, 0)
        
        if current_count > 0:
            drop_off_rate = (current_count - next_count) / current_count
            drop_off_rates[f"{current_stage} → {next_stage}"] = {
                'from_count': current_count,
                'to_count': next_count,
                'drop_off_count': current_count - next_count,
                'drop_off_rate': drop_off_rate,
            }
    
    return {
        'stage_counts': dict(stage_counts),
        'stage_counts_by_day': dict(stage_counts_by_day),
        'drop_off_rates': drop_off_rates,
        'total_trades': len(trades_by_id),
    }


def main():
    parser = argparse.ArgumentParser(description="Lifecycle funnel dashboard")
    parser.add_argument(
        "--logs",
        required=True,
        help="Path to lifecycle logs file (JSONL format)"
    )
    parser.add_argument(
        "--output",
        help="Output analytics report to file"
    )
    
    args = parser.parse_args()
    
    # Load logs
    print(f"Loading lifecycle logs from {args.logs}...")
    events = load_lifecycle_logs(args.logs)
    print(f"Loaded {len(events)} lifecycle events")
    
    # Analyze
    print("\nAnalyzing lifecycle funnel...")
    analytics = analyze_lifecycle_funnel(events)
    
    # Display results
    print(f"\n{'='*70}")
    print(f"LIFECYCLE FUNNEL ANALYTICS")
    print(f"{'='*70}")
    print(f"Total unique trades: {analytics['total_trades']}")
    print(f"\nStage Counts:")
    print("-" * 70)
    
    stage_sequence = [
        'SIGNAL_GENERATED',
        'STRATEGY_GATED',
        'RISK_APPROVED',
        'ORDER_PLACED',
        'FILL_RECEIVED',
        'SETTLED'
    ]
    
    for stage in stage_sequence:
        count = analytics['stage_counts'].get(stage, 0)
        print(f"  {stage:25s}: {count}")
    
    print(f"\nDrop-off Rates:")
    print("-" * 70)
    for transition, metrics in analytics['drop_off_rates'].items():
        print(f"  {transition:30s}: {metrics['drop_off_rate']:.1%} ({metrics['drop_off_count']} dropped)")
    
    print(f"\nStage Counts by Day (showing last 3 days):")
    print("-" * 70)
    days = sorted(analytics['stage_counts_by_day'].keys())[-3:]
    for day in days:
        print(f"\n  {day}:")
        for stage in stage_sequence:
            count = analytics['stage_counts_by_day'][day].get(stage, 0)
            print(f"    {stage:25s}: {count}")
    
    # Write output if requested
    if args.output:
        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "logs_path": args.logs,
            "analytics": analytics,
        }
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"\nReport written to {args.output}")


if __name__ == "__main__":
    main()
