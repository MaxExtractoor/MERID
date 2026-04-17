#!/usr/bin/env python3
"""
Week 4: Scale Test Expansion - Controlled Batch 2
Proven use case expansion with strict quality gates
"""

import sys
import json
from datetime import datetime

sys.path.append('.')
sys.path.append('swarm')

from swarm.integration.task_runner import task_runner
from swarm.roi.tracker import roi_tracker, ImprovementType
from swarm.operations.cadence import operations_cadence
from utils.logger import get_logger

logger = get_logger("swarm.scale_test_expansion")

def create_batch_2_test_tasks():
    """Create batch 2 test expansion tasks for controlled scaling"""
    tasks = []
    
    # Module 1: swarm/quality module (medium risk, high test debt)
    task1 = {
        "task_id": "test_expansion_quality_1",
        "type": "testing",
        "description": "Add comprehensive unit tests for swarm/quality/metrics_collector.py",
        "complexity": "medium",
        "module": "swarm/quality",
        "risk_level": "medium",
        "agents": [
            {"id": "test_planner_q1", "role": "planner", "tools": ["code_analyzer", "test_planner"]},
            {"id": "test_implementer_q1", "role": "implementer", "tools": ["test_generator", "mock_builder"]},
            {"id": "test_reviewer_q1", "role": "reviewer", "tools": ["test_validator", "quality_checker"]}
        ],
        "expected_duration": 150.0,  # 2.5 hours baseline
        "target_coverage": 0.80,
        "target_tests": 15
    }
    tasks.append(task1)
    
    # Module 2: swarm/operations module (low risk, operational importance)
    task2 = {
        "task_id": "test_expansion_operations_1",
        "type": "testing",
        "description": "Add integration tests for swarm/operations/cadence.py",
        "complexity": "medium",
        "module": "swarm/operations",
        "risk_level": "low",
        "agents": [
            {"id": "test_planner_o1", "role": "planner", "tools": ["system_analyzer", "test_planner"]},
            {"id": "test_implementer_o1", "role": "implementer", "tools": ["test_generator", "fixture_builder"]},
            {"id": "test_reviewer_o1", "role": "reviewer", "tools": ["test_validator", "integration_checker"]}
        ],
        "expected_duration": 120.0,  # 2 hours baseline
        "target_coverage": 0.75,
        "target_tests": 12
    }
    tasks.append(task2)
    
    return tasks

def run_batch_2_scaling():
    """Run batch 2 test expansion with strict quality gates"""
    print("=" * 70)
    print("WEEK 4: SCALE TEST EXPANSION - BATCH 2")
    print("=" * 70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    print("Strategy: Controlled scaling of proven use case")
    print()
    
    # Create batch 2 tasks
    tasks = create_batch_2_test_tasks()
    
    # Define scaling targets
    scaling_targets = {
        "total_hours_saved": 5.0,  # Minimum 5 hours saved
        "avg_roi_score": 85.0,    # Minimum 85/100 ROI
        "quality_improvement": 0.5,  # Minimum 0.5 quality improvement
        "success_rate": 0.9,       # Minimum 90% success rate
        "zero_incidents": True      # Zero incidents
    }
    
    print("SCALING TARGETS:")
    print("-" * 40)
    for target, value in scaling_targets.items():
        print(f"  • {target}: {value}")
    print()
    
    # Define baseline human effort
    baseline_effort = {
        "test_expansion_quality_1": 2.5,
        "test_expansion_operations_1": 2.0
    }
    
    print("BASELINE HUMAN EFFORT:")
    print("-" * 40)
    total_baseline = sum(baseline_effort.values())
    for task_id, hours in baseline_effort.items():
        print(f"  {task_id}: {hours:.1f} hours")
    print(f"  Total baseline: {total_baseline:.1f} hours")
    print()
    
    # Quality gate check before starting
    print("QUALITY GATES CHECK:")
    print("-" * 40)
    
    # Check current SLO compliance
    try:
        with open("week3_review_log.json", 'r') as f:
            week3_data = json.load(f)
        
        slo_score = week3_data.get("slo_score", 0)
        slo_compliance = week3_data.get("slo_compliance", {})
        
        print(f"  • SLO Score: {slo_score:.1f}/100")
        print(f"  • SLO Status: {'✅ COMPLIANT' if slo_score >= 80 else '❌ NEEDS ATTENTION'}")
        
        # Check if any critical SLOs are failing
        critical_slos = ["success_rate", "cascade_size", "branching_factor"]
        critical_failures = [slo for slo in critical_slos if not slo_compliance.get(slo, True)]
        
        if critical_failures:
            print(f"  • Critical SLO failures: {critical_failures}")
            print("  • Decision: ❌ STOP SCALING - Fix critical SLOs first")
            return {"status": "stopped", "reason": "critical_slo_failures", "failed_slos": critical_failures}
        
        print("  • Decision: ✅ PROCEED WITH SCALING")
        
    except Exception as e:
        print(f"  • Error loading SLO data: {e}")
        print("  • Decision: ⚠️  PROCEED WITH CAUTION")
    
    print()
    
    # Run batch 2 tasks
    print("RUNNING BATCH 2 TASKS:")
    print("-" * 40)
    
    batch_results = []
    total_time_saved = 0
    successful_tasks = 0
    
    for task_config in tasks:
        task_id = task_config["task_id"]
        expected_human_time = baseline_effort[task_id]
        
        print(f"\nTask: {task_id}")
        print(f"Module: {task_config['module']}")
        print(f"Risk Level: {task_config['risk_level']}")
        print(f"Baseline effort: {expected_human_time:.1f} hours")
        
        # Track with ROI tracker
        roi_task = roi_tracker.track_improvement_task(
            task_config, 
            ImprovementType.TEST_EXPANSION,
            expected_human_time
        )
        
        print(f"Swarm execution: {roi_task.swarm_metrics['execution_time']:.2f}s")
        print(f"Success: {'✅' if roi_task.swarm_metrics['success'] else '❌'}")
        print(f"ROI Score: {roi_task.roi_score:.1f}/100")
        print(f"Quality Improvement: {roi_task.quality_improvement_score:+.2f}")
        
        if roi_task.swarm_metrics["success"]:
            time_saved = expected_human_time - (roi_task.swarm_metrics["execution_time"] / 3600)
            total_time_saved += time_saved
            successful_tasks += 1
            print(f"Time saved: {time_saved:.2f} hours")
            
            # Check if task meets quality gates
            quality_gate_met = (
                roi_task.roi_score >= scaling_targets["avg_roi_score"] and
                roi_task.quality_improvement_score >= scaling_targets["quality_improvement"]
            )
            
            print(f"Quality Gate: {'✅ PASSED' if quality_gate_met else '❌ FAILED'}")
            
            if not quality_gate_met:
                print(f"  • ROI Score: {roi_task.roi_score:.1f} < {scaling_targets['avg_roi_score']}")
                print(f"  • Quality: {roi_task.quality_improvement_score:.2f} < {scaling_targets['quality_improvement']}")
        else:
            print(f"Time saved: 0.0 hours (task failed)")
        
        batch_results.append(roi_task)
    
    print()
    
    # Evaluate batch results against targets
    print("BATCH 2 EVALUATION:")
    print("-" * 40)
    
    success_rate = successful_tasks / len(tasks)
    avg_roi_score = sum(r.roi_score for r in batch_results) / len(batch_results)
    avg_quality_improvement = sum(r.quality_improvement_score for r in batch_results) / len(batch_results)
    
    print(f"Tasks completed: {successful_tasks}/{len(tasks)} ({success_rate:.1%})")
    print(f"Total time saved: {total_time_saved:.1f} hours")
    print(f"Target time saved: {scaling_targets['total_hours_saved']:.1f} hours")
    print(f"Time saved target: {'✅ MET' if total_time_saved >= scaling_targets['total_hours_saved'] else '❌ MISSED'}")
    print()
    print(f"Average ROI score: {avg_roi_score:.1f}/100")
    print(f"Target ROI: {scaling_targets['avg_roi_score']:.1f}/100")
    print(f"ROI target: {'✅ MET' if avg_roi_score >= scaling_targets['avg_roi_score'] else '❌ MISSED'}")
    print()
    print(f"Average quality improvement: {avg_quality_improvement:+.2f}")
    print(f"Target quality: {scaling_targets['quality_improvement']:+.2f}")
    print(f"Quality target: {'✅ MET' if avg_quality_improvement >= scaling_targets['quality_improvement'] else '❌ MISSED'}")
    print()
    print(f"Success rate: {success_rate:.1%}")
    print(f"Target success: {scaling_targets['success_rate']:.1%}")
    print(f"Success target: {'✅ MET' if success_rate >= scaling_targets['success_rate'] else '❌ MISSED'}")
    
    # Overall batch decision
    all_targets_met = (
        total_time_saved >= scaling_targets["total_hours_saved"] and
        avg_roi_score >= scaling_targets["avg_roi_score"] and
        avg_quality_improvement >= scaling_targets["quality_improvement"] and
        success_rate >= scaling_targets["success_rate"]
    )
    
    print()
    print("BATCH 2 DECISION:")
    print("-" * 40)
    if all_targets_met:
        print("✅ ALL TARGETS MET - Continue scaling test expansion")
        next_action = "Continue scaling to next batch"
        scaling_status = "successful"
    else:
        print("⚠️  SOME TARGETS MISSED - Optimize before further scaling")
        next_action = "Refine approach and retry"
        scaling_status = "needs_optimization"
    
    print(f"Next Action: {next_action}")
    
    # Save batch results
    batch_data = {
        "batch": 2,
        "date": datetime.now().isoformat(),
        "tasks": [
            {
                "task_id": r.task_id,
                "module": next((t["module"] for t in tasks if t["task_id"] == r.task_id), "unknown"),
                "risk_level": next((t["risk_level"] for t in tasks if t["task_id"] == r.task_id), "unknown"),
                "success": r.swarm_metrics["success"],
                "roi_score": r.roi_score,
                "quality_improvement": r.quality_improvement_score,
                "time_saved": baseline_effort[r.task_id] - (r.swarm_metrics["execution_time"] / 3600 if r.swarm_metrics["success"] else 0)
            }
            for r in batch_results
        ],
        "targets": scaling_targets,
        "results": {
            "total_time_saved": total_time_saved,
            "avg_roi_score": avg_roi_score,
            "avg_quality_improvement": avg_quality_improvement,
            "success_rate": success_rate,
            "all_targets_met": all_targets_met
        },
        "decision": {
            "status": scaling_status,
            "next_action": next_action,
            "continue_scaling": all_targets_met
        }
    }
    
    with open("test_expansion_batch_2_results.json", 'w') as f:
        json.dump(batch_data, f, indent=2)
    
    print(f"\n✅ Batch 2 results saved to test_expansion_batch_2_results.json")
    
    # Add changelog entry
    operations_cadence.add_changelog_entry(
        "scaling",
        f"Test expansion batch 2 - {scaling_status}",
        "improved" if all_targets_met else "mixed",
        {"batch": 1, "total_time_saved": 9.5},
        {"batch": 2, "total_time_saved": total_time_saved}
    )
    
    print("✅ Changelog entry added")
    
    print()
    print("=" * 70)
    print("BATCH 2 COMPLETE")
    print(f"Status: {scaling_status.upper()}")
    print(f"Decision: {next_action}")
    print("=" * 70)
    
    return batch_data

if __name__ == "__main__":
    run_batch_2_scaling()
