#!/usr/bin/env python3
"""
Focused Topology Lab Experiments
Small, controlled experiments to evaluate topology improvements
"""

import sys
import json
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

sys.path.append('.')
sys.path.append('swarm')

from swarm.lab.topology_lab import topology_lab, TopologyType
from swarm.roi.tracker import roi_tracker, ImprovementType
from utils.logger import get_logger

logger = get_logger("swarm.focused_topology_lab")


@dataclass
class TopologyExperimentConfig:
    """Configuration for focused topology experiment"""
    name: str
    topology_type: TopologyType
    task_types: List[str]  # Limited to specific task types
    success_threshold: float  # Minimum success rate to consider
    quality_threshold: float  # Minimum quality score to consider
    resilience_threshold: float  # Minimum resilience score to consider


class FocusedTopologyLab:
    """Focused topology lab for controlled experiments"""
    
    def __init__(self):
        self.experiment_configs = self._create_experiment_configs()
        self.results: List[Dict[str, Any]] = []
        
        logger.info("Focused Topology Lab initialized")
    
    def _create_experiment_configs(self) -> List[TopologyExperimentConfig]:
        """Create focused experiment configurations"""
        return [
            TopologyExperimentConfig(
                name="shallow_hierarchy_non_critical",
                topology_type=TopologyType.SHALLOW_HIERARCHY,
                task_types=["code_analysis", "data_processing"],  # Non-critical only
                success_threshold=0.85,
                quality_threshold=0.75,
                resilience_threshold=0.8
            ),
            TopologyExperimentConfig(
                name="current_topology_baseline",
                topology_type=TopologyType.CURRENT_MESH,
                task_types=["code_analysis", "data_processing", "trading"],
                success_threshold=0.90,
                quality_threshold=0.80,
                resilience_threshold=0.9
            ),
            TopologyExperimentConfig(
                name="star_topology_low_risk",
                topology_type=TopologyType.STAR_TOPOLOGY,
                task_types=["documentation_improvement", "dependency_updates"],  # Low risk only
                success_threshold=0.80,
                quality_threshold=0.70,
                resilience_threshold=0.7
            )
        ]
    
    def run_focused_experiment(self, config: TopologyExperimentConfig) -> Dict[str, Any]:
        """Run a focused topology experiment"""
        logger.info(f"Running focused experiment: {config.name}")
        
        # Select appropriate tasks
        task_ids = self._select_task_ids(config.task_types)
        
        # Create experiment
        experiment_id = topology_lab.create_experiment(
            config.topology_type,
            task_ids,
            f"Focused experiment: {config.name}"
        )
        
        # Run experiment
        start_time = time.time()
        experiment_results = topology_lab.run_experiment(experiment_id)
        execution_time = time.time() - start_time
        
        # Evaluate against thresholds
        evaluation = self._evaluate_experiment(experiment_results, config)
        
        # Create result summary
        result = {
            "experiment_name": config.name,
            "topology_type": config.topology_type.value,
            "config": config,
            "results": experiment_results,
            "evaluation": evaluation,
            "execution_time": execution_time,
            "recommendation": self._generate_recommendation(evaluation, config)
        }
        
        self.results.append(result)
        
        logger.info(f"Experiment {config.name} completed: {evaluation['overall_status']}")
        
        return result
    
    def _select_task_ids(self, task_types: List[str]) -> List[str]:
        """Select task IDs for given task types"""
        # Map task types to specific task IDs
        task_mapping = {
            "code_analysis": ["code_analysis_0", "code_analysis_1", "code_analysis_2"],
            "data_processing": ["data_processing_0", "data_processing_1"],
            "trading": ["trading_0", "trading_1"],
            "documentation_improvement": ["governance_0", "governance_1"],
            "dependency_updates": ["infrastructure_0"],
            "security_hardening": ["risk_mgmt_0"]
        }
        
        selected_ids = []
        for task_type in task_types:
            selected_ids.extend(task_mapping.get(task_type, []))
        
        return selected_ids[:5]  # Limit to 5 tasks for focused experiments
    
    def _evaluate_experiment(self, results: Dict[str, Any], 
                           config: TopologyExperimentConfig) -> Dict[str, Any]:
        """Evaluate experiment results against thresholds"""
        if "error" in results:
            return {
                "overall_status": "failed",
                "success_rate": 0.0,
                "quality_score": 0.0,
                "resilience_score": 0.0,
                "thresholds_met": False,
                "issues": ["Experiment execution failed"]
            }
        
        success_rate = results.get("success_rate", 0.0)
        quality_score = results.get("avg_quality_score", 0.0)
        
        # Calculate resilience score (inverse of cascade size + branching factor)
        cascade_size = results.get("avg_cascade_size", 0.0)
        branching_factor = results.get("avg_branching_factor", 0.0)
        resilience_score = max(0.0, 1.0 - (cascade_size * 0.5 + branching_factor * 0.5))
        
        # Check thresholds
        success_met = success_rate >= config.success_threshold
        quality_met = quality_score >= config.quality_threshold
        resilience_met = resilience_score >= config.resilience_threshold
        
        thresholds_met = success_met and quality_met and resilience_met
        
        # Identify issues
        issues = []
        if not success_met:
            issues.append(f"Success rate {success_rate:.2%} below threshold {config.success_threshold:.2%}")
        if not quality_met:
            issues.append(f"Quality score {quality_score:.2f} below threshold {config.quality_threshold:.2f}")
        if not resilience_met:
            issues.append(f"Resilience score {resilience_score:.2f} below threshold {config.resilience_threshold:.2f}")
        
        # Determine overall status
        if thresholds_met:
            if success_rate >= 0.95 and quality_score >= 0.9:
                overall_status = "excellent"
            else:
                overall_status = "acceptable"
        else:
            if success_rate < 0.6 or quality_score < 0.5:
                overall_status = "poor"
            else:
                overall_status = "needs_improvement"
        
        return {
            "overall_status": overall_status,
            "success_rate": success_rate,
            "quality_score": quality_score,
            "resilience_score": resilience_score,
            "thresholds_met": thresholds_met,
            "issues": issues,
            "metrics": {
                "success_rate_vs_threshold": success_rate - config.success_threshold,
                "quality_score_vs_threshold": quality_score - config.quality_threshold,
                "resilience_score_vs_threshold": resilience_score - config.resilience_threshold
            }
        }
    
    def _generate_recommendation(self, evaluation: Dict[str, Any], 
                                config: TopologyExperimentConfig) -> str:
        """Generate recommendation based on evaluation"""
        if evaluation["overall_status"] == "excellent":
            return f"STRONGLY_RECOMMENDED - {config.topology_type.value} shows excellent performance"
        elif evaluation["overall_status"] == "acceptable":
            return f"CONSIDER - {config.topology_type.value} meets minimum thresholds"
        elif evaluation["overall_status"] == "needs_improvement":
            return f"EXPERIMENTAL - {config.topology_type.value} needs optimization before consideration"
        else:
            return f"NOT_RECOMMENDED - {config.topology_type.value} fails to meet requirements"
    
    def run_comparison_study(self) -> Dict[str, Any]:
        """Run comparison study between topologies"""
        logger.info("Running topology comparison study")
        
        # Run all experiments
        experiment_results = []
        for config in self.experiment_configs:
            try:
                result = self.run_focused_experiment(config)
                experiment_results.append(result)
            except Exception as e:
                logger.error(f"Failed to run experiment {config.name}: {e}")
        
        # Create comparison table
        comparison_table = []
        for result in experiment_results:
            evaluation = result["evaluation"]
            comparison_table.append({
                "topology": result["topology_type"],
                "experiment": result["experiment_name"],
                "success_rate": evaluation["success_rate"],
                "quality_score": evaluation["quality_score"],
                "resilience_score": evaluation["resilience_score"],
                "overall_status": evaluation["overall_status"],
                "thresholds_met": evaluation["thresholds_met"],
                "recommendation": result["recommendation"]
            })
        
        # Sort by overall performance
        comparison_table.sort(key=lambda x: (
            x["success_rate"] + x["quality_score"] + x["resilience_score"]
        ), reverse=True)
        
        # Find best topology
        if comparison_table:
            best_topology = comparison_table[0]
            best_recommendation = best_topology["recommendation"]
        else:
            best_topology = None
            best_recommendation = "No successful experiments"
        
        # Generate analysis
        analysis = {
            "best_topology": best_topology["topology"] if best_topology else None,
            "best_recommendation": best_recommendation,
            "comparison_table": comparison_table,
            "key_findings": self._generate_key_findings(comparison_table),
            "next_steps": self._generate_next_steps(comparison_table)
        }
        
        return analysis
    
    def _generate_key_findings(self, comparison_table: List[Dict[str, Any]]) -> List[str]:
        """Generate key findings from comparison"""
        findings = []
        
        if not comparison_table:
            return ["No experiments completed successfully"]
        
        # Performance analysis
        best_success = max(row["success_rate"] for row in comparison_table)
        worst_success = min(row["success_rate"] for row in comparison_table)
        
        if best_success - worst_success > 0.2:
            findings.append(f"Significant performance variation: {best_success:.1%} vs {worst_success:.1%}")
        
        # Quality analysis
        best_quality = max(row["quality_score"] for row in comparison_table)
        worst_quality = min(row["quality_score"] for row in comparison_table)
        
        if best_quality - worst_quality > 0.2:
            findings.append(f"Quality variation: {best_quality:.2f} vs {worst_quality:.2f}")
        
        # Resilience analysis
        best_resilience = max(row["resilience_score"] for row in comparison_table)
        worst_resilience = min(row["resilience_score"] for row in comparison_table)
        
        if best_resilience - worst_resilience > 0.2:
            findings.append(f"Resilience variation: {best_resilience:.2f} vs {worst_resilience:.2f}")
        
        # Threshold compliance
        compliant_topologies = [row for row in comparison_table if row["thresholds_met"]]
        if len(compliant_topologies) < len(comparison_table):
            findings.append(f"{len(compliant_topologies)}/{len(comparison_table)} topologies meet all thresholds")
        
        # Best topology characteristics
        best_row = comparison_table[0]
        if best_row["overall_status"] == "excellent":
            findings.append(f"Best topology ({best_row['topology']}) shows excellent performance across all metrics")
        
        return findings
    
    def _generate_next_steps(self, comparison_table: List[Dict[str, Any]]) -> List[str]:
        """Generate next steps based on comparison"""
        steps = []
        
        if not comparison_table:
            return ["Fix experiment execution issues before proceeding"]
        
        best_topology = comparison_table[0]
        
        if best_topology["overall_status"] in ["excellent", "acceptable"]:
            steps.append(f"Consider deploying {best_topology['topology']} for {best_topology['experiment']} tasks")
            
            # Check if it's significantly better than current mesh
            current_mesh = next((row for row in comparison_table 
                                if row["topology"] == "current_mesh"), None)
            
            if current_mesh and best_topology["success_rate"] > current_mesh["success_rate"] + 0.1:
                steps.append(f"Strong case for {best_topology['topology']} - outperforms current mesh by {best_topology['success_rate'] - current_mesh['success_rate']:.1%}")
        
        # Identify improvement opportunities
        poor_performers = [row for row in comparison_table if row["overall_status"] == "poor"]
        if poor_performers:
            steps.append(f"Optimize {poor_performers[0]['topology']} before further consideration")
        
        # Suggest focused experiments
        acceptable_topologies = [row for row in comparison_table if row["overall_status"] == "acceptable"]
        if acceptable_topologies:
            steps.append(f"Run larger experiments with {acceptable_topologies[0]['topology']} to validate performance")
        
        return steps
    
    def export_results(self, filename: str = "focused_topology_results.json"):
        """Export focused topology lab results"""
        results_data = {
            "timestamp": time.time(),
            "experiment_configs": [
                {
                    "name": config.name,
                    "topology_type": config.topology_type.value,
                    "task_types": config.task_types,
                    "thresholds": {
                        "success": config.success_threshold,
                        "quality": config.quality_threshold,
                        "resilience": config.resilience_threshold
                    }
                }
                for config in self.experiment_configs
            ],
            "results": self.results,
            "comparison_study": self.run_comparison_study() if self.results else None
        }
        
        with open(filename, 'w') as f:
            json.dump(results_data, f, indent=2)
        
        logger.info(f"Focused topology results exported to {filename}")


# Global focused topology lab instance
focused_topology_lab = FocusedTopologyLab()
