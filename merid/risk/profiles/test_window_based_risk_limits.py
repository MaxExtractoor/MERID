"""Unit tests for slot-based risk limits (fixed $1 exposure cap per 15m window).

CRITICAL FIX (2026-07-08): Window-based percentage limits (3% per-agent, 5% total) REMOVED.
Risk is now enforced via global_slot_allocator with fixed $1.00 exposure cap across all 5 assets.
These tests verify the slot allocation enforcement in global_slot_allocator.py.
"""

import pytest
import time
from unittest.mock import MagicMock, patch
from decimal import Decimal


class TestSlotBasedRiskLimits:
    """Test slot-based risk limit enforcement (fixed $1 exposure cap)."""
    
    def test_slot_limit_enforced_in_global_allocator(self):
        """Test that slot limit is enforced in global_slot_allocator.py with fixed $1 cap."""
        from merid.risk.global_slot_allocator import GlobalSlotAllocator, AllocationRequest
        
        allocator = GlobalSlotAllocator()
        
        # Test 1: Allocate first slot (35c)
        request1 = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-26JUN301900-00",
            entry_price_cents=35,
            edge_pct=5.0,
            spread_cents=2,
            confidence=0.8  # High confidence
        )
        allocated1, reason1, slot_id1 = allocator.request_allocation(request1)
        assert allocated1 is True
        assert slot_id1 is not None
        
        # Test 2: Allocate second slot (40c) - should succeed
        request2 = AllocationRequest(
            agent_id="ETH_15M",
            asset="ETH",
            ticker="KXETH15M-26JUN301900-00",
            entry_price_cents=40,
            edge_pct=5.0,
            spread_cents=2,
            confidence=0.7  # Medium-high confidence
        )
        allocated2, reason2, slot_id2 = allocator.request_allocation(request2)
        assert allocated2 is True
        assert slot_id2 is not None
        
        # Test 3: Allocate third slot (25c) - should succeed (total = $1.00)
        request3 = AllocationRequest(
            agent_id="SOL_15M",
            asset="SOL",
            ticker="KXSOL15M-26JUN301900-00",
            entry_price_cents=25,
            edge_pct=5.0,
            spread_cents=2,
            confidence=0.6  # Medium confidence
        )
        allocated3, reason3, slot_id3 = allocator.request_allocation(request3)
        assert allocated3 is True
        assert slot_id3 is not None
        
        # Test 4: Total exposure = $1.00, should reject next allocation
        request4 = AllocationRequest(
            agent_id="XRP_15M",
            asset="XRP",
            ticker="KXXRP15M-26JUN301900-00",
            entry_price_cents=20,
            edge_pct=5.0,
            spread_cents=2,
            confidence=0.9  # High confidence but no slot available
        )
        allocated4, reason4, slot_id4 = allocator.request_allocation(request4)
        assert allocated4 is False
        assert "insufficient exposure" in reason4.lower()
    
    def test_exit_orders_bypass_slot_allocation(self):
        """Test that exit orders bypass slot allocation and free up slots."""
        from merid.risk.global_slot_allocator import GlobalSlotAllocator, AllocationRequest
        
        allocator = GlobalSlotAllocator()
        
        # Allocate a slot (35c)
        request1 = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-26JUN301900-00",
            entry_price_cents=35,
            edge_pct=5.0,
            spread_cents=2,
            confidence=0.8  # High confidence
        )
        allocated1, reason1, slot_id1 = allocator.request_allocation(request1)
        assert allocated1 is True
        assert allocator.get_total_exposure() == 0.35
        
        # Exit order should bypass allocation
        exit_request = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-26JUN301900-00",
            entry_price_cents=35,
            edge_pct=5.0,
            spread_cents=2,
            confidence=0.5,  # Default confidence for exit orders
            is_exit_order=True
        )
        allocated_exit, reason_exit, slot_id_exit = allocator.request_allocation(exit_request)
        assert allocated_exit is True
        assert slot_id_exit is None  # Exit orders don't get slot IDs
        
        # Release the slot
        allocator.release_slot(slot_id1)
        assert allocator.get_total_exposure() == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
