"""Regression tests for Trading-Lifecycle Audit Sprint 1 fixes.

Covers:
  C2 — record_pnl() wired into WS fill handler + position-value background loop
  C3 — record_order_rejection() / record_order_success() in _route_live()
  C4 — PositionSizer.compute() returns 0 when hourly cap exhausted
  C5 — SwarmConsensusEngine derives action from proposal side (not hardcoded buy)
  C6 — existing_position lookup fail-closed in live mode
  L1 — reset() clears _consecutive_rejections
"""

import ast
import inspect
import textwrap
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# C2 — record_pnl wired into WS fill handler
# ---------------------------------------------------------------------------

class TestC2RecordPnlWiredIntoWSFillHandler(unittest.TestCase):
    """C2: The WS bridge fill handler must call risk_controller.record_pnl()
    whenever a fill changes a position's realized PnL."""

    def test_ws_bridge_publish_event_contains_record_pnl_call(self):
        """Source code of _publish_event must reference record_pnl."""
        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge
        src = inspect.getsource(KalshiWebSocketBridge._publish_event)
        self.assertIn("record_pnl", src,
                       "C2: _publish_event must call record_pnl after fill")

    def test_ws_bridge_publish_event_snapshots_pnl_before_fill(self):
        """Source must snapshot realized_pnl_usd BEFORE calling on_fill."""
        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge
        src = inspect.getsource(KalshiWebSocketBridge._publish_event)
        before_idx = src.index("_rpnl_before")
        on_fill_idx = src.index("cache.on_fill")
        self.assertLess(before_idx, on_fill_idx,
                        "C2: must snapshot PnL before on_fill()")

    def test_ws_bridge_position_value_loop_exists(self):
        """C2: bridge must have a _position_value_loop method."""
        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge
        self.assertTrue(hasattr(KalshiWebSocketBridge, "_position_value_loop"),
                        "C2: _position_value_loop missing from bridge")

    def test_ws_bridge_position_value_loop_calls_update_position_value(self):
        """_position_value_loop must call risk_controller.update_position_value."""
        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge
        src = inspect.getsource(KalshiWebSocketBridge._position_value_loop)
        self.assertIn("update_position_value", src)

    def test_ws_bridge_start_launches_position_value_task(self):
        """start() -> _post_connect_start() must create _position_value_task."""
        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge
        src = inspect.getsource(KalshiWebSocketBridge._post_connect_start)
        self.assertIn("_position_value_task", src,
                       "C2: _post_connect_start() must launch _position_value_task")

    def test_ws_bridge_stop_cancels_position_value_task(self):
        """stop() must cancel _position_value_task."""
        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge
        src = inspect.getsource(KalshiWebSocketBridge.stop)
        self.assertIn("_position_value_task", src,
                       "C2: stop() must cancel _position_value_task")

    def test_ws_bridge_has_post_connect_start(self):
        """Bridge must have _post_connect_start for retry path."""
        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge
        self.assertTrue(hasattr(KalshiWebSocketBridge, "_post_connect_start"),
                        "Bridge must have _post_connect_start method")

    def test_ws_bridge_start_has_background_retry(self):
        """start() must schedule background retry on connect failure."""
        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge
        src = inspect.getsource(KalshiWebSocketBridge.start)
        self.assertIn("_background_connect_retry", src,
                       "start() must have background connect retry logic")

    def test_ws_bridge_has_retry_task_attr(self):
        """Bridge __init__ must define _retry_task."""
        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge
        bridge = KalshiWebSocketBridge.__new__(KalshiWebSocketBridge)
        # Just check the class has the init pattern
        src = inspect.getsource(KalshiWebSocketBridge.__init__)
        self.assertIn("_retry_task", src,
                       "__init__ must define _retry_task attribute")

    def test_ws_bridge_stop_cancels_retry_task(self):
        """stop() must cancel _retry_task."""
        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge
        src = inspect.getsource(KalshiWebSocketBridge.stop)
        self.assertIn("_retry_task", src,
                       "stop() must cancel _retry_task")

    def test_ws_bridge_status_includes_retry_pending(self):
        """status() must include retry_pending field."""
        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge
        src = inspect.getsource(KalshiWebSocketBridge.status)
        self.assertIn("retry_pending", src,
                       "status() must expose retry_pending field")


# ---------------------------------------------------------------------------
# C3 — record_order_rejection / record_order_success in _route_live
# ---------------------------------------------------------------------------

class TestC3OrderRejectionSuccessTracking(unittest.TestCase):
    """C3: _route_live must call record_order_rejection on exchange rejection
    and record_order_success on accepted/filled results."""

    def test_route_live_calls_record_order_rejection(self):
        src = inspect.getsource(
            __import__(
                "merid.event_venues.kalshi.order_router",
                fromlist=["_route_live"],
            )._route_live
        )
        self.assertIn("record_order_rejection", src,
                       "C3: _route_live must call record_order_rejection on exchange rejection")

    def test_route_live_calls_record_order_success(self):
        src = inspect.getsource(
            __import__(
                "merid.event_venues.kalshi.order_router",
                fromlist=["_route_live"],
            )._route_live
        )
        self.assertIn("record_order_success", src,
                       "C3: _route_live must call record_order_success on filled/accepted")

    def test_record_order_rejection_increments_counter(self):
        """Calling record_order_rejection 5 times should trigger kill."""
        from merid.risk.kill_switches import RiskController
        rc = RiskController()
        for _ in range(5):
            rc.record_order_rejection()
        self.assertTrue(rc._global_kill,
                        "C3: 5 consecutive rejections should trigger kill switch")

    def test_record_order_success_resets_counter(self):
        """Calling record_order_success should reset rejection counter."""
        from merid.risk.kill_switches import RiskController
        rc = RiskController()
        rc.record_order_rejection()
        rc.record_order_rejection()
        self.assertEqual(rc._consecutive_rejections, 2)
        rc.record_order_success()
        self.assertEqual(rc._consecutive_rejections, 0)


# ---------------------------------------------------------------------------
# C4 — PositionSizer returns 0 when hourly cap exhausted
# ---------------------------------------------------------------------------

class TestC4PositionSizerExhaustedCap(unittest.TestCase):
    """C4: PositionSizer.compute() must return 0 when the per-underlying
    hourly exposure cap is fully consumed."""

    def test_compute_returns_zero_at_exhausted_cap(self):
        from merid.event_venues.kalshi.position_sizer import PositionSizer, SizerConfig
        cfg = SizerConfig(
            max_contracts_per_underlying_per_hour=10,
            min_contracts=1,
            max_contracts=50,
        )
        sizer = PositionSizer(cfg)
        contracts = sizer.compute(
            agent_name="test",
            edge_pct=5.0,
            price_cents=50,
            bankroll_cents=500_000,
            current_exposure_contracts=10,  # at cap
        )
        self.assertEqual(contracts, 0,
                         "C4: must return 0 when hourly cap is exhausted")

    def test_compute_returns_zero_beyond_cap(self):
        from merid.event_venues.kalshi.position_sizer import PositionSizer, SizerConfig
        cfg = SizerConfig(
            max_contracts_per_underlying_per_hour=10,
            min_contracts=1,
            max_contracts=50,
        )
        sizer = PositionSizer(cfg)
        contracts = sizer.compute(
            agent_name="test",
            edge_pct=5.0,
            price_cents=50,
            bankroll_cents=500_000,
            current_exposure_contracts=15,  # beyond cap
        )
        self.assertEqual(contracts, 0,
                         "C4: must return 0 when exposure exceeds hourly cap")

    def test_compute_returns_nonzero_under_cap(self):
        from merid.event_venues.kalshi.position_sizer import PositionSizer, SizerConfig
        cfg = SizerConfig(
            max_contracts_per_underlying_per_hour=50,
            min_contracts=1,
            max_contracts=50,
        )
        sizer = PositionSizer(cfg)
        contracts = sizer.compute(
            agent_name="test",
            edge_pct=5.0,
            price_cents=50,
            bankroll_cents=500_000,
            current_exposure_contracts=0,
        )
        self.assertGreater(contracts, 0,
                           "C4: should return >0 when under cap with positive edge")

    def test_size_factor_scaling_still_enforces_min_one(self):
        """When size_factor < 1 but cap has room, should still get >= 1."""
        from merid.event_venues.kalshi.position_sizer import PositionSizer, SizerConfig
        cfg = SizerConfig(
            max_contracts_per_underlying_per_hour=50,
            min_contracts=1,
            max_contracts=50,
        )
        sizer = PositionSizer(cfg)
        contracts = sizer.compute(
            agent_name="test",
            edge_pct=5.0,
            price_cents=50,
            bankroll_cents=500_000,
            current_exposure_contracts=0,
            size_factor=0.5,
        )
        self.assertGreaterEqual(contracts, 1,
                                "C4: size_factor scaling should still enforce min 1")

    def test_ordering_size_factor_before_cap(self):
        """Verify in source that size_factor max(1,...) comes BEFORE
        the remaining_capacity clamp."""
        from merid.event_venues.kalshi.position_sizer import PositionSizer
        src = inspect.getsource(PositionSizer.compute)
        sf_idx = src.index("size_factor")
        cap_idx = src.index("remaining_capacity")
        self.assertLess(sf_idx, cap_idx,
                        "C4: size_factor enforcement must precede exposure cap clamp")


# ---------------------------------------------------------------------------
# C5 — SwarmConsensusEngine action derived from proposal side
# ---------------------------------------------------------------------------

class TestC5ConsensusEngineActionDerivation(unittest.TestCase):
    """C5: SwarmConsensusEngine must derive kalshi_action from proposal side,
    not hardcode 'buy'."""

    def test_sell_proposal_produces_sell_action(self):
        """Source must map OrderSide.SELL → action='sell'."""
        from merid.swarm.consensus_engine import SwarmConsensusEngine
        src = inspect.getsource(SwarmConsensusEngine.run_consensus)
        # The fixed code should have both buy and sell derivations
        self.assertIn('kalshi_action = "buy" if prop.side == OrderSide.BUY else "sell"', src,
                       "C5: kalshi_action must be derived from prop.side")

    def test_no_hardcoded_buy_only(self):
        """Source must NOT have the old hardcoded 'buy' line."""
        from merid.swarm.consensus_engine import SwarmConsensusEngine
        src = inspect.getsource(SwarmConsensusEngine.run_consensus)
        # Old code was: kalshi_action = "buy" # We assume agents are always taking positions
        self.assertNotIn("We assume agents are always taking positions", src,
                         "C5: old hardcoded buy comment should be removed")

    def test_side_derivation_for_buy(self):
        """BUY proposal should yield side=yes, action=buy."""
        from merid.swarm.consensus_engine import SwarmConsensusEngine
        src = inspect.getsource(SwarmConsensusEngine.run_consensus)
        self.assertIn('kalshi_side = "yes" if prop.side == OrderSide.BUY else "no"', src)


# ---------------------------------------------------------------------------
# C6 — Fail-closed position cache lookup in live mode
# ---------------------------------------------------------------------------

class TestC6FailClosedPositionLookup(unittest.TestCase):
    """C6: If position cache raises in _route_live, reject with
    reason=position_cache_unavailable."""

    def test_route_live_rejects_on_position_cache_error(self):
        """Source of _route_live must return rejected on position cache exception."""
        src = inspect.getsource(
            __import__(
                "merid.event_venues.kalshi.order_router",
                fromlist=["_route_live"],
            )._route_live
        )
        self.assertIn("position_cache_unavailable", src,
                       "C6: must reject with position_cache_unavailable on cache error")

    def test_no_bare_pass_in_position_cache_except(self):
        """The old fail-open 'pass' on position cache exception must be gone."""
        src = inspect.getsource(
            __import__(
                "merid.event_venues.kalshi.order_router",
                fromlist=["_route_live"],
            )._route_live
        )
        # The old code was: except Exception:\n            pass  # best-effort
        self.assertNotIn("best-effort", src,
                         "C6: old fail-open pass comment must be removed")


# ---------------------------------------------------------------------------
# L1 — reset() clears _consecutive_rejections
# ---------------------------------------------------------------------------

class TestL1ResetClearsRejections(unittest.TestCase):
    """L1: RiskController.reset() must zero _consecutive_rejections."""

    def test_reset_clears_consecutive_rejections(self):
        from merid.risk.kill_switches import RiskController
        rc = RiskController()
        # Simulate 4 rejections (below threshold of 5)
        for _ in range(4):
            rc.record_order_rejection()
        self.assertEqual(rc._consecutive_rejections, 4)
        # Trigger kill manually to test reset
        rc.emergency_stop("test")
        rc.reset("operator")
        self.assertEqual(rc._consecutive_rejections, 0,
                         "L1: reset() must clear _consecutive_rejections")

    def test_reset_prevents_immediate_retrigger(self):
        """After reset, 1 more rejection should NOT retrigger kill."""
        from merid.risk.kill_switches import RiskController
        rc = RiskController()
        # 5 rejections triggers kill
        for _ in range(5):
            rc.record_order_rejection()
        self.assertTrue(rc._global_kill)
        # Reset
        rc.reset("operator")
        self.assertFalse(rc._global_kill)
        # 1 more rejection should NOT trigger (counter was reset)
        rc.record_order_rejection()
        self.assertFalse(rc._global_kill,
                         "L1: single rejection after reset must not trigger kill")
        self.assertEqual(rc._consecutive_rejections, 1)


# ---------------------------------------------------------------------------
# Compile checks — all modified files must parse cleanly
# ---------------------------------------------------------------------------

class TestCompileChecks(unittest.TestCase):
    """All modified files must compile without errors."""

    def _check_compiles(self, module_path: str):
        import importlib
        mod = importlib.import_module(module_path)
        self.assertIsNotNone(mod)

    def test_order_router_compiles(self):
        self._check_compiles("merid.event_venues.kalshi.order_router")

    def test_position_sizer_compiles(self):
        self._check_compiles("merid.event_venues.kalshi.position_sizer")

    def test_ws_bridge_compiles(self):
        self._check_compiles("merid.event_venues.kalshi.ws_bridge")

    def test_consensus_engine_compiles(self):
        self._check_compiles("merid.swarm.consensus_engine")

    def test_kill_switches_compiles(self):
        self._check_compiles("merid.risk.kill_switches")


# ---------------------------------------------------------------------------
# RiskController integration: record_pnl triggers daily loss kill
# ---------------------------------------------------------------------------

class TestRiskControllerPnLTracking(unittest.TestCase):
    """Verify that record_pnl actually fires the daily loss kill switch."""

    def test_record_pnl_triggers_daily_loss_kill(self):
        from merid.risk.kill_switches import RiskController
        rc = RiskController(daily_loss_limit=100.0)
        # Record a series of losses
        rc.record_pnl(-50.0)
        self.assertTrue(rc.can_trade(), "Should still be able to trade at -50")
        rc.record_pnl(-60.0)  # Total: -110, exceeds 100 limit
        self.assertFalse(rc.can_trade(),
                         "C2 regression: daily loss kill must fire at -110 > 100")

    def test_record_pnl_accumulates(self):
        from merid.risk.kill_switches import RiskController
        rc = RiskController(daily_loss_limit=500.0)
        rc.record_pnl(-10.0)
        rc.record_pnl(-20.0)
        rc.record_pnl(5.0)  # small win
        self.assertEqual(rc._daily_pnl, -25.0)

    def test_update_position_value_triggers_position_limit_kill(self):
        from merid.risk.kill_switches import RiskController
        rc = RiskController(max_position_value=1000.0)
        result = rc.update_position_value(500.0)
        self.assertTrue(result, "Should be fine at 500")
        result = rc.update_position_value(1500.0)
        self.assertFalse(result, "Should trigger position limit kill at 1500 > 1000")
        self.assertFalse(rc.can_trade())


if __name__ == "__main__":
    unittest.main()
