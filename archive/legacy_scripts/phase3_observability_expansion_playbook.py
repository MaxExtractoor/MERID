#!/usr/bin/env python3
"""
Phase 3 Observability Expansion Playbook
Scoped expansion of observability lane with maintained safety envelope
"""

import sys
import json
from datetime import datetime
from pathlib import Path

sys.path.append('.')
sys.path.append('swarm')

from utils.logger import get_logger

logger = get_logger("swarm.phase3_observability")

class Phase3ObservabilityPlaybook:
    """Phase 3 Observability Expansion Playbook"""
    
    def __init__(self):
        self.playbook = {
            "phase": "Phase 3",
            "domain": "Observability Expansion",
            "base_lane": "permanent_observability",
            "target_date": datetime.now().strftime('%Y-%m-%d'),
            "risk_level": "low_to_medium",
            "entry_criteria": {
                "slo_status": "green",
                "ci_health": "3_consecutive_green",
                "guardrails": "active",
                "roi_threshold": 95.0,
                "slo_threshold": 95.0,
                "phase2_validation": "completed"
            },
            "success_criteria": {
                "weekly_hours_saved": "5-10h (stretch band)",
                "avg_roi_score": ">=95/100",
                "slo_compliance": ">=95%",
                "incident_rate": "0%",
                "rollback_rate": "0%",
                "phase3_validation": "maintained_safety_envelope"
            },
            "task_backlog": self._generate_task_backlog(),
            "execution_plan": self._generate_execution_plan(),
            "roi_schema_mapping": self._generate_roi_schema_mapping(),
            "monitoring_plan": self._generate_monitoring_plan(),
            "expansion_gates": self._generate_expansion_gates()
        }
    
    def _generate_task_backlog(self):
        """Generate Phase 3 expansion task backlog"""
        return {
            "advanced_alerting": [
                {
                    "task_id": "obs_alerting_correlation_1",
                    "title": "Implement alert correlation patterns",
                    "description": "Add intelligent alert correlation to reduce noise and identify root causes",
                    "module": "swarm/alerting",
                    "complexity": "medium",
                    "risk_level": "low",
                    "baseline_hours": 3.0,
                    "priority": "high",
                    "dependencies": ["obs_logs_error_tracking_1"],
                    "acceptance_criteria": [
                        "Alert correlation rules implemented",
                        "Noise reduction > 50%",
                        "Root cause identification improved"
                    ]
                },
                {
                    "task_id": "obs_alerting_ml_1",
                    "title": "Add ML-based anomaly detection",
                    "description": "Implement machine learning anomaly detection for observability metrics",
                    "module": "swarm/analytics",
                    "complexity": "high",
                    "risk_level": "medium",
                    "baseline_hours": 4.0,
                    "priority": "medium",
                    "dependencies": ["obs_alerting_correlation_1"],
                    "acceptance_criteria": [
                        "ML anomaly detection model trained",
                        "False positive rate < 10%",
                        "Anomaly alerts integrated"
                    ]
                }
            ],
            "deeper_tracing": [
                {
                    "task_id": "obs_tracing_agent_workflow_1",
                    "title": "Deep tracing for multi-agent workflows",
                    "description": "Add comprehensive tracing for complex multi-agent interaction patterns",
                    "module": "swarm/tracing",
                    "complexity": "high",
                    "risk_level": "low",
                    "baseline_hours": 4.5,
                    "priority": "high",
                    "dependencies": ["obs_traces_distributed_1"],
                    "acceptance_criteria": [
                        "Multi-agent workflow tracing complete",
                        "Performance bottlenecks identified",
                        "Trace visualization available"
                    ]
                },
                {
                    "task_id": "obs_tracing_span_enrichment_1",
                    "title": "Span enrichment with business context",
                    "description": "Enrich tracing spans with business context and metadata",
                    "module": "swarm/tracing",
                    "complexity": "medium",
                    "risk_level": "low",
                    "baseline_hours": 2.5,
                    "priority": "medium",
                    "dependencies": ["obs_tracing_agent_workflow_1"],
                    "acceptance_criteria": [
                        "Business context added to spans",
                        "Metadata enrichment automated",
                        "Business impact tracing available"
                    ]
                }
            ],
            "targeted_harness_refactors": [
                {
                    "task_id": "obs_harness_parallel_1",
                    "title": "Parallel test execution optimization",
                    "description": "Refactor test harness for parallel execution to reduce CI time",
                    "module": "swarm/testing",
                    "complexity": "medium",
                    "risk_level": "low",
                    "baseline_hours": 3.0,
                    "priority": "high",
                    "dependencies": ["obs_harness_coverage_1"],
                    "acceptance_criteria": [
                        "Parallel test execution implemented",
                        "CI time reduced > 30%",
                        "Test isolation maintained"
                    ]
                },
                {
                    "task_id": "obs_harness_smart_retry_1",
                    "title": "Smart retry logic for flaky tests",
                    "description": "Implement intelligent retry logic for flaky tests based on historical patterns",
                    "module": "swarm/testing",
                    "complexity": "medium",
                    "risk_level": "low",
                    "baseline_hours": 2.0,
                    "priority": "medium",
                    "dependencies": ["obs_harness_flakiness_1"],
                    "acceptance_criteria": [
                        "Smart retry logic implemented",
                        "Flaky test success rate > 95%",
                        "Retry patterns learned"
                    ]
                }
            ],
            "performance_monitoring": [
                {
                    "task_id": "obs_perf_profiling_1",
                    "title": "Deep performance profiling integration",
                    "description": "Add comprehensive performance profiling for swarm operations",
                    "module": "swarm/performance",
                    "complexity": "high",
                    "risk_level": "medium",
                    "baseline_hours": 3.5,
                    "priority": "medium",
                    "dependencies": ["obs_metrics_execution_1"],
                    "acceptance_criteria": [
                        "Performance profiling integrated",
                        "Bottleneck identification automated",
                        "Performance trends tracked"
                    ]
                },
                {
                    "task_id": "obs_perf_resource_monitoring_1",
                    "title": "Resource utilization monitoring",
                    "description": "Add detailed resource utilization monitoring for swarm agents",
                    "module": "swarm/monitoring",
                    "complexity": "medium",
                    "risk_level": "low",
                    "baseline_hours": 2.5,
                    "priority": "medium",
                    "dependencies": ["obs_perf_profiling_1"],
                    "acceptance_criteria": [
                        "Resource monitoring implemented",
                        "Utilization alerts configured",
                        "Resource optimization suggestions"
                    ]
                }
            ]
        }
    
    def _generate_execution_plan(self):
        """Generate execution plan with progressive complexity"""
        return {
            "week_1": {
                "focus": "Advanced Alerting Foundation",
                "tasks": [
                    "obs_alerting_correlation_1"
                ],
                "target_hours": 3.0,
                "risk_profile": "low",
                "complexity": "medium"
            },
            "week_2": {
                "focus": "Deeper Tracing Implementation",
                "tasks": [
                    "obs_tracing_agent_workflow_1",
                    "obs_harness_parallel_1"
                ],
                "target_hours": 7.5,
                "risk_profile": "low",
                "complexity": "high"
            },
            "week_3": {
                "focus": "Performance & Harness Optimization",
                "tasks": [
                    "obs_perf_profiling_1",
                    "obs_harness_smart_retry_1"
                ],
                "target_hours": 5.5,
                "risk_profile": "medium",
                "complexity": "medium"
            },
            "week_4": {
                "focus": "Advanced Features & Integration",
                "tasks": [
                    "obs_alerting_ml_1",
                    "obs_tracing_span_enrichment_1",
                    "obs_perf_resource_monitoring_1"
                ],
                "target_hours": 9.0,
                "risk_profile": "medium",
                "complexity": "high"
            }
        }
    
    def _generate_roi_schema_mapping(self):
        """Generate ROI schema mapping for Phase 3"""
        return {
            "critical_fields": {
                "task_type": "'observability_expansion' or 'alerting' or 'tracing' or 'performance'",
                "risk_level": "'low' or 'medium'",
                "business_value": "'high' (advanced observability)",
                "impact_score": "90-98 (advanced capabilities)",
                "roi_score": "95-100 (expansion ROI)",
                "quality_improvement": "0.85-1.0 (enhanced reliability)",
                "defects_avoided": "3-7 (advanced prevention)",
                "human_review_friction": "0.15-0.25 (moderate complexity)"
            },
            "phase3_specific": {
                "evidence_links": "['dashboard_url', 'analytics_url', 'tracing_url', 'alerting_url']",
                "notes": "'Phase 3 observability expansion for {module}'",
                "batch_id": "'phase3_observability_week_{week}'"
            },
            "safety_tracking": {
                "slo_compliance": "'green' or 'yellow' (monitor for complexity)",
                "slo_violations": "JSON array of any SLO issues",
                "incidents": "0 (maintain safety)",
                "near_misses": "Track any complexity-related issues"
            }
        }
    
    def _generate_monitoring_plan(self):
        """Generate enhanced monitoring plan for Phase 3"""
        return {
            "daily_checks": [
                "SLO compliance status (monitor for complexity impact)",
                "Task success rates (track medium-risk tasks)",
                "Error rate monitoring (alerting system health)",
                "Performance metrics (new monitoring systems)"
            ],
            "weekly_reviews": [
                "ROI metrics analysis (track expansion ROI)",
                "Quality improvement tracking (advanced features)",
                "Risk assessment (medium-risk task impact)",
                "Progress toward success criteria (5-10h stretch band)"
            ],
            "monthly_assessments": [
                "Phase 3 target progress (expansion validation)",
                "ROI sustainability (advanced features)",
                "SLO trend analysis (complexity impact)",
                "Next phase planning (further expansion or optimization)"
            ],
            "expansion_gates": [
                "Week 2: Check if low-risk tasks maintain safety envelope",
                "Week 3: Evaluate medium-risk task impact",
                "Week 4: Full expansion assessment and decision point"
            ],
            "alerting_thresholds": {
                "success_rate_below_90": "Immediate alert",
                "slo_compliance_below_90": "Daily alert",
                "roi_score_below_95": "Weekly alert",
                "error_rate_above_5": "Immediate alert",
                "complexity_impact_above_10": "Weekly alert"
            }
        }
    
    def _generate_expansion_gates(self):
        """Generate expansion gates for Phase 3"""
        return {
            "gate_1": {
                "week": 2,
                "criteria": "Low-risk tasks maintain 100% SLO compliance",
                "action": "Proceed to medium-risk tasks",
                "fallback": "Pause and reassess complexity"
            },
            "gate_2": {
                "week": 3,
                "criteria": "Medium-risk tasks achieve ≥95% success rate",
                "action": "Proceed to advanced features",
                "fallback": "Scale back to low-risk only"
            },
            "gate_3": {
                "week": 4,
                "criteria": "Full expansion maintains ≥95% ROI and ≥95% SLO",
                "action": "Promote to expanded permanent lane",
                "fallback": "Revert to base observability lane"
            }
        }
    
    def generate_playbook_document(self):
        """Generate complete Phase 3 playbook document"""
        print("=" * 70)
        print("PHASE 3 OBSERVABILITY EXPANSION PLAYBOOK")
        print("=" * 70)
        print(f"Date: {self.playbook['target_date']}")
        print(f"Domain: {self.playbook['domain']}")
        print(f"Base Lane: {self.playbook['base_lane']}")
        print(f"Risk Level: {self.playbook['risk_level']}")
        print()
        
        print("ENTRY CRITERIA:")
        print("-" * 50)
        for criterion, requirement in self.playbook["entry_criteria"].items():
            print(f"  • {criterion}: {requirement}")
        print()
        
        print("SUCCESS CRITERIA:")
        print("-" * 50)
        for criterion, requirement in self.playbook["success_criteria"].items():
            print(f"  • {criterion}: {requirement}")
        print()
        
        print("TASK BACKLOG:")
        print("-" * 50)
        
        total_hours = 0
        for category, tasks in self.playbook["task_backlog"].items():
            print(f"\n{category.upper().replace('_', ' ')}:")
            for task in tasks:
                print(f"  • {task['task_id']}")
                print(f"    Title: {task['title']}")
                print(f"    Module: {task['module']}")
                print(f"    Hours: {task['baseline_hours']:.1f}h")
                print(f"    Priority: {task['priority']}")
                print(f"    Risk: {task['risk_level']}")
                print(f"    Dependencies: {', '.join(task['dependencies']) if task['dependencies'] else 'None'}")
                total_hours += task['baseline_hours']
        
        print(f"\nTotal Backlog: {total_hours:.1f}h")
        print()
        
        print("EXECUTION PLAN:")
        print("-" * 50)
        
        for week, plan in self.playbook["execution_plan"].items():
            print(f"\n{week.upper().replace('_', ' ')}:")
            print(f"  Focus: {plan['focus']}")
            print(f"  Tasks: {len(plan['tasks'])}")
            print(f"  Target Hours: {plan['target_hours']:.1f}h")
            print(f"  Risk Profile: {plan['risk_profile']}")
            print(f"  Complexity: {plan['complexity']}")
            print(f"  Task List:")
            for task in plan['tasks']:
                print(f"    - {task}")
        
        print()
        
        print("EXPANSION GATES:")
        print("-" * 50)
        
        for gate_name, gate in self.playbook["expansion_gates"].items():
            print(f"\n{gate_name.upper().replace('_', ' ')}:")
            print(f"  Week: {gate['week']}")
            print(f"  Criteria: {gate['criteria']}")
            print(f"  Action: {gate['action']}")
            print(f"  Fallback: {gate['fallback']}")
        
        print()
        
        print("SAFETY ENVELOPE:")
        print("-" * 50)
        print("  • Maintain 100% SLO compliance for low-risk tasks")
        print("  • Target ≥95% success rate for medium-risk tasks")
        print("  • Zero incidents/rollbacks throughout expansion")
        print("  • ROI ≥95 for all expansion tasks")
        print("  • Volume: 5-10h/week stretch band")
        print()
        
        print("=" * 70)
        print("PLAYBOOK SUMMARY")
        print("-" * 50)
        print(f"Total Tasks: {sum(len(tasks) for tasks in self.playbook['task_backlog'].values())}")
        print(f"Total Hours: {total_hours:.1f}h")
        print(f"Duration: 4 weeks")
        print(f"Avg Weekly: {total_hours/4:.1f}h")
        print(f"Risk Level: {self.playbook['risk_level']}")
        print(f"Success Rate Expected: 95%+")
        print(f"ROI Expected: 95-100/100")
        print(f"Safety Envelope: Maintained")
        print()
        print("NEXT STEPS:")
        print("1. Verify Phase 2 completion and permanent lane status")
        print("2. Execute Week 1 low-risk expansion tasks")
        print("3. Monitor expansion gates and safety envelope")
        print("4. Evaluate full expansion at Week 4 gate")
        print("=" * 70)
        
        return self.playbook

def main():
    """Generate Phase 3 Observability Expansion Playbook"""
    playbook = Phase3ObservabilityPlaybook()
    playbook_document = playbook.generate_playbook_document()
    
    # Save playbook to file
    with open("phase3_observability_expansion_playbook.json", 'w') as f:
        json.dump(playbook_document, f, indent=2)
    
    print("\n✅ Phase 3 expansion playbook saved to phase3_observability_expansion_playbook.json")
    print("Ready for Phase 3 execution with maintained safety envelope")

if __name__ == "__main__":
    main()
