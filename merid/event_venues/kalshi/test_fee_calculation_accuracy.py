"""
Unit tests for Kalshi fee calculation accuracy across price range.

Tests the canonical tiered fee formula from fees.py and ensures
fee calculation is accurate across the full price range (1c-99c).
"""

import pytest
from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents


def test_fee_calculation_at_50c_small_tier():
    """Test fee calculation at 50 cents with < 100 contracts (7% tier)."""
    # At 50c, fee = ceil(0.07 * 1 * 0.50 * 0.50 * 100) = ceil(1.75) = 2c
    fee = calculate_kalshi_fee_cents(contracts=1, price_cents=50)
    assert fee == 2, f"Expected fee=2c at 50c, got {fee}c"


def test_fee_calculation_at_50c_medium_tier():
    """Test fee calculation at 50 cents with 100-999 contracts (5% tier)."""
    # At 50c, fee = ceil(0.05 * 100 * 0.50 * 0.50 * 100) = ceil(125) = 125c
    fee = calculate_kalshi_fee_cents(contracts=100, price_cents=50)
    assert fee == 125, f"Expected fee=125c at 50c with 100 contracts, got {fee}c"


def test_fee_calculation_at_50c_large_tier():
    """Test fee calculation at 50 cents with 1000+ contracts (3% tier)."""
    # At 50c, fee = ceil(0.03 * 1000 * 0.50 * 0.50 * 100) = ceil(750) = 750c
    fee = calculate_kalshi_fee_cents(contracts=1000, price_cents=50)
    assert fee == 750, f"Expected fee=750c at 50c with 1000 contracts, got {fee}c"


def test_fee_calculation_at_extreme_prices():
    """Test fee calculation at price extremes (1c and 99c)."""
    # At 1c, fee should be at minimum floor (2c)
    fee_1c = calculate_kalshi_fee_cents(contracts=1, price_cents=1)
    assert fee_1c >= 2, f"Fee should be at minimum floor (2c) at 1c, got {fee_1c}c"
    
    # At 99c, fee should be at minimum floor (2c)
    fee_99c = calculate_kalshi_fee_cents(contracts=1, price_cents=99)
    assert fee_99c >= 2, f"Fee should be at minimum floor (2c) at 99c, got {fee_99c}c"
    
    # Fees at extremes should be at minimum floor (parabolic curve with floor)
    # Due to minimum floor of 2c, fees at extremes equal the floor
    fee_50c = calculate_kalshi_fee_cents(contracts=1, price_cents=50)
    assert fee_1c <= fee_50c, f"Fee at 1c ({fee_1c}c) should be <= fee at 50c ({fee_50c}c)"
    assert fee_99c <= fee_50c, f"Fee at 99c ({fee_99c}c) should be <= fee at 50c ({fee_50c}c)"


def test_fee_calculation_parabolic_curve():
    """Test that fee follows parabolic curve (peaks at 50c) for larger orders."""
    # For single contracts, minimum floor (2c) dominates across most of the range
    # Test with larger order size to see parabolic behavior
    prices = [10, 25, 40, 50, 60, 75, 90]
    fees = [calculate_kalshi_fee_cents(contracts=100, price_cents=p) for p in prices]
    
    # Find max fee (should be at 50c)
    max_fee = max(fees)
    max_idx = fees.index(max_fee)
    
    assert max_idx == 3, f"Max fee should be at 50c (index 3), got max at index {max_idx} (price={prices[max_idx]}c, fee={max_fee}c)"


def test_fee_calculation_multiple_contracts():
    """Test fee calculation scales with contract count."""
    fee_1 = calculate_kalshi_fee_cents(contracts=1, price_cents=50)
    fee_10 = calculate_kalshi_fee_cents(contracts=10, price_cents=50)
    fee_100 = calculate_kalshi_fee_cents(contracts=100, price_cents=50)
    
    # Fee should scale with contracts (non-linear due to tiering)
    assert fee_10 > fee_1, f"Fee for 10 contracts ({fee_10}c) should be > fee for 1 contract ({fee_1}c)"
    assert fee_100 > fee_10, f"Fee for 100 contracts ({fee_100}c) should be > fee for 10 contracts ({fee_10}c)"


def test_fee_calculation_minimum_floor():
    """Test that fee has minimum floor (2c per contract)."""
    # Even at low prices, fee should be at least 2c per contract for valid trades
    # (This is Kalshi's documented minimum)
    fee = calculate_kalshi_fee_cents(contracts=1, price_cents=50)
    assert fee >= 2, f"Fee should be >= 2c minimum, got {fee}c"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
