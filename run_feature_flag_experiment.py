#!/usr/bin/env python3
"""
Week 4: Feature Flag Experiments
One active experiment at a time with A/B comparison
"""

import sys
import json
from datetime import datetime

sys.path.append('.')
sys.path.append('swarm')

from swarm.lab.topology_lab import topology_lab, TopologyType
from swarm.quality.optimizer import quality_optimizer, OptimizationTarget
from utils.logger import get_logger

logger = get_logger("swarm.feature_flag_experiments")

class FeatureFlagExperiment:
    """Manages experiments as feature flags"""
    
    def __init__(self):
        self.active_experiments = {}
        self.experiment_history = []
        
    def start_experiment(self, experiment_type: str, experiment_config: dict) -> str:
        """Start a new experiment (feature flag)"""
        experiment_id = f"exp_{experiment_type}_{int(datetime.now().timestamp())}"
        
        # Check if any experiment is already running
        if self.active_experiments:
            logger.warning(f"Cannot start {experiment_type} experiment - {list(self.active_experiments.keys())} already running")
            return None
        
        self.active_experiments[experiment_id] = {
            "type": experiment_type,
            "config": experiment_config,
            "start_time": datetime.now().isoformat(),
            "status": "running"
        }
        
        logger.info(f"Started experiment {experiment_id}: {experiment_type}")
        return experiment_id
    
    def run_ab_comparison(self, experiment_id: str) -> dict:
        """Run A/B comparison for experiment"""
        if experiment_id not in self.active_experiments:
            raise ValueError(f"Experiment {experiment_id} not found")
        
        experiment = self.active_experiments[experiment_id]
        experiment_type = experiment["type"]
        
        logger.info(f"Running A/B comparison for {experiment_id}")
        
        if experiment_type == "topology":
            return self._run_topology_ab_comparison(experiment_id, experiment["config"])
        elif experiment_type == "prompt":
            return self._run_prompt_ab_comparison(experiment_id, experiment["config"])
        else:
            raise ValueError(f"Unknown experiment type: {experiment_type}")
    
    def _run_topology_ab_comparison(self, experiment_id: str, config: dict) -> dict:
        """Run topology A/B comparison"""
        # Current topology (control)
        control_tasks = config.get("task_ids", ["code_analysis_0", "data_processing_0"])
        control_exp_id = topology_lab.create_experiment(
            TopologyType.CURRENT_MESH,
            control_tasks,
            f"Control: {experiment_id}"
        )
        
        control_results = topology_lab.run_experiment(control_exp_id)
        
        # Variant topology (experiment)
        variant_topology = config.get("variant_topology", TopologyType.SHALLOW_HIERARCHY)
        variant_exp_id = topology_lab.create_experiment(
            variant_topology,
            control_tasks,
            f"Variant: {experiment_id}",
            comparison_baseline=control_exp_id
        )
        
        variant_results = topology_lab.run_experiment(variant_exp_id)
        
        # Compare results
        comparison = self._compare_results(control_results, variant_results)
        
        # Complete experiment
        self.active_experiments[experiment_id]["status"] = "completed"
        self.active_experiments[experiment_id]["end_time"] = datetime.now().isoformat()
        self.active_experiments[experiment_id]["results"] = {
            "control": control_results,
            "variant": variant_results,
            "comparison": comparison
        }
        
        # Move to history
        self.experiment_history.append(self.active_experiments.pop(experiment_id))
        
        return {
            "experiment_id": experiment_id,
            "experiment_type": "topology",
            "control": control_results,
            "variant": variant_results,
            "comparison": comparison,
            "recommendation": self._generate_topology_recommendation(comparison)
        }
    
    def _run_prompt_ab_comparison(self, experiment_id: str, config: dict) -> dict:
        """Run prompt A/B comparison"""
        # Baseline prompt (control)
        control_variant = config.get("control_variant", {
            "role": config.get("role", "planner"),
            "prompt_variant": "baseline",
            "description": "Current baseline prompt"
        })
        
        control_experiment = quality_optimizer.run_optimization_experiment(
            OptimizationTarget[config.get("target", "PLANNER_SPEC_CLARITY")],
            control_variant
        )
        
        # Enhanced prompt (variant)
        variant_prompt = config.get("variant_prompt", {
            "role": config.get("role", "planner"),
            "prompt_variant": "enhanced_v1",
            "description": "Enhanced prompt with improvements",
            "prompt_changes": config.get("prompt_changes", {})
        })
        
        variant_experiment = quality_optimizer.run_optimization_experiment(
            OptimizationTarget[config.get("target", "PLANNER_SPEC_CLARITY")],
            variant_prompt
        )
        
        # Compare results
        comparison = self._compare_prompt_results(control_experiment, variant_experiment)
        
        # Complete experiment
        self.active_experiments[experiment_id]["status"] = "completed"
        self.active_experiments[experiment_id]["end_time"] = datetime.now().isoformat()
        self.active_experiments[experiment_id]["results"] = {
            "control": control_experiment,
            "variant": variant_experiment,
            "comparison": comparison
        }
        
        # Move to history
        self.experiment_history.append(self.active_experiments.pop(experiment_id))
        
        return {
            "experiment_id": experiment_id,
            "experiment_type": "prompt",
            "control": control_experiment,
            "variant": variant_experiment,
            "comparison": comparison,
            "recommendation": self._generate_prompt_recommendation(comparison)
        }
    
    def _compare_results(self, control_results: dict, variant_results: dict) -> dict:
        """Compare control and variant results"""
        if "error" in control_results or "error" in variant_results:
            return {
                "status": "error",
                "message": "One or both experiments failed"
            }
        
        control_success = control_results.get("success_rate", 0)
        variant_success = variant_results.get("success_rate", 0)
        
        control_quality = control_results.get("avg_quality_score", 0)
        variant_quality = variant_results.get("avg_quality_score", 0)
        
        control_resilience = 1.0 - control_results.get("avg_cascade_size", 0)
        variant_resilience = 1.0 - variant_results.get("avg_cascade_size", 0)
        
        # Calculate improvement
        success_improvement = variant_success - control_success
        quality_improvement = variant_quality - control_quality
        resilience_improvement = variant_resilience - control_resilience
        
        # Overall improvement score
        improvement_score = (success_improvement * 0.4 + 
                              quality_improvement * 0.3 + 
                              resilience_improvement * 0.3)
        
        return {
            "success_rate": {
                "control": control_success,
                "variant": variant_success,
                "improvement": success_improvement
            },
            "quality_score": {
                "control": control_quality,
                "variant": variant_quality,
                "improvement": quality_improvement
            },
            "resilience_score": {
                "control": control_resilience,
                "variant": variant_resilience,
                "improvement": resilience_improvement
            },
            "overall_improvement": improvement_score,
            "variant_better": improvement_score > 0.05  # 5% minimum improvement
        }
    
    def _compare_prompt_results(self, control_experiment, variant_experiment) -> dict:
        """Compare prompt optimization results"""
        control_improvement = control_experiment.improvement_score
        variant_improvement = variant_experiment.improvement_score
        
        improvement_delta = variant_improvement - control_improvement
        
        return {
            "control_improvement": control_improvement,
            "variant_improvement": variant_improvement,
            "improvement_delta": improvement_delta,
            "variant_better": improvement_delta > 0.05,
            "statistical_significance": variant_experiment.statistical_significance
        }
    
    def _generate_topology_recommendation(self, comparison: dict) -> str:
        """Generate recommendation for topology experiment"""
        if comparison["variant_better"]:
            improvement = comparison["overall_improvement"]
            if improvement > 0.1:
                return "STRONGLY_RECOMMENDED - Significant improvement"
            elif improvement > 0.05:
                return "RECOMMENDED - Clear improvement"
            else:
                return "CONSIDER - Marginal improvement"
        else:
            return "NOT_RECOMMENDED - No clear benefit"
    
    def _generate_prompt_recommendation(self, comparison: dict) -> str:
        """Generate recommendation for prompt experiment"""
        if comparison["variant_better"] and comparison["statistical_significance"] > 0.6:
            improvement = comparison["improvement_delta"]
            if improvement > 0.1:
                return "STRONGLY_RECOMMENDED - Significant improvement"
            elif improvement > 0.05:
                return "RECOMMENDED - Clear improvement"
            else:
                return "CONSIDER - Marginal improvement"
        else:
            return "NOT_RECOMMENDED - No clear benefit"
    
    def kill_experiment(self, experiment_id: str) -> bool:
        """Kill an active experiment"""
        if experiment_id not in self.active_experiments:
            return False
        
        experiment = self.active_experiments.pop(experiment_id)
        experiment["status"] = "killed"
        experiment["end_time"] = datetime.now().isoformat()
        
        self.experiment_history.append(experiment)
        
        logger.info(f"Killed experiment {experiment_id}")
        return True
    
    def get_active_experiments(self) -> dict:
        """Get currently active experiments"""
        return self.active_experiments.copy()
    
    def get_experiment_history(self) -> list:
        """Get experiment history"""
        return self.experiment_history.copy()


# Global feature flag manager
feature_flag_manager = FeatureFlagExperiment()


def run_single_topology_experiment():
    """Run a single topology experiment as feature flag"""
    print("=" * 60)
    print("FEATURE FLAG EXPERIMENT: TOPOLOGY")
    print("=" * 60)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    print("Strategy: One experiment at a time with A/B comparison")
    print()
    
    # Check if any experiment is running
    active = feature_flag_manager.get_active_experiments()
    if active:
        print(f"❌ Cannot start - experiments already running: {list(active.keys())}")
        return None
    
    # Start topology experiment
    experiment_config = {
        "variant_topology": TopologyType.SHALLOW_HIERARCHY,
        "task_ids": ["code_analysis_0", "data_processing_0", "trading_0"],
        "description": "Test shallow hierarchy on mixed task types"
    }
    
    experiment_id = feature_flag_manager.start_experiment("topology", experiment_config)
    
    if not experiment_id:
        print("❌ Failed to start experiment")
        return None
    
    print(f"Started experiment: {experiment_id}")
    
    # Run A/B comparison
    results = feature_flag_manager.run_ab_comparison(experiment_id)
    
    print("\nEXPERIMENT RESULTS:")
    print("-" * 40)
    print(f"Experiment ID: {results['experiment_id']}")
    print(f"Type: {results['experiment_type']}")
    print()
    
    comparison = results["comparison"]
    print("A/B Comparison:")
    print(f"  Success Rate: Control {comparison['success_rate']['control']:.2%} → Variant {comparison['success_rate']['variant']:.2%} ({comparison['success_rate']['improvement']:+.1%})")
    print(f"  Quality Score: Control {comparison['quality_score']['control']:.2f} → Variant {comparison['quality_score']['variant']:.2f} ({comparison['quality_score']['improvement']:+.2f})")
    print(f"  Resilience: Control {comparison['resilience_score']['control']:.2f} → Variant {comparison['resilience_score']['variant']:.2f} ({comparison['resilience_score']['improvement']:+.2f})")
    print(f"  Overall Improvement: {comparison['overall_improvement']:+.3f}")
    print()
    print(f"Recommendation: {results['recommendation']}")
    
    # Save results
    with open("feature_flag_topology_experiment.json", 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n✅ Results saved to feature_flag_topology_experiment.json")
    
    print()
    print("=" * 60)
    print("FEATURE FLAG EXPERIMENT COMPLETE")
    print(f"Status: {results['recommendation']}")
    print("=" * 60)
    
    return results


if __name__ == "__main__":
    run_single_topology_experiment()
