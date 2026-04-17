"""Tests for merid.tick_events — canonical tick event schema and bus.

Coverage:
- TickContext: emit_started, emit_snapshot, emit_agent_cycle, emit_risk_check,
  emit_order_submitted, emit_order_rejected, emit_fill, emit_stop_loss,
  emit_session_gated, emit_error, finalise
- TickSummary: all counter fields roll up correctly
- TickEventBus: emit, subscribe, unsubscribe, recent_summaries, recent_events, stats
- Singleton: get_tick_bus returns same instance
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from merid.tick_events import (
    AGENT_CYCLE_COMPLETED,
    DATA_SNAPSHOT_TAKEN,
    FILL_RECEIVED,
    ORDER_REJECTED,
    ORDER_SUBMITTED,
    RISK_CHECKED,
    SESSION_GATED,
    STOP_LOSS_TRIGGERED,
    TICK_ERROR,
    TICK_STARTED,
    TICK_SUMMARY,
    TickContext,
    TickEvent,
    TickEventBus,
    TickSummary,
    get_tick_bus,
)


# ── TickContext ────────────────────────────────────────────────────────


class TestTickContext:
    def _ctx(self, agent_id: str = "test_agent", cycle: int = 1) -> TickContext:
        return TickContext(agent_id=agent_id, cycle_number=cycle, mode="paper")

    def test_tick_id_is_unique(self):
        a = self._ctx()
        b = self._ctx()
        assert a.tick_id != b.tick_id

    def test_emit_started_fields(self):
        ctx = self._ctx()
        ev = ctx.emit_started()
        assert ev.event == TICK_STARTED
        assert ev.tick_id == ctx.tick_id
        assert ev.agent_id == "test_agent"
        assert ev.mode == "paper"
        assert ev.payload["cycle_number"] == 1

    def test_emit_snapshot_updates_context(self):
        ctx = self._ctx()
        ev = ctx.emit_snapshot(markets_resolved=10, markets_in_window=3, session_allowed=True)
        assert ev.event == DATA_SNAPSHOT_TAKEN
        assert ctx.markets_resolved == 10
        assert ctx.markets_in_window == 3
        assert ctx.session_allowed is True
        assert ev.payload["markets_resolved"] == 10

    def test_emit_snapshot_session_blocked(self):
        ctx = self._ctx()
        ev = ctx.emit_snapshot(markets_resolved=0, markets_in_window=0, session_allowed=False)
        assert ctx.session_allowed is False

    def test_emit_agent_cycle_accumulates(self):
        ctx = self._ctx()
        ctx.emit_agent_cycle(signals_evaluated=5, signals_actionable=2, signals_consensus_blocked=1)
        ctx.emit_agent_cycle(signals_evaluated=3, signals_actionable=1, signals_consensus_blocked=0)
        assert ctx.signals_evaluated == 8
        assert ctx.signals_actionable == 3
        assert ctx.signals_consensus_blocked == 1

    def test_emit_agent_cycle_event(self):
        ctx = self._ctx()
        ev = ctx.emit_agent_cycle(signals_evaluated=4, signals_actionable=2)
        assert ev.event == AGENT_CYCLE_COMPLETED
        assert ev.payload["signals_evaluated"] == 4

    def test_emit_risk_check_allowed(self):
        ctx = self._ctx()
        ev = ctx.emit_risk_check("MKT-001", allowed=True)
        assert ev.event == RISK_CHECKED
        assert ctx.risk_allowed == 1
        assert ctx.risk_blocked == 0
        assert ev.payload["allowed"] is True

    def test_emit_risk_check_blocked(self):
        ctx = self._ctx()
        ev = ctx.emit_risk_check("MKT-001", allowed=False, reason="notional_cap")
        assert ctx.risk_allowed == 0
        assert ctx.risk_blocked == 1
        assert ev.payload["reason"] == "notional_cap"

    def test_emit_order_submitted(self):
        ctx = self._ctx()
        ev = ctx.emit_order_submitted("MKT-001", side="yes", contracts=5, price_cents=65, order_id="abc123")
        assert ev.event == ORDER_SUBMITTED
        assert ctx.orders_submitted == 1
        assert ev.payload["contracts"] == 5
        assert ev.payload["order_id"] == "abc123"

    def test_emit_order_rejected(self):
        ctx = self._ctx()
        ev = ctx.emit_order_rejected("MKT-001", reason="venue_error")
        assert ev.event == ORDER_REJECTED
        assert ctx.orders_rejected == 1

    def test_emit_fill(self):
        ctx = self._ctx()
        ev = ctx.emit_fill("MKT-001", side="yes", contracts=3, fill_price_cents=66)
        assert ev.event == FILL_RECEIVED
        assert ctx.fills_confirmed == 1
        assert ev.payload["fill_price_cents"] == 66

    def test_emit_stop_loss(self):
        ctx = self._ctx()
        ev = ctx.emit_stop_loss("MKT-SL", rule="max_loss", reason="exceeded 20%")
        assert ev.event == STOP_LOSS_TRIGGERED
        assert ctx.stop_losses_triggered == 1

    def test_emit_session_gated(self):
        ctx = self._ctx()
        ev = ctx.emit_session_gated("outside_session_window")
        assert ev.event == SESSION_GATED
        assert ctx.session_allowed is False

    def test_emit_error(self):
        ctx = self._ctx()
        ev = ctx.emit_error("something_broke")
        assert ev.event == TICK_ERROR
        assert ctx.error == "something_broke"

    def test_finalise_rolls_up_correctly(self):
        ctx = self._ctx(cycle=7)
        ctx.emit_snapshot(markets_resolved=5, markets_in_window=2, session_allowed=True)
        ctx.emit_risk_check("M1", allowed=True)
        ctx.emit_risk_check("M2", allowed=False, reason="cap")
        ctx.emit_order_submitted("M1", "yes", 2, 60)
        ctx.emit_fill("M1", "yes", 2, 61)
        ctx.emit_agent_cycle(signals_evaluated=3, signals_actionable=2)

        summary = ctx.finalise()
        assert isinstance(summary, TickSummary)
        assert summary.tick_id == ctx.tick_id
        assert summary.agent_id == "test_agent"
        assert summary.cycle_number == 7
        assert summary.markets_resolved == 5
        assert summary.risk_allowed == 1
        assert summary.risk_blocked == 1
        assert summary.orders_submitted == 1
        assert summary.fills_confirmed == 1
        assert summary.signals_evaluated == 3
        assert summary.duration_ms >= 0

    def test_finalise_to_dict_contains_event_field(self):
        ctx = self._ctx()
        summary = ctx.finalise()
        d = summary.to_dict()
        assert d["event"] == TICK_SUMMARY
        assert "tick_id" in d
        assert "duration_ms" in d
        assert "orders_submitted" in d

    def test_tick_event_to_dict_merges_payload(self):
        ctx = self._ctx()
        ev = ctx.emit_order_submitted("MKT-X", "no", 1, 40, order_id="xyz")
        d = ev.to_dict()
        assert d["event"] == ORDER_SUBMITTED
        assert d["agent_id"] == "test_agent"
        assert d["market_id"] == "MKT-X"
        assert d["order_id"] == "xyz"


# ── TickEventBus ──────────────────────────────────────────────────────


class TestTickEventBus:
    def _bus(self) -> TickEventBus:
        return TickEventBus(max_summaries=20, max_events=50)

    def _summary(self, tick_id: str = "abc", agent: str = "ag1") -> TickSummary:
        t = time.time()
        return TickSummary(
            tick_id=tick_id,
            agent_id=agent,
            ts_started=t - 0.1,
            ts_ended=t,
            duration_ms=100.0,
        )

    def _event(self, tick_id: str = "abc", event: str = ORDER_SUBMITTED) -> TickEvent:
        return TickEvent(event=event, tick_id=tick_id, agent_id="ag1", payload={"market_id": "M1"})

    def test_emit_summary_stored(self):
        bus = self._bus()
        bus.emit(self._summary("t1"))
        summaries = bus.recent_summaries(10)
        assert len(summaries) == 1
        assert summaries[0]["tick_id"] == "t1"

    def test_emit_event_stored(self):
        bus = self._bus()
        bus.emit(self._event("t1"))
        events = bus.recent_events(10)
        assert len(events) == 1
        assert events[0]["event"] == ORDER_SUBMITTED

    def test_max_summaries_cap(self):
        bus = self._bus()
        for i in range(30):
            bus.emit(self._summary(f"t{i}"))
        assert len(bus.recent_summaries(100)) == 20

    def test_max_events_cap(self):
        bus = self._bus()
        for i in range(60):
            bus.emit(self._event(f"t{i}"))
        assert len(bus.recent_events(100)) == 50

    def test_recent_summaries_limit(self):
        bus = self._bus()
        for i in range(10):
            bus.emit(self._summary(f"t{i}"))
        assert len(bus.recent_summaries(5)) == 5

    def test_stats_empty(self):
        bus = self._bus()
        stats = bus.stats()
        assert stats["total_ticks"] == 0
        assert stats["subscribers"] == 0

    def test_stats_with_data(self):
        bus = self._bus()
        s1 = self._summary("t1")
        s1.orders_submitted = 3
        s1.fills_confirmed = 2
        s2 = self._summary("t2")
        s2.error = "boom"
        bus.emit(s1)
        bus.emit(s2)
        stats = bus.stats()
        assert stats["total_ticks"] == 2
        assert stats["error_rate"] == 0.5
        assert stats["total_orders_submitted"] == 3
        assert stats["total_fills_confirmed"] == 2

    def test_subscribe_receives_events(self):
        """Subscriber queue receives emitted events."""
        bus = self._bus()
        q = bus.subscribe()
        ev = self._event("t1")
        bus.emit(ev)
        assert not q.empty()
        item = q.get_nowait()
        assert item["tick_id"] == "t1"

    def test_unsubscribe_stops_delivery(self):
        bus = self._bus()
        q = bus.subscribe()
        bus.unsubscribe(q)
        bus.emit(self._event("t1"))
        assert q.empty()

    def test_full_queue_does_not_raise(self):
        bus = self._bus()
        q = bus.subscribe(maxsize=1)
        # Fill the queue
        bus.emit(self._event("t1"))
        # This should not raise even though queue is full
        bus.emit(self._event("t2"))

    def test_summary_not_duplicated_in_events_only(self):
        """TickSummary goes to both _summaries and _events lists."""
        bus = self._bus()
        bus.emit(self._summary("t1"))
        assert len(bus.recent_summaries(10)) == 1
        assert len(bus.recent_events(10)) == 1


# ── Singleton ─────────────────────────────────────────────────────────


class TestTickBusSingleton:
    def test_get_tick_bus_same_instance(self):
        a = get_tick_bus()
        b = get_tick_bus()
        assert a is b

    def test_get_tick_bus_returns_tick_event_bus(self):
        assert isinstance(get_tick_bus(), TickEventBus)


# ── Integration: emit full tick lifecycle ────────────────────────────


class TestTickLifecycle:
    def test_full_tick_emitted_to_bus(self):
        bus = TickEventBus(max_summaries=50, max_events=200)
        q = bus.subscribe()

        ctx = TickContext(agent_id="btc15m", cycle_number=42, mode="paper")
        bus.emit(ctx.emit_started())
        bus.emit(ctx.emit_snapshot(5, 2, True))
        bus.emit(ctx.emit_risk_check("MKT-BTC-001", allowed=True))
        bus.emit(ctx.emit_order_submitted("MKT-BTC-001", "yes", 1, 65))
        bus.emit(ctx.emit_fill("MKT-BTC-001", "yes", 1, 65))
        bus.emit(ctx.emit_agent_cycle(signals_evaluated=1, signals_actionable=1))
        summary = ctx.finalise()
        bus.emit(summary)

        # 7 events delivered to subscriber
        events_delivered = []
        while not q.empty():
            events_delivered.append(q.get_nowait())
        assert len(events_delivered) == 7

        event_names = [e["event"] for e in events_delivered]
        assert event_names[0] == TICK_STARTED
        assert event_names[-1] == TICK_SUMMARY

        # Summary is also in recent_summaries
        summaries = bus.recent_summaries(10)
        assert len(summaries) == 1
        assert summaries[0]["orders_submitted"] == 1
        assert summaries[0]["fills_confirmed"] == 1
        assert summaries[0]["cycle_number"] == 42

    def test_error_tick_lifecycle(self):
        bus = TickEventBus()
        ctx = TickContext(agent_id="btc15m", cycle_number=1)
        bus.emit(ctx.emit_started())
        bus.emit(ctx.emit_error("market_resolution_timeout"))
        summary = ctx.finalise()
        bus.emit(summary)

        summaries = bus.recent_summaries(5)
        assert summaries[-1]["error"] == "market_resolution_timeout"
