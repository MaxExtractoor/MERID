#!/usr/bin/env python3
"""
Single Topology Experiment - Shallow Hierarchy on Documentation
One experiment at a time with clear success criteria
"""

import sys
import json
from datetime import datetime

sys.path.append('.')
sys.path.append('swarm')

from swarm.lab.topology_lab import topology_lab, TopologyType
from utils.logger import get_logger

logger = get_logger("swarm.single_topology_experiment")

def run_single_topology_experiment():
    """Run one topology experiment on documentation improvements"""
    print("=" * 70)
    print("SINGLE TOPOLOGY EXPERIMENT")
    print("=" * 70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    print("Strategy: One experiment at a time, clear success criteria")
    print()
    
    # Define experiment: Shallow hierarchy on documentation tasks
    experiment_config = {
        "variant_topology": TopologyType.SHALLOW_HIERARCHY,
        "task_ids": [
            "documentation_0",  # Low-risk doc improvement
            "documentation_1",  # Low-risk doc improvement  
            "documentation_2",  # Low-risk doc improvement
            "documentation_3",  # Low-risk doc improvement
            "documentation_4"   # Low-risk doc improvement
        ],
        "task_types": ["documentation"],
        "description": "Test shallow hierarchy on documentation improvements",
        "success_threshold": 0.80,  # 80% success rate minimum
        "quality_threshold": 0.70,   # 70% quality minimum
        "resilience_threshold": 0.80  # 80% resilience minimum
    }
    
    print("EXPERIMENT CONFIGURATION:")
    print("-" * 50)
    print(f"Topology: {experiment_config['variant_topology'].value}")
    print(f"Task Types: {', '.join(experiment_config['task_types'])}")
    print(f"Task Count: {len(experiment_config['task_ids'])}")
    print(f"Success Threshold: {experiment_config['success_threshold']:.0%}")
    print(f"Quality Threshold: {experiment_config['quality_threshold']:.0%}")
    print(f"Resilience Threshold: {experiment_config['resilience_threshold']:.0%}")
    print(f"Description: {experiment_config['description']}")
    print()
    
    # Check if any experiment is already running
    try:
        with open("active_topology_experiment.json", 'r') as f:
            active = json.load(f)
        print(f"❌ Cannot start - experiment already running: {active.get('experiment_id', 'unknown')}")
        return None
    except FileNotFoundError:
        pass
    
    # Start the experiment
    print("STARTING EXPERIMENT:")
    print("-" * 50)
    
    # Create baseline experiment (current topology)
    print("Creating baseline experiment (current topology)...")
    baseline_exp_id = topology_lab.create_experiment(
        TopologyType.CURRENT_MESH,
        experiment_config["task_ids"],
        f"Baseline: Documentation improvements"
    )
    
    print(f"Baseline experiment ID: {baseline_exp_id}")
    
    # Run baseline
    print("Running baseline experiment...")
    baseline_results = topology_lab.run_experiment(baseline_exp_id)
    
    if "error" in baseline_results:
        print(f"❌ Baseline experiment failed: {baseline_results['error']}")
        return None
    
    print(f"Baseline completed: {baseline_results.get('success_rate', 0):.1%} success rate")
    
    # Create variant experiment (shallow hierarchy)
    print("\nCreating variant experiment (shallow hierarchy)...")
    variant_exp_id = topology_lab.create_experiment(
        experiment_config["variant_topology"],
        experiment_config["task_ids"],
        f"Variant: {experiment_config['description']}",
        comparison_baseline=baseline_exp_id
    )
    
    print(f"Variant experiment ID: {variant_exp_id}")
    
    # Run variant
    print("Running variant experiment...")
    variant_results = topology_lab.run_experiment(variant_exp_id)
    
    if "error" in variant_results:
        print(f"❌ Variant experiment failed: {variant_results['error']}")
        return None
    
    print(f"Variant completed: {variant_results.get('success_rate', 0):.1%} success rate")
    
    # Compare results
    print("\nA/B COMPARISON:")
    print("-" * 50)
    
    baseline_success = baseline_results.get("success_rate", 0)
    variant_success = variant_results.get("success_rate", 0)
    
    baseline_quality = baseline_results.get("avg_quality_score", 0)
    variant_quality = variant_results.get("avg_quality_score", 0)
    
    baseline_resilience = 1.0 - baseline_results.get("avg_cascade_size", 0)
    variant_resilience = 1.0 - variant_results.get("avg_cascade_size", 0)
    
    # Calculate improvements
    success_improvement = variant_success - baseline_success
    quality_improvement = variant_quality - baseline_quality
    resilience_improvement = variant_resilience - baseline_resilience
    
    # Overall improvement score
    improvement_score = (success_improvement * 0.4 + 
                          quality_improvement * 0.3 + 
                          resilience_improvement * 0.3)
    
    print(f"Success Rate: Baseline {baseline_success:.1%} → Variant {variant_success:.1%} ({success_improvement:+.1%})")
    print(f"Quality Score: Baseline {baseline_quality:.2f} → Variant {variant_quality:.2f} ({quality_improvement:+.2f})")
    print(f"Resilience: Baseline {baseline_resilience:.2f} → Variant {variant_resilience:.2f} ({resilience_improvement:+.2f})")
    print(f"Overall Improvement: {improvement_score:+.3f}")
    print()
    
    # Check against thresholds
    variant_better = (
        variant_success >= experiment_config["success_threshold"] and
        variant_quality >= experiment_config["quality_threshold"] and
        variant_resilience >= experiment_config["resilience_threshold"]
    )
    
    clearly_better = (
        variant_better and
        improvement_score > 0.05  # 5% minimum improvement
    )
    
    print("THRESHOLD EVALUATION:")
    print("-" * 50)
    print(f"Success Threshold (≥{experiment_config['success_threshold']:.0%}): {'✅ MET' if variant_success >= experiment_config['success_threshold'] else '❌ MISSED'}")
    print(f"Quality Threshold (≥{experiment_config['quality_threshold']:.0%}): {'✅ MET' if variant_quality >= experiment_config['quality_threshold'] else '❌ MISSED'}")
    print(f"Resilience Threshold (≥{experiment_config['resilience_threshold']:.0%}): {'✅ MET' if variant_resilience >= experiment_config['resilience_threshold'] else '❌ MISSED'}")
    print()
    print(f"Overall: {'✅ ALL THRESHOLDS MET' if variant_better else '❌ SOME THRESHOLDS MISSED'}")
    print(f"Clear Improvement: {'✅ YES' if clearly_better else '❌ NO'}")
    print()
    
    # Generate recommendation
    if clearly_better:
        recommendation = "STRONGLY_RECOMMENDED - Shallow hierarchy shows clear benefits"
        next_action = "Consider controlled rollout for documentation tasks"
        decision = "PROMOTE_TO_CONTROLLED_ROLLOUT"
    elif variant_better:
        recommendation = "CONSIDER - Shallow hierarchy meets thresholds"
        next_action = "Run larger experiment before deciding"
        decision = "GATHER_MORE_DATA"
    else:
        recommendation = "NOT_RECOMMENDED - Current topology remains superior"
        next_action = "Keep current topology, focus on other optimizations"
        decision = "MAINTAIN_STATUS_QUO"
    
    print("RECOMMENDATION:")
    print("-" * 50)
    print(f"Decision: {recommendation}")
    print(f"Next Action: {next_action}")
    print()
    
    # Save experiment results
    experiment_results = {
        "experiment_id": variant_exp_id,
        "experiment_type": "topology",
        "topology_variant": experiment_config["variant_topology"].value,
        "task_types": experiment_config["task_types"],
        "task_count": len(experiment_config["task_ids"]),
        "thresholds": {
            "success": experiment_config["success_threshold"],
            "quality": experiment_config["quality_threshold"],
            "resilience": experiment_config["resilience_threshold"]
        },
        "baseline": {
            "experiment_id": baseline_exp_id,
            "success_rate": baseline_success,
            "quality_score": baseline_quality,
            "resilience_score": baseline_resilience
        },
        "variant": {
            "experiment_id": variant_exp_id,
            "success_rate": variant_success,
            "quality_score": variant_quality,
            "resilience_score": variant_resilience
        },
        "comparison": {
            "success_improvement": success_improvement,
            "quality_improvement": quality_improvement,
            "resilience_improvement": resilience_improvement,
            "overall_improvement": improvement_score,
            "variant_better": variant_better,
            "clearly_better": clearly_better
        },
        "recommendation": recommendation,
        "next_action": next_action,
        "decision": decision,
        "date": datetime.now().isoformat()
    }
    
    with open("single_topology_experiment_results.json", 'w') as f:
        json.dump(experiment_results, f, indent=2)
    
    print(f"✅ Results saved to single_topology_experiment_results.json")
    
    # Clean up active experiment marker
    try:
        import os
        if os.path.exists("active_topology_experiment.json"):
            os.remove("active_topology_experiment.json")
    except:
        pass
    
    print()
    print("=" * 70)
    print("SINGLE TOPOLOGY EXPERIMENT COMPLETE")
    print(f"Result: {recommendation}")
    print(f"Next: {next_action}")
    print("=" * 70)
    
    return experiment_results

if __name__ == "__main__":
    run_single_topology_experiment()
