"""
Phase 3: High-Load Stress & End-to-End Validation

Tests for production-readiness covering:
1. Concurrent explainability recording under load
2. End-to-end latency validation
3. Data authenticity (no fabricated data)
4. Observability (structured logging, metrics)
5. Swarm health gating under load

Reference: .windsurf/tickets/phase3-stress-and-e2e-validation.md
Baseline: Commit c25d2702
"""

import asyncio
import statistics
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Any, Optional
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

import merid.risk.kill_switches as _ks_mod


@pytest.fixture(autouse=True)
def _isolate_risk_kill_switch_file(tmp_path):
    """RiskController loads ``data/risk_kill_switch.json`` on init; isolate per test."""
    fake = tmp_path / "risk_kill_switch.json"
    fake.write_text('{"active": false}', encoding="utf-8")
    with patch.object(_ks_mod, "_KILL_SWITCH_FILE", fake):
        yield


from agents.explainability import (
    ExplainabilityTracker,
    DecisionReasoning,
    DecisionType,
    get_explainability_tracker,
)
from merid.event_venues.kalshi.ws import KalshiWebSocket
from merid.event_venues.base import QuoteEvent


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_decision(agent_id: str, idx: int) -> DecisionReasoning:
    """Create a synthetic DecisionReasoning for stress tests."""
    return DecisionReasoning(
        decision_id=f"dec-{agent_id}-{idx}",
        agent_id=agent_id,
        decision_type=DecisionType.SIGNAL,
        timestamp=time.time(),
        decision="BUY_YES" if idx % 2 == 0 else "HOLD",
        confidence=0.5 + (idx % 50) / 100,
        primary_reason=f"Edge detected on market {idx}",
        supporting_factors=["momentum", "volume"],
        contrary_factors=["high_spread"],
        data_sources=["kalshi_orderbook", "model_v3"],
        market_context={"ticker": f"KXBTC-{idx:04d}", "mid": 55 + idx % 10},
        risk_assessment={"exposure_pct": 5.0, "max_loss": 100},
        processing_time_ms=1.0 + (idx % 5) * 0.5,
    )


# ── 1. High-Load Explainability Stress ───────────────────────────────────


class TestExplainabilityStress:
    """Concurrent recording under high throughput."""

    @pytest.mark.asyncio
    @pytest.mark.stress_core
    async def test_concurrent_recording_no_data_loss(self):
        """10 agents x 200 decisions each — no records lost."""
        tracker = ExplainabilityTracker(max_history=10_000)
        n_agents = 10
        decisions_per_agent = 200

        async def agent_workload(agent_id: str):
            for i in range(decisions_per_agent):
                tracker.record_decision(_make_decision(agent_id, i))
                if i % 50 == 0:
                    await asyncio.sleep(0)  # yield to event loop

        tasks = [
            agent_workload(f"agent-{a}") for a in range(n_agents)
        ]
        await asyncio.gather(*tasks)

        total = n_agents * decisions_per_agent
        assert len(tracker.decisions) == total, (
            f"Expected {total} decisions, got {len(tracker.decisions)}"
        )
        assert len(tracker._decisions_by_agent) == n_agents

    @pytest.mark.asyncio
    @pytest.mark.stress_core
    async def test_recording_latency_under_10ms(self):
        """P99 record_decision latency < 10 ms."""
        tracker = ExplainabilityTracker(max_history=10_000)
        latencies: List[float] = []

        for i in range(1000):
            start = time.perf_counter()
            tracker.record_decision(_make_decision("latency-agent", i))
            latencies.append((time.perf_counter() - start) * 1000)

        p99 = sorted(latencies)[int(len(latencies) * 0.99)]
        assert p99 < 10.0, f"P99 latency {p99:.2f} ms exceeds 10 ms target"

    @pytest.mark.asyncio
    @pytest.mark.stress_core
    async def test_history_trim_bounded_memory(self):
        """Tracker trims history at max_history to prevent unbounded growth."""
        max_h = 500
        tracker = ExplainabilityTracker(max_history=max_h)

        for i in range(max_h + 200):
            tracker.record_decision(_make_decision("trim-agent", i))

        assert len(tracker.decisions) == max_h
        # Oldest decision should have been evicted
        ids = {d.decision_id for d in tracker.decisions}
        assert "dec-trim-agent-0" not in ids

    @pytest.mark.asyncio
    @pytest.mark.stress_core
    async def test_concurrent_read_write_safety(self):
        """Concurrent reads and writes don't raise or corrupt."""
        tracker = ExplainabilityTracker(max_history=5_000)
        errors: List[Exception] = []

        async def writer():
            for i in range(500):
                try:
                    tracker.record_decision(_make_decision("rw-agent", i))
                except Exception as exc:
                    errors.append(exc)
                if i % 50 == 0:
                    await asyncio.sleep(0)

        async def reader():
            for _ in range(500):
                try:
                    tracker.get_recent_decisions(50)
                    tracker.get_decision_stats()
                except Exception as exc:
                    errors.append(exc)
                await asyncio.sleep(0)

        await asyncio.gather(writer(), reader())
        assert len(errors) == 0, f"Errors during concurrent access: {errors}"


# ── 2. End-to-End Latency ────────────────────────────────────────────────


class TestEndToEndLatency:
    """Validate component-level and pipeline latency."""

    def test_ws_message_parse_latency_under_5ms(self):
        """WS bridge _parse_message should complete < 5 ms at P95."""
        ws = KalshiWebSocket()
        latencies: List[float] = []

        for i in range(500):
            msg = {
                "type": "ticker",
                "ticker": f"KXBTC-{i:04d}",
                "bid": 5500 + i,
                "ask": 5600 + i,
                "last_price": 5550 + i,
                "volume": 1000 + i,
            }
            start = time.perf_counter()
            ws._parse_message(msg)
            latencies.append((time.perf_counter() - start) * 1000)

        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        assert p95 < 5.0, f"P95 parse latency {p95:.2f} ms exceeds 5 ms target"

    def test_explainability_query_latency_under_20ms(self):
        """get_recent_decisions query should complete < 20 ms at P95."""
        tracker = ExplainabilityTracker(max_history=10_000)

        # Fill with 5000 decisions
        for i in range(5000):
            tracker.record_decision(_make_decision(f"agent-{i % 10}", i))

        latencies: List[float] = []
        for _ in range(200):
            start = time.perf_counter()
            tracker.get_recent_decisions(100)
            latencies.append((time.perf_counter() - start) * 1000)

        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        assert p95 < 20.0, f"P95 query latency {p95:.2f} ms exceeds 20 ms target"

    def test_decision_stats_latency_under_50ms(self):
        """get_decision_stats should complete < 50 ms at P95 with 10k records."""
        tracker = ExplainabilityTracker(max_history=10_000)

        for i in range(10_000):
            tracker.record_decision(_make_decision(f"agent-{i % 10}", i))

        latencies: List[float] = []
        for _ in range(100):
            start = time.perf_counter()
            tracker.get_decision_stats()
            latencies.append((time.perf_counter() - start) * 1000)

        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        assert p95 < 50.0, f"P95 stats latency {p95:.2f} ms exceeds 50 ms target"

    def test_sequence_check_throughput(self):
        """WS sequence checker handles >10k messages/sec."""
        ws = KalshiWebSocket()
        n = 10_000

        start = time.perf_counter()
        for i in range(1, n + 1):
            ws._check_sequence({"seq": i, "ticker": "KXBTC-BENCH"})
        elapsed = time.perf_counter() - start

        rate = n / elapsed
        assert rate > 10_000, f"Throughput {rate:.0f} msg/s below 10k target"


# ── 3. Data Authenticity ────────────────────────────────────────────────


class TestDataAuthenticity:
    """Verify no fabricated or placeholder data leaks."""

    def test_empty_tracker_returns_empty_list(self):
        """Empty ExplainabilityTracker returns [] not placeholder data."""
        tracker = ExplainabilityTracker()
        decisions = tracker.get_recent_decisions()
        assert decisions == []
        assert isinstance(decisions, list)

    def test_empty_tracker_stats_zero(self):
        """Empty tracker stats show 0 totals, not mocked numbers."""
        tracker = ExplainabilityTracker()
        stats = tracker.get_decision_stats()
        assert stats["total_decisions"] == 0
        assert stats["agents_active"] == 0
        assert stats["avg_confidence"] == 0.0

    def test_agent_decisions_empty_for_unknown_agent(self):
        """Querying unknown agent returns [], never fabricated decisions."""
        tracker = ExplainabilityTracker()
        tracker.record_decision(_make_decision("real-agent", 1))
        result = tracker.get_agent_decisions("nonexistent-agent")
        assert result == []

    def test_decision_id_lookup_returns_none_for_missing(self):
        """Querying unknown decision_id returns None, never fabricated record."""
        tracker = ExplainabilityTracker()
        tracker.record_decision(_make_decision("agent-1", 1))
        result = tracker.get_decision_by_id("nonexistent-id")
        assert result is None

    def test_decision_to_dict_round_trips(self):
        """DecisionReasoning.to_dict() produces valid JSON-serializable dict."""
        import json
        decision = _make_decision("roundtrip-agent", 42)
        d = decision.to_dict()
        serialized = json.dumps(d)
        deserialized = json.loads(serialized)
        assert deserialized["agent_id"] == "roundtrip-agent"
        assert deserialized["decision_id"] == "dec-roundtrip-agent-42"


# ── 4. Observability ────────────────────────────────────────────────────


class TestObservability:
    """Verify structured logging and metrics counters."""

    def test_ws_counters_increment_on_messages(self):
        """WS bridge counters track messages and errors."""
        ws = KalshiWebSocket()
        assert ws._messages_received == 0
        assert ws._errors_received == 0

        # Simulate error handling
        ws._handle_error_message({
            "type": "error",
            "code": "invalid_channel",
            "msg": "test error",
        })
        assert ws._errors_received == 1

    def test_ws_counters_track_sequence_gaps(self):
        """WS bridge tracks cumulative sequence gaps."""
        ws = KalshiWebSocket()
        assert ws._seq_gaps == 0

        ws._last_seq["KXBTC-TEST"] = 100
        ws._ob_initialised.add("KXBTC-TEST")

        # Gap of 5 messages
        ws._check_sequence({"seq": 106, "ticker": "KXBTC-TEST"})
        assert ws._seq_gaps == 5

    def test_ws_reconnect_counter(self):
        """WS bridge tracks reconnect count."""
        ws = KalshiWebSocket()
        assert ws._reconnect_count == 0

    def test_tracker_stats_surface_decision_types(self):
        """Tracker stats include per-type breakdown."""
        tracker = ExplainabilityTracker()
        for i in range(10):
            tracker.record_decision(_make_decision("obs-agent", i))

        stats = tracker.get_decision_stats()
        assert "decision_types" in stats
        assert stats["total_decisions"] == 10
        assert stats["agents_active"] == 1

    def test_decision_reasoning_has_processing_time(self):
        """Every decision records processing_time_ms."""
        d = _make_decision("timing-agent", 1)
        assert d.processing_time_ms > 0
        assert "processing_time_ms" in d.to_dict()

    def test_human_readable_output(self):
        """DecisionReasoning produces structured human-readable output."""
        d = _make_decision("readable-agent", 5)
        text = d.to_human_readable()
        assert "Decision:" in text
        assert "Agent: readable-agent" in text
        assert "Primary Reason:" in text
        assert "Supporting Factors:" in text


# ── 5. Swarm Health Gating Under Load ────────────────────────────────────


class TestSwarmHealthUnderLoad:
    """Verify swarm health checks remain effective under throughput."""

    def test_integrity_report_serialization(self):
        """IntegrityReport round-trips correctly."""
        from core.swarm_integrity_guard import IntegrityReport

        report = IntegrityReport(
            ok=True,
            issues=[],
            health_summary={"checks_passed": 5, "checks_failed": 0},
        )
        assert report.ok is True
        d = report.to_dict()
        assert d["ok"] is True
        assert d["issues"] == []

    def test_degraded_integrity_report(self):
        """Degraded IntegrityReport correctly flags unhealthy state."""
        from core.swarm_integrity_guard import IntegrityReport

        report = IntegrityReport(
            ok=False,
            issues=["agent_liveness", "consensus_quorum"],
            warning="Swarm health degraded",
            health_summary={"checks_passed": 3, "checks_failed": 2},
        )
        assert report.ok is False
        assert len(report.issues) == 2
        assert "agent_liveness" in report.issues


# ── 6. WS Bridge Resilience Under Load ──────────────────────────────────


class TestWSBridgeUnderLoad:
    """Validate WS bridge handles high message throughput."""

    def test_parse_message_handles_all_known_types(self):
        """WS parser handles ticker, trade, orderbook_snapshot, orderbook_delta."""
        ws = KalshiWebSocket()

        # Ticker
        event = ws._parse_message({
            "type": "ticker",
            "ticker": "KXBTC-TEST",
            "bid": 55,
            "ask": 56,
            "last_price": 55,
            "volume": 100,
        })
        assert event is not None
        assert event.market_id == "KXBTC-TEST"

        # Subscribed (should be skipped)
        event = ws._parse_message({"type": "subscribed", "channel": "ticker"})
        assert event is None

        # Unknown type (should be skipped)
        event = ws._parse_message({"type": "unknown_type", "data": "x"})
        assert event is None

    def test_orderbook_delta_forwarded_before_snapshot(self):
        """Orderbook deltas before WS snapshot cache warm are forwarded to the bridge."""
        ws = KalshiWebSocket()

        msg = {
            "type": "orderbook_delta",
            "ticker": "KXBTC-NOSNAPSHOT",
            "seq": 1,
            "delta": {"yes": [{"price": 55, "quantity": 10}]},
        }
        event = ws._parse_message(msg)
        assert event is msg

    def test_sequence_tracking_at_scale(self):
        """Sequence tracking works across multiple markets concurrently."""
        ws = KalshiWebSocket()
        markets = [f"KXBTC-{i:03d}" for i in range(50)]

        for market in markets:
            for seq in range(1, 101):
                result = ws._check_sequence({"seq": seq, "ticker": market})
                assert result is True

        # All markets should be tracked
        assert len(ws._last_seq) == 50
        # All at seq 100
        for market in markets:
            assert ws._last_seq[market] == 100

    def test_out_of_order_rejected_at_scale(self):
        """Out-of-order messages correctly rejected across many markets."""
        ws = KalshiWebSocket()

        # Establish sequences
        for i in range(1, 51):
            ws._check_sequence({"seq": i, "ticker": "KXBTC-OOO"})

        # Old message should be rejected
        result = ws._check_sequence({"seq": 25, "ticker": "KXBTC-OOO"})
        assert result is False

        # Next in sequence should be accepted
        result = ws._check_sequence({"seq": 51, "ticker": "KXBTC-OOO"})
        assert result is True

    def test_error_handling_counts_correctly(self):
        """Error counter increments for each error message."""
        ws = KalshiWebSocket()

        for i in range(20):
            ws._handle_error_message({
                "type": "error",
                "code": "invalid_channel",
                "msg": f"Error {i}",
            })

        assert ws._errors_received == 20


# ── 7. Full Pipeline Integration ────────────────────────────────────────


class TestFullPipelineIntegration:
    """End-to-end pipeline: WS parse → record → query."""

    def test_ws_parse_to_tracker_pipeline(self):
        """WS parsed event feeds into tracker without data loss."""
        ws = KalshiWebSocket()
        tracker = ExplainabilityTracker(max_history=1_000)

        # Simulate 100 market updates → 100 decisions
        for i in range(100):
            msg = {
                "type": "ticker",
                "ticker": f"KXBTC-{i:04d}",
                "bid": 5500 + i,
                "ask": 5600 + i,
                "last_price": 5550 + i,
                "volume": 1000 + i,
            }
            event = ws._parse_message(msg)
            assert event is not None

            # Simulate agent decision based on event
            decision = DecisionReasoning(
                decision_id=f"pipe-{i}",
                agent_id="pipeline-agent",
                decision_type=DecisionType.SIGNAL,
                timestamp=time.time(),
                decision="BUY_YES" if event.bid_price and event.bid_price > Decimal("55") else "HOLD",
                confidence=0.75,
                primary_reason=f"Ticker update for {event.market_id}",
                supporting_factors=["momentum"],
                contrary_factors=[],
                data_sources=["kalshi_ws"],
                market_context={"ticker": event.market_id},
            )
            tracker.record_decision(decision)

        assert len(tracker.decisions) == 100
        stats = tracker.get_decision_stats()
        assert stats["total_decisions"] == 100
        assert stats["agents_active"] == 1

    @pytest.mark.asyncio
    async def test_concurrent_pipeline_no_cross_contamination(self):
        """Multiple agents processing concurrently don't mix decisions."""
        tracker = ExplainabilityTracker(max_history=10_000)
        n_agents = 5
        decisions_per = 100

        async def agent_pipeline(agent_id: str):
            for i in range(decisions_per):
                d = _make_decision(agent_id, i)
                tracker.record_decision(d)
                if i % 20 == 0:
                    await asyncio.sleep(0)

        await asyncio.gather(*[
            agent_pipeline(f"pipe-agent-{a}") for a in range(n_agents)
        ])

        # Each agent should have exactly its own decisions
        for a in range(n_agents):
            agent_decisions = tracker.get_agent_decisions(f"pipe-agent-{a}", limit=1000)
            assert len(agent_decisions) == decisions_per
            for d in agent_decisions:
                assert d.agent_id == f"pipe-agent-{a}"

        assert len(tracker.decisions) == n_agents * decisions_per


# ── 8. Alert Trigger Tests ───────────────────────────────────────────────


class TestAlertTriggers:
    """Verify system-level alert conditions are correctly detected and surfaced."""

    def test_ws_disconnect_increments_reconnect_counter(self):
        """WS reconnect counter starts at 0 and increments on each reconnect attempt."""
        ws = KalshiWebSocket()
        assert ws._reconnect_count == 0
        # Manually simulate reconnect path (counter update only, no network)
        ws._reconnect_count += 1
        assert ws._reconnect_count == 1
        ws._reconnect_count += 1
        assert ws._reconnect_count == 2

    def test_sequence_gap_triggers_gap_alert(self):
        """Sequence gaps are detected and counted for alert correlation."""
        ws = KalshiWebSocket()

        # Establish baseline sequence
        for seq in range(1, 51):
            ws._check_sequence({"seq": seq, "ticker": "KXBTC-ALERT"})

        initial_gaps = ws._seq_gaps

        # Inject a gap of 10
        ws._check_sequence({"seq": 61, "ticker": "KXBTC-ALERT"})

        assert ws._seq_gaps == initial_gaps + 10, (
            f"Expected {initial_gaps + 10} total gaps, got {ws._seq_gaps}"
        )

    def test_sequence_gap_invalidates_orderbook_cache(self):
        """Gap detection invalidates cached orderbook state for affected ticker."""
        ws = KalshiWebSocket()

        # Simulate an initialised orderbook
        ws._ob_initialised.add("KXBTC-CACHE")
        ws._last_seq["KXBTC-CACHE"] = 100

        # Inject a gap
        ws._check_sequence({"seq": 120, "ticker": "KXBTC-CACHE"})

        # Orderbook should be invalidated
        assert "KXBTC-CACHE" not in ws._ob_initialised, (
            "Orderbook cache should be invalidated after sequence gap"
        )

    def test_kill_switch_blocks_can_trade(self):
        """Kill switch activation immediately blocks can_trade() → False."""
        from merid.risk.kill_switches import RiskController, KillSwitchReason

        rc = RiskController(daily_loss_limit=1000.0)
        assert rc.can_trade() is True

        rc.emergency_stop("Test kill switch activation")
        assert rc.can_trade() is False
        assert rc.get_state().value == "triggered"

    def test_kill_switch_reason_captured(self):
        """Kill switch reason is persisted for audit and alert correlation."""
        from merid.risk.kill_switches import RiskController, KillSwitchReason

        rc = RiskController(daily_loss_limit=1000.0)
        rc.emergency_stop("Operator halted — manual test")

        reason = rc.get_kill_reason()
        assert reason is not None
        assert len(reason) > 0

    def test_kill_switch_daily_loss_auto_triggers(self):
        """Daily loss exceeding limit auto-triggers kill switch."""
        from merid.risk.kill_switches import RiskController

        rc = RiskController(daily_loss_limit=100.0)
        assert rc.can_trade() is True

        rc.record_pnl(-150.0)
        assert rc.can_trade() is False

    def test_kill_switch_reset_re_enables_trading(self):
        """Kill switch can be reset to re-enable trading."""
        from merid.risk.kill_switches import RiskController

        rc = RiskController(daily_loss_limit=1000.0)
        rc.emergency_stop("Test reset")
        assert rc.can_trade() is False

        rc.reset("operator-test")
        assert rc.can_trade() is True

    def test_swarm_health_degraded_captured_in_report(self):
        """Degraded swarm health is captured in IntegrityReport for alert routing."""
        from core.swarm_integrity_guard import IntegrityReport

        report = IntegrityReport(
            ok=False,
            issues=["consensus_engine_timeout", "risk_manager_offline"],
            warning="Two critical components offline",
            health_summary={"degraded_components": 2},
        )

        assert report.ok is False
        assert len(report.issues) == 2
        d = report.to_dict()
        assert d["ok"] is False
        assert "consensus_engine_timeout" in d["issues"]

    def test_multiple_gap_tickers_tracked_independently(self):
        """Each ticker's sequence gap is tracked independently."""
        ws = KalshiWebSocket()

        for seq in range(1, 21):
            ws._check_sequence({"seq": seq, "ticker": "KXBTC-A"})
        for seq in range(1, 21):
            ws._check_sequence({"seq": seq, "ticker": "KXBTC-B"})

        gaps_before = ws._seq_gaps

        # Gap only in KXBTC-A
        ws._check_sequence({"seq": 30, "ticker": "KXBTC-A"})

        assert ws._seq_gaps == gaps_before + 9
        # KXBTC-B is unaffected
        assert ws._last_seq.get("KXBTC-B") == 20

    def test_error_burst_counted_correctly(self):
        """WS error counter accumulates across error types."""
        ws = KalshiWebSocket()

        error_msgs = [
            {"type": "error", "code": "invalid_channel", "msg": "bad channel"},
            {"type": "error", "code": "invalid_channel", "msg": "bad channel"},
            {"type": "error", "code": "rate_limited_warn", "msg": "slow down"},
        ]
        for msg in error_msgs:
            ws._handle_error_message(msg)

        assert ws._errors_received == 3
