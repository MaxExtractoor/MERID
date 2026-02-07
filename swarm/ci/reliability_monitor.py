"""
MERID Swarm CI Reliability Monitor
Continuous reliability monitoring for CI/CD pipeline integration.
"""

import os
import sys
import json
import time
import argparse
from typing import Dict, List, Any
from pathlib import Path

# Add swarm modules to path
sys.path.append(str(Path(__file__).parent.parent))

from swarm.testing.baseline_suite import baseline_suite
from swarm.integration.task_runner import task_runner
from utils.logger import get_logger

logger = get_logger("swarm.ci_monitor")


class CIReliabilityMonitor:
    """CI reliability monitor for continuous swarm health checking"""
    
    def __init__(self):
        self.thresholds = self._load_thresholds()
        
        # CI-specific task subset (5-10 synthetic tasks)
        self.ci_tasks = self._create_ci_task_subset()
        
        logger.info("CI Reliability Monitor initialized")
    
    def _create_ci_task_subset(self) -> List[Dict[str, Any]]:
        """Create small subset of synthetic tasks for CI"""
        return [
            {
                "type": "code_analysis",
                "complexity": "low",
                "agents": [
                    {"id": "ci_planner", "role": "planner", "tools": ["repo_search"]},
                    {"id": "ci_analyzer", "role": "analyzer", "tools": ["linting"]},
                    {"id": "ci_reviewer", "role": "reviewer", "tools": ["file_read"]}
                ]
            },
            {
                "type": "data_processing",
                "complexity": "low", 
                "agents": [
                    {"id": "ci_collector", "role": "collector", "tools": ["data_fetcher"]},
                    {"id": "ci_processor", "role": "processor", "tools": ["data_cleaner"]},
                    {"id": "ci_analyzer", "role": "analyzer", "tools": ["statistical_analyzer"]}
                ]
            },
            {
                "type": "trading",
                "complexity": "medium",
                "agents": [
                    {"id": "ci_trader", "role": "trader", "tools": ["market_data"]},
                    {"id": "ci_risk", "role": "risk_manager", "tools": ["risk_checker"]},
                    {"id": "ci_executor", "role": "executor", "tools": ["order_placement"]}
                ]
            },
            {
                "type": "governance",
                "complexity": "medium",
                "agents": [
                    {"id": "ci_governor", "role": "governor", "tools": ["policy_checker"]},
                    {"id": "ci_auditor", "role": "auditor", "tools": ["audit_trail"]},
                    {"id": "ci_approver", "role": "approver", "tools": ["approval_workflow"]}
                ]
            },
            {
                "type": "experimental",
                "complexity": "variable",
                "agents": [
                    {"id": "ci_experimenter", "role": "experimenter", "tools": ["feature_tester"]},
                    {"id": "ci_monitor", "role": "monitor", "tools": ["performance_monitor"]},
                    {"id": "ci_analyzer", "role": "analyzer", "tools": ["result_analyzer"]}
                ]
            }
        ]
    
    def run_ci_checks(self, output_file: str = "ci_reliability_report.json") -> bool:
        """Run CI reliability checks and return pass/fail status"""
        logger.info("Starting CI reliability checks")
        
        start_time = time.time()
        results = []
        
        # Run each CI task
        for i, task_config in enumerate(self.ci_tasks):
            logger.info(f"Running CI task {i+1}/{len(self.ci_tasks)}: {task_config['type']}")
            
            try:
                metrics = task_runner.execute_task(task_config)
                results.append(metrics)
                logger.info(f"CI task {task_config['type']} completed - success: {metrics.success}")
                
            except Exception as e:
                logger.error(f"CI task {task_config['type']} failed: {e}")
                # Create failure metrics
                failure_metrics = type('obj', (object,), {
                    'task_id': f"ci_task_{i}",
                    'success': False,
                    'cascade_size': 0,
                    'cascade_depth': 0,
                    'branching_factor': 0.0,
                    'retry_index': 0.0,
                    'misalignment_scores': {},
                    'total_turns': 0,
                    'total_tokens': 0
                })()
                results.append(failure_metrics)
        
        end_time = time.time()
        
        # Calculate CI metrics
        ci_metrics = self._calculate_ci_metrics(results, end_time - start_time)
        
        # Check against thresholds
        passed = self._check_thresholds(ci_metrics)
        
        # Generate report
        report = {
            "timestamp": time.time(),
            "duration_seconds": end_time - start_time,
            "passed": passed,
            "metrics": ci_metrics,
            "thresholds": self.thresholds,
            "individual_results": [
                {
                    "task_type": self.ci_tasks[i]["type"],
                    "success": r.success,
                    "cascade_size": r.cascade_size,
                    "branching_factor": r.branching_factor,
                    "misalignment_avg": sum(r.misalignment_scores.values()) / len(r.misalignment_scores) if r.misalignment_scores else 0
                }
                for i, r in enumerate(results)
            ]
        }
        
        # Save report
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"CI reliability check completed - {'PASSED' if passed else 'FAILED'}")
        logger.info("Threshold summary:")
        logger.info("  • Configured misalignment cap: %.3f", self.thresholds["max_misalignment"])
        logger.info("  • Observed avg misalignment: %.3f", ci_metrics.get("avg_misalignment", 0.0))
        logger.info(f"Report saved to {output_file}")
        
        return passed
    
    def _calculate_ci_metrics(self, results: List[Any], duration: float) -> Dict[str, Any]:
        """Calculate metrics for CI run"""
        if not results:
            return {"error": "No results to calculate"}
        
        total_tasks = len(results)
        successful_tasks = sum(1 for r in results if r.success)
        success_rate = successful_tasks / total_tasks
        
        # Aggregate cascade metrics
        cascade_sizes = [r.cascade_size for r in results]
        branching_factors = [r.branching_factor for r in results]
        retry_indices = [r.retry_index for r in results]
        
        avg_cascade_size = sum(cascade_sizes) / len(cascade_sizes) if cascade_sizes else 0
        avg_branching_factor = sum(branching_factors) / len(branching_factors) if branching_factors else 0
        avg_retry_index = sum(retry_indices) / len(retry_indices) if retry_indices else 0
        
        # Aggregate misalignment
        all_misalignment_scores = []
        for r in results:
            all_misalignment_scores.extend(r.misalignment_scores.values())
        
        avg_misalignment = sum(all_misalignment_scores) / len(all_misalignment_scores) if all_misalignment_scores else 0
        
        return {
            "total_tasks": total_tasks,
            "successful_tasks": successful_tasks,
            "success_rate": success_rate,
            "duration_seconds": duration,
            "avg_cascade_size": avg_cascade_size,
            "avg_branching_factor": avg_branching_factor,
            "avg_retry_index": avg_retry_index,
            "avg_misalignment": avg_misalignment,
            "max_cascade_size": max(cascade_sizes) if cascade_sizes else 0,
            "max_branching_factor": max(branching_factors) if branching_factors else 0
        }
    
    def _check_thresholds(self, metrics: Dict[str, Any]) -> bool:
        """Check metrics against thresholds"""
        violations = []
        
        if metrics["success_rate"] < self.thresholds["min_success_rate"]:
            violations.append(f"Success rate {metrics['success_rate']:.3f} < {self.thresholds['min_success_rate']}")
        
        if metrics["avg_cascade_size"] > self.thresholds["max_cascade_size"]:
            violations.append(f"Avg cascade size {metrics['avg_cascade_size']:.3f} > {self.thresholds['max_cascade_size']}")
        
        if metrics["avg_branching_factor"] > self.thresholds["max_branching_factor"]:
            violations.append(f"Avg branching factor {metrics['avg_branching_factor']:.3f} > {self.thresholds['max_branching_factor']}")
        
        if metrics["avg_misalignment"] > self.thresholds["max_misalignment"]:
            violations.append(f"Avg misalignment {metrics['avg_misalignment']:.3f} > {self.thresholds['max_misalignment']}")
        
        if metrics["avg_retry_index"] > self.thresholds["max_retry_index"]:
            violations.append(f"Avg retry index {metrics['avg_retry_index']:.3f} > {self.thresholds['max_retry_index']}")
        
        if violations:
            logger.error(f"CI reliability check FAILED with violations:")
            for violation in violations:
                logger.error(f"  - {violation}")
            return False
        else:
            logger.info("CI reliability check PASSED - all metrics within thresholds")
            return True
    
    def update_thresholds(self, new_thresholds: Dict[str, float]):
        """Update threshold values"""
        self.thresholds.update(new_thresholds)
        logger.info(f"Updated thresholds: {self.thresholds}")
    
    def get_current_thresholds(self) -> Dict[str, float]:
        """Get current threshold values"""
        return self.thresholds.copy()

    def _load_thresholds(self) -> Dict[str, float]:
        """Load thresholds from external config if available"""
        default_thresholds = {
            "min_success_rate": 0.8,
            "max_cascade_size": 3.0,
            "max_branching_factor": 1.3,
            "max_misalignment": 0.7,
            "max_retry_index": 2.0
        }

        config_path = Path("week5_slo_config.json")
        if config_path.exists():
            try:
                with config_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                logger.info("Loaded SLO thresholds from %s", config_path)
                return {
                    "min_success_rate": data.get("success_rate", default_thresholds["min_success_rate"]),
                    "max_cascade_size": data.get("avg_cascade_size", default_thresholds["max_cascade_size"]),
                    "max_branching_factor": data.get("avg_branching_factor", default_thresholds["max_branching_factor"]),
                    "max_misalignment": data.get("avg_misalignment", default_thresholds["max_misalignment"]),
                    "max_retry_index": data.get("avg_retry_index", default_thresholds["max_retry_index"])
                }
            except Exception as exc:
                logger.error("Failed to load %s: %s", config_path, exc)

        return default_thresholds


def main():
    """Main entry point for CI script"""
    parser = argparse.ArgumentParser(description="MERID Swarm CI Reliability Monitor")
    parser.add_argument("--output", default="ci_reliability_report.json", 
                       help="Output file for reliability report")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--update-thresholds", help="Update thresholds (JSON format)")
    
    args = parser.parse_args()
    
    if args.verbose:
        import logging
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Initialize monitor
    monitor = CIReliabilityMonitor()
    
    # Update thresholds if provided
    if args.update_thresholds:
        try:
            new_thresholds = json.loads(args.update_thresholds)
            monitor.update_thresholds(new_thresholds)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid thresholds JSON: {e}")
            return 1
    
    # Run CI checks
    try:
        passed = monitor.run_ci_checks(args.output)
        
        # Exit with appropriate code
        sys.exit(0 if passed else 1)
        
    except Exception as e:
        logger.error(f"CI reliability check failed with error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
