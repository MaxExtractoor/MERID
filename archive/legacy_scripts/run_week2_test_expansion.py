#!/usr/bin/env python3
"""
Week 2: First High-ROI Use Case - Automated Test Expansion
Real-world swarm task with ROI tracking
"""

import sys
import json
from datetime import datetime

sys.path.append('.')
sys.path.append('swarm')

from swarm.integration.task_runner import task_runner
from swarm.roi.tracker import roi_tracker, ImprovementType
from utils.logger import get_logger

logger = get_logger("swarm.test_expansion_roi")

def create_test_expansion_tasks():
    """Create real test expansion tasks for ROI tracking"""
    tasks = []
    
    # Task 1: Add unit tests for swarm/tracing module
    task1 = {
        "task_id": "test_expansion_tracing_1",
        "type": "testing",
        "description": "Add comprehensive unit tests for swarm/tracing/tracer.py",
        "complexity": "medium",
        "agents": [
            {"id": "test_planner_1", "role": "planner", "tools": ["code_analyzer", "test_planner"]},
            {"id": "test_implementer_1", "role": "implementer", "tools": ["test_generator", "code_writer"]},
            {"id": "test_reviewer_1", "role": "reviewer", "tools": ["test_validator", "coverage_checker"]}
        ],
        "expected_duration": 120.0,
        "files_to_test": [
            "swarm/tracing/tracer.py",
            "swarm/tracing/span.py"
        ],
        "target_coverage": 0.85
    }
    tasks.append(task1)
    
    # Task 2: Add integration tests for watchdog system
    task2 = {
        "task_id": "test_expansion_watchdog_1", 
        "type": "testing",
        "description": "Add integration tests for swarm/watchdog/monitor.py",
        "complexity": "medium",
        "agents": [
            {"id": "test_planner_2", "role": "planner", "tools": ["code_analyzer", "test_planner"]},
            {"id": "test_implementer_2", "role": "implementer", "tools": ["test_generator", "mock_builder"]},
            {"id": "test_reviewer_2", "role": "reviewer", "tools": ["test_validator", "integration_checker"]}
        ],
        "expected_duration": 90.0,
        "files_to_test": [
            "swarm/watchdog/monitor.py",
            "swarm/watchdog/enhanced_monitor.py"
        ],
        "target_coverage": 0.80
    }
    tasks.append(task2)
    
    # Task 3: Add end-to-end tests for CI reliability
    task3 = {
        "task_id": "test_expansion_ci_1",
        "type": "testing", 
        "description": "Add end-to-end tests for CI reliability monitoring",
        "complexity": "low",
        "agents": [
            {"id": "test_planner_3", "role": "planner", "tools": ["system_analyzer", "test_planner"]},
            {"id": "test_implementer_3", "role": "implementer", "tools": ["e2e_generator", "fixture_builder"]},
            {"id": "test_reviewer_3", "role": "reviewer", "tools": ["test_validator", "system_checker"]}
        ],
        "expected_duration": 60.0,
        "files_to_test": [
            "swarm/ci/reliability_monitor.py"
        ],
        "target_coverage": 0.75
    }
    tasks.append(task3)
    
    return tasks

def run_test_expansion_roi_experiment():
    """Run the test expansion ROI experiment"""
    print("=" * 70)
    print("WEEK 2: TEST EXPANSION ROI EXPERIMENT")
    print("=" * 70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    print("Use Case: Automated Test Expansion")
    print("Target: 30-50% time reduction with equal/higher quality")
    print()
    
    # Create tasks
    tasks = create_test_expansion_tasks()
    
    # Define baseline human effort
    baseline_effort = {
        "test_expansion_tracing_1": 4.0,  # 4 hours for comprehensive tracing tests
        "test_expansion_watchdog_1": 3.5,  # 3.5 hours for watchdog integration tests  
        "test_expansion_ci_1": 2.0  # 2 hours for CI e2e tests
    }
    
    print("BASELINE HUMAN EFFORT:")
    print("-" * 40)
    total_baseline = 0
    for task_id, hours in baseline_effort.items():
        print(f"  {task_id}: {hours:.1f} hours")
        total_baseline += hours
    print(f"  Total baseline: {total_baseline:.1f} hours")
    print()
    
    # Run tasks through swarm
    print("RUNNING SWARM TASKS:")
    print("-" * 40)
    
    roi_results = []
    total_time_saved = 0
    
    for task_config in tasks:
        task_id = task_config["task_id"]
        expected_human_time = baseline_effort[task_id]
        
        print(f"\nTask: {task_id}")
        print(f"Description: {task_config['description']}")
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
            print(f"Time saved: {time_saved:.2f} hours")
        else:
            print(f"Time saved: 0.0 hours (task failed)")
        
        roi_results.append(roi_task)
    
    print()
    
    # Calculate overall results
    print("OVERALL RESULTS:")
    print("-" * 40)
    
    successful_tasks = [r for r in roi_results if r.swarm_metrics["success"]]
    success_rate = len(successful_tasks) / len(roi_results)
    
    avg_roi_score = sum(r.roi_score for r in roi_results) / len(roi_results)
    avg_quality_improvement = sum(r.quality_improvement_score for r in roi_results) / len(roi_results)
    
    print(f"Tasks completed: {len(successful_tasks)}/{len(roi_results)} ({success_rate:.1%})")
    print(f"Total baseline time: {total_baseline:.1f} hours")
    print(f"Total time saved: {total_time_saved:.1f} hours")
    print(f"Time reduction: {(total_time_saved / total_baseline):.1%}")
    print(f"Average ROI score: {avg_roi_score:.1f}/100")
    print(f"Average quality improvement: {avg_quality_improvement:+.2f}")
    
    # Check if we met targets
    time_reduction_target = 0.30  # 30% minimum
    quality_target = 0.0  # At least neutral quality
    
    time_reduction_met = (total_time_saved / total_baseline) >= time_reduction_target
    quality_met = avg_quality_improvement >= quality_target
    
    print()
    print("TARGET ACHIEVEMENT:")
    print("-" * 40)
    print(f"Time reduction target (≥30%): {'✅ MET' if time_reduction_met else '❌ NOT MET'}")
    print(f"Quality target (≥0): {'✅ MET' if quality_met else '❌ NOT MET'}")
    print(f"Overall success: {'✅ SUCCESS' if time_reduction_met and quality_met else '❌ NEEDS IMPROVEMENT'}")
    
    # Get productivity impact
    print()
    print("PRODUCTIVITY IMPACT:")
    print("-" * 40)
    
    productivity_impact = roi_tracker.get_productivity_impact()
    if "error" not in productivity_impact:
        print(f"Total tasks completed by swarm: {productivity_impact['total_tasks_completed']}")
        print(f"Total human time saved: {productivity_impact['total_human_time_saved_hours']:.1f} hours")
        print(f"Average time saved per task: {productivity_impact['avg_time_saved_per_task_hours']:.1f} hours")
        print(f"Average ROI score: {productivity_impact['avg_roi_score']:.1f}/100")
    
    # Save results
    results_data = {
        "experiment": "test_expansion_roi_week2",
        "date": datetime.now().isoformat(),
        "baseline_effort_hours": total_baseline,
        "swarm_results": {
            "tasks_completed": len(successful_tasks),
            "total_tasks": len(roi_results),
            "success_rate": success_rate,
            "time_saved_hours": total_time_saved,
            "time_reduction_percentage": (total_time_saved / total_baseline),
            "avg_roi_score": avg_roi_score,
            "avg_quality_improvement": avg_quality_improvement
        },
        "targets_met": {
            "time_reduction": time_reduction_met,
            "quality": quality_met,
            "overall": time_reduction_met and quality_met
        },
        "individual_results": [
            {
                "task_id": r.task_id,
                "success": r.swarm_metrics["success"],
                "roi_score": r.roi_score,
                "quality_improvement": r.quality_improvement_score,
                "time_saved": baseline_effort[r.task_id] - (r.swarm_metrics["execution_time"] / 3600 if r.swarm_metrics["success"] else 0)
            }
            for r in roi_results
        ]
    }
    
    with open("week2_test_expansion_results.json", 'w') as f:
        json.dump(results_data, f, indent=2)
    
    print(f"\n✅ Results saved to week2_test_expansion_results.json")
    
    # Add changelog entry
    from swarm.operations.cadence import operations_cadence
    operations_cadence.add_changelog_entry(
        "roi_experiment",
        f"Test expansion ROI experiment - {len(successful_tasks)}/{len(roi_results)} tasks successful",
        "improved" if time_reduction_met and quality_met else "mixed",
        {"time_reduction": 0, "quality_score": 0},
        {"time_reduction": (total_time_saved / total_baseline), "quality_score": avg_quality_improvement}
    )
    
    print("✅ Changelog entry added")
    
    print()
    print("=" * 70)
    print("WEEK 2 EXPERIMENT COMPLETE")
    if time_reduction_met and quality_met:
        print("RESULT: ✅ SUCCESS - Ready to scale test expansion usage")
    else:
        print("RESULT: ⚠️  MIXED - Optimize before scaling")
    print("=" * 70)
    
    return results_data

if __name__ == "__main__":
    run_test_expansion_roi_experiment()
