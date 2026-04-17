"""
MERID Swarm Baseline Test Suite
Runs representative tasks to establish baseline resilience metrics.
"""

import time
import json
from typing import Dict, List, Any
from dataclasses import dataclass
from swarm.integration.task_runner import task_runner, TaskMetrics
from utils.logger import get_logger

logger = get_logger("swarm.baseline_tests")


@dataclass
class TaskDefinition:
    """Definition for a baseline test task"""
    task_id: str
    task_type: str
    complexity: str
    agents: List[Dict[str, Any]]
    expected_duration: float
    risk_level: str


class BaselineTestSuite:
    """Baseline test suite for swarm resilience measurement"""
    
    def __init__(self):
        self.tasks = self._create_task_matrix()
        self.results: List[TaskMetrics] = []
        
        logger.info(f"Baseline test suite initialized with {len(self.tasks)} tasks")
    
    def _create_task_matrix(self) -> List[TaskDefinition]:
        """Create the 46-task matrix as specified in the reliability plan"""
        tasks = []
        
        # Code Analysis Tasks (10)
        for i in range(10):
            tasks.append(TaskDefinition(
                task_id=f"code_analysis_{i}",
                task_type="code_analysis",
                complexity="low",
                agents=[
                    {"id": f"planner_{i}", "role": "planner", "tools": ["repo_search", "file_read"]},
                    {"id": f"analyzer_{i}", "role": "analyzer", "tools": ["linting", "security_scan"]},
                    {"id": f"reviewer_{i}", "role": "reviewer", "tools": ["file_read"]},
                    {"id": f"reporter_{i}", "role": "reporter", "tools": ["file_write"]}
                ],
                expected_duration=30.0,
                risk_level="low"
            ))
        
        # Trading Operations Tasks (8)
        for i in range(8):
            tasks.append(TaskDefinition(
                task_id=f"trading_{i}",
                task_type="trading",
                complexity="medium",
                agents=[
                    {"id": f"trader_{i}", "role": "trader", "tools": ["market_data", "price_analysis"]},
                    {"id": f"risk_manager_{i}", "role": "risk_manager", "tools": ["position_calculator", "risk_checker"]},
                    {"id": f"executor_{i}", "role": "executor", "tools": ["order_placement", "portfolio_update"]},
                    {"id": f"monitor_{i}", "role": "monitor", "tools": ["position_tracker", "alert_system"]}
                ],
                expected_duration=45.0,
                risk_level="medium"
            ))
        
        # Risk Management Tasks (6)
        for i in range(6):
            tasks.append(TaskDefinition(
                task_id=f"risk_mgmt_{i}",
                task_type="risk_management",
                complexity="high",
                agents=[
                    {"id": f"risk_analyzer_{i}", "role": "risk_analyzer", "tools": ["portfolio_scan", "var_calculator"]},
                    {"id": f"liquidation_monitor_{i}", "role": "liquidation_monitor", "tools": ["liquidation_scanner", "cascade_detector"]},
                    {"id": f"hedge_manager_{i}", "role": "hedge_manager", "tools": ["hedge_calculator", "derivative_pricer"]},
                    {"id": f"reporter_{i}", "role": "reporter", "tools": ["risk_report", "alert_generator"]}
                ],
                expected_duration=60.0,
                risk_level="high"
            ))
        
        # Data Processing Tasks (5)
        for i in range(5):
            tasks.append(TaskDefinition(
                task_id=f"data_processing_{i}",
                task_type="data_processing",
                complexity="low",
                agents=[
                    {"id": f"collector_{i}", "role": "collector", "tools": ["data_fetcher", "validator"]},
                    {"id": f"processor_{i}", "role": "processor", "tools": ["data_cleaner", "transformer"]},
                    {"id": f"analyzer_{i}", "role": "analyzer", "tools": ["statistical_analyzer", "pattern_detector"]},
                    {"id": f"storage_{i}", "role": "storage", "tools": ["database_writer", "cache_updater"]}
                ],
                expected_duration=25.0,
                risk_level="low"
            ))
        
        # Governance Tasks (4)
        for i in range(4):
            tasks.append(TaskDefinition(
                task_id=f"governance_{i}",
                task_type="governance",
                complexity="medium",
                agents=[
                    {"id": f"governor_{i}", "role": "governor", "tools": ["policy_checker", "compliance_validator"]},
                    {"id": f"auditor_{i}", "role": "auditor", "tools": ["audit_trail", "compliance_report"]},
                    {"id": f"approver_{i}", "role": "approver", "tools": ["approval_workflow", "sign_off"]},
                    {"id": f"recorder_{i}", "role": "recorder", "tools": ["record_keeper", "documentation"]}
                ],
                expected_duration=35.0,
                risk_level="medium"
            ))
        
        # Experimental Tasks (3)
        for i in range(3):
            tasks.append(TaskDefinition(
                task_id=f"experimental_{i}",
                task_type="experimental",
                complexity="variable",
                agents=[
                    {"id": f"experimenter_{i}", "role": "experimenter", "tools": ["feature_tester", "ab_tester"]},
                    {"id": f"monitor_{i}", "role": "monitor", "tools": ["performance_monitor", "error_tracker"]},
                    {"id": f"analyzer_{i}", "role": "analyzer", "tools": ["result_analyzer", "statistical_tester"]},
                    {"id": f"decider_{i}", "role": "decider", "tools": ["decision_maker", "recommendation_engine"]}
                ],
                expected_duration=40.0,
                risk_level="variable"
            ))
        
        return tasks
    
    def run_baseline_tests(self) -> Dict[str, Any]:
        """Run all baseline tests and collect metrics"""
        logger.info("Starting baseline test suite execution")
        
        start_time = time.time()
        self.results = []
        
        for i, task in enumerate(self.tasks):
            logger.info(f"Running task {i+1}/{len(self.tasks)}: {task.task_id}")
            
            try:
                # Convert task definition to task config
                task_config = {
                    "type": task.task_type,
                    "complexity": task.complexity,
                    "agents": task.agents
                }
                
                # Execute task with tracing and monitoring
                metrics = task_runner.execute_task(task_config)
                self.results.append(metrics)
                
                logger.info(f"Task {task.task_id} completed - success: {metrics.success}")
                
            except Exception as e:
                logger.error(f"Task {task.task_id} failed: {e}")
                # Create failure metrics
                failure_metrics = TaskMetrics(
                    task_id=task.task_id,
                    start_time=time.time(),
                    end_time=time.time(),
                    success=False
                )
                self.results.append(failure_metrics)
        
        end_time = time.time()
        total_duration = end_time - start_time
        
        # Calculate aggregate metrics
        aggregate_metrics = self._calculate_aggregate_metrics(total_duration)
        
        logger.info(f"Baseline test suite completed in {total_duration:.2f}s")
        
        return aggregate_metrics
    
    def run_fault_injection_tests(self, fault_modes: List[str]) -> Dict[str, Any]:
        """Run tests with fault injection"""
        logger.info(f"Starting fault injection tests with modes: {fault_modes}")
        
        fault_results = {}
        
        for fault_mode in fault_modes:
            logger.info(f"Running fault injection mode: {fault_mode}")
            
            # Configure fault injection
            if fault_mode == "flaky_tool":
                task_runner.enable_fault_injection(flaky_tool_rate=0.15)
            elif fault_mode == "degraded_agent":
                # Simulate degraded agent by reducing capacity
                task_runner.enable_fault_injection(flaky_tool_rate=0.05)
            elif fault_mode == "limited_capacity":
                task_runner.enable_fault_injection(flaky_tool_rate=0.25)
            else:
                logger.warning(f"Unknown fault mode: {fault_mode}")
                continue
            
            # Run a subset of tasks for fault injection
            fault_tasks = self.tasks[:15]  # First 15 tasks
            fault_mode_results = []
            
            for task in fault_tasks:
                try:
                    task_config = {
                        "type": task.task_type,
                        "complexity": task.complexity,
                        "agents": task.agents
                    }
                    
                    metrics = task_runner.execute_task(task_config)
                    fault_mode_results.append(metrics)
                    
                except Exception as e:
                    logger.error(f"Fault injection task {task.task_id} failed: {e}")
                    failure_metrics = TaskMetrics(
                        task_id=task.task_id,
                        start_time=time.time(),
                        end_time=time.time(),
                        success=False
                    )
                    fault_mode_results.append(failure_metrics)
            
            fault_results[fault_mode] = fault_mode_results
            
            # Clean up fault injection
            task_runner.disable_fault_injection()
        
        return fault_results
    
    def _calculate_aggregate_metrics(self, total_duration: float) -> Dict[str, Any]:
        """Calculate aggregate metrics from all test results"""
        if not self.results:
            return {"error": "No results to aggregate"}
        
        # Basic success metrics
        total_tasks = len(self.results)
        successful_tasks = sum(1 for r in self.results if r.success)
        success_rate = successful_tasks / total_tasks
        
        # Cascade metrics
        cascade_sizes = [r.cascade_size for r in self.results]
        cascade_depths = [r.cascade_depth for r in self.results]
        branching_factors = [r.branching_factor for r in self.results]
        
        avg_cascade_size = sum(cascade_sizes) / len(cascade_sizes) if cascade_sizes else 0
        avg_cascade_depth = sum(cascade_depths) / len(cascade_depths) if cascade_depths else 0
        avg_branching_factor = sum(branching_factors) / len(branching_factors) if branching_factors else 0
        
        # Retry and intervention metrics
        retry_indices = [r.retry_index for r in self.results]
        human_interventions = [r.human_intervention_count for r in self.results]
        
        avg_retry_index = sum(retry_indices) / len(retry_indices) if retry_indices else 0
        total_interventions = sum(human_interventions)
        
        # Misalignment metrics
        all_misalignment_scores = []
        for r in self.results:
            all_misalignment_scores.extend(r.misalignment_scores.values())
        
        avg_misalignment = sum(all_misalignment_scores) / len(all_misalignment_scores) if all_misalignment_scores else 0
        
        # Performance metrics
        total_turns = sum(r.total_turns for r in self.results)
        total_tokens = sum(r.total_tokens for r in self.results)
        avg_turns_per_task = total_turns / total_tasks
        avg_tokens_per_task = total_tokens / total_tasks
        
        # Topology analysis
        topology_behavior = self._analyze_topology_behavior(avg_cascade_size, avg_branching_factor)
        
        return {
            "test_summary": {
                "total_tasks": total_tasks,
                "successful_tasks": successful_tasks,
                "success_rate": success_rate,
                "total_duration_seconds": total_duration,
                "avg_duration_per_task": total_duration / total_tasks
            },
            "cascade_metrics": {
                "avg_cascade_size": avg_cascade_size,
                "avg_cascade_depth": avg_cascade_depth,
                "avg_branching_factor": avg_branching_factor,
                "max_cascade_size": max(cascade_sizes) if cascade_sizes else 0,
                "max_cascade_depth": max(cascade_depths) if cascade_depths else 0
            },
            "operational_metrics": {
                "avg_retry_index": avg_retry_index,
                "total_human_interventions": total_interventions,
                "avg_turns_per_task": avg_turns_per_task,
                "avg_tokens_per_task": avg_tokens_per_task
            },
            "misalignment_metrics": {
                "avg_misalignment_score": avg_misalignment,
                "total_agent_pairs": len(all_misalignment_scores),
                "max_misalignment": max(all_misalignment_scores) if all_misalignment_scores else 0
            },
            "topology_analysis": {
                "behavior_pattern": topology_behavior,
                "resilience_characteristics": self._get_resilience_characteristics(avg_cascade_size, avg_branching_factor, success_rate)
            },
            "recommendations": self._generate_recommendations(success_rate, avg_cascade_size, avg_branching_factor, avg_misalignment)
        }
    
    def _analyze_topology_behavior(self, avg_cascade_size: float, avg_branching_factor: float) -> str:
        """Analyze whether behavior is ring-like or mesh-like"""
        if avg_cascade_size <= 2 and avg_branching_factor < 1.2:
            return "ring_like_local_failures"
        elif avg_cascade_size > 5 and avg_branching_factor > 1.5:
            return "mesh_like_wide_cascades"
        else:
            return "hybrid_mixed_behavior"
    
    def _get_resilience_characteristics(self, cascade_size: float, branching_factor: float, success_rate: float) -> str:
        """Get resilience characteristics description"""
        if success_rate > 0.8 and cascade_size < 2:
            return "high_resilience_local_failures"
        elif success_rate > 0.6 and cascade_size < 5:
            return "moderate_resilience_contained_cascades"
        elif success_rate > 0.4:
            return "low_resilience_frequent_cascades"
        else:
            return "very_low_resilience_systemic_failures"
    
    def _generate_recommendations(self, success_rate: float, cascade_size: float, 
                                branching_factor: float, misalignment: float) -> List[str]:
        """Generate recommendations based on metrics"""
        recommendations = []
        
        if success_rate < 0.6:
            recommendations.append("Consider improving error handling and retry mechanisms")
        
        if cascade_size > 3:
            recommendations.append("Implement better failure containment to reduce cascade propagation")
        
        if branching_factor > 1.3:
            recommendations.append("Review agent communication patterns to reduce branching")
        
        if misalignment > 0.7:
            recommendations.append("Address agent state misalignment through better coordination")
        
        if success_rate > 0.8 and cascade_size < 2:
            recommendations.append("Current topology performs well - focus on optimization")
        
        if not recommendations:
            recommendations.append("System shows good resilience - continue monitoring")
        
        return recommendations
    
    def export_results(self, filename: str = "baseline_results.json"):
        """Export results to JSON file"""
        results_data = {
            "timestamp": time.time(),
            "aggregate_metrics": self._calculate_aggregate_metrics(time.time()),
            "individual_results": [
                {
                    "task_id": r.task_id,
                    "success": r.success,
                    "duration": (r.end_time or 0) - r.start_time,
                    "cascade_size": r.cascade_size,
                    "cascade_depth": r.cascade_depth,
                    "branching_factor": r.branching_factor,
                    "retry_index": r.retry_index,
                    "misalignment_scores": r.misalignment_scores,
                    "total_turns": r.total_turns,
                    "total_tokens": r.total_tokens
                }
                for r in self.results
            ]
        }
        
        with open(filename, 'w') as f:
            json.dump(results_data, f, indent=2)
        
        logger.info(f"Results exported to {filename}")


# Global test suite instance
baseline_suite = BaselineTestSuite()
