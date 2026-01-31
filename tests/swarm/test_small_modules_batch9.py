"""Tests for sniper_scanner and swarm_lab_orchestrator modules."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from swarm.sniper_scanner import (
    ComplianceCategory,
    OpportunityType,
    SniperOpportunityScanner,
    TacticType,
)
from swarm.swarm_lab_orchestrator import (
    IdeaCategory,
    IdeaStatus,
    SwarmLabOrchestrator,
    TestResult,
    TestStage,
)


@pytest.fixture()
def sniper_scanner():
    return SniperOpportunityScanner()


class TestSniperOpportunityScanner:
    def test_detect_arbitrage_creates_approved_opportunity(self, sniper_scanner):
        opportunity = sniper_scanner.detect_arbitrage_opportunity(
            asset="ETH",
            buy_venue="venue_a",
            sell_venue="venue_b",
            buy_price=Decimal("1000"),
            sell_price=Decimal("1015"),
            max_size=Decimal("2"),
            estimated_slippage_bps=3.0,
            required_latency_ms=80.0,
        )

        assert opportunity is not None
        assert opportunity.approved_for_execution is True
        assert opportunity.compliance_category == ComplianceCategory.ALLOWED
        assert opportunity.risk_score > 0
        stored = sniper_scanner.get_opportunities(approved_only=True)
        assert stored and stored[0].opportunity_id == opportunity.opportunity_id

    def test_banning_tactic_blocks_opportunity(self, sniper_scanner):
        sniper_scanner.register_tactic_policy(
            tactic_type=TacticType.SIMPLE_ARB,
            compliance_category=ComplianceCategory.BANNED,
            allowed=False,
            policy_reason="temporary halt",
        )

        opportunity = sniper_scanner.detect_arbitrage_opportunity(
            asset="BTC",
            buy_venue="x",
            sell_venue="y",
            buy_price=Decimal("100"),
            sell_price=Decimal("110"),
            max_size=Decimal("1"),
        )

        assert opportunity is not None
        assert opportunity.blocked is True
        assert opportunity.approved_for_execution is False
        assert opportunity.compliance_category == ComplianceCategory.BANNED

    def test_record_execution_and_stats(self, sniper_scanner):
        opportunity = sniper_scanner.detect_liquidation_opportunity(
            asset="SOL",
            venue="dex",
            liquidation_price=Decimal("18"),
            market_price=Decimal("19"),
            size=Decimal("10"),
        )
        execution = sniper_scanner.record_execution(
            opportunity_id=opportunity.opportunity_id,
            success=True,
            actual_profit_usd=Decimal("25"),
            actual_edge_bps=75.0,
            latency_ms=42.0,
        )

        stats = sniper_scanner.get_execution_stats()
        assert execution.success is True
        assert stats["total_executions"] == 1
        assert stats["successful_executions"] == 1
        assert stats["total_profit_usd"] == pytest.approx(25.0)
        assert stats["avg_latency_ms"] == pytest.approx(42.0)

    def test_get_opportunities_filters(self, sniper_scanner):
        sniper_scanner.detect_arbitrage_opportunity(
            asset="ARB",
            buy_venue="buy",
            sell_venue="sell",
            buy_price=Decimal("10"),
            sell_price=Decimal("11"),
            max_size=Decimal("5"),
        )
        sniper_scanner.detect_liquidation_opportunity(
            asset="ARB",
            venue="buy",
            liquidation_price=Decimal("9"),
            market_price=Decimal("10"),
            size=Decimal("5"),
        )

        allowed = sniper_scanner.get_opportunities(
            opportunity_type=OpportunityType.ARBITRAGE,
            compliance_category=ComplianceCategory.ALLOWED,
            approved_only=True,
        )
        assert allowed and all(o.opportunity_type == OpportunityType.ARBITRAGE for o in allowed)
        assert all(o.approved_for_execution for o in allowed)


@pytest.fixture()
def lab_orchestrator():
    orch = SwarmLabOrchestrator()
    orch.register_idea_source(
        lambda: [
            {
                "title": "Faster Pipelines",
                "description": "Reduce orchestration latency",
                "category": IdeaCategory.PERFORMANCE.value,
                "impact": 0.9,
                "effort": 0.3,
                "source": "tests",
            }
        ]
    )
    return orch


class TestSwarmLabOrchestrator:
    def test_end_to_end_pipeline_deploys_and_monitors(self, lab_orchestrator):
        ideas = lab_orchestrator.discover_ideas()
        prioritized = lab_orchestrator.prioritize_ideas()
        assert ideas and prioritized
        idea_id = prioritized[0].idea_id

        assert lab_orchestrator.design_idea(idea_id) is True
        assert lab_orchestrator.implement_idea(idea_id) is True

        for stage in [TestStage.STATIC_ANALYSIS, TestStage.UNIT_TESTS, TestStage.SIMULATION]:
            result = lab_orchestrator.test_idea(idea_id, stage)
            assert result.passed is True

        assert lab_orchestrator.deploy_idea(idea_id) is True
        metrics = lab_orchestrator.monitor_idea(idea_id)
        assert metrics["uptime"] >= 0.9
        assert lab_orchestrator.complete_idea(idea_id) is True
        assert lab_orchestrator._ideas[idea_id].status == IdeaStatus.COMPLETED

    def test_custom_test_runner_records_results(self, lab_orchestrator):
        idea = lab_orchestrator.discover_ideas()[0]
        lab_orchestrator.prioritize_ideas()

        def custom_runner(_: str) -> TestResult:
            return TestResult(
                stage=TestStage.STAGING,
                passed=True,
                tests_run=5,
                tests_passed=5,
                coverage=0.99,
                duration_seconds=12.0,
            )

        lab_orchestrator.register_test_runner(TestStage.STAGING, custom_runner)
        lab_orchestrator.design_idea(idea.idea_id)
        result = lab_orchestrator.test_idea(idea.idea_id, TestStage.STAGING)

        assert result.coverage == 0.99
        stored = lab_orchestrator._ideas[idea.idea_id].test_results[TestStage.STAGING]
        assert stored["passed"] is True
        assert stored["tests_run"] == 5

    def test_run_full_pipeline_success(self, lab_orchestrator):
        idea = lab_orchestrator.discover_ideas()[0]
        lab_orchestrator.prioritize_ideas()
        assert lab_orchestrator.run_full_pipeline(idea.idea_id) is True

        pipeline = lab_orchestrator.get_pipeline_status()
        assert pipeline["total_ideas"] >= 1
        assert pipeline["by_status"][IdeaStatus.COMPLETED.value] >= 1
