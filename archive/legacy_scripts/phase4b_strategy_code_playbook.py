#!/usr/bin/env python3
"""
Phase 4B Strategy Code Playbook Generator
Builds the playbook for Phase 4B (strategy_code) with mandated safety envelope
"""

import json
from datetime import datetime
from pathlib import Path

from utils.logger import get_logger

logger = get_logger("swarm.phase4b_playbook")

class Phase4BStrategyPlaybook:
    """Phase 4B playbook generator with strategy_code constraints"""

    def __init__(self):
        self.playbook = {
            "phase": "Phase 4B",
            "domain": "strategy_code",
            "batch_id": "phase4b_strategy_code",
            "target_date": datetime.now().strftime("%Y-%m-%d"),
            "risk_level": "medium_high",
            "entry_criteria": self._entry_criteria(),
            "success_criteria": self._success_criteria(),
            "task_backlog": self._task_backlog(),
            "execution_plan": self._execution_plan(),
            "roi_schema_requirements": self._roi_requirements(),
            "gate_plan": self._gate_plan(),
            "monitoring_plan": self._monitoring_plan()
        }

    @staticmethod
    def _entry_criteria():
        return {
            "phase4a_governance": "success_marked",
            "strategy_slo_status": {
                "latency": "green",
                "policy_adherence": "green",
                "error_rate": "green"
            },
            "open_incidents": "none_in_strategy_or_execution",
            "risk_mitigation": "enhanced_controls_active",
            "human_supervision": "strategy_owner_on_call"
        }

    @staticmethod
    def _success_criteria():
        return {
            "weekly_hours_saved": "target_10h, effective_min_9.5h",
            "avg_roi_score": ">=95/100",
            "strategy_slo_compliance": ">=95%",
            "incident_rate": "0% (any incident halts phase)",
            "rollback_readiness": "documented_for_each_task"
        }

    @staticmethod
    def _task_backlog():
        return {
            "strategy_policy_automation": [
                {
                    "task_id": "strategy_policy_guardrails_1",
                    "title": "Automate strategy policy guardrails",
                    "description": "Encode policy guardrails with automated enforcement hooks",
                    "module": "swarm/strategy",
                    "risk_level": "medium",
                    "baseline_hours": 3.5,
                    "allowed": True,
                    "explicit_rollback": "disable_guardrail_feature_flag",
                    "dependencies": ["permanent_observability", "phase4a_governance"],
                    "exclusions": ["new_markets", "structural_refactors"]
                },
                {
                    "task_id": "strategy_policy_notifications_1",
                    "title": "Policy deviation notification automation",
                    "description": "Automate notifications when policy adherence drifts",
                    "module": "swarm/strategy",
                    "risk_level": "medium",
                    "baseline_hours": 2.5,
                    "allowed": True,
                    "explicit_rollback": "revert_notification_rules",
                    "dependencies": ["strategy_policy_guardrails_1"],
                    "exclusions": ["new_products", "untested_topologies"]
                }
            ],
            "strategy_optimization": [
                {
                    "task_id": "strategy_optimization_playbook_1",
                    "title": "Strategy optimization playbook",
                    "description": "Codify optimization routines with human approval hooks",
                    "module": "swarm/optimization",
                    "risk_level": "medium_high",
                    "baseline_hours": 4.0,
                    "allowed": True,
                    "explicit_rollback": "restore_previous_playbook",
                    "dependencies": ["strategy_policy_guardrails_1"],
                    "exclusions": ["capital_allocation_changes"]
                },
                {
                    "task_id": "strategy_optimization_simulation_1",
                    "title": "Simulation-backed optimization validation",
                    "description": "Validate optimization routines using sandbox simulations",
                    "module": "swarm/simulation",
                    "risk_level": "medium",
                    "baseline_hours": 3.0,
                    "allowed": True,
                    "explicit_rollback": "rollback_simulation_configs",
                    "dependencies": ["strategy_optimization_playbook_1"],
                    "exclusions": ["live_trading_pipeline_edits"]
                }
            ]
        }

    @staticmethod
    def _execution_plan():
        return {
            "week_1": {
                "focus": "Policy guardrails",
                "tasks": ["strategy_policy_guardrails_1"],
                "target_hours": 3.5,
                "risk_profile": "medium"
            },
            "week_2": {
                "focus": "Policy notifications",
                "tasks": ["strategy_policy_notifications_1"],
                "target_hours": 2.5,
                "risk_profile": "medium"
            },
            "week_3": {
                "focus": "Optimization playbook",
                "tasks": ["strategy_optimization_playbook_1"],
                "target_hours": 4.0,
                "risk_profile": "medium_high"
            },
            "week_4": {
                "focus": "Simulation validation",
                "tasks": ["strategy_optimization_simulation_1"],
                "target_hours": 3.0,
                "risk_profile": "medium"
            }
        }

    @staticmethod
    def _roi_requirements():
        return {
            "mandatory_fields": [
                "task_type",
                "risk_level",
                "rollback_plan",
                "evidence_links",
                "slo_compliance",
                "slo_violations",
                "incidents",
                "near_misses"
            ],
            "task_type_values": ["strategy_policy", "strategy_optimization"],
            "batch_id": "phase4b_strategy_code",
            "volume_gate": {
                "target": 10.0,
                "min_effective": 9.5,
                "epsilon": 1e-6
            },
            "incident_policy": "any_incident_or_slo_regression_halts_phase",
            "evidence_requirements": [
                "policy_diff_url",
                "rollback_plan_doc",
                "strategy_dashboard_url"
            ]
        }

    @staticmethod
    def _gate_plan():
        return {
            "volume_gate": "target_10h_min_9.5h",
            "slo_gate": "strategy_slos_must_remain_green",
            "incident_gate": "incident_or_slo_regression=hard_stop",
            "human_approval": "required_for_strategy_changes"
        }

    @staticmethod
    def _monitoring_plan():
        return {
            "daily": [
                "strategy_latency_slo",
                "policy_adherence",
                "error_rate",
                "rollback_ready_state"
            ],
            "weekly": [
                "ROI_vs_target",
                "hours_saved_vs_target",
                "incident_report",
                "human_approval_log"
            ],
            "halt_triggers": [
                "strategy_slo_regression",
                "any_incident",
                "missing_rollback_plan",
                "missing_evidence_links"
            ]
        }

    def generate(self):
        print("=" * 70)
        print("PHASE 4B STRATEGY CODE PLAYBOOK")
        print("=" * 70)
        print(json.dumps(self.playbook, indent=2))
        target = Path("phase4b_strategy_code_playbook.json")
        with target.open("w", encoding="utf-8") as fh:
            json.dump(self.playbook, fh, indent=2)
        logger.info("Phase 4B playbook saved to %s", target)
        print(f"\n✅ Playbook saved to {target}")


def main():
    Phase4BStrategyPlaybook().generate()


if __name__ == "__main__":
    main()
