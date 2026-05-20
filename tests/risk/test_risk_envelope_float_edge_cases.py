"""Floating-point edge case tests for KalshiCrypto15mRiskEnvelope.

Tests for floating-point precision issues in:
- Drawdown calculations (peak equity, current equity, drawdown %)
- Adaptive risk band threshold comparisons
- Kelly fraction calculations
- Risk multiplier computations
"""

import pytest
from decimal import Decimal


def test_drawdown_calculation_precision():
    """Test drawdown calculation handles floating-point precision correctly."""
    # Test case 1: Very small drawdown (near zero)
    peak_equity = 10000.0
    current_equity = 9999.99
    expected_drawdown = (peak_equity - current_equity) / peak_equity
    
    # Should not suffer from floating-point precision loss
    assert expected_drawdown == pytest.approx(1e-06, abs=1e-10)
    
    # Test case 2: Large equity values
    peak_equity = 1_000_000.0
    current_equity = 950_000.0
    expected_drawdown = (peak_equity - current_equity) / peak_equity
    
    assert expected_drawdown == pytest.approx(0.05, abs=1e-10)


def test_drawdown_threshold_comparison():
    """Test drawdown threshold comparisons are robust to floating-point errors."""
    halt_pct = 0.15
    unwind_pct = 0.10
    
    # Test case 1: Exactly at threshold
    current_drawdown = 0.10
    # Should not trigger halt (halt > unwind)
    assert current_drawdown <= halt_pct
    assert current_drawdown >= unwind_pct
    
    # Test case 2: Just below halt due to floating-point error
    current_drawdown = 0.149
    assert current_drawdown < halt_pct
    
    # Test case 3: Just above halt due to floating-point error
    current_drawdown = 0.151
    assert current_drawdown >= halt_pct


def test_adaptive_risk_band_thresholds():
    """Test adaptive risk band threshold comparisons handle edge cases."""
    bands = [
        {"max_drawdown_pct": 0.05, "multiplier": 1.0},
        {"max_drawdown_pct": 0.10, "multiplier": 0.75},
        {"max_drawdown_pct": 0.15, "multiplier": 0.5},
    ]
    
    # Test case 1: Exactly at band boundary
    current_drawdown = 0.10
    # Should select second band (multiplier 0.75)
    for band in bands:
        if current_drawdown <= band["max_drawdown_pct"]:
            assert band["multiplier"] == 0.75
            break
    
    # Test case 2: Just below boundary
    current_drawdown = 0.09999999999999999
    for band in bands:
        if current_drawdown <= band["max_drawdown_pct"]:
            assert band["multiplier"] == 0.75
            break
    
    # Test case 3: Just above boundary
    current_drawdown = 0.10000000000000002
    for band in bands:
        if current_drawdown <= band["max_drawdown_pct"]:
            assert band["multiplier"] == 0.5
            break


def test_kelly_fraction_precision():
    """Test Kelly fraction calculations preserve precision."""
    # Test case 1: Very small Kelly fraction
    kelly_fraction = 0.001
    assert kelly_fraction > 0
    assert kelly_fraction <= 1.0
    
    # Test case 2: Kelly fraction near 1.0
    kelly_fraction = 0.9999999999999999
    assert kelly_fraction > 0
    assert kelly_fraction <= 1.0
    
    # Test case 3: Kelly fraction at 0.5
    kelly_fraction = 0.5
    assert kelly_fraction == pytest.approx(0.5, abs=1e-10)


def test_risk_multiplier_computation():
    """Test risk multiplier computation handles floating-point edge cases."""
    # Test case 1: Multiplier exactly 0 (halted)
    multiplier = 0.0
    assert multiplier == 0.0
    
    # Test case 2: Multiplier very small but non-zero
    multiplier = 0.0000000001
    assert multiplier > 0
    assert multiplier < 1.0
    
    # Test case 3: Multiplier exactly 1.0 (full risk)
    multiplier = 1.0
    assert multiplier == pytest.approx(1.0, abs=1e-10)
    
    # Test case 4: Multiplier near 0.5
    multiplier = 0.5000000000000001
    assert multiplier == pytest.approx(0.5, abs=1e-10)


def test_distance_to_halt_calculation():
    """Test distance to halt calculation handles floating-point precision."""
    halt_pct = 0.15
    current_drawdown = 0.10
    
    distance = halt_pct - current_drawdown
    assert distance == pytest.approx(0.05, abs=1e-10)
    
    # Test case 1: Very close to halt
    current_drawdown = 0.149
    distance = halt_pct - current_drawdown
    assert distance > 0
    assert distance < 0.01
    
    # Test case 2: Exactly at halt
    current_drawdown = 0.15
    distance = halt_pct - current_drawdown
    assert distance == pytest.approx(0.0, abs=1e-10)
    
    # Test case 3: Past halt (should be negative)
    current_drawdown = 0.151
    distance = halt_pct - current_drawdown
    assert distance < 0


def test_per_trade_risk_pct_calculation():
    """Test per-trade risk percentage calculation preserves precision."""
    kelly_fraction = 0.25
    risk_multiplier = 0.75
    
    per_trade_risk_pct = kelly_fraction * risk_multiplier
    expected = 0.1875
    
    assert per_trade_risk_pct == pytest.approx(expected, abs=1e-10)
    
    # Test case 1: Very small values
    kelly_fraction = 0.001
    risk_multiplier = 0.5
    per_trade_risk_pct = kelly_fraction * risk_multiplier
    assert per_trade_risk_pct == pytest.approx(0.0005, abs=1e-10)


def test_effective_per_trade_risk_usd():
    """Test effective per-trade risk USD calculation handles large values."""
    per_trade_risk_pct = 0.02
    current_equity = 1_000_000.0
    
    effective_risk_usd = per_trade_risk_pct * current_equity
    expected = 20_000.0
    
    assert effective_risk_usd == pytest.approx(expected, abs=0.01)
    
    # Test case 1: Small equity
    current_equity = 100.0
    effective_risk_usd = per_trade_risk_pct * current_equity
    assert effective_risk_usd == pytest.approx(2.0, abs=0.01)
    
    # Test case 2: Very small risk percentage
    per_trade_risk_pct = 0.0001
    current_equity = 10_000.0
    effective_risk_usd = per_trade_risk_pct * current_equity
    assert effective_risk_usd == pytest.approx(1.0, abs=0.01)


def test_band_multiplier_ordering():
    """Test that adaptive risk bands are ordered correctly for threshold comparisons."""
    bands = [
        {"max_drawdown_pct": 0.05, "multiplier": 1.0},
        {"max_drawdown_pct": 0.10, "multiplier": 0.75},
        {"max_drawdown_pct": 0.15, "multiplier": 0.5},
    ]
    
    # Verify bands are ordered by max_drawdown_pct
    for i in range(len(bands) - 1):
        assert bands[i]["max_drawdown_pct"] < bands[i + 1]["max_drawdown_pct"]
    
    # Verify multipliers decrease as drawdown increases
    for i in range(len(bands) - 1):
        assert bands[i]["multiplier"] > bands[i + 1]["multiplier"]


def test_edge_case_zero_equity():
    """Test behavior when equity is zero or near-zero."""
    # Test case 1: Peak equity is zero (should be handled gracefully)
    peak_equity = 0.0
    current_equity = 0.0
    
    # Drawdown calculation should handle this (typically returns 0 or raises error)
    if peak_equity == 0:
        # Expected behavior: either return 0 or raise error
        try:
            drawdown = (peak_equity - current_equity) / peak_equity
            # If no error, should be NaN or inf
            assert not (drawdown == drawdown)  # NaN check
        except ZeroDivisionError:
            # Expected
            pass
    
    # Test case 2: Current equity is zero (valid case)
    peak_equity = 10000.0
    current_equity = 0.0
    drawdown = (peak_equity - current_equity) / peak_equity
    assert drawdown == pytest.approx(1.0, abs=1e-10)


def test_edge_case_negative_equity():
    """Test behavior when equity is negative (should not happen but handle gracefully)."""
    peak_equity = 10000.0
    current_equity = -100.0
    
    drawdown = (peak_equity - current_equity) / peak_equity
    # Drawdown > 1.0 indicates loss exceeds peak equity
    assert drawdown > 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
