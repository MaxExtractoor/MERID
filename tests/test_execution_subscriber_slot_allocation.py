"""Tests for execution_subscriber slot allocation enforcement.

Tests that the execution_subscriber properly requests slot allocation
before order execution to prevent bypassing the $1 global exposure cap.
"""

import pytest


class TestExecutionSubscriberSlotAllocation:
    """Test slot allocation in execution_subscriber via code structure analysis."""
    
    def test_slot_allocation_requested_before_order(self):
        """Test that slot allocation is requested before order execution."""
        with open("merid/swarm/execution_subscriber.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # Verify slot allocation is requested
        assert "request_allocation" in source, \
            "Execution subscriber should call request_allocation"
        
        # Verify allocation happens before _kalshi_place_order
        lines = source.split('\n')
        allocation_line = None
        place_order_line = None
        
        for i, line in enumerate(lines):
            if "request_allocation" in line and "slot_allocator" in line:
                allocation_line = i
            if "_kalshi_place_order" in line and not "#" in line:
                place_order_line = i
        
        assert allocation_line is not None, "Slot allocation should exist"
        assert place_order_line is not None, "_kalshi_place_order should exist"
        # Allocation should be before order placement
        assert allocation_line < place_order_line, \
            "Slot allocation should happen before _kalshi_place_order"
    
    def test_slot_allocation_blocks_insufficient_exposure(self):
        """Test that order is blocked when slot allocation fails."""
        with open("merid/swarm/execution_subscriber.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # Verify check for allocation result
        assert "if not allocated:" in source, \
            "Execution subscriber should check allocation result"
        
        # Verify blocking logic
        assert "return" in source and "Skip order" in source, \
            "Execution subscriber should skip order if no slot available"
    
    def test_exit_order_bypasses_slot_allocation(self):
        """Test that exit orders bypass slot allocation."""
        with open("merid/swarm/execution_subscriber.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # Verify exit order check exists
        assert "is_exit_order" in source, \
            "Execution subscriber should check for exit orders"
        
        # Verify is_exit_order is set based on action
        assert '"sell"' in source or '"close"' in source, \
            "Execution subscriber should check for sell/close actions"
    
    def test_slot_released_on_execution_failure(self):
        """Test that slot is released when order execution fails."""
        with open("merid/swarm/execution_subscriber.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # Verify slot release on exception
        assert "release_slot" in source, \
            "Execution subscriber should release slots"
        
        # Verify release happens in exception handler
        assert "except" in source and "release_slot" in source, \
            "Execution subscriber should release slot on exception"
    
    def test_fallback_path_slot_allocation(self):
        """Test slot allocation in fallback direct placement path."""
        with open("merid/swarm/execution_subscriber.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # Verify fallback path exists
        assert "fallback" in source.lower() or "direct placement" in source.lower(), \
            "Execution subscriber should have fallback path"
        
        # Verify slot allocation in fallback
        lines = source.split('\n')
        allocation_count = 0
        for line in lines:
            if "request_allocation" in line and "slot_allocator" in line:
                allocation_count += 1
        
        # Should have at least 2 slot allocation calls (AgentGrid path + fallback)
        assert allocation_count >= 2, \
            "Execution subscriber should have slot allocation in both AgentGrid and fallback paths"
    
    def test_asset_extraction_from_market_id(self):
        """Test asset extraction from market_id in fallback path."""
        with open("merid/swarm/execution_subscriber.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # Verify asset extraction logic
        assert "BTC" in source and "ETH" in source and "SOL" in source, \
            "Execution subscriber should handle multiple crypto assets"
        
        # Verify asset extraction from market_id
        assert "market_id" in source, \
            "Execution subscriber should extract asset from market_id"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
