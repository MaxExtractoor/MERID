"""Batch 23 tests for protocol maintenance and spawner lineage."""

from __future__ import annotations

import random

import pytest

from swarm.protocol_maintenance import (
    HealthMetricType,
    HealthStatus,
    ParameterTunerAgent,
    ProtocolHealthMonitor,
    UpgradeCoordinator,
)
from swarm.spawner import SwarmSpawner


class StubLedger:
    def __init__(self, leaderboard_rows, parent_row):
        self._leaderboard = leaderboard_rows
        self._parent = parent_row

    def leaderboard(self, limit: int = 20):
        return self._leaderboard[:limit]

    def best_parent(self, min_score: float, min_votes: int):
        if self._parent["score"] >= min_score and self._parent["votes"] >= min_votes:
            return self._parent
        return None


class DeterministicAgent:
    def __init__(self, agent_id: str, model_name: str | None = None):
        self.agent_id = agent_id
        self.model_name = model_name or "model"
        self.trust = 1.0
        self.tool_budget = 5


class FallbackAgent:
    def __init__(self):
        self.agent_id = "fallback"
        self.trust = 1.0
        self.tool_budget = 3


class TestProtocolMaintenanceAgents:
    def test_metric_status_transitions_and_report(self) -> None:
        monitor = ProtocolHealthMonitor()

        critical_metric = monitor.update_metric(HealthMetricType.VOLUME_24H, 5000.0)
        assert critical_metric.status == HealthStatus.CRITICAL

        warning_metric = monitor.update_metric(HealthMetricType.ERROR_RATE, 0.02)
        assert warning_metric.status == HealthStatus.DEGRADED

        healthy_metric = monitor.update_metric(HealthMetricType.SLIPPAGE, 0.001)
        assert healthy_metric.status == HealthStatus.HEALTHY

        report = monitor.get_health_report()
        assert report["overall_status"] == monitor.get_overall_health().value
        assert report["metrics"][HealthMetricType.VOLUME_24H.value]["status"] == "critical"
        assert report["metrics"][HealthMetricType.ERROR_RATE.value]["status"] == "degraded"

    def test_parameter_tuner_requires_approval(self) -> None:
        tuner = ParameterTunerAgent()
        assert tuner.approve_proposal("missing") is False

        proposal = tuner.propose_parameter_change(
            parameter_type=HealthMetricType.GOVERNANCE_PARTICIPATION,
            parameter_name="delegate_reward",
            current_value=0.02,
            proposed_value=0.03,
            reason="Stimulate voting",
            within_governance_caps=True,
        )
        assert tuner.apply_proposal(proposal.proposal_id) is False
        tuner.approve_proposal(proposal.proposal_id)
        assert tuner.apply_proposal(proposal.proposal_id) is True

    def test_upgrade_coordinator_errors_and_execution(self) -> None:
        coordinator = UpgradeCoordinator()
        plan = coordinator.create_upgrade_plan(
            upgrade_type=HealthMetricType.SLIPPAGE,
            description="Router upgrade",
            affected_contracts=["router_v1"],
            estimated_downtime_minutes=5,
        )
        with pytest.raises(ValueError):
            coordinator.prepare_governance_proposal(plan.plan_id)
        coordinator.simulate_upgrade(plan.plan_id, {"stress": "high"})
        proposal_id = coordinator.prepare_governance_proposal(plan.plan_id)
        assert proposal_id.startswith("gov_proposal_")
        assert coordinator.execute_upgrade(plan.plan_id, governance_approved=False) is False
        assert coordinator.execute_upgrade(plan.plan_id, governance_approved=True) is True


class TestSpawnerFallbackLineage:
    def test_spawn_child_with_constructor_fallback(self) -> None:
        random.seed(0)
        ledger = StubLedger(
            leaderboard_rows=[{"agent_id": "fallback", "score": 0.9, "votes": 10}],
            parent_row={"agent_id": "fallback", "score": 0.9, "votes": 10},
        )
        spawner = SwarmSpawner(
            ledger,
            max_population=3,
            spawn_threshold=0.6,
            min_votes_to_spawn=5,
        )
        parent = FallbackAgent()
        spawner.bootstrap([parent])

        assert spawner.get_replication_count() == 0
        assert spawner.get_termination_count() == 0
        assert spawner.get_evolution_count() == 0

        refreshed = spawner.refresh_population()
        assert any(agent.agent_id.startswith("fallback#") for agent in refreshed)

        lineage_records = spawner.lineage()
        assert any(record.parent_id == "fallback" for record in lineage_records)
