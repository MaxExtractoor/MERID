#!/usr/bin/env python3
"""
Advanced stress testing for MERID swarm resilience
Combines multiple fault types and realistic task scenarios
"""

import sys
import os
sys.path.append('.')
sys.path.append('swarm')

from swarm.testing.baseline_suite import baseline_suite
from swarm.integration.task_runner import task_runner
from utils.logger import get_logger

logger = get_logger("swarm.stress_testing")

class AdvancedStressTest:
    """Advanced stress testing with combined fault scenarios"""
    
    def __init__(self):
        self.baseline_suite = baseline_suite
        
    def create_realistic_task_matrix(self) -> list:
        """Create more realistic, "ugly" task scenarios"""
        tasks = []
        
        # Cross-cutting refactor tasks (high complexity)
        for i in range(5):
            tasks.append({
                "task_id": f"cross_cutting_refactor_{i}",
                "task_type": "refactor",
                "complexity": "high",
                "agents": [
                    {"id": f"architect_{i}", "role": "architect", "tools": ["dependency_analyzer", "impact_assessor"]},
                    {"id": f"planner_{i}", "role": "planner", "tools": ["refactor_planner", "migration_planner"]},
                    {"id": f"implementer_{i}", "role": "implementer", "tools": ["code_generator", "test_generator"]},
                    {"id": f"validator_{i}", "role": "validator", "tools": ["integration_tester", "regression_checker"]},
                    {"id": f"deployer_{i}", "role": "deployer", "tools": ["canary_deployer", "rollback_manager"]}
                ],
                "expected_duration": 120.0,
                "risk_level": "high"
            })
        
        # Infrastructure change tasks
        for i in range(4):
            tasks.append({
                "task_id": f"infra_change_{i}",
                "task_type": "infrastructure",
                "complexity": "high",
                "agents": [
                    {"id": f"infra_planner_{i}", "role": "planner", "tools": ["infra_designer", "capacity_planner"]},
                    {"id": f"config_manager_{i}", "role": "config_manager", "tools": ["config_validator", "secret_manager"]},
                    {"id": f"deploy_engineer_{i}", "role": "deployer", "tools": ["terraform_runner", "k8s_deployer"]},
                    {"id": f"monitor_{i}", "role": "monitor", "tools": ["health_checker", "metrics_collector"]}
                ],
                "expected_duration": 90.0,
                "risk_level": "high"
            })
        
        # Schema migration tasks
        for i in range(3):
            tasks.append({
                "task_id": f"schema_migration_{i}",
                "task_type": "migration",
                "complexity": "high",
                "agents": [
                    {"id": f"db_analyzer_{i}", "role": "analyzer", "tools": ["schema_analyzer", "data_profiler"]},
                    {"id": f"migration_planner_{i}", "role": "planner", "tools": ["migration_planner", "rollback_planner"]},
                    {"id": f"migrator_{i}", "role": "migrator", "tools": ["data_migrator", "schema_migrator"]},
                    {"id": f"validator_{i}", "role": "validator", "tools": ["data_validator", "consistency_checker"]}
                ],
                "expected_duration": 150.0,
                "risk_level": "critical"
            })
        
        # Multi-service integration tasks
        for i in range(3):
            tasks.append({
                "task_id": f"multi_service_{i}",
                "task_type": "integration",
                "complexity": "high",
                "agents": [
                    {"id": f"api_designer_{i}", "role": "designer", "tools": ["api_designer", "contract_generator"]},
                    {"id": f"service_dev_{i}", "role": "developer", "tools": ["microservice_builder", "api_implementer"]},
                    {"id": f"integration_tester_{i}", "role": "tester", "tools": ["contract_tester", "e2e_tester"]},
                    {"id": f"monitor_{i}", "role": "monitor", "tools": ["service_monitor", "trace_collector"]}
                ],
                "expected_duration": 100.0,
                "risk_level": "medium"
            })
        
        return tasks
    
    def run_combined_fault_scenarios(self) -> dict:
        """Run tests with combined fault scenarios"""
        logger.info("Starting combined fault scenario testing")
        
        scenarios = {
            "flaky_tools_degraded_agents": {
                "flaky_tool_rate": 0.2,
                "degraded_agent_rate": 0.15,
                "limited_capacity": False
            },
            "flaky_tools_limited_capacity": {
                "flaky_tool_rate": 0.25,
                "degraded_agent_rate": 0.0,
                "limited_capacity": True
            },
            "all_faults_combined": {
                "flaky_tool_rate": 0.15,
                "degraded_agent_rate": 0.1,
                "limited_capacity": True
            }
        }
        
        results = {}
        
        for scenario_name, config in scenarios.items():
            logger.info(f"Running scenario: {scenario_name}")
            
            # Configure fault injection
            task_runner.enable_fault_injection(flaky_tool_rate=config["flaky_tool_rate"])
            
            # Add degraded agent simulation
            if config["degraded_agent_rate"] > 0:
                task_runner._degraded_agent_rate = config["degraded_agent_rate"]
            
            # Add limited capacity simulation
            if config["limited_capacity"]:
                task_runner._limited_capacity = True
            
            # Run realistic tasks
            realistic_tasks = self.create_realistic_task_matrix()
            scenario_results = []
            
            for task_config in realistic_tasks:
                try:
                    metrics = task_runner.execute_task(task_config)
                    scenario_results.append(metrics)
                    logger.info(f"✓ {task_config['task_id']} completed")
                except Exception as e:
                    logger.error(f"✗ {task_config['task_id']} failed: {e}")
                    # Create failure metrics
                    failure_metrics = type('obj', (object,), {
                        'task_id': task_config['task_id'],
                        'success': False,
                        'cascade_size': 0,
                        'cascade_depth': 0,
                        'branching_factor': 0.0,
                        'retry_index': 0.0,
                        'misalignment_scores': {},
                        'total_turns': 0,
                        'total_tokens': 0
                    })()
                    scenario_results.append(failure_metrics)
            
            # Calculate scenario metrics
            scenario_metrics = self._calculate_scenario_metrics(scenario_results, scenario_name)
            results[scenario_name] = scenario_metrics
            
            # Clean up fault injection
            task_runner.disable_fault_injection()
            task_runner._limited_capacity = False
            if hasattr(task_runner, '_degraded_agent_rate'):
                delattr(task_runner, '_degraded_agent_rate')
        
        return results
    
    def _calculate_scenario_metrics(self, results: list, scenario_name: str) -> dict:
        """Calculate metrics for a scenario"""
        if not results:
            return {"error": "No results"}
        
        total_tasks = len(results)
        successful_tasks = sum(1 for r in results if r.success)
        success_rate = successful_tasks / total_tasks
        
        # Aggregate metrics
        cascade_sizes = [r.cascade_size for r in results]
        branching_factors = [r.branching_factor for r in results]
        retry_indices = [r.retry_index for r in results]
        
        avg_cascade_size = sum(cascade_sizes) / len(cascade_sizes) if cascade_sizes else 0
        avg_branching_factor = sum(branching_factors) / len(branching_factors) if branching_factors else 0
        avg_retry_index = sum(retry_indices) / len(retry_indices) if retry_indices else 0
        
        # Misalignment
        all_misalignment_scores = []
        for r in results:
            all_misalignment_scores.extend(r.misalignment_scores.values())
        avg_misalignment = sum(all_misalignment_scores) / len(all_misalignment_scores) if all_misalignment_scores else 0
        
        return {
            "scenario_name": scenario_name,
            "total_tasks": total_tasks,
            "successful_tasks": successful_tasks,
            "success_rate": success_rate,
            "avg_cascade_size": avg_cascade_size,
            "avg_branching_factor": avg_branching_factor,
            "avg_retry_index": avg_retry_index,
            "avg_misalignment": avg_misalignment,
            "max_cascade_size": max(cascade_sizes) if cascade_sizes else 0,
            "resilience_status": self._evaluate_resilience(success_rate, avg_cascade_size, avg_branching_factor)
        }
    
    def _evaluate_resilience(self, success_rate: float, cascade_size: float, branching_factor: float) -> str:
        """Evaluate resilience status"""
        if success_rate >= 0.8 and cascade_size < 2 and branching_factor < 1.2:
            return "EXCELLENT"
        elif success_rate >= 0.6 and cascade_size < 5 and branching_factor < 1.5:
            return "GOOD"
        elif success_rate >= 0.4:
            return "ACCEPTABLE"
        else:
            return "POOR"
    
    def run_stress_comparison(self) -> dict:
        """Compare baseline vs stress scenarios"""
        logger.info("Running stress comparison analysis")
        
        # Run baseline (no faults)
        baseline_tasks = self.create_realistic_task_matrix()
        baseline_results = []
        
        for task_config in baseline_tasks:
            try:
                metrics = task_runner.execute_task(task_config)
                baseline_results.append(metrics)
            except Exception as e:
                logger.error(f"Baseline task failed: {e}")
        
        baseline_metrics = self._calculate_scenario_metrics(baseline_results, "baseline")
        
        # Run stress scenarios
        stress_results = self.run_combined_fault_scenarios()
        
        # Comparison analysis
        comparison = {
            "baseline": baseline_metrics,
            "stress_scenarios": stress_results,
            "analysis": self._analyze_stress_impact(baseline_metrics, stress_results)
        }
        
        return comparison
    
    def _analyze_stress_impact(self, baseline: dict, stress_scenarios: dict) -> dict:
        """Analyze impact of stress scenarios"""
        analysis = {
            "baseline_success_rate": baseline["success_rate"],
            "worst_case_success_rate": min(s["success_rate"] for s in stress_scenarios.values()),
            "best_case_success_rate": max(s["success_rate"] for s in stress_scenarios.values()),
            "avg_success_rate": sum(s["success_rate"] for s in stress_scenarios.values()) / len(stress_scenarios),
            "max_cascade_impact": max(s["avg_cascade_size"] for s in stress_scenarios.values()),
            "resilience_degradation": baseline["success_rate"] - min(s["success_rate"] for s in stress_scenarios.values()),
            "recommendations": []
        }
        
        # Generate recommendations
        if analysis["worst_case_success_rate"] < 0.6:
            analysis["recommendations"].append("Consider implementing additional fault tolerance measures")
        if analysis["max_cascade_impact"] > 2.0:
            analysis["recommendations"].append("Investigate cascade containment mechanisms")
        if analysis["resilience_degradation"] > 0.2:
            analysis["recommendations"].append("Review and strengthen critical path resilience")
        
        if not analysis["recommendations"]:
            analysis["recommendations"].append("System shows good resilience under stress - continue monitoring")
        
        return analysis

def main():
    """Main stress testing execution"""
    print("=== ADVANCED STRESS TESTING ===")
    
    stress_test = AdvancedStressTest()
    
    # Run stress comparison
    comparison = stress_test.run_stress_comparison()
    
    print(f"\n--- BASELINE PERFORMANCE ---")
    baseline = comparison["baseline"]
    print(f'Success Rate: {baseline["success_rate"]:.2%}')
    print(f'Avg Cascade Size: {baseline["avg_cascade_size"]:.2f}')
    print(f'Avg Branching Factor: {baseline["avg_branching_factor"]:.2f}')
    print(f'Avg Retry Index: {baseline["avg_retry_index"]:.2f}')
    print(f'Avg Misalignment: {baseline["avg_misalignment"]:.3f}')
    
    print(f'\n--- STRESS SCENARIOS ---')
    for scenario_name, metrics in comparison["stress_scenarios"].items():
        print(f'\n{scenario_name.upper()}:')
        print(f'  Success Rate: {metrics["success_rate"]:.2%} ({metrics["resilience_status"]})')
        print(f'  Avg Cascade Size: {metrics["avg_cascade_size"]:.2f}')
        print(f'  Avg Branching Factor: {metrics["avg_branching_factor"]:.2f}')
        print(f'  Avg Retry Index: {metrics["avg_retry_index"]:.2f}')
        print(f'  Max Cascade Size: {metrics["max_cascade_size"]}')
    
    print(f'\n--- IMPACT ANALYSIS ---')
    analysis = comparison["analysis"]
    print(f'Baseline Success Rate: {analysis["baseline_success_rate"]:.2%}')
    print(f'Worst Case Success Rate: {analysis["worst_case_success_rate"]:.2%}')
    print(f'Best Case Success Rate: {analysis["best_case_success_rate"]:.2%}')
    print(f'Average Stress Success Rate: {analysis["avg_success_rate"]:.2%}')
    print(f'Max Cascade Impact: {analysis["max_cascade_impact"]:.2f}')
    print(f'Resilience Degradation: {analysis["resilience_degradation"]:.2%}')
    
    print(f'\n--- RECOMMENDATIONS ---')
    for rec in analysis["recommendations"]:
        print(f'  • {rec}')
    
    # Export results
    import json
    with open('advanced_stress_results.json', 'w') as f:
        json.dump(comparison, f, indent=2)
    
    print(f'\nResults exported to advanced_stress_results.json')
    
    return comparison

if __name__ == "__main__":
    main()
