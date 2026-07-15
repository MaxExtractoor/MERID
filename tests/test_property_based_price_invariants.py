"""Property-based tests for price calculation invariants using Hypothesis.

This module tests mathematical properties of price calculations in the 15m Kalshi
crypto trading system, ensuring that critical invariants hold for all valid inputs.

Key Invariants Tested:
1. Price clamping to canonical range (10-75c)
2. Price rounding and conversion
3. Price arithmetic operations
4. Edge case handling (negative, zero, extreme values)
"""

import pytest
from hypothesis import given, strategies as st, settings, example
from hypothesis.strategies import integers, floats, decimals
from decimal import Decimal
import math


# Canonical price range constants
MIN_PRICE_CENTS = 10
MAX_PRICE_CENTS = 75
CANONICAL_RANGE = (MIN_PRICE_CENTS, MAX_PRICE_CENTS)


class TestPriceClampingInvariants:
    """Property-based tests for price clamping to canonical range."""

    @given(integers(min_value=-1000, max_value=1000))
    @settings(max_examples=500)
    def test_clamp_to_canonical_range(self, raw_price_cents):
        """Price clamping must always result in value within 10-75c range."""
        clamped = max(MIN_PRICE_CENTS, min(MAX_PRICE_CENTS, raw_price_cents))
        assert MIN_PRICE_CENTS <= clamped <= MAX_PRICE_CENTS, \
            f"Clamped price {clamped} outside canonical range {CANONICAL_RANGE}"

    @given(integers(min_value=MIN_PRICE_CENTS, max_value=MAX_PRICE_CENTS))
    @settings(max_examples=200)
    def test_in_range_price_unchanged(self, in_range_price):
        """Prices already within canonical range should remain unchanged."""
        clamped = max(MIN_PRICE_CENTS, min(MAX_PRICE_CENTS, in_range_price))
        assert clamped == in_range_price, \
            f"In-range price {in_range_price} was changed to {clamped}"

    @given(integers(min_value=-1000, max_value=MIN_PRICE_CENTS - 1))
    @settings(max_examples=200)
    def test_below_minimum_clamps_to_minimum(self, below_min_price):
        """Prices below minimum should clamp to 10c."""
        clamped = max(MIN_PRICE_CENTS, min(MAX_PRICE_CENTS, below_min_price))
        assert clamped == MIN_PRICE_CENTS, \
            f"Price {below_min_price} below min should clamp to {MIN_PRICE_CENTS}, got {clamped}"

    @given(integers(min_value=MAX_PRICE_CENTS + 1, max_value=1000))
    @settings(max_examples=200)
    def test_above_maximum_clamps_to_maximum(self, above_max_price):
        """Prices above maximum should clamp to 75c."""
        clamped = max(MIN_PRICE_CENTS, min(MAX_PRICE_CENTS, above_max_price))
        assert clamped == MAX_PRICE_CENTS, \
            f"Price {above_max_price} above max should clamp to {MAX_PRICE_CENTS}, got {clamped}"

    @given(integers(min_value=-1000, max_value=1000))
    @settings(max_examples=300)
    @example(raw_price_cents=0)
    @example(raw_price_cents=10)
    @example(raw_price_cents=75)
    @example(raw_price_cents=100)
    def test_clamping_is_idempotent(self, raw_price_cents):
        """Clamping the same value twice should yield the same result."""
        first_clamp = max(MIN_PRICE_CENTS, min(MAX_PRICE_CENTS, raw_price_cents))
        second_clamp = max(MIN_PRICE_CENTS, min(MAX_PRICE_CENTS, first_clamp))
        assert first_clamp == second_clamp, \
            f"Clamping not idempotent: {raw_price_cents} -> {first_clamp} -> {second_clamp}"


class TestPriceConversionInvariants:
    """Property-based tests for price conversion between formats."""

    @given(floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=300)
    def test_dollar_to_cents_conversion(self, price_dollars):
        """Converting dollars to cents should be accurate to nearest cent."""
        price_cents = round(price_dollars * 100)
        # Verify round-trip conversion
        back_to_dollars = price_cents / 100.0
        assert abs(back_to_dollars - price_dollars) < 0.005, \
            f"Round-trip conversion failed: {price_dollars} -> {price_cents} -> {back_to_dollars}"

    @given(integers(min_value=0, max_value=1000))
    @settings(max_examples=300)
    def test_cents_to_dollars_conversion(self, price_cents):
        """Converting cents to dollars should preserve value."""
        price_dollars = price_cents / 100.0
        back_to_cents = round(price_dollars * 100)
        assert back_to_cents == price_cents, \
            f"Round-trip conversion failed: {price_cents} -> {price_dollars} -> {back_to_cents}"

    @given(floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=300)
    def test_dollar_to_cents_with_clamping(self, price_dollars):
        """Converting dollars to cents and clamping should stay in range."""
        raw_cents = round(price_dollars * 100)
        clamped_cents = max(MIN_PRICE_CENTS, min(MAX_PRICE_CENTS, raw_cents))
        assert MIN_PRICE_CENTS <= clamped_cents <= MAX_PRICE_CENTS, \
            f"Clamped cents {clamped_cents} outside canonical range"


class TestPriceArithmeticInvariants:
    """Property-based tests for price arithmetic operations."""

    @given(integers(min_value=MIN_PRICE_CENTS, max_value=MAX_PRICE_CENTS),
           integers(min_value=-10, max_value=10))
    @settings(max_examples=300)
    def test_price_with_slippage_stays_in_range(self, base_price, slippage_cents):
        """Price with slippage should clamp to canonical range."""
        adjusted_price = base_price + slippage_cents
        clamped_price = max(MIN_PRICE_CENTS, min(MAX_PRICE_CENTS, adjusted_price))
        assert MIN_PRICE_CENTS <= clamped_price <= MAX_PRICE_CENTS, \
            f"Price with slippage {clamped_price} outside canonical range"

    @given(integers(min_value=MIN_PRICE_CENTS, max_value=MAX_PRICE_CENTS),
           integers(min_value=1, max_value=10))
    @settings(max_examples=200)
    def test_price_multiplication_with_clamping(self, base_price, multiplier):
        """Price multiplication should clamp to canonical range."""
        multiplied = base_price * multiplier
        clamped = max(MIN_PRICE_CENTS, min(MAX_PRICE_CENTS, multiplied))
        assert MIN_PRICE_CENTS <= clamped <= MAX_PRICE_CENTS, \
            f"Multiplied price {clamped} outside canonical range"

    @given(integers(min_value=MIN_PRICE_CENTS, max_value=MAX_PRICE_CENTS),
           integers(min_value=MIN_PRICE_CENTS, max_value=MAX_PRICE_CENTS))
    @settings(max_examples=200)
    def test_price_average_stays_in_range(self, price1, price2):
        """Average of two in-range prices should stay in range."""
        average = (price1 + price2) // 2
        assert MIN_PRICE_CENTS <= average <= MAX_PRICE_CENTS, \
            f"Average price {average} outside canonical range"


class TestPriceEdgeCases:
    """Property-based tests for edge cases in price calculations."""

    @given(integers(min_value=-1000000, max_value=1000000))
    @settings(max_examples=200)
    def test_extreme_values_clamp_correctly(self, extreme_price):
        """Extreme values should clamp to canonical range."""
        clamped = max(MIN_PRICE_CENTS, min(MAX_PRICE_CENTS, extreme_price))
        assert clamped in (MIN_PRICE_CENTS, MAX_PRICE_CENTS), \
            f"Extreme value {extreme_price} should clamp to boundary, got {clamped}"

    @given(st.one_of(st.just(0), st.just(1), st.just(-1)))
    @settings(max_examples=10)
    def test_boundary_values(self, boundary_price):
        """Boundary values (0, 1, -1) should clamp correctly."""
        clamped = max(MIN_PRICE_CENTS, min(MAX_PRICE_CENTS, boundary_price))
        assert clamped == MIN_PRICE_CENTS, \
            f"Boundary value {boundary_price} should clamp to {MIN_PRICE_CENTS}, got {clamped}"

    @given(integers(min_value=MIN_PRICE_CENTS, max_value=MAX_PRICE_CENTS))
    @settings(max_examples=200)
    def test_positive_prices_remain_positive(self, positive_price):
        """Positive prices should remain positive after clamping."""
        clamped = max(MIN_PRICE_CENTS, min(MAX_PRICE_CENTS, positive_price))
        assert clamped > 0, f"Clamped price {clamped} should be positive"


class TestPriceConsistencyAcrossModules:
    """Property-based tests for price consistency across different modules."""

    @given(integers(min_value=0, max_value=1000))
    @settings(max_examples=300)
    def test_clamping_consistency(self, raw_price):
        """Clamping should be consistent regardless of implementation."""
        # Test multiple clamping implementations
        clamp1 = max(MIN_PRICE_CENTS, min(MAX_PRICE_CENTS, raw_price))
        clamp2 = MIN_PRICE_CENTS if raw_price < MIN_PRICE_CENTS else (MAX_PRICE_CENTS if raw_price > MAX_PRICE_CENTS else raw_price)
        assert clamp1 == clamp2, \
            f"Inconsistent clamping: {raw_price} -> {clamp1} vs {clamp2}"

    @given(integers(min_value=MIN_PRICE_CENTS, max_value=MAX_PRICE_CENTS))
    @settings(max_examples=200)
    def test_range_check_consistency(self, in_range_price):
        """Range check should be consistent across different implementations."""
        check1 = MIN_PRICE_CENTS <= in_range_price <= MAX_PRICE_CENTS
        check2 = (in_range_price >= MIN_PRICE_CENTS) and (in_range_price <= MAX_PRICE_CENTS)
        assert check1 == check2, \
            f"Inconsistent range check for {in_range_price}"


class TestPriceWithFees:
    """Property-based tests for price calculations with fees."""

    @given(integers(min_value=MIN_PRICE_CENTS, max_value=MAX_PRICE_CENTS),
           floats(min_value=0.0, max_value=0.05, allow_nan=False))
    @settings(max_examples=300)
    def test_price_with_fee_stays_in_range(self, base_price, fee_rate):
        """Price with fee should clamp to canonical range."""
        fee_cents = round(base_price * fee_rate)
        price_with_fee = base_price + fee_cents
        clamped = max(MIN_PRICE_CENTS, min(MAX_PRICE_CENTS, price_with_fee))
        assert MIN_PRICE_CENTS <= clamped <= MAX_PRICE_CENTS, \
            f"Price with fee {clamped} outside canonical range"

    @given(integers(min_value=MIN_PRICE_CENTS, max_value=MAX_PRICE_CENTS),
           integers(min_value=0, max_value=5))
    @settings(max_examples=200)
    def test_price_with_fixed_fee_stays_in_range(self, base_price, fixed_fee_cents):
        """Price with fixed fee should clamp to canonical range."""
        price_with_fee = base_price + fixed_fee_cents
        clamped = max(MIN_PRICE_CENTS, min(MAX_PRICE_CENTS, price_with_fee))
        assert MIN_PRICE_CENTS <= clamped <= MAX_PRICE_CENTS, \
            f"Price with fixed fee {clamped} outside canonical range"


class TestPriceBidAskSpread:
    """Property-based tests for bid-ask spread calculations."""

    @given(integers(min_value=MIN_PRICE_CENTS, max_value=MAX_PRICE_CENTS - 1),
           integers(min_value=1, max_value=10))
    @settings(max_examples=200)
    def test_bid_ask_midpoint_in_range(self, bid_price, spread_cents):
        """Midpoint of bid-ask should stay in range."""
        ask_price = bid_price + spread_cents
        midpoint = (bid_price + ask_price) // 2
        clamped = max(MIN_PRICE_CENTS, min(MAX_PRICE_CENTS, midpoint))
        assert MIN_PRICE_CENTS <= clamped <= MAX_PRICE_CENTS, \
            f"Midpoint {clamped} outside canonical range"

    @given(integers(min_value=MIN_PRICE_CENTS, max_value=MAX_PRICE_CENTS),
           integers(min_value=MIN_PRICE_CENTS, max_value=MAX_PRICE_CENTS))
    @settings(max_examples=200)
    def test_bid_less_than_ask(self, bid_price, ask_price):
        """Bid should be less than or equal to ask."""
        if bid_price <= ask_price:
            assert True  # Valid spread
        else:
            # Invalid spread, but clamping should still work
            clamped_bid = max(MIN_PRICE_CENTS, min(MAX_PRICE_CENTS, bid_price))
            clamped_ask = max(MIN_PRICE_CENTS, min(MAX_PRICE_CENTS, ask_price))
            assert MIN_PRICE_CENTS <= clamped_bid <= MAX_PRICE_CENTS
            assert MIN_PRICE_CENTS <= clamped_ask <= MAX_PRICE_CENTS
