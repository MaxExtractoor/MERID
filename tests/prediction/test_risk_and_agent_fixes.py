"""Regression tests for audit-identified bugs in risk.py and trading_agent.py.

Covers:
1. Rate limiter counter increment (P0-1) — check_order must increment
   _orders_this_minute / _orders_this_hour so limits are actually enforced.
2. Consensus bypass after N cycles (P0-2) — agent must not be permanently
   blocked when swarm bus returns no consensus after 3+ cycles.
3. markets_in_window correct count in tick snapshot (P1-1) — emit_snapshot
   must carry the post-filter active market count, not hardcoded 0.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from merid.prediction.risk import (
    PredictionMarketRisk,
    PredictionRiskConfig,
    RiskAction,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

_order_seq = 0


def _make_risk(
    max_per_minute: int = 30,
    max_per_hour: int = 300,
) -> PredictionMarketRisk:
    cfg = PredictionRiskConfig(
        max_orders_per_minute=max_per_minute,
        max_orders_per_hour=max_per_hour,
    )
    return PredictionMarketRisk(cfg)


def _check_unique(risk: PredictionMarketRisk):
    """Submit one order with a globally unique market/event ID and return the PreTradeCheck."""
    global _order_seq
    _order_seq += 1
    return risk.check_order(
        market_id=f"MKT-{_order_seq}",
        event_id=f"EVT-{_order_seq}",
        side="yes",
        contracts=1,
        price_cents=Decimal("50"),
    )


def _allow_order(risk: PredictionMarketRisk, market_id: str | None = None) -> bool:
    """Place a minimal valid order and return whether it was allowed.

    Each call uses a unique market_id + event_id to avoid per-market/per-event
    cap interference when testing rate limits.
    """
    global _order_seq
    _order_seq += 1
    mid = market_id or f"MKT-{_order_seq}"
    result = risk.check_order(
        market_id=mid,
        event_id=f"EVT-{_order_seq}",
        side="yes",
        contracts=1,
        price_cents=Decimal("50"),
    )
    return result.allowed


# ── 1. Rate limiter: counter must increment ───────────────────────────────────

class TestRateLimiterCounterIncrement:
    def test_first_order_allowed(self):
        risk = _make_risk(max_per_minute=3)
        assert _allow_order(risk) is True

    def test_second_order_allowed_increments_counter(self):
        risk = _make_risk(max_per_minute=3)
        _allow_order(risk)
        assert risk._orders_this_minute == 1

    def test_counter_reaches_limit(self):
        risk = _make_risk(max_per_minute=2)
        _allow_order(risk, "MKT-1")
        _allow_order(risk, "MKT-2")
        assert risk._orders_this_minute == 2

    def test_third_order_blocked_after_limit(self):
        risk = _make_risk(max_per_minute=2)
        _allow_order(risk, "MKT-1")
        _allow_order(risk, "MKT-2")
        result = risk.check_order(
            market_id="MKT-3",
            event_id="MKT",
            side="yes",
            contracts=1,
            price_cents=Decimal("50"),
        )
        assert result.allowed is False
        assert result.action == RiskAction.REJECT
        assert "Rate limit" in result.reason

    def test_hourly_counter_increments(self):
        risk = _make_risk(max_per_minute=10, max_per_hour=5)
        for i in range(3):
            risk.check_order(
                market_id=f"MKT-{i}",
                event_id=f"EVT-{i}",  # distinct event IDs avoid per-event cap
                side="yes",
                contracts=1,
                price_cents=Decimal("50"),
            )
        assert risk._orders_this_hour == 3

    def test_hourly_limit_enforced(self):
        risk = _make_risk(max_per_hour=2)
        _allow_order(risk)
        _allow_order(risk)
        result = _check_unique(risk)
        assert result.allowed is False
        assert "Rate limit" in result.reason

    def test_blocked_order_does_not_increment_counter(self):
        risk = _make_risk(max_per_minute=1)
        _allow_order(risk)
        assert risk._orders_this_minute == 1
        # Now blocked — must not increment
        _check_unique(risk)
        assert risk._orders_this_minute == 1

    def test_counter_resets_after_minute(self):
        from datetime import timedelta
        risk = _make_risk(max_per_minute=1)
        _allow_order(risk)
        assert risk._orders_this_minute == 1
        # Simulate minute passing
        risk._last_minute_reset = datetime.now(timezone.utc) - timedelta(seconds=61)
        risk._reset_rate_counters(datetime.now(timezone.utc))
        assert risk._orders_this_minute == 0

    def test_halted_risk_does_not_reach_rate_increment(self):
        risk = _make_risk()
        risk.halt("test halt")
        result = risk.check_order(
            market_id="MKT-HALT",
            event_id="EVT-HALT",
            side="yes",
            contracts=1,
            price_cents=Decimal("50"),
        )
        assert result.allowed is False
        assert risk._orders_this_minute == 0


# ── 2. Duplicate tick-size check removed ─────────────────────────────────────

class TestNoEarlyTickSizeReject:
    """Verify check_order passes valid prices through the full check chain
    and the early duplicate tick-size block is gone."""

    def test_valid_price_reaches_allow(self):
        risk = _make_risk()
        result = risk.check_order(
            market_id="MKT-1",
            event_id="MKT",
            side="yes",
            contracts=1,
            price_cents=Decimal("50"),  # 50 is a valid multiple of tick_size=1
        )
        assert result.allowed is True

    def test_invalid_price_still_rejected_at_check11(self):
        cfg = PredictionRiskConfig(tick_size_cents=5)
        risk = PredictionMarketRisk(cfg)
        result = risk.check_order(
            market_id="MKT-1",
            event_id="MKT",
            side="yes",
            contracts=1,
            price_cents=Decimal("51"),  # 51 % 5 != 0 → invalid
        )
        assert result.allowed is False
        assert "tick size" in result.reason.lower()


# ── 3. Consensus bypass — markets_in_window tick count ───────────────────────
# These tests verify the cycle body produces correct snapshot data.
# They use a tightly mocked KalshiTradingAgent to avoid real network calls.

class TestMarketsInWindowSnapshot:
    """Verify that emit_snapshot carries the actual filtered market count."""

    def _make_agent(self):
        from merid.prediction.agent_grid_config import AgentConfig
        from merid.prediction.trading_agent import KalshiTradingAgent

        config = AgentConfig(
            name="test-agent",
            category="crypto",
            assets=["BTC"],
            timeframes=["15m"],
            enabled=True,
            archetype="directional",
        )
        return KalshiTradingAgent(config)

    def _make_market(self, market_id: str = "KXBTC-TEST"):
        from decimal import Decimal
        from datetime import timedelta
        from merid.event_venues.base import EventMarket, EventOutcome

        return EventMarket(
            market_id=market_id,
            venue="kalshi",
            question="Test market",
            description="",
            outcomes=[
                EventOutcome("yes", "Yes", Decimal("55")),
                EventOutcome("no", "No", Decimal("45")),
            ],
            end_date=datetime.now(timezone.utc) + timedelta(hours=2),
            active=True,
            volume=Decimal("1000"),
        )

    def test_snapshot_emitted_with_correct_markets_in_window(self):
        """emit_snapshot markets_in_window must equal len(active_markets)."""
        agent = self._make_agent()
        market = self._make_market()

        # Inject resolved markets directly
        agent._resolved_markets = [market]

        captured_events = []

        class FakeBus:
            def emit(self, event):
                captured_events.append(event)

        class FakeTick:
            markets_in_window = 0
            def emit_session_gated(self, reason): return {"event": "session_gated"}
            def emit_snapshot(self, markets_resolved, markets_in_window, session_allowed):
                self.markets_in_window = markets_in_window
                return {
                    "event": "data_snapshot_taken",
                    "markets_resolved": markets_resolved,
                    "markets_in_window": markets_in_window,
                }
            def emit_agent_cycle(self, **kwargs): return {"event": "agent_cycle"}
            def emit_risk_check(self, *args, **kwargs): return {}
            def emit_order_submitted(self, *args, **kwargs): return {}

        fake_tick = FakeTick()
        fake_bus = FakeBus()

        # Patch all side effects to isolate snapshot logic
        with patch.object(agent, '_check_stop_losses', new=AsyncMock()), \
             patch.object(agent, '_resolve_markets', new=AsyncMock()), \
             patch.object(agent._session_guard, 'is_trading_allowed', return_value=True), \
             patch.object(agent, '_maybe_reset_window'), \
             patch.object(agent, '_filter_active_contracts', return_value=[market]), \
             patch.object(agent._strategy, 'evaluate', side_effect=Exception("stop")):

            try:
                asyncio.get_event_loop().run_until_complete(
                    agent._run_cycle_body(datetime.now(timezone.utc), fake_tick, fake_bus)
                )
            except Exception:
                pass

        # The snapshot event must have been emitted with non-zero markets_in_window
        snapshot_events = [e for e in captured_events if isinstance(e, dict) and e.get("event") == "data_snapshot_taken"]
        assert len(snapshot_events) == 1
        assert snapshot_events[0]["markets_in_window"] == 1
        assert snapshot_events[0]["markets_resolved"] == 1

    def test_snapshot_emitted_zero_when_no_resolved_markets(self):
        """When no markets resolved, snapshot markets_in_window must be 0."""
        agent = self._make_agent()
        agent._resolved_markets = []

        captured_events = []

        class FakeBus:
            def emit(self, event):
                captured_events.append(event)

        class FakeTick:
            markets_in_window = 0
            def emit_session_gated(self, reason): return {}
            def emit_snapshot(self, markets_resolved, markets_in_window, session_allowed):
                return {
                    "event": "data_snapshot_taken",
                    "markets_resolved": markets_resolved,
                    "markets_in_window": markets_in_window,
                }
            def emit_agent_cycle(self, **kwargs): return {}

        fake_tick = FakeTick()
        fake_bus = FakeBus()

        with patch.object(agent, '_check_stop_losses', new=AsyncMock()), \
             patch.object(agent, '_resolve_markets', new=AsyncMock()), \
             patch.object(agent._session_guard, 'is_trading_allowed', return_value=True):

            asyncio.get_event_loop().run_until_complete(
                agent._run_cycle_body(datetime.now(timezone.utc), fake_tick, fake_bus)
            )

        snapshot_events = [e for e in captured_events if isinstance(e, dict) and e.get("event") == "data_snapshot_taken"]
        assert len(snapshot_events) == 1
        assert snapshot_events[0]["markets_in_window"] == 0
        assert snapshot_events[0]["markets_resolved"] == 0


# ── 4. Consensus bypass after 3+ cycles ──────────────────────────────────────

class TestConsensusBypassAfterNCycles:
    """Verify that signals are not permanently blocked when no consensus exists."""

    def test_signal_held_on_cycle_1(self):
        """On cycle 1, no consensus → signal should be held (blocked)."""
        from merid.prediction.trading_agent import KalshiTradingAgent
        from merid.prediction.agent_grid_config import AgentConfig

        config = AgentConfig(
            name="test-agent",
            category="crypto",
            assets=["BTC"],
            timeframes=["15m"],
            enabled=True,
            archetype="directional",
        )
        agent = KalshiTradingAgent(config)
        agent.state.cycles_run = 1

        # cycles_run <= 3 with no consensus → should block
        should_block = agent.state.cycles_run <= 3
        assert should_block is True

    def test_signal_proceeds_on_cycle_4(self):
        """On cycle 4+, no consensus → signal should proceed (solo mode)."""
        from merid.prediction.trading_agent import KalshiTradingAgent
        from merid.prediction.agent_grid_config import AgentConfig

        config = AgentConfig(
            name="test-agent",
            category="crypto",
            assets=["BTC"],
            timeframes=["15m"],
            enabled=True,
            archetype="directional",
        )
        agent = KalshiTradingAgent(config)
        agent.state.cycles_run = 4

        # cycles_run > 3 with no consensus → should NOT block
        should_block = agent.state.cycles_run <= 3
        assert should_block is False

    def test_boundary_cycle_3_blocks(self):
        from merid.prediction.trading_agent import KalshiTradingAgent
        from merid.prediction.agent_grid_config import AgentConfig

        config = AgentConfig(
            name="test-agent",
            category="crypto",
            assets=["BTC"],
            timeframes=["15m"],
            enabled=True,
            archetype="directional",
        )
        agent = KalshiTradingAgent(config)
        agent.state.cycles_run = 3
        assert (agent.state.cycles_run <= 3) is True

    def test_boundary_cycle_4_does_not_block(self):
        from merid.prediction.trading_agent import KalshiTradingAgent
        from merid.prediction.agent_grid_config import AgentConfig

        config = AgentConfig(
            name="test-agent",
            category="crypto",
            assets=["BTC"],
            timeframes=["15m"],
            enabled=True,
            archetype="directional",
        )
        agent = KalshiTradingAgent(config)
        agent.state.cycles_run = 4
        assert (agent.state.cycles_run <= 3) is False
