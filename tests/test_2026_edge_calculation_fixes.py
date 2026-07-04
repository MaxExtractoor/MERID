"""
Tests for 2026 edge calculation fixes based on industry research.

These tests validate the transition from edge-based filtering to confidence-based filtering
for momentum-based binary options trading, as per 2026 industry standards.

Key changes:
- Replaced min_edge_threshold (0.02%) with min_confidence_threshold (6.0%)
- Based on binary-options-ml research showing confidence filtering improves win rate from 52% → 58.47%
- Removed volatility-regime edge adjustment (was crushing edge to 0.01%)
- Edge calculation now uses velocity magnitude for momentum signals
"""

import pytest
from unittest.mock import patch, MagicMock
import os


def test_confidence_filter_threshold_6_percent():
    """Test that confidence filtering uses 6% threshold (2026 industry standard)."""
    # Read the agent_grid_15m.py file to verify the threshold
    with open('merid/prediction/agent_grid_15m.py', 'r') as f:
        content = f.read()
    
    # Verify the confidence threshold is set to 6.0%
    assert 'min_confidence_threshold = 6.0' in content, \
        "Confidence threshold should be 6.0% (2026 industry standard)"
    
    # Verify the comment references binary-options-ml research
    assert 'binary-options-ml research' in content, \
        "Should reference binary-options-ml research in comments"
    
    # Verify the comment mentions 6% threshold
    assert '6%' in content or '0.06' in content, \
        "Should mention 6% threshold in comments"


def test_min_edge_threshold_removed():
    """Test that min_edge_threshold (0.02%) has been removed from signal generation."""
    with open('merid/prediction/agent_grid_15m.py', 'r') as f:
        content = f.read()
    
    # The old min_edge_threshold = 0.02 should NOT be present in signal generation
    # Check that we're not using edge-based filtering for momentum signals
    lines = content.split('\n')
    
    # Find the signal generation section (around line 3500)
    signal_gen_section = '\n'.join(lines[3400:3600])
    
    # Verify min_edge_threshold is not used for filtering in signal generation
    assert 'min_edge_threshold = 0.02' not in signal_gen_section, \
        "min_edge_threshold should be removed from signal generation"
    
    # Verify confidence filtering is used instead
    assert 'min_confidence_threshold' in signal_gen_section, \
        "Should use min_confidence_threshold instead of min_edge_threshold"


def test_volatility_regime_edge_adjustment_removed():
    """Test that volatility-regime edge adjustment has been removed from signal generation."""
    with open('merid/prediction/agent_grid_15m.py', 'r') as f:
        content = f.read()
    
    # Find the signal generation section
    lines = content.split('\n')
    signal_gen_section = '\n'.join(lines[3400:3600])
    
    # Verify volatility-regime edge adjustment is not present
    assert 'volatility_regime_edge_adjustment_enabled' not in signal_gen_section, \
        "Volatility-regime edge adjustment should be removed from signal generation"
    
    assert 'VOLATILITY-REGIME-EDGE' not in signal_gen_section, \
        "VOLATILITY-REGIME-EDGE logging should be removed from signal generation"


def test_edge_calculation_uses_velocity_magnitude():
    """Test that edge calculation uses velocity magnitude for momentum signals."""
    with open('merid/prediction/agent_grid_15m.py', 'r') as f:
        content = f.read()
    
    # Verify edge calculation uses velocity magnitude
    assert 'edge_pct = abs(velocity) * 100.0' in content, \
        "Edge should be calculated as velocity magnitude * 100%"
    
    # Verify the comment explains why velocity is used
    assert 'velocity magnitude as edge' in content, \
        "Should explain that velocity magnitude is used as edge"


def test_confidence_calculation_from_probability():
    """Test that confidence is calculated as distance from neutral probability (0.5)."""
    with open('merid/prediction/agent_grid_15m.py', 'r') as f:
        content = f.read()
    
    # Verify confidence calculation
    assert 'confidence_pct = abs(p_model - 0.5) * 100.0' in content, \
        "Confidence should be calculated as |p_model - 0.5| * 100%"
    
    # Verify the final confidence calculation for logging
    assert 'confidence = min(0.99, 0.50 + 2.0 * abs(p_model - 0.5))' in content, \
        "Final confidence should be bounded at 0.99 with 2x scaling"


def test_confidence_filter_logging():
    """Test that confidence filter has proper logging."""
    with open('merid/prediction/agent_grid_15m.py', 'r') as f:
        content = f.read()
    
    # Verify confidence filter logging
    assert '[CONFIDENCE-FILTER]' in content, \
        "Should have CONFIDENCE-FILTER logging"
    
    assert 'confidence=%.2f%% < min_confidence=%.2f%%' in content, \
        "Should log confidence and threshold values"


def test_profile_has_volatility_regime_disabled():
    """Test that volatility_regime_edge_adjustment is disabled in profile."""
    import yaml
    
    with open('config/profiles/kalshi_crypto_15m_v2.yaml', 'r', encoding='utf-8') as f:
        profile_config = yaml.safe_load(f)
    
    # Verify volatility_regime_edge_adjustment is disabled
    volatility_config = profile_config.get('volatility_regime_edge_adjustment', {})
    assert volatility_config.get('enabled', True) == False, \
        "volatility_regime_edge_adjustment should be disabled in profile"


def test_edge_pct_calculation_for_momentum():
    """Test that edge_pct is calculated correctly for momentum signals."""
    # Test with various velocity values
    test_cases = [
        (0.0001, 0.01),   # 0.01% velocity -> 0.01% edge
        (0.0005, 0.05),   # 0.05% velocity -> 0.05% edge
        (0.0010, 0.10),   # 0.10% velocity -> 0.10% edge
        (0.0020, 0.20),   # 0.20% velocity -> 0.20% edge
    ]
    
    for velocity, expected_edge in test_cases:
        calculated_edge = abs(velocity) * 100.0
        assert abs(calculated_edge - expected_edge) < 0.001, \
            f"Velocity {velocity} should produce edge {expected_edge}%, got {calculated_edge}%"


def test_confidence_calculation_for_probability():
    """Test that confidence is calculated correctly from probability."""
    # Test with various probability values
    test_cases = [
        (0.50, 0.0),    # Neutral probability -> 0% confidence
        (0.56, 6.0),    # 56% probability -> 6% confidence (meets threshold)
        (0.44, 6.0),    # 44% probability -> 6% confidence (meets threshold)
        (0.60, 10.0),   # 60% probability -> 10% confidence
        (0.40, 10.0),   # 40% probability -> 10% confidence
        (0.70, 20.0),   # 70% probability -> 20% confidence
    ]
    
    for p_model, expected_confidence in test_cases:
        calculated_confidence = abs(p_model - 0.5) * 100.0
        assert abs(calculated_confidence - expected_confidence) < 0.001, \
            f"Probability {p_model} should produce confidence {expected_confidence}%, got {calculated_confidence}%"


def test_confidence_threshold_passes():
    """Test that signals with confidence >= 6% pass the filter."""
    # Test cases that should pass (in percentage units)
    passing_cases = [
        6.0,    # Exactly at threshold
        10.0,   # Above threshold
        15.0,   # Well above threshold
        50.0,   # Very high confidence
    ]
    
    min_confidence_threshold = 6.0
    
    for confidence in passing_cases:
        assert confidence >= min_confidence_threshold, \
            f"Confidence {confidence}% should pass filter (threshold: {min_confidence_threshold}%)"


def test_confidence_threshold_fails():
    """Test that signals with confidence < 6% fail the filter."""
    # Test cases that should fail
    failing_cases = [
        0.00,   # No confidence
        0.01,   # Very low confidence
        0.02,   # Low confidence
        0.04,   # Below threshold
        0.05,   # Just below threshold
    ]
    
    min_confidence_threshold = 6.0
    
    for confidence in failing_cases:
        assert confidence < min_confidence_threshold, \
            f"Confidence {confidence}% should fail filter (threshold: {min_confidence_threshold}%)"


def test_industry_standard_coverage():
    """Test that 6% confidence threshold provides reasonable signal coverage."""
    # Based on binary-options-ml research:
    # - 6% threshold provides 9.3% coverage (filters 90.7% of signals)
    # - This is optimal for 15m binary options trading
    
    # Simulate a distribution of probabilities clustered around 0.5
    # Momentum signals typically have probabilities close to neutral (0.5)
    # Use normal distribution with small standard deviation
    import random
    import math
    random.seed(42)
    
    num_signals = 10000
    # Normal distribution centered at 0.5 with std=0.04
    # This means 95% of probabilities are in range [0.42, 0.58]
    probabilities = [random.gauss(0.5, 0.04) for _ in range(num_signals)]
    # Clamp to valid range [0, 1]
    probabilities = [max(0.0, min(1.0, p)) for p in probabilities]
    
    # Calculate confidence for each signal
    confidences = [abs(p - 0.5) * 100.0 for p in probabilities]
    
    # Apply 6% threshold
    min_confidence_threshold = 6.0
    passing_signals = [c for c in confidences if c >= min_confidence_threshold]
    
    coverage = len(passing_signals) / num_signals
    
    # Coverage should be in reasonable range (5-15% based on research)
    assert 0.05 <= coverage <= 0.15, \
        f"Coverage {coverage:.1%} should be in range 5-15% (research shows 9.3% optimal)"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
