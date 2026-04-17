#!/usr/bin/env python3
"""
Simple CLI analytics tool for MERID agent runs.
Shows Brier scores, bucket composition, and LLM mode/status.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict, Counter

def load_agent_runs(log_file="logs/agent_runs.jsonl"):
    """Load agent runs from JSONL file."""
    runs = []
    try:
        with open(log_file) as f:
            for line in f:
                if line.strip():
                    runs.append(json.loads(line))
    except FileNotFoundError:
        print(f"❌ Log file not found: {log_file}")
        return []
    return runs

def get_timestamp(run):
    """Extract timestamp from run, handling both numeric and ISO formats."""
    if 'timestamp' in run:
        return run['timestamp']
    elif 'ts' in run:
        # Parse ISO timestamp like "2026-01-24T10:51:05Z"
        try:
            from datetime import datetime
            return datetime.fromisoformat(run['ts'].replace('Z', '+00:00')).timestamp()
        except:
            return 0
    return 0

def show_brier_vs_time(runs, days=7):
    """Show Brier scores over time."""
    print(f"\n📈 Brier Score vs Time (Last {days} days)")
    print("=" * 50)
    
    cutoff = datetime.now() - timedelta(days=days)
    recent_runs = [r for r in runs if datetime.fromtimestamp(get_timestamp(r)) > cutoff]
    
    if not recent_runs:
        print("No recent runs found")
        return
    
    # Group by date
    daily_scores = defaultdict(list)
    for run in recent_runs:
        if run.get('brier_score') is not None:
            date = datetime.fromtimestamp(get_timestamp(run)).strftime('%Y-%m-%d')
            daily_scores[date].append(run['brier_score'])
    
    for date in sorted(daily_scores.keys()):
        scores = daily_scores[date]
        avg_score = sum(scores) / len(scores)
        print(f"{date}: {avg_score:.4f} (n={len(scores)})")

def show_bucket_composition(runs):
    """Show bucket analysis composition."""
    print(f"\n🪣 Bucket Composition")
    print("=" * 30)
    
    bucket_counts = defaultdict(int)
    bucket_briers = defaultdict(list)
    
    for run in runs:
        buckets = run.get('bucket_stats', [])
        # Handle both string and dict formats
        for bucket in buckets:
            if isinstance(bucket, str):
                # Skip string representations, look for actual data
                continue
            elif isinstance(bucket, dict):
                bucket_range = bucket.get('bucket_range', 'unknown')
                bucket_counts[bucket_range] += bucket.get('count', 0)
                if bucket.get('avg_forecast') is not None:
                    bucket_briers[bucket_range].append(bucket.get('avg_forecast'))
    
    if not bucket_counts:
        print("No bucket data found")
        return
    
    for bucket_range in sorted(bucket_counts.keys()):
        count = bucket_counts[bucket_range]
        avg_forecast = sum(bucket_briers[bucket_range]) / len(bucket_briers[bucket_range]) if bucket_briers[bucket_range] else 0
        print(f"{bucket_range}: {count} opportunities (avg forecast: {avg_forecast:.3f})")

def show_llm_mode_status(runs):
    """Show LLM mode and status distribution."""
    print(f"\n🤖 LLM Mode/Status Distribution")
    print("=" * 40)
    
    mode_counts = Counter()
    status_counts = Counter()
    mode_status_combo = Counter()
    
    for run in runs:
        mode = run.get('llm_mode', 'unknown')
        status = run.get('llm_status', 'unknown')
        
        mode_counts[mode] += 1
        status_counts[status] += 1
        mode_status_combo[f"{mode}/{status}"] += 1
    
    print("Mode Distribution:")
    for mode, count in mode_counts.most_common():
        pct = count / len(runs) * 100
        print(f"  {mode}: {count} ({pct:.1f}%)")
    
    print("\nStatus Distribution:")
    for status, count in status_counts.most_common():
        pct = count / len(runs) * 100
        print(f"  {status}: {count} ({pct:.1f}%)")
    
    print("\nMode/Status Combo:")
    for combo, count in mode_status_combo.most_common():
        pct = count / len(runs) * 100
        print(f"  {combo}: {count} ({pct:.1f}%)")

def show_baseline_metrics(runs):
    """Show baseline Model 0 metrics (mock mode only)."""
    print(f"\n📊 Baseline Model 0 Metrics (Mock Mode)")
    print("=" * 45)
    
    mock_runs = [r for r in runs if r.get('llm_mode') == 'mock']
    
    if not mock_runs:
        print("No mock runs found")
        return
    
    # Brier scores
    brier_scores = [r.get('brier_score') for r in mock_runs if r.get('brier_score') is not None]
    if brier_scores:
        avg_brier = sum(brier_scores) / len(brier_scores)
        min_brier = min(brier_scores)
        max_brier = max(brier_scores)
        print(f"Brier Score: {avg_brier:.4f} (min: {min_brier:.4f}, max: {max_brier:.4f})")
    
    # Latency
    latencies = [r.get('latency_ms', 0) for r in mock_runs]
    if latencies:
        avg_latency = sum(latencies) / len(latencies)
        print(f"Latency: {avg_latency:.1f}ms")
    
    # Success rate
    success_count = len([r for r in mock_runs if r.get('status') == 'success'])
    success_rate = success_count / len(mock_runs) * 100
    print(f"Success Rate: {success_rate:.1f}% ({success_count}/{len(mock_runs)})")
    
    # Opportunities analyzed
    total_opp = sum([r.get('total_opportunities', 0) for r in mock_runs])
    avg_opp = total_opp / len(mock_runs)
    print(f"Opportunities: {avg_opp:.1f} avg per run")

def show_recent_activity(runs, hours=24):
    """Show recent activity summary."""
    print(f"\n⏰ Recent Activity (Last {hours} hours)")
    print("=" * 40)
    
    cutoff = datetime.now() - timedelta(hours=hours)
    recent_runs = [r for r in runs if datetime.fromtimestamp(get_timestamp(r)) > cutoff]
    
    if not recent_runs:
        print("No recent activity")
        return
    
    print(f"Total runs: {len(recent_runs)}")
    
    # Mode breakdown
    mode_counts = Counter([r.get('llm_mode', 'unknown') for r in recent_runs])
    for mode, count in mode_counts.most_common():
        print(f"  {mode}: {count}")
    
    # Status breakdown
    status_counts = Counter([r.get('llm_status', 'unknown') for r in recent_runs])
    for status, count in status_counts.most_common():
        print(f"  {status}: {count}")

def main():
    """Main CLI interface."""
    log_file = "logs/agent_runs.jsonl"
    
    if len(sys.argv) > 1:
        log_file = sys.argv[1]
    
    runs = load_agent_runs(log_file)
    
    if not runs:
        print("❌ No runs found. Run some experiments first!")
        return
    
    print(f"📋 Loaded {len(runs)} runs from {log_file}")
    
    # Show all views
    show_recent_activity(runs)
    show_llm_mode_status(runs)
    show_baseline_metrics(runs)
    show_brier_vs_time(runs)
    show_bucket_composition(runs)
    
    print(f"\n✅ Analysis complete!")

if __name__ == "__main__":
    main()
