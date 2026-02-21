#!/usr/bin/env python3
"""
Week 2-3: Tiny Focused Experiments
One prompt/role experiment and one topology experiment at a time
"""

import sys
import json
from datetime import datetime

sys.path.append('.')
sys.path.append('swarm')

from swarm.quality.optimizer import quality_optimizer, OptimizationTarget
from swarm.lab.focused_experiments import focused_topology_lab
from utils.logger import get_logger

logger = get_logger("swarm.tiny_experiments")

def run_single_prompt_experiment():
    """Run one focused prompt optimization experiment"""
    print("=" * 60)
    print("TINY EXPERIMENT 1: PROMPT OPTIMIZATION")
    print("=" * 60)
    print("Target: Planner spec clarity")
    print("Scope: Single variant, controlled testing")
    print()
    
    # Create one prompt variant for planner spec clarity
    variant = {
        "role": "planner",
        "prompt_variant": "enhanced_spec_clarity_v1",
        "description": "More detailed specification requirements with explicit acceptance criteria",
        "prompt_changes": {
            "spec_requirements": "Add explicit acceptance criteria and edge cases",
            "clarity_focus": "Emphasize unambiguous language",
            "validation_steps": "Include pre-flight validation checklist"
        }
    }
    
    print("EXPERIMENT CONFIGURATION:")
    print("-" * 40)
    print(f"Target: {OptimizationTarget.PLANNER_SPEC_CLARITY.value}")
    print(f"Variant: {variant['prompt_variant']}")
    print(f"Description: {variant['description']}")
    print()
    
    # Run the experiment
    try:
        experiment = quality_optimizer.run_optimization_experiment(
            OptimizationTarget.PLANNER_SPEC_CLARITY,
            variant
        )
        
        print("RESULTS:")
        print("-" * 40)
        print(f"Experiment ID: {experiment.experiment_id}")
        print(f"Baseline Success Rate: {experiment.baseline_metrics.get('success_rate', 0):.2%}")
        print(f"Variant Success Rate: {experiment.variant_metrics.get('success_rate', 0):.2%}")
        print(f"Improvement Score: {experiment.improvement_score:+.3f}")
        print(f"Statistical Significance: {experiment.statistical_significance:.2f}")
        print(f"Recommendation: {experiment.recommendation}")
        
        # Save result
        result_data = {
            "experiment_type": "prompt_optimization",
            "target": OptimizationTarget.PLANNER_SPEC_CLARITY.value,
            "variant": variant["prompt_variant"],
            "experiment_id": experiment.experiment_id,
            "improvement_score": experiment.improvement_score,
            "statistical_significance": experiment.statistical_significance,
            "recommendation": experiment.recommendation,
            "date": datetime.now().isoformat()
        }
        
        with open("tiny_prompt_experiment_result.json", 'w') as f:
            json.dump(result_data, f, indent=2)
        
        print(f"\n✅ Result saved to tiny_prompt_experiment_result.json")
        
        return experiment
        
    except Exception as e:
        print(f"❌ Experiment failed: {e}")
        return None

def run_single_topology_experiment():
    """Run one focused topology experiment"""
    print("\n" + "=" * 60)
    print("TINY EXPERIMENT 2: TOPOLOGY COMPARISON")
    print("=" * 60)
    print("Target: Shallow hierarchy on non-critical tasks")
    print("Scope: 5 tasks, clear thresholds")
    print()
    
    # Get the shallow hierarchy config
    config = None
    for exp_config in focused_topology_lab.experiment_configs:
        if exp_config.name == "shallow_hierarchy_non_critical":
            config = exp_config
            break
    
    if not config:
        print("❌ Shallow hierarchy config not found")
        return None
    
    print("EXPERIMENT CONFIGURATION:")
    print("-" * 40)
    print(f"Topology: {config.topology_type.value}")
    print(f"Task Types: {', '.join(config.task_types)}")
    print(f"Success Threshold: {config.success_threshold:.2%}")
    print(f"Quality Threshold: {config.quality_threshold:.2f}")
    print(f"Resilience Threshold: {config.resilience_threshold:.2f}")
    print()
    
    # Run the experiment
    try:
        result = focused_topology_lab.run_focused_experiment(config)
        
        print("RESULTS:")
        print("-" * 40)
        evaluation = result["evaluation"]
        print(f"Overall Status: {evaluation['overall_status']}")
        print(f"Success Rate: {evaluation['success_rate']:.2%}")
        print(f"Quality Score: {evaluation['quality_score']:.2f}")
        print(f"Resilience Score: {evaluation['resilience_score']:.2f}")
        print(f"Thresholds Met: {'✅' if evaluation['thresholds_met'] else '❌'}")
        print(f"Recommendation: {result['recommendation']}")
        
        if evaluation['issues']:
            print("Issues:")
            for issue in evaluation['issues']:
                print(f"  - {issue}")
        
        # Save result
        result_data = {
            "experiment_type": "topology_comparison",
            "topology": config.topology_type.value,
            "config_name": config.name,
            "evaluation": evaluation,
            "recommendation": result["recommendation"],
            "date": datetime.now().isoformat()
        }
        
        with open("tiny_topology_experiment_result.json", 'w') as f:
            json.dump(result_data, f, indent=2)
        
        print(f"\n✅ Result saved to tiny_topology_experiment_result.json")
        
        return result
        
    except Exception as e:
        print(f"❌ Experiment failed: {e}")
        return None

def generate_experiment_summary(prompt_result, topology_result):
    """Generate summary of both tiny experiments"""
    print("\n" + "=" * 60)
    print("TINY EXPERIMENTS SUMMARY")
    print("=" * 60)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    print()
    
    print("PROMPT OPTIMIZATION EXPERIMENT:")
    print("-" * 40)
    if prompt_result:
        if prompt_result.improvement_score > 0.05 and prompt_result.statistical_significance > 0.6:
            status = "✅ SUCCESS"
            action = "Consider deploying this prompt variant"
        else:
            status = "⚠️  NEEDS WORK"
            action = "Refine prompt variant before deployment"
        
        print(f"Status: {status}")
        print(f"Improvement: {prompt_result.improvement_score:+.3f}")
        print(f"Confidence: {prompt_result.statistical_significance:.2f}")
        print(f"Next Action: {action}")
    else:
        print("Status: ❌ FAILED")
        print("Next Action: Fix experiment setup and retry")
    
    print()
    print("TOPOLOGY COMPARISON EXPERIMENT:")
    print("-" * 40)
    if topology_result:
        evaluation = topology_result["evaluation"]
        if evaluation["thresholds_met"]:
            status = "✅ MEETS THRESHOLDS"
            action = "Consider for limited deployment"
        else:
            status = "⚠️  BELOW THRESHOLDS"
            action = "Optimize topology before consideration"
        
        print(f"Status: {status}")
        print(f"Overall: {evaluation['overall_status']}")
        print(f"Success Rate: {evaluation['success_rate']:.2%}")
        print(f"Quality Score: {evaluation['quality_score']:.2f}")
        print(f"Next Action: {action}")
    else:
        print("Status: ❌ FAILED")
        print("Next Action: Fix experiment setup and retry")
    
    print()
    print("NEXT WEEK'S FOCUS:")
    print("-" * 40)
    
    # Determine next focus based on results
    next_actions = []
    
    if prompt_result and prompt_result.improvement_score > 0.05:
        next_actions.append("Deploy successful prompt variant to production")
    else:
        next_actions.append("Refine prompt optimization approach")
    
    if topology_result and topology_result["evaluation"]["thresholds_met"]:
        next_actions.append("Run larger topology experiment with more tasks")
    else:
        next_actions.append("Stick with current topology for now")
    
    next_actions.extend([
        "Continue weekly operational cadence",
        "Scale test expansion use case based on Week 2 success",
        "Document Swarm Ops v1 process"
    ])
    
    for i, action in enumerate(next_actions, 1):
        print(f"{i}. {action}")
    
    # Save summary
    summary_data = {
        "date": datetime.now().isoformat(),
        "prompt_experiment": {
            "success": prompt_result is not None,
            "improvement_score": prompt_result.improvement_score if prompt_result else 0,
            "recommendation": prompt_result.recommendation if prompt_result else "FAILED"
        },
        "topology_experiment": {
            "success": topology_result is not None,
            "thresholds_met": topology_result["evaluation"]["thresholds_met"] if topology_result else False,
            "recommendation": topology_result["recommendation"] if topology_result else "FAILED"
        },
        "next_actions": next_actions
    }
    
    with open("tiny_experiments_summary.json", 'w') as f:
        json.dump(summary_data, f, indent=2)
    
    print(f"\n✅ Summary saved to tiny_experiments_summary.json")

def main():
    """Run both tiny experiments"""
    print("STARTING TINY FOCUSED EXPERIMENTS")
    print("One prompt experiment + one topology experiment")
    print()
    
    # Run prompt experiment
    prompt_result = run_single_prompt_experiment()
    
    # Run topology experiment  
    topology_result = run_single_topology_experiment()
    
    # Generate summary
    generate_experiment_summary(prompt_result, topology_result)
    
    print("\n" + "=" * 60)
    print("TINY EXPERIMENTS COMPLETE")
    print("Ready for Week 3 decisions")
    print("=" * 60)

if __name__ == "__main__":
    main()
