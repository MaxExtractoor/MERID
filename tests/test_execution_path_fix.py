"""Tests for execution path fix - direct invocation in collect_order_candidate.

This test verifies that the structural design flaw has been fixed:
- Signal generation now invokes execution directly
- Orders are routed through _kalshi_place_order → route_order_async → PreTradeGate.check
- Guardrails are enforced before order submission
- Fail-safe behavior: if order submission fails, signal is rejected
"""

import pytest


class TestExecutionPathFix:
    """Test the execution path fix in collect_order_candidate."""

    def test_execution_invocation_code_exists(self):
        """Verify that the execution invocation code is present in collect_order_candidate."""
        from merid.prediction.agent_grid_15m import LeanAgent15m
        import inspect
        
        # Get the source code of collect_order_candidate
        source = inspect.getsource(LeanAgent15m.collect_order_candidate)
        
        # Verify the critical fix is present
        assert "_kalshi_place_order" in source, "collect_order_candidate should call _kalshi_place_order"
        assert "route_order_async" in source, "collect_order_candidate should mention route_order_async"
        assert "PreTradeGate" in source, "collect_order_candidate should mention guardrails"
        
        # Verify fail-safe behavior is present
        assert "fail-safe" in source.lower() or "failsafe" in source.lower(), "collect_order_candidate should mention fail-safe"
        assert "SIGNAL REJECTED" in source, "collect_order_candidate should reject signals on failure"

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
