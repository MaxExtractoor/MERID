"""
Tests for position sizing functions.

Tests edge_to_size_fraction, volatility_adjusted_fraction, and correlation_adjusted_fraction.
"""

import pytest
from merid.event_venues.kalshi.position_sizer import (
    edge_to_size_fraction,
    volatility_adjusted_fraction,
    correlation_adjusted_fraction,
)


class TestEdgeToSizeFraction:
    """Test edge-to-size mapping function."""
    
    def test_edge_to_size_basic(self):
        """Test basic edge-to-size mapping."""
        # 1% edge with k1=0.05 → 5% capital, but clipped to max 3%
        f = edge_to_size_fraction(1.0, k1=0.05)
        assert f == 0.03  # Clipped to max
        
        # 0.5% edge with k1=0.05 → 2.5% capital (within bounds)
        f = edge_to_size_fraction(0.5, k1=0.05)
        assert f == 0.025
    
    def test_edge_to_size_clipping(self):
        """Test clipping to min/max bounds."""
        # Very small edge should be clipped to min
        f = edge_to_size_fraction(0.01, k1=0.05, min_fraction=0.005)
        assert f == 0.005  # Clipped to min
        
        # Very large edge should be clipped to max
        f = edge_to_size_fraction(10.0, k1=0.05, max_fraction=0.03)
        assert f == 0.03  # Clipped to max
    
    def test_edge_to_size_within_bounds(self):
        """Test edge within bounds is not clipped."""
        # 3% edge with k1=0.05 → 15% capital, clipped to 3% max
        f = edge_to_size_fraction(3.0, k1=0.05, max_fraction=0.03)
        assert f == 0.03
        
        # 0.5% edge with k1=0.05 → 2.5% capital, above min
        f = edge_to_size_fraction(0.5, k1=0.05, min_fraction=0.005)
        assert f == 0.025
    
    def test_edge_to_size_custom_k1(self):
        """Test custom k1 multiplier."""
        # k1=0.10 → 10% capital per 1% edge, but clipped to max 3%
        f = edge_to_size_fraction(1.0, k1=0.10)
        assert f == 0.03  # Clipped to max
        
        # With higher max, should not clip
        f = edge_to_size_fraction(1.0, k1=0.10, max_fraction=0.20)
        assert f == 0.10
    
    def test_edge_to_size_zero_edge(self):
        """Test zero edge returns min fraction."""
        f = edge_to_size_fraction(0.0, k1=0.05, min_fraction=0.005)
        assert f == 0.005


class TestVolatilityAdjustedFraction:
    """Test volatility adjustment function."""
    
    def test_volatility_adjusted_low(self):
        """Test LOW volatility (no reduction)."""
        f = volatility_adjusted_fraction(0.10, "LOW")
        assert f == 0.10  # 100% of base
    
    def test_volatility_adjusted_normal(self):
        """Test NORMAL volatility (20% reduction)."""
        f = volatility_adjusted_fraction(0.10, "NORMAL")
        assert f == pytest.approx(0.08)  # 80% of base
    
    def test_volatility_adjusted_high(self):
        """Test HIGH volatility (50% reduction)."""
        f = volatility_adjusted_fraction(0.10, "HIGH")
        assert f == 0.05  # 50% of base
    
    def test_volatility_adjusted_extreme(self):
        """Test EXTREME volatility (75% reduction)."""
        f = volatility_adjusted_fraction(0.10, "EXTREME")
        assert f == 0.025  # 25% of base
    
    def test_volatility_adjusted_unknown(self):
        """Test unknown regime defaults to NORMAL."""
        f = volatility_adjusted_fraction(0.10, "UNKNOWN")
        assert f == pytest.approx(0.08)  # Defaults to NORMAL (80%)
    
    def test_volatility_adjusted_custom_multipliers(self):
        """Test custom multipliers."""
        custom_multipliers = {
            "LOW": 1.0,
            "NORMAL": 0.5,
            "HIGH": 0.25,
        }
        
        f = volatility_adjusted_fraction(0.10, "NORMAL", custom_multipliers)
        assert f == 0.05  # 50% of base


class TestCorrelationAdjustedFraction:
    """Test correlation adjustment function."""
    
    def test_correlation_adjusted_sufficient_risk(self):
        """Test when sufficient category risk available."""
        # 3% position, 25% used, 30% max → 5% available
        f = correlation_adjusted_fraction(
            base_fraction=0.03,
            current_category_allocation_pct=0.25,
            max_category_allocation_pct=0.30,
        )
        assert f == 0.03  # Not capped
    
    def test_correlation_adjusted_capped(self):
        """Test when position exceeds available risk."""
        # 5% position, 28% used, 30% max → 2% available
        f = correlation_adjusted_fraction(
            base_fraction=0.05,
            current_category_allocation_pct=0.28,
            max_category_allocation_pct=0.30,
        )
        assert f == pytest.approx(0.02)  # Capped to available
    
    def test_correlation_adjusted_at_limit(self):
        """Test when at category limit."""
        # 3% position, 30% used, 30% max → 0% available
        f = correlation_adjusted_fraction(
            base_fraction=0.03,
            current_category_allocation_pct=0.30,
            max_category_allocation_pct=0.30,
        )
        assert f == 0.0  # No risk available
    
    def test_correlation_adjusted_over_limit(self):
        """Test when already over category limit."""
        # 3% position, 35% used, 30% max → negative available
        f = correlation_adjusted_fraction(
            base_fraction=0.03,
            current_category_allocation_pct=0.35,
            max_category_allocation_pct=0.30,
        )
        assert f == 0.0  # Clipped to 0
    
    def test_correlation_adjusted_custom_max(self):
        """Test custom max category allocation."""
        f = correlation_adjusted_fraction(
            base_fraction=0.05,
            current_category_allocation_pct=0.20,
            max_category_allocation_pct=0.50,  # 50% max
        )
        assert f == 0.05  # Not capped (30% available)
    
    def test_correlation_adjusted_zero_allocation(self):
        """Test with zero current allocation."""
        f = correlation_adjusted_fraction(
            base_fraction=0.03,
            current_category_allocation_pct=0.0,
            max_category_allocation_pct=0.30,
        )
        assert f == 0.03  # Not capped (30% available)
