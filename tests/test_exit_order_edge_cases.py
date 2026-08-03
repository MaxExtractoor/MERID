"""
Edge case tests for exit order bypass logic.

Tests corner cases, error conditions, and boundary scenarios for the
exit order bypass feature to ensure robustness.
"""

import pytest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestExitOrderEdgeCases:
    """Edge case tests for exit order bypass logic."""
    
    def setup_method(self):
        """Reset all singletons before each test."""
        from merid.risk.global_slot_allocator import reset_global_slot_allocator
        reset_global_slot_allocator()
    
    def test_exit_order_with_zero_price(self):
        """Test that exit orders handle zero price gracefully."""
        from merid.risk.global_slot_allocator import AllocationRequest
        
        # Exit order with zero price should be allowed
        exit_req = AllocationRequest("monitor", "BTC", "KXBTC15M-1", 0, 0.0, 0, is_exit_order=True)
        assert exit_req.entry_price_cents == 0
        assert exit_req.is_exit_order == True
        
        print("✓ Exit order with zero price test passed")
    
    def test_exit_order_with_negative_price(self):
        """Test that exit orders handle negative price gracefully."""
        from merid.risk.global_slot_allocator import AllocationRequest
        
        # Exit order with negative price should be allowed (bypasses validation)
        exit_req = AllocationRequest("monitor", "BTC", "KXBTC15M-1", -10, 0.0, 0, is_exit_order=True)
        assert exit_req.entry_price_cents == -10
        assert exit_req.is_exit_order == True
        
        print("✓ Exit order with negative price test passed")
    
    def test_exit_order_with_extreme_price(self):
        """Test that exit orders handle extreme prices gracefully."""
        from merid.risk.global_slot_allocator import AllocationRequest
        
        # Exit order with extreme price should be allowed
        exit_req = AllocationRequest("monitor", "BTC", "KXBTC15M-1", 9999, 0.0, 0, is_exit_order=True)
        assert exit_req.entry_price_cents == 9999
        assert exit_req.is_exit_order == True
        
        print("✓ Exit order with extreme price test passed")
    
    def test_entry_order_rejects_boundary_prices(self):
        """Test that entry orders reject prices at boundaries."""
        from merid.risk.global_slot_allocator import AllocationRequest
        
        # Entry order at 9c should be rejected (below minimum)
        with pytest.raises(ValueError, match="Entry price.*outside allowed range"):
            AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", 9, 2.0, 5, is_exit_order=False)
        
        # Entry order at 76c should be rejected (above 75c canonical maximum)
        with pytest.raises(ValueError, match="Entry price.*outside allowed range"):
            AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", 76, 2.0, 5, is_exit_order=False)
        
        print("✓ Entry order rejects boundary prices test passed")
    
    def test_exit_order_at_exact_capacity(self):
        """Test exit order behavior when exactly at $1 capacity."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        
        # Fill to exactly $1.00
        req1 = AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", 25, 2.0, 5, is_exit_order=False)
        req2 = AllocationRequest("ETH_15M", "ETH", "KXETH15M-1", 25, 2.0, 5, is_exit_order=False)
        req3 = AllocationRequest("SOL_15M", "SOL", "KXSOL15M-1", 25, 2.0, 5, is_exit_order=False)
        req4 = AllocationRequest("XRP_15M", "XRP", "KXXRP15M-1", 25, 2.0, 5, is_exit_order=False)
        
        allocated1, _, _ = allocator.request_allocation(req1)
        allocated2, _, _ = allocator.request_allocation(req2)
        allocated3, _, _ = allocator.request_allocation(req3)
        allocated4, _, _ = allocator.request_allocation(req4)
        
        assert allocated1 and allocated2 and allocated3 and allocated4
        assert abs(allocator.get_total_exposure() - 1.00) < 0.01
        assert abs(allocator.get_available_exposure() - 0.00) < 0.01
        
        # Exit order should still bypass
        exit_req = AllocationRequest("monitor", "BTC", "KXBTC15M-1", 50, 0.0, 0, is_exit_order=True)
        allocated_exit, reason_exit, _ = allocator.request_allocation(exit_req)
        assert allocated_exit
        assert reason_exit == "EXIT_ORDER_BYPASS"
        
        print("✓ Exit order at exact capacity test passed")
    
    def test_multiple_exit_orders_same_asset(self):
        """Test multiple exit orders for the same asset."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        
        # Allocate a slot
        req = AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", 30, 2.0, 5, is_exit_order=False)
        allocated, _, slot_id = allocator.request_allocation(req)
        assert allocated
        
        # Multiple exit orders should all bypass
        exit_req1 = AllocationRequest("monitor", "BTC", "KXBTC15M-1", 50, 0.0, 0, is_exit_order=True)
        exit_req2 = AllocationRequest("monitor", "BTC", "KXBTC15M-1", 55, 0.0, 0, is_exit_order=True)
        exit_req3 = AllocationRequest("monitor", "BTC", "KXBTC15M-1", 60, 0.0, 0, is_exit_order=True)
        
        allocated1, reason1, _ = allocator.request_allocation(exit_req1)
        allocated2, reason2, _ = allocator.request_allocation(exit_req2)
        allocated3, reason3, _ = allocator.request_allocation(exit_req3)
        
        assert allocated1 and allocated2 and allocated3
        assert reason1 == reason2 == reason3 == "EXIT_ORDER_BYPASS"
        
        # Slot should still be allocated (exit orders don't consume slots)
        assert allocator.get_slot_count() == 1
        
        print("✓ Multiple exit orders same asset test passed")
    
    def test_exit_order_without_position(self):
        """Test exit order behavior when no position exists."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        
        # Exit order for asset with no position should still bypass allocation
        exit_req = AllocationRequest("monitor", "BTC", "KXBTC15M-1", 50, 0.0, 0, is_exit_order=True)
        allocated, reason, _ = allocator.request_allocation(exit_req)
        
        assert allocated
        assert reason == "EXIT_ORDER_BYPASS"
        
        # Should not consume a slot
        assert allocator.get_slot_count() == 0
        
        print("✓ Exit order without position test passed")
    
    def test_exit_order_with_negative_edge(self):
        """Test exit order with negative edge (should be allowed)."""
        from merid.risk.global_slot_allocator import AllocationRequest
        
        # Exit order with negative edge should be allowed
        exit_req = AllocationRequest("monitor", "BTC", "KXBTC15M-1", 50, -5.0, 0, is_exit_order=True)
        assert exit_req.edge_pct == -5.0
        assert exit_req.is_exit_order == True
        
        print("✓ Exit order with negative edge test passed")
    
    def test_exit_order_with_zero_spread(self):
        """Test exit order with zero spread (should be allowed)."""
        from merid.risk.global_slot_allocator import AllocationRequest
        
        # Exit order with zero spread should be allowed
        exit_req = AllocationRequest("monitor", "BTC", "KXBTC15M-1", 50, 0.0, 0, is_exit_order=True)
        assert exit_req.spread_cents == 0
        assert exit_req.is_exit_order == True
        
        print("✓ Exit order with zero spread test passed")
    
    def test_exit_order_with_large_spread(self):
        """Test exit order with large spread (should be allowed)."""
        from merid.risk.global_slot_allocator import AllocationRequest
        
        # Exit order with large spread should be allowed
        exit_req = AllocationRequest("monitor", "BTC", "KXBTC15M-1", 50, 0.0, 100, is_exit_order=True)
        assert exit_req.spread_cents == 100
        assert exit_req.is_exit_order == True
        
        print("✓ Exit order with large spread test passed")
    
    def test_release_slot_that_doesnt_exist(self):
        """Test releasing a slot that doesn't exist."""
        from merid.risk.global_slot_allocator import get_global_slot_allocator
        
        allocator = get_global_slot_allocator()
        
        # Try to release a non-existent slot
        released = allocator.release_slot("non_existent_slot_id")
        assert released == False
        
        print("✓ Release slot that doesn't exist test passed")
    
    def test_release_by_asset_with_no_slots(self):
        """Test releasing by asset when no slots exist."""
        from merid.risk.global_slot_allocator import get_global_slot_allocator
        
        allocator = get_global_slot_allocator()
        
        # Try to release slots for asset with no slots
        released = allocator.release_by_asset("BTC")
        assert released == 0
        
        print("✓ Release by asset with no slots test passed")
    
    def test_release_by_agent_with_no_slots(self):
        """Test releasing by agent when no slots exist."""
        from merid.risk.global_slot_allocator import get_global_slot_allocator
        
        allocator = get_global_slot_allocator()
        
        # Try to release slots for agent with no slots
        released = allocator.release_by_agent("BTC_15M")
        assert released == 0
        
        print("✓ Release by agent with no slots test passed")
    
    def test_concurrent_allocation_requests(self):
        """Test handling of concurrent allocation requests."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        import threading
        
        allocator = get_global_slot_allocator()
        results = []
        
        def allocate_request(price_cents):
            req = AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", price_cents, 2.0, 5, is_exit_order=False)
            allocated, _, _ = allocator.request_allocation(req)
            results.append(allocated)
        
        # Create multiple threads trying to allocate
        threads = []
        for i in range(5):
            t = threading.Thread(target=allocate_request, args=(20,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # Should have some allocations (thread-safe)
        assert len(results) == 5
        assert sum(results) > 0  # At least some should succeed
        
        print("✓ Concurrent allocation requests test passed")
    
    def test_exit_order_does_not_affect_exposure(self):
        """Test that exit orders don't affect exposure calculation."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        
        # Allocate some exposure
        req = AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", 50, 2.0, 5, is_exit_order=False)
        allocated, _, _ = allocator.request_allocation(req)
        assert allocated
        
        initial_exposure = allocator.get_total_exposure()
        
        # Process exit order
        exit_req = AllocationRequest("monitor", "BTC", "KXBTC15M-1", 50, 0.0, 0, is_exit_order=True)
        allocated_exit, _, _ = allocator.request_allocation(exit_req)
        assert allocated_exit
        
        # Exposure should not change
        assert allocator.get_total_exposure() == initial_exposure
        
        print("✓ Exit order does not affect exposure test passed")
    
    def test_exit_order_with_missing_agent_id(self):
        """Test exit order with empty agent_id."""
        from merid.risk.global_slot_allocator import AllocationRequest
        
        # Exit order with empty agent_id should be allowed
        exit_req = AllocationRequest("", "BTC", "KXBTC15M-1", 50, 0.0, 0, is_exit_order=True)
        assert exit_req.agent_id == ""
        assert exit_req.is_exit_order == True
        
        print("✓ Exit order with missing agent_id test passed")
    
    def test_exit_order_with_missing_asset(self):
        """Test exit order with empty asset."""
        from merid.risk.global_slot_allocator import AllocationRequest
        
        # Exit order with empty asset should be allowed
        exit_req = AllocationRequest("monitor", "", "KXBTC15M-1", 50, 0.0, 0, is_exit_order=True)
        assert exit_req.asset == ""
        assert exit_req.is_exit_order == True
        
        print("✓ Exit order with missing asset test passed")
    
    def test_exit_order_with_missing_ticker(self):
        """Test exit order with empty ticker."""
        from merid.risk.global_slot_allocator import AllocationRequest
        
        # Exit order with empty ticker should be allowed
        exit_req = AllocationRequest("monitor", "BTC", "", 50, 0.0, 0, is_exit_order=True)
        assert exit_req.ticker == ""
        assert exit_req.is_exit_order == True
        
        print("✓ Exit order with missing ticker test passed")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x", "-s"])
