#!/usr/bin/env python3
"""
Log Analysis Tools for MERID Agent Performance

Provides utilities to analyze agent run logs and extract insights
about prompt performance, calibration, and operational metrics.
"""

import json
import statistics
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timezone
import argparse

class AgentLogAnalyzer:
    """Analyzes structured agent run logs."""
    
    def __init__(self, log_file: str = "logs/agent_runs.jsonl"):
        self.log_file = Path(log_file)
        self.logs = []
        self.load_logs()
    
    def load_logs(self):
        """Load all logs from file."""
        if not self.log_file.exists():
            print(f"❌ Log file not found: {self.log_file}")
            return
        
        print(f"📂 Loading logs from {self.log_file}")
        
        with self.log_file.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    log_entry = json.loads(line.strip())
                    self.logs.append(log_entry)
                except json.JSONDecodeError as e:
                    print(f"⚠️  Skipping malformed line {line_num}: {e}")
                    continue
        
        print(f"✅ Loaded {len(self.logs)} log entries")
    
    def filter_logs(self, **filters) -> List[Dict[str, Any]]:
        """Filter logs by specified criteria."""
        filtered = self.logs
        
        for key, value in filters.items():
            if key == "experiment_id":
                filtered = [log for log in filtered if log.get("experiment_id") == value]
            elif key == "agent_version":
                filtered = [log for log in filtered if log.get("agent_version") == value]
            elif key == "run_type":
                filtered = [log for log in filtered if log.get("run_type") == value]
            elif key == "status":
                filtered = [log for log in filtered if log.get("status") == value]
            elif key == "time_range_days":
                # Filter logs from last N days
                cutoff_time = datetime.now(timezone.utc).timestamp() - (value * 24 * 3600)
                filtered = [log for log in filtered if log.get("timestamp", 0) > cutoff_time]
        
        return filtered
    
    def analyze_prompt_experiment(self, experiment_id: str) -> Dict[str, Any]:
        """Analyze results of a specific prompt experiment."""
        experiment_logs = self.filter_logs(experiment_id=experiment_id)
        
        if not experiment_logs:
            return {"error": f"No logs found for experiment {experiment_id}"}
        
        # Group by agent version (prompt variant)
        variants = {}
        for log in experiment_logs:
            version = log.get("agent_version", "unknown")
            if version not in variants:
                variants[version] = []
            variants[version].append(log)
        
        analysis = {
            "experiment_id": experiment_id,
            "total_runs": len(experiment_logs),
            "variants": len(variants),
            "variant_analysis": {}
        }
        
        # Analyze each variant
        for version, logs in variants.items():
            variant_analysis = self._analyze_variant_logs(version, logs)
            analysis["variant_analysis"][version] = variant_analysis
        
        # Find winner
        best_variant = None
        best_brier = float('inf')
        
        for version, variant_data in analysis["variant_analysis"].items():
            avg_brier = variant_data.get("avg_brier_score")
            if avg_brier is not None and avg_brier < best_brier:
                best_brier = avg_brier
                best_variant = version
        
        if best_variant:
            analysis["winner"] = {
                "variant": best_variant,
                "avg_brier_score": best_brier
            }
        
        return analysis
    
    def _analyze_variant_logs(self, version: str, logs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze logs for a single variant."""
        successful_logs = [log for log in logs if log.get("status") == "success"]
        
        # Brier scores
        brier_scores = [log["brier_score"] for log in successful_logs if log.get("brier_score") is not None]
        
        # Latency
        latencies = [log["latency_ms"] for log in logs if log.get("latency_ms") is not None]
        
        # Bucket analysis
        bucket_distributions = {}
        for log in successful_logs:
            bucket_stats = log.get("bucket_stats", [])
            for bucket in bucket_stats:
                bucket_range = bucket.get("bucket_range", "")
                count = bucket.get("count", 0)
                if bucket_range not in bucket_distributions:
                    bucket_distributions[bucket_range] = []
                bucket_distributions[bucket_range].append(count)
        
        # Calculate statistics
        analysis = {
            "total_runs": len(logs),
            "successful_runs": len(successful_logs),
            "success_rate": len(successful_logs) / len(logs) if logs else 0,
            "avg_brier_score": statistics.mean(brier_scores) if brier_scores else None,
            "brier_score_std": statistics.stdev(brier_scores) if len(brier_scores) > 1 else None,
            "avg_latency_ms": statistics.mean(latencies) if latencies else None,
            "latency_std": statistics.stdev(latencies) if len(latencies) > 1 else None,
            "bucket_distribution": {}
        }
        
        # Bucket distribution statistics
        for bucket_range, counts in bucket_distributions.items():
            analysis["bucket_distribution"][bucket_range] = {
                "avg_count": statistics.mean(counts),
                "total_count": sum(counts)
            }
        
        return analysis
    
    def analyze_calibration_trends(self, days: int = 7) -> Dict[str, Any]:
        """Analyze calibration trends over time."""
        recent_logs = self.filter_logs(time_range_days=days)
        
        if not recent_logs:
            return {"error": f"No logs found in last {days} days"}
        
        # Group by day
        daily_stats = {}
        
        for log in recent_logs:
            if log.get("status") != "success" or log.get("brier_score") is None:
                continue
            
            timestamp = log.get("timestamp", 0)
            date = datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d")
            
            if date not in daily_stats:
                daily_stats[date] = {"brier_scores": [], "latencies": []}
            
            daily_stats[date]["brier_scores"].append(log["brier_score"])
            daily_stats[date]["latencies"].append(log.get("latency_ms", 0))
        
        # Calculate daily averages
        trend_data = []
        for date, stats in sorted(daily_stats.items()):
            avg_brier = statistics.mean(stats["brier_scores"]) if stats["brier_scores"] else None
            avg_latency = statistics.mean(stats["latencies"]) if stats["latencies"] else None
            
            trend_data.append({
                "date": date,
                "avg_brier_score": avg_brier,
                "run_count": len(stats["brier_scores"]),
                "avg_latency_ms": avg_latency
            })
        
        # Calculate overall trend
        if len(trend_data) >= 2:
            first_brier = trend_data[0]["avg_brier_score"]
            last_brier = trend_data[-1]["avg_brier_score"]
            if first_brier and last_brier:
                trend_direction = "improving" if last_brier < first_brier else "degrading"
                trend_change = ((last_brier - first_brier) / first_brier) * 100
            else:
                trend_direction = "unknown"
                trend_change = 0
        else:
            trend_direction = "insufficient_data"
            trend_change = 0
        
        return {
            "period_days": days,
            "total_runs": len(recent_logs),
            "daily_data": trend_data,
            "trend_direction": trend_direction,
            "trend_change_percent": trend_change
        }
    
    def analyze_operational_health(self, days: int = 1) -> Dict[str, Any]:
        """Analyze operational health metrics."""
        recent_logs = self.filter_logs(time_range_days=days)
        
        if not recent_logs:
            return {"error": f"No logs found in last {days} days"}
        
        # Status distribution
        status_counts = {}
        for log in recent_logs:
            status = log.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        
        # Latency analysis
        latencies = [log["latency_ms"] for log in recent_logs if log.get("latency_ms") is not None]
        
        # Error analysis
        error_logs = [log for log in recent_logs if log.get("status") != "success"]
        
        health_analysis = {
            "period_days": days,
            "total_runs": len(recent_logs),
            "status_distribution": status_counts,
            "success_rate": status_counts.get("success", 0) / len(recent_logs),
            "avg_latency_ms": statistics.mean(latencies) if latencies else None,
            "p95_latency_ms": sorted(latencies)[int(len(latencies) * 0.95)] if latencies else None,
            "error_count": len(error_logs),
            "error_rate": len(error_logs) / len(recent_logs),
            "common_errors": {}
        }
        
        # Analyze common errors
        error_types = {}
        for log in error_logs:
            error_type = log.get("error_type", "unknown")
            error_types[error_type] = error_types.get(error_type, 0) + 1
        
        health_analysis["common_errors"] = error_types
        
        return health_analysis
    
    def export_analysis(self, output_file: str):
        """Export all analyses to JSON file."""
        analyses = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_logs": len(self.logs),
            "prompt_experiments": {},
            "calibration_trends": self.analyze_calibration_trends(),
            "operational_health": self.analyze_operational_health()
        }
        
        # Analyze all experiments
        experiment_ids = set(log.get("experiment_id") for log in self.logs if log.get("experiment_id"))
        for exp_id in experiment_ids:
            analyses["prompt_experiments"][exp_id] = self.analyze_prompt_experiment(exp_id)
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(analyses, f, indent=2, default=str)
        
        print(f"📊 Analysis exported to {output_file}")

def main():
    """Command line interface for log analysis."""
    parser = argparse.ArgumentParser(description="Analyze MERID agent logs")
    parser.add_argument("--experiment", help="Analyze specific experiment ID")
    parser.add_argument("--trends", type=int, default=7, help="Analyze calibration trends over N days")
    parser.add_argument("--health", type=int, default=1, help="Analyze operational health over N days")
    parser.add_argument("--export", help="Export analysis to JSON file")
    parser.add_argument("--log-file", default="logs/agent_runs.jsonl", help="Path to log file")
    
    args = parser.parse_args()
    
    analyzer = AgentLogAnalyzer(args.log_file)
    
    if args.experiment:
        print(f"\n🔬 Analyzing Experiment: {args.experiment}")
        analysis = analyzer.analyze_prompt_experiment(args.experiment)
        print(json.dumps(analysis, indent=2, default=str))
    
    if args.trends:
        print(f"\n📈 Calibration Trends ({args.trends} days)")
        trends = analyzer.analyze_calibration_trends(args.trends)
        print(json.dumps(trends, indent=2, default=str))
    
    if args.health:
        print(f"\n🏥 Operational Health ({args.health} days)")
        health = analyzer.analyze_operational_health(args.health)
        print(json.dumps(health, indent=2, default=str))
    
    if args.export:
        analyzer.export_analysis(args.export)

if __name__ == "__main__":
    main()
