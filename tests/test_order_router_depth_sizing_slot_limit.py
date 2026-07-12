"""Tests for order router depth-based sizing slot limit enforcement.

INVARIANT MARKER: This test validates the slot-based model invariant that
no order can exceed 1 contract per order. Depth-based sizing should never
increase count beyond 1, as the slot-based model enforces a fixed $1 exposure
cap with 1 contract per order.
"""

import pytest
from merid.event_venues.kalshi.order_router import OrderIntent, _apply_depth_based_order_sizing


class MockMarketState:
    """Mock market state for testing."""
    def __init__(self, top_of_book_size=0):
        self.top_of_book_size = top_of_book_size


class TestDepthBasedSizingSlotLimit:
    """Tests for _apply_depth_based_order_sizing slot limit enforcement."""
    
    def test_requested_count_1_returns_1(self):
        """Test that requested_count=1 returns 1 (slot limit)."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        state = MockMarketState(top_of_book_size=10)
        
        result = _apply_depth_based_order_sizing(intent, state)
        assert result == 1
    
    def test_requested_count_0_returns_0(self):
        """Test that requested_count=0 returns 0."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=0,
        )
        state = MockMarketState(top_of_book_size=10)
        
        result = _apply_depth_based_order_sizing(intent, state)
        assert result == 0
    
    def test_requested_count_greater_than_1_capped_to_1(self):
        """Test that requested_count > 1 is capped to 1 (slot limit)."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=5,
        )
        state = MockMarketState(top_of_book_size=10)
        
        result = _apply_depth_based_order_sizing(intent, state)
        assert result == 1
    
    def test_requested_count_greater_than_1_with_no_state_capped_to_1(self):
        """Test that requested_count > 1 with no state is capped to 1."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
        )
        state = None
        
        result = _apply_depth_based_order_sizing(intent, state)
        assert result == 1
    
    def test_requested_count_greater_than_1_with_zero_liquidity_capped_to_1(self):
        """Test that requested_count > 1 with zero liquidity is capped to 1."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=3,
        )
        state = MockMarketState(top_of_book_size=0)
        
        result = _apply_depth_based_order_sizing(intent, state)
        assert result == 1
    
    def test_requested_count_1_with_thin_liquidity_returns_1(self):
        """Test that requested_count=1 with thin liquidity returns 1 (minimum)."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        state = MockMarketState(top_of_book_size=1)
        
        result = _apply_depth_based_order_sizing(intent, state)
        assert result == 1
    
    def test_requested_count_1_with_no_state_returns_1(self):
        """Test that requested_count=1 with no state returns 1."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        state = None
        
        result = _apply_depth_based_order_sizing(intent, state)
        assert result == 1
    
    def test_requested_count_1_with_zero_liquidity_returns_1(self):
        """Test that requested_count=1 with zero liquidity returns 1."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        state = MockMarketState(top_of_book_size=0)
        
        result = _apply_depth_based_order_sizing(intent, state)
        assert result == 1
    
    def test_max_size_never_exceeds_1(self):
        """Test that max_size calculation never exceeds 1 (slot limit)."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        # Even with massive liquidity, should not exceed 1
        state = MockMarketState(top_of_book_size=1000)
        
        result = _apply_depth_based_order_sizing(intent, state)
        assert result == 1
    
    def test_requested_count_100_capped_to_1(self):
        """Test that requested_count=100 is capped to 1 (extreme case)."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=100,
        )
        state = MockMarketState(top_of_book_size=1000)
        
        result = _apply_depth_based_order_sizing(intent, state)
        assert result == 1
