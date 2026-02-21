#!/usr/bin/env python3
"""
SLO Breach Diagnosis and Fix
Treat misalignment > 0.7 as a mini incident
"""

import sys
import json
from datetime import datetime

sys.path.append('.')
sys.path.append('swarm')

from swarm.ci.reliability_monitor import CIReliabilityMonitor
from swarm.watchdog.monitor import SwarmWatchdog
from utils.logger import get_logger

logger = get_logger("swarm.slo_diagnosis")

def diagnose_slo_breach():
    """Diagnose the SLO breach (misalignment > 0.7)"""
    print("=" * 70)
    print("SLO BREACH DIAGNOSIS")
    print("=" * 70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    print("Issue: Misalignment > 0.7 threshold breach")
    print()
    
    # Run CI check to get current SLO status
    print("RUNNING SLO CHECK:")
    print("-" * 50)
    
    ci_monitor = CIReliabilityMonitor()
    ci_passed = ci_monitor.run_ci_checks("slo_diagnosis_check.json")
    
    try:
        with open("slo_diagnosis_check.json", 'r') as f:
            ci_report = json.load(f)
        
        ci_metrics = ci_report["metrics"]
        violations = ci_report.get("violations", [])
        
        print(f"Success Rate: {ci_metrics['success_rate']:.1%}")
        print(f"Avg Cascade Size: {ci_metrics['avg_cascade_size']:.2f}")
        print(f"Avg Branching Factor: {ci_metrics['avg_branching_factor']:.2f}")
        print(f"Avg Misalignment: {ci_metrics['avg_misalignment']:.3f}")
        print(f"CI Status: {'✅ PASSED' if ci_passed else '❌ FAILED'}")
        print()
        
        # Identify specific violations
        misalignment_violations = [v for v in violations if "misalignment" in v.get("description", "").lower()]
        
        print("SLO VIOLATIONS:")
        print("-" * 50)
        if misalignment_violations:
            print(f"Misalignment Violations: {len(misalignment_violations)}")
            for violation in misalignment_violations:
                print(f"  • {violation.get('description', 'Unknown')}")
                print(f"    Severity: {violation.get('severity', 'Unknown')}")
                print(f"    Task: {violation.get('task_id', 'Unknown')}")
        else:
            print("No specific misalignment violations found")
            print("Check individual task metrics...")
        
        print()
        
        # Analyze task-level misalignment
        print("TASK-LEVEL MISALIGNMENT ANALYSIS:")
        print("-" * 50)
        
        # Get task details from CI run
        task_details = ci_report.get("task_details", [])
        
        if task_details:
            high_misalignment_tasks = []
            for task in task_details:
                misalignment = task.get("metrics", {}).get("avg_misalignment", 0)
                if misalignment > 0.7:
                    high_misalignment_tasks.append({
                        "task_id": task.get("task_id", "unknown"),
                        "task_type": task.get("task_type", "unknown"),
                        "misalignment": misalignment,
                        "agents": task.get("agents", []),
                        "success": task.get("success", False)
                    })
            
            if high_misalignment_tasks:
                print(f"Tasks with Misalignment > 0.7: {len(high_misalignment_tasks)}")
                print()
                
                # Group by agent pairs
                agent_pair_analysis = {}
                for task in high_misalignment_tasks:
                    agents = task["agents"]
                    if len(agents) >= 2:
                        # Focus on planner-reviewer and planner-implementer pairs
                        for i in range(len(agents) - 1):
                            pair = (agents[i]["role"], agents[i + 1]["role"])
                            if pair not in agent_pair_analysis:
                                agent_pair_analysis[pair] = []
                            agent_pair_analysis[pair].append(task)
                
                print("AGENT PAIR ANALYSIS:")
                for pair, tasks in agent_pair_analysis.items():
                    avg_misalignment = sum(t["misalignment"] for t in tasks) / len(tasks)
                    print(f"  • {pair[0]} ↔ {pair[1]}: {len(tasks)} tasks, avg misalignment {avg_misalignment:.3f}")
                
                print()
                print("HIGHEST MISALIGNMENT TASKS:")
                # Sort by misalignment
                high_misalignment_tasks.sort(key=lambda x: x["misalignment"], reverse=True)
                for task in high_misalignment_tasks[:5]:  # Top 5
                    print(f"  • {task['task_id']}: {task['misalignment']:.3f}")
                    print(f"    Type: {task['task_type']}")
                    print(f"    Agents: {', '.join([a['role'] for a in task['agents']])}")
                    print(f"    Success: {'✅' if task['success'] else '❌'}")
                    print()
                
                # Generate diagnosis
                diagnosis = {
                    "breach_type": "misalignment",
                    "threshold": 0.7,
                    "current_value": ci_metrics['avg_misalignment'],
                    "affected_tasks": len(high_misalignment_tasks),
                    "agent_pairs": list(agent_pair_analysis.keys()),
                    "most_problematic_pairs": [
                        pair for pair, tasks in agent_pair_analysis.items() 
                        if len(tasks) >= 2
                    ],
                    "sample_tasks": high_misalignment_tasks[:3]
                }
                
            else:
                print("No individual tasks with misalignment > 0.7 found")
                print("Issue may be in aggregate calculation")
                diagnosis = {"breach_type": "aggregate_misalignment", "current_value": ci_metrics['avg_misalignment']}
        else:
            print("No task details available for analysis")
            diagnosis = {"breach_type": "unknown", "current_value": ci_metrics['avg_misalignment']}
        
        return diagnosis
        
    except Exception as e:
        print(f"Error during diagnosis: {e}")
        return {"error": str(e)}

def generate_corrective_actions(diagnosis):
    """Generate specific corrective actions based on diagnosis"""
    print()
    print("CORRECTIVE ACTIONS:")
    print("-" * 50)
    
    actions = []
    
    if diagnosis.get("breach_type") == "misalignment":
        # Check for problematic agent pairs
        problematic_pairs = diagnosis.get("most_problematic_pairs", [])
        
        if "planner" in str(problematic_pairs):
            actions.append({
                "priority": "HIGH",
                "action": "Tighten planner spec template",
                "details": [
                    "Add explicit goal statement section",
                    "Add constraints and acceptance criteria",
                    "Add measurable success indicators",
                    "Add validation checklist before execution"
                ]
            })
        
        if "reviewer" in str(problematic_pairs):
            actions.append({
                "priority": "HIGH", 
                "action": "Tighten reviewer contract",
                "details": [
                    "Add explicit objective alignment checklist",
                    "Require reviewer to confirm planner goals",
                    "Add justification for any deviations",
                    "Add final approval criteria"
                ]
            })
        
        if "implementer" in str(problematic_pairs):
            actions.append({
                "priority": "MEDIUM",
                "action": "Improve implementer-planner communication",
                "details": [
                    "Add requirement confirmation step",
                    "Add progress checkpoints",
                    "Add deviation reporting mechanism"
                ]
            })
        
        # General actions
        actions.append({
            "priority": "HIGH",
            "action": "Adjust misalignment threshold or add human confirmation",
            "details": [
                "Consider if 0.7 threshold is too strict",
                "Add 'human_confirmed_misalignment' label",
                "Distinguish between harmful vs harmless misalignment"
            ]
        })
        
        actions.append({
            "priority": "MEDIUM",
            "action": "Add targeted watchdog checks",
            "details": [
                "Block merges when misalignment > 0.8 AND reviewer disagrees",
                "Add human confirmation step for high-risk tasks",
                "Add early warning for rising misalignment"
            ]
        })
    
    elif diagnosis.get("breach_type") == "aggregate_misalignment":
        actions.append({
            "priority": "HIGH",
            "action": "Investigate aggregate calculation",
            "details": [
                "Check if metric calculation is correct",
                "Review if threshold should be adjusted",
                "Add noise filtering for harmless variance"
            ]
        })
    
    else:
        actions.append({
            "priority": "HIGH",
            "action": "Comprehensive investigation needed",
            "details": [
                "Manual review of recent tasks",
                "Check measurement methodology",
                "Validate SLO calculation logic"
            ]
        })
    
    # Sort by priority
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    actions.sort(key=lambda x: priority_order.get(x["priority"], 3))
    
    for i, action in enumerate(actions, 1):
        print(f"{i}. [{action['priority']}] {action['action']}")
        for detail in action["details"]:
            print(f"   • {detail}")
        print()
    
    return actions

def create_slo_breach_playbook():
    """Create a one-page SLO breach playbook"""
    playbook = {
        "title": "SLO Breach Playbook",
        "version": "1.0",
        "date": datetime.now().isoformat(),
        "purpose": "Rapid response to SLO breaches with minimal disruption",
        
        "slo_thresholds": {
            "success_rate": 0.90,
            "avg_cascade_size": 2.0,
            "avg_branching_factor": 1.2,
            "avg_misalignment": 0.7,
            "avg_retry_index": 2.0
        },
        
        "breach_types": {
            "misalignment": {
                "severity": "HIGH",
                "impact": "Objective misalignment between agents",
                "immediate_actions": [
                    "Run diagnosis script to identify affected tasks",
                    "Check agent pair misalignment patterns",
                    "Review sample of high-misalignment tasks"
                ],
                "corrective_actions": [
                    "Tighten planner spec template",
                    "Tighten reviewer contract",
                    "Add targeted watchdog checks",
                    "Consider threshold adjustment"
                ],
                "escalation": "If >10 tasks affected or misalignment >0.9"
            },
            "cascade": {
                "severity": "CRITICAL",
                "impact": "Cascading failures across agents",
                "immediate_actions": [
                    "Halt all swarm operations",
                    "Investigate cascade root cause",
                    "Review agent interaction patterns"
                ],
                "corrective_actions": [
                    "Fix agent communication protocols",
                    "Add cascade prevention measures",
                    "Improve error handling"
                ],
                "escalation": "IMMEDIATE - Any cascade > size 2"
            },
            "success_rate": {
                "severity": "HIGH",
                "impact": "Low task completion rate",
                "immediate_actions": [
                    "Check task failure patterns",
                    "Review agent capabilities",
                    "Verify task complexity"
                ],
                "corrective_actions": [
                    "Adjust task difficulty",
                    "Improve agent prompts",
                    "Add capability checks"
                ],
                "escalation": "If success rate < 80% for 3 consecutive runs"
            }
        },
        
        "response_procedure": [
            "1. RUN DIAGNOSIS: Execute slo_diagnosis.py",
            "2. IDENTIFY: Determine breach type and affected components",
            "3. ASSESS: Evaluate severity and impact",
            "4. ACT: Implement corrective actions from playbook",
            "5. VERIFY: Re-run SLO check to confirm fix",
            "6. DOCUMENT: Log breach and resolution",
            "7. MONITOR: Watch for recurrence"
        ],
        
        "contacts": {
            "on_call": "swarm_operations",
            "escalation": "swarm_leads",
            "documentation": "swarm_ops_v1"
        }
    }
    
    with open("slo_breach_playbook.json", 'w') as f:
        json.dump(playbook, f, indent=2)
    
    print("✅ SLO Breach Playbook saved to slo_breach_playbook.json")
    return playbook

if __name__ == "__main__":
    print("SLO BREACH DIAGNOSIS AND FIX")
    print("=" * 50)
    
    # Step 1: Diagnose the breach
    diagnosis = diagnose_slo_breach()
    
    # Step 2: Generate corrective actions
    if "error" not in diagnosis:
        actions = generate_corrective_actions(diagnosis)
        
        # Step 3: Create playbook
        playbook = create_slo_breach_playbook()
        
        # Save diagnosis and actions
        breach_report = {
            "diagnosis_date": datetime.now().isoformat(),
            "diagnosis": diagnosis,
            "corrective_actions": actions,
            "status": "diagnosed",
            "next_step": "implement_corrective_actions"
        }
        
        with open("slo_breach_diagnosis.json", 'w') as f:
            json.dump(breach_report, f, indent=2)
        
        print("✅ Diagnosis saved to slo_breach_diagnosis.json")
        print()
        print("=" * 70)
        print("SLO BREACH DIAGNOSIS COMPLETE")
        print("Next: Implement corrective actions")
        print("=" * 70)
    else:
        print("❌ Diagnosis failed - check logs")
        print("Next: Manual investigation required")
