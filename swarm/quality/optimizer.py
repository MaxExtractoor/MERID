#!/usr/bin/env python3
"""
Quality-Based Role and Prompt Optimization for MERID Swarm
Uses quality metrics to identify and optimize high-impact areas
"""

import sys
import json
import time
from typing import Dict, List, Any, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

sys.path.append('.')
sys.path.append('swarm')

from swarm.lab.topology_lab import topology_lab, TopologyType
from swarm.quality.metrics_collector import quality_collector
from swarm.integration.task_runner import task_runner
from utils.logger import get_logger

logger = get_logger("swarm.quality_optimization")


class OptimizationTarget(Enum):
    """Areas for quality optimization"""
    PLANNER_SPEC_CLARITY = "planner_spec_clarity"
    REVIEWER_CONTRACT = "reviewer_contract"
    IMPLEMENTER_EFFICIENCY = "implementer_efficiency"
    COORDINATION_OVERHEAD = "coordination_overhead"
    TOOL_SELECTION = "tool_selection"


@dataclass
class OptimizationExperiment:
    """Experiment for role/prompt optimization"""
    experiment_id: str
    target: OptimizationTarget
    baseline_metrics: Dict[str, float]
    variant_metrics: Dict[str, float]
    improvement_score: float
    statistical_significance: float
    recommendation: str


class QualityBasedOptimizer:
    """Optimizes roles and prompts based on quality metrics"""
    
    def __init__(self):
        self.experiments: List[OptimizationExperiment] = []
        self.correlation_cache: Dict[str, float] = {}
        
        logger.info("Quality-based optimizer initialized")
    
    def analyze_misalignment_correlations(self) -> Dict[str, float]:
        """Analyze correlations between misalignment and quality issues"""
        logger.info("Analyzing misalignment-quality correlations")
        
        correlations = {}
        
        # Get correlation data from quality collector
        correlation_data = quality_collector.correlate_misalignment_with_corrections()
        
        if "error" not in correlation_data:
            correlation_coeff = correlation_data.get("correlation_coefficient", 0.0)
            correlations["overall_misalignment_correlation"] = correlation_coeff
            
            # Analyze specific role pairs
            role_pairs = [
                "planner_vs_reviewer",
                "planner_vs_implementer", 
                "reviewer_vs_implementer",
                "coordinator_vs_agent"
            ]
            
            for pair in role_pairs:
                # This would need actual correlation data per role pair
                # For now, we'll use placeholder logic
                correlations[pair] = correlation_coeff * 0.8  # Assume similar correlation
        
        self.correlation_cache = correlations
        return correlations
    
    def identify_optimization_targets(self) -> List[OptimizationTarget]:
        """Identify which roles/prompts need optimization"""
        correlations = self.analyze_misalignment_correlations()
        
        targets = []
        
        # High correlation areas indicate optimization opportunities
        if correlations.get("planner_vs_reviewer", 0) > 0.5:
            targets.append(OptimizationTarget.PLANNER_SPEC_CLARITY)
            targets.append(OptimizationTarget.REVIEWER_CONTRACT)
        
        if correlations.get("planner_vs_implementer", 0) > 0.5:
            targets.append(OptimizationTarget.PLANNER_SPEC_CLARITY)
            targets.append(OptimizationTarget.IMPLEMENTER_EFFICIENCY)
        
        if correlations.get("reviewer_vs_implementer", 0) > 0.5:
            targets.append(OptimizationTarget.REVIEWER_CONTRACT)
            targets.append(OptimizationTarget.IMPLEMENTER_EFFICIENCY)
        
        # Always include tool selection as it's a common optimization area
        targets.append(OptimizationTarget.TOOL_SELECTION)
        
        return targets
    
    def create_prompt_variants(self, target: OptimizationTarget) -> List[Dict[str, str]]:
        """Create prompt variants for optimization testing"""
        variants = []
        
        if target == OptimizationTarget.PLANNER_SPEC_CLARITY:
            variants = [
                {
                    "role": "planner",
                    "prompt_variant": "enhanced_spec_clarity",
                    "description": "More detailed specification requirements",
                    "prompt_changes": {
                        "spec_requirements": "Add explicit acceptance criteria and edge cases",
                        "clarity_focus": "Emphasize unambiguous language",
                        "validation_steps": "Include pre-flight validation checklist"
                    }
                },
                {
                    "role": "planner", 
                    "prompt_variant": "structured_planning",
                    "description": "Structured planning with templates",
                    "prompt_changes": {
                        "planning_template": "Use standardized planning template",
                        "step_by_step": "Break down into explicit sequential steps",
                        "dependency_mapping": "Explicit dependency identification"
                    }
                }
            ]
        
        elif target == OptimizationTarget.REVIEWER_CONTRACT:
            variants = [
                {
                    "role": "reviewer",
                    "prompt_variant": "enhanced_review_checklist",
                    "description": "Comprehensive review checklist",
                    "prompt_changes": {
                        "checklist_items": "Expand review checklist to 20+ items",
                        "quality_gates": "Add explicit quality gate criteria",
                        "context_awareness": "Consider broader system impact"
                    }
                },
                {
                    "role": "reviewer",
                    "prompt_variant": "risk_focused_review",
                    "description": "Risk-focused review approach",
                    "prompt_changes": {
                        "risk_assessment": "Prioritize security and performance risks",
                        "impact_analysis": "Quantify potential impact of changes",
                        "rollback_planning": "Verify rollback feasibility"
                    }
                }
            ]
        
        elif target == OptimizationTarget.IMPLEMENTER_EFFICIENCY:
            variants = [
                {
                    "role": "implementer",
                    "prompt_variant": "efficient_coding_patterns",
                    "description": "Focus on efficient coding patterns",
                    "prompt_changes": {
                        "code_patterns": "Use established coding patterns",
                        "performance_focus": "Prioritize performance considerations",
                        "test_first": "Emphasize test-driven development"
                    }
                },
                {
                    "role": "implementer",
                    "prompt_variant": "modular_design",
                    "description": "Modular and maintainable design",
                    "prompt_changes": {
                        "modularity": "Break into small, focused modules",
                        "maintainability": "Consider long-term maintenance",
                        "documentation": "Include comprehensive documentation"
                    }
                }
            ]
        
        elif target == OptimizationTarget.TOOL_SELECTION:
            variants = [
                {
                    "role": "all",
                    "prompt_variant": "optimized_tool_usage",
                    "description": "Better tool selection and usage",
                    "prompt_changes": {
                        "tool_efficiency": "Choose most efficient tools for task",
                        "tool_combination": "Combine tools for better results",
                        "fallback_tools": "Have backup tools ready"
                    }
                }
            ]
        
        return variants
    
    def run_optimization_experiment(self, target: OptimizationTarget, 
                                   variant: Dict[str, str]) -> OptimizationExperiment:
        """Run optimization experiment in topology lab"""
        logger.info(f"Running optimization experiment for {target.value}")
        
        experiment_id = f"opt_{target.value}_{variant['prompt_variant']}_{int(time.time())}"
        
        # Create baseline experiment (current topology)
        baseline_tasks = ["code_analysis_0", "code_analysis_1", "trading_0", "trading_1"]  # Small subset
        baseline_exp_id = topology_lab.create_experiment(
            TopologyType.CURRENT_MESH,
            baseline_tasks,
            f"Baseline for {target.value}"
        )
        
        # Run baseline
        baseline_results = topology_lab.run_experiment(baseline_exp_id)
        baseline_metrics = self._extract_quality_metrics(baseline_results)
        
        # Create variant experiment with prompt changes
        variant_tasks = baseline_tasks.copy()
        variant_exp_id = topology_lab.create_experiment(
            TopologyType.CURRENT_MESH,
            variant_tasks,
            f"Variant: {variant['description']}",
            comparison_baseline=baseline_exp_id
        )
        
        # Apply prompt changes (this would modify agent prompts)
        self._apply_prompt_variant(variant)
        
        # Run variant experiment
        variant_results = topology_lab.run_experiment(variant_exp_id)
        variant_metrics = self._extract_quality_metrics(variant_results)
        
        # Calculate improvement
        improvement_score = self._calculate_improvement(baseline_metrics, variant_metrics)
        statistical_significance = self._calculate_statistical_significance(
            baseline_metrics, variant_metrics
        )
        
        # Generate recommendation
        recommendation = self._generate_recommendation(improvement_score, statistical_significance)
        
        experiment = OptimizationExperiment(
            experiment_id=experiment_id,
            target=target,
            baseline_metrics=baseline_metrics,
            variant_metrics=variant_metrics,
            improvement_score=improvement_score,
            statistical_significance=statistical_significance,
            recommendation=recommendation
        )
        
        self.experiments.append(experiment)
        
        logger.info(f"Experiment {experiment_id} completed: {recommendation}")
        
        return experiment
    
    def _extract_quality_metrics(self, experiment_results: Dict[str, Any]) -> Dict[str, float]:
        """Extract quality metrics from experiment results"""
        if not experiment_results or "error" in experiment_results:
            return {"quality_score": 0.0, "success_rate": 0.0, "efficiency": 0.0}
        
        return {
            "quality_score": experiment_results.get("avg_quality_score", 0.0),
            "success_rate": experiment_results.get("success_rate", 0.0),
            "efficiency": experiment_results.get("avg_quality_score", 0.0) * 0.5,  # Proxy for efficiency
            "resilience": 1.0 - experiment_results.get("avg_cascade_size", 0.0)  # Inverse cascade size
        }
    
    def _apply_prompt_variant(self, variant: Dict[str, str]):
        """Apply prompt variant to agents (placeholder implementation)"""
        # This would modify the actual agent prompts
        # For now, we'll just log the changes
        logger.info(f"Applying prompt variant: {variant['description']}")
        logger.info(f"Changes: {variant.get('prompt_changes', {})}")
    
    def _calculate_improvement(self, baseline: Dict[str, float], variant: Dict[str, float]) -> float:
        """Calculate improvement score (0-1)"""
        if not baseline or not variant:
            return 0.0
        
        improvements = []
        weights = {"quality_score": 0.4, "success_rate": 0.3, "efficiency": 0.2, "resilience": 0.1}
        
        for metric, weight in weights.items():
            baseline_val = baseline.get(metric, 0.0)
            variant_val = variant.get(metric, 0.0)
            
            if baseline_val > 0:
                improvement = (variant_val - baseline_val) / baseline_val
                improvements.append(improvement * weight)
        
        return sum(improvements)
    
    def _calculate_statistical_significance(self, baseline: Dict[str, float], 
                                           variant: Dict[str, float]) -> float:
        """Calculate statistical significance (placeholder)"""
        # This would use proper statistical tests
        # For now, we'll use a simple heuristic based on improvement magnitude
        improvement = self._calculate_improvement(baseline, variant)
        
        if improvement > 0.1:
            return 0.95  # High significance
        elif improvement > 0.05:
            return 0.8   # Medium significance
        elif improvement > 0.02:
            return 0.6   # Low significance
        else:
            return 0.4   # Not significant
    
    def _generate_recommendation(self, improvement_score: float, 
                               statistical_significance: float) -> str:
        """Generate recommendation based on experiment results"""
        if improvement_score > 0.1 and statistical_significance > 0.8:
            return "STRONGLY_RECOMMENDED - Significant improvement with high confidence"
        elif improvement_score > 0.05 and statistical_significance > 0.6:
            return "RECOMMENDED - Moderate improvement with reasonable confidence"
        elif improvement_score > 0.02:
            return "CONSIDER - Minor improvement, low confidence"
        elif improvement_score < -0.05:
            return "AVOID - Performance degradation detected"
        else:
            return "NEUTRAL - No significant impact"
    
    def run_optimization_campaign(self) -> Dict[str, Any]:
        """Run complete optimization campaign"""
        logger.info("Starting quality-based optimization campaign")
        
        # Identify targets
        targets = self.identify_optimization_targets()
        
        campaign_results = {
            "targets_identified": [t.value for t in targets],
            "experiments_run": [],
            "successful_improvements": [],
            "recommendations": []
        }
        
        # Run experiments for each target
        for target in targets:
            variants = self.create_prompt_variants(target)
            
            for variant in variants:
                try:
                    experiment = self.run_optimization_experiment(target, variant)
                    campaign_results["experiments_run"].append(experiment.experiment_id)
                    
                    if experiment.improvement_score > 0.05:
                        campaign_results["successful_improvements"].append({
                            "target": target.value,
                            "variant": variant["prompt_variant"],
                            "improvement": experiment.improvement_score,
                            "confidence": experiment.statistical_significance
                        })
                    
                    if experiment.recommendation in ["STRONGLY_RECOMMENDED", "RECOMMENDED"]:
                        campaign_results["recommendations"].append({
                            "target": target.value,
                            "variant": variant["prompt_variant"],
                            "action": experiment.recommendation,
                            "expected_improvement": experiment.improvement_score
                        })
                
                except Exception as e:
                    logger.error(f"Failed to run experiment for {target.value}: {e}")
        
        # Generate campaign summary
        campaign_results["summary"] = {
            "total_experiments": len(campaign_results["experiments_run"]),
            "successful_experiments": len(campaign_results["successful_improvements"]),
            "success_rate": len(campaign_results["successful_improvements"]) / len(campaign_results["experiments_run"]) if campaign_results["experiments_run"] else 0,
            "best_improvement": max([exp["improvement"] for exp in campaign_results["successful_improvements"]], default=0) if campaign_results["successful_improvements"] else 0
        }
        
        logger.info(f"Optimization campaign completed: {campaign_results['summary']}")
        
        return campaign_results
    
    def get_optimization_report(self) -> Dict[str, Any]:
        """Get comprehensive optimization report"""
        if not self.experiments:
            return {"error": "No experiments run yet"}
        
        # Analyze by target
        target_analysis = {}
        for experiment in self.experiments:
            target = experiment.target.value
            if target not in target_analysis:
                target_analysis[target] = []
            target_analysis[target].append(experiment)
        
        # Find best improvements
        best_improvements = sorted(self.experiments, 
                                  key=lambda x: x.improvement_score, 
                                  reverse=True)[:5]
        
        # Calculate overall success rate
        successful_experiments = [exp for exp in self.experiments 
                                 if exp.improvement_score > 0.05 and exp.statistical_significance > 0.6]
        success_rate = len(successful_experiments) / len(self.experiments)
        
        return {
            "total_experiments": len(self.experiments),
            "success_rate": success_rate,
            "target_analysis": {
                target: {
                    "experiments": len(experiments),
                    "best_improvement": max([exp.improvement_score for exp in experiments]),
                    "avg_improvement": sum([exp.improvement_score for exp in experiments]) / len(experiments)
                }
                for target, experiments in target_analysis.items()
            },
            "best_improvements": [
                {
                    "experiment_id": exp.experiment_id,
                    "target": exp.target.value,
                    "improvement_score": exp.improvement_score,
                    "recommendation": exp.recommendation
                }
                for exp in best_improvements
            ],
            "correlations": self.correlation_cache,
            "next_steps": self._generate_next_steps()
        }
    
    def _generate_next_steps(self) -> List[str]:
        """Generate next steps based on optimization results"""
        if not self.experiments:
            return ["Run initial optimization experiments to establish baseline"]
        
        successful_experiments = [exp for exp in self.experiments 
                                 if exp.recommendation in ["STRONGLY_RECOMMENDED", "RECOMMENDED"]]
        
        if successful_experiments:
            return [
                f"Deploy {len(successful_experiments)} successful prompt improvements",
                "Monitor impact on production metrics",
                "Run follow-up experiments on successful patterns"
            ]
        else:
            return [
                "Review experiment methodology - no significant improvements found",
                "Consider alternative optimization approaches",
                "Focus on fundamental role redesign rather than prompt tweaks"
            ]


# Global optimizer instance
quality_optimizer = QualityBasedOptimizer()
