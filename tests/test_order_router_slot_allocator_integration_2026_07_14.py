"""
Test suite for Order Router + Slot Allocator integration (2026-07-14)

Tests that the order router properly calls slot_allocator.can_allocate()
to enforce per-asset position limits (MAX_POSITIONS_PER_ASSET=1).
"""

import pytest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestOrderRouterSlotAllocatorIntegration:
    """Test suite for order router slot allocator integration."""
    
    def setup_method(self):
        """Reset allocator before each test."""
        from merid.risk.global_slot_allocator import reset_global_slot_allocator
        reset_global_slot_allocator()
    
    def test_order_router_calls_can_allocate(self):
        """Test that order router calls slot_allocator.can_allocate() for entry orders."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        
        allocator = get_global_slot_allocator()
        
        # First BTC allocation should succeed
        request1 = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-26JUL111145-45",
            entry_price_cents=35,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        can_alloc1, reason1 = allocator.can_allocate(35, "BTC")
        assert can_alloc1, f"First BTC should be allocatable: {reason1}"
        
        # Allocate it
        allocated1, _, slot1 = allocator.request_allocation(request1)
        assert allocated1
        assert allocator.get_total_exposure() == 0.35
        
        # Second BTC allocation should fail (per-asset limit)
        can_alloc2, reason2 = allocator.can_allocate(40, "BTC")
        assert not can_alloc2, f"Second BTC should NOT be allocatable: {reason2}"
        assert "already has" in reason2.lower() or "position" in reason2.lower()
        
        print("✓ Order router calls can_allocate() test passed")
    
    def test_exit_order_bypasses_can_allocate(self):
        """Test that exit orders bypass can_allocate() check."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        
        allocator = get_global_slot_allocator()
        
        # Fill up to capacity
        request = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-26JUL111145-45",
            entry_price_cents=75,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        allocated, _, slot_id = allocator.request_allocation(request)
        assert allocated
        assert allocator.get_total_exposure() == 0.75
        
        # Exit order request should bypass allocation even at full capacity
        exit_request = AllocationRequest(
            agent_id="position_monitor",
            asset="BTC",
            ticker="KXBTC15M-26JUL111145-45",
            entry_price_cents=50,
            edge_pct=0.0,
            spread_cents=0,
            is_exit_order=True
        )
        allocated_exit, reason_exit, slot_id_exit = allocator.request_allocation(exit_request)
        assert allocated_exit
        assert reason_exit == "EXIT_ORDER_BYPASS"
        assert slot_id_exit is None  # Exit orders don't get slot IDs
        
        # Exposure should still be $0.75 (exit orders don't consume slots)
        assert allocator.get_total_exposure() == 0.75
        
        print("✓ Exit order bypasses can_allocate() test passed")
    
    def test_per_asset_limit_enforcement(self):
        """Test that can_allocate() enforces MAX_POSITIONS_PER_ASSET=1."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )
        
        allocator = get_global_slot_allocator()
        
        # First BTC allocation should succeed
        request1 = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-26JUL111145-45",
            entry_price_cents=35,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        can_alloc1, reason1 = allocator.can_allocate(35, "BTC")
        assert can_alloc1, f"First BTC should be allocatable: {reason1}"
        
        # Allocate it
        allocated1, _, slot1 = allocator.request_allocation(request1)
        assert allocated1
        
        # Second BTC allocation should fail (per-asset limit)
        can_alloc2, reason2 = allocator.can_allocate(40, "BTC")
        assert not can_alloc2, f"Second BTC should NOT be allocatable: {reason2}"
        assert "already has" in reason2.lower() or "position" in reason2.lower()
        
        # ETH should still be allocatable (different asset)
        can_alloc3, reason3 = allocator.can_allocate(30, "ETH")
        assert can_alloc3, f"ETH should be allocatable: {reason3}"
        
        print("✓ Per-asset limit enforcement test passed")
    
    def test_can_allocate_respects_exposure_cap(self):
        """can_allocate() enforces the configured exposure cap at boundaries.

        The production default moved $1 -> $3 -> $6 (commit 811db09f), so the
        cap is injected explicitly rather than asserted against the ambient
        default.  Prices stay inside the [25c, 80c] entry band so the exposure
        check — not the price-domain check — is what rejects."""
        from merid.risk.global_slot_allocator import (
            get_global_slot_allocator,
            AllocationRequest
        )

        allocator = get_global_slot_allocator()
        allocator.max_exposure_usd = 1.00

        # Fill to $0.75: BTC 1ct @45c + ETH 1ct @30c -> $0.25 available.
        request1 = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-26JUL111145-45",
            entry_price_cents=45,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )
        request2 = AllocationRequest(
            agent_id="ETH_15M",
            asset="ETH",
            ticker="KXETH15M-26JUL111145-45",
            entry_price_cents=30,
            edge_pct=2.0,
            spread_cents=5,
            is_exit_order=False
        )

        allocator.request_allocation(request1)
        allocator.request_allocation(request2)
        assert abs(allocator.get_total_exposure() - 0.75) < 0.01

        # Boundary: SOL 1ct @25c needs exactly $0.25 == available -> allowed.
        can_alloc, reason = allocator.can_allocate(25, "SOL")
        assert can_alloc, f"25c order should fit exactly at $0.25 available: {reason}"

        # Over cap: SOL 1ct @60c needs $0.60 > $0.25 -> insufficient exposure.
        can_alloc2, reason2 = allocator.can_allocate(60, "SOL")
        assert not can_alloc2, f"60c order should fail at $0.25 available: {reason2}"
        assert "insufficient exposure" in reason2.lower()

        # Fractional count still bounded by the same cash exposure math:
        # 0.5ct @60c = $0.30 > $0.25 -> rejected.
        can_alloc3, reason3 = allocator.can_allocate(60, "SOL", count=0.5)
        assert not can_alloc3, f"0.5ct @60c should fail at $0.25 available: {reason3}"

        # 0.4ct @60c = $0.24 <= $0.25 -> allowed.
        can_alloc4, reason4 = allocator.can_allocate(60, "SOL", count=0.4)
        assert can_alloc4, f"0.4ct @60c should fit at $0.25 available: {reason4}"

        print("✓ can_allocate() respects exposure cap test passed")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x", "-s"])
