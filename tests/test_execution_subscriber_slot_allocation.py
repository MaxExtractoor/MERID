"""Tests for execution_subscriber slot allocation enforcement.

CRITICAL FIX (2026-07-12): Slot allocation removed from execution_subscriber.
Slot allocation now happens exclusively in order_router.route_order_async to prevent
double allocation bugs. execution_subscriber now routes to kalshi_tools which routes
to order_router where slot allocation occurs.
"""

import pytest


class TestExecutionSubscriberSlotAllocation:
    """Test that execution_subscriber does NOT have slot allocation (removed in 2026-07-12 fix)."""
    
    def test_no_direct_slot_allocation(self):
        """Test that execution_subscriber does NOT call slot_allocator directly."""
        with open("merid/swarm/execution_subscriber.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # execution_subscriber should NOT have slot allocation calls (check for actual function calls)
        assert "slot_allocator.request_allocation(" not in source, \
            "execution_subscriber should not call slot_allocator.request_allocation directly"
        
        # Verify it calls _kalshi_place_order
        assert "_kalshi_place_order" in source, \
            "execution_subscriber should call _kalshi_place_order"
        
        # Verify it does NOT call release_slot
        assert "slot_allocator.release_slot(" not in source, \
            "execution_subscriber should not call slot_allocator.release_slot directly"
    
    def test_routes_to_kalshi_tools(self):
        """Test that execution_subscriber routes to kalshi_tools for execution."""
        with open("merid/swarm/execution_subscriber.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # Verify it calls _kalshi_place_order
        assert "_kalshi_place_order" in source, \
            "execution_subscriber should call _kalshi_place_order"
        
        # Verify kalshi_tools import
        assert "from merid.prediction.kalshi_tools import _kalshi_place_order" in source, \
            "execution_subscriber should import _kalshi_place_order"
    
    def test_fallback_path_exists(self):
        """Test that fallback path exists for direct placement."""
        with open("merid/swarm/execution_subscriber.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # Verify fallback path exists
        assert "fallback" in source.lower() or "direct placement" in source.lower(), \
            "Execution subscriber should have fallback path"
        
        # Verify fallback also routes to kalshi_tools
        assert "_kalshi_place_order" in source, \
            "Fallback path should also call _kalshi_place_order"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
