"""Batch 27 tests for Swarm Lab lifecycle and sniper scanner stats."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

import swarm.swarm_lab as swarm_lab_module
from swarm.sniper_scanner import (
    ComplianceCategory,
    SniperOpportunityScanner,
    TacticType,
)
from swarm.swarm_lab import SwarmLabOrchestrator


class TestSwarmLabLifecycle:
    @pytest.mark.asyncio
    async def test_start_stop_cycle_publishes_activity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        orchestrator = SwarmLabOrchestrator()
        published = []

        class StubEventStream:
            async def publish(self, event_type, payload):
                published.append((event_type, payload))

        monkeypatch.setattr(swarm_lab_module, "event_stream", StubEventStream())

        async def fake_run_loop(self):
            self._status = swarm_lab_module.SwarmLabStatus.RUNNING
            payload = self.get_status_payload()
            await swarm_lab_module.event_stream.publish("swarm_activity", payload)
            self._status = swarm_lab_module.SwarmLabStatus.STOPPED

        monkeypatch.setattr(SwarmLabOrchestrator, "_run_loop", fake_run_loop)

        await orchestrator.start(cycle_interval=0.01)
        await orchestrator._loop_task
        await orchestrator.stop()

        assert orchestrator.status == swarm_lab_module.SwarmLabStatus.STOPPED
        assert orchestrator._loop_task is None
        assert published and published[0][0] == "swarm_activity"
        assert "metrics" in published[0][1]


class TestSniperScannerAdvanced:
    def test_policy_limits_and_execution_stats(self) -> None:
        scanner = SniperOpportunityScanner()

        scanner.register_tactic_policy(
            tactic_type=TacticType.SIMPLE_ARB,
            compliance_category=ComplianceCategory.ALLOWED,
            allowed=True,
            requires_approval=False,
            max_size_usd=Decimal("10000"),
            policy_reason="limit simple arb size",
        )

        risky = scanner.detect_arbitrage_opportunity(
            asset="ETH",
            buy_venue="exA",
            sell_venue="exB",
            buy_price=Decimal("2000"),
            sell_price=Decimal("2030"),
            max_size=Decimal("200"),
            estimated_slippage_bps=25,
            required_latency_ms=40,
        )
        assert risky is not None
        assert risky.approved_for_execution is False
        assert any("exceeds limit" in note for note in risky.compliance_notes)
        assert risky.risk_score > 0.3

        with pytest.raises(ValueError):
            scanner.record_execution("missing", True, Decimal("0"), 0.0, 10.0)

        scanner.register_tactic_policy(
            tactic_type=TacticType.SIMPLE_ARB,
            compliance_category=ComplianceCategory.ALLOWED,
            allowed=True,
            requires_approval=False,
            policy_reason="reset policy",
        )

        allowed = scanner.detect_arbitrage_opportunity(
            asset="BTC",
            buy_venue="dex1",
            sell_venue="dex2",
            buy_price=Decimal("30000"),
            sell_price=Decimal("30100"),
            max_size=Decimal("1"),
            buy_fee_bps=5,
            sell_fee_bps=5,
            estimated_slippage_bps=2,
        )
        assert allowed and allowed.approved_for_execution is True

        success_exec = scanner.record_execution(
            opportunity_id=allowed.opportunity_id,
            success=True,
            actual_profit_usd=Decimal("150"),
            actual_edge_bps=20.0,
            latency_ms=60.0,
        )
        fail_exec = scanner.record_execution(
            opportunity_id=allowed.opportunity_id,
            success=False,
            actual_profit_usd=Decimal("-20"),
            actual_edge_bps=-5.0,
            latency_ms=80.0,
        )
        assert success_exec.success is True
        assert fail_exec.success is False

        successful_only = scanner.get_executions(success_only=True)
        assert len(successful_only) == 1 and successful_only[0].success is True

        stats = scanner.get_execution_stats()
        assert stats["total_executions"] == 2
        assert stats["successful_executions"] == 1
        assert stats["success_rate"] == 0.5
        assert stats["total_profit_usd"] == 150.0
        assert stats["avg_latency_ms"] == pytest.approx((60.0 + 80.0) / 2)

        future_stats = scanner.get_execution_stats(since=datetime.utcnow() + timedelta(seconds=1))
        assert future_stats == {
            "total_executions": 0,
            "successful_executions": 0,
            "success_rate": 0.0,
            "total_profit_usd": 0.0,
            "avg_edge_bps": 0.0,
            "avg_latency_ms": 0.0,
        }
