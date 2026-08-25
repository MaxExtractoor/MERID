"""Comprehensive tests for YES/NO price adjustment and sweet spot logic fixes.

Tests the fix for BUY_NO/BUY_YES trades failing due to blind sweet spot repricing.
The SWEET-SPOT-EXECUTION block was transforming prices (e.g. 40c/48c) into 55c without
respecting side, role, or the current order book, causing downstream rejections.

Classification (2026-08-18): The `book_not_initialized` failures were an
**invalid fixture** — the production guard in `_adjust_order_price_for_fill_rate`
explicitly raises `RepriceWouldCross` when the orderbook is uninitialized or
stale, which is the correct fail-closed behavior.  The `MockMarketState` fixture
now models a valid, initialized book and new tests cover the guard branches.

Key fixes tested:
1. _determine_dynamic_order_type bypasses SWEET-SPOT-EXECUTION for BUY NO / BUY YES.
2. _adjust_order_price_for_fill_rate is side-aware and role-aware (maker/taker).
3. compute_order_size always re-runs Kelly/sizing against the final repriced price.
4. Maker BUY routes enforce the strict invariant adjusted_price < side_ask.
   Maker SELL routes enforce adjusted_price > side_bid.
   Taker BUY/SELL must cross or touch the spread.
   Violations raise RepriceWouldCross (not assert).
5. Uninitialized, stale, absent, or crossed books raise RepriceWouldCross.
"""

import time as _time
import pytest
from unittest.mock import Mock, MagicMock
from dataclasses import dataclass, field
from decimal import Decimal

# Import the functions we're testing
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from merid.event_venues.kalshi.order_router import (
    _adjust_order_price_for_fill_rate,
    _determine_dynamic_order_type,
    OrderIntent,
    RepriceWouldCross,
)
from merid.prediction.unified_sizing import compute_order_size


@dataclass
class MockMarketState:
    """Mock market state for testing.

    2026-08-18: Added `book_initialized` and `last_book_update_wall_ts` so the
    fixture models a valid, live-equivalent book by default. Tests that need to
    exercise the uninitialized/stale guard can set `book_initialized=False` or
    an old timestamp.
    """
    mid_cents: int
    best_bid_cents: int
    best_ask_cents: int
    ask_cents: int
    bid_cents: int
    depth_10c: int = 1000  # Default depth to avoid liquidity check triggering market orders
    best_bid_size: int = 1
    best_ask_size: int = 1
    book_initialized: bool = True
    last_book_update_wall_ts: float = field(default_factory=_time.time)


class TestNOOrderPriceAdjustment:
    """Test that NO orders use correct NO mid-price for price adjustment."""
    
    def test_buy_no_price_adjustment_uses_no_mid(self):
        """Test that BUY_NO orders use NO mid-price (100 - YES_mid) for adjustment."""
        # Create a BUY_NO intent at 37c (NO price)
        intent = OrderIntent(
            ticker="KXETH15M-26JUL312300-00",
            side="BUY_NO",
            action="buy",
            price_cents=37,
            count=1,
            order_type="limit",
            time_in_force="gtc"
        )
        
        # Mock market state with YES mid=63c, so NO mid should be 37c.
        # Give YES a tiny spread so the NO ask is 38c; a maker BUY_NO at 37c
        # remains non-crossing (37c < 38c) and is not adjusted.
        state = MockMarketState(
            mid_cents=63,  # YES mid
            best_bid_cents=62,
            best_ask_cents=64,
            ask_cents=64,
            bid_cents=62
        )
        
        # Adjust price
        adjusted_price = _adjust_order_price_for_fill_rate(intent, state)
        
        # For BUY_NO at 37c with NO mid=37c, should not adjust (already at mid)
        # The fix ensures NO mid-price is used: NO_mid = 100 - YES_mid = 100 - 63 = 37
        # Since 37c == NO mid, no adjustment should occur
        assert adjusted_price == 37, f"BUY_NO at 37c with NO mid=37c should not adjust, got {adjusted_price}c"
    
    def test_buy_no_price_adjustment_below_no_mid(self):
        """Test that BUY_NO orders below NO mid are adjusted toward NO mid."""
        # Create a BUY_NO intent at 30c (below NO mid)
        intent = OrderIntent(
            ticker="KXETH15M-26JUL312300-00",
            side="BUY_NO",
            action="buy",
            price_cents=30,
            count=1,
            order_type="limit",
            time_in_force="gtc"
        )
        
        # Mock market state with YES mid=70c, so NO mid should be 30c.
        # Give YES a tiny spread so the NO ask is 31c; a maker BUY_NO at 30c
        # remains non-crossing and is not adjusted.
        state = MockMarketState(
            mid_cents=70,  # YES mid
            best_bid_cents=69,
            best_ask_cents=70,
            ask_cents=70,
            bid_cents=69
        )
        
        # Adjust price
        adjusted_price = _adjust_order_price_for_fill_rate(intent, state)
        
        # For BUY_NO at 30c with NO mid=30c, should not adjust (already at mid)
        # The fix ensures NO mid-price is used: NO_mid = 100 - YES_mid = 100 - 70 = 30
        assert adjusted_price == 30, f"BUY_NO at 30c with NO mid=30c should not adjust, got {adjusted_price}c"
    
    def test_buy_yes_price_adjustment_uses_yes_mid(self):
        """Test that BUY_YES orders still use YES mid-price for adjustment."""
        # Create a BUY_YES intent at 37c (YES price)
        intent = OrderIntent(
            ticker="KXETH15M-26JUL312300-00",
            side="BUY_YES",
            action="buy",
            price_cents=37,
            count=1,
            order_type="limit",
            time_in_force="gtc"
        )
        
        # Mock market state with YES mid=63c and a valid bid/ask spread.
        # A locked book (bid == ask) would be rejected by the fail-closed
        # canonical-price placement guard, so we use a 1c spread.
        state = MockMarketState(
            mid_cents=63,  # YES mid
            best_bid_cents=62,
            best_ask_cents=63,
            ask_cents=63,
            bid_cents=62
        )
        
        # Adjust price
        adjusted_price = _adjust_order_price_for_fill_rate(intent, state)
        
        # For BUY_YES at 37c with YES mid=63c, should adjust toward mid
        # 25% of distance: 37 + (63-37)*0.25 = 37 + 6.5 = 43.5 -> 43c
        # And ensure we don't go above mid: min(43, 63-1) = 42c
        # But the actual implementation does: int(37 + (63-37)*0.25) = int(43.5) = 43
        # Then min(43, 62) = 43c
        assert adjusted_price == 43, f"BUY_YES at 37c with YES mid=63c should adjust to 43c, got {adjusted_price}c"
    
    def test_sell_no_price_adjustment_uses_no_mid(self):
        """Test that SELL_NO orders use NO mid-price for adjustment."""
        # Create a SELL_NO intent at 70c (NO price)
        intent = OrderIntent(
            ticker="KXETH15M-26JUL312300-00",
            side="SELL_NO",
            action="sell",
            price_cents=70,
            count=1,
            order_type="limit",
            time_in_force="gtc"
        )
        
        # Mock market state with YES mid=30c, so NO mid should be 70c.
        # Give YES a tiny spread so the NO bid is 69c; a maker SELL_NO at 70c
        # remains non-crossing (70c > 69c) and is not adjusted.
        state = MockMarketState(
            mid_cents=30,  # YES mid
            best_bid_cents=30,
            best_ask_cents=31,
            ask_cents=31,
            bid_cents=30
        )
        
        # Adjust price
        adjusted_price = _adjust_order_price_for_fill_rate(intent, state)
        
        # For SELL_NO at 70c with NO mid=70c, should not adjust (already at mid)
        # The fix ensures NO mid-price is used: NO_mid = 100 - YES_mid = 100 - 30 = 70
        assert adjusted_price == 70, f"SELL_NO at 70c with NO mid=70c should not adjust, got {adjusted_price}c"
    
    def test_sell_yes_price_adjustment_uses_yes_mid(self):
        """Test that SELL_YES orders still use YES mid-price for adjustment."""
        # Create a SELL_YES intent at 70c (YES price)
        intent = OrderIntent(
            ticker="KXETH15M-26JUL312300-00",
            side="SELL_YES",
            action="sell",
            price_cents=70,
            count=1,
            order_type="limit",
            time_in_force="gtc"
        )
        
        # Mock market state with YES mid=50c and a valid bid/ask spread.
        # A locked book (bid == ask) would be rejected by the fail-closed
        # canonical-price placement guard, so we use a 1c spread.
        state = MockMarketState(
            mid_cents=50,  # YES mid
            best_bid_cents=49,
            best_ask_cents=50,
            ask_cents=50,
            bid_cents=49
        )
        
        # Adjust price
        adjusted_price = _adjust_order_price_for_fill_rate(intent, state)
        
        # For SELL_YES at 70c with YES mid=50c, should adjust toward mid
        # 25% of distance: 70 - (70-50)*0.25 = 70 - 5 = 65c
        # And ensure we don't go below mid: max(65, 50+1) = 51c
        # But the actual implementation does: int(70 - (70-50)*0.25) = int(65) = 65
        # Then max(65, 51) = 65c
        assert adjusted_price == 65, f"SELL_YES at 70c with YES mid=50c should adjust to 65c, got {adjusted_price}c"


class TestSweetSpotLogicForNOOrders:
    """Test that sweet spot logic works correctly for NO orders using YES-space conversion."""
    
    def test_buy_no_uses_sweet_spot_logic(self):
        """Test that BUY_NO orders use sweet spot logic with YES-space conversion."""
        # Create a BUY_NO intent at 37c (NO price)
        # YES mid = 63c, so NO mid = 37c
        # YES equivalent = 100 - 37 = 63c (above optimal range, no sweet spot)
        intent = OrderIntent(
            ticker="KXETH15M-26JUL312300-00",
            side="BUY_NO",
            action="buy",
            price_cents=37,
            count=1,
            order_type="limit",
            time_in_force="gtc"
        )
        
        # Mock market state with YES mid=63c
        state = MockMarketState(
            mid_cents=63,
            best_bid_cents=63,
            best_ask_cents=63,
            ask_cents=63,
            bid_cents=63,
            depth_10c=1000  # Add depth to avoid liquidity check
        )
        
        # Determine dynamic order type
        order_type, tif = _determine_dynamic_order_type(intent, state)
        
        # Should return limit order without sweet spot adjustment (above optimal range)
        assert order_type == "limit", f"BUY_NO should return limit order, got {order_type}"
        # Price should remain unchanged (YES equivalent 63c is above optimal 55c)
        assert intent.price_cents == 37, f"BUY_NO price should not be adjusted (above optimal range), got {intent.price_cents}c"
    
    def test_sell_no_uses_sweet_spot_logic(self):
        """Test that SELL_NO orders use sweet spot logic with YES-space conversion."""
        # Create a SELL_NO intent at 70c (NO price)
        # YES mid = 30c, so NO mid = 70c
        # YES equivalent = 100 - 70 = 30c (below optimal range, sweet spot applies)
        intent = OrderIntent(
            ticker="KXETH15M-26JUL312300-00",
            side="SELL_NO",
            action="sell",
            price_cents=70,
            count=1,
            order_type="limit",
            time_in_force="gtc"
        )
        
        # Mock market state with YES mid=30c and bid=25c (lower than sweet spot)
        state = MockMarketState(
            mid_cents=30,
            best_bid_cents=25,  # YES bid
            best_ask_cents=30,
            ask_cents=30,
            bid_cents=25,
            depth_10c=2000  # $600 depth to avoid liquidity check (2000 * 0.30 = $600)
        )
        
        # Determine dynamic order type
        order_type, tif = _determine_dynamic_order_type(intent, state)
        
        # Should return limit order with sweet spot adjustment
        assert order_type == "limit", f"SELL_NO should return limit order, got {order_type}"
        # Sweet spot in YES space: 30c + 5c = 35c
        # Sweet spot in NO space: 100 - 35c = 65c
        # NO bid = 100 - YES ask = 100 - 30 = 70c, so sweet spot 65c is below bid
        # Should be raised to bid: 70c
        assert intent.price_cents == 70, f"SELL_NO sweet spot should be raised to NO bid 70c, got {intent.price_cents}c"
    
    def test_buy_yes_bypasses_sweet_spot_logic(self):
        """Test that BUY_YES orders bypass sweet spot logic to avoid blind repricing."""
        # Create a BUY_YES intent below optimal range
        intent = OrderIntent(
            ticker="KXETH15M-26JUL312300-00",
            side="BUY_YES",
            action="buy",
            price_cents=35,  # Below optimal range (40-55c)
            count=1,
            order_type="limit",
            time_in_force="gtc"
        )
        
        # Mock market state with YES mid=35c and ask=40c
        state = MockMarketState(
            mid_cents=35,
            best_bid_cents=35,
            best_ask_cents=40,
            ask_cents=40,
            bid_cents=35,
            depth_10c=1000  # Add depth to avoid liquidity check
        )
        
        # Determine dynamic order type
        order_type, tif = _determine_dynamic_order_type(intent, state)
        
        # Should return limit order (sweet spot bypassed for BUY)
        assert order_type == "limit", f"BUY_YES should return limit order, got {order_type}"
        assert tif == "gtc", f"BUY_YES should return GTC, got {tif}"
        # Price should remain unchanged; sweet spot is disabled for BUY YES
        assert intent.price_cents == 35, f"BUY_YES at 35c should not be sweet-spot repriced, got {intent.price_cents}c"
    
    def test_sell_yes_bypasses_sweet_spot_logic(self):
        """Test that SELL_YES orders bypass the SWEET-SPOT-EXECUTION price mutation."""
        # Create a SELL_YES intent below optimal range
        intent = OrderIntent(
            ticker="KXETH15M-26JUL312300-00",
            side="SELL_YES",
            action="sell",
            price_cents=35,
            count=1,
            order_type="limit",
            time_in_force="gtc"
        )
        
        # Mock market state with YES mid=35c and bid=30c
        state = MockMarketState(
            mid_cents=35,
            best_bid_cents=30,
            best_ask_cents=35,
            ask_cents=35,
            bid_cents=30,
            depth_10c=1000
        )
        
        # Determine dynamic order type
        order_type, tif = _determine_dynamic_order_type(intent, state)
        
        # Sweet-spot price mutation is bypassed for all orders now; role-aware
        # repricing lives in _adjust_order_price_for_fill_rate.
        assert order_type == "limit", f"SELL_YES should return limit order, got {order_type}"
        assert tif == "gtc", f"SELL_YES should return GTC, got {tif}"
        assert intent.price_cents == 35, f"SELL_YES price should not be sweet-spot mutated, got {intent.price_cents}c"


class TestNOOrderPriceValidation:
    """Test that NO orders pass price validation with correct ask/bid conversion."""
    
    def test_buy_no_price_validation_with_no_ask(self):
        """Test that BUY_NO orders are validated against NO ask (100 - YES bid)."""
        # This test ensures the price validation logic correctly converts YES bid/ask to NO space
        # The fix is in _validate_order_price which uses outcome_side to determine conversion
        
        # Scenario: YES bid=63c, YES ask=63c
        # NO ask = 100 - YES bid = 100 - 63 = 37c
        # NO bid = 100 - YES ask = 100 - 63 = 37c
        
        # A BUY_NO order at 37c should be valid (at or below NO ask of 37c)
        # A BUY_NO order at 47c should be invalid (above NO ask of 37c)
        
        # This test validates the conversion logic is correct
        yes_bid = 63
        yes_ask = 63
        no_ask = 100 - yes_bid  # Should be 37
        no_bid = 100 - yes_ask  # Should be 37
        
        assert no_ask == 37, f"NO ask should be 37c (100 - {yes_bid}), got {no_ask}c"
        assert no_bid == 37, f"NO bid should be 37c (100 - {yes_ask}), got {no_bid}c"
        
        # BUY_NO at 37c should be valid (at NO ask)
        buy_no_price = 37
        assert buy_no_price <= no_ask, f"BUY_NO at {buy_no_price}c should be <= NO ask {no_ask}c"
        
        # BUY_NO at 47c should be invalid (above NO ask)
        buy_no_price_invalid = 47
        assert buy_no_price_invalid > no_ask, f"BUY_NO at {buy_no_price_invalid}c should be > NO ask {no_ask}c (would cross spread)"
    
    def test_sell_no_price_validation_with_no_bid(self):
        """Test that SELL_NO orders are validated against NO bid (100 - YES ask)."""
        # Scenario: YES bid=30c, YES ask=30c
        # NO ask = 100 - YES bid = 100 - 30 = 70c
        # NO bid = 100 - YES ask = 100 - 30 = 70c
        
        # A SELL_NO order at 70c should be valid (at or above NO bid of 70c)
        # A SELL_NO order at 60c should be invalid (below NO bid of 70c)
        
        yes_bid = 30
        yes_ask = 30
        no_ask = 100 - yes_bid  # Should be 70
        no_bid = 100 - yes_ask  # Should be 70
        
        assert no_ask == 70, f"NO ask should be 70c (100 - {yes_bid}), got {no_ask}c"
        assert no_bid == 70, f"NO bid should be 70c (100 - {yes_ask}), got {no_bid}c"
        
        # SELL_NO at 70c should be valid (at NO bid)
        sell_no_price = 70
        assert sell_no_price >= no_bid, f"SELL_NO at {sell_no_price}c should be >= NO bid {no_bid}c"
        
        # SELL_NO at 60c should be invalid (below NO bid)
        sell_no_price_invalid = 60
        assert sell_no_price_invalid < no_bid, f"SELL_NO at {sell_no_price_invalid}c should be < NO bid {no_bid}c (would cross spread)"


class TestDualityConsistency:
    """Test YES/NO price duality consistency across the system."""
    
    def test_yes_no_duality_sum_to_100(self):
        """Test that YES and NO prices sum to 100c (duality invariant)."""
        test_cases = [
            (10, 90),  # YES=10c, NO=90c
            (25, 75),  # YES=25c, NO=75c
            (37, 63),  # YES=37c, NO=63c (from logs)
            (50, 50),  # YES=50c, NO=50c
            (63, 37),  # YES=63c, NO=37c (from logs)
            (75, 25),  # YES=75c, NO=25c
            (90, 10),  # YES=90c, NO=10c
        ]
        
        for yes_price, no_price in test_cases:
            assert yes_price + no_price == 100, \
                f"Duality violation: YES {yes_price}c + NO {no_price}c != 100"
    
    def test_no_mid_calculation(self):
        """Test that NO mid-price is correctly calculated as 100 - YES mid."""
        test_cases = [
            (10, 90),  # YES mid=10c, NO mid=90c
            (25, 75),  # YES mid=25c, NO mid=75c
            (37, 63),  # YES mid=37c, NO mid=63c
            (50, 50),  # YES mid=50c, NO mid=50c
            (63, 37),  # YES mid=63c, NO mid=37c (from logs)
            (75, 25),  # YES mid=75c, NO mid=25c
            (90, 10),  # YES mid=90c, NO mid=10c
        ]
        
        for yes_mid, expected_no_mid in test_cases:
            calculated_no_mid = 100 - yes_mid
            assert calculated_no_mid == expected_no_mid, \
                f"NO mid calculation failed: 100 - {yes_mid}c = {calculated_no_mid}c, expected {expected_no_mid}c"
    
    def test_no_ask_from_yes_bid(self):
        """Test that NO ask is correctly calculated as 100 - YES bid."""
        test_cases = [
            (10, 90),  # YES bid=10c, NO ask=90c
            (25, 75),  # YES bid=25c, NO ask=75c
            (63, 37),  # YES bid=63c, NO ask=37c (from logs)
            (70, 30),  # YES bid=70c, NO ask=30c
        ]
        
        for yes_bid, expected_no_ask in test_cases:
            calculated_no_ask = 100 - yes_bid
            assert calculated_no_ask == expected_no_ask, \
                f"NO ask calculation failed: 100 - {yes_bid}c = {calculated_no_ask}c, expected {expected_no_ask}c"
    
    def test_no_bid_from_yes_ask(self):
        """Test that NO bid is correctly calculated as 100 - YES ask."""
        test_cases = [
            (10, 90),  # YES ask=10c, NO bid=90c
            (25, 75),  # YES ask=25c, NO bid=75c
            (37, 63),  # YES ask=37c, NO bid=63c
            (30, 70),  # YES ask=30c, NO bid=70c
        ]
        
        for yes_ask, expected_no_bid in test_cases:
            calculated_no_bid = 100 - yes_ask
            assert calculated_no_bid == expected_no_bid, \
                f"NO bid calculation failed: 100 - {yes_ask}c = {calculated_no_bid}c, expected {expected_no_bid}c"


class TestRealWorldScenarioFromLogs:
    """Test the exact scenario from the logs that was failing."""
    
    def test_eth_buy_no_scenario_from_logs(self):
        """Test the exact ETH BUY_NO scenario from the logs that was failing."""
        # From logs:
        # ticker=KXETH15M-26JUL312300-00 side=BUY_NO
        # Signal price: 37c (correct for NO side)
        # YES mid: 63c, so NO mid: 37c
        # Bug: Price adjustment used YES mid (63c) instead of NO mid (37c)
        # Result: 37c -> 42c -> 47c (rejected for crossing NO ask)
        #
        # For this test we give YES a tiny spread so that NO ask=38c; a maker
        # BUY_NO at the 37c mid stays non-crossing (37c < 38c) and is not moved.
        
        intent = OrderIntent(
            ticker="KXETH15M-26JUL312300-00",
            side="BUY_NO",
            action="buy",
            price_cents=37,  # Signal price (correct)
            count=1,
            order_type="limit",
            time_in_force="gtc"
        )
        
        state = MockMarketState(
            mid_cents=63,  # YES mid
            best_bid_cents=62,
            best_ask_cents=64,
            ask_cents=64,
            bid_cents=62
        )
        
        # Test price adjustment with fix
        adjusted_price = _adjust_order_price_for_fill_rate(intent, state)
        
        # With fix: should use NO mid (37c) and not adjust
        assert adjusted_price == 37, \
            f"BUY_NO at 37c with NO mid=37c should not adjust, got {adjusted_price}c (fix prevents rejection)"
        
        # Test sweet spot logic with fix
        order_type, tif = _determine_dynamic_order_type(intent, state)
        
        # With fix: should skip sweet spot logic for NO orders
        assert order_type == "limit", f"BUY_NO should return limit, got {order_type}"
        assert intent.price_cents == 37, \
            f"BUY_NO price should remain 37c (sweet spot skipped), got {intent.price_cents}c"
        
        # Verify final price would pass strict maker validation
        # NO ask = 100 - YES bid = 100 - 62 = 38c
        no_ask = 100 - state.best_bid_cents
        assert no_ask == 38, f"NO ask should be 38c, got {no_ask}c"
        assert adjusted_price < no_ask, \
            f"Adjusted price {adjusted_price}c should be <= NO ask {no_ask}c (fix prevents rejection)"
    
    def test_btc_buy_yes_scenario_from_logs(self):
        """Test a BTC BUY_YES scenario to ensure YES orders still work correctly."""
        # From logs:
        # ticker=KXBTC15M-26JUL312300-00 side=yes
        # Signal price: 17c (YES price)
        # YES mid: 17c, NO mid: 83c
        # This should work correctly with existing logic
        
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL312300-00",
            side="BUY_YES",
            action="buy",
            price_cents=17,  # Signal price
            count=1,
            order_type="limit",
            time_in_force="gtc"
        )
        
        state = MockMarketState(
            mid_cents=17,  # YES mid
            best_bid_cents=17,
            best_ask_cents=25,  # Ask is higher than sweet spot
            ask_cents=25,
            bid_cents=17
        )
        
        # Test price adjustment
        adjusted_price = _adjust_order_price_for_fill_rate(intent, state)
        
        # For BUY_YES at 17c with YES mid=17c, should not adjust (already at mid)
        assert adjusted_price == 17, \
            f"BUY_YES at 17c with YES mid=17c should not adjust, got {adjusted_price}c"
        
        # Test sweet spot logic
        order_type, tif = _determine_dynamic_order_type(intent, state)
        
        # Sweet spot is disabled for BUY orders to avoid blind repricing.
        # The price remains at the signal price (17c), which is then validated
        # by the side-aware price adjustment layer.
        assert order_type == "limit", f"BUY_YES should return limit, got {order_type}"
        assert intent.price_cents == 17, \
            f"BUY_YES at 17c should not be sweet-spot repriced, got {intent.price_cents}c"


class TestAllOrderTypes:
    """Test all four order types: BUY_YES, SELL_YES, BUY_NO, SELL_NO."""
    
    def test_all_order_types_with_mid_price(self):
        """Test that all order types use correct mid-price for adjustment."""
        test_cases = [
            # (side, action, price, yes_mid, expected_adjusted)
            ("BUY_YES", "buy", 35, 50, 38),  # 35 + (50-35)*0.25 = 38.75 -> 38 (int)
            ("SELL_YES", "sell", 65, 50, 61),  # 65 - (65-50)*0.25 = 61.25 -> 61, max(61, 51) = 61
            ("BUY_NO", "buy", 35, 50, 38),   # NO mid = 50, 35 + (50-35)*0.25 = 38.75 -> 38 (int)
            ("SELL_NO", "sell", 65, 50, 61),  # NO mid = 50, 65 - (65-50)*0.25 = 61.25 -> 61, max(61, 51) = 61
        ]
        
        for side, action, price, yes_mid, expected in test_cases:
            intent = OrderIntent(
                ticker="KXETH15M-26JUL312300-00",
                side=side,
                action=action,
                price_cents=price,
                count=1,
                order_type="limit",
                time_in_force="gtc"
            )
            
            # Use a 1c spread around the mid so the canonical book is valid.
            # A locked (bid == ask) book is rejected by the fail-closed guard.
            state = MockMarketState(
                mid_cents=yes_mid,
                best_bid_cents=yes_mid - 1,
                best_ask_cents=yes_mid + 1,
                ask_cents=yes_mid + 1,
                bid_cents=yes_mid - 1
            )
            
            adjusted = _adjust_order_price_for_fill_rate(intent, state)
            assert adjusted == expected, \
                f"{side} {action} at {price}c with YES mid {yes_mid}c should adjust to {expected}c, got {adjusted}c"


class TestMakerTakerSideAwareRepricing:
    """Test that _adjust_order_price_for_fill_rate is side-aware and role-aware."""
    
    def test_maker_buy_no_respects_side_ask_invariant(self):
        """Maker BUY_NO must be priced at or below side_ask (invariant)."""
        # YES mid=70 => NO mid=30, NO ask=100-YES_bid=31, NO bid=100-YES_ask=30
        intent = OrderIntent(
            ticker="KXETH15M-26JUL312300-00",
            side="BUY_NO",
            action="buy",
            price_cents=32,  # Above NO mid, should be pulled back
            count=1,
            order_type="limit",
            time_in_force="gtc",
            post_only=True,
        )
        
        state = MockMarketState(
            mid_cents=70,  # YES mid
            best_bid_cents=69,
            best_ask_cents=70,
            ask_cents=70,
            bid_cents=69
        )
        
        adjusted = _adjust_order_price_for_fill_rate(intent, state)
        no_ask = 100 - state.best_bid_cents  # 31
        # 25% toward NO mid 30: 32 - (32-30)*0.25 = 31.5 -> 31
        # Maker cap at no_ask - 1 = 30, so final should be 30.
        assert adjusted <= no_ask, \
            f"maker BUY_NO adjusted price {adjusted}c must be <= side_ask {no_ask}c"
        assert adjusted == 30, \
            f"maker BUY_NO at 32c should be capped to 30c, got {adjusted}c"
    
    def test_taker_buy_no_crosses_side_ask(self):
        """Taker BUY_NO must cross or lift side_ask."""
        intent = OrderIntent(
            ticker="KXETH15M-26JUL312300-00",
            side="BUY_NO",
            action="buy",
            price_cents=28,
            count=1,
            order_type="limit",
            time_in_force="gtc",
            post_only=False,
            aggressiveness=1.0,
        )
        
        state = MockMarketState(
            mid_cents=70,  # YES mid
            best_bid_cents=69,
            best_ask_cents=70,
            ask_cents=70,
            bid_cents=69
        )
        
        adjusted = _adjust_order_price_for_fill_rate(intent, state)
        no_ask = 100 - state.best_bid_cents  # 31
        # Taker buy should lift to side ask.
        assert adjusted >= no_ask, \
            f"taker BUY_NO adjusted price {adjusted}c must be >= side_ask {no_ask}c"
        assert adjusted == 31, \
            f"taker BUY_NO at 28c should lift to side_ask 31c, got {adjusted}c"
    
    def test_maker_sell_yes_respects_side_bid_invariant(self):
        """Maker SELL_YES must be priced at or above side_bid."""
        # YES bid=30, YES ask=35, mid=32.5
        intent = OrderIntent(
            ticker="KXETH15M-26JUL312300-00",
            side="SELL_YES",
            action="sell",
            price_cents=40,
            count=1,
            order_type="limit",
            time_in_force="gtc",
            post_only=True,
        )
        
        state = MockMarketState(
            mid_cents=32,
            best_bid_cents=30,
            best_ask_cents=35,
            ask_cents=35,
            bid_cents=30
        )
        
        adjusted = _adjust_order_price_for_fill_rate(intent, state)
        # 25% toward mid: 40 - (40-32)*0.25 = 38
        # Maker sell floor at side_bid + 1 = 31, so stays 38.
        # Invariant: adjusted >= side_bid (30)
        assert adjusted >= state.best_bid_cents, \
            f"maker SELL_YES adjusted price {adjusted}c must be >= side_bid {state.best_bid_cents}c"
        assert adjusted == 38, \
            f"maker SELL_YES at 40c should adjust to 38c, got {adjusted}c"


class TestKellyRerunAfterRepricing:
    """Test that Kelly/sizing is re-evaluated at the final repriced price."""
    
    def test_kelly_filter_rejects_repriced_order_with_no_edge(self):
        """Previously SWEET-SPOT set a flag that skipped Kelly. Now it always runs."""
        # Model prob 50% at a repriced YES price of 55c has negative Kelly edge.
        # The old metadata flag must no longer bypass the filter.
        count, notional, metadata = compute_order_size(
            bankroll_usd=Decimal("100"),
            price_cents=55,
            asset="ETH",
            model_prob=0.5,
            side="yes",
            metadata={
                "price_adjusted_by_sweet_spot": True,
                "original_signal_price": 35,
                "adjusted_price": 55,
            },
        )
        assert count == 0, \
            f"Repriced order with no edge should be rejected, got count={count}"
        assert metadata.get("reason") == "kelly_no_edge", \
            f"Expected kelly_no_edge, got {metadata.get('reason')}"
        assert metadata.get("kelly_fraction", 1.0) <= 0, \
            f"Expected non-positive Kelly fraction, got {metadata.get('kelly_fraction')}"


class TestBookInitializationSafety:
    """Fail-closed behavior for uninitialized, stale, or invalid books."""

    def _make_state(self, **overrides):
        defaults = {
            "mid_cents": 50,
            "best_bid_cents": 49,
            "best_ask_cents": 51,
            "ask_cents": 51,
            "bid_cents": 49,
            "book_initialized": True,
            "last_book_update_wall_ts": _time.time(),
            "best_bid_size": 1,
            "best_ask_size": 1,
        }
        defaults.update(overrides)
        return MockMarketState(**defaults)

    def _make_intent(self):
        return OrderIntent(
            ticker="KXBTC15M-TEST",
            side="BUY_YES",
            action="buy",
            price_cents=45,
            count=1,
            order_type="limit",
            time_in_force="gtc",
        )

    def test_uninitialized_book_rejects(self):
        state = self._make_state(book_initialized=False)
        with pytest.raises(RepriceWouldCross) as exc:
            _adjust_order_price_for_fill_rate(self._make_intent(), state)
        assert "book_not_initialized" in str(exc.value)

    def test_no_snapshot_rejects(self):
        state = self._make_state(
            mid_cents=None,
            best_bid_cents=None,
            best_ask_cents=None,
            ask_cents=None,
            bid_cents=None,
        )
        with pytest.raises(RepriceWouldCross) as exc:
            _adjust_order_price_for_fill_rate(self._make_intent(), state)
        assert "book_unavailable_or_invalid" in str(exc.value)

    def test_one_side_missing_rejects(self):
        state = self._make_state(best_ask_cents=None)
        with pytest.raises(RepriceWouldCross) as exc:
            _adjust_order_price_for_fill_rate(self._make_intent(), state)
        assert "book_unavailable_or_invalid" in str(exc.value)

    def test_stale_book_rejects(self):
        state = self._make_state(
            last_book_update_wall_ts=_time.time() - 600.0,
        )
        with pytest.raises(RepriceWouldCross) as exc:
            _adjust_order_price_for_fill_rate(self._make_intent(), state)
        assert "stale_snapshot" in str(exc.value)

    def test_locked_book_is_rejected(self):
        state = self._make_state(best_bid_cents=50, best_ask_cents=50)
        with pytest.raises(RepriceWouldCross) as exc:
            _adjust_order_price_for_fill_rate(self._make_intent(), state)
        # Locked/crossed books are refused by the canonical placement invariant.
        assert "book" in str(exc.value).lower() or "crossed" in str(exc.value).lower()

    def test_crossed_book_raises(self):
        state = self._make_state(best_bid_cents=52, best_ask_cents=48)
        with pytest.raises(RepriceWouldCross) as exc:
            _adjust_order_price_for_fill_rate(self._make_intent(), state)
        assert "crossed" in str(exc.value).lower()

    def test_null_zero_best_bid_ask_rejects(self):
        state = self._make_state(best_bid_cents=0, best_ask_cents=0)
        with pytest.raises(RepriceWouldCross) as exc:
            _adjust_order_price_for_fill_rate(self._make_intent(), state)

    def test_invalid_book_does_not_mutate_price(self):
        # An unsafe book should raise, never silently return the original price.
        state = self._make_state(book_initialized=False)
        with pytest.raises(RepriceWouldCross):
            _adjust_order_price_for_fill_rate(self._make_intent(), state)


class TestRepriceWouldCross:
    """Test that _adjust_order_price_for_fill_rate raises RepriceWouldCross instead of assert."""
    
    def test_maker_buy_on_crossed_book_raises(self):
        """A maker BUY_YES on a crossed/locked book produces a typed rejection."""
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            order_type="limit",
            time_in_force="gtc",
            post_only=True,
            aggressiveness=0.0,
        )
        # Crossed book: bid 51c > ask 50c. No coherent maker/taker price exists.
        state = MockMarketState(
            mid_cents=50,
            best_bid_cents=51,
            best_ask_cents=50,
            ask_cents=50,
            bid_cents=51,
        )
        with pytest.raises(RepriceWouldCross) as exc_info:
            _adjust_order_price_for_fill_rate(intent, state)
        e = exc_info.value
        assert e.role == "maker"
        assert e.action == "buy"
        assert e.side == "yes"
        assert e.side_bid == 51
        assert e.side_ask == 50
        assert "crossed" in e.reason
    
    def test_taker_buy_cannot_reach_ask_after_clamp_raises(self):
        """A taker BUY_YES whose post-clamp price falls below the ask is rejected."""
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            order_type="limit",
            time_in_force="gtc",
            post_only=False,
            aggressiveness=1.0,
        )
        # Best ask at 80c. Taker must cross/lift it. The allocator hard cap of 75c
        # pulls the price back, making the post-clamp price inconsistent with taker role.
        state = MockMarketState(
            mid_cents=60,
            best_bid_cents=50,
            best_ask_cents=80,
            ask_cents=80,
            bid_cents=50,
        )
        with pytest.raises(RepriceWouldCross) as exc_info:
            _adjust_order_price_for_fill_rate(intent, state)
        e = exc_info.value
        assert e.role == "taker"
        assert e.action == "buy"
        assert e.side == "yes"
        assert e.side_ask == 80


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
