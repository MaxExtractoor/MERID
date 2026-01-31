"""Batch 25 tests for Swarm Lab metrics and sniper scanner filters."""

from __future__ import annotations

from decimal import Decimal
from swarm.sniper_scanner import (
    ComplianceCategory,
    OpportunityType,
    SniperOpportunityScanner,
    TacticType,
)
from swarm.swarm_lab import (
    IdeaStatus,
    RiskLevel,
    SwarmLabOrchestrator,
    SwarmLabStatus,
    TestStage,
)


class TestSwarmLabAnalytics:
    def test_metrics_snapshots_and_lab_metrics(self) -> None:
        orchestrator = SwarmLabOrchestrator()
        metrics = orchestrator.get_metrics()
        assert metrics["total_agents"] >= 1
        assert metrics["ideas_total"] == 0

        snapshot = orchestrator.get_agents_snapshot(limit=2)
        assert len(snapshot) == 2
        assert snapshot[0]["tasks_completed"] >= snapshot[-1]["tasks_completed"]

        top_ideas = orchestrator.get_top_ideas()
        assert top_ideas == []

        payload = orchestrator.get_status_payload()
        assert payload["status"] in {status.value for status in SwarmLabStatus}
        assert payload["cycle_count"] == 0
        assert payload["metrics"] == metrics

        lab_metrics = orchestrator.get_lab_metrics()
        assert lab_metrics["agents"]["total"] == metrics["total_agents"]
        assert lab_metrics["ideas"]["total"] == metrics["ideas_total"]

    def test_rollout_and_prioritized_views(self) -> None:
        orchestrator = SwarmLabOrchestrator()
        agent = next(iter(orchestrator._agents.values()))
        idea = orchestrator.discover_idea(
            theme="Governance",
            category="infra",
            title="Proposal bundler",
            problem="Slow voting",
            discovered_by=agent.agent_id,
        )
        orchestrator.prioritize_idea(idea.idea_id, 0.95, 0.1, RiskLevel.LOW)
        prioritized = orchestrator.get_prioritized_ideas(top_n=5)
        assert prioritized and prioritized[0].idea_id == idea.idea_id

        design = orchestrator.create_design(idea.idea_id, "Bundle Design", "desc")
        orchestrator.approve_design(design.design_id, agent.agent_id)
        implementation = orchestrator.create_implementation(design.design_id)
        active_impls = orchestrator.get_active_implementations()
        assert implementation in active_impls

        orchestrator.mark_implementation_complete(implementation.implementation_id)
        rollout = orchestrator.create_rollout(implementation.implementation_id, governance_required=True)
        orchestrator.advance_rollout_stage(rollout.rollout_id)
        orchestrator.advance_rollout_stage(rollout.rollout_id)
        assert orchestrator.advance_rollout_stage(rollout.rollout_id).completed_at is not None

        lab_metrics = orchestrator.get_lab_metrics()
        assert lab_metrics["rollouts"]["completed"] >= 1
        assert lab_metrics["ideas"]["by_status"][IdeaStatus.DEPLOYED.value] >= 1


class TestSniperScannerFilters:
    def test_opportunity_filters_and_stats(self) -> None:
        scanner = SniperOpportunityScanner()

        scanner.detect_arbitrage_opportunity(
            asset="ETH",
            buy_venue="dexA",
            sell_venue="dexB",
            buy_price=Decimal("1800"),
            sell_price=Decimal("1815"),
            max_size=Decimal("10"),
            buy_fee_bps=5,
            sell_fee_bps=5,
            estimated_slippage_bps=1,
        )
        scanner.detect_liquidation_opportunity(
            asset="BTC",
            venue="perpX",
            liquidation_price=Decimal("26000"),
            market_price=Decimal("26500"),
            size=Decimal("2"),
        )

        opportunities = scanner.get_opportunities(
            opportunity_type=OpportunityType.ARBITRAGE,
            compliance_category=ComplianceCategory.ALLOWED,
            approved_only=True,
            min_edge_bps=10,
        )
        assert opportunities and all(o.approved_for_execution for o in opportunities)

        execution = scanner.record_execution(
            opportunity_id=opportunities[0].opportunity_id,
            success=True,
            actual_profit_usd=Decimal("500"),
            actual_edge_bps=25.0,
            latency_ms=40.0,
        )
        assert execution.compliance_approved is True

        stats = scanner.get_execution_stats()
        assert stats["total_executions"] == 1
        assert stats["success_rate"] == 1.0
        assert stats["total_profit_usd"] == 500.0

        assert scanner.is_tactic_allowed(TacticType.SIMPLE_ARB) is True
        assert scanner.is_tactic_allowed(TacticType.SPOOFING) is False
