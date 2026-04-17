#!/usr/bin/env python3
"""Phase 6 Combined Strategy Code + Execution Tuning Playbook Generator."""

import json
from datetime import datetime
from pathlib import Path

from utils.logger import get_logger

logger = get_logger("swarm.phase6_playbook")


class Phase6CombinedPlaybook:
    """Generate Phase 6 playbook combining strategy_code and execution_tuning lanes."""

    def __init__(self):
        self.playbook = {
            "phase": "Phase 6",
            "domain": "strategy_execution_combo",
            "batch_id": "phase6_joint_lane",
            "target_date": datetime.now().strftime("%Y-%m-%d"),
            "risk_level": "medium_high",
            "entry_criteria": self._entry_criteria(),
            "success_criteria": self._success_criteria(),
            "lane_backlogs": self._lane_backlogs(),
            "execution_plan": self._execution_plan(),
            "joint_roi_requirements": self._roi_requirements(),
            "joint_gate_plan": self._gate_plan(),
            "monitoring_plan": self._monitoring_plan(),
            "incident_policy": self._incident_policy(),
            "promotion_checklist": self._promotion_checklist()
        }

    @staticmethod
    def _entry_criteria():
        return {
            "phase4_gates": "strategy_code lane promoted",
            "phase5_gates": "execution_tuning lane promoted",
            "phase5b_confirmation": "passing",
            "joint_slo_state": {
                "latency": "green",
                "reliability": "green",
                "error_rate": "green"
            },
            "incident_backlog": "zero_active",
            "human_supervision": "governance_owner + performance_engineer",
            "shared_dashboards": "phase6_joint_dashboard_ready"
        }

    @staticmethod
    def _success_criteria():
        return {
            "volume_joint_hours": ">=12h per cycle (combined)",
            "roi_score_joint": ">=96/100 blended",
            "latency_gate": ">=8% improvement",
            "reliability_gate": ">=4% improvement",
            "strategy_accuracy_gate": ">=97% policy compliance",
            "incident_rate": "0% (shared hard stop)",
            "slo_regression": "none allowed",
            "joint_review": "weekly governance + performance review"
        }

    @staticmethod
    def _lane_backlogs():
        return {
            "strategy_code": [
                {
                    "task_id": "phase6_strategy_policy_guardrails",
                    "title": "Strategy policy guardrail refresh",
                    "description": "Update governance guardrails reflecting execution tuning insights",
                    "module": "swarm/strategy",
                    "risk_level": "medium",
                    "baseline_hours": 3.5,
                    "dependencies": ["phase4b_strategy_code"],
                    "explicit_rollback": "restore_prev_guardrails"
                },
                {
                    "task_id": "phase6_strategy_deployment",
                    "title": "Strategy rollout + execution sync",
                    "description": "Deploy strategy bundles with execution-aware toggles",
                    "module": "swarm/strategy",
                    "risk_level": "medium_high",
                    "baseline_hours": 4.0,
                    "dependencies": ["phase6_strategy_policy_guardrails"],
                    "explicit_rollback": "halt_rollout_revert_flags"
                }
            ],
            "execution_tuning": [
                {
                    "task_id": "phase6_execution_latency_watch",
                    "title": "Latency + strategy alignment",
                    "description": "Ensure strategy-triggered code paths maintain tuned latency",
                    "module": "swarm/execution",
                    "risk_level": "medium",
                    "baseline_hours": 3.0,
                    "dependencies": ["phase5b_execution_tuning"],
                    "explicit_rollback": "disable_alignment_hooks"
                },
                {
                    "task_id": "phase6_execution_scaling_guard",
                    "title": "Scaling guardrail for joint lane",
                    "description": "Apply scaling safeguards when strategy load spikes",
                    "module": "swarm/scaling",
                    "risk_level": "medium_high",
                    "baseline_hours": 3.0,
                    "dependencies": ["phase6_execution_latency_watch"],
                    "explicit_rollback": "restore_prev_scaling_config"
                }
            ]
        }

    @staticmethod
    def _execution_plan():
        return {
            "week_1": {
                "focus": "Strategy guardrails + latency alignment",
                "tasks": [
                    "phase6_strategy_policy_guardrails",
                    "phase6_execution_latency_watch"
                ],
                "target_hours": 6.5,
                "risk_profile": "medium"
            },
            "week_2": {
                "focus": "Joint rollout + scaling guard",
                "tasks": [
                    "phase6_strategy_deployment",
                    "phase6_execution_scaling_guard"
                ],
                "target_hours": 7.0,
                "risk_profile": "medium_high"
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
                "incidents",
                "near_misses",
                "latency_improvement",
                "reliability_improvement",
                "strategy_policy_accuracy"
            ],
            "task_type_values": [
                "strategy_policy",
                "strategy_rollout",
                "performance_optimization",
                "scaling_optimization"
            ],
            "batch_id": "phase6_joint_lane",
            "volume_gate": {
                "target": 12.0,
                "min_effective": 11.0,
                "epsilon": 1e-6
            },
            "incident_policy": "incident_in_any_lane_halts_both",
            "evidence_requirements": [
                "governance_review_doc",
                "performance_dashboard_url",
                "joint_slo_report",
                "rollback_plan_doc"
            ],
            "improvement_metrics": {
                "latency_gate": 0.08,
                "reliability_gate": 0.04,
                "latency_stretch": 0.10,
                "reliability_stretch": 0.05,
                "strategy_accuracy_gate": 0.97,
                "strategy_accuracy_stretch": 0.985
            }
        }

    @staticmethod
    def _gate_plan():
        return {
            "volume_gate": "target_12h_min_11h_combined",
            "roi_gate": "blended_roi>=96",
            "slo_gate": "latency/reliability/error_rate all green",
            "strategy_accuracy_gate": ">=97%",
            "improvement_gate": "latency>=8% AND reliability>=4%",
            "incident_gate": "incident_in_either_lane=hard_stop",
            "joint_freeze_gate": "any red SLO triggers full freeze"
        }

    @staticmethod
    def _monitoring_plan():
        return {
            "daily": [
                "strategy_policy_adherence",
                "execution_latency_slo",
                "reliability_slo",
                "error_rate",
                "joint_incident_board"
            ],
            "per_run": [
                "evidence_link_check",
                "rollback_ready_state",
                "joint_slo_snapshot"
            ],
            "weekly": [
                "Governance + Performance joint review",
                "ROI_vs_gate",
                "Hours_vs_gate",
                "Latency_vs_gate_vs_stretch",
                "Reliability_vs_gate_vs_stretch",
                "Strategy_accuracy_vs_gate"
            ],
            "halt_triggers": [
                "incident_in_either_lane",
                "SLO regression",
                "missing rollback",
                "gate miss two consecutive runs"
            ]
        }

    @staticmethod
    def _incident_policy():
        return {
            "policy": "joint_slo_incident_policy",
            "rules": [
                "Any incident in strategy_code or execution_tuning halts both lanes",
                "Restart requires joint governance sign-off",
                "SLO regression to yellow forces investigation window (48h)",
                "Red SLO forces immediate freeze and rollback"
            ]
        }

    @staticmethod
    def _promotion_checklist():
        return {
            "requirements": [
                "Two consecutive passes of all gates",
                "Joint incident-free window of 14 days",
                "Documented joint rollback drill",
                "Updated dashboards in observability stack",
                "Phase 6 completion report generated"
            ]
        }

    def generate(self):
        print("=" * 70)
        print("PHASE 6 COMBINED PLAYBOOK")
        print("=" * 70)
        print(json.dumps(self.playbook, indent=2))
        target = Path("phase6_combined_strategy_execution_playbook.json")
        with target.open("w", encoding="utf-8") as fh:
            json.dump(self.playbook, fh, indent=2)
        logger.info("Phase 6 playbook saved to %s", target)
        print(f"\n✅ Playbook saved to {target}")


def main():
    Phase6CombinedPlaybook().generate()


if __name__ == "__main__":
    main()
