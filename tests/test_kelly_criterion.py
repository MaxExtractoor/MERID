"""Unit tests for Kelly Criterion implementation in unified_sizing.py.

Tests the calculate_kelly_fraction function and Kelly integration in compute_order_size.
"""

import pytest
from decimal import Decimal
from merid.prediction.unified_sizing import calculate_kelly_fraction, compute_order_size


class TestCalculateKellyFraction:
    """Test Kelly fraction calculation for binary options."""
    
    def test_positive_edge(self):
        """Test Kelly calculation with positive edge (YES side)."""
        # Example: price=$0.40, model_prob=0.60
        # b = (1-0.4)/0.4 = 1.5
        # kelly = (1.5*0.6 - 0.4) / 1.5 = 0.333...
        # quarter-kelly = 0.333... * 0.25 = 0.0833...
        # With confidence=0.5, multiplier=1.25, so ~0.104
        result = calculate_kelly_fraction(
            model_prob=0.60,
            price_cents=40,
            confidence=0.5,
            fractional_kelly=0.25,
            side="yes"
        )
        assert result > 0
        assert result < 1.0
        # Full Kelly should be ~0.333, quarter-Kelly ~0.083
        # With confidence=0.5, multiplier=1.25, so ~0.104
        assert 0.09 < result < 0.12
    
    def test_negative_edge(self):
        """Test Kelly calculation with negative edge returns 0 (YES side)."""
        # Example: price=$0.50, model_prob=0.50 (no edge)
        # b = (1-0.5)/0.5 = 1.0
        # kelly = (1.0*0.5 - 0.5) / 1.0 = 0.0
        result = calculate_kelly_fraction(
            model_prob=0.50,
            price_cents=50,
            confidence=0.5,
            fractional_kelly=0.25,
            side="yes"
        )
        assert result == 0.0
    
    def test_strong_edge(self):
        """Test Kelly calculation with strong edge (YES side)."""
        # Example: price=$0.30, model_prob=0.70
        # b = (1-0.3)/0.3 = 2.33
        # kelly = (2.33*0.7 - 0.3) / 2.33 = 0.57
        # quarter-kelly = 0.57 * 0.25 = 0.14
        result = calculate_kelly_fraction(
            model_prob=0.70,
            price_cents=30,
            confidence=0.5,
            fractional_kelly=0.25,
            side="yes"
        )
        assert result > 0
        assert result < 1.0
        # Should be higher than the 0.60/0.40 case
        assert result > 0.02
    
    def test_confidence_weighting(self):
        """Test confidence weighting affects Kelly fraction."""
        # High confidence should increase Kelly
        kelly_high_conf = calculate_kelly_fraction(
            model_prob=0.60,
            price_cents=40,
            confidence=0.9,
            fractional_kelly=0.25
        )
        
        # Low confidence should decrease Kelly
        kelly_low_conf = calculate_kelly_fraction(
            model_prob=0.60,
            price_cents=40,
            confidence=0.1,
            fractional_kelly=0.25
        )
        
        assert kelly_high_conf > kelly_low_conf
    
    def test_fractional_kelly(self):
        """Test fractional Kelly parameter affects result (YES side)."""
        # Full Kelly
        kelly_full = calculate_kelly_fraction(
            model_prob=0.60,
            price_cents=40,
            confidence=0.5,
            fractional_kelly=1.0,
            side="yes"
        )
        
        # Quarter Kelly
        kelly_quarter = calculate_kelly_fraction(
            model_prob=0.60,
            price_cents=40,
            confidence=0.5,
            fractional_kelly=0.25,
            side="yes"
        )
        
        # Quarter Kelly should be 1/4 of full Kelly (approximately)
        assert kelly_quarter < kelly_full
        assert abs(kelly_quarter - kelly_full * 0.25) < 0.01
    
    def test_invalid_model_prob_clamping(self):
        """Test invalid model_prob is clamped to [0,1] (YES side)."""
        # Should clamp to 1.0
        result = calculate_kelly_fraction(
            model_prob=1.5,
            price_cents=40,
            confidence=0.5,
            fractional_kelly=0.25,
            side="yes"
        )
        assert result >= 0
        
        # Should clamp to 0.0
        result = calculate_kelly_fraction(
            model_prob=-0.5,
            price_cents=40,
            confidence=0.5,
            fractional_kelly=0.25,
            side="yes"
        )
        assert result >= 0
    
    def test_invalid_confidence_clamping(self):
        """Test invalid confidence is clamped to [0,1] (YES side)."""
        result = calculate_kelly_fraction(
            model_prob=0.60,
            price_cents=40,
            confidence=1.5,
            fractional_kelly=0.25,
            side="yes"
        )
        assert result >= 0
        
        result = calculate_kelly_fraction(
            model_prob=0.60,
            price_cents=40,
            confidence=-0.5,
            fractional_kelly=0.25,
            side="yes"
        )
        assert result >= 0
    
    def test_invalid_price(self):
        """Test invalid price returns 0 (YES side)."""
        result = calculate_kelly_fraction(
            model_prob=0.60,
            price_cents=0,
            confidence=0.5,
            fractional_kelly=0.25,
            side="yes"
        )
        assert result == 0.0
        
        result = calculate_kelly_fraction(
            model_prob=0.60,
            price_cents=100,  # $1.00 (invalid for binary)
            confidence=0.5,
            fractional_kelly=0.25,
            side="yes"
        )
        assert result == 0.0


class TestComputeOrderSizeKellyIntegration:
    """Test Kelly integration in compute_order_size function."""
    
    def test_kelly_filter_rejects_no_edge(self):
        """Test Kelly filter rejects trades with no edge (YES side)."""
        count, notional, metadata = compute_order_size(
            bankroll_usd=Decimal("100.00"),
            price_cents=50,
            asset="BTC",
            model_prob=0.50,  # No edge at 50c
            confidence=Decimal("0.5"),
            side="yes"
        )
        
        assert count == 0
        assert notional == Decimal("0")
        assert metadata["reason"] == "kelly_no_edge"
        assert metadata["model_prob"] == 0.50
        assert metadata["kelly_fraction"] == 0.0
    
    def test_kelly_filter_allows_positive_edge(self):
        """Test Kelly filter allows trades with positive edge."""
        count, notional, metadata = compute_order_size(
            bankroll_usd=Decimal("100.00"),
            price_cents=40,
            asset="BTC",
            model_prob=0.60,  # Positive edge at 40c
            confidence=Decimal("0.5")
        )
        
        # Should not be rejected by Kelly filter
        # May be rejected by slot allocation if no slots available
        assert metadata.get("reason") != "kelly_no_edge"
        if count > 0:
            assert "kelly_fraction" in metadata
            assert metadata["kelly_fraction"] > 0
    
    def test_kelly_metadata_included(self):
        """Test Kelly metadata is included in result when model_prob provided."""
        count, notional, metadata = compute_order_size(
            bankroll_usd=Decimal("100.00"),
            price_cents=40,
            asset="BTC",
            model_prob=0.60,
            confidence=Decimal("0.8")
        )
        
        assert "model_prob" in metadata
        assert "confidence" in metadata
        assert "kelly_fraction" in metadata
        assert metadata["model_prob"] == 0.60
        assert metadata["confidence"] == 0.8
    
    def test_no_model_prob_skips_kelly(self):
        """Test that without model_prob, Kelly filter is skipped (YES side)."""
        count, notional, metadata = compute_order_size(
            bankroll_usd=Decimal("100.00"),
            price_cents=40,
            asset="BTC",
            model_prob=None,  # No model_prob
            confidence=Decimal("0.5"),
            side="yes"
        )
        
        # Should not have Kelly-related metadata
        assert "kelly_fraction" not in metadata
        assert "model_prob" not in metadata
    
    def test_kelly_with_slot_allocation(self):
        """Test Kelly works with slot allocation (YES side)."""
        # This test assumes slot allocator is available
        # If not, it will fall back to position cache
        count, notional, metadata = compute_order_size(
            bankroll_usd=Decimal("100.00"),
            price_cents=35,
            asset="BTC",
            model_prob=0.65,
            confidence=Decimal("0.7"),
            side="yes"
        )
        
        # Kelly should allow this trade
        assert metadata.get("reason") != "kelly_no_edge"
        if count > 0:
            assert metadata["kelly_fraction"] > 0


class TestKellyEdgeCases:
    """Test edge cases for Kelly calculation."""
    
    def test_break_even_probability(self):
        """Test Kelly at break-even probability (YES side)."""
        # At 50c price, break-even is 50% probability
        result = calculate_kelly_fraction(
            model_prob=0.50,
            price_cents=50,
            confidence=0.5,
            fractional_kelly=0.25,
            side="yes"
        )
        assert result == 0.0
    
    def test_very_high_probability(self):
        """Test Kelly with very high probability."""
        result = calculate_kelly_fraction(
            model_prob=0.90,
            price_cents=20,
            confidence=0.8,
            fractional_kelly=0.25
        )
        # Should be positive but capped at 1.0
        assert 0 < result <= 1.0
    
    def test_very_low_probability(self):
        """Test Kelly with very low probability (YES side)."""
        result = calculate_kelly_fraction(
            model_prob=0.10,
            price_cents=80,
            confidence=0.3,
            fractional_kelly=0.25,
            side="yes"
        )
        # Should be 0 (negative edge)
        assert result == 0.0
    
    def test_confidence_extremes(self):
        """Test confidence at extremes (0.0 and 1.0) (YES side)."""
        # Confidence 0.0 should give minimum multiplier (0.5)
        kelly_min = calculate_kelly_fraction(
            model_prob=0.60,
            price_cents=40,
            confidence=0.0,
            fractional_kelly=0.25,
            side="yes"
        )
        
        # Confidence 1.0 should give maximum multiplier (2.0)
        kelly_max = calculate_kelly_fraction(
            model_prob=0.60,
            price_cents=40,
            confidence=1.0,
            fractional_kelly=0.25,
            side="yes"
        )
        
        # Max should be 4x min (2.0 / 0.5 = 4)
        assert kelly_max > kelly_min
        assert abs(kelly_max / kelly_min - 4.0) < 0.1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
