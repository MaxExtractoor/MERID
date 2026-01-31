"""Tests for role_refactoring, self_healing_rollback, and self_evolution_loop."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List

import pytest

from swarm import self_evolution_loop as self_evolution_loop_module
from swarm.role_refactoring import (
    RefactorProposal,
    RoleRefactoringEngine,
    RoleSnapshot,
)
from swarm.self_healing_rollback import (
    DeploymentSnapshot,
    RollbackPlan,
    SelfHealingRollbackManager,
)


class TestSelfHealingRollbackManager:
    def test_create_plan_picks_latest_snapshot_and_executes(self):
        manager = SelfHealingRollbackManager()
        older = DeploymentSnapshot(
            snapshot_id="snap-1",
            component="dex",
            version="1.0",
            created_at=datetime(2024, 1, 1, 12, 0, 0),
            metadata={"sha": "a"},
        )
        newer = DeploymentSnapshot(
            snapshot_id="snap-2",
            component="dex",
            version="1.1",
            created_at=datetime(2024, 1, 2, 12, 0, 0),
            metadata={"sha": "b"},
        )
        manager.register_snapshot(older)
        manager.register_snapshot(newer)

        plan = manager.create_plan(component="dex", reason="latency_spike")

        assert plan.target_snapshot == "snap-2"
        assert plan.steps[:2] == ["Pause traffic", "Restore snapshot snap-2"]
        assert plan.approved is False

        executed = manager.approve_and_execute(plan.plan_id)
        assert executed.approved is True
        assert executed.executed_at is not None

    def test_create_plan_without_snapshot_raises(self):
        manager = SelfHealingRollbackManager()
        with pytest.raises(ValueError):
            manager.create_plan(component="does-not-exist", reason="degraded")


class TestRoleRefactoringEngine:
    def test_propose_refactors_detects_overlap_and_underperformers(self):
        engine = RoleRefactoringEngine()
        engine.register_role(
            RoleSnapshot(
                role_id="coder_a",
                name="Coder A",
                responsibilities=["build", "fix", "review", "optimize"],
                reliability=0.92,
                load_factor=0.7,
            )
        )
        engine.register_role(
            RoleSnapshot(
                role_id="coder_b",
                name="Coder B",
                responsibilities=["build", "fix", "review", "optimize"],
                reliability=0.9,
                load_factor=0.65,
            )
        )
        engine.register_role(
            RoleSnapshot(
                role_id="ops_low",
                name="Ops Low",
                responsibilities=["deploy"],
                reliability=0.4,
                load_factor=0.6,
            )
        )

        proposals = engine.propose_refactors(reliability_floor=0.6)
        actions = {proposal.action for proposal in proposals}

        assert "merge" in actions  # coder_a & coder_b overlap ~66% -> should merge
        assert any(
            proposal.action in {"split", "retire"} and proposal.roles_involved == ["ops_low"]
            for proposal in proposals
        )
        merge = next(p for p in proposals if p.action == "merge")
        assert merge.projected_savings == pytest.approx(0.675)
        assert 0.3 <= merge.risk_score <= 0.35


class TestSelfEvolutionLoop:
    @pytest.fixture(name="loop")
    def _loop_fixture(self, monkeypatch):
        reflections: List[str] = []
        optimizations: List[str] = []
        assignments: List[tuple[str, str]] = []
        innovations: List[str] = []
        recorded_variants: List[List[tuple]] = []

        class DummyExperiment:
            def __init__(self, experiment_id: str) -> None:
                self.experiment_id = experiment_id

        class DummyABTesting:
            def start_experiment(self, *, name: str, hypothesis: str, success_metric: str, variants: List[tuple], metadata: Dict[str, str]):
                recorded_variants.append(variants)
                return DummyExperiment("exp-123")

        class DummyCurriculum:
            def assign_track(self, agent_id: str, track_id: str) -> None:  # pragma: no cover - simple storage
                assignments.append((agent_id, track_id))

        class DummyPatterns:
            def suggest_patterns(self, capability: str, min_sharpe: float = 1.0):
                return [
                    type("Pattern", (), {
                        "pattern_id": "pat-1",
                        "name": "Sharpe Booster",
                        "strengths": [capability],
                        "success_metrics": {"sharpe_ratio": min_sharpe + Decimal("0.5")},
                    })()
                ]

        class DummyMetrics:
            def record_innovation(self, **kwargs):
                innovations.append(kwargs["name"])

        monkeypatch.setattr(
            self_evolution_loop_module, "get_curriculum_planner", lambda: DummyCurriculum()
        )
        monkeypatch.setattr(
            self_evolution_loop_module, "get_ab_testing_framework", lambda: DummyABTesting()
        )
        monkeypatch.setattr(
            self_evolution_loop_module, "get_agent_pattern_library", lambda: DummyPatterns()
        )
        monkeypatch.setattr(
            self_evolution_loop_module, "get_growth_metrics_tracker", lambda: DummyMetrics()
        )

        loop = self_evolution_loop_module.SelfEvolutionLoop()
        loop._reflections = reflections  # type: ignore[attr-defined]
        loop._optimizations = optimizations  # type: ignore[attr-defined]
        loop._assignments = assignments  # type: ignore[attr-defined]
        loop._innovations = innovations  # type: ignore[attr-defined]
        loop._recorded_variants = recorded_variants  # type: ignore[attr-defined]
        return loop

    def test_iteration_flow_records_actions(self, loop, monkeypatch):
        iteration = loop.start_iteration("reduce_latency")
        loop.record_reflection(iteration.iteration_id, "latency trending up")
        loop.plan_optimization(iteration.iteration_id, "rewire fastpath cache")

        exp_id = loop.schedule_experiment(
            iteration.iteration_id,
            experiment_name="fastpath-rollout",
            hypothesis="cache reduces p99",
            variants=[("control", 0.0), ("fastpath", 1.0)],
            metric="latency_p99",
        )
        assert exp_id == "exp-123"

        recommended = loop.recommend_patterns("latency", min_sharpe=Decimal("1.2"))
        assert recommended[0]["pattern_id"] == "pat-1"
        assert recommended[0]["sharpe_ratio"] == Decimal("1.7")

        loop.assign_curriculum("agent-7", "infra-track")
        completed = loop.complete_iteration(iteration.iteration_id, outcome="success")

        assert completed.outcome == "success"
        assert completed.associated_experiment == "exp-123"
        assert loop.get_iterations(limit=1)[0].objective == "reduce_latency"

    def test_get_iteration_missing_raises(self, loop):
        with pytest.raises(KeyError):
            loop._get_iteration("not-real")
