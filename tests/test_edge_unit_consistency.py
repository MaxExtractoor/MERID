"""
Regression tests for edge/spread/fee unit consistency.

These tests ensure that the unit mismatch bug (fraction vs percentage)
cannot recur in the codebase. They test invariants that should always hold.
"""

import pytest
from merid.utils.edge_utils import (
    convert_edge_fraction_to_percentage,
    convert_edge_percentage_to_fraction,
    convert_edge_fraction_to_cents_kalshi,
    convert_edge_fraction_to_cents_general,
    calculate_executable_edge,
    validate_edge_units,
    validate_kalshi_contract_price,
)
from merid.prediction.agent_grid_15m import calculate_velocity_edge
from merid.event_venues.kalshi.risk_parameters import validate_edge


class TestEdgeUnitConversions:
    """Test edge unit conversion functions."""

    def test_fraction_to_percentage_conversion(self):
        """Test converting fraction to percentage."""
        assert convert_edge_fraction_to_percentage(0.0) == 0.0
        assert convert_edge_fraction_to_percentage(0.15) == 15.0
        assert convert_edge_fraction_to_percentage(0.50) == 50.0
        assert convert_edge_fraction_to_percentage(1.0) == 100.0

    def test_percentage_to_fraction_conversion(self):
        """Test converting percentage to fraction."""
        assert convert_edge_percentage_to_fraction(0.0) == 0.0
        assert convert_edge_percentage_to_fraction(15.0) == 0.15
        assert convert_edge_percentage_to_fraction(50.0) == 0.50
        assert convert_edge_percentage_to_fraction(100.0) == 1.0

    def test_roundtrip_conversion(self):
        """Test that roundtrip conversion preserves value."""
        original = 0.42
        converted = convert_edge_fraction_to_percentage(original)
        back = convert_edge_percentage_to_fraction(converted)
        assert abs(back - original) < 1e-9

    def test_fraction_to_cents_kalshi_conversion(self):
        """Test converting fraction to cents for Kalshi markets ($1 contracts)."""
        assert convert_edge_fraction_to_cents_kalshi(0.0) == 0.0
        assert convert_edge_fraction_to_cents_kalshi(0.15) == 15.0
        assert convert_edge_fraction_to_cents_kalshi(0.50) == 50.0
        assert convert_edge_fraction_to_cents_kalshi(1.0) == 100.0

    def test_fraction_to_cents_general_conversion(self):
        """Test converting fraction to cents for general contract prices."""
        # $1 contract (100c)
        assert convert_edge_fraction_to_cents_general(0.15, 100) == 15.0
        # $0.50 contract (50c)
        assert convert_edge_fraction_to_cents_general(0.15, 50) == 7.5
        # $2 contract (200c)
        assert convert_edge_fraction_to_cents_general(0.15, 200) == 30.0

    def test_kalshi_vs_general_conversion_equivalence(self):
        """Test that Kalshi and general conversions are equivalent for $1 contracts."""
        edge_frac = 0.15
        contract_price_cents = 100  # $1 contract

        kalshi_result = convert_edge_fraction_to_cents_kalshi(edge_frac)
        general_result = convert_edge_fraction_to_cents_general(edge_frac, contract_price_cents)

        assert kalshi_result == general_result

    def test_kalshi_contract_price_validation(self):
        """Test that Kalshi contract price validation works."""
        # Valid $1 contract
        assert validate_kalshi_contract_price(100) == True

        # Invalid non-$1 contracts
        with pytest.raises(ValueError, match="Kalshi contract price must be"):
            validate_kalshi_contract_price(50)

        with pytest.raises(ValueError, match="Kalshi contract price must be"):
            validate_kalshi_contract_price(200)


class TestExecutableEdgeCalculation:
    """Test executable edge calculation with unit consistency."""

    def test_maker_economics(self):
        """Test maker edge calculation (no spread cost, reduced fee)."""
        edge_frac = 0.15  # 15% edge
        spread_pct = 2.0  # 2% spread (ignored for maker)
        taker_fee_pct = 5.0  # 5% taker fee (ignored for maker)
        maker_fee_pct = 1.25  # 1.25% maker fee

        maker_edge, taker_edge = calculate_executable_edge(
            edge_frac, spread_pct, taker_fee_pct, maker_fee_pct
        )

        # Maker: 15.0 - 1.25 = 13.75%
        assert maker_edge == 13.75
        # Taker: 15.0 - 2.0 - 5.0 = 8.0%
        assert taker_edge == 8.0

    def test_taker_economics(self):
        """Test taker edge calculation (spread cost + full fee)."""
        edge_frac = 0.20  # 20% edge
        spread_pct = 3.0  # 3% spread
        taker_fee_pct = 5.0  # 5% taker fee
        maker_fee_pct = 1.25  # 1.25% maker fee

        maker_edge, taker_edge = calculate_executable_edge(
            edge_frac, spread_pct, taker_fee_pct, maker_fee_pct
        )

        # Maker: 20.0 - 1.25 = 18.75%
        assert maker_edge == 18.75
        # Taker: 20.0 - 3.0 - 5.0 = 12.0%
        assert taker_edge == 12.0

    def test_zero_edge(self):
        """Test edge calculation with zero edge."""
        edge_frac = 0.0
        spread_pct = 2.0
        taker_fee_pct = 5.0
        maker_fee_pct = 1.25

        maker_edge, taker_edge = calculate_executable_edge(
            edge_frac, spread_pct, taker_fee_pct, maker_fee_pct
        )

        # Both should be negative (edge < costs)
        assert maker_edge == -1.25
        assert taker_edge == -7.0

    def test_unit_mismatch_invariant(self):
        """
        CRITICAL REGRESSION TEST: This test would fail if the unit mismatch bug recurs.

        The bug was: executable_edge = edge_pct (fraction) - spread_pct (percentage)
        This resulted in: 0.15 - 15.0 = -14.85 (wrong)

        The fix is: convert edge_pct to percentage first
        This results in: 15.0 - 15.0 = 0.0 (correct for taker)
        Maker edge: 15.0 - 0.0 = 15.0 (no spread cost, no fee)
        """
        edge_frac = 0.15  # 15% as fraction
        spread_pct = 15.0  # 15% as percentage
        taker_fee_pct = 0.0  # 0% fee
        maker_fee_pct = 0.0  # 0% fee

        maker_edge, taker_edge = calculate_executable_edge(
            edge_frac, spread_pct, taker_fee_pct, maker_fee_pct
        )

        # If the bug recurs, taker_edge would be -14.85 instead of 0.0
        assert taker_edge == 0.0, f"Unit mismatch detected: taker_edge={taker_edge}, expected 0.0"
        # Maker edge should be 15.0 (no spread cost, no fee)
        assert maker_edge == 15.0, f"Unit mismatch detected: maker_edge={maker_edge}, expected 15.0"

    def test_exact_bug_reproduction_momentum_fvg_path(self):
        """
        CRITICAL REGRESSION TEST: Reproduce exact bug from MOMENTUM-FVG path.

        Original bug location: agent_grid_15m.py line 5851
        Test case: edge=0.15, spread=2.22, taker_fee=4.44, maker_fee=1.11
        Expected: taker_edge = 15.0 - 2.22 - 4.44 = 8.34
        Bug would produce: taker_edge = 0.15 - 2.22 - 4.44 = -6.51
        """
        edge_frac = 0.15
        spread_pct = 2.22
        taker_fee_pct = 4.44
        maker_fee_pct = 1.11

        maker_edge, taker_edge = calculate_executable_edge(
            edge_frac, spread_pct, taker_fee_pct, maker_fee_pct
        )

        # Correct calculation with unit conversion
        assert abs(taker_edge - 8.34) < 0.01, f"Bug detected: taker_edge={taker_edge}, expected ~8.34"
        assert abs(maker_edge - 13.89) < 0.01, f"Bug detected: maker_edge={maker_edge}, expected ~13.89"

    def test_exact_bug_reproduction_price_based_path(self):
        """
        CRITICAL REGRESSION TEST: Reproduce exact bug from price-based path.

        Original bug location: agent_grid_15m.py line 6798
        Test case: edge=0.04, spread=2.22, taker_fee=4.44, maker_fee=1.11
        Expected: taker_edge = 4.0 - 2.22 - 4.44 = -2.66
        Bug would produce: taker_edge = 0.04 - 2.22 - 4.44 = -6.62
        """
        edge_frac = 0.04
        spread_pct = 2.22
        taker_fee_pct = 4.44
        maker_fee_pct = 1.11

        maker_edge, taker_edge = calculate_executable_edge(
            edge_frac, spread_pct, taker_fee_pct, maker_fee_pct
        )

        # Correct calculation with unit conversion
        assert abs(taker_edge - (-2.66)) < 0.01, f"Bug detected: taker_edge={taker_edge}, expected ~-2.66"
        assert abs(maker_edge - 2.89) < 0.01, f"Bug detected: maker_edge={maker_edge}, expected ~2.89"

    def test_exact_bug_reproduction_legacy_fee_path(self):
        """
        CRITICAL REGRESSION TEST: Reproduce exact bug from legacy fee modeling path.

        Original bug location: agent_grid_15m.py line 11261
        Test case: edge=0.15, fee=4.44
        Expected: net_edge = 15.0 - 4.44 = 10.56
        Bug would produce: net_edge = 0.15 - 4.44 = -4.29
        """
        edge_frac = 0.15
        fee_pct = 4.44

        # Use conversion helper
        edge_pct_percentage = convert_edge_fraction_to_percentage(edge_frac)
        net_edge_pct = edge_pct_percentage - fee_pct

        # Correct calculation with unit conversion
        assert abs(net_edge_pct - 10.56) < 0.01, f"Bug detected: net_edge_pct={net_edge_pct}, expected ~10.56"


class TestEdgeUnitValidation:
    """Test edge unit validation function."""

    def test_valid_units(self):
        """Test validation with valid units."""
        edge_pct = 0.15  # Valid fraction
        spread_pct = 15.0  # Valid percentage
        taker_fee_pct = 5.0  # Valid percentage
        maker_fee_pct = 1.25  # Valid percentage

        assert validate_edge_units(edge_pct, spread_pct, taker_fee_pct, maker_fee_pct)

    def test_invalid_edge_pct_too_high(self):
        """Test validation rejects edge_pct > 1.0."""
        with pytest.raises(ValueError, match="edge_pct"):
            validate_edge_units(1.5, 15.0, 5.0, 1.25)

    def test_invalid_edge_pct_negative(self):
        """Test validation rejects negative edge_pct."""
        with pytest.raises(ValueError, match="edge_pct"):
            validate_edge_units(-0.1, 15.0, 5.0, 1.25)

    def test_invalid_spread_pct_too_high(self):
        """Test validation rejects spread_pct > 100.0."""
        with pytest.raises(ValueError, match="spread_pct"):
            validate_edge_units(0.15, 150.0, 5.0, 1.25)

    def test_invalid_spread_pct_negative(self):
        """Test validation rejects negative spread_pct."""
        with pytest.raises(ValueError, match="spread_pct"):
            validate_edge_units(0.15, -5.0, 5.0, 1.25)

    def test_invalid_taker_fee_pct_too_high(self):
        """Test validation rejects taker_fee_pct > 100.0."""
        with pytest.raises(ValueError, match="taker_fee_pct"):
            validate_edge_units(0.15, 15.0, 150.0, 1.25)

    def test_invalid_maker_fee_pct_too_high(self):
        """Test validation rejects maker_fee_pct > 100.0."""
        with pytest.raises(ValueError, match="maker_fee_pct"):
            validate_edge_units(0.15, 15.0, 5.0, 150.0)


class TestEdgeInvariants:
    """Test mathematical invariants that should always hold."""

    def test_spread_increase_decreases_taker_edge(self):
        """Invariant: Increasing spread decreases taker edge."""
        edge_frac = 0.20
        taker_fee_pct = 5.0
        maker_fee_pct = 1.25

        _, taker_edge_low_spread = calculate_executable_edge(
            edge_frac, 2.0, taker_fee_pct, maker_fee_pct
        )
        _, taker_edge_high_spread = calculate_executable_edge(
            edge_frac, 5.0, taker_fee_pct, maker_fee_pct
        )

        assert taker_edge_low_spread > taker_edge_high_spread

    def test_fee_increase_decreases_taker_edge(self):
        """Invariant: Increasing fee decreases taker edge."""
        edge_frac = 0.20
        spread_pct = 3.0
        maker_fee_pct = 1.25

        _, taker_edge_low_fee = calculate_executable_edge(
            edge_frac, spread_pct, 4.0, maker_fee_pct
        )
        _, taker_edge_high_fee = calculate_executable_edge(
            edge_frac, spread_pct, 6.0, maker_fee_pct
        )

        assert taker_edge_low_fee > taker_edge_high_fee

    def test_maker_edge_always_higher_than_taker_edge(self):
        """Invariant: Maker edge >= taker edge (maker has lower fees, no spread cost)."""
        edge_frac = 0.20
        spread_pct = 3.0
        taker_fee_pct = 5.0
        maker_fee_pct = 1.25

        maker_edge, taker_edge = calculate_executable_edge(
            edge_frac, spread_pct, taker_fee_pct, maker_fee_pct
        )

        assert maker_edge >= taker_edge

    def test_zero_spread_maker_equals_taker(self):
        """Invariant: With zero spread, maker and taker edges differ only by fee difference."""
        edge_frac = 0.20
        spread_pct = 0.0
        taker_fee_pct = 5.0
        maker_fee_pct = 1.25

        maker_edge, taker_edge = calculate_executable_edge(
            edge_frac, spread_pct, taker_fee_pct, maker_fee_pct
        )

        # Difference should be taker_fee - maker_fee = 5.0 - 1.25 = 3.75
        assert abs((maker_edge - taker_edge) - (taker_fee_pct - maker_fee_pct)) < 0.01

    def test_impossible_edge_rejected(self):
        """Invariant: Executable edge cannot exceed 100% (impossible)."""
        edge_frac = 2.0  # 200% edge (impossible, but test validation)
        spread_pct = 0.0
        taker_fee_pct = 0.0
        maker_fee_pct = 0.0

        # Validation should reject edge_frac > 1.0
        with pytest.raises(ValueError, match="edge_pct"):
            validate_edge_units(edge_frac, spread_pct, taker_fee_pct, maker_fee_pct)


class TestVelocityEdgeUnitConsistency:
    """Velocity edge is emitted in percentage points and converted to fraction
    before the threshold/confidence validation that expects a fraction.
    """

    def test_calculate_velocity_edge_returns_percentage_points(self):
        """A velocity of 0.0004 against a 0.0002 threshold is a 4% edge."""
        edge_pct = calculate_velocity_edge(0.0004, 0.0002)
        assert edge_pct == 4.0

    def test_calculate_velocity_edge_zero_threshold_is_zero(self):
        """A zero threshold must not produce an infinity or large value."""
        assert calculate_velocity_edge(0.0004, 0.0) == 0.0

    def test_validate_edge_receives_fraction_from_velocity_edge(self):
        """The percentage-point output must be divided by 100 before validate_edge."""
        edge_pct = calculate_velocity_edge(0.0004, 0.0002)
        edge_frac = edge_pct / 100.0
        confidence = 0.5 + edge_frac

        is_valid, _ = validate_edge(edge_frac, "BTC", confidence)
        assert is_valid is True

    def test_velocity_edge_points_vs_fraction_invariant(self):
        """A 15.0 pp velocity edge validates as 0.15 fraction, not 15.0."""
        edge_pct = 15.0
        edge_frac = edge_pct / 100.0

        # 15.0 as a fraction would be 1500% and should be rejected as >1.0,
        # which is the exact unit bug this invariant protects against.
        with pytest.raises(ValueError, match="edge_pct"):
            validate_edge_units(edge_pct, 0.0, 0.0, 0.0)

        is_valid, _ = validate_edge(edge_frac, "BTC", 0.5 + edge_frac)
        assert is_valid is True
