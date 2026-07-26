"""
Unit tests for liquidity-first filtering based on SimpleFunctions best practices.

Tests the liquidity-first filtering function that prioritizes markets with
tight spreads and high volume based on industry research thresholds.
"""

import pytest
from merid.event_venues.kalshi.spread_edge_analytics import check_liquidity_first_filter


def test_liquidity_first_filter_high_liquidity():
    """Test HIGH liquidity score (≤2¢ spread, ≥500 depth)."""
    spread_cents = 1
    depth_within_3c = 1000
    
    passes, score, reason = check_liquidity_first_filter(spread_cents, depth_within_3c)
    
    assert passes is True, f"Should pass with HIGH liquidity"
    assert score == "HIGH", f"Should have HIGH score, got {score}"
    assert "≤ 2c" in reason, f"Reason should mention spread threshold"
    assert "≥ 500" in reason, f"Reason should mention depth threshold"


def test_liquidity_first_filter_high_liquidity_boundary():
    """Test HIGH liquidity at boundary (2¢ spread, 500 depth)."""
    spread_cents = 2
    depth_within_3c = 500
    
    passes, score, reason = check_liquidity_first_filter(spread_cents, depth_within_3c)
    
    assert passes is True, f"Should pass at HIGH boundary"
    assert score == "HIGH", f"Should have HIGH score at boundary"


def test_liquidity_first_filter_medium_liquidity():
    """Test MEDIUM liquidity score (≤5¢ spread, ≥100 depth)."""
    spread_cents = 3
    depth_within_3c = 200
    
    passes, score, reason = check_liquidity_first_filter(spread_cents, depth_within_3c)
    
    assert passes is False, f"Should reject MEDIUM liquidity (liquidity-first only accepts HIGH)"
    assert score == "MEDIUM", f"Should have MEDIUM score, got {score}"
    assert "MEDIUM" in reason, f"Reason should mention MEDIUM score"
    assert "only HIGH accepted" in reason, f"Reason should explain rejection"


def test_liquidity_first_filter_medium_liquidity_boundary():
    """Test MEDIUM liquidity at boundary (5¢ spread, 100 depth)."""
    spread_cents = 5
    depth_within_3c = 100
    
    passes, score, reason = check_liquidity_first_filter(spread_cents, depth_within_3c)
    
    assert passes is False, f"Should reject MEDIUM at boundary"
    assert score == "MEDIUM", f"Should have MEDIUM score at boundary"


def test_liquidity_first_filter_low_liquidity_wide_spread():
    """Test LOW liquidity due to wide spread (>5¢)."""
    spread_cents = 6
    depth_within_3c = 1000
    
    passes, score, reason = check_liquidity_first_filter(spread_cents, depth_within_3c)
    
    assert passes is False, f"Should reject LOW liquidity"
    assert score == "LOW", f"Should have LOW score, got {score}"
    assert "> 5c" in reason, f"Reason should mention wide spread"


def test_liquidity_first_filter_low_liquidity_shallow_depth():
    """Test LOW liquidity due to shallow depth (<100)."""
    spread_cents = 2
    depth_within_3c = 50
    
    passes, score, reason = check_liquidity_first_filter(spread_cents, depth_within_3c)
    
    assert passes is False, f"Should reject LOW liquidity"
    assert score == "LOW", f"Should have LOW score, got {score}"
    assert "< 100" in reason, f"Reason should mention shallow depth"


def test_liquidity_first_filter_low_liquidity_both():
    """Test LOW liquidity due to both wide spread and shallow depth."""
    spread_cents = 10
    depth_within_3c = 10
    
    passes, score, reason = check_liquidity_first_filter(spread_cents, depth_within_3c)
    
    assert passes is False, f"Should reject LOW liquidity"
    assert score == "LOW", f"Should have LOW score"


def test_liquidity_first_filter_custom_thresholds():
    """Test liquidity-first filtering with custom thresholds."""
    spread_cents = 3
    depth_within_3c = 400
    
    # Default thresholds (2c, 500) would reject this
    passes_default, _, _ = check_liquidity_first_filter(spread_cents, depth_within_3c)
    assert passes_default is False, f"Should reject with default thresholds"
    
    # Custom thresholds (3c, 400) should accept this
    passes_custom, score, _ = check_liquidity_first_filter(
        spread_cents, depth_within_3c, min_spread_cents=3, min_depth_contracts=400
    )
    assert passes_custom is True, f"Should pass with custom thresholds"
    assert score == "HIGH", f"Should have HIGH score with custom thresholds"


def test_liquidity_first_filter_zero_depth():
    """Test liquidity-first filtering with zero depth."""
    spread_cents = 1
    depth_within_3c = 0
    
    passes, score, reason = check_liquidity_first_filter(spread_cents, depth_within_3c)
    
    assert passes is False, f"Should reject with zero depth"
    assert score == "LOW", f"Should have LOW score with zero depth"


def test_liquidity_first_filter_edge_cases():
    """Test edge cases for liquidity-first filtering."""
    # Case 1: Tight spread but just below depth threshold
    passes, score, _ = check_liquidity_first_filter(1, 499)
    assert passes is False, f"Should reject 499 depth (below 500 threshold)"
    assert score == "MEDIUM", f"Should be MEDIUM (spread OK, depth insufficient)"
    
    # Case 2: Sufficient depth but just above spread threshold
    passes, score, _ = check_liquidity_first_filter(3, 500)
    assert passes is False, f"Should reject 3c spread (above 2c threshold)"
    assert score == "MEDIUM", f"Should be MEDIUM (depth OK, spread too wide)"
    
    # Case 3: Exactly at HIGH thresholds
    passes, score, _ = check_liquidity_first_filter(2, 500)
    assert passes is True, f"Should accept at exact HIGH thresholds"
    assert score == "HIGH", f"Should be HIGH at exact thresholds"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
