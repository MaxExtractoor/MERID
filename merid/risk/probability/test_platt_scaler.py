"""
Unit tests for PlattScaler probability calibration.
Tests Phase 5.1: PlattScaler class implementation.
"""

import pytest
import numpy as np
from merid.risk.probability.platt_scaler import PlattScaler, CalibrationMetrics


def test_platt_scaler_initialization():
    """Test PlattScaler initialization."""
    scaler = PlattScaler(regularization=1e-4)
    assert scaler.regularization == 1e-4
    assert not scaler.is_fitted()
    assert scaler.get_parameters() is None


def test_platt_scaler_fit_basic():
    """Test basic fitting with synthetic data."""
    scaler = PlattScaler(regularization=1e-4)
    
    # Generate synthetic data: logits that correlate with outcomes
    logits = [i * 0.1 for i in range(-5, 6)]  # -0.5 to 0.5
    outcomes = [1 if logit > 0 else 0 for logit in logits]
    
    scaler.fit(logits, outcomes)
    
    assert scaler.is_fitted()
    params = scaler.get_parameters()
    assert params is not None
    assert len(params) == 2
    assert params[0] is not None  # a parameter
    assert params[1] is not None  # b parameter


def test_platt_scaler_fit_insufficient_data():
    """Test that fitting with insufficient data raises error."""
    scaler = PlattScaler()
    
    with pytest.raises(ValueError, match="Insufficient data"):
        scaler.fit([0.1, 0.2], [0, 1])  # Only 2 samples


def test_platt_scaler_fit_mismatched_lengths():
    """Test that fitting with mismatched lengths raises error."""
    scaler = PlattScaler()
    
    with pytest.raises(ValueError, match="same length"):
        scaler.fit([0.1, 0.2, 0.3], [0, 1])  # 3 logits, 2 outcomes


def test_platt_scaler_predict():
    """Test probability prediction after fitting."""
    scaler = PlattScaler()
    
    # Fit with synthetic data
    logits = [i * 0.1 for i in range(-5, 6)]
    outcomes = [1 if logit > 0 else 0 for logit in logits]
    scaler.fit(logits, outcomes)
    
    # Predict on new logits
    test_logits = [-0.3, 0.0, 0.3]
    probs = scaler.predict(test_logits)
    
    assert len(probs) == 3
    assert all(0.0 <= p <= 1.0 for p in probs)
    # Higher logit should give higher probability
    assert probs[0] < probs[1] < probs[2]


def test_platt_scaler_predict_unfitted():
    """Test that prediction without fitting raises error."""
    scaler = PlattScaler()
    
    with pytest.raises(RuntimeError, match="must be fitted"):
        scaler.predict([0.1, 0.2])


def test_platt_scaler_predict_single():
    """Test single logit prediction."""
    scaler = PlattScaler()
    
    # Fit with synthetic data
    logits = [i * 0.1 for i in range(-5, 6)]
    outcomes = [1 if logit > 0 else 0 for logit in logits]
    scaler.fit(logits, outcomes)
    
    # Predict single logit
    prob = scaler.predict_single(0.5)
    
    assert 0.0 <= prob <= 1.0
    assert prob > 0.5  # Positive logit should give > 0.5 probability


def test_platt_scaler_brier_score():
    """Test Brier score calculation."""
    scaler = PlattScaler()
    
    # Fit with well-calibrated data
    logits = [i * 0.1 for i in range(-5, 6)]
    outcomes = [1 if logit > 0 else 0 for logit in logits]
    scaler.fit(logits, outcomes)
    
    # Evaluate metrics
    metrics = scaler.evaluate_metrics(logits, outcomes)
    
    assert isinstance(metrics, CalibrationMetrics)
    assert metrics.brier_score >= 0.0
    assert metrics.brier_score <= 1.0
    assert metrics.num_samples == len(logits)


def test_platt_scaler_ece():
    """Test Expected Calibration Error calculation."""
    scaler = PlattScaler()
    
    # Fit with synthetic data
    logits = [i * 0.1 for i in range(-5, 6)]
    outcomes = [1 if logit > 0 else 0 for logit in logits]
    scaler.fit(logits, outcomes)
    
    # Evaluate metrics
    metrics = scaler.evaluate_metrics(logits, outcomes, num_bins=5)
    
    assert isinstance(metrics, CalibrationMetrics)
    assert metrics.expected_calibration_error >= 0.0
    assert metrics.expected_calibration_error <= 1.0


def test_platt_scaler_mce():
    """Test Maximum Calibration Error calculation."""
    scaler = PlattScaler()
    
    # Fit with synthetic data
    logits = [i * 0.1 for i in range(-5, 6)]
    outcomes = [1 if logit > 0 else 0 for logit in logits]
    scaler.fit(logits, outcomes)
    
    # Evaluate metrics
    metrics = scaler.evaluate_metrics(logits, outcomes, num_bins=5)
    
    assert isinstance(metrics, CalibrationMetrics)
    assert metrics.maximum_calibration_error >= 0.0
    assert metrics.maximum_calibration_error <= 1.0


def test_platt_scaler_reset():
    """Test resetting the scaler."""
    scaler = PlattScaler()
    
    # Fit with data
    logits = [i * 0.1 for i in range(-5, 6)]
    outcomes = [1 if logit > 0 else 0 for logit in logits]
    scaler.fit(logits, outcomes)
    
    assert scaler.is_fitted()
    
    # Reset
    scaler.reset()
    
    assert not scaler.is_fitted()
    assert scaler.get_parameters() is None


def test_platt_scaler_perfect_calibration():
    """Test calibration with perfectly calibrated data."""
    scaler = PlattScaler()
    
    # Generate perfectly calibrated data with at least 10 samples
    # Probabilities match actual outcomes exactly
    logits = [i * 0.2 for i in range(-10, 11)]  # -2.0 to 2.0, 21 samples
    # Use sigmoid to get probabilities, then sample outcomes
    probs = [1 / (1 + np.exp(-logit)) for logit in logits]
    outcomes = [1 if p > 0.5 else 0 for p in probs]
    
    scaler.fit(logits, outcomes)
    
    # Evaluate metrics - should have low error
    metrics = scaler.evaluate_metrics(logits, outcomes)
    
    # Brier score should be relatively low for well-calibrated data
    assert metrics.brier_score < 0.3


def test_platt_scaler_with_noise():
    """Test calibration with noisy data."""
    scaler = PlattScaler()
    
    # Generate noisy data
    np.random.seed(42)
    logits = np.random.randn(50).tolist()
    # Add noise to outcomes
    probs = [1 / (1 + np.exp(-logit)) for logit in logits]
    outcomes = [1 if p + np.random.randn() * 0.1 > 0.5 else 0 for p in probs]
    
    scaler.fit(logits, outcomes)
    
    assert scaler.is_fitted()
    
    # Should still produce valid probabilities
    test_logits = [-1.0, 0.0, 1.0]
    probs = scaler.predict(test_logits)
    
    assert all(0.0 <= p <= 1.0 for p in probs)


def test_platt_scaler_clipping():
    """Test that probabilities are clipped to valid range."""
    scaler = PlattScaler()
    
    # Fit with extreme logits (need at least 10 samples)
    logits = [i * 5.0 for i in range(-5, 6)]  # -25 to 25, 11 samples
    outcomes = [0 if i < 5 else 1 for i in range(-5, 6)]
    scaler.fit(logits, outcomes)
    
    # Predict on extreme logits
    extreme_logits = [-100.0, 100.0]
    probs = scaler.predict(extreme_logits)
    
    # Should be clipped to [0.01, 0.99]
    assert all(0.01 <= p <= 0.99 for p in probs)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
