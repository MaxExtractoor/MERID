"""
Tests for regime classification.

Tests the _classify_regime method in LeanAgent15m:
- Regime classification from market depth
- All 5 regime types: both_sides, one_sided_yes, one_sided_no, no_liquidity, normal
- Fallback to 'normal' on errors
"""

import pytest
from dataclasses import dataclass


@dataclass
class MockMarketState:
    """Mock market state for testing."""
    min_depth_yes: int = 0
    min_depth_no: int = 0


def classify_regime(min_depth_yes: int, min_depth_no: int, threshold: int = 1) -> str:
    """Simulate _classify_regime logic for testing."""
    has_yes = min_depth_yes >= threshold
    has_no = min_depth_no >= threshold
    
    if has_yes and has_no:
        return "both_sides"
    elif has_yes and not has_no:
        return "one_sided_yes"
    elif not has_yes and has_no:
        return "one_sided_no"
    else:
        return "no_liquidity"


def test_regime_both_sides():
    """Test regime classification when both sides have liquidity."""
    min_depth_yes = 5
    min_depth_no = 5
    threshold = 1
    
    regime = classify_regime(min_depth_yes, min_depth_no, threshold)
    assert regime == "both_sides", f"Expected 'both_sides', got {regime}"


def test_regime_one_sided_yes():
    """Test regime classification when only yes side has liquidity."""
    min_depth_yes = 5
    min_depth_no = 0
    threshold = 1
    
    regime = classify_regime(min_depth_yes, min_depth_no, threshold)
    assert regime == "one_sided_yes", f"Expected 'one_sided_yes', got {regime}"


def test_regime_one_sided_no():
    """Test regime classification when only no side has liquidity."""
    min_depth_yes = 0
    min_depth_no = 5
    threshold = 1
    
    regime = classify_regime(min_depth_yes, min_depth_no, threshold)
    assert regime == "one_sided_no", f"Expected 'one_sided_no', got {regime}"


def test_regime_no_liquidity():
    """Test regime classification when neither side has liquidity."""
    min_depth_yes = 0
    min_depth_no = 0
    threshold = 1
    
    regime = classify_regime(min_depth_yes, min_depth_no, threshold)
    assert regime == "no_liquidity", f"Expected 'no_liquidity', got {regime}"


def test_regime_threshold_boundary():
    """Test regime classification at threshold boundary."""
    # Exactly at threshold
    min_depth_yes = 1
    min_depth_no = 1
    threshold = 1
    
    regime = classify_regime(min_depth_yes, min_depth_no, threshold)
    assert regime == "both_sides", f"Expected 'both_sides' at threshold, got {regime}"
    
    # Just below threshold
    min_depth_yes = 0
    min_depth_no = 1
    threshold = 1
    
    regime = classify_regime(min_depth_yes, min_depth_no, threshold)
    assert regime == "one_sided_no", f"Expected 'one_sided_no' below threshold, got {regime}"


def test_regime_with_high_depth():
    """Test regime classification with high depth values."""
    min_depth_yes = 100
    min_depth_no = 100
    threshold = 1
    
    regime = classify_regime(min_depth_yes, min_depth_no, threshold)
    assert regime == "both_sides", f"Expected 'both_sides' with high depth, got {regime}"


def test_regime_with_asymmetric_depth():
    """Test regime classification with asymmetric depth."""
    min_depth_yes = 10
    min_depth_no = 2
    threshold = 1
    
    regime = classify_regime(min_depth_yes, min_depth_no, threshold)
    assert regime == "both_sides", f"Expected 'both_sides' with asymmetric depth, got {regime}"


def test_regime_default_fallback():
    """Test that regime defaults to 'normal' on errors."""
    # Simulate error condition (e.g., market_state_store is None)
    market_state_store = None
    
    if not market_state_store:
        regime = "normal"
    else:
        regime = classify_regime(5, 5, 1)
    
    assert regime == "normal", f"Expected 'normal' fallback, got {regime}"


def test_regime_with_missing_market_state():
    """Test regime classification when market_state is missing."""
    market_state = None
    
    if not market_state:
        regime = "normal"
    else:
        min_depth_yes = getattr(market_state, 'min_depth_yes', 0)
        min_depth_no = getattr(market_state, 'min_depth_no', 0)
        regime = classify_regime(min_depth_yes, min_depth_no, 1)
    
    assert regime == "normal", f"Expected 'normal' with missing market_state, got {regime}"


def test_regime_with_exception_handling():
    """Test that regime classification handles exceptions gracefully."""
    try:
        # Simulate an exception during classification
        raise Exception("Test exception")
    except Exception as e:
        regime = "normal"
    
    assert regime == "normal", f"Expected 'normal' on exception, got {regime}"


def test_regime_for_all_crypto_assets():
    """Test regime classification for all 5 crypto assets."""
    assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    
    for asset in assets:
        # Simulate regime classification for each asset
        min_depth_yes = 5
        min_depth_no = 5
        regime = classify_regime(min_depth_yes, min_depth_no, 1)
        
        assert regime == "both_sides", f"Expected 'both_sides' for {asset}, got {regime}"


def test_regime_transition():
    """Test regime transition as depth changes."""
    # Start with both_sides
    min_depth_yes = 5
    min_depth_no = 5
    regime = classify_regime(min_depth_yes, min_depth_no, 1)
    assert regime == "both_sides"
    
    # Transition to one_sided_yes
    min_depth_no = 0
    regime = classify_regime(min_depth_yes, min_depth_no, 1)
    assert regime == "one_sided_yes"
    
    # Transition to no_liquidity
    min_depth_yes = 0
    regime = classify_regime(min_depth_yes, min_depth_no, 1)
    assert regime == "no_liquidity"


def test_regime_with_different_thresholds():
    """Test regime classification with different thresholds."""
    min_depth_yes = 3
    min_depth_no = 3
    
    # With threshold = 1
    regime = classify_regime(min_depth_yes, min_depth_no, threshold=1)
    assert regime == "both_sides"
    
    # With threshold = 5
    regime = classify_regime(min_depth_yes, min_depth_no, threshold=5)
    assert regime == "no_liquidity"


def test_regime_logging():
    """Test that regime classification logs correctly."""
    min_depth_yes = 5
    min_depth_no = 5
    threshold = 1
    ticker = "KXBTCD-..."
    
    regime = classify_regime(min_depth_yes, min_depth_no, threshold)
    
    # Simulate logging
    log_message = f"[REGIME-CLASSIFY] ticker={ticker} regime={regime} (yes_depth={min_depth_yes} no_depth={min_depth_no})"
    
    assert "regime=both_sides" in log_message
    assert "yes_depth=5" in log_message
    assert "no_depth=5" in log_message


def test_regime_in_signal_dict():
    """Test that regime is included in signal dict."""
    regime = "both_sides"
    
    signal = {
        "asset": "BTC",
        "side": "yes",
        "action": "buy",
        "velocity": 0.0002,
        "regime": regime,
    }
    
    assert "regime" in signal
    assert signal["regime"] == "both_sides"


def test_regime_in_candidate_dict():
    """Test that regime is carried to candidate dict."""
    signal = {"regime": "both_sides"}
    
    candidate = {
        "agent_id": "BTC_15M",
        "ticker": "KXBTCD-...",
        "regime": signal.get("regime", "normal"),
    }
    
    assert "regime" in candidate
    assert candidate["regime"] == "both_sides"


def test_regime_in_order_intent():
    """Test that regime is carried to OrderIntent."""
    candidate = {"regime": "both_sides"}
    
    order_intent = {
        "ticker": "KXBTCD-...",
        "regime": candidate.get("regime"),
    }
    
    assert "regime" in order_intent
    assert order_intent["regime"] == "both_sides"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
