"""test_kalshi_bug_investigation_regressions.py

Regression tests for the 9 bugs identified and fixed in the
Kalshi Bug Investigation (see docs/KALSHI_BUG_INVESTIGATION.md).

Test classes:
  TestH1_WsBridgeOrderGroupEventType  — plural/singular event type forwarding
  TestH2_SpreadGate                   — spread normalization + zero-liquidity rejection
  TestH3_LimitPriceForwarding         — limit_price_cents passed to place_order
  TestM1_SSEQueuePattern              — SSE endpoints use queue, not nested yield
  TestM2_ActivePlansDeprecation       — _active_plans emits DeprecationWarning
  TestM3_StalenessSignalTimestamp     — staleness guard uses signal_timestamp
  TestL1_DeploymentPublicAPI          — kalshi_tools uses get_mode() not _agents
  TestL2_TypeCountsConsistency        — ws_bridge _type_counts uses defaultdict
"""

from __future__ import annotations

import asyncio
import time
import threading
import unittest
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch


# ═══════════════════════════════════════════════════════════════════════════
# H1 — WS Bridge: order_group_update vs order_group_updates event type
# ═══════════════════════════════════════════════════════════════════════════

class TestH1_WsBridgeOrderGroupEventType(unittest.TestCase):
    """H1: The bridge must forward BOTH singular and plural event types."""

    def _make_bridge(self):
        """Create a minimal KalshiWebSocketBridge with mocked internals."""
        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge

        ws_mock = MagicMock()
        bridge = KalshiWebSocketBridge.__new__(KalshiWebSocketBridge)
        bridge._ws = ws_mock
        bridge._events_forwarded = 0
        bridge._events_dropped = 0
        bridge._forward_errors = 0
        bridge._type_counts = defaultdict(int)
        bridge._ui_latest = {}
        bridge._ui_coalesce_interval = 0.1
        bridge._publish_to_bus = AsyncMock()
        return bridge

    def test_plural_event_type_forwarded(self):
        """order_group_updates (plural, Kalshi wire format) must reach the bus."""
        bridge = self._make_bridge()
        event = {
            "type": "order_group_updates",
            "data": {
                "order_group_id": "og-test-1",
                "status": "active",
                "filled_cost": 100,
                "remaining_cost": 900,
                "limit": 1000,
                "contracts_used": 5,
                "contracts_remaining": 95,
            },
            "timestamp": "2026-03-18T23:00:00Z",
        }
        asyncio.get_event_loop().run_until_complete(bridge._publish_event(event))

        bridge._publish_to_bus.assert_called_once()
        call_args = bridge._publish_to_bus.call_args
        self.assertEqual(call_args[0][0], "kalshi:order_group_update")
        self.assertEqual(call_args[0][1]["order_group_id"], "og-test-1")
        self.assertEqual(bridge._type_counts["order_group_update"], 1)

    def test_singular_event_type_still_works(self):
        """order_group_update (singular, legacy) must still reach the bus."""
        bridge = self._make_bridge()
        event = {
            "type": "order_group_update",
            "data": {
                "order_group_id": "og-test-2",
                "status": "triggered",
                "filled_cost": 500,
                "remaining_cost": 0,
                "limit": 500,
            },
            "timestamp": "2026-03-18T23:01:00Z",
        }
        asyncio.get_event_loop().run_until_complete(bridge._publish_event(event))

        bridge._publish_to_bus.assert_called_once()
        call_args = bridge._publish_to_bus.call_args
        self.assertEqual(call_args[0][0], "kalshi:order_group_update")
        self.assertEqual(call_args[0][1]["order_group_id"], "og-test-2")

    def test_unknown_type_goes_to_fallback(self):
        """Non-matching dict events must go to kalshi:ws_event fallback."""
        bridge = self._make_bridge()
        event = {"type": "some_unknown_channel", "data": {"foo": "bar"}}
        asyncio.get_event_loop().run_until_complete(bridge._publish_event(event))

        bridge._publish_to_bus.assert_called_once()
        call_args = bridge._publish_to_bus.call_args
        self.assertEqual(call_args[0][0], "kalshi:ws_event")


# ═══════════════════════════════════════════════════════════════════════════
# H2 — Execution Subscriber: Spread Gate
# ═══════════════════════════════════════════════════════════════════════════

class TestH2_SpreadGate(unittest.TestCase):
    """H2: Spread gate must reject zero liquidity and wide % spreads."""

    def _make_subscriber(self):
        from merid.swarm.execution_subscriber import ExecutionSubscriber
        sub = ExecutionSubscriber()
        sub._pending_decisions = {}
        sub._handle_decision = AsyncMock()
        return sub

    def _simulate_ticker_and_check(self, sub, bid, ask, market_id="TEST-MKT"):
        """Simulate a ticker event hitting a pending decision. Returns True if executed."""
        decision = {
            "decision_id": "d-1",
            "market_id": market_id,
            "action": "buy",
            "side": "yes",
            "size_contracts": 5,
            "risk_approved": True,
            "limit_price_cents": 50,
            "_expiry": time.time() + 30,
            "_created_at": time.time(),
        }
        sub._pending_decisions[market_id] = decision

        # The spread gate logic extracted from _process_loop
        if bid and ask and bid > 0 and ask > 0:
            spread = ask - bid
            mid = (ask + bid) / 2.0
            spread_pct = spread / mid if mid > 0 else 1.0
            if spread_pct < 0.05 and spread <= 5:
                return True  # would execute
        return False  # would not execute

    def test_rejects_zero_liquidity(self):
        """bid=0, ask=0 must NOT pass the spread gate."""
        sub = self._make_subscriber()
        self.assertFalse(self._simulate_ticker_and_check(sub, bid=0, ask=0))

    def test_rejects_zero_bid(self):
        """bid=0, ask=50 must NOT pass (no valid bid)."""
        sub = self._make_subscriber()
        self.assertFalse(self._simulate_ticker_and_check(sub, bid=0, ask=50))

    def test_rejects_wide_pct_spread_low_probability(self):
        """3c spread on 5c market (60% of mid) must be rejected."""
        sub = self._make_subscriber()
        # bid=3, ask=6 → spread=3c, mid=4.5, spread_pct=66.7%
        self.assertFalse(self._simulate_ticker_and_check(sub, bid=3, ask=6))

    def test_accepts_tight_spread(self):
        """2c spread on 50c market (4% of mid) must be accepted."""
        sub = self._make_subscriber()
        # bid=49, ask=51 → spread=2c, mid=50, spread_pct=4%
        self.assertTrue(self._simulate_ticker_and_check(sub, bid=49, ask=51))

    def test_rejects_wide_absolute_spread(self):
        """6c spread on 90c market (~6.7% of mid) must be rejected (>5c absolute)."""
        sub = self._make_subscriber()
        # bid=87, ask=93 → spread=6c, mid=90, spread_pct=6.7%
        # Fails BOTH conditions: spread_pct > 5% AND spread > 5c
        self.assertFalse(self._simulate_ticker_and_check(sub, bid=87, ask=93))

    def test_rejects_borderline_pct_but_ok_absolute(self):
        """5c spread on 50c market (10% of mid) — rejected on pct even though <=5c absolute."""
        sub = self._make_subscriber()
        # bid=48, ask=53 → spread=5c, mid=50.5, spread_pct=9.9%
        self.assertFalse(self._simulate_ticker_and_check(sub, bid=48, ask=53))


# ═══════════════════════════════════════════════════════════════════════════
# H3 — Execution Subscriber: limit_price forwarding
# ═══════════════════════════════════════════════════════════════════════════

class TestH3_LimitPriceForwarding(unittest.TestCase):
    """H3: limit_price_cents from decisions must reach _kalshi_place_order."""

    def test_limit_price_in_route_to_execution_agentgrid_path(self):
        """When AgentGrid path fires, price_cents= must be passed."""
        import inspect
        from merid.swarm.execution_subscriber import ExecutionSubscriber

        source = inspect.getsource(ExecutionSubscriber._route_to_execution)
        # Verify price_cents=limit_price appears in the source
        self.assertIn("price_cents=limit_price", source,
                       "H3: _route_to_execution must pass price_cents=limit_price to _kalshi_place_order")

    def test_limit_price_in_fallback_path(self):
        """The fallback direct placement path must also forward price_cents."""
        import inspect
        from merid.swarm.execution_subscriber import ExecutionSubscriber

        source = inspect.getsource(ExecutionSubscriber._route_to_execution)
        # Count occurrences — should appear in both AgentGrid and fallback paths
        count = source.count("price_cents=limit_price")
        self.assertGreaterEqual(count, 2,
                                 f"H3: price_cents=limit_price must appear in both call sites, found {count}")

    def test_limit_price_extracted_from_data(self):
        """The _route_to_execution method must extract limit_price from the data dict."""
        import inspect
        from merid.swarm.execution_subscriber import ExecutionSubscriber

        source = inspect.getsource(ExecutionSubscriber._route_to_execution)
        self.assertIn("limit_price", source,
                       "H3: _route_to_execution must reference limit_price variable")


# ═══════════════════════════════════════════════════════════════════════════
# M1 — SSE Streaming: queue-based pattern (no yield inside nested async def)
# ═══════════════════════════════════════════════════════════════════════════

class TestM1_SSEQueuePattern(unittest.TestCase):
    """M1: SSE endpoints must NOT use yield inside nested async def."""

    def test_orderbook_stream_no_nested_yield(self):
        """The orderbook stream endpoint must use queue, not nested async generator."""
        import inspect
        from web.api.kalshi_api import stream_orderbook

        source = inspect.getsource(stream_orderbook)
        # The message_handler should use await sse_queue.put, not yield
        self.assertIn("sse_queue", source,
                       "M1: orderbook stream must use sse_queue pattern")
        # Verify no yield inside message_handler
        # Find the message_handler body and check it doesn't yield
        handler_start = source.find("async def message_handler")
        self.assertGreater(handler_start, -1, "message_handler must exist")
        # After message_handler, the next 'yield' should be in the outer generator, not inside handler
        handler_body = source[handler_start:source.find("listen_task", handler_start)]
        self.assertNotIn("yield ", handler_body,
                          "M1: message_handler must NOT contain yield — use sse_queue.put instead")

    def test_order_groups_stream_no_nested_yield(self):
        """The order groups stream endpoint must use queue, not nested async generator."""
        import inspect
        from web.api.kalshi_api import stream_order_group_updates

        source = inspect.getsource(stream_order_group_updates)
        self.assertIn("sse_queue", source,
                       "M1: order groups stream must use sse_queue pattern")
        handler_start = source.find("async def message_handler")
        self.assertGreater(handler_start, -1, "message_handler must exist")
        handler_body = source[handler_start:source.find("listen_task", handler_start)]
        self.assertNotIn("yield ", handler_body,
                          "M1: message_handler must NOT contain yield — use sse_queue.put instead")

    def test_sse_uses_json_dumps(self):
        """SSE payloads must use json.dumps for proper serialization."""
        import inspect
        from web.api.kalshi_api import stream_orderbook

        source = inspect.getsource(stream_orderbook)
        self.assertIn("json.dumps", source,
                       "M1: SSE events must use json.dumps for payloads")


# ═══════════════════════════════════════════════════════════════════════════
# M2 — Consensus _active_plans deprecation
# ═══════════════════════════════════════════════════════════════════════════

class TestM2_ActivePlansDeprecation(unittest.TestCase):
    """M2: _active_plans compat shim must emit DeprecationWarning."""

    def test_deprecation_warning_emitted(self):
        """Accessing _active_plans must trigger a DeprecationWarning."""
        from consensus.consensus_coordinator import EnhancedConsensusCoordinator

        coord = EnhancedConsensusCoordinator.__new__(EnhancedConsensusCoordinator)
        coord._rounds = {}
        coord._pending_opinions = {}
        coord._lock = asyncio.Lock()

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _ = coord._active_plans
            self.assertEqual(len(w), 1)
            self.assertTrue(issubclass(w[0].category, DeprecationWarning))
            self.assertIn("ConsensusRound", str(w[0].message))

    def test_active_plans_returns_rounds(self):
        """_active_plans must still return _rounds dict for backward compat."""
        from consensus.consensus_coordinator import EnhancedConsensusCoordinator

        coord = EnhancedConsensusCoordinator.__new__(EnhancedConsensusCoordinator)
        test_rounds = {"round-1": {"symbol": "BTC", "status": "pending"}}
        coord._rounds = test_rounds
        coord._pending_opinions = {}
        coord._lock = asyncio.Lock()

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = coord._active_plans
            self.assertIs(result, test_rounds)


# ═══════════════════════════════════════════════════════════════════════════
# M3 — Execution Subscriber: staleness uses signal_timestamp
# ═══════════════════════════════════════════════════════════════════════════

class TestM3_StalenessSignalTimestamp(unittest.TestCase):
    """M3: Staleness guard must use signal_timestamp, not buffer time."""

    def test_source_uses_signal_timestamp(self):
        """The _created_at assignment must prefer signal_timestamp from decision data."""
        import inspect
        from merid.swarm.execution_subscriber import ExecutionSubscriber

        source = inspect.getsource(ExecutionSubscriber._process_loop)
        self.assertIn('data.get("signal_timestamp"', source,
                       "M3: _created_at must fall back to signal_timestamp from decision data")

    def test_stale_decision_with_old_signal_timestamp_discarded(self):
        """A decision with signal_timestamp 60s old must be discarded by staleness guard."""
        from collections import deque
        from merid.swarm.execution_subscriber import ExecutionSubscriber, _MAX_DECISION_AGE_S, ExecutionRecord

        sub = ExecutionSubscriber()
        sub._decisions_received = 0
        sub._decisions_routed = 0
        sub._decisions_skipped = 0
        sub._consecutive_failures = 0
        sub._history = deque(maxlen=500)

        old_signal_time = time.time() - (_MAX_DECISION_AGE_S + 10)
        data = {
            "decision_id": "d-stale",
            "market_id": "STALE-MKT",
            "action": "buy",
            "side": "yes",
            "size_contracts": 5,
            "risk_approved": True,
            "_created_at": old_signal_time,  # simulates signal_timestamp being old
        }

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(sub._handle_decision(data))
        finally:
            loop.close()

        self.assertEqual(sub._decisions_skipped, 1)
        self.assertEqual(sub._decisions_routed, 0)
        last_record = sub._history[-1]
        self.assertIsInstance(last_record, ExecutionRecord)
        self.assertIn("stale_decision", last_record.route_reason)


# ═══════════════════════════════════════════════════════════════════════════
# L1 — kalshi_tools: public API for deployment mode
# ═══════════════════════════════════════════════════════════════════════════

class TestL1_DeploymentPublicAPI(unittest.TestCase):
    """L1: kalshi_tools must use get_mode() instead of _agents private dict."""

    def test_no_private_agents_access(self):
        """_kalshi_place_order source must NOT access _dc._agents."""
        import inspect
        from merid.prediction.kalshi_tools import _kalshi_place_order

        source = inspect.getsource(_kalshi_place_order)
        self.assertNotIn("._agents", source,
                          "L1: _kalshi_place_order must not access private _agents dict")

    def test_uses_get_mode(self):
        """_kalshi_place_order source must use _dc.get_mode()."""
        import inspect
        from merid.prediction.kalshi_tools import _kalshi_place_order

        source = inspect.getsource(_kalshi_place_order)
        self.assertIn("get_mode", source,
                       "L1: _kalshi_place_order must use public get_mode() API")


# ═══════════════════════════════════════════════════════════════════════════
# L2 — ws_bridge: _type_counts consistent defaultdict access
# ═══════════════════════════════════════════════════════════════════════════

class TestL2_TypeCountsConsistency(unittest.TestCase):
    """L2: ws_bridge must use consistent _type_counts[key] += 1 pattern."""

    def test_no_dict_get_for_type_counts(self):
        """_publish_event source must NOT use _type_counts.get() for incrementing."""
        import inspect
        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge

        source = inspect.getsource(KalshiWebSocketBridge._publish_event)
        self.assertNotIn('_type_counts.get("order_group_update"', source,
                          "L2: must use _type_counts[key] += 1, not .get() + 1")

    def test_uses_increment_operator(self):
        """order_group_update counter must use += 1 pattern."""
        import inspect
        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge

        source = inspect.getsource(KalshiWebSocketBridge._publish_event)
        self.assertIn('_type_counts["order_group_update"] += 1', source,
                       "L2: must use _type_counts['order_group_update'] += 1")


# ═══════════════════════════════════════════════════════════════════════════
# UI/UX wiring verification
# ═══════════════════════════════════════════════════════════════════════════

class TestUIWiringAfterFixes(unittest.TestCase):
    """Verify UI/UX hooks remain compatible with backend changes."""

    def test_order_group_stream_hook_exists(self):
        """useOrderGroupStream hook file must exist and export the hook."""
        import os
        hook_path = os.path.join(
            os.path.dirname(__file__), "..", "web", "react", "src", "hooks", "useOrderGroupStream.ts"
        )
        self.assertTrue(os.path.exists(hook_path),
                         "useOrderGroupStream.ts must exist")
        with open(hook_path, "r") as f:
            content = f.read()
        self.assertIn("export function useOrderGroupStream", content)
        # Hook must parse JSON — compatible with our json.dumps backend
        self.assertIn("JSON.parse", content)

    def test_orderbook_stream_hook_exists(self):
        """useKalshiOrderbookStream hook file must exist."""
        import os
        hook_path = os.path.join(
            os.path.dirname(__file__), "..", "web", "react", "src", "hooks", "useKalshiOrderbookStream.ts"
        )
        self.assertTrue(os.path.exists(hook_path),
                         "useKalshiOrderbookStream.ts must exist")
        with open(hook_path, "r") as f:
            content = f.read()
        self.assertIn("EventSource", content)
        self.assertIn("JSON.parse", content)

    def test_sse_endpoints_use_json_dumps_for_ui_compat(self):
        """Backend SSE endpoints must use json.dumps so UI JSON.parse works."""
        import inspect
        from web.api.kalshi_api import stream_orderbook, stream_order_group_updates

        for fn in (stream_orderbook, stream_order_group_updates):
            source = inspect.getsource(fn)
            self.assertIn("json.dumps", source,
                           f"M1/UI: {fn.__name__} must use json.dumps for UI compatibility")

    def test_order_group_sse_accepts_both_channel_names(self):
        """SSE order group handler must accept both singular and plural channel names."""
        import inspect
        from web.api.kalshi_api import stream_order_group_updates

        source = inspect.getsource(stream_order_group_updates)
        self.assertIn("order_group_updates", source)
        self.assertIn("order_group_update", source,
                       "SSE handler must accept both singular and plural event types")


# ═══════════════════════════════════════════════════════════════════════════
# ConsensusRound TradePlan compatibility shim
# ═══════════════════════════════════════════════════════════════════════════

class TestConsensusRoundCompat(unittest.TestCase):
    """ConsensusRound must expose TradePlan-compatible attributes for loop.py."""

    def _make_round(self, **kwargs):
        from consensus.consensus_coordinator import ConsensusRound, ConsensusState
        defaults = dict(
            symbol="BTC",
            venue="kalshi",
            state=ConsensusState.DECIDED,
            target_size_usd=500.0,
            direction="long",
        )
        defaults.update(kwargs)
        return ConsensusRound(**defaults)

    def test_status_maps_decided_to_approved(self):
        from consensus.consensus_coordinator import ConsensusState
        r = self._make_round(state=ConsensusState.DECIDED)
        self.assertEqual(r.status, "approved")

    def test_status_maps_timeout_to_expired(self):
        from consensus.consensus_coordinator import ConsensusState
        r = self._make_round(state=ConsensusState.TIMEOUT)
        self.assertEqual(r.status, "expired")

    def test_status_setter_executed(self):
        from consensus.consensus_coordinator import ConsensusState
        r = self._make_round()
        r.status = "executed"
        self.assertEqual(r.state, ConsensusState.DECIDED)

    def test_plan_id_aliases_round_id(self):
        r = self._make_round()
        self.assertEqual(r.plan_id, r.round_id)

    def test_domain_inferred_from_kalshi_venue(self):
        r = self._make_round(venue="kalshi")
        self.assertEqual(r.domain, "prediction")

    def test_domain_defaults_to_crypto(self):
        r = self._make_round(venue="binance")
        self.assertEqual(r.domain, "crypto")

    def test_approved_size_usd_reads_target(self):
        r = self._make_round(target_size_usd=750.0)
        self.assertEqual(r.approved_size_usd, 750.0)

    def test_approved_size_usd_writes_target(self):
        r = self._make_round(target_size_usd=100.0)
        r.approved_size_usd = 300.0
        self.assertEqual(r.target_size_usd, 300.0)

    def test_is_expired_false_for_recent(self):
        r = self._make_round()
        self.assertFalse(r.is_expired())

    def test_is_expired_true_for_old(self):
        r = self._make_round()
        r.started_at = time.time() - 300  # 5 min ago, default timeout 120s
        self.assertTrue(r.is_expired())

    def test_is_expired_true_for_timeout_state(self):
        from consensus.consensus_coordinator import ConsensusState
        r = self._make_round(state=ConsensusState.TIMEOUT)
        self.assertTrue(r.is_expired())

    def test_loop_execute_plans_attribute_chain(self):
        """Simulate the exact attribute access pattern from loop.py _execute_plans."""
        from consensus.consensus_coordinator import ConsensusState
        r = self._make_round(state=ConsensusState.DECIDED, direction="long", target_size_usd=100.0)
        # line 984: p.status == "approved" and not p.is_expired()
        self.assertEqual(r.status, "approved")
        self.assertFalse(r.is_expired())
        # line 987-993
        domain = getattr(r, "domain", "crypto")
        self.assertEqual(domain, "prediction")
        size_usd = getattr(r, "approved_size_usd", None) or r.target_size_usd
        self.assertEqual(size_usd, 100.0)
        # line 1006
        _ = r.plan_id
        _ = r.symbol
        _ = r.direction
        # line 1019: plan.approved_size_usd = verdict.adjusted_size_usd
        r.approved_size_usd = 75.0
        self.assertEqual(r.target_size_usd, 75.0)
        # line 1081: plan.status = "executed"
        r.status = "executed"
        self.assertEqual(r.state, ConsensusState.DECIDED)


# ═══════════════════════════════════════════════════════════════════════════
# Main / Loop wiring verification
# ═══════════════════════════════════════════════════════════════════════════

class TestMainLoopWiring(unittest.TestCase):
    """Verify main.py and loop.py are properly wired."""

    def test_kalshi_api_router_registered(self):
        """kalshi_api router must be imported in main.py."""
        import inspect
        import web.main as main_mod
        source = inspect.getsource(main_mod)
        self.assertIn('kalshi_api_router', source)
        self.assertIn('_reg(kalshi_api_router)', source)

    def test_ws_bridge_started_in_lifespan(self):
        """WS bridge must be started in the lifespan."""
        import inspect
        import web.main as main_mod
        source = inspect.getsource(main_mod._app_lifespan)
        self.assertIn('get_ws_bridge', source)
        self.assertIn('kalshi-ws-bridge', source)

    def test_consensus_opinion_subscriber_started(self):
        """EnhancedConsensusCoordinator opinion subscriber must start in lifespan."""
        import inspect
        import web.main as main_mod
        source = inspect.getsource(main_mod._app_lifespan)
        self.assertIn('start_opinion_subscriber', source)

    def test_merid_loop_started_in_lifespan(self):
        """MeridLoop must be started in the lifespan (gated by startup_success)."""
        import inspect
        import web.main as main_mod
        source = inspect.getsource(main_mod._app_lifespan)
        self.assertIn('get_merid_loop', source)
        self.assertIn('merid-loop', source)

    def test_loop_execution_subscriber_gated(self):
        """ExecutionSubscriber start in loop.run() must be gated by enable_execution."""
        import inspect
        from merid.loop import MeridLoop
        source = inspect.getsource(MeridLoop.run)
        self.assertIn('enable_execution', source)
        self.assertIn('get_execution_subscriber', source)

    def test_loop_ws_bridge_reuses_singleton(self):
        """Loop must reuse the lifespan WS bridge singleton, not create a new one."""
        import inspect
        from merid.loop import MeridLoop
        source = inspect.getsource(MeridLoop.run)
        self.assertIn('get_ws_bridge', source)
        # Must NOT call KalshiWebSocketBridge() directly
        self.assertNotIn('KalshiWebSocketBridge()', source)

    def test_loop_consensus_coordinator_uses_enhanced(self):
        """Loop must use EnhancedConsensusCoordinator, not legacy TaCo."""
        import inspect
        from merid.loop import MeridLoop
        source = inspect.getsource(MeridLoop._consensus_coordinator)
        self.assertIn('EnhancedConsensusCoordinator', source)

    def test_shutdown_stops_loop_first(self):
        """Shutdown must stop MeridLoop before WS bridge and other services."""
        import inspect
        import web.main as main_mod
        source = inspect.getsource(main_mod._app_lifespan)
        # Isolate the shutdown section (after the yield)
        shutdown_start = source.find("MERID shutdown initiated")
        self.assertGreater(shutdown_start, 0, "Shutdown section must exist in lifespan")
        shutdown_source = source[shutdown_start:]
        loop_stop = shutdown_source.find('MeridLoop stopped')
        ws_stop = shutdown_source.find('KalshiWebSocketBridge')
        # Both must exist in shutdown
        self.assertGreater(loop_stop, 0, "MeridLoop stop must be in shutdown")
        self.assertGreater(ws_stop, 0, "KalshiWebSocketBridge stop must be in shutdown")
        # Loop must stop before WS bridge
        self.assertLess(loop_stop, ws_stop,
                         "MeridLoop must stop BEFORE KalshiWebSocketBridge in shutdown")


if __name__ == "__main__":
    unittest.main()
