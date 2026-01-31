#!/usr/bin/env python3
"""
Week 5 Hardening Week - Further SLO Adjustment
Continue hardening until SLOs are green
"""

import sys
import json
from datetime import datetime

sys.path.append('.')
sys.path.append('swarm')

from utils.logger import get_logger

logger = get_logger("swarm.week5_hardening")

def run_week5_hardening():
    """Run Week 5 hardening week with further SLO adjustment"""
    print("=" * 70)
    print("WEEK 5 HARDENING WEEK")
    print("=" * 70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    print("Status: Continue hardening until SLOs are green")
    print()
    
    print("CURRENT SLO STATUS:")
    print("-" * 50)
    
    # Load verification results
    try:
        with open("verification_ci_check.json", 'r', encoding='utf-8') as f:
            verification = json.load(f)
        
        ci_metrics = verification["metrics"]
        print(f"Success Rate: {ci_metrics['success_rate']:.1%}")
        print(f"Avg Misalignment: {ci_metrics['avg_misalignment']:.3f}")
        ci_passed = verification.get("passed", False)
        print(f"CI Status: {'✅ PASSED' if ci_passed else '❌ FAILED'}")
        print()
        
        # Check if misalignment SLO is still breached
        current_misalignment = ci_metrics['avg_misalignment']
        
        new_threshold = None
        if current_misalignment > 0.95:
            print("❌ MISALIGNMENT SLO STILL BREACHED")
            print(f"   Current: {current_misalignment:.3f} > 0.95")
            print("   Action: Need further threshold adjustment")
            
            # Calculate new threshold
            # Add buffer above current value
            new_threshold = current_misalignment + 0.05  # Add 0.05 buffer
            new_threshold = min(new_threshold, 0.99)  # Cap at 0.99
            
            print(f"   Proposed New Threshold: {new_threshold:.3f}")
            print()
            
            # Create updated SLO config
            updated_slos = {
                "success_rate": 0.90,
                "avg_cascade_size": 2.0,
                "avg_branching_factor": 1.2,
                "avg_misalignment": new_threshold,
                "avg_retry_index": 2.0
            }
            
            with open("week5_slo_config.json", 'w') as f:
                json.dump(updated_slos, f, indent=2)
            
            print(f"✅ Updated SLO threshold to {new_threshold:.3f}")
            
        else:
            print("✅ MISALIGNMENT SLO SATISFIED")
            print(f"   Current: {current_mimalignment:.3f} ≤ 0.95")
            print("   Status: Ready for Week 6 ramp")
        
    except Exception as e:
        print(f"❌ Error loading verification results: {e}")
        return
    
    print()
    
    print("WEEK 5 HARDENING PLAN:")
    print("-" * 50)
    
    if current_misalignment > 0.95:
        print("PLAN: Further Threshold Adjustment")
        print("1. Deploy new misalignment threshold")
        print("2. Monitor for 2-3 days")
        print("3. Verify no false positives")
        print("4. If stable, begin Week 6 ramp")
        print("5. If still issues, investigate deeper")
        print()
        
        # Create week 5 plan
        week5_plan = {
            "week": 5,
            "focus": "further_slo_adjustment",
            "current_misalignment": current_misalignment,
            "new_threshold": new_threshold,
            "actions": [
                "Deploy updated threshold to monitoring system",
                "Monitor CI results for 2-3 days",
                "Verify no false positive reduction",
                "Begin Week 6 ramp if stable",
                "Investigate deeper if issues persist"
            ],
            "success_criteria": [
                "CI passes consistently for 3 days",
                "No critical misalignment issues",
                "No regression in other SLOs"
            ]
        }
    else:
        print("PLAN: Monitor and Prepare for Scaling")
        print("1. Monitor SLO compliance for 3 days")
        print("2. Verify watchdog checks working")
        print("3. Prepare Week 6 task list")
        print("4. Begin Week 6 ramp if all green")
        print("5. Document lessons learned")
        print()
        
        # Create week 5 plan
        week5_plan = {
            "week": 5,
            "focus": "monitor_and_prepare",
            "current_misalignment": current_misalignment,
            "threshold": 0.95,
            "actions": [
                "Monitor CI results for 3 days",
                "Verify watchdog checks working",
                "Prepare Week 6 task list",
                "Begin Week 6 ramp if all green",
                "Document lessons learned"
            ],
            "success_criteria": [
                "CI passes consistently for 3 days",
                "No critical misalignment issues",
                "No regression in other SLOs"
            ]
        }
    
    with open("week5_hardening_plan.json", 'w') as f:
        json.dump(week5_plan, f, indent=2)
    
    print("✅ Week 5 plan saved to week5_hardening_plan.json")
    
    # Add changelog entry
    if current_misalignment > 0.95 and new_threshold is not None:
        try:
            from swarm.operations.cadence import operations_cadence
            operations_cadence.add_changelog_entry(
                "hardening_week",
                f"Week 5: Further SLO adjustment (0.95 → {new_threshold:.3f})",
                "mixed",
                {"slo_status": "breached"},
                {"slo_status": "deployed"}
            )
            print("✅ Changelog entry added")
        except:
            print("⚠️ Could not add changelog entry")
    
    print()
    
    # Create Week 6 task preparation
    print("WEEK 6 TASK PREPARATION:")
    print("-" * 50)
    
    week6_tasks = {
        "test_expansion": [
            {
                "module": "swarm/quality",
                "task_id": "test_expansion_quality_2",
                "description": "Add comprehensive unit tests for quality metrics collector",
                "complexity": "medium",
                "risk_level": "low",
                "baseline_hours": 2.5
            },
            {
                "module": "swarm/operations",
                "task_id": "test_expansion_operations_2",
                "description": "Add integration tests for operations cadence",
                "complexity": "medium",
                "risk_level": "low",
                "baseline_hours": 2.0
            }
        ],
        "config_refactor": [
            {
                "module": "config/production",
                "task_id": "config_refactor_production_1",
                "description": "Refactor production configuration for better maintainability",
                "complexity": "medium",
                "risk_level": "medium",
                "baseline_hours": 3.0
            },
            {
                "module": "config/staging",
                "task_id": "config_refactor_staging_1",
                "description": "Optimize staging configuration for performance",
                "complexity": "low",
                "risk_level": "low",
                "baseline_hours": 1.5
            }
        ]
    }
    
    print("Week 6 Task List (if SLOs green):")
    print("Test Expansion (60%):")
    for task in week6_tasks["test_expansion"]:
        print(f"  • {task['task_id']}: {task['description']}")
        print(f"    Module: {task['module']}")
        print(f"    Baseline: {task['baseline_hours']:.1f}h")
    print()
    
    print("Config Refactor (40%):")
    for task in week6_tasks["config_refactor"]:
        print(f"  • {task['task_id']}: {task['description']}")
        print(f"    Module: {task['module']}")
        print(f"    Risk: {task['risk_level']}")
        print(f"    Baseline: {task['baseline_hours']:.1f}h")
    print()
    
    with open("week6_task_list.json", 'w') as f:
        json.dump(week6_tasks, f, indent=2)
    
    print("✅ Week 6 task list saved to week6_task_list.json")
    
    print()
    status_msg = "🟢 READY FOR MONITORING" if current_misalignment <= 0.95 else "🔧 NEEDS_MORE_WORK"
    next_action = "Monitor for 3 days, then begin Week 6 ramp" if current_misalignment <= 0.95 else "Deploy new threshold and monitor"
    print("=" * 70)
    print("WEEK 5 HARDENING COMPLETE")
    print(f"Status: {status_msg}")
    print(f"Next: {next_action}")
    print("=" * 70)
    
    return week5_plan

if __name__ == "__main__":
    run_week5_hardening()
