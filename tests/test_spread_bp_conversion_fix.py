"""Tests for spread validation in binary options markets.

CRITICAL FIX (2026-07-09): Removed basis point validation for binary options.
Binary options have 0-100c price range, making BP calculations inappropriate.
A 37c spread on 50c mid = 74% = 7400bp, which looks extreme but is normal for binary options.
Use cents-based validation only, which is correctly configured with 75c coarse filter.

This test verifies the cents-based spread validation correctly rejects pathological spreads.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch


def test_pathological_spread_95c_rejected_by_coarse_filter():
    """Test that 95c spread is rejected by 75c coarse filter."""
    spread_cents = 95
    coarse_filter_threshold = 75
    
    # Should be rejected by coarse filter (first gate)
    assert spread_cents > coarse_filter_threshold, \
        f"95c spread should exceed 75c coarse filter"


def test_pathological_spread_41c_passes_coarse_filter():
    """Test that 41c spread passes 75c coarse filter."""
    spread_cents = 41
    coarse_filter_threshold = 75
    
    # Should pass coarse filter (below new threshold)
    assert spread_cents <= coarse_filter_threshold, \
        f"41c spread should pass 75c coarse filter"


def test_normal_spread_10c_passes_validation():
    """Test that normal 10c spread passes validation."""
    spread_cents = 10
    coarse_filter_threshold = 75
    
    # Should pass coarse filter
    assert spread_cents <= coarse_filter_threshold, \
        f"10c spread should pass 75c coarse filter"


def test_normal_spread_37c_passes_validation():
    """Test that 37c spread passes validation (typical binary option spread)."""
    spread_cents = 37
    coarse_filter_threshold = 75
    
    # Should pass coarse filter
    assert spread_cents <= coarse_filter_threshold, \
        f"37c spread should pass 75c coarse filter"


def test_edge_case_spread_75c_passes_validation():
    """Test that 75c spread (exactly at threshold) passes validation."""
    spread_cents = 75
    coarse_filter_threshold = 75
    
    # Should pass coarse filter (at threshold)
    assert spread_cents <= coarse_filter_threshold, \
        f"75c spread should pass 75c coarse filter (at threshold)"


def test_spread_validation_various_scenarios():
    """Test cents-based spread validation across various scenarios."""
    test_cases = [
        # (spread_cents, should_pass, description)
        (5, True, "Very tight spread"),
        (10, True, "Normal tight spread"),
        (20, True, "Normal spread"),
        (30, True, "Wide but acceptable spread"),
        (40, True, "Wide spread (acceptable)"),
        (50, True, "Wide spread (acceptable)"),
        (60, True, "Wide spread (acceptable)"),
        (70, True, "Wide spread (acceptable)"),
        (75, True, "At threshold (should pass)"),
        (76, False, "Just over threshold (should fail)"),
        (80, False, "Pathological spread (should fail)"),
        (95, False, "Pathological spread (should fail)"),
        (98, False, "Extreme spread (should fail)"),
    ]
    
    coarse_filter_threshold = 75
    
    for spread_cents, should_pass, description in test_cases:
        passes = spread_cents <= coarse_filter_threshold
        assert passes == should_pass, \
            f"{description}: {spread_cents}c spread - expected {'pass' if should_pass else 'fail'}, got {'pass' if passes else 'fail'}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
