"""Tests for order router depth-based sizing slot limit enforcement.

INVARIANT MARKER: This test validates the slot-based model invariant that
no order can exceed MAX_CONTRACTS_PER_ORDER. Depth-based sizing should never
increase count beyond that cap, and with thin depth it reduces to 80% of
top-of-book.  (2026-10-09: the cap is env-configured — the .env trade-every-
window raise to 3 contracts made the literal 1-contract assertions stale; the
invariant is "never exceeds the configured cap", not "== 1".)
"""

from decimal import Decimal as _Decimal

import pytest
from merid.event_venues.kalshi.order_router import OrderIntent, _apply_depth_based_order_sizing
from merid.event_venues.kalshi.order_router import MAX_CONTRACTS_PER_ORDER as _CAP


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
    
    def test_requested_count_above_cap_capped_to_cap(self):
        """Test that requested_count > MAX_CONTRACTS_PER_ORDER is capped.

        The request must exceed the *configured* cap to exercise the clamp —
        a fixed literal goes stale every time the cap is retuned (the cap
        moved 1 -> 3 -> 6 across 2026-10)."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=int(_CAP) + 5,
        )
        state = MockMarketState(top_of_book_size=10)

        result = _apply_depth_based_order_sizing(intent, state)
        assert result == _CAP
    
    def test_requested_count_greater_than_1_with_no_state_capped_to_1(self):
        """Test that requested_count > cap with no state is capped."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
        )
        state = None
        
        result = _apply_depth_based_order_sizing(intent, state)
        assert result == _CAP
    
    def test_requested_count_above_cap_with_zero_liquidity_capped_to_cap(self):
        """Test that requested_count > cap with zero liquidity is capped.

        Zero top-of-book returns the (already cap-clamped) request unchanged;
        the request must exceed the configured cap to exercise the clamp."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=int(_CAP) + 3,
        )
        state = MockMarketState(top_of_book_size=0)

        result = _apply_depth_based_order_sizing(intent, state)
        assert result == _CAP
    
    def test_requested_count_1_with_thin_liquidity_returns_1(self):
        """Requested 1 with top-of-book=1: depth sizing reduces to 80% depth."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        state = MockMarketState(top_of_book_size=1)
        
        result = _apply_depth_based_order_sizing(intent, state)
        assert result == _Decimal("0.8")
    
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
        """Test that requested_count=100 is capped to the slot limit."""
        intent = OrderIntent(
            ticker="KXBTC15M-12345",
            side="yes",
            action="buy",
            price_cents=50,
            count=100,
        )
        state = MockMarketState(top_of_book_size=1000)
        
        result = _apply_depth_based_order_sizing(intent, state)
        assert result == _CAP
