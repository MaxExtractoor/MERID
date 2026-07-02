"""
Unit tests for horizon-aware probability calibration.
Tests Phase 5.3: Horizon-aware calibration based on 2026 research.
"""

import pytest
import math


def test_horizon_factor_calculation():
    """Test horizon factor calculation for different time horizons."""
    
    # Test 15-minute market (0.25 hours)
    horizon_hours = 0.25
    horizon_factor = 1.0 + 0.08 * math.log(max(0.1, horizon_hours))
    # Expected: 1 + 0.08 * ln(0.25) = 1 + 0.08 * (-1.386) = 0.889
    assert abs(horizon_factor - 0.889) < 0.01
    
    # Test 1-hour market
    horizon_hours = 1.0
    horizon_factor = 1.0 + 0.08 * math.log(max(0.1, horizon_hours))
    # Expected: 1 + 0.08 * ln(1) = 1 + 0 = 1.0
    assert abs(horizon_factor - 1.0) < 0.01
    
    # Test 24-hour market
    horizon_hours = 24.0
    horizon_factor = 1.0 + 0.08 * math.log(max(0.1, horizon_hours))
    # Expected: 1 + 0.08 * ln(24) = 1 + 0.08 * 3.178 = 1.254
    assert abs(horizon_factor - 1.254) < 0.01


def test_crypto_slope_calibration():
    """Test domain-specific slope for crypto markets."""
    
    # Research shows crypto markets have slope ~1.08
    crypto_slope = 1.08
    
    # Test calibration with crypto slope
    p_model = 0.50
    logit_p = math.log(p_model / (1.0 - p_model)) if p_model > 0 and p_model < 1 else 0.0
    adjusted_logit = crypto_slope * logit_p
    calibrated_p = 1.0 / (1.0 + math.exp(-adjusted_logit))
    
    # For p=0.50, logit=0, so calibrated_p should still be 0.50
    assert abs(calibrated_p - 0.50) < 0.01
    
    # Test with higher probability
    p_model = 0.70
    logit_p = math.log(p_model / (1.0 - p_model))
    adjusted_logit = crypto_slope * logit_p
    calibrated_p = 1.0 / (1.0 + math.exp(-adjusted_logit))
    
    # With slope > 1, probability should increase
    assert calibrated_p > p_model
    assert calibrated_p < 0.99  # Should be clamped


def test_horizon_aware_calibration_formula():
    """Test the complete horizon-aware calibration formula."""
    
    # Test for 15-minute market with crypto slope
    p_model = 0.60
    horizon_hours = 0.25
    crypto_slope = 1.08
    
    # Calculate horizon factor
    horizon_factor = 1.0 + 0.08 * math.log(max(0.1, horizon_hours))
    
    # Apply full calibration
    logit_p = math.log(p_model / (1.0 - p_model))
    adjusted_logit = crypto_slope * horizon_factor * logit_p
    horizon_calibrated_p = 1.0 / (1.0 + math.exp(-adjusted_logit))
    
    # Clamp to valid range
    horizon_calibrated_p = max(0.01, min(0.99, horizon_calibrated_p))
    
    # Result should be in valid range
    assert 0.01 <= horizon_calibrated_p <= 0.99
    
    # For 15-minute markets, horizon factor < 1, so probability should be slightly reduced
    # But crypto slope > 1, so net effect depends on values
    assert isinstance(horizon_calibrated_p, float)


def test_calibration_edge_cases():
    """Test calibration with edge case probabilities."""
    
    crypto_slope = 1.08
    horizon_factor = 0.889  # 15-minute market
    
    # Test p_model = 0.01 (minimum)
    p_model = 0.01
    logit_p = math.log(p_model / (1.0 - p_model))
    adjusted_logit = crypto_slope * horizon_factor * logit_p
    calibrated_p = 1.0 / (1.0 + math.exp(-adjusted_logit))
    calibrated_p = max(0.01, min(0.99, calibrated_p))
    assert calibrated_p >= 0.01
    
    # Test p_model = 0.99 (maximum)
    p_model = 0.99
    logit_p = math.log(p_model / (1.0 - p_model))
    adjusted_logit = crypto_slope * horizon_factor * logit_p
    calibrated_p = 1.0 / (1.0 + math.exp(-adjusted_logit))
    calibrated_p = max(0.01, min(0.99, calibrated_p))
    assert calibrated_p <= 0.99
    
    # Test p_model = 0.50 (neutral)
    p_model = 0.50
    logit_p = 0.0  # log(0.5/0.5) = 0
    adjusted_logit = crypto_slope * horizon_factor * logit_p
    calibrated_p = 1.0 / (1.0 + math.exp(-adjusted_logit))
    calibrated_p = max(0.01, min(0.99, calibrated_p))
    assert abs(calibrated_p - 0.50) < 0.01


def test_calibration_clamping():
    """Test that calibration results are properly clamped."""
    
    crypto_slope = 1.08
    horizon_factor = 0.889
    
    # Test extreme case that would produce probability > 0.99
    p_model = 0.95
    logit_p = math.log(p_model / (1.0 - p_model))
    adjusted_logit = crypto_slope * horizon_factor * logit_p
    calibrated_p = 1.0 / (1.0 + math.exp(-adjusted_logit))
    calibrated_p = max(0.01, min(0.99, calibrated_p))
    
    assert calibrated_p <= 0.99
    assert calibrated_p >= 0.01


def test_different_horizons_same_probability():
    """Test that same probability calibrates differently for different horizons."""
    
    p_model = 0.60
    crypto_slope = 1.08
    
    # 15-minute market
    horizon_hours_15m = 0.25
    horizon_factor_15m = 1.0 + 0.08 * math.log(max(0.1, horizon_hours_15m))
    logit_p = math.log(p_model / (1.0 - p_model))
    adjusted_logit_15m = crypto_slope * horizon_factor_15m * logit_p
    calibrated_15m = 1.0 / (1.0 + math.exp(-adjusted_logit_15m))
    calibrated_15m = max(0.01, min(0.99, calibrated_15m))
    
    # 1-hour market
    horizon_hours_1h = 1.0
    horizon_factor_1h = 1.0 + 0.08 * math.log(max(0.1, horizon_hours_1h))
    adjusted_logit_1h = crypto_slope * horizon_factor_1h * logit_p
    calibrated_1h = 1.0 / (1.0 + math.exp(-adjusted_logit_1h))
    calibrated_1h = max(0.01, min(0.99, calibrated_1h))
    
    # Results should differ due to different horizon factors
    assert abs(calibrated_15m - calibrated_1h) > 0.001


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
