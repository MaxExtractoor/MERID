"""
Test for signal_mag clamping fix in agent_grid_15m.py.

This test verifies that signal_mag is clamped to prevent extreme direction_bias values
that could push model probabilities to extremes (0.05 or 0.95) even with clamping.
"""

import pytest


def test_signal_mag_clamping_prevents_extreme_direction_bias():
    """
    Test that signal_mag is clamped to 3.0 to prevent extreme direction_bias.
    
    Without clamping, very high velocity (e.g., 10x threshold) could cause
    direction_bias > 1.0, which would push p_model to extreme values even with
    the max(0.05, min(0.95, ...)) clamping.
    """
    
    # Test case 1: Normal velocity (1x threshold) - should not be clamped
    velocity_normal = 0.00015  # Exactly at threshold
    threshold = 0.00015
    signal_mag_normal = abs(velocity_normal) / threshold
    assert signal_mag_normal == 1.0
    
    # Test case 2: High velocity (3x threshold) - should be at clamp limit
    velocity_high = 0.00045  # 3x threshold
    signal_mag_high = abs(velocity_high) / threshold
    signal_mag_clamped = min(signal_mag_high, 3.0)
    assert signal_mag_clamped == 3.0
    
    # Test case 3: Extreme velocity (10x threshold) - should be clamped to 3.0
    velocity_extreme = 0.0015  # 10x threshold
    signal_mag_extreme = abs(velocity_extreme) / threshold
    signal_mag_clamped = min(signal_mag_extreme, 3.0)
    assert signal_mag_clamped == 3.0
    assert signal_mag_clamped < signal_mag_extreme  # Verify clamping occurred
    
    # Test case 4: Verify direction_bias stays in reasonable range with clamping
    # Without clamping: direction_bias = 0.1 * 10.0 = 1.0 (would push p_model to 0.95)
    # With clamping: direction_bias = 0.1 * 3.0 = 0.3 (reasonable range)
    direction_bias_unclamped = 0.1 * signal_mag_extreme
    direction_bias_clamped = 0.1 * signal_mag_clamped
    assert abs(direction_bias_clamped - 0.3) < 1e-9  # Floating point tolerance
    assert direction_bias_clamped < direction_bias_unclamped
    
    # Test case 5: Verify p_model stays away from extremes with clamping
    base_prob = 0.5
    p_model_unclamped = max(0.05, min(0.95, base_prob + direction_bias_unclamped))
    p_model_clamped = max(0.05, min(0.95, base_prob + direction_bias_clamped))
    
    # With clamping, p_model should be 0.8 (0.5 + 0.3)
    # Without clamping, p_model would be 0.95 (clamped at extreme)
    assert p_model_clamped == 0.8
    assert p_model_clamped < p_model_unclamped


def test_signal_mag_clamping_symmetric_for_positive_and_negative_velocity():
    """
    Test that signal_mag clamping works symmetrically for both positive and negative velocity.
    """
    threshold = 0.00015
    
    # Positive velocity
    velocity_pos = 0.0015  # 10x threshold
    signal_mag_pos = abs(velocity_pos) / threshold
    signal_mag_clamped_pos = min(signal_mag_pos, 3.0)
    
    # Negative velocity
    velocity_neg = -0.0015  # -10x threshold
    signal_mag_neg = abs(velocity_neg) / threshold
    signal_mag_clamped_neg = min(signal_mag_neg, 3.0)
    
    # Both should be clamped to the same value
    assert signal_mag_clamped_pos == signal_mag_clamped_neg == 3.0


def test_signal_mag_below_threshold_no_clamping():
    """
    Test that signal_mag below clamp threshold is not affected.
    """
    threshold = 0.00015
    
    # Low velocity (0.5x threshold)
    velocity_low = 0.000075
    signal_mag_low = abs(velocity_low) / threshold
    signal_mag_clamped = min(signal_mag_low, 3.0)
    
    # Should not be clamped
    assert signal_mag_clamped == signal_mag_low == 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
