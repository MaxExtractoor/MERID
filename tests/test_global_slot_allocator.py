"""
Test suite for Global Slot Allocator

Tests the $1 hard limit enforcement across all 5 assets with slot-based position management.
"""

import pytest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestGlobalSlotAllocator:
    """Test suite for GlobalSlotAllocator."""
    
    def setup_method(self):
        """Reset allocator before each test."""
        from merid.risk.global_slot_allocator import reset_global_slot_allocator
        reset_global_slot_allocator()
    
    def test_basic_import(self):
        """Test that the module can be imported."""
        from merid.risk.global_slot_allocator import GlobalSlotAllocator
        assert GlobalSlotAllocator is not None
        print("✓ Basic import test passed")
    
    def test_singleton_initialization(self):
        """Test that singleton pattern works correctly."""
        from merid.risk.global_slot_allocator import get_global_slot_allocator
        allocator1 = get_global_slot_allocator()
        allocator2 = get_global_slot_allocator()
        assert allocator1 is allocator2, "Singleton should return same instance"
        print("✓ Singleton initialization test passed")
    
    def test_max_exposure_limit(self):
        """Test that $1 exposure limit is enforced."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        
        # Should allow 50c entry
        request = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=50,
            edge_pct=2.0,
            spread_cents=5
        )
        allocated, reason, slot_id = allocator.request_allocation(request)
        assert allocated, f"50c entry should be allowed: {reason}"
        assert slot_id is not None
        
        # Check exposure
        total_exposure = allocator.get_total_exposure()
        assert total_exposure == 0.50, f"Expected 0.50 exposure, got {total_exposure}"
        
        print("✓ Max exposure limit test passed")
    
    def test_entry_price_range_validation(self):
        """Test that entry price must be between 10c and 50c."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        
        # Test that AllocationRequest validates entry price for entry orders
        # Should reject below 10c
        with pytest.raises(ValueError, match="Entry price.*outside allowed range"):
            AllocationRequest(
                agent_id="BTC_15M",
                asset="BTC",
                ticker="KXBTC15M-TEST",
                entry_price_cents=5,
                edge_pct=2.0,
                spread_cents=5,
                is_exit_order=False
            )
        
        # Should reject above 50c
        with pytest.raises(ValueError, match="Entry price.*outside allowed range"):
            AllocationRequest(
                agent_id="BTC_15M",
                asset="BTC",
                ticker="KXBTC15M-TEST",
                entry_price_cents=60,
                edge_pct=2.0,
                spread_cents=5,
                is_exit_order=False
            )
        
        # Should accept 10c (minimum)
        request_min = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=10,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        assert request_min.entry_price_cents == 10
        
        # Should accept 50c (maximum)
        request_max = AllocationRequest(
            agent_id="ETH_15M",
            asset="ETH",
            ticker="KXETH15M-TEST",
            entry_price_cents=50,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        assert request_max.entry_price_cents == 50
        
        print("✓ Entry price range validation test passed")
    
    def test_exit_order_bypasses_price_validation(self):
        """Test that exit orders bypass entry price validation."""
        from merid.risk.global_slot_allocator import AllocationRequest
        
        # Exit orders should accept any price (no validation)
        request_exit_low = AllocationRequest(
            agent_id="position_monitor",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=5,  # Below minimum
            edge_pct=0.0,
            spread_cents=0,
            is_exit_order=True
        )
        assert request_exit_low.entry_price_cents == 5
        
        request_exit_high = AllocationRequest(
            agent_id="position_monitor",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=99,  # Above maximum
            edge_pct=0.0,
            spread_cents=0,
            is_exit_order=True
        )
        assert request_exit_high.entry_price_cents == 99
        
        print("✓ Exit order bypasses price validation test passed")
    
    def test_exit_order_bypasses_slot_allocation(self):
        """Test that exit orders bypass slot allocation even at full capacity."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        
        # Fill up to $1 capacity
        request1 = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=30,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        allocated1, _, _ = allocator.request_allocation(request1)
        assert allocated1
        
        request2 = AllocationRequest(
            agent_id="ETH_15M",
            asset="ETH",
            ticker="KXETH15M-TEST",
            entry_price_cents=40,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        allocated2, _, _ = allocator.request_allocation(request2)
        assert allocated2
        
        request3 = AllocationRequest(
            agent_id="SOL_15M",
            asset="SOL",
            ticker="KXSOL15M-TEST",
            entry_price_cents=30,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        allocated3, _, _ = allocator.request_allocation(request3)
        assert allocated3
        
        # Total should be $1.00
        assert allocator.get_total_exposure() == 1.00
        assert allocator.get_available_exposure() == 0.00
        
        # Entry order should be rejected at full capacity
        request_reject = AllocationRequest(
            agent_id="XRP_15M",
            asset="XRP",
            ticker="KXXRP15M-TEST",
            entry_price_cents=10,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        allocated_reject, reason_reject, _ = allocator.request_allocation(request_reject)
        assert not allocated_reject
        assert "Insufficient exposure" in reason_reject
        
        # Exit order should bypass allocation even at full capacity
        request_exit = AllocationRequest(
            agent_id="position_monitor",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=50,
            edge_pct=0.0,
            spread_cents=0,
            is_exit_order=True
        )
        allocated_exit, reason_exit, slot_id_exit = allocator.request_allocation(request_exit)
        assert allocated_exit
        assert reason_exit == "EXIT_ORDER_BYPASS"
        assert slot_id_exit is None  # Exit orders don't get slot IDs
        
        # Exposure should still be $1.00 (exit orders don't consume slots)
        assert allocator.get_total_exposure() == 1.00
        
        print("✓ Exit order bypasses slot allocation test passed")
    
    def test_slot_release_on_closure(self):
        """Test that slots are released when positions close."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        
        # Allocate a slot
        request = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=35,
            edge_pct=2.0,
            spread_cents=5
        )
        allocated, _, slot_id = allocator.request_allocation(request)
        assert allocated
        assert allocator.get_total_exposure() == 0.35
        
        # Release the slot
        released = allocator.release_slot(slot_id, exit_price_cents=99)
        assert released
        assert allocator.get_total_exposure() == 0.0
        assert allocator.get_available_exposure() == 1.0
        
        print("✓ Slot release on closure test passed")
    
    def test_sequential_trading_with_exits(self):
        """Test the sequential trading scenario with early exits."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        
        # Scenario: BTC 35c + ETH 30c + SOL 20c = 85c used, 15c available
        request_btc = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=35,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        request_eth = AllocationRequest(
            agent_id="ETH_15M",
            asset="ETH",
            ticker="KXETH15M-TEST",
            entry_price_cents=30,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        request_sol = AllocationRequest(
            agent_id="SOL_15M",
            asset="SOL",
            ticker="KXSOL15M-TEST",
            entry_price_cents=20,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        
        allocated_btc, _, slot_btc = allocator.request_allocation(request_btc)
        allocated_eth, _, slot_eth = allocator.request_allocation(request_eth)
        allocated_sol, _, slot_sol = allocator.request_allocation(request_sol)
        
        assert allocated_btc and allocated_eth and allocated_sol
        assert abs(allocator.get_total_exposure() - 0.85) < 0.01  # Floating point tolerance
        assert abs(allocator.get_available_exposure() - 0.15) < 0.01
        
        # Should reject DOGE 20c (would exceed $1)
        request_doge = AllocationRequest(
            agent_id="DOGE_15M",
            asset="DOGE",
            ticker="KXDOGE15M-TEST",
            entry_price_cents=20,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        allocated_doge, reason_doge, _ = allocator.request_allocation(request_doge)
        assert not allocated_doge
        assert "Insufficient exposure" in reason_doge
        
        # Exit order for BTC should be allowed even at full capacity
        request_exit_btc = AllocationRequest(
            agent_id="position_monitor",
            asset="BTC",
            ticker="KXBTC15M-TEST",
            entry_price_cents=50,
            edge_pct=0.0,
            spread_cents=0,
            is_exit_order=True
        )
        allocated_exit_btc, reason_exit_btc, _ = allocator.request_allocation(request_exit_btc)
        assert allocated_exit_btc
        assert reason_exit_btc == "EXIT_ORDER_BYPASS"
        
        # BTC closes - release slot
        allocator.release_slot(slot_btc, exit_price_cents=50)
        assert allocator.get_total_exposure() == 0.50
        assert allocator.get_available_exposure() == 0.50
        
        # Now DOGE 20c should be allowed
        allocated_doge2, _, slot_doge = allocator.request_allocation(request_doge)
        assert allocated_doge2
        assert allocator.get_total_exposure() == 0.70
        
        print("✓ Sequential trading with exits test passed")
    
    def test_release_by_asset(self):
        """Test releasing all slots for a specific asset."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        allocator = get_global_slot_allocator()
        
        # Allocate slots for different agents but same asset
        request1 = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-TEST1",
            entry_price_cents=20,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        request2 = AllocationRequest(
            agent_id="ETH_15M",  # Different agent to avoid any agent-specific limits
            asset="BTC",
            ticker="KXBTC15M-TEST2",
            entry_price_cents=30,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        
        allocated1, _, _ = allocator.request_allocation(request1)
        allocated2, _, _ = allocator.request_allocation(request2)
        
        assert allocated1 and allocated2
        assert abs(allocator.get_total_exposure() - 0.50) < 0.01  # Floating point tolerance
        
        # Release all slots for asset
        released_count = allocator.release_by_asset("BTC")
        assert released_count == 2
        assert allocator.get_total_exposure() == 0.0
        
        print("✓ Release by asset test passed")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x", "-s"])
