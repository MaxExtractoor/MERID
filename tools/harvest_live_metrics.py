#!/usr/bin/env python3
"""
Live Metrics Harvester for MERID Predictions

Harvests and analyzes live metrics from agent runs to inform:
- Baseline prompt/agent selection
- Performance guardrails
- Calibration trends
- Latency envelopes
"""

import argparse
import json
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import defaultdict, Counter


def load_runs(log_path: str, days_back: int = 7) -> List[Dict[str, Any]]:
    """Load recent agent runs from log file."""
    from datetime import timezone
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=days_back)
    runs = []
    
    try:
        with Path(log_path).open() as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    run = json.loads(line.strip())
                    # Parse timestamp
                    if 'timestamp' in run:
                        ts = datetime.fromtimestamp(run['timestamp'], tz=timezone.utc)
                    elif 'ts' in run:
                        ts_str = run['ts'].replace('Z', '+00:00')
                        ts = datetime.fromisoformat(ts_str)
                    else:
                        continue
                    
                    if ts >= cutoff_time:
                        run['parsed_timestamp'] = ts
                        runs.append(run)
                except (json.JSONDecodeError, ValueError):
                    continue
    except FileNotFoundError:
        print(f"❌ Log file not found: {log_path}")
        return []
    
    return runs


def analyze_brier_trends(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze Brier score trends by agent version and time."""
    brier_by_version = defaultdict(list)
    brier_by_day = defaultdict(list)
    
    for run in runs:
        if run.get('brier_score') is not None:
            version = run.get('agent_version', 'unknown')
            day = run['parsed_timestamp'].date().isoformat()
            
            brier_by_version[version].append(run['brier_score'])
            brier_by_day[day].append(run['brier_score'])
    
    # Calculate statistics
    version_stats = {}
    for version, scores in brier_by_version.items():
        version_stats[version] = {
            'count': len(scores),
            'mean_brier': statistics.mean(scores),
            'median_brier': statistics.median(scores),
            'min_brier': min(scores),
            'max_brier': max(scores),
            'std_brier': statistics.stdev(scores) if len(scores) > 1 else 0
        }
    
    day_stats = {}
    for day, scores in brier_by_day.items():
        day_stats[day] = {
            'count': len(scores),
            'mean_brier': statistics.mean(scores),
            'median_brier': statistics.median(scores)
        }
    
    return {
        'by_version': version_stats,
        'by_day': day_stats,
        'overall_trend': list(day_stats.items())
    }


def analyze_latency_envelopes(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze latency patterns and envelopes."""
    latencies = [r.get('latency_ms', 0) for r in runs if r.get('latency_ms') is not None]
    
    if not latencies:
        return {'error': 'No latency data found'}
    
    # Calculate percentiles
    percentiles = {
        'p50': statistics.quantiles(latencies, n=2)[0],
        'p75': statistics.quantiles(latencies, n=4)[2],
        'p90': statistics.quantiles(latencies, n=10)[8],
        'p95': statistics.quantiles(latencies, n=20)[18],
        'p99': statistics.quantiles(latencies, n=100)[98] if len(latencies) >= 100 else max(latencies)
    }
    
    return {
        'count': len(latencies),
        'mean_latency': statistics.mean(latencies),
        'median_latency': statistics.median(latencies),
        'min_latency': min(latencies),
        'max_latency': max(latencies),
        'std_latency': statistics.stdev(latencies) if len(latencies) > 1 else 0,
        'percentiles': percentiles,
        'latency_distribution': {
            'under_1s': len([l for l in latencies if l < 1000]),
            'under_2s': len([l for l in latencies if l < 2000]),
            'under_5s': len([l for l in latencies if l < 5000]),
            'over_5s': len([l for l in latencies if l >= 5000])
        }
    }


def analyze_bucket_calibration(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze bucket calibration patterns."""
    bucket_stats = defaultdict(list)
    category_buckets = defaultdict(lambda: defaultdict(list))
    
    for run in runs:
        if 'bucket_stats' in run and run['bucket_stats']:
            categories = run.get('filters', {}).get('categories', [])
            category = categories[0] if categories else 'all'
            
            for bucket in run['bucket_stats']:
                if isinstance(bucket, dict):
                    bucket_range = bucket.get('bucket_range', 'unknown')
                    bucket_stats[bucket_range].append(bucket)
                    category_buckets[category][bucket_range].append(bucket)
    
    # Analyze calibration quality
    calibration_analysis = {}
    for bucket_range, buckets in bucket_stats.items():
        if buckets:
            avg_forecast = statistics.mean([b.get('avg_forecast', 0) for b in buckets])
            avg_empirical = statistics.mean([b.get('empirical_success_rate', 0) for b in buckets])
            calibration_error = abs(avg_forecast - avg_empirical)
            
            calibration_analysis[bucket_range] = {
                'count': len(buckets),
                'avg_forecast': avg_forecast,
                'avg_empirical': avg_empirical,
                'calibration_error': calibration_error,
                'avg_spread': statistics.mean([b.get('avg_spread', 0) for b in buckets]),
                'avg_liquidity': statistics.mean([b.get('avg_liquidity', 0) for b in buckets])
            }
    
    return {
        'overall_calibration': calibration_analysis,
        'by_category': {
            cat: {br: {
                'count': len(buckets),
                'avg_forecast': statistics.mean([b.get('avg_forecast', 0) for b in buckets]),
                'avg_empirical': statistics.mean([b.get('empirical_success_rate', 0) for b in buckets])
            } for br, buckets in cat_buckets.items() if buckets}
            for cat, cat_buckets in category_buckets.items()
        }
    }


def analyze_failure_modes(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze failure patterns and modes."""
    total_runs = len(runs)
    successful_runs = len([r for r in runs if r.get('status') == 'success'])
    failed_runs = total_runs - successful_runs
    
    error_types = Counter()
    error_messages = Counter()
    
    for run in runs:
        if run.get('status') != 'success':
            error_type = run.get('error_type', 'unknown')
            error_message = run.get('error_message', 'unknown')
            error_types[error_type] += 1
            error_messages[error_message] += 1
    
    return {
        'total_runs': total_runs,
        'successful_runs': successful_runs,
        'failed_runs': failed_runs,
        'success_rate': successful_runs / total_runs if total_runs > 0 else 0,
        'error_types': dict(error_types),
        'common_errors': dict(error_messages.most_common(5))
    }


def generate_recommendations(analysis: Dict[str, Any]) -> List[str]:
    """Generate actionable recommendations based on analysis."""
    recommendations = []
    
    # Brier score recommendations
    brier_analysis = analysis.get('brier_trends', {})
    if 'by_version' in brier_analysis:
        version_stats = brier_analysis['by_version']
        if len(version_stats) > 1:
            best_version = min(version_stats.items(), key=lambda x: x[1]['mean_brier'])
            recommendations.append(
                f"🏆 Best performing version: {best_version[0]} "
                f"(mean Brier: {best_version[1]['mean_brier']:.4f})"
            )
    
    # Latency recommendations
    latency_analysis = analysis.get('latency_envelopes', {})
    if 'percentiles' in latency_analysis:
        p95 = latency_analysis['percentiles']['p95']
        if p95 > 5000:  # 5 seconds
            recommendations.append(
                f"⚠️ High P95 latency ({p95:.0f}ms) - consider LLM optimization"
            )
        elif p95 < 2000:  # 2 seconds
            recommendations.append(
                f"✅ Excellent P95 latency ({p95:.0f}ms) - system is well optimized"
            )
    
    # Calibration recommendations
    calibration_analysis = analysis.get('bucket_calibration', {})
    if 'overall_calibration' in calibration_analysis:
        calibration_errors = [
            bucket['calibration_error'] 
            for bucket in calibration_analysis['overall_calibration'].values()
        ]
        if calibration_errors:
            avg_error = statistics.mean(calibration_errors)
            if avg_error > 0.1:  # 10% error
                recommendations.append(
                    f"⚠️ High calibration error ({avg_error:.3f}) - review prompt quality"
                )
            elif avg_error < 0.05:  # 5% error
                recommendations.append(
                    f"✅ Excellent calibration ({avg_error:.3f}) - prompts are well calibrated"
                )
    
    # Failure rate recommendations
    failure_analysis = analysis.get('failure_modes', {})
    if failure_analysis.get('success_rate', 0) < 0.8:  # 80% success rate
        recommendations.append(
            f"⚠️ Low success rate ({failure_analysis['success_rate']:.1%}) - investigate failure modes"
        )
    
    return recommendations


def main():
    parser = argparse.ArgumentParser(description="Harvest and analyze live MERID metrics")
    parser.add_argument("--log-file", default="logs/agent_runs.jsonl", help="Agent runs log file")
    parser.add_argument("--days-back", type=int, default=7, help="Days to look back")
    parser.add_argument("--output", help="Output JSON file for analysis results")
    parser.add_argument("--version", help="Filter by agent version")
    parser.add_argument("--category", help="Filter by category")
    
    args = parser.parse_args()
    
    print("🌾 MERID Live Metrics Harvester")
    print("=" * 50)
    
    # Load runs
    runs = load_runs(args.log_file, args.days_back)
    
    # Filter if specified
    if args.version:
        runs = [r for r in runs if r.get('agent_version') == args.version]
    if args.category:
        runs = [r for r in runs if args.category in r.get('filters', {}).get('categories', [])]
    
    print(f"📊 Analyzing {len(runs)} runs from last {args.days_back} days")
    
    if not runs:
        print("❌ No runs found matching criteria")
        return
    
    # Run analyses
    analysis = {
        'timestamp': datetime.now().isoformat(),
        'period_days': args.days_back,
        'total_runs': len(runs),
        'brier_trends': analyze_brier_trends(runs),
        'latency_envelopes': analyze_latency_envelopes(runs),
        'bucket_calibration': analyze_bucket_calibration(runs),
        'failure_modes': analyze_failure_modes(runs),
        'recommendations': []
    }
    
    # Generate recommendations
    analysis['recommendations'] = generate_recommendations(analysis)
    
    # Print summary
    print(f"\n📈 Key Metrics:")
    print(f"  Total Runs: {analysis['total_runs']}")
    print(f"  Success Rate: {analysis['failure_modes']['success_rate']:.1%}")
    
    if analysis['brier_trends']['by_version']:
        best_version = min(analysis['brier_trends']['by_version'].items(), 
                          key=lambda x: x[1]['mean_brier'])
        print(f"  Best Version: {best_version[0]} (Brier: {best_version[1]['mean_brier']:.4f})")
    
    if 'percentiles' in analysis['latency_envelopes']:
        p95 = analysis['latency_envelopes']['percentiles']['p95']
        print(f"  P95 Latency: {p95:.0f}ms")
    
    print(f"\n🎯 Recommendations:")
    for rec in analysis['recommendations']:
        print(f"  {rec}")
    
    # Save results
    if args.output:
        with Path(args.output).open('w') as f:
            json.dump(analysis, f, indent=2, default=str)
        print(f"\n💾 Analysis saved to: {args.output}")


if __name__ == "__main__":
    main()
