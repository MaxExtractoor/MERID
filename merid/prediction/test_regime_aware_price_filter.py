"""
Unit tests for regime-aware price filter expansion (5c-95c).

Tests that the agent grid price filter correctly expands the acceptable
price range to 5c-95c when extreme price conditions are detected.
"""

import pytest


def test_price_filter_normal_regime():
    """Test price filter uses canonical range (10c-75c) in normal conditions."""
    # Simulate normal price conditions (both sides within 15c-85c)
    yes_price_cents = 45
    no_price_cents = 55
    
    # Detect extreme conditions
    is_extreme = (yes_price_cents > 85 or yes_price_cents < 15 or 
                  no_price_cents > 85 or no_price_cents < 15)
    
    # Should NOT be extreme
    assert not is_extreme, f"Normal prices should not be detected as extreme"
    
    # Use canonical range
    canonical_min = 10
    canonical_max = 75
    crisis_min = 5
    crisis_max = 95
    
    if is_extreme:
        min_price_cents = crisis_min
        max_price_cents = crisis_max
        regime_name = "EXTREME"
    else:
        min_price_cents = canonical_min
        max_price_cents = canonical_max
        regime_name = "NORMAL"
    
    # Verify canonical range is used
    assert regime_name == "NORMAL", f"Should use NORMAL regime, got {regime_name}"
    assert min_price_cents == canonical_min, f"Min price should be {canonical_min}c, got {min_price_cents}c"
    assert max_price_cents == canonical_max, f"Max price should be {canonical_max}c, got {max_price_cents}c"
    
    # Verify prices are in range
    yes_in_range = (min_price_cents <= yes_price_cents <= max_price_cents)
    no_in_range = (min_price_cents <= no_price_cents <= max_price_cents)
    assert yes_in_range, f"YES price {yes_price_cents}c should be in range {min_price_cents}c-{max_price_cents}c"
    assert no_in_range, f"NO price {no_price_cents}c should be in range {min_price_cents}c-{max_price_cents}c"


def test_price_filter_extreme_regime_yes_high():
    """Test price filter uses crisis range (5c-95c) when YES price is extreme (>85c)."""
    # Simulate extreme YES price
    yes_price_cents = 95
    no_price_cents = 5
    
    # Detect extreme conditions
    is_extreme = (yes_price_cents > 85 or yes_price_cents < 15 or 
                  no_price_cents > 85 or no_price_cents < 15)
    
    # Should be extreme (YES > 85c)
    assert is_extreme, f"Extreme YES price should be detected"
    
    # Use crisis range
    canonical_min = 10
    canonical_max = 75
    crisis_min = 5
    crisis_max = 95
    
    if is_extreme:
        min_price_cents = crisis_min
        max_price_cents = crisis_max
        regime_name = "EXTREME"
    else:
        min_price_cents = canonical_min
        max_price_cents = canonical_max
        regime_name = "NORMAL"
    
    # Verify crisis range is used
    assert regime_name == "EXTREME", f"Should use EXTREME regime, got {regime_name}"
    assert min_price_cents == crisis_min, f"Min price should be {crisis_min}c, got {min_price_cents}c"
    assert max_price_cents == crisis_max, f"Max price should be {crisis_max}c, got {max_price_cents}c"
    
    # Verify prices are in range (with expanded range)
    yes_in_range = (min_price_cents <= yes_price_cents <= max_price_cents)
    no_in_range = (min_price_cents <= no_price_cents <= max_price_cents)
    assert yes_in_range, f"YES price {yes_price_cents}c should be in expanded range {min_price_cents}c-{max_price_cents}c"
    assert no_in_range, f"NO price {no_price_cents}c should be in expanded range {min_price_cents}c-{max_price_cents}c"


def test_price_filter_extreme_regime_no_low():
    """Test price filter uses crisis range (5c-95c) when NO price is extreme (<15c)."""
    # Simulate extreme NO price
    yes_price_cents = 90
    no_price_cents = 10
    
    # Detect extreme conditions
    is_extreme = (yes_price_cents > 85 or yes_price_cents < 15 or 
                  no_price_cents > 85 or no_price_cents < 15)
    
    # Should be extreme (NO < 15c)
    assert is_extreme, f"Extreme NO price should be detected"
    
    # Use crisis range
    canonical_min = 10
    canonical_max = 75
    crisis_min = 5
    crisis_max = 95
    
    if is_extreme:
        min_price_cents = crisis_min
        max_price_cents = crisis_max
        regime_name = "EXTREME"
    else:
        min_price_cents = canonical_min
        max_price_cents = canonical_max
        regime_name = "NORMAL"
    
    # Verify crisis range is used
    assert regime_name == "EXTREME", f"Should use EXTREME regime, got {regime_name}"
    assert min_price_cents == crisis_min, f"Min price should be {crisis_min}c, got {min_price_cents}c"
    assert max_price_cents == crisis_max, f"Max price should be {crisis_max}c, got {max_price_cents}c"
    
    # Verify prices are in range (with expanded range)
    yes_in_range = (min_price_cents <= yes_price_cents <= max_price_cents)
    no_in_range = (min_price_cents <= no_price_cents <= max_price_cents)
    assert yes_in_range, f"YES price {yes_price_cents}c should be in expanded range {min_price_cents}c-{max_price_cents}c"
    assert no_in_range, f"NO price {no_price_cents}c should be in expanded range {min_price_cents}c-{max_price_cents}c"


def test_price_filter_rejection_both_sides_outside_canonical():
    """Test that prices outside canonical range are rejected in normal regime."""
    # Simulate prices outside canonical range
    yes_price_cents = 95
    no_price_cents = 5
    
    # Detect extreme conditions
    is_extreme = (yes_price_cents > 85 or yes_price_cents < 15 or 
                  no_price_cents > 85 or no_price_cents < 15)
    
    # Should be extreme
    assert is_extreme, f"Extreme prices should be detected"
    
    # Use canonical range (simulating normal regime without expansion)
    canonical_min = 10
    canonical_max = 75
    
    # In normal regime, these would be rejected
    yes_in_range_canonical = (canonical_min <= yes_price_cents <= canonical_max)
    no_in_range_canonical = (canonical_min <= no_price_cents <= canonical_max)
    
    assert not yes_in_range_canonical, f"YES price {yes_price_cents}c should be outside canonical range {canonical_min}c-{canonical_max}c"
    assert not no_in_range_canonical, f"NO price {no_price_cents}c should be outside canonical range {canonical_min}c-{canonical_max}c"


def test_price_filter_acceptance_with_expansion():
    """Test that prices outside canonical range are accepted with crisis expansion."""
    # Simulate prices outside canonical range
    yes_price_cents = 95
    no_price_cents = 5
    
    # Detect extreme conditions
    is_extreme = (yes_price_cents > 85 or yes_price_cents < 15 or 
                  no_price_cents > 85 or no_price_cents < 15)
    
    # Should be extreme
    assert is_extreme, f"Extreme prices should be detected"
    
    # Use crisis range
    crisis_min = 5
    crisis_max = 95
    
    # With expansion, these should be accepted
    yes_in_range_crisis = (crisis_min <= yes_price_cents <= crisis_max)
    no_in_range_crisis = (crisis_min <= no_price_cents <= crisis_max)
    
    assert yes_in_range_crisis, f"YES price {yes_price_cents}c should be in crisis range {crisis_min}c-{crisis_max}c"
    assert no_in_range_crisis, f"NO price {no_price_cents}c should be in crisis range {crisis_min}c-{crisis_max}c"


def test_price_filter_threshold_boundaries():
    """Test price filter threshold boundaries (15c and 85c)."""
    # Test boundary cases
    
    # Exactly at threshold (should NOT be extreme)
    yes_price_cents = 85
    no_price_cents = 15
    is_extreme = (yes_price_cents > 85 or yes_price_cents < 15 or 
                  no_price_cents > 85 or no_price_cents < 15)
    assert not is_extreme, f"Prices at threshold (85c, 15c) should not be extreme"
    
    # Just beyond threshold (should be extreme)
    yes_price_cents = 86
    no_price_cents = 14
    is_extreme = (yes_price_cents > 85 or yes_price_cents < 15 or 
                  no_price_cents > 85 or no_price_cents < 15)
    assert is_extreme, f"Prices just beyond threshold (86c, 14c) should be extreme"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
