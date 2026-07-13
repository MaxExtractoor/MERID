"""Test for _allocated_slot_id fix (2026-07-13).

Tests that order_router correctly uses intent._allocated_slot_id instead of
a local _allocated_slot_id variable to prevent NameError.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import inspect


class TestAllocatedSlotIdFix:
    """Test that order_router uses intent._allocated_slot_id correctly."""
    
    def test_order_router_uses_intent_allocated_slot_id(self):
        """Verify order_router.py uses intent._allocated_slot_id, not local variable."""
        from merid.event_venues.kalshi import order_router
        
        # Get the source code of order_router
        source = inspect.getsource(order_router)
        
        # Check that intent._allocated_slot_id is used in slot release logic
        assert "intent._allocated_slot_id" in source, \
            "order_router should use intent._allocated_slot_id attribute"
        
        # Check that the pattern of releasing slots uses intent._allocated_slot_id
        assert "slot_allocator.release_slot(intent._allocated_slot_id)" in source, \
            "order_router should release slots using intent._allocated_slot_id"
        
        # Ensure there are no standalone _allocated_slot_id references (without intent.)
        # This is a heuristic - we check for the problematic pattern
        lines = source.split('\n')
        problematic_lines = []
        for i, line in enumerate(lines):
            # Look for if _allocated_slot_id: or slot_allocator.release_slot(_allocated_slot_id)
            # that doesn't have intent. prefix
            if 'if _allocated_slot_id:' in line and 'intent._allocated_slot_id' not in line:
                problematic_lines.append((i+1, line))
            elif 'release_slot(_allocated_slot_id)' in line and 'intent._allocated_slot_id' not in line:
                problematic_lines.append((i+1, line))
        
        if problematic_lines:
            pytest.fail(
                f"Found {len(problematic_lines)} lines using _allocated_slot_id without intent. prefix:\n" +
                "\n".join(f"Line {ln}: {content}" for ln, content in problematic_lines)
            )
    
    def test_release_allocated_slot_function(self):
        """Test _release_allocated_slot function uses intent._allocated_slot_id."""
        from merid.event_venues.kalshi.order_router import _release_allocated_slot
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        # Create a mock intent with _allocated_slot_id
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
        )
        intent._allocated_slot_id = "test_slot_123"
        
        # Mock the slot allocator (imported inside _release_allocated_slot)
        with patch('merid.risk.global_slot_allocator.get_global_slot_allocator') as mock_get_allocator:
            mock_allocator = MagicMock()
            mock_get_allocator.return_value = mock_allocator
            
            # Call the function
            _release_allocated_slot(intent)
            
            # Verify it released the correct slot
            mock_allocator.release_slot.assert_called_once_with("test_slot_123")
    
    def test_release_allocated_slot_with_none(self):
        """Test _release_allocated_slot handles None slot_id gracefully."""
        from merid.event_venues.kalshi.order_router import _release_allocated_slot
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        # Create a mock intent without _allocated_slot_id
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
        )
        # Don't set _allocated_slot_id (defaults to None)
        
        # Mock the slot allocator (it's imported from merid.risk.global_slot_allocator)
        with patch('merid.risk.global_slot_allocator.get_global_slot_allocator') as mock_get_allocator:
            mock_allocator = MagicMock()
            mock_get_allocator.return_value = mock_allocator
            
            # Call the function - should not crash
            _release_allocated_slot(intent)
            
            # Verify it did NOT try to release (since slot_id is None)
            mock_allocator.release_slot.assert_not_called()
    
    def test_intent_has_allocated_slot_id_attribute(self):
        """Test OrderIntent can have _allocated_slot_id attribute."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
        )
        
        # Should be able to set and get _allocated_slot_id
        intent._allocated_slot_id = "test_slot"
        assert intent._allocated_slot_id == "test_slot"
        
        # Should default to None if not set
        intent2 = OrderIntent(
            ticker="KXETH15M-TEST",
            side="no",
            action="sell",
            price_cents=30,
            count=5,
        )
        assert getattr(intent2, '_allocated_slot_id', None) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
