"""
Test for per-asset limit race condition fix (2026-07-14)

This test verifies that the slot allocation BEFORE order submission
prevents multiple contracts from executing for the same asset in the
same 15-minute window.

Root cause: Previous implementation allocated slots AFTER fill, allowing
multiple orders to pass can_allocate() simultaneously and all fill before
slots were allocated.

Fix: Move slot allocation to BEFORE order submission to enforce
MAX_POSITIONS_PER_ASSET=1 at submission time.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from merid.risk.global_slot_allocator import get_global_slot_allocator, AllocationRequest


class TestPerAssetLimitRaceConditionFix:
    """Test that slot allocation before submission prevents race condition."""
    
    def test_slot_allocation_blocks_duplicate_asset_orders(self):
        """Test that once a slot is allocated for an asset, subsequent orders are blocked."""
        allocator = get_global_slot_allocator()
        allocator.reset_all()  # Start clean
        
        # First BTC order should succeed
        request1 = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC-15M-...",
            entry_price_cents=42,
            edge_pct=0.05,
            spread_cents=2,
            confidence=0.7,
            is_exit_order=False
        )
        
        allocated1, reason1, slot_id1 = allocator.request_allocation(request1)
        assert allocated1, f"First BTC order should be allocated, got: {reason1}"
        assert slot_id1 is not None
        
        # Second BTC order should be rejected (per-asset limit)
        request2 = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC-15M-...",
            entry_price_cents=45,
            edge_pct=0.06,
            spread_cents=2,
            confidence=0.75,
            is_exit_order=False
        )
        
        allocated2, reason2, slot_id2 = allocator.request_allocation(request2)
        assert not allocated2, f"Second BTC order should be rejected, got allocated: {slot_id2}"
        assert "already has" in reason2.lower() or "max" in reason2.lower(), f"Expected per-asset limit rejection, got: {reason2}"
        
        # ETH order should still succeed (different asset)
        request3 = AllocationRequest(
            agent_id="ETH_15M",
            asset="ETH",
            ticker="KXETH-15M-...",
            entry_price_cents=38,
            edge_pct=0.04,
            spread_cents=2,
            confidence=0.65,
            is_exit_order=False
        )
        
        allocated3, reason3, slot_id3 = allocator.request_allocation(request3)
        assert allocated3, f"ETH order should be allocated (different asset), got: {reason3}"
        assert slot_id3 is not None
        
        # Cleanup
        allocator.release_slot(slot_id1)
        allocator.release_slot(slot_id3)
        
        print("✓ Slot allocation blocks duplicate asset orders test passed")
    
    def test_can_allocate_enforces_per_asset_limit(self):
        """Test that can_allocate() enforces MAX_POSITIONS_PER_ASSET=1."""
        allocator = get_global_slot_allocator()
        allocator.reset_all()  # Start clean
        
        # First XRP order should pass can_allocate
        can_alloc1, reason1 = allocator.can_allocate(35, "XRP")
        assert can_alloc1, f"First XRP order should pass can_allocate, got: {reason1}"
        
        # Allocate the slot
        request = AllocationRequest(
            agent_id="XRP_15M",
            asset="XRP",
            ticker="KXXRP-15M-...",
            entry_price_cents=35,
            edge_pct=0.05,
            spread_cents=2,
            confidence=0.7,
            is_exit_order=False
        )
        allocated, _, slot_id = allocator.request_allocation(request)
        assert allocated
        
        # Second XRP order should fail can_allocate (per-asset limit)
        can_alloc2, reason2 = allocator.can_allocate(40, "XRP")
        assert not can_alloc2, f"Second XRP order should fail can_allocate, got: {reason2}"
        assert "already has" in reason2.lower() or "max" in reason2.lower(), f"Expected per-asset limit, got: {reason2}"
        
        # DOGE order should still pass can_allocate (different asset)
        can_alloc3, reason3 = allocator.can_allocate(30, "DOGE")
        assert can_alloc3, f"DOGE order should pass can_allocate (different asset), got: {reason3}"
        
        # Cleanup
        allocator.release_slot(slot_id)
        
        print("✓ can_allocate enforces per-asset limit test passed")
    
    def test_exit_orders_bypass_per_asset_limit(self):
        """Test that exit orders bypass the per-asset limit."""
        allocator = get_global_slot_allocator()
        allocator.reset_all()  # Start clean
        
        # Allocate a slot for DOGE
        entry_request = AllocationRequest(
            agent_id="DOGE_15M",
            asset="DOGE",
            ticker="KXDOGE-15M-...",
            entry_price_cents=25,
            edge_pct=0.05,
            spread_cents=2,
            confidence=0.7,
            is_exit_order=False
        )
        allocated, _, slot_id = allocator.request_allocation(entry_request)
        assert allocated
        
        # Exit order should bypass slot allocation (returns success without allocating)
        exit_request = AllocationRequest(
            agent_id="DOGE_15M",
            asset="DOGE",
            ticker="KXDOGE-15M-...",
            entry_price_cents=25,
            edge_pct=0.0,
            spread_cents=0,
            confidence=0.5,
            is_exit_order=True
        )
        
        allocated_exit, reason_exit, slot_id_exit = allocator.request_allocation(exit_request)
        assert allocated_exit, f"Exit order should bypass allocation, got: {reason_exit}"
        assert slot_id_exit is None, f"Exit order should not allocate a slot, got: {slot_id_exit}"
        assert reason_exit == "EXIT_ORDER_BYPASS", f"Expected EXIT_ORDER_BYPASS, got: {reason_exit}"
        
        # Cleanup
        allocator.release_slot(slot_id)
        
        print("✓ Exit orders bypass per-asset limit test passed")
    
    def test_slot_release_on_rejection(self):
        """Test that slots are released when orders are rejected."""
        allocator = get_global_slot_allocator()
        allocator.reset_all()  # Start clean
        
        # Allocate a slot for SOL
        request = AllocationRequest(
            agent_id="SOL_15M",
            asset="SOL",
            ticker="KXSOL-15M-...",
            entry_price_cents=50,
            edge_pct=0.05,
            spread_cents=2,
            confidence=0.7,
            is_exit_order=False
        )
        allocated, _, slot_id = allocator.request_allocation(request)
        assert allocated
        
        # Verify slot is occupied
        assert allocator.get_slot_count() == 1
        
        # Release the slot (simulating order rejection)
        released = allocator.release_slot(slot_id)
        assert released, "Slot should be released successfully"
        
        # Verify slot is now free
        assert allocator.get_slot_count() == 0
        
        # New SOL order should now be able to allocate
        request2 = AllocationRequest(
            agent_id="SOL_15M",
            asset="SOL",
            ticker="KXSOL-15M-...",
            entry_price_cents=52,
            edge_pct=0.06,
            spread_cents=2,
            confidence=0.75,
            is_exit_order=False
        )
        allocated2, _, slot_id2 = allocator.request_allocation(request2)
        assert allocated2, "New SOL order should be allocated after slot release"
        
        # Cleanup
        allocator.release_slot(slot_id2)
        
        print("✓ Slot release on rejection test passed")
    
    def test_allocation_request_with_agent_id_fallback(self):
        """Test that allocation request handles missing agent_id with fallback to source."""
        allocator = get_global_slot_allocator()
        allocator.reset_all()  # Start clean
        
        # Test with agent_id provided
        request1 = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC-15M-...",
            entry_price_cents=42,
            edge_pct=0.05,
            spread_cents=2,
            confidence=0.7,
            is_exit_order=False
        )
        allocated1, _, slot_id1 = allocator.request_allocation(request1)
        assert allocated1, "Allocation with agent_id should succeed"
        
        # Release the first slot to test different agent_id values
        allocator.release_slot(slot_id1)
        
        # Test with 'unknown' agent_id (simulating the bug fix scenario)
        # The code uses: intent.agent_id or intent.source or "unknown"
        request2 = AllocationRequest(
            agent_id="unknown",  # This is what the code falls back to
            asset="ETH",
            ticker="KXETH-15M-...",
            entry_price_cents=38,
            edge_pct=0.04,
            spread_cents=2,
            confidence=0.65,
            is_exit_order=False
        )
        allocated2, _, slot_id2 = allocator.request_allocation(request2)
        assert allocated2, "Allocation with 'unknown' agent_id should succeed"
        
        # Release the second slot
        allocator.release_slot(slot_id2)
        
        # Test with source as fallback
        request3 = AllocationRequest(
            agent_id="merid.prediction.agent_grid_15m",  # Using source as agent_id
            asset="DOGE",
            ticker="KXDOGE-15M-...",
            entry_price_cents=25,
            edge_pct=0.03,
            spread_cents=2,
            confidence=0.6,
            is_exit_order=False
        )
        allocated3, _, slot_id3 = allocator.request_allocation(request3)
        assert allocated3, "Allocation with source as agent_id should succeed"
        
        # Cleanup
        allocator.release_slot(slot_id3)
        
        print("✓ Allocation request with agent_id fallback test passed")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
