"""
Test for AllocationRequest price validation fix (2026-07-15)

This test verifies that AllocationRequest validates entry prices against the
canonical 10-75c range, not the legacy 10-50c range.

Bug: AllocationRequest.__post_init__ was validating against 10-50c instead of 10-75c
Fix: Changed validation from > 50 to > 75 to match GlobalSlotAllocator.MAX_ENTRY_CENTS
"""

import pytest
from merid.risk.global_slot_allocator import AllocationRequest


class TestAllocationRequest75cFix:
    """Test AllocationRequest price validation with 75c max."""

    def test_allocation_request_accepts_75c_entry_price(self):
        """AllocationRequest should accept entry prices up to 75c."""
        # This should NOT raise ValueError
        request = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-26JUL121430-30",
            entry_price_cents=75,
            edge_pct=2.5,
            spread_cents=5,
            is_exit_order=False
        )
        assert request.entry_price_cents == 75

    def test_allocation_request_accepts_10c_entry_price(self):
        """AllocationRequest should accept entry prices at minimum 10c."""
        # This should NOT raise ValueError
        request = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-26JUL121430-30",
            entry_price_cents=10,
            edge_pct=2.5,
            spread_cents=5,
            is_exit_order=False
        )
        assert request.entry_price_cents == 10

    def test_allocation_request_accepts_mid_range_price(self):
        """AllocationRequest should accept mid-range prices (e.g., 42c)."""
        # This should NOT raise ValueError
        request = AllocationRequest(
            agent_id="ETH_15M",
            asset="ETH",
            ticker="KXETH15M-26JUL121430-30",
            entry_price_cents=42,
            edge_pct=2.0,
            spread_cents=3,
            is_exit_order=False
        )
        assert request.entry_price_cents == 42

    def test_allocation_request_rejects_below_10c(self):
        """AllocationRequest should reject entry prices below 10c."""
        with pytest.raises(ValueError, match="Entry price .*c outside allowed range \\[10, 75\\]"):
            AllocationRequest(
                agent_id="BTC_15M",
                asset="BTC",
                ticker="KXBTC15M-26JUL121430-30",
                entry_price_cents=9,
                edge_pct=2.5,
                spread_cents=5,
                is_exit_order=False
            )

    def test_allocation_request_rejects_above_75c(self):
        """AllocationRequest should reject entry prices above 75c."""
        with pytest.raises(ValueError, match="Entry price .*c outside allowed range \\[10, 75\\]"):
            AllocationRequest(
                agent_id="BTC_15M",
                asset="BTC",
                ticker="KXBTC15M-26JUL121430-30",
                entry_price_cents=76,
                edge_pct=2.5,
                spread_cents=5,
                is_exit_order=False
            )

    def test_allocation_request_rejects_51c_was_bug(self):
        """
        CRITICAL: This test verifies the bug fix.
        
        Before fix: AllocationRequest rejected 51-75c (validated against 10-50c)
        After fix: AllocationRequest accepts 51-75c (validates against 10-75c)
        
        This test would have FAILED before the fix and PASSES after the fix.
        """
        # This should NOT raise ValueError after the fix
        request = AllocationRequest(
            agent_id="SOL_15M",
            asset="SOL",
            ticker="KXSOL15M-26JUL121430-30",
            entry_price_cents=64,  # In the 51-75c range that was previously rejected
            edge_pct=2.5,
            spread_cents=5,
            is_exit_order=False
        )
        assert request.entry_price_cents == 64

    def test_allocation_request_exit_order_bypasses_validation(self):
        """Exit orders should bypass price validation entirely."""
        # Exit orders can be at any price, even outside 10-75c range
        request = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-26JUL121430-30",
            entry_price_cents=100,  # Above 75c - would normally be rejected
            edge_pct=2.5,
            spread_cents=5,
            is_exit_order=True  # Exit order bypasses validation
        )
        assert request.entry_price_cents == 100

    def test_allocation_request_exit_order_accepts_low_price(self):
        """Exit orders should accept prices below 10c."""
        request = AllocationRequest(
            agent_id="BTC_15M",
            asset="BTC",
            ticker="KXBTC15M-26JUL121430-30",
            entry_price_cents=5,  # Below 10c - would normally be rejected
            edge_pct=2.5,
            spread_cents=5,
            is_exit_order=True  # Exit order bypasses validation
        )
        assert request.entry_price_cents == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
