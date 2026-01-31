"""Batch 15 tests for protocol_maintenance agents."""

from __future__ import annotations

import pytest

from swarm.protocol_maintenance import (
    HealthMetricType,
    HealthStatus,
    ParameterTunerAgent,
    ParameterType,
    ProtocolHealthMonitor,
    SecurityMaintenanceAgent,
    UpgradeCoordinator,
    UpgradeType,
)


class TestProtocolHealthMonitor:
    def test_metric_transitions_raise_alerts(self) -> None:
        monitor = ProtocolHealthMonitor()

        metric = monitor.update_metric(HealthMetricType.TVL, 600_000.0)
        assert metric.status is HealthStatus.DEGRADED

        metric = monitor.update_metric(HealthMetricType.TVL, 100_000.0)
        assert metric.status is HealthStatus.CRITICAL

        report = monitor.get_health_report()
        assert report["overall_status"] == HealthStatus.CRITICAL.value
        assert report["recent_alerts"]
        assert report["recent_alerts"][-1]["severity"] == "critical"


class TestParameterTunerAgent:
    def test_proposal_lifecycle_requires_approval(self) -> None:
        tuner = ParameterTunerAgent()

        proposal = tuner.propose_parameter_change(
            ParameterType.FEE,
            "maker_fee",
            current_value=0.001,
            proposed_value=0.002,
            reason="volatility spike",
            within_governance_caps=False,
        )

        assert proposal.requires_approval is True
        assert tuner.approve_proposal(proposal.proposal_id) is True
        assert tuner.apply_proposal(proposal.proposal_id) is True
        assert proposal.approved is True and proposal.applied is True

    def test_experiment_tracks_results_and_winner(self) -> None:
        tuner = ParameterTunerAgent()
        experiment = tuner.start_experiment(
            experiment_id="exp_fee",
            parameter_name="maker_fee",
            variants=[0.001, 0.002],
            duration_hours=6,
        )

        for _ in range(5):
            tuner.record_experiment_result("exp_fee", 0.001, success=True)
        for _ in range(3):
            tuner.record_experiment_result("exp_fee", 0.001, success=False)
        for _ in range(2):
            tuner.record_experiment_result("exp_fee", 0.002, success=True)
        tuner.record_experiment_result("exp_fee", 0.002, success=False)

        winner = tuner.get_experiment_winner("exp_fee")
        assert winner == 0.002
        assert experiment["winner"] == 0.002


class TestUpgradeCoordinator:
    def test_upgrade_simulation_and_governance_flow(self) -> None:
        coordinator = UpgradeCoordinator()
        plan = coordinator.create_upgrade_plan(
            upgrade_type=UpgradeType.CONTRACT_UPGRADE,
            description="Deploy v2 contracts",
            affected_contracts=["VaultV2"],
            estimated_downtime_minutes=30,
            requires_liquidity_migration=True,
        )

        sim_result = coordinator.simulate_upgrade(plan.plan_id, {"env": "staging"})
        assert sim_result["success"] is True
        assert plan.simulated is True

        proposal_id = coordinator.prepare_governance_proposal(plan.plan_id)
        assert plan.governance_proposal_id == proposal_id

        assert coordinator.execute_upgrade(plan.plan_id, governance_approved=False) is False
        assert coordinator.execute_upgrade(plan.plan_id, governance_approved=True) is True
        assert plan.executed is True


class TestSecurityMaintenanceAgent:
    def test_security_update_apply_and_pending(self) -> None:
        agent = SecurityMaintenanceAgent()
        update = agent.create_security_update(
            update_type="exploit_pattern",
            description="New sandwich exploit",
            new_patterns=["sandwich:v3"],
            deprecated_patterns=["legacy:pattern"],
            protocols_affected=["DexA"],
            recommended_action="quarantine",
        )

        pending = agent.get_pending_updates()
        assert update in pending and update.applied is False

        assert agent.apply_security_update(update.update_id) is True
        assert update.applied is True
        assert agent.get_pending_updates() == []
