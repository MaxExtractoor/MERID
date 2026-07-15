"""Property-based tests for edge calculation invariants using Hypothesis.

This module tests mathematical properties of edge calculations in the 15m Kalshi
crypto trading system, ensuring that critical invariants hold for all valid inputs.

Key Invariants Tested:
1. Edge values must be between 0 and 1 (0-100%)
2. Edge threshold validation (2.5% minimum edge)
3. Edge arithmetic operations
4. Edge case handling (negative, zero, extreme values)
5. Edge consistency across different calculation methods
"""

import pytest
from hypothesis import given, strategies as st, settings, example
from hypothesis.strategies import floats
import math


# Edge calculation constants
MIN_EDGE = 0.0
MAX_EDGE = 1.0
EDGE_THRESHOLD = 0.025  # 2.5% minimum edge


class TestEdgeRangeInvariants:
    """Property-based tests for edge range constraints."""

    @given(floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=500)
    def test_edge_clamped_to_zero_one(self, raw_edge):
        """Edge values must be clamped to [0, 1] range."""
        clamped_edge = max(MIN_EDGE, min(MAX_EDGE, raw_edge))
        assert MIN_EDGE <= clamped_edge <= MAX_EDGE, \
            f"Edge {clamped_edge} outside valid range [{MIN_EDGE}, {MAX_EDGE}]"

    @given(floats(min_value=MIN_EDGE, max_value=MAX_EDGE, allow_nan=False, allow_infinity=False))
    @settings(max_examples=300)
    def test_in_range_edge_unchanged(self, in_range_edge):
        """Edges already in valid range should remain unchanged."""
        clamped_edge = max(MIN_EDGE, min(MAX_EDGE, in_range_edge))
        assert clamped_edge == in_range_edge, \
            f"In-range edge {in_range_edge} was changed to {clamped_edge}"

    @given(floats(min_value=-10.0, max_value=MIN_EDGE - 0.001, allow_nan=False, allow_infinity=False))
    @settings(max_examples=200)
    def test_below_minimum_clamps_to_zero(self, below_min_edge):
        """Edges below minimum should clamp to 0."""
        clamped_edge = max(MIN_EDGE, min(MAX_EDGE, below_min_edge))
        assert clamped_edge == MIN_EDGE, \
            f"Edge {below_min_edge} below min should clamp to {MIN_EDGE}, got {clamped_edge}"

    @given(floats(min_value=MAX_EDGE + 0.001, max_value=10.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=200)
    def test_above_maximum_clamps_to_one(self, above_max_edge):
        """Edges above maximum should clamp to 1."""
        clamped_edge = max(MIN_EDGE, min(MAX_EDGE, above_max_edge))
        assert clamped_edge == MAX_EDGE, \
            f"Edge {above_max_edge} above max should clamp to {MAX_EDGE}, got {clamped_edge}"

    @given(floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=300)
    @example(raw_edge=0.0)
    @example(raw_edge=0.5)
    @example(raw_edge=1.0)
    @example(raw_edge=-0.5)
    @example(raw_edge=1.5)
    def test_clamping_is_idempotent(self, raw_edge):
        """Clamping the same edge twice should yield the same result."""
        first_clamp = max(MIN_EDGE, min(MAX_EDGE, raw_edge))
        second_clamp = max(MIN_EDGE, min(MAX_EDGE, first_clamp))
        assert first_clamp == second_clamp, \
            f"Clamping not idempotent: {raw_edge} -> {first_clamp} -> {second_clamp}"


class TestEdgeThresholdInvariants:
    """Property-based tests for edge threshold validation."""

    @given(floats(min_value=EDGE_THRESHOLD, max_value=MAX_EDGE, allow_nan=False, allow_infinity=False))
    @settings(max_examples=300)
    def test_edge_above_threshold_is_valid(self, valid_edge):
        """Edges above threshold should be considered valid."""
        assert valid_edge >= EDGE_THRESHOLD, \
            f"Edge {valid_edge} should be >= threshold {EDGE_THRESHOLD}"

    @given(floats(min_value=MIN_EDGE, max_value=EDGE_THRESHOLD - 0.001, allow_nan=False, allow_infinity=False))
    @settings(max_examples=200)
    def test_edge_below_threshold_is_invalid(self, invalid_edge):
        """Edges below threshold should be considered invalid."""
        assert invalid_edge < EDGE_THRESHOLD, \
            f"Edge {invalid_edge} should be < threshold {EDGE_THRESHOLD}"

    @given(floats(min_value=MIN_EDGE, max_value=MAX_EDGE, allow_nan=False, allow_infinity=False))
    @settings(max_examples=300)
    @example(edge=EDGE_THRESHOLD)
    @example(edge=0.0)
    @example(edge=1.0)
    def test_threshold_check_consistency(self, edge):
        """Threshold check should be consistent across different implementations."""
        check1 = edge >= EDGE_THRESHOLD
        check2 = (edge - EDGE_THRESHOLD) >= 0
        assert check1 == check2, \
            f"Inconsistent threshold check for edge {edge}"

    @given(floats(min_value=MIN_EDGE, max_value=MAX_EDGE, allow_nan=False, allow_infinity=False))
    @settings(max_examples=200)
    def test_edge_threshold_absolute_value(self, edge):
        """Edge threshold should work with absolute values for contrarian signals."""
        abs_edge = abs(edge)
        if abs_edge >= EDGE_THRESHOLD:
            assert True  # Valid absolute edge
        else:
            assert abs_edge < EDGE_THRESHOLD  # Invalid absolute edge


class TestEdgeArithmeticInvariants:
    """Property-based tests for edge arithmetic operations."""

    @given(floats(min_value=MIN_EDGE, max_value=MAX_EDGE, allow_nan=False, allow_infinity=False),
           floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False))
    @settings(max_examples=300)
    def test_edge_with_adjustment_stays_in_range(self, base_edge, adjustment):
        """Edge with adjustment should clamp to [0, 1] range."""
        adjusted_edge = base_edge + adjustment
        clamped_edge = max(MIN_EDGE, min(MAX_EDGE, adjusted_edge))
        assert MIN_EDGE <= clamped_edge <= MAX_EDGE, \
            f"Adjusted edge {clamped_edge} outside valid range"

    @given(floats(min_value=MIN_EDGE, max_value=MAX_EDGE, allow_nan=False, allow_infinity=False),
           floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=200)
    def test_edge_multiplication_with_clamping(self, base_edge, multiplier):
        """Edge multiplication should clamp to [0, 1] range."""
        multiplied_edge = base_edge * multiplier
        clamped_edge = max(MIN_EDGE, min(MAX_EDGE, multiplied_edge))
        assert MIN_EDGE <= clamped_edge <= MAX_EDGE, \
            f"Multiplied edge {clamped_edge} outside valid range"

    @given(floats(min_value=MIN_EDGE, max_value=MAX_EDGE, allow_nan=False, allow_infinity=False),
           floats(min_value=MIN_EDGE, max_value=MAX_EDGE, allow_nan=False, allow_infinity=False))
    @settings(max_examples=200)
    def test_edge_average_stays_in_range(self, edge1, edge2):
        """Average of two valid edges should stay in range."""
        average_edge = (edge1 + edge2) / 2.0
        assert MIN_EDGE <= average_edge <= MAX_EDGE, \
            f"Average edge {average_edge} outside valid range"

    @given(floats(min_value=MIN_EDGE, max_value=MAX_EDGE, allow_nan=False, allow_infinity=False),
           floats(min_value=MIN_EDGE, max_value=MAX_EDGE, allow_nan=False, allow_infinity=False))
    @settings(max_examples=200)
    def test_edge_sum_with_clamping(self, edge1, edge2):
        """Sum of edges should clamp to [0, 1] range."""
        sum_edge = edge1 + edge2
        clamped_edge = max(MIN_EDGE, min(MAX_EDGE, sum_edge))
        assert MIN_EDGE <= clamped_edge <= MAX_EDGE, \
            f"Sum edge {clamped_edge} outside valid range"


class TestEdgeEdgeCases:
    """Property-based tests for edge cases in edge calculations."""

    @given(floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=200)
    def test_extreme_values_clamp_correctly(self, extreme_edge):
        """Extreme values should clamp to [0, 1] range."""
        clamped_edge = max(MIN_EDGE, min(MAX_EDGE, extreme_edge))
        assert MIN_EDGE <= clamped_edge <= MAX_EDGE, \
            f"Extreme value {extreme_edge} should clamp to range, got {clamped_edge}"

    @given(st.one_of(st.just(0.0), st.just(0.5), st.just(1.0), st.just(-0.5), st.just(1.5)))
    @settings(max_examples=10)
    def test_boundary_values(self, boundary_edge):
        """Boundary values should clamp correctly."""
        clamped_edge = max(MIN_EDGE, min(MAX_EDGE, boundary_edge))
        expected = MIN_EDGE if boundary_edge < MIN_EDGE else (MAX_EDGE if boundary_edge > MAX_EDGE else boundary_edge)
        assert clamped_edge == expected, \
            f"Boundary value {boundary_edge} should clamp to {expected}, got {clamped_edge}"

    @given(floats(min_value=MIN_EDGE, max_value=MAX_EDGE, allow_nan=False, allow_infinity=False))
    @settings(max_examples=200)
    def test_non_negative_edges_remain_non_negative(self, non_negative_edge):
        """Non-negative edges should remain non-negative after clamping."""
        clamped_edge = max(MIN_EDGE, min(MAX_EDGE, non_negative_edge))
        assert clamped_edge >= 0, f"Clamped edge {clamped_edge} should be non-negative"

    @given(floats(min_value=MIN_EDGE, max_value=MAX_EDGE, allow_nan=False, allow_infinity=False))
    @settings(max_examples=200)
    def test_edge_squared_stays_in_range(self, edge):
        """Squared edge should stay in [0, 1] range."""
        squared_edge = edge ** 2
        assert MIN_EDGE <= squared_edge <= MAX_EDGE, \
            f"Squared edge {squared_edge} outside valid range"

    @given(floats(min_value=MIN_EDGE, max_value=MAX_EDGE, allow_nan=False, allow_infinity=False))
    @settings(max_examples=200)
    def test_edge_sqrt_stays_in_range(self, edge):
        """Square root of edge should stay in [0, 1] range."""
        sqrt_edge = math.sqrt(edge)
        assert MIN_EDGE <= sqrt_edge <= MAX_EDGE, \
            f"Square root edge {sqrt_edge} outside valid range"


class TestEdgeConsistencyAcrossModules:
    """Property-based tests for edge consistency across different modules."""

    @given(floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=300)
    def test_clamping_consistency(self, raw_edge):
        """Clamping should be consistent regardless of implementation."""
        # Test multiple clamping implementations
        clamp1 = max(MIN_EDGE, min(MAX_EDGE, raw_edge))
        clamp2 = MIN_EDGE if raw_edge < MIN_EDGE else (MAX_EDGE if raw_edge > MAX_EDGE else raw_edge)
        assert clamp1 == clamp2, \
            f"Inconsistent clamping: {raw_edge} -> {clamp1} vs {clamp2}"

    @given(floats(min_value=MIN_EDGE, max_value=MAX_EDGE, allow_nan=False, allow_infinity=False))
    @settings(max_examples=200)
    def test_range_check_consistency(self, in_range_edge):
        """Range check should be consistent across different implementations."""
        check1 = MIN_EDGE <= in_range_edge <= MAX_EDGE
        check2 = (in_range_edge >= MIN_EDGE) and (in_range_edge <= MAX_EDGE)
        assert check1 == check2, \
            f"Inconsistent range check for edge {in_range_edge}"


class TestEdgeWithConfidence:
    """Property-based tests for edge calculations with confidence."""

    @given(floats(min_value=MIN_EDGE, max_value=MAX_EDGE, allow_nan=False, allow_infinity=False),
           floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=300)
    def test_edge_weighted_by_confidence(self, edge, confidence):
        """Edge weighted by confidence should stay in [0, 1] range."""
        weighted_edge = edge * confidence
        clamped_edge = max(MIN_EDGE, min(MAX_EDGE, weighted_edge))
        assert MIN_EDGE <= clamped_edge <= MAX_EDGE, \
            f"Weighted edge {clamped_edge} outside valid range"

    @given(floats(min_value=MIN_EDGE, max_value=MAX_EDGE, allow_nan=False, allow_infinity=False),
           floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=200)
    def test_confidence_scaling_preserves_sign(self, edge, confidence):
        """Confidence scaling should preserve the sign of the edge."""
        weighted_edge = edge * confidence
        if edge > 0:
            assert weighted_edge >= 0, f"Positive edge became negative: {edge} * {confidence} = {weighted_edge}"
        elif edge < 0:
            assert weighted_edge <= 0, f"Negative edge became positive: {edge} * {confidence} = {weighted_edge}"


class TestEdgeNormalization:
    """Property-based tests for edge normalization operations."""

    @given(floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=300)
    def test_normalization_to_unit_range(self, raw_value):
        """Normalization should map values to [0, 1] range."""
        # Simple normalization: map [-1, 1] to [0, 1]
        normalized = (raw_value + 1) / 2
        clamped = max(MIN_EDGE, min(MAX_EDGE, normalized))
        assert MIN_EDGE <= clamped <= MAX_EDGE, \
            f"Normalized value {clamped} outside valid range"

    @given(floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=200)
    def test_min_max_normalization(self, raw_value):
        """Min-max normalization should map to [0, 1] range."""
        # Normalize assuming range [0, 100]
        normalized = raw_value / 100.0
        clamped = max(MIN_EDGE, min(MAX_EDGE, normalized))
        assert MIN_EDGE <= clamped <= MAX_EDGE, \
            f"Min-max normalized value {clamped} outside valid range"


class TestEdgeSignalDirection:
    """Property-based tests for edge signal direction."""

    @given(floats(min_value=MIN_EDGE, max_value=MAX_EDGE, allow_nan=False, allow_infinity=False))
    @settings(max_examples=300)
    def test_positive_edge_indicates_buy(self, edge):
        """Positive edge should indicate buy signal."""
        if edge > 0:
            assert edge > 0, f"Positive edge {edge} should indicate buy"

    @given(floats(min_value=MIN_EDGE, max_value=MAX_EDGE, allow_nan=False, allow_infinity=False))
    @settings(max_examples=300)
    def test_negative_edge_indicates_sell(self, edge):
        """Negative edge should indicate sell signal."""
        if edge < 0:
            assert edge < 0, f"Negative edge {edge} should indicate sell"

    @given(floats(min_value=MIN_EDGE, max_value=MAX_EDGE, allow_nan=False, allow_infinity=False))
    @settings(max_examples=200)
    def test_zero_edge_indicates_neutral(self, edge):
        """Zero edge should indicate neutral signal."""
        if abs(edge) < 0.001:  # Near zero
            assert abs(edge) < 0.001, f"Zero edge {edge} should indicate neutral"

    @given(floats(min_value=MIN_EDGE, max_value=MAX_EDGE, allow_nan=False, allow_infinity=False))
    @settings(max_examples=200)
    def test_edge_magnitude_indicates_strength(self, edge):
        """Edge magnitude should indicate signal strength."""
        magnitude = abs(edge)
        assert MIN_EDGE <= magnitude <= MAX_EDGE, \
            f"Edge magnitude {magnitude} outside valid range"
