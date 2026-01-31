"""Batch 18 tests covering sniper scanner filters, spawner retirements, and Swarm Lab lifecycle."""

from __future__ import annotations

import random
from decimal import Decimal

import pytest

from swarm.sniper_scanner import (
    ComplianceCategory,
    SniperOpportunityScanner,
    TacticType,
)
from swarm.spawner import SwarmSpawner
from swarm.swarm_lab import (
    AgentRole,
    IdeaStatus,
    RiskLevel,
    SwarmLabOrchestrator,
    TestStage,
)


class TestSniperScannerAdvanced:
    def test_arbitrage_negative_edge_returns_none(self) -> None:
        scanner = SniperOpportunityScanner()
        result = scanner.detect_arbitrage_opportunity(
            asset="BTC",
            buy_venue="dex_a",
            sell_venue="dex_b",
            buy_price=Decimal("100"),
            sell_price=Decimal("101"),
            max_size=Decimal("1"),
            buy_fee_bps=20.0,
            sell_fee_bps=30.0,
            estimated_slippage_bps=60.0,
        )
        assert result is None

    def test_flash_loan_policy_requires_approval_and_filters(self) -> None:
        scanner = SniperOpportunityScanner()
        opp = scanner.detect_arbitrage_opportunity(
            asset="ARB",
            buy_venue="dex_x",
            sell_venue="dex_y",
            buy_price=Decimal("10"),
            sell_price=Decimal("10.8"),
            max_size=Decimal("4000"),
        )
        assert opp is not None
        opp.execution_tactic = TacticType.FLASH_LOAN_ARB
        scanner._check_compliance(opp)
        assert opp.compliance_category == ComplianceCategory.RESTRICTED
        assert opp.approved_for_execution is False
        assert any("Requires governance approval" in note for note in opp.compliance_notes)

        # Generate two more opportunities for filtering
        scanner.detect_arbitrage_opportunity(
            asset="EDGE1",
            buy_venue="a",
            sell_venue="b",
            buy_price=Decimal("10"),
            sell_price=Decimal("10.5"),
            max_size=Decimal("1"),
        )
        scanner.detect_arbitrage_opportunity(
            asset="EDGE2",
            buy_venue="a",
            sell_venue="b",
            buy_price=Decimal("10"),
            sell_price=Decimal("11"),
            max_size=Decimal("1"),
        )

        filtered = scanner.get_opportunities(
            opportunity_type=opp.opportunity_type,
            compliance_category=ComplianceCategory.ALLOWED,
            approved_only=True,
            min_edge_bps=5.0,
        )
        assert filtered
        assert all(o.approved_for_execution and o.estimated_edge_bps >= 5.0 for o in filtered)
        assert filtered[0].estimated_edge_bps >= filtered[-1].estimated_edge_bps


class DummyLedger:
    def __init__(self, rows):
        self._rows = rows

    def leaderboard(self, limit: int = 20):
        return self._rows[:limit]

    def best_parent(self, min_score: float, min_votes: int):
        candidates = [row for row in self._rows if row["score"] >= min_score and row["votes"] >= min_votes]
        return candidates[0] if candidates else None


class DummyAgent:
    def __init__(self, agent_id: str | None = None, model_name: str | None = "model",
                 generation: int = 0):
        self.agent_id = agent_id or "dummy"
        self.trust = 1.0
        self.tool_budget = 5
        self.model_name = model_name or "model"
        self.generation = generation


class TestSpawnerRetirements:
    def test_child_retirement_and_diversity(self) -> None:
        random.seed(0)
        ledger = DummyLedger([
            {"agent_id": "parent", "score": 0.9, "votes": 10},
            {"agent_id": "parent#0001", "score": 0.2, "votes": 10},
        ])
        spawner = SwarmSpawner(
            ledger,
            max_population=3,
            stale_score=0.3,
            spawn_threshold=0.6,
            min_votes_to_spawn=5,
        )
        parent = DummyAgent("parent")
        spawner.bootstrap([parent])

        # Spawn child based on leaderboard parent stats
        spawner.refresh_population()
        assert any("#" in agent.agent_id for agent in spawner.get_active_agents())

        # Update ledger to reflect child underperformance (generation > 0 should retire)
        child_id = next(agent.agent_id for agent in spawner.get_active_agents() if "#" in agent.agent_id)
        ledger._rows[1] = {"agent_id": child_id, "score": 0.2, "votes": 10}

        refreshed = spawner.refresh_population()
        assert all(agent.agent_id != child_id for agent in refreshed)
        assert len(refreshed) <= spawner.max_population


class TestSwarmLabLifecycle:
    def test_idea_to_rollout_flow(self) -> None:
        orchestrator = SwarmLabOrchestrator()
        sample_agent = next(iter(orchestrator._agents.values()))

        idea = orchestrator.discover_idea(
            theme="RWA UX",
            category="ui",
            title="Portfolio heatmap",
            problem="Users lack visual clarity",
            discovered_by=sample_agent.agent_id,
        )
        assert idea.status == IdeaStatus.DISCOVERED

        prioritized = orchestrator.prioritize_idea(
            idea_id=idea.idea_id,
            impact_score=0.9,
            complexity_score=0.3,
            risk_level=RiskLevel.MEDIUM,
        )
        assert prioritized.status == IdeaStatus.PRIORITIZED
        design = orchestrator.create_design(
            idea_id=idea.idea_id,
            title="Heatmap spec",
            description="Detailed layout",
            backend_modules=["analytics"],
        )
        orchestrator.approve_design(design.design_id, approved_by=sample_agent.agent_id)
        assert orchestrator._ideas[idea.idea_id].status == IdeaStatus.IMPLEMENTING

        impl = orchestrator.create_implementation(design.design_id, files_created=["heatmap.py"])
        orchestrator.mark_implementation_complete(impl.implementation_id)
        assert orchestrator._ideas[idea.idea_id].status == IdeaStatus.TESTING

        result = orchestrator.run_test_stage(impl.implementation_id, TestStage.SIMULATION)
        assert result.passed is True

        rollout = orchestrator.create_rollout(impl.implementation_id, governance_required=True)
        assert rollout.governance_approved is False
        orchestrator.advance_rollout_stage(rollout.rollout_id)
        orchestrator.advance_rollout_stage(rollout.rollout_id)
        orchestrator.advance_rollout_stage(rollout.rollout_id)  # completes rollout
        assert orchestrator._ideas[idea.idea_id].status == IdeaStatus.DEPLOYED

        metrics = orchestrator.get_status_payload()
        assert metrics["status"] == orchestrator.status.value
        assert metrics["top_ideas"][0]["idea_id"] == idea.idea_id

    def test_rollout_rollback_records_reason(self) -> None:
        orchestrator = SwarmLabOrchestrator()
        idea = orchestrator.discover_idea(
            theme="Safety",
            category="infra",
            title="Circuit breaker",
            problem="Need failsafe",
        )
        orchestrator.prioritize_idea(idea.idea_id, 0.8, 0.2, RiskLevel.LOW)
        design = orchestrator.create_design(idea.idea_id, "Breaker", "desc")
        impl = orchestrator.create_implementation(design.design_id)
        rollout = orchestrator.create_rollout(impl.implementation_id)

        rolled_back = orchestrator.rollback_rollout(rollout.rollout_id, "metric regression")
        assert rolled_back.rolled_back is True
        assert rolled_back.rollback_reason == "metric regression"
