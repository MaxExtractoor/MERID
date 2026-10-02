"""Tests for execution path - candidate collection → grid-level execution.

The canonical path is two-stage:

1. ``LeanAgent15m._collect_order_candidate_impl`` builds and returns an order
   candidate dict — it does NOT submit orders.  Execution is delegated to the
   grid level (``TradingAgent._execute_candidate``) so all agents share one
   allocator/router path.
2. ``TradingAgent._execute_candidate`` converts the candidate to an
   ``OrderIntent`` and calls ``route_order_async``, which routes through
   ``_route_order_async_impl`` → ``_run_pre_trade_gate`` →
   ``PreTradeGate.check``.  Guardrails are enforced before submission.
3. Fail-safe: any router rejection/recovery/unfilled outcome returns ``False``
   so the candidate is treated as rejected rather than assumed submitted.
"""

import pytest


class TestExecutionPathFix:
    """Test the candidate → execution handoff contract."""

    def test_execution_invocation_code_exists(self):
        """Verify the candidate/execution handoff is wired through the canonical path."""
        import inspect

        # Stage 1: signal collection returns the candidate for grid-level
        # execution — it must not submit orders itself.
        from merid.prediction.agent_grid_15m import LeanAgent15m

        collect_src = inspect.getsource(LeanAgent15m._collect_order_candidate_impl)
        assert "Return candidate without execution" in collect_src, (
            "collect_order_candidate should return the candidate for "
            "grid-level execution"
        )

        # Stage 2: grid-level executor converts the candidate to an OrderIntent
        # and routes it through route_order_async.
        from merid.loop_15m import Kalshi15mLoop

        exec_src = inspect.getsource(Kalshi15mLoop._execute_candidate)
        assert "route_order_async" in exec_src, (
            "_execute_candidate should route via route_order_async"
        )

        # Fail-safe: router rejection must reject the candidate (return False),
        # never assume the order landed.
        assert '"rejected"' in exec_src, (
            "_execute_candidate should handle router rejections"
        )
        assert "requires_recovery" in exec_src, (
            "_execute_candidate should handle recovery-required outcomes"
        )
        assert "ROUTER-REJECTED" in exec_src, (
            "_execute_candidate should log rejected signals"
        )

        # Stage 3: route_order_async routes through the pre-trade gate before
        # submission.
        from merid.event_venues.kalshi import order_router

        gate_src = inspect.getsource(order_router._route_order_async_impl)
        assert "_run_pre_trade_gate" in gate_src, (
            "route_order_async should enforce the pre-trade gate"
        )
        ptg_src = inspect.getsource(order_router._run_pre_trade_gate)
        assert "get_pre_trade_gate" in ptg_src and ".check(" in ptg_src, (
            "_run_pre_trade_gate should invoke PreTradeGate.check"
        )

    def test_direct_execution_import(self):
        """Verify that _kalshi_place_order can be imported from kalshi_tools."""
        from merid.prediction.kalshi_tools import _kalshi_place_order
        
        assert _kalshi_place_order is not None, "_kalshi_place_order should be importable"
        assert callable(_kalshi_place_order), "_kalshi_place_order should be callable"

    def test_route_order_async_import(self):
        """Verify that route_order_async can be imported from order_router."""
        from merid.event_venues.kalshi.order_router import route_order_async
        
        assert route_order_async is not None, "route_order_async should be importable"
        assert callable(route_order_async), "route_order_async should be callable"

    def test_pre_trade_gate_import(self):
        """Verify that PreTradeGate can be imported from order_gate."""
        from merid.event_venues.kalshi.order_gate import PreTradeGate
        
        assert PreTradeGate is not None, "PreTradeGate should be importable"
        assert hasattr(PreTradeGate, 'check'), "PreTradeGate should have a check method"



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
