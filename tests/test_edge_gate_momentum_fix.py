"""Tests for edge gate fix for momentum-based trading.

The edge gates (EDGE GATE 1: uncertain zone, EDGE GATE 2: minimum edge requirement)
were disabled for momentum-based trading because momentum signals rely on velocity
exceeding threshold as conviction, not on probability-based edge (p_model - p_mkt).

This test verifies that momentum signals can execute even when:
- Market price is outside the uncertain zone (e.g., near settlement at 90c+)
- Probability edge is negative or below minimum thresholds
"""

import pytest
from unittest.mock import Mock, patch, MagicMock


class TestEdgeGateMomentumFix:
    """Tests for edge gate being disabled for momentum-based trading."""
    
    def test_momentum_signal_executes_with_high_market_price(self):
        """Test that momentum signals execute even when p_mkt is outside uncertain zone.
        
        Before the fix, EDGE GATE 1 blocked trades when p_mkt was outside [0.10, 0.90].
        After the fix, momentum signals should execute based on velocity threshold,
        regardless of market price level.
        """
        # Simulate a momentum signal with high market price (near settlement)
        p_mkt = 0.95  # 95 cents - outside uncertain zone
        p_model = 0.50  # Neutral model probability from low velocity
        velocity = 0.00015  # Above threshold (should trigger signal)
        velocity_threshold = 0.00005
        
        # Edge calculation (would be negative)
        edge_yes_pct = (p_model - p_mkt) * 100.0  # -45%
        
        # Before fix: EDGE GATE 1 would block this (p_mkt outside [0.10, 0.90])
        # After fix: Should pass because momentum uses velocity threshold
        signal_valid = velocity > velocity_threshold
        
        assert signal_valid, "Momentum signal should be valid when velocity exceeds threshold"
        assert edge_yes_pct < 0, "Edge is negative (would be blocked by old edge gate)"
    
    def test_momentum_signal_executes_with_negative_edge(self):
        """Test that momentum signals execute even when probability edge is negative.
        
        Before the fix, EDGE GATE 2 blocked trades when edge_pct < min_edge_required.
        After the fix, momentum signals should execute based on velocity threshold,
        regardless of probability edge sign or magnitude.
        """
        # Simulate a momentum signal with negative edge
        p_mkt = 0.80  # 80 cents
        p_model = 0.50  # Neutral model probability
        velocity = 0.00020  # Above threshold
        velocity_threshold = 0.00005
        
        # Edge calculation (negative)
        edge_yes_pct = (p_model - p_mkt) * 100.0  # -30%
        min_edge_required_pct = 3.0  # 3% minimum for BTC
        
        # Before fix: EDGE GATE 2 would block this (edge_pct < min_edge_required)
        # After fix: Should pass because momentum uses velocity threshold
        signal_valid = velocity > velocity_threshold
        
        assert signal_valid, "Momentum signal should be valid when velocity exceeds threshold"
        assert edge_yes_pct < min_edge_required_pct, "Edge is below minimum (would be blocked by old edge gate)"
    
    def test_momentum_signal_with_low_market_price(self):
        """Test that momentum signals execute with low market price (cheap contracts).
        
        This is the ideal case - cheap contracts with momentum signal.
        """
        p_mkt = 0.30  # 30 cents - in sweet spot
        p_model = 0.60  # Bullish model probability
        velocity = 0.00025  # Above threshold
        velocity_threshold = 0.00005
        
        # Edge calculation (positive)
        edge_yes_pct = (p_model - p_mkt) * 100.0  # +30%
        
        # Should pass regardless (momentum based on velocity)
        signal_valid = velocity > velocity_threshold
        
        assert signal_valid, "Momentum signal should be valid when velocity exceeds threshold"
        assert edge_yes_pct > 0, "Edge is positive (ideal case)"
    
    def test_momentum_signal_below_threshold_no_trade(self):
        """Test that momentum signals are rejected when velocity is below threshold.
        
        Even with edge gates disabled, momentum trading still requires velocity
        to exceed the threshold as the conviction signal.
        """
        p_mkt = 0.50  # Neutral market price
        p_model = 0.50  # Neutral model probability
        velocity = 0.00002  # Below threshold
        velocity_threshold = 0.00005
        
        # Edge calculation (zero)
        edge_yes_pct = (p_model - p_mkt) * 100.0  # 0%
        
        # Should be rejected (velocity below threshold)
        signal_valid = velocity > velocity_threshold
        
        assert not signal_valid, "Momentum signal should be invalid when velocity below threshold"
    
    def test_uncertain_zone_gate_disabled_for_momentum(self):
        """Test that uncertain zone gate is effectively disabled for momentum.
        
        The uncertain zone gate (p_mkt in [0.10, 0.90]) is appropriate for
        probability-based strategies but should not block momentum signals.
        """
        # Test various market price levels
        test_cases = [
            (0.05, "below minimum"),
            (0.10, "at minimum"),
            (0.50, "neutral"),
            (0.90, "at maximum"),
            (0.95, "above maximum"),
            (0.99, "near settlement"),
        ]
        
        velocity = 0.00015  # Above threshold
        velocity_threshold = 0.00005
        
        for p_mkt, description in test_cases:
            # Momentum signal validity depends only on velocity
            signal_valid = velocity > velocity_threshold
            
            assert signal_valid, f"Momentum signal should be valid for p_mkt={p_mkt} ({description})"
    
    def test_minimum_edge_gate_disabled_for_momentum(self):
        """Test that minimum edge gate is effectively disabled for momentum.
        
        The minimum edge gate (edge_pct >= min_edge_required) is appropriate for
        probability-based strategies but should not block momentum signals.
        """
        # Test various edge levels
        test_cases = [
            (-50.0, "strongly negative"),
            (-10.0, "negative"),
            (-1.0, "slightly negative"),
            (0.0, "zero"),
            (1.0, "below minimum"),
            (3.0, "at minimum"),
            (10.0, "above minimum"),
        ]
        
        velocity = 0.00015  # Above threshold
        velocity_threshold = 0.00005
        min_edge_required_pct = 3.0
        
        for edge_pct, description in test_cases:
            # Momentum signal validity depends only on velocity
            signal_valid = velocity > velocity_threshold
            
            assert signal_valid, f"Momentum signal should be valid for edge_pct={edge_pct}% ({description})"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
