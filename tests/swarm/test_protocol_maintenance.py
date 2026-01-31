"""Tests for protocol maintenance agents."""

from __future__ import annotations

from decimal import Decimal

import pytest

from swarm import protocol_maintenance as pm


def test_protocol_health_monitor_updates_status_and_alerts(monkeypatch):
    monitor = pm.ProtocolHealthMonitor()

    # Ensure metric exists
    metric = monitor.update_metric(pm.HealthMetricType.TVL, 2000000.0)
    assert metric.status is pm.HealthStatus.DEGRADED

    # Force critical breach
    metric = monitor.update_metric(pm.HealthMetricType.TVL, 1000.0)
    assert metric.status is pm.HealthStatus.CRITICAL

    report = monitor.get_health_report()
    assert report["overall_status"] in {pm.HealthStatus.CRITICAL.value, pm.HealthStatus.DEGRADED.value}
    assert report["recent_alerts"]


def test_parameter_tuner_proposal_flow():
    tuner = pm.ParameterTunerAgent()

    proposal = tuner.propose_parameter_change(
        parameter_type=pm.ParameterType.FEE,
        parameter_name="swap_fee",
        current_value=0.001,
        proposed_value=0.0008,
        reason="lower slippage",
    )

    assert proposal.requires_approval is False
    assert tuner.approve_proposal(proposal.proposal_id) is True
    assert tuner.apply_proposal(proposal.proposal_id) is True

    experiment = tuner.start_experiment("exp1", "incentive_weight", variants=[0.1, 0.2])
    tuner.record_experiment_result("exp1", 0.1, success=True)
    tuner.record_experiment_result("exp1", 0.2, success=False)
    assert tuner.get_experiment_winner("exp1") == 0.1


def test_upgrade_coordinator_simulate_and_execute():
    coordinator = pm.UpgradeCoordinator()
    plan = coordinator.create_upgrade_plan(
        upgrade_type=pm.UpgradeType.CONTRACT_UPGRADE,
        description="Upgrade execution contract",
        estimated_downtime_minutes=10,
    )

    results = coordinator.simulate_upgrade(plan.plan_id, simulation_params={})
    assert results["success"] is True

    proposal_id = coordinator.prepare_governance_proposal(plan.plan_id)
    assert proposal_id.startswith("gov_proposal_")

    assert coordinator.execute_upgrade(plan.plan_id, governance_approved=True) is True


def test_security_maintenance_agent_pending_updates():
    agent = pm.SecurityMaintenanceAgent()
    update = agent.create_security_update(
        update_type="exploit_pattern",
        description="New sandwich attack pattern",
        new_patterns=["pattern_a"],
    )

    pending = agent.get_pending_updates()
    assert update in pending

    assert agent.apply_security_update(update.update_id) is True
    assert agent.get_pending_updates() == []
