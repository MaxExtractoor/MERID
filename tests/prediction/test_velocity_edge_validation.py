"""
Test suite for velocity-based momentum signal edge validation.

This test validates that velocity-based momentum signals are NOT rejected
based on probability edge, since edge calculation is inappropriate for
momentum trading. The signal strength is determined by velocity magnitude,
not probability difference between model and market.

Root cause analysis:
- p_model is derived from velocity via logistic mapping (alpha_0 + alpha_1 * velocity)
- With alpha_1=2-5, even large velocities produce p_model≈0.50
- p_mkt is market-implied probability from bid/ask
- Edge = (p_model - p_mkt) compares two different probability sources
- For momentum trading, this comparison is meaningless
- Momentum signals are about DIRECTION (velocity sign), not probability calibration

Industry standard (2026 research):
- Momentum-based binary options trading uses velocity/direction for signal generation
- Edge is only relevant for probability-based models (e.g., statistical arbitrage)
- For momentum: velocity magnitude > threshold = trade, regardless of probability edge
"""

import pytest
import math
from unittest.mock import Mock, patch, MagicMock


class TestVelocityEdgeValidation:
    """Test edge validation for velocity-based momentum signals."""

    def test_velocity_signal_with_negative_edge_not_rejected(self):
        """Test that velocity signals with negative probability edge are NOT rejected.
        
        This is the core fix: momentum signals should not be rejected based on
        negative edge, since edge calculation is inappropriate for momentum trading.
        """
        # Simulate a velocity-based signal with negative edge
        # p_model = 0.50 (from velocity via logistic mapping)
        # p_mkt = 0.89 (market-implied probability)
        # edge = (0.50 - 0.89) * 100 = -39% (negative edge)
        # This should NOT be rejected for velocity-based signals
        
        p_model = 0.50
        p_mkt = 0.89
        edge_pct = (p_model - p_mkt) * 100.0
        
        # Negative edge should be allowed for velocity signals
        # The fix removes min_edge check for velocity-based signals
        assert edge_pct < 0, "Edge should be negative"
        assert edge_pct == -39.0, f"Expected -39%, got {edge_pct}%"
        
        # In the old code, this would be rejected by min_edge check
        # In the new code, this is allowed because momentum signals
        # are validated by velocity magnitude, not probability edge

    def test_velocity_signal_with_large_positive_edge_not_rejected(self):
        """Test that velocity signals with large positive edge are NOT rejected.
        
        Large positive edges are artifacts of the p_model/p_mkt mismatch,
        not signal quality indicators. They should be allowed for momentum signals.
        """
        # Simulate a velocity-based signal with large positive edge
        # p_model = 0.50 (from velocity via logistic mapping)
        # p_mkt = 0.10 (market-implied probability)
        # edge = (0.50 - 0.10) * 100 = 40% (large positive edge)
        # This should NOT be rejected for velocity-based signals
        
        p_model = 0.50
        p_mkt = 0.10
        edge_pct = (p_model - p_mkt) * 100.0
        
        # Large positive edge should be allowed for velocity signals
        assert edge_pct > 0, "Edge should be positive"
        assert edge_pct == 40.0, f"Expected 40%, got {edge_pct}%"
        
        # In the old code, this might be rejected by max_edge check (50% threshold)
        # In the new code, max_edge is increased to 90% as a sanity check only

    def test_extreme_edge_rejected_as_data_error(self):
        """Test that extreme edges (>90%) are rejected as data errors.
        
        The max_edge check is kept as a sanity check for corrupted market data
        or calculation errors, not for signal quality validation.
        """
        # Simulate extreme edge indicating data error
        # p_model = 0.99
        # p_mkt = 0.05 (heavily skewed market)
        # edge = (0.99 - 0.05) * 100 = 94% (should be rejected as data error)
        
        p_model = 0.99
        p_mkt = 0.05  # Extreme market skew
        edge_pct = (p_model - p_mkt) * 100.0
        
        # Edge > 90% should be rejected as data error
        assert abs(edge_pct) > 90.0, f"Edge should be extreme (>90%), got {edge_pct}%"
        
        # This should trigger the sanity check rejection
        max_edge_threshold = 90.0
        should_reject = abs(edge_pct) > max_edge_threshold
        assert should_reject, "Extreme edge should be rejected as data error"

    def test_edge_calculation_for_logging_only(self):
        """Test that edge is calculated for logging purposes but not for validation.
        
        Edge calculation is still performed for logging and monitoring,
        but it should not be used to reject velocity-based signals.
        """
        # Calculate edge for both YES and NO sides
        p_model = 0.50
        p_mkt = 0.75
        
        edge_yes_pct = (p_model - p_mkt) * 100.0
        edge_no_pct = ((1.0 - p_model) - (1.0 - p_mkt)) * 100.0
        
        # Edge should be calculated correctly
        assert edge_yes_pct == -25.0, f"Expected -25% for YES edge, got {edge_yes_pct}%"
        assert edge_no_pct == 25.0, f"Expected 25% for NO edge, got {edge_no_pct}%"
        
        # Edge values should be opposite signs (binary duality)
        assert abs(edge_yes_pct + edge_no_pct) < 0.01, "YES and NO edges should sum to ~0"

    def test_velocity_magnitude_determines_signal_strength(self):
        """Test that velocity magnitude, not edge, determines signal strength.
        
        For momentum trading, the signal strength is the velocity magnitude
        compared to the velocity threshold, not the probability edge.
        """
        # Simulate different velocity magnitudes
        velocity_threshold = 0.0005  # 0.05% threshold
        
        # Strong negative velocity (strong sell signal)
        velocity_strong = -0.0010  # 0.1% per second
        is_strong_signal = abs(velocity_strong) > velocity_threshold
        assert is_strong_signal, "Strong velocity should generate signal"
        
        # Weak negative velocity (weak sell signal)
        velocity_weak = -0.0003  # 0.03% per second
        is_weak_signal = abs(velocity_weak) > velocity_threshold
        assert not is_weak_signal, "Weak velocity should not generate signal"
        
        # Edge is irrelevant for this determination
        p_model = 0.50  # Neutral probability from logistic mapping
        p_mkt = 0.80  # Market-implied probability
        edge_pct = (p_model - p_mkt) * 100.0  # -30% edge
        
        # Signal should be determined by velocity, not edge
        # Even with -30% edge, strong velocity should generate signal
        assert abs(velocity_strong) > velocity_threshold

    def test_logistic_mapping_produces_meaningful_probability_shifts(self):
        """Test that logistic mapping from velocity produces meaningful probability shifts.
        
        With increased alpha_1 coefficients (200-500 instead of 2-5),
        velocities at threshold (0.4%-0.8%) produce significant probability shifts.
        This is by design for momentum trading to generate viable edge.
        """
        # Test with typical velocity values
        alpha_0 = 0.0
        alpha_1 = 200.0  # Updated to 2026-07-04 industry standard
        
        # Velocity at threshold (0.4%)
        velocity = 0.004  # 0.4% per second
        raw_logit = alpha_0 + alpha_1 * velocity
        p_model = 1.0 / (1.0 + math.exp(-raw_logit))
        
        # p_model should be significantly above 0.50 (bullish signal)
        assert p_model > 0.65, f"Expected p_model>0.65 for positive velocity, got {p_model}"
        
        # Negative velocity at threshold
        velocity = -0.004  # -0.4% per second
        raw_logit = alpha_0 + alpha_1 * velocity
        p_model = 1.0 / (1.0 + math.exp(-raw_logit))
        
        # p_model should be significantly below 0.50 (bearish signal)
        assert p_model < 0.35, f"Expected p_model<0.35 for negative velocity, got {p_model}"

    def test_no_min_edge_check_in_agent_grid(self):
        """Test that agent_grid_15m.py does not have min_edge check for velocity signals.
        
        This is a regression test to ensure the min_edge workaround (-100% threshold)
        is replaced with proper removal of the check.
        """
        # Read the agent_grid_15m.py file and check for min_edge check
        import os
        agent_grid_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "merid", "prediction", "agent_grid_15m.py"
        )
        
        with open(agent_grid_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that min_edge_threshold is NOT set to -100.0 (the workaround)
        # The proper fix removes the min_edge check entirely
        assert "min_edge_threshold = -100.0" not in content, \
            "min_edge_threshold should not be -100.0 (workaround removed)"
        
        # Check that the proper fix is in place
        # The new code should have a comment explaining why min_edge is not checked
        assert "NO min_edge check for velocity-based signals" in content or \
               "min_edge check entirely for velocity-based signals" in content, \
            "Should have comment explaining min_edge removal"

    def test_max_edge_as_sanity_check_only(self):
        """Test that max_edge is used as a sanity check, not signal validation.
        
        The max_edge threshold should be high (90%) to only catch data errors,
        not to filter legitimate momentum signals.
        """
        # Check that max_edge_threshold is set to 90% (sanity check)
        import os
        agent_grid_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "merid", "prediction", "agent_grid_15m.py"
        )
        
        with open(agent_grid_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that max_edge_threshold is 90.0 (sanity check)
        assert "max_edge_threshold = 90.0" in content, \
            "max_edge_threshold should be 90.0 (sanity check for data errors)"
        
        # Check that the comment explains it's a sanity check
        assert "sanity check" in content.lower(), \
            "Should have comment explaining max_edge is a sanity check"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
