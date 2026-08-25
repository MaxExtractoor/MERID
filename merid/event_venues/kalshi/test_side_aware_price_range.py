"""Unit tests for side-aware price range filtering (BUY NO bias fix).

Tests the new side-aware price range logic that prevents systematic rejection
of NO orders in late-expiry markets where YES prices are low (1c-6c) and
NO prices are high (94c-99c).
"""

import pytest
from merid.event_venues.kalshi.binary_price_space import (
    is_price_in_side_aware_range,
    is_price_in_canonical_range,
    is_price_in_crisis_range,
    yes_to_no_price,
    no_to_yes_price,
)


def test_side_aware_yes_range():
    """Test that YES prices use expanded range (1c-75c)."""
    # Valid YES prices (including late-expiry low prices)
    assert is_price_in_side_aware_range(1, "yes") == True
    assert is_price_in_side_aware_range(6, "yes") == True
    assert is_price_in_side_aware_range(10, "yes") == True
    assert is_price_in_side_aware_range(25, "yes") == True
    assert is_price_in_side_aware_range(50, "yes") == True
    assert is_price_in_side_aware_range(75, "yes") == True
    
    # Invalid YES prices (too low)
    assert is_price_in_side_aware_range(0, "yes") == False
    
    # Invalid YES prices (too high)
    assert is_price_in_side_aware_range(76, "yes") == False
    assert is_price_in_side_aware_range(80, "yes") == False
    assert is_price_in_side_aware_range(94, "yes") == False
    assert is_price_in_side_aware_range(99, "yes") == False


def test_side_aware_no_range():
    """Test that NO prices use expanded range (25c-99c) to account for duality."""
    # Valid NO prices (late-expiry scenario)
    assert is_price_in_side_aware_range(25, "no") == True
    assert is_price_in_side_aware_range(50, "no") == True
    assert is_price_in_side_aware_range(75, "no") == True
    assert is_price_in_side_aware_range(90, "no") == True
    
    # Valid NO prices in late-expiry (high prices due to duality)
    assert is_price_in_side_aware_range(94, "no") == True  # This was previously rejected!
    assert is_price_in_side_aware_range(95, "no") == True  # This was previously rejected!
    assert is_price_in_side_aware_range(97, "no") == True  # This was previously rejected!
    assert is_price_in_side_aware_range(99, "no") == True  # This was previously rejected!
    
    # Invalid NO prices (too low)
    assert is_price_in_side_aware_range(5, "no") == False
    assert is_price_in_side_aware_range(10, "no") == False
    assert is_price_in_side_aware_range(20, "no") == False
    assert is_price_in_side_aware_range(24, "no") == False
    
    # Invalid NO prices (too high)
    assert is_price_in_side_aware_range(100, "no") == False


def test_late_expiry_scenario():
    """Test late-expiry scenario where YES is low and NO is high."""
    # Late-expiry: YES at 6c, NO at 94c (derived from duality)
    yes_price = 6
    no_price = 94
    
    # Both should be in range with side-aware logic
    assert is_price_in_side_aware_range(yes_price, "yes") == True
    assert is_price_in_side_aware_range(no_price, "no") == True
    
    # Verify duality
    assert yes_to_no_price(yes_price) == 94
    assert no_to_yes_price(no_price) == 6


def test_early_expiry_scenario():
    """Test early-expiry scenario where YES and NO are mid-range."""
    # Early-expiry: YES at 50c, NO at 50c (balanced market)
    yes_price = 50
    no_price = 50
    
    # Both should be in range
    assert is_price_in_side_aware_range(yes_price, "yes") == True
    assert is_price_in_side_aware_range(no_price, "no") == True
    
    # Verify duality
    assert yes_to_no_price(yes_price) == 50
    assert no_to_yes_price(no_price) == 50


def test_canonical_range_still_works():
    """Test that canonical range is the symmetric 10c-75c entry range."""
    # CRITICAL FIX (2026-08-14): canonical range is now 10c-75c for both sides.

    # YES canonical range (10c-75c)
    assert is_price_in_canonical_range(10, "yes") == True   # Min YES
    assert is_price_in_canonical_range(25, "yes") == True
    assert is_price_in_canonical_range(75, "yes") == True  # Max YES
    assert is_price_in_canonical_range(9, "yes") == False  # Too low
    assert is_price_in_canonical_range(76, "yes") == False  # Too high

    # NO canonical range (10c-75c)
    assert is_price_in_canonical_range(10, "no") == True  # Min NO
    assert is_price_in_canonical_range(25, "no") == True
    assert is_price_in_canonical_range(75, "no") == True  # Max NO
    assert is_price_in_canonical_range(9, "no") == False  # Too low
    assert is_price_in_canonical_range(76, "no") == False  # Too high


def test_crisis_range_still_works():
    """Test that crisis range function now uses side-aware ranges (2026-08-01 fix)."""
    # Crisis range is now side-aware: YES 1c-99c, NO 5c-99c
    # This fixes the bug where crisis range was rejecting valid extreme prices

    # YES crisis range (1c-99c) - accepts full range
    assert is_price_in_crisis_range(1, "yes") == True   # Min YES (FIX: now accepted!)
    assert is_price_in_crisis_range(5, "yes") == True
    assert is_price_in_crisis_range(99, "yes") == True  # Max YES
    assert is_price_in_crisis_range(0, "yes") == False  # Too low
    assert is_price_in_crisis_range(100, "yes") == False  # Too high

    # NO crisis range (5c-99c)
    assert is_price_in_crisis_range(5, "no") == True   # Min NO
    assert is_price_in_crisis_range(99, "no") == True  # Max NO
    assert is_price_in_crisis_range(4, "no") == False  # Too low
    assert is_price_in_crisis_range(100, "no") == False  # Too high


def test_side_aware_vs_canonical_comparison():
    """Side-aware range still accepts late-expiry; canonical 10c-75c rejects it."""
    # Late-expiry scenario: YES=6c, NO=94c

    # Side-aware range accepts late-expiry prices
    side_aware_yes = is_price_in_side_aware_range(6, "yes")
    side_aware_no = is_price_in_side_aware_range(94, "no")
    assert side_aware_yes is True  # YES=6c inside side-aware 1c-75c
    assert side_aware_no is True  # NO=94c inside side-aware 25c-99c

    # Canonical 10c-75c entry range rejects the same prices
    canonical_yes = is_price_in_canonical_range(6, "yes")
    canonical_no = is_price_in_canonical_range(94, "no")
    assert canonical_yes is False
    assert canonical_no is False


def test_all_assets_late_expiry():
    """Test all assets from the logs with late-expiry prices."""
    # From the logs, all assets showed this pattern:
    test_cases = [
        ("BTC", 3, 97),
        ("ETH", 1, 99),
        ("SOL", 1, 99),
        ("XRP", 6, 94),
        ("DOGE", 1, 99),
    ]

    for asset, yes_price, no_price in test_cases:
        # With side-aware range, both should be accepted
        assert is_price_in_side_aware_range(yes_price, "yes") == True, \
            f"{asset}: YES {yes_price}c should be in range"
        assert is_price_in_side_aware_range(no_price, "no") == True, \
            f"{asset}: NO {no_price}c should be in range (FIX)"

        # Canonical 10c-75c entry range must reject these extreme fills.
        assert is_price_in_canonical_range(yes_price, "yes") == False, \
            f"{asset}: YES {yes_price}c should be outside canonical 10c-75c (FIX)"
        assert is_price_in_canonical_range(no_price, "no") == False, \
            f"{asset}: NO {no_price}c should be outside canonical 10c-75c (FIX)"

        # Verify duality
        assert yes_to_no_price(yes_price) == no_price, \
            f"{asset}: Duality violation: {yes_price}c + {no_price}c != 100"


def test_edge_cases():
    """Test edge cases for side-aware range."""
    # Boundary values for YES
    assert is_price_in_side_aware_range(1, "yes") == True   # Min YES
    assert is_price_in_side_aware_range(75, "yes") == True  # Max YES
    assert is_price_in_side_aware_range(0, "yes") == False   # Just below min
    assert is_price_in_side_aware_range(76, "yes") == False  # Just above max
    
    # Boundary values for NO
    assert is_price_in_side_aware_range(25, "no") == True  # Min NO
    assert is_price_in_side_aware_range(99, "no") == True  # Max NO
    assert is_price_in_side_aware_range(24, "no") == False  # Just below min
    assert is_price_in_side_aware_range(100, "no") == False  # Just above max


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
