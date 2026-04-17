#!/usr/bin/env python3
"""
Scaling Plan - Reach 40h/month Goal
Controlled volume increase after SLO fix
"""

import sys
import json
import sqlite3
from datetime import datetime, timedelta

sys.path.append('.')
sys.path.append('swarm')

from utils.logger import get_logger

logger = get_logger("swarm.scaling_plan")

def compute_volume_requirements():
    """Compute required task volume to hit 40h/month goal"""
    print("=" * 70)
    print("SCALING PLAN - REACH 40H/MONTH GOAL")
    print("=" * 70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    print("Strategy: Controlled volume increase after SLO fix")
    print()
    
    print("VOLUME REQUIREMENTS ANALYSIS:")
    print("-" * 50)
    
    # Get current performance data
    try:
        conn = sqlite3.connect("per_task_roi.db")
        cursor = conn.cursor()
        
        # Get average hours saved per task
        cursor.execute("""
            SELECT 
                AVG(human_time_saved_hours) as avg_hours_saved,
                COUNT(*) as total_tasks,
                SUM(human_time_saved_hours) as total_hours_saved,
                AVG(roi_score) as avg_roi_score
            FROM per_task_roi
        """)
        
        result = cursor.fetchone()
        
        if result and result[0]:
            avg_hours_per_task = result[0]
            total_tasks = result[1]
            total_hours_saved = result[2]
            avg_roi_score = result[3]
            
            print(f"Current Performance:")
            print(f"  • Average hours saved per task: {avg_hours_per_task:.2f}h")
            print(f"  • Total tasks completed: {total_tasks}")
            print(f"  • Total hours saved: {total_hours_saved:.1f}h")
            print(f"  • Average ROI score: {avg_roi_score:.1f}/100")
            print()
            
            # Calculate required volume
            target_hours_per_month = 40
            tasks_needed_per_month = target_hours_per_month / avg_hours_per_task
            
            print(f"Target: {target_hours_per_month}h/month")
            print(f"Required tasks per month: {tasks_needed_per_month:.1f}")
            print(f"Required tasks per week: {tasks_needed_per_month/4:.1f}")
            print()
            
            # Calculate scaling factor
            current_monthly_tasks = total_tasks  # Assuming current month
            scaling_factor = tasks_needed_per_month / current_monthly_tasks if current_monthly_tasks > 0 else tasks_needed_per_month
            
            print(f"Scaling Analysis:")
            print(f"  • Current monthly tasks: {current_monthly_tasks}")
            print(f"  • Target monthly tasks: {tasks_needed_per_month:.1f}")
            print(f"  • Scaling factor: {scaling_factor:.1f}x")
            print()
            
            # Create ramp schedule
            ramp_schedule = {
                "current": {
                    "week": "Current",
                    "tasks_per_week": current_monthly_tasks / 4,
                    "hours_per_month": total_hours_saved,
                    "status": "baseline"
                },
                "week_6": {
                    "week": "Week 6",
                    "tasks_per_week": 2,  # Conservative start
                    "hours_per_month": 2 * 4 * avg_hours_per_task,
                    "status": "ramp_start"
                },
                "week_7": {
                    "week": "Week 7",
                    "tasks_per_week": 3,
                    "hours_per_month": 3 * 4 * avg_hours_per_task,
                    "status": "ramp_continue"
                },
                "week_8": {
                    "week": "Week 8",
                    "tasks_per_week": 4,
                    "hours_per_month": 4 * 4 * avg_hours_per_task,
                    "status": "ramp_accelerate"
                },
                "week_9": {
                    "week": "Week 9",
                    "tasks_per_week": 5,
                    "hours_per_month": 5 * 4 * avg_hours_per_task,
                    "status": "target_approach"
                },
                "week_10": {
                    "week": "Week 10",
                    "tasks_per_week": tasks_needed_per_month / 4,
                    "hours_per_month": target_hours_per_month,
                    "status": "target_reached"
                }
            }
            
            print("RAMP SCHEDULE:")
            print("-" * 50)
            for week_key, week_data in ramp_schedule.items():
                print(f"{week_data['week']}:")
                print(f"  • Tasks per week: {week_data['tasks_per_week']:.1f}")
                print(f"  • Hours per month: {week_data['hours_per_month']:.1f}h")
                print(f"  • Status: {week_data['status']}")
                print()
            
            # Calculate weekly task distribution by use case
            primary_use_cases = ["test_expansion", "config_refactor"]
            
            weekly_distribution = {}
            for week_key in ["week_6", "week_7", "week_8", "week_9", "week_10"]:
                week_tasks = ramp_schedule[week_key]["tasks_per_week"]
                weekly_distribution[week_key] = {
                    "test_expansion": week_tasks * 0.6,  # 60% test expansion
                    "config_refactor": week_tasks * 0.4   # 40% config refactor
                }
            
            print("WEEKLY TASK DISTRIBUTION:")
            print("-" * 50)
            for week_key, distribution in weekly_distribution.items():
                print(f"{ramp_schedule[week_key]['week']}:")
                print(f"  • Test Expansion: {distribution['test_expansion']:.1f} tasks")
                print(f"  • Config Refactor: {distribution['config_refactor']:.1f} tasks")
                print()
            
            # Create scaling plan
            scaling_plan = {
                "target_hours_per_month": target_hours_per_month,
                "avg_hours_per_task": avg_hours_per_task,
                "tasks_needed_per_month": tasks_needed_per_month,
                "tasks_needed_per_week": tasks_needed_per_month / 4,
                "scaling_factor": scaling_factor,
                "ramp_schedule": ramp_schedule,
                "weekly_distribution": weekly_distribution,
                "success_criteria": {
                    "slo_compliance": "All SLOs green (misalignment < 0.95)",
                    "roi_threshold": "Average ROI ≥ 85/100",
                    "quality_threshold": "Quality improvement ≥ 0.3",
                    "incident_threshold": "Zero production incidents"
                },
                "risk_mitigation": {
                    "freeze_if_slos_fail": "Pause scaling immediately if SLOs breach",
                    "reduce_if_roi_drops": "Reduce volume if ROI < 85/100",
                    "monitor_quality": "Track quality improvements closely",
                    "weekly_checkpoints": "Review metrics every Friday"
                }
            }
            
            print("SUCCESS CRITERIA:")
            print("-" * 50)
            criteria = scaling_plan["success_criteria"]
            print(f"• SLO Compliance: {criteria['slo_compliance']}")
            print(f"• ROI Threshold: {criteria['roi_threshold']}")
            print(f"• Quality Threshold: {criteria['quality_threshold']}")
            print(f"• Incident Threshold: {criteria['incident_threshold']}")
            print()
            
            print("RISK MITIGATION:")
            print("-" * 50)
            mitigation = scaling_plan["risk_mitigation"]
            print(f"• SLO Freeze: {mitigation['freeze_if_slos_fail']}")
            print(f"• ROI Guard: {mitigation['reduce_if_roi_drops']}")
            print(f"• Quality Monitor: {mitigation['monitor_quality']}")
            print(f"• Checkpoints: {mitigation['weekly_checkpoints']}")
            print()
            
            return scaling_plan
            
        else:
            print("No ROI data available - using estimates")
            
            # Estimate based on typical values
            estimated_hours_per_task = 2.5  # Conservative estimate
            tasks_needed_per_month = 40 / estimated_hours_per_task
            
            print(f"ESTIMATED REQUIREMENTS:")
            print(f"  • Estimated hours per task: {estimated_hours_per_task}h")
            print(f"  • Tasks needed per month: {tasks_needed_per_month:.1f}")
            print(f"  • Tasks needed per week: {tasks_needed_per_month/4:.1f}")
            print()
            
            return {"status": "estimated", "tasks_needed_per_month": tasks_needed_per_month}
            
    except Exception as e:
        print(f"Error analyzing volume requirements: {e}")
        return {"error": str(e)}

def create_scaling_roadmap(scaling_plan):
    """Create detailed scaling roadmap"""
    print("CREATING SCALING ROADMAP:")
    print("-" * 50)
    
    roadmap = {
        "title": "MERID Swarm Scaling Roadmap",
        "goal": "Reach 40 dev hours/month saved",
        "duration": "5 weeks (Weeks 6-10)",
        "status": "ready_to_execute",
        
        "preconditions": [
            "SLO compliance achieved (misalignment < 0.95)",
            "Hardening sprint completed successfully",
            "ROI logging system operational",
            "Weekly no-thrash enforcement active"
        ],
        
        "weekly_plan": {
            "week_6": {
                "focus": "Controlled ramp start",
                "tasks_per_week": 2,
                "distribution": {"test_expansion": 1.2, "config_refactor": 0.8},
                "success_metrics": {
                    "slo_compliance": "Green",
                    "roi_score": "≥ 90/100",
                    "quality_improvement": "≥ 0.3"
                },
                "risk_mitigation": "Pause if SLOs breach"
            },
            "week_7": {
                "focus": "Volume increase",
                "tasks_per_week": 3,
                "distribution": {"test_expansion": 1.8, "config_refactor": 1.2},
                "success_metrics": {
                    "slo_compliance": "Green",
                    "roi_score": "≥ 90/100",
                    "quality_improvement": "≥ 0.3"
                },
                "risk_mitigation": "Reduce volume if ROI < 85/100"
            },
            "week_8": {
                "focus": "Acceleration",
                "tasks_per_week": 4,
                "distribution": {"test_expansion": 2.4, "config_refactor": 1.6},
                "success_metrics": {
                    "slo_compliance": "Green",
                    "roi_score": "≥ 90/100",
                    "quality_improvement": "≥ 0.3"
                },
                "risk_mitigation": "Monitor quality trends closely"
            },
            "week_9": {
                "focus": "Target approach",
                "tasks_per_week": 5,
                "distribution": {"test_expansion": 3.0, "config_refactor": 2.0},
                "success_metrics": {
                    "slo_compliance": "Green",
                    "roi_score": "≥ 90/100",
                    "quality_improvement": "≥ 0.3"
                },
                "risk_mitigation": "Prepare for target volume"
            },
            "week_10": {
                "focus": "Target achievement",
                "tasks_per_week": scaling_plan.get("tasks_needed_per_week", 5),
                "distribution": {"test_expansion": scaling_plan.get("tasks_needed_per_week", 5) * 0.6, "config_refactor": scaling_plan.get("tasks_needed_per_week", 5) * 0.4},
                "success_metrics": {
                    "slo_compliance": "Green",
                    "roi_score": "≥ 90/100",
                    "quality_improvement": "≥ 0.3",
                    "monthly_hours_saved": "≥ 40h"
                },
                "risk_mitigation": "Maintain target volume"
            }
        },
        
        "monitoring": {
            "daily": "Track task completion and basic metrics",
            "weekly": "Full SLO, ROI, and quality review",
            "monthly": "Quarter goal progress assessment"
        },
        
        "decision_points": {
            "continue_scaling": "All SLOs green AND ROI ≥ 85/100",
            "pause_scaling": "Any SLO breach OR ROI < 85/100",
            "reduce_volume": "Quality improvement < 0.3 OR incidents detected",
            "emergency_stop": "Production incidents OR critical SLO failures"
        }
    }
    
    with open("scaling_roadmap.json", 'w') as f:
        json.dump(roadmap, f, indent=2)
    
    print("✅ Scaling roadmap saved to scaling_roadmap.json")
    
    print("ROADMAP SUMMARY:")
    print("-" * 50)
    print(f"Goal: {roadmap['goal']}")
    print(f"Duration: {roadmap['duration']}")
    print(f"Status: {roadmap['status']}")
    print()
    
    print("Key Preconditions:")
    for i, precondition in enumerate(roadmap["preconditions"], 1):
        print(f"  {i}. {precondition}")
    print()
    
    print("Decision Framework:")
    for decision, condition in roadmap["decision_points"].items():
        print(f"  • {decision}: {condition}")
    print()
    
    return roadmap

if __name__ == "__main__":
    print("SCALING PLAN - 40H/MONTH GOAL")
    print("=" * 50)
    
    # Step 1: Compute volume requirements
    scaling_plan = compute_volume_requirements()
    
    # Step 2: Create scaling roadmap
    if "error" not in scaling_plan and scaling_plan.get("status") != "estimated":
        roadmap = create_scaling_roadmap(scaling_plan)
        
        print()
        print("=" * 70)
        print("SCALING PLAN COMPLETE")
        print("Status: Ready to execute after SLO fix")
        print("Next: Complete hardening sprint, then begin Week 6 ramp")
        print("=" * 70)
    else:
        print()
        print("=" * 70)
        print("SCALING PLAN - ESTIMATES ONLY")
        print("Status: Need more data for precise planning")
        print("Next: Collect more ROI data, then recompute requirements")
        print("=" * 70)
