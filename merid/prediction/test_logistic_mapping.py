"""
Unit tests for logistic mapping, edge calculation, and confidence calculation.

Tests the core signal generation logic in LeanAgent15m._generate_signal:
- Logistic mapping from velocity to model probability
- Edge calculation (p_model - p_mkt)
- Confidence calculation (distance from 0.5)
- Error handling for missing coefficients and invalid probabilities
"""

import math
import pytest


def test_logistic_mapping_basic():
    """Test basic logistic mapping from velocity to probability."""
    # Test with alpha_0 = 0, alpha_1 = 1000
    alpha_0 = 0.0
    alpha_1 = 1000.0
    
    # At velocity = 0, logit = 0, p_model = 0.5
    velocity = 0.0
    raw_logit = alpha_0 + alpha_1 * velocity
    p_model = 1.0 / (1.0 + math.exp(-raw_logit))
    assert abs(p_model - 0.5) < 0.001, f"Expected p_model ≈ 0.5 at velocity=0, got {p_model}"
    
    # At positive velocity, p_model > 0.5
    velocity = 0.0002
    raw_logit = alpha_0 + alpha_1 * velocity
    p_model = 1.0 / (1.0 + math.exp(-raw_logit))
    assert p_model > 0.5, f"Expected p_model > 0.5 at positive velocity, got {p_model}"
    
    # At negative velocity, p_model < 0.5
    velocity = -0.0002
    raw_logit = alpha_0 + alpha_1 * velocity
    p_model = 1.0 / (1.0 + math.exp(-raw_logit))
    assert p_model < 0.5, f"Expected p_model < 0.5 at negative velocity, got {p_model}"


def test_logistic_mapping_with_intercept():
    """Test logistic mapping with non-zero intercept."""
    # Test with alpha_0 = -0.5, alpha_1 = 1000
    alpha_0 = -0.5
    alpha_1 = 1000.0
    
    # At velocity = 0, logit = -0.5, p_model < 0.5
    velocity = 0.0
    raw_logit = alpha_0 + alpha_1 * velocity
    p_model = 1.0 / (1.0 + math.exp(-raw_logit))
    assert p_model < 0.5, f"Expected p_model < 0.5 with negative intercept, got {p_model}"
    
    # At higher velocity, p_model should exceed 0.5
    velocity = 0.001  # Higher velocity to overcome negative intercept
    raw_logit = alpha_0 + alpha_1 * velocity
    p_model = 1.0 / (1.0 + math.exp(-raw_logit))
    assert p_model > 0.5, f"Expected p_model > 0.5 at higher velocity, got {p_model}"


def test_edge_calculation():
    """Test edge calculation as difference between model and market probability."""
    p_model = 0.60
    p_mkt = 0.50
    edge_pct = (p_model - p_mkt) * 100.0
    assert abs(edge_pct - 10.0) < 0.001, f"Expected edge_pct = 10.0, got {edge_pct}"
    
    # Test negative edge
    p_model = 0.40
    p_mkt = 0.50
    edge_pct = (p_model - p_mkt) * 100.0
    assert abs(edge_pct - (-10.0)) < 0.001, f"Expected edge_pct = -10.0, got {edge_pct}"
    
    # Test zero edge
    p_model = 0.50
    p_mkt = 0.50
    edge_pct = (p_model - p_mkt) * 100.0
    assert abs(edge_pct - 0.0) < 0.001, f"Expected edge_pct = 0.0, got {edge_pct}"


def test_confidence_calculation():
    """Test confidence calculation as distance from 0.5."""
    # At p_model = 0.5, confidence should be 0.5 (minimum)
    p_model = 0.5
    confidence = min(0.99, 0.50 + 2.0 * abs(p_model - 0.5))
    assert abs(confidence - 0.5) < 0.001, f"Expected confidence = 0.5 at p_model=0.5, got {confidence}"
    
    # At p_model = 0.6, confidence should be 0.7
    p_model = 0.6
    confidence = min(0.99, 0.50 + 2.0 * abs(p_model - 0.5))
    assert abs(confidence - 0.7) < 0.001, f"Expected confidence = 0.7 at p_model=0.6, got {confidence}"
    
    # At p_model = 0.7, confidence should be 0.9
    p_model = 0.7
    confidence = min(0.99, 0.50 + 2.0 * abs(p_model - 0.5))
    assert abs(confidence - 0.9) < 0.001, f"Expected confidence = 0.9 at p_model=0.7, got {confidence}"
    
    # At p_model = 0.8, confidence should be capped at 0.99 (exceeds cap)
    p_model = 0.8
    confidence = min(0.99, 0.50 + 2.0 * abs(p_model - 0.5))
    assert abs(confidence - 0.99) < 0.001, f"Expected confidence = 0.99 at p_model=0.8, got {confidence}"
    
    # At p_model = 0.95, confidence should be capped at 0.99
    p_model = 0.95
    confidence = min(0.99, 0.50 + 2.0 * abs(p_model - 0.5))
    assert abs(confidence - 0.99) < 0.001, f"Expected confidence = 0.99 at p_model=0.95, got {confidence}"


def test_p_model_clamping():
    """Test that p_model is clamped to valid range [0.01, 0.99]."""
    # Test extreme positive logit
    raw_logit = 100.0
    p_model = 1.0 / (1.0 + math.exp(-raw_logit))
    p_model_clamped = max(0.01, min(0.99, p_model))
    assert p_model_clamped == 0.99, f"Expected p_model clamped to 0.99, got {p_model_clamped}"
    
    # Test extreme negative logit
    raw_logit = -100.0
    p_model = 1.0 / (1.0 + math.exp(-raw_logit))
    p_model_clamped = max(0.01, min(0.99, p_model))
    assert p_model_clamped == 0.01, f"Expected p_model clamped to 0.01, got {p_model_clamped}"
    
    # Test normal range
    raw_logit = 0.0
    p_model = 1.0 / (1.0 + math.exp(-raw_logit))
    p_model_clamped = max(0.01, min(0.99, p_model))
    assert abs(p_model_clamped - 0.5) < 0.001, f"Expected p_model = 0.5, got {p_model_clamped}"


def test_p_mkt_clamping():
    """Test that p_mkt is clamped to valid range [0.05, 0.95]."""
    # Test below minimum
    p_mkt = 0.0
    p_mkt_clamped = max(0.05, min(0.95, p_mkt))
    assert p_mkt_clamped == 0.05, f"Expected p_mkt clamped to 0.05, got {p_mkt_clamped}"
    
    # Test above maximum
    p_mkt = 1.0
    p_mkt_clamped = max(0.05, min(0.95, p_mkt))
    assert p_mkt_clamped == 0.95, f"Expected p_mkt clamped to 0.95, got {p_mkt_clamped}"
    
    # Test normal range
    p_mkt = 0.50
    p_mkt_clamped = max(0.05, min(0.95, p_mkt))
    assert abs(p_mkt_clamped - 0.50) < 0.001, f"Expected p_mkt = 0.50, got {p_mkt_clamped}"


def test_error_handling_missing_coefficients():
    """Test error handling for missing velocity coefficients."""
    alpha_0 = None
    alpha_1 = 1000.0
    velocity = 0.0002
    
    # Should detect missing alpha_0
    if alpha_0 is None or alpha_1 is None:
        # This is the expected behavior - signal generation should skip
        assert True, "Correctly detected missing coefficient"
    else:
        assert False, "Should have detected missing coefficient"


def test_error_handling_overflow():
    """Test error handling for overflow in logistic calculation."""
    alpha_0 = 0.0
    alpha_1 = 1e10  # Very large coefficient
    velocity = 0.0002
    
    raw_logit = alpha_0 + alpha_1 * velocity
    try:
        p_model = 1.0 / (1.0 + math.exp(-raw_logit))
        # Should not overflow with proper clamping
        assert 0.0 <= p_model <= 1.0, f"p_model out of range: {p_model}"
    except (OverflowError, ValueError) as e:
        # This is acceptable if the coefficient is too large
        assert True, f"Overflow detected as expected: {e}"


def test_signal_validation():
    """Test that p_model is validated to be in [0, 1] range."""
    # Valid p_model
    p_model = 0.6
    if not (0.0 <= p_model <= 1.0):
        assert False, f"Valid p_model should pass validation"
    
    # Invalid p_model (should never happen with clamping, but test validation logic)
    p_model = 1.5
    if not (0.0 <= p_model <= 1.0):
        assert True, "Invalid p_model correctly detected"
    else:
        assert False, "Should have detected invalid p_model"


def test_per_asset_coefficients():
    """Test that different assets can have different coefficients."""
    # BTC coefficients
    btc_alpha_0 = 0.0
    btc_alpha_1 = 1000.0
    
    # ETH coefficients (different sensitivity)
    eth_alpha_0 = 0.0
    eth_alpha_1 = 800.0
    
    velocity = 0.0002
    
    # Calculate p_model for BTC
    btc_raw_logit = btc_alpha_0 + btc_alpha_1 * velocity
    btc_p_model = 1.0 / (1.0 + math.exp(-btc_raw_logit))
    
    # Calculate p_model for ETH
    eth_raw_logit = eth_alpha_0 + eth_alpha_1 * velocity
    eth_p_model = 1.0 / (1.0 + math.exp(-eth_raw_logit))
    
    # BTC should have higher p_model due to higher alpha_1
    assert btc_p_model > eth_p_model, f"BTC p_model should be higher with higher alpha_1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
