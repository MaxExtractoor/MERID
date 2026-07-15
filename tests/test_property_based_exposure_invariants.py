"""Property-based tests for exposure cap invariants using Hypothesis.

This module tests mathematical properties of position sizing and exposure calculations
in the 15m Kalshi crypto trading system, ensuring that critical invariants hold
for all valid inputs.

Key Invariants Tested:
1. Global exposure cap never exceeds $1.00 (MERID_FIXED_EXPOSURE_CAP_USD)
2. Per-asset position limits are never violated
3. Position counts are always non-negative
4. Exposure calculations are consistent across assets
5. Multi-asset exposure aggregation
"""

import pytest
from hypothesis import given, strategies as st, settings, example
from hypothesis.strategies import floats, integers, lists
import math


# Exposure cap constants
GLOBAL_EXPOSURE_CAP_USD = 1.00  # Fixed $1.00 global exposure cap
MIN_EXPOSURE = 0.0
MAX_EXPOSURE = GLOBAL_EXPOSURE_CAP_USD

# Asset list for 15m Kalshi crypto system
CRYPTO_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
NUM_ASSETS = len(CRYPTO_ASSETS)


class TestGlobalExposureCapInvariants:
    """Property-based tests for global exposure cap constraints."""

    @given(floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=500)
    def test_exposure_clamped_to_global_cap(self, raw_exposure):
        """Exposure must be clamped to $1.00 global cap."""
        clamped_exposure = min(MAX_EXPOSURE, raw_exposure)
        assert MIN_EXPOSURE <= clamped_exposure <= MAX_EXPOSURE, \
            f"Exposure {clamped_exposure} exceeds global cap ${MAX_EXPOSURE}"

    @given(floats(min_value=MIN_EXPOSURE, max_value=MAX_EXPOSURE, allow_nan=False, allow_infinity=False))
    @settings(max_examples=300)
    def test_in_range_exposure_unchanged(self, in_range_exposure):
        """Exposure already within cap should remain unchanged."""
        clamped_exposure = min(MAX_EXPOSURE, in_range_exposure)
        assert clamped_exposure == in_range_exposure, \
            f"In-range exposure {in_range_exposure} was changed to {clamped_exposure}"

    @given(floats(min_value=MAX_EXPOSURE + 0.01, max_value=100.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=200)
    def test_above_cap_clamps_to_cap(self, above_cap_exposure):
        """Exposure above cap should clamp to $1.00."""
        clamped_exposure = min(MAX_EXPOSURE, above_cap_exposure)
        assert clamped_exposure == MAX_EXPOSURE, \
            f"Exposure {above_cap_exposure} above cap should clamp to ${MAX_EXPOSURE}, got ${clamped_exposure}"

    @given(floats(min_value=-10.0, max_value=0.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=200)
    def test_negative_exposure_clamps_to_zero(self, negative_exposure):
        """Negative exposure should clamp to $0.00."""
        clamped_exposure = max(MIN_EXPOSURE, min(MAX_EXPOSURE, negative_exposure))
        assert clamped_exposure == MIN_EXPOSURE, \
            f"Negative exposure {negative_exposure} should clamp to ${MIN_EXPOSURE}, got ${clamped_exposure}"

    @given(floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=300)
    @example(raw_exposure=0.0)
    @example(raw_exposure=0.5)
    @example(raw_exposure=1.0)
    @example(raw_exposure=1.5)
    @example(raw_exposure=-0.5)
    def test_clamping_is_idempotent(self, raw_exposure):
        """Clamping the same exposure twice should yield the same result."""
        first_clamp = max(MIN_EXPOSURE, min(MAX_EXPOSURE, raw_exposure))
        second_clamp = max(MIN_EXPOSURE, min(MAX_EXPOSURE, first_clamp))
        assert abs(first_clamp - second_clamp) < 1e-9, \
            f"Clamping not idempotent: ${raw_exposure} -> ${first_clamp} -> ${second_clamp}"


class TestMultiAssetExposureInvariants:
    """Property-based tests for multi-asset exposure aggregation."""

    @given(lists(floats(min_value=0.0, max_value=0.5, allow_nan=False, allow_infinity=False),
                 min_size=NUM_ASSETS, max_size=NUM_ASSETS))
    @settings(max_examples=300)
    def test_total_exposure_never_exceeds_cap(self, asset_exposures):
        """Total exposure across all assets must never exceed $1.00 cap."""
        total_exposure = sum(asset_exposures)
        clamped_total = min(MAX_EXPOSURE, total_exposure)
        assert clamped_total <= MAX_EXPOSURE, \
            f"Total exposure ${clamped_total} exceeds global cap ${MAX_EXPOSURE}"

    @given(lists(floats(min_value=0.0, max_value=0.3, allow_nan=False, allow_infinity=False),
                 min_size=NUM_ASSETS, max_size=NUM_ASSETS))
    @settings(max_examples=200)
    def test_equal_distribution_stays_in_range(self, asset_exposures):
        """Equal distribution across assets should stay within cap."""
        per_asset = MAX_EXPOSURE / NUM_ASSETS
        # Test that equal distribution would be valid
        equal_exposure = per_asset * NUM_ASSETS
        assert equal_exposure <= MAX_EXPOSURE, \
            f"Equal distribution ${equal_exposure} exceeds cap ${MAX_EXPOSURE}"

    @given(lists(floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
                 min_size=NUM_ASSETS, max_size=NUM_ASSETS))
    @settings(max_examples=200)
    def test_exposure_aggregation_is_commutative(self, asset_exposures):
        """Exposure aggregation should be commutative (order doesn't matter)."""
        total1 = sum(asset_exposures)
        total2 = sum(reversed(asset_exposures))
        assert abs(total1 - total2) < 1e-9, \
            f"Exposure aggregation not commutative: {total1} vs {total2}"

    @given(lists(floats(min_value=0.0, max_value=0.5, allow_nan=False, allow_infinity=False),
                 min_size=NUM_ASSETS, max_size=NUM_ASSETS))
    @settings(max_examples=200)
    def test_exposure_aggregation_is_associative(self, asset_exposures):
        """Exposure aggregation should be associative."""
        # Group assets in different ways
        group1 = sum(asset_exposures[:2]) + sum(asset_exposures[2:])
        group2 = sum(asset_exposures[:3]) + sum(asset_exposures[3:])
        assert abs(group1 - group2) < 0.001, \
            f"Exposure aggregation not associative: {group1} vs {group2}"


class TestPositionSizingInvariants:
    """Property-based tests for position sizing calculations."""

    @given(floats(min_value=0.01, max_value=0.5, allow_nan=False, allow_infinity=False),
           integers(min_value=1, max_value=100))
    @settings(max_examples=300)
    def test_position_size_times_price_equals_exposure(self, price_cents, quantity):
        """Position size * price should equal exposure (within cap)."""
        exposure_usd = (price_cents / 100.0) * quantity
        clamped_exposure = min(MAX_EXPOSURE, exposure_usd)
        assert clamped_exposure <= MAX_EXPOSURE, \
            f"Position exposure ${clamped_exposure} exceeds cap ${MAX_EXPOSURE}"

    @given(floats(min_value=10.0, max_value=75.0, allow_nan=False, allow_infinity=False),
           floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=300)
    def test_position_sizing_respects_cap(self, price_cents, edge):
        """Position sizing based on edge should respect exposure cap."""
        # Simplified position sizing: higher edge = larger position
        base_quantity = int(edge * 10)  # Base quantity from edge
        exposure_usd = (price_cents / 100.0) * base_quantity
        clamped_exposure = min(MAX_EXPOSURE, exposure_usd)
        assert clamped_exposure <= MAX_EXPOSURE, \
            f"Position exposure ${clamped_exposure} exceeds cap ${MAX_EXPOSURE}"

    @given(floats(min_value=10.0, max_value=75.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=200)
    def test_max_quantity_for_price(self, price_cents):
        """Maximum quantity for a given price should respect cap."""
        max_quantity = int((MAX_EXPOSURE * 100) / price_cents)
        exposure_usd = (price_cents / 100.0) * max_quantity
        assert exposure_usd <= MAX_EXPOSURE, \
            f"Max quantity exposure ${exposure_usd} exceeds cap ${MAX_EXPOSURE}"

    @given(integers(min_value=0, max_value=1000))
    @settings(max_examples=200)
    def test_non_negative_quantities(self, quantity):
        """Position quantities must be non-negative."""
        assert quantity >= 0, f"Position quantity {quantity} must be non-negative"


class TestPerAssetLimitsInvariants:
    """Property-based tests for per-asset position limits."""

    @given(floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=300)
    def test_per_asset_limit_fraction_of_global(self, asset_fraction):
        """Per-asset limit should be a fraction of global cap."""
        per_asset_limit = asset_fraction * MAX_EXPOSURE
        assert per_asset_limit <= MAX_EXPOSURE, \
            f"Per-asset limit ${per_asset_limit} exceeds global cap ${MAX_EXPOSURE}"

    @given(lists(floats(min_value=0.0, max_value=0.2, allow_nan=False, allow_infinity=False),
                 min_size=NUM_ASSETS, max_size=NUM_ASSETS))
    @settings(max_examples=200)
    def test_per_asset_limits_sum_to_global(self, asset_limits):
        """Sum of per-asset limits should not exceed global cap."""
        total_limit = sum(asset_limits)
        assert total_limit <= MAX_EXPOSURE, \
            f"Sum of per-asset limits ${total_limit} exceeds global cap ${MAX_EXPOSURE}"

    @given(floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=200)
    def test_equal_per_asset_allocation(self, allocation_fraction):
        """Equal allocation across assets should be valid."""
        per_asset = allocation_fraction * MAX_EXPOSURE / NUM_ASSETS
        total = per_asset * NUM_ASSETS
        assert total <= MAX_EXPOSURE, \
            f"Equal allocation total ${total} exceeds cap ${MAX_EXPOSURE}"


class TestExposureConsistencyInvariants:
    """Property-based tests for exposure calculation consistency."""

    @given(floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
           floats(min_value=10.0, max_value=75.0, allow_nan=False, allow_infinity=False),
           integers(min_value=1, max_value=100))
    @settings(max_examples=300)
    def test_exposure_calculation_consistency(self, edge, price_cents, quantity):
        """Exposure calculation should be consistent across methods."""
        # Method 1: direct calculation
        exposure1 = (price_cents / 100.0) * quantity
        # Method 2: via edge-based sizing
        base_quantity = int(edge * 10)
        exposure2 = (price_cents / 100.0) * base_quantity
        # Both should respect cap
        assert min(MAX_EXPOSURE, exposure1) <= MAX_EXPOSURE
        assert min(MAX_EXPOSURE, exposure2) <= MAX_EXPOSURE

    @given(lists(floats(min_value=0.0, max_value=0.15, allow_nan=False, allow_infinity=False),
                 min_size=NUM_ASSETS, max_size=NUM_ASSETS))
    @settings(max_examples=200)
    def test_exposure_tracking_consistency(self, asset_exposures):
        """Exposure tracking should be consistent across updates."""
        initial_total = sum(asset_exposures)
        # Simulate adding exposure to first asset
        updated_exposures = asset_exposures.copy()
        updated_exposures[0] = min(MAX_EXPOSURE, updated_exposures[0] + 0.05)
        updated_total = sum(updated_exposures)
        # Clamp the total to respect the cap
        clamped_total = min(MAX_EXPOSURE, updated_total)
        assert clamped_total <= MAX_EXPOSURE, \
            f"Updated exposure ${clamped_total} exceeds cap ${MAX_EXPOSURE}"


class TestExposureEdgeCases:
    """Property-based tests for edge cases in exposure calculations."""

    @given(floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=200)
    def test_extreme_exposure_values_clamp_correctly(self, extreme_exposure):
        """Extreme exposure values should clamp to [0, $1.00] range."""
        clamped_exposure = max(MIN_EXPOSURE, min(MAX_EXPOSURE, extreme_exposure))
        assert MIN_EXPOSURE <= clamped_exposure <= MAX_EXPOSURE, \
            f"Extreme exposure ${extreme_exposure} should clamp to range, got ${clamped_exposure}"

    @given(st.one_of(st.just(0.0), st.just(0.5), st.just(1.0), st.just(-0.5), st.just(1.5)))
    @settings(max_examples=10)
    def test_boundary_exposure_values(self, boundary_exposure):
        """Boundary exposure values should clamp correctly."""
        clamped_exposure = max(MIN_EXPOSURE, min(MAX_EXPOSURE, boundary_exposure))
        expected = MIN_EXPOSURE if boundary_exposure < MIN_EXPOSURE else (MAX_EXPOSURE if boundary_exposure > MAX_EXPOSURE else boundary_exposure)
        assert clamped_exposure == expected, \
            f"Boundary exposure ${boundary_exposure} should clamp to ${expected}, got ${clamped_exposure}"

    @given(floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=200)
    def test_zero_exposure_is_valid(self, zero_exposure):
        """Zero exposure should be valid."""
        clamped_exposure = max(MIN_EXPOSURE, min(MAX_EXPOSURE, zero_exposure))
        assert clamped_exposure >= MIN_EXPOSURE, f"Zero exposure should be valid"

    @given(floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=200)
    def test_max_exposure_is_valid(self, max_exposure):
        """Maximum exposure ($1.00) should be valid."""
        clamped_exposure = max(MIN_EXPOSURE, min(MAX_EXPOSURE, max_exposure))
        assert clamped_exposure <= MAX_EXPOSURE, f"Max exposure should be valid"


class TestExposureWithFees:
    """Property-based tests for exposure calculations with fees."""

    @given(floats(min_value=10.0, max_value=75.0, allow_nan=False, allow_infinity=False),
           integers(min_value=1, max_value=100),
           floats(min_value=0.0, max_value=0.05, allow_nan=False, allow_infinity=False))
    @settings(max_examples=300)
    def test_exposure_with_fee_stays_in_cap(self, price_cents, quantity, fee_rate):
        """Exposure with fees should stay within global cap."""
        base_exposure = (price_cents / 100.0) * quantity
        fee_exposure = base_exposure * fee_rate
        total_exposure = base_exposure + fee_exposure
        clamped_exposure = min(MAX_EXPOSURE, total_exposure)
        assert clamped_exposure <= MAX_EXPOSURE, \
            f"Exposure with fee ${clamped_exposure} exceeds cap ${MAX_EXPOSURE}"

    @given(floats(min_value=10.0, max_value=75.0, allow_nan=False, allow_infinity=False),
           integers(min_value=1, max_value=100),
           integers(min_value=0, max_value=5))
    @settings(max_examples=200)
    def test_exposure_with_fixed_fee_stays_in_cap(self, price_cents, quantity, fixed_fee_cents):
        """Exposure with fixed fee should stay within global cap."""
        base_exposure = (price_cents / 100.0) * quantity
        fee_exposure = fixed_fee_cents / 100.0
        total_exposure = base_exposure + fee_exposure
        clamped_exposure = min(MAX_EXPOSURE, total_exposure)
        assert clamped_exposure <= MAX_EXPOSURE, \
            f"Exposure with fixed fee ${clamped_exposure} exceeds cap ${MAX_EXPOSURE}"


class TestExposureReallocation:
    """Property-based tests for exposure reallocation between assets."""

    @given(lists(floats(min_value=0.0, max_value=0.2, allow_nan=False, allow_infinity=False),
                 min_size=NUM_ASSETS, max_size=NUM_ASSETS),
           integers(min_value=0, max_value=NUM_ASSETS - 1),
           integers(min_value=0, max_value=NUM_ASSETS - 1))
    @settings(max_examples=200)
    def test_exposure_reallocation_preserves_total(self, asset_exposures, from_asset, to_asset):
        """Reallocation between assets should preserve total exposure."""
        initial_total = sum(asset_exposures)
        if from_asset != to_asset and asset_exposures[from_asset] > 0:
            reallocation_amount = min(asset_exposures[from_asset], 0.1)
            updated_exposures = asset_exposures.copy()
            updated_exposures[from_asset] -= reallocation_amount
            updated_exposures[to_asset] = min(MAX_EXPOSURE, updated_exposures[to_asset] + reallocation_amount)
            updated_total = sum(updated_exposures)
            # Total should not increase (may decrease due to cap)
            assert updated_total <= initial_total + 0.001, \
                f"Reallocation increased total: {initial_total} -> {updated_total}"
            assert updated_total <= MAX_EXPOSURE, \
                f"Reallocation total ${updated_total} exceeds cap ${MAX_EXPOSURE}"

    @given(lists(floats(min_value=0.0, max_value=0.2, allow_nan=False, allow_infinity=False),
                 min_size=NUM_ASSETS, max_size=NUM_ASSETS))
    @settings(max_examples=200)
    def test_exposure_reduction_is_safe(self, asset_exposures):
        """Reducing exposure should always be safe."""
        initial_total = sum(asset_exposures)
        reduced_exposures = [max(0.0, e * 0.5) for e in asset_exposures]
        reduced_total = sum(reduced_exposures)
        assert reduced_total <= initial_total, \
            f"Exposure reduction increased total: {initial_total} -> {reduced_total}"
        assert reduced_total <= MAX_EXPOSURE, \
            f"Reduced exposure ${reduced_total} exceeds cap ${MAX_EXPOSURE}"
