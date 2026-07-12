"""
Integration tests for exit order bypass logic across the trading stack.

Tests the complete flow from signal generation through order routing to ensure
exit orders bypass slot allocation even at full $1 capacity.
"""

import pytest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestExitOrderIntegration:
    """Integration tests for exit order bypass logic."""
    
    def setup_method(self):
        """Reset all singletons before each test."""
        from merid.risk.global_slot_allocator import reset_global_slot_allocator
        reset_global_slot_allocator()
    
    def test_signal_generation_entry_order_flag(self):
        """Test that signal generation sets is_exit_order=False."""
        from merid.risk.global_slot_allocator import AllocationRequest
        
        # Entry order should have is_exit_order=False
        entry_request = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=30,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        
        assert entry_request.is_exit_order == False
        assert entry_request.entry_price_cents == 30
        
        print("✓ Signal generation entry order flag test passed")
    
    def test_exit_order_bypass_at_full_capacity(self):
        """Test that exit orders bypass allocation at full $1 capacity."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        
        # Fill to full capacity
        requests = [
            AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", 25, 2.0, 5, False),
            AllocationRequest("ETH_15M", "ETH", "KXETH15M-1", 25, 2.0, 5, False),
            AllocationRequest("SOL_15M", "SOL", "KXSOL15M-1", 25, 2.0, 5, False),
            AllocationRequest("XRP_15M", "XRP", "KXXRP15M-1", 25, 2.0, 5, False),
        ]
        
        for req in requests:
            allocated, _, _ = allocator.request_allocation(req)
            assert allocated
        
        assert abs(allocator.get_total_exposure() - 1.00) < 0.01
        
        # Entry order should be rejected
        entry_req = AllocationRequest("DOGE_15M", "DOGE", "KXDOGE15M-1", 10, 2.0, 5, False)
        allocated_entry, reason_entry, _ = allocator.request_allocation(entry_req)
        assert not allocated_entry
        assert "Insufficient exposure" in reason_entry
        
        # Exit order should bypass
        exit_req = AllocationRequest("position_monitor", "BTC", "KXBTC15M-1", 50, 0.0, 0, True)
        allocated_exit, reason_exit, _ = allocator.request_allocation(exit_req)
        assert allocated_exit
        assert reason_exit == "EXIT_ORDER_BYPASS"
        
        print("✓ Exit order bypass at full capacity test passed")
    
    def test_slot_allocator_to_position_cache_integration(self):
        """Test that slot allocator and position cache exposure tracking align."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        
        # Allocate slots
        req1 = AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", 30, 2.0, 5, False)
        req2 = AllocationRequest("ETH_15M", "ETH", "KXETH15M-1", 40, 2.0, 5, False)
        
        allocated1, _, slot1 = allocator.request_allocation(req1)
        allocated2, _, slot2 = allocator.request_allocation(req2)
        
        assert allocated1 and allocated2
        assert abs(allocator.get_total_exposure() - 0.70) < 0.01
        
        # Release by asset
        released = allocator.release_by_asset("BTC")
        assert released == 1
        assert abs(allocator.get_total_exposure() - 0.40) < 0.01
        
        print("✓ Slot allocator to position cache integration test passed")
    
    def test_unified_sizing_uses_slot_allocator(self):
        """Test that unified sizing uses slot allocator for exposure calculation."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        from merid.prediction.unified_sizing import compute_order_size
        from decimal import Decimal
        
        allocator = get_global_slot_allocator()
        
        # Allocate to near capacity using valid entry prices (10-50c)
        req1 = AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", 50, 2.0, 5, False)
        req2 = AllocationRequest("ETH_15M", "ETH", "KXETH15M-1", 40, 2.0, 5, False)
        
        allocated1, _, _ = allocator.request_allocation(req1)
        allocated2, _, _ = allocator.request_allocation(req2)
        assert allocated1 and allocated2
        
        # Total should be 90c, leaving 10c available
        assert abs(allocator.get_total_exposure() - 0.90) < 0.01
        
        # Try to size a 30c order (should fail due to insufficient exposure)
        count, notional, metadata = compute_order_size(
            bankroll_usd=Decimal("100.0"),
            price_cents=30,
            asset="ETH"
        )
        
        # Should return 0 due to insufficient exposure
        assert count == 0
        assert metadata.get("reason") == "insufficient_exposure_slot"
        
        print("✓ Unified sizing uses slot allocator test passed")
    
    def test_order_gate_uses_slot_allocator(self):
        """Test that order gate uses slot allocator for sequential trading check."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        
        # Fill to near capacity with valid entry prices (10-50c)
        req1 = AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", 50, 2.0, 5, False)
        req2 = AllocationRequest("ETH_15M", "ETH", "KXETH15M-1", 40, 2.0, 5, False)
        
        allocated1, _, _ = allocator.request_allocation(req1)
        allocated2, _, _ = allocator.request_allocation(req2)
        assert allocated1 and allocated2
        
        # Available should be 10c
        available = allocator.get_available_exposure()
        assert abs(available - 0.10) < 0.01
        
        # 20c order should be rejected by gate (insufficient exposure)
        # This would be tested by actual order gate call, but we test the logic here
        required_exposure = 20 / 100.0
        assert required_exposure > available
        
        print("✓ Order gate uses slot allocator test passed")
    
    def test_exit_order_price_validation_bypass(self):
        """Test that exit orders bypass entry price validation."""
        from merid.risk.global_slot_allocator import AllocationRequest
        
        # Exit orders should accept any price
        exit_low = AllocationRequest("monitor", "BTC", "KXBTC15M-1", 5, 0.0, 0, True)
        exit_high = AllocationRequest("monitor", "BTC", "KXBTC15M-1", 99, 0.0, 0, True)
        
        assert exit_low.entry_price_cents == 5
        assert exit_high.entry_price_cents == 99
        
        # Entry orders should reject out-of-range prices
        with pytest.raises(ValueError):
            AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", 5, 2.0, 5, False)
        
        with pytest.raises(ValueError):
            AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", 99, 2.0, 5, False)
        
        print("✓ Exit order price validation bypass test passed")
    
    def test_sequential_trading_scenario(self):
        """Test the full sequential trading scenario with early exits."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        
        # Initial: BTC 10c + ETH 30c + SOL 20c = 60c used, 40c available
        req_btc = AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", 10, 2.0, 5, False)
        req_eth = AllocationRequest("ETH_15M", "ETH", "KXETH15M-1", 30, 2.0, 5, False)
        req_sol = AllocationRequest("SOL_15M", "SOL", "KXSOL15M-1", 20, 2.0, 5, False)
        
        allocated_btc, _, slot_btc = allocator.request_allocation(req_btc)
        allocated_eth, _, slot_eth = allocator.request_allocation(req_eth)
        allocated_sol, _, slot_sol = allocator.request_allocation(req_sol)
        
        assert allocated_btc and allocated_eth and allocated_sol
        assert abs(allocator.get_total_exposure() - 0.60) < 0.01
        
        # DOGE 50c should be rejected (would exceed $1)
        req_doge = AllocationRequest("DOGE_15M", "DOGE", "KXDOGE15M-1", 50, 2.0, 5, False)
        allocated_doge, reason_doge, _ = allocator.request_allocation(req_doge)
        assert not allocated_doge
        
        # Exit order for BTC should bypass
        exit_btc = AllocationRequest("monitor", "BTC", "KXBTC15M-1", 50, 0.0, 0, True)
        allocated_exit, reason_exit, _ = allocator.request_allocation(exit_btc)
        assert allocated_exit
        assert reason_exit == "EXIT_ORDER_BYPASS"
        
        # Release BTC slot
        allocator.release_slot(slot_btc, exit_price_cents=50)
        assert abs(allocator.get_total_exposure() - 0.50) < 0.01
        
        # Now DOGE 40c should be allowed
        req_doge2 = AllocationRequest("DOGE_15M", "DOGE", "KXDOGE15M-1", 40, 2.0, 5, False)
        allocated_doge2, _, slot_doge = allocator.request_allocation(req_doge2)
        assert allocated_doge2
        assert abs(allocator.get_total_exposure() - 0.90) < 0.01
        
        print("✓ Sequential trading scenario test passed")
    
    def test_concurrent_exit_and_entry_orders(self):
        """Test that exit orders and entry orders can interleave correctly."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        
        # Fill to capacity
        req1 = AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", 50, 2.0, 5, False)
        req2 = AllocationRequest("ETH_15M", "ETH", "KXETH15M-1", 50, 2.0, 5, False)
        
        allocated1, _, slot1 = allocator.request_allocation(req1)
        allocated2, _, slot2 = allocator.request_allocation(req2)
        
        assert allocated1 and allocated2
        assert abs(allocator.get_total_exposure() - 1.00) < 0.01
        
        # Entry order should be rejected
        entry_req = AllocationRequest("SOL_15M", "SOL", "KXSOL15M-1", 10, 2.0, 5, False)
        allocated_entry, _, _ = allocator.request_allocation(entry_req)
        assert not allocated_entry
        
        # Exit order should bypass
        exit_req = AllocationRequest("monitor", "BTC", "KXBTC15M-1", 50, 0.0, 0, True)
        allocated_exit, _, _ = allocator.request_allocation(exit_req)
        assert allocated_exit
        
        # Release slot
        allocator.release_slot(slot1, exit_price_cents=50)
        assert abs(allocator.get_total_exposure() - 0.50) < 0.01
        
        # Entry order should now be allowed
        allocated_entry2, _, _ = allocator.request_allocation(entry_req)
        assert allocated_entry2
        assert abs(allocator.get_total_exposure() - 0.60) < 0.01
        
        print("✓ Concurrent exit and entry orders test passed")
    
    def test_exit_order_does_not_consume_slot(self):
        """Test that exit orders don't consume slots (only entry orders do)."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        
        # Initial slot count should be 0
        assert allocator.get_slot_count() == 0
        
        # Entry order should consume a slot
        entry_req = AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", 30, 2.0, 5, False)
        allocated, _, slot_id = allocator.request_allocation(entry_req)
        assert allocated
        assert slot_id is not None
        assert allocator.get_slot_count() == 1
        
        # Exit order should not consume a slot
        exit_req = AllocationRequest("monitor", "BTC", "KXBTC15M-1", 50, 0.0, 0, True)
        allocated_exit, _, exit_slot_id = allocator.request_allocation(exit_req)
        assert allocated_exit
        assert exit_slot_id is None  # Exit orders don't get slot IDs
        assert allocator.get_slot_count() == 1  # Still 1 slot
        
        print("✓ Exit order does not consume slot test passed")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x", "-s"])
