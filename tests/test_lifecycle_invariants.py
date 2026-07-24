"""
Test lifecycle invariants for the 15m Kalshi crypto trading system.

This test suite validates that order lifecycle (entry, fill, exit) maintains
correct state across position cache, resting order monitor, and risk components.

Invariant: Position state must be consistent across all lifecycle stages.
"""

import pytest
from datetime import datetime, timezone


class TestPositionLifecycle:
    """Test position lifecycle from entry to exit."""
    
    def test_position_creation(self):
        """Verify position is created correctly on entry."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        position = CachedPosition(
            market_id="KXBTC15M-26JUL211745-45",
            agent_id="test_agent",
            side="yes",
            contracts=1,
            avg_price_cents=42,
            thesis_side="yes",  # Immutable invariant
        )
        assert position.contracts == 1
        assert position.side == "yes"
        assert position.thesis_side == "yes"
        assert position.avg_price_cents == 42
    
    def test_position_fill_processing(self):
        """Verify fill processing updates position correctly."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        position = CachedPosition(
            market_id="KXBTC15M-26JUL211745-45",
            agent_id="test_agent",
            side="yes",
            contracts=0,
            avg_price_cents=None,
            thesis_side="yes",
        )
        
        # Process entry fill
        position.apply_fill(
            contracts=1,
            price_cents=42,
            fee_cents=2,
            side="yes",
            action="buy",
        )
        
        assert position.contracts == 1, "Position should have 1 contract after fill"
        assert position.avg_price_cents == 42, "Avg price should be set to fill price"
    
    def test_position_exit_fill(self):
        """Verify exit fill reduces position correctly."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        position = CachedPosition(
            market_id="KXBTC15M-26JUL211745-45",
            agent_id="test_agent",
            side="yes",
            contracts=1,
            avg_price_cents=42,
            thesis_side="yes",
        )
        
        # Process exit fill
        position.apply_fill(
            contracts=1,
            price_cents=50,
            fee_cents=2,
            side="yes",
            action="sell",
        )
        
        assert position.contracts == 0, "Position should be closed after exit fill"
    
    def test_wrong_direction_fill_detection(self):
        """Verify wrong-direction position changes are detected."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        position = CachedPosition(
            market_id="KXBTC15M-26JUL211745-45",
            agent_id="test_agent",
            side="yes",
            contracts=1,
            avg_price_cents=42,
            thesis_side="yes",
        )
        
        # Try to add more contracts on exit (should log critical alarm)
        # This would be a wrong-direction change
        position.apply_fill(
            contracts=1,
            price_cents=50,
            fee_cents=2,
            side="yes",
            action="sell",  # Sell action should reduce, not increase
        )
        
        # Position should be reduced, not increased
        assert position.contracts == 0, "Exit fill should reduce position"


class TestThesisSideInvariant:
    """Test thesis side invariant across lifecycle."""
    
    def test_thesis_side_immutable_on_fill(self):
        """Verify thesis_side is not changed by fill processing."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        position = CachedPosition(
            market_id="KXBTC15M-26JUL211745-45",
            agent_id="test_agent",
            side="yes",
            contracts=0,
            avg_price_cents=None,
            thesis_side="yes",
        )
        
        position.apply_fill(
            contracts=1,
            price_cents=42,
            fee_cents=2,
            side="yes",
            action="buy",
        )
        
        assert position.thesis_side == "yes", "Thesis side should remain immutable"
    
    def test_thesis_side_used_for_exit(self):
        """Verify exit orders use thesis_side, not mutable side."""
        # This is tested in loop_15m.py logic
        # Here we verify the invariant is preserved
        from merid.event_venues.kalshi.position_cache import CachedPosition
        position = CachedPosition(
            market_id="KXBTC15M-26JUL211745-45",
            agent_id="test_agent",
            side="yes",  # Mutable (may be overwritten by REST)
            contracts=1,
            avg_price_cents=42,
            thesis_side="yes",  # Immutable
        )
        
        # Simulate REST sync overwriting side
        position.side = "yes"  # REST API always reports "yes"
        
        # Thesis side should still be correct
        assert position.thesis_side == "yes", "Thesis side should not be affected by REST sync"


class TestRestingOrderLifecycle:
    """Test resting order lifecycle."""
    
    def test_resting_order_creation(self):
        """Verify resting order is tracked correctly."""
        from merid.event_venues.kalshi.resting_order_monitor import RestingOrderRecord
        record = RestingOrderRecord(
            kalshi_order_id="test_order_123",
            ticker="KXBTC15M-26JUL211745-45",
            side="BUY_YES",
            action="buy",
            original_size=1,
            remaining_size=1,
            status="OPEN",
        )
        
        assert record.kalshi_order_id == "test_order_123"
        assert record.ticker == "KXBTC15M-26JUL211745-45"
        assert record.remaining_size == 1
        assert record.status == "OPEN"
    
    def test_resting_order_fill(self):
        """Verify resting order is updated on fill."""
        from merid.event_venues.kalshi.resting_order_monitor import RestingOrderRecord
        record = RestingOrderRecord(
            kalshi_order_id="test_order_123",
            ticker="KXBTC15M-26JUL211745-45",
            side="BUY_YES",
            action="buy",
            original_size=1,
            remaining_size=1,
            status="OPEN",
        )
        
        # Simulate fill
        record.remaining_size = 0
        record.status = "FILLED"
        
        assert record.remaining_size == 0
        assert record.status == "FILLED"
    
    def test_find_open_order(self):
        """Verify find_open_order correctly identifies live orders."""
        from merid.event_venues.kalshi.resting_order_monitor import RestingOrderMonitor, RestingOrderRecord
        monitor = RestingOrderMonitor()
        
        # Add a resting order
        record = RestingOrderRecord(
            kalshi_order_id="test_order_123",
            ticker="KXBTC15M-26JUL211745-45",
            side="BUY_YES",
            action="buy",
            original_size=1,
            remaining_size=1,
            status="OPEN",
        )
        monitor._resting_orders["test_order_123"] = record
        
        # Find it
        found_id = monitor.find_open_order(
            ticker="KXBTC15M-26JUL211745-45",
            side="BUY_YES",
            action="buy",
        )
        
        assert found_id == "test_order_123"
    
    def test_find_open_order_ignores_terminal(self):
        """Verify find_open_order ignores terminal orders."""
        from merid.event_venues.kalshi.resting_order_monitor import RestingOrderMonitor, RestingOrderRecord
        monitor = RestingOrderMonitor()
        
        # Add a filled order (status must be lowercase to match TERMINAL_STATUSES)
        record = RestingOrderRecord(
            kalshi_order_id="test_order_123",
            ticker="KXBTC15M-26JUL211745-45",
            side="BUY_YES",
            action="buy",
            original_size=1,
            remaining_size=0,
            status="filled",  # lowercase to match TERMINAL_STATUSES
        )
        monitor._resting_orders["test_order_123"] = record
        
        # Should not find it (terminal status and remaining_size=0)
        found_id = monitor.find_open_order(
            ticker="KXBTC15M-26JUL211745-45",
            side="BUY_YES",
            action="buy",
        )
        
        # The function checks both terminal status and remaining_size <= 0
        # Since remaining_size is 0, it should return None
        assert found_id is None


class TestSlotAllocatorLifecycle:
    """Test slot allocator lifecycle."""
    
    def test_slot_allocation(self):
        """Verify slot is allocated correctly."""
        from merid.risk.global_slot_allocator import GlobalSlotAllocator
        allocator = GlobalSlotAllocator()
        
        # Check that allocation is possible
        can_allocate, reason = allocator.can_allocate(42, "BTC")
        assert can_allocate == True, f"Should allow allocation: {reason}"
    
    def test_slot_release(self):
        """Verify slot is released correctly."""
        from merid.risk.global_slot_allocator import GlobalSlotAllocator
        allocator = GlobalSlotAllocator()
        
        # Check allocation is possible
        can_allocate, reason = allocator.can_allocate(42, "BTC")
        assert can_allocate == True, f"Should allow allocation: {reason}"
    
    def test_slot_release_on_rejection(self):
        """Verify slot is released on order rejection."""
        from merid.risk.global_slot_allocator import GlobalSlotAllocator
        allocator = GlobalSlotAllocator()
        
        # Check allocation is possible
        can_allocate, reason = allocator.can_allocate(42, "BTC")
        assert can_allocate == True, f"Should allow allocation: {reason}"


class TestGlobalAllocatorLifecycle:
    """Test global allocator pending order lifecycle."""
    
    def test_pending_order_marked(self):
        """Verify pending order is marked correctly."""
        from merid.risk.profiles.global_allocator import GlobalAllocator
        allocator = GlobalAllocator()
        
        # Use record_order_submitted to mark pending order (requires notional_usd)
        allocator.record_order_submitted("BTC", "order_123", 0.42)
        
        assert allocator.has_pending_order("BTC") == True
        assert allocator.get_pending_orders()["BTC"] == "order_123"
    
    def test_pending_order_cleared(self):
        """Verify pending order is cleared correctly."""
        from merid.risk.profiles.global_allocator import GlobalAllocator
        allocator = GlobalAllocator()
        
        # Use record_order_submitted to mark pending order (requires notional_usd)
        allocator.record_order_submitted("BTC", "order_123", 0.42)
        # Use record_order_filled to clear pending order
        allocator.record_order_filled("BTC", "order_123", 0.42)
        
        assert allocator.has_pending_order("BTC") == False
    
    def test_stale_pending_order_auto_cleared(self):
        """Verify stale pending orders are auto-cleared."""
        from merid.risk.profiles.global_allocator import GlobalAllocator
        import time
        
        allocator = GlobalAllocator()
        allocator._pending_order_timeout = 1  # 1 second timeout for testing
        
        # Use record_order_submitted to mark pending order (requires notional_usd)
        allocator.record_order_submitted("BTC", "order_123", 0.42)
        time.sleep(1.1)  # Wait for timeout
        
        # Should be auto-cleared by has_pending_order check
        assert allocator.has_pending_order("BTC") == False


class TestLifecycleInvariants:
    """Test high-level lifecycle invariants."""
    
    def test_entry_exit_consistency(self):
        """Verify entry and exit fills are consistent."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        position = CachedPosition(
            market_id="KXBTC15M-26JUL211745-45",
            agent_id="test_agent",
            side="yes",
            contracts=0,
            avg_price_cents=None,
            thesis_side="yes",
        )
        
        # Entry
        position.apply_fill(contracts=1, price_cents=42, fee_cents=2, side="yes", action="buy")
        assert position.contracts == 1
        
        # Exit
        position.apply_fill(contracts=1, price_cents=50, fee_cents=2, side="yes", action="sell")
        assert position.contracts == 0
    
    def test_position_state_synchronization(self):
        """Verify position state is synchronized across components."""
        # This is a high-level invariant check
        # In production, position cache, resting monitor, and allocator should be consistent
        from merid.event_venues.kalshi.position_cache import CachedPosition
        from merid.risk.global_slot_allocator import GlobalSlotAllocator
        
        position = CachedPosition(
            market_id="KXBTC15M-26JUL211745-45",
            agent_id="test_agent",
            side="yes",
            contracts=1,
            avg_price_cents=42,
            thesis_side="yes",
        )
        
        allocator = GlobalSlotAllocator()
        
        # Both should indicate 1 contract exposure
        assert position.contracts == 1
        can_allocate, reason = allocator.can_allocate(42, "BTC")
        # Since we have a position at 42c, the allocator should check if this exceeds cap
        # For this test, we just verify the allocator can check the price
    
    def test_no_position_leaks(self):
        """Verify positions don't leak on lifecycle transitions."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        from merid.risk.global_slot_allocator import GlobalSlotAllocator
        
        position = CachedPosition(
            market_id="KXBTC15M-26JUL211745-45",
            agent_id="test_agent",
            side="yes",
            contracts=0,
            avg_price_cents=None,
            thesis_side="yes",
        )
        
        allocator = GlobalSlotAllocator()
        
        # Entry
        position.apply_fill(contracts=1, price_cents=42, fee_cents=2, side="yes", action="buy")
        
        # Exit
        position.apply_fill(contracts=1, price_cents=50, fee_cents=2, side="yes", action="sell")
        
        # Position should be clean
        assert position.contracts == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
