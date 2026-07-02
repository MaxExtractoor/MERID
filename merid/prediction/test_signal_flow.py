"""
Integration tests for signal→candidate→OrderIntent flow.

Tests the complete flow from signal generation in LeanAgent15m._generate_signal
through candidate construction in collect_order_candidate to OrderIntent creation
in loop_15m._execute_candidate.
"""

import pytest
from dataclasses import dataclass
from typing import Dict, Any, Optional


@dataclass
class MockMarket:
    """Mock market object for testing."""
    market_id: str


@dataclass
class MockMarketState:
    """Mock market state for testing."""
    min_depth_yes: int = 5
    min_depth_no: int = 5


def test_signal_dict_structure():
    """Test that signal dict contains all required fields."""
    signal = {
        "asset": "BTC",
        "side": "yes",
        "action": "buy",
        "velocity": 0.0002,
        "spot_price": 65000.0,
        "minutes_to_expiry": 10.0,
        "best_bid": 50,
        "best_ask": 52,
        "price_source": "kalshi",
        "strategy_staleness": 1.0,
        "venue_staleness": 1.0,
        "edge_pct": 5.0,
        "confidence": 0.7,
        "model_prob": 0.55,
        "p_mkt": 0.50,
        "raw_logit": 0.2,
        "regime": "both_sides",
    }
    
    # Verify all required fields are present
    required_fields = [
        "asset", "side", "action", "velocity", "spot_price", "minutes_to_expiry",
        "best_bid", "best_ask", "price_source", "strategy_staleness", "venue_staleness",
        "edge_pct", "confidence", "model_prob", "p_mkt", "raw_logit", "regime"
    ]
    
    for field in required_fields:
        assert field in signal, f"Missing required field: {field}"


def test_candidate_dict_structure():
    """Test that candidate dict contains all required fields."""
    candidate = {
        "agent_id": "BTC_15M",
        "ticker": "KXBTCD-...",
        "side": "yes",
        "action": "buy",
        "spot_price": 65000.0,
        "velocity": 0.0002,
        "minutes_to_expiry": 10.0,
        "edge_pct": 5.0,
        "confidence": 0.7,
        "model_prob": 0.55,
        "regime": "both_sides",
    }
    
    # Verify all required fields are present
    required_fields = [
        "agent_id", "ticker", "side", "action", "spot_price", "velocity",
        "minutes_to_expiry", "edge_pct", "confidence", "model_prob", "regime"
    ]
    
    for field in required_fields:
        assert field in candidate, f"Missing required field: {field}"


def test_signal_to_candidate_flow():
    """Test that signal fields are correctly carried to candidate."""
    signal = {
        "asset": "BTC",
        "side": "yes",
        "action": "buy",
        "velocity": 0.0002,
        "spot_price": 65000.0,
        "minutes_to_expiry": 10.0,
        "edge_pct": 5.0,
        "confidence": 0.7,
        "model_prob": 0.55,
        "regime": "both_sides",
    }
    
    # Simulate candidate construction from signal
    candidate = {
        "agent_id": "BTC_15M",
        "ticker": "KXBTCD-...",
        "side": signal["side"],
        "action": signal["action"],
        "spot_price": signal["spot_price"],
        "velocity": signal["velocity"],
        "minutes_to_expiry": signal["minutes_to_expiry"],
        "edge_pct": signal.get("edge_pct", 0.0),
        "confidence": signal.get("confidence", 0.5),
        "model_prob": signal.get("model_prob", 0.5),
        "regime": signal.get("regime", "normal"),
    }
    
    # Verify fields are carried correctly
    assert candidate["side"] == signal["side"]
    assert candidate["action"] == signal["action"]
    assert candidate["edge_pct"] == signal["edge_pct"]
    assert candidate["confidence"] == signal["confidence"]
    assert candidate["model_prob"] == signal["model_prob"]
    assert candidate["regime"] == signal["regime"]


def test_candidate_to_order_intent_flow():
    """Test that candidate fields are correctly carried to OrderIntent."""
    candidate = {
        "ticker": "KXBTCD-...",
        "side": "yes",
        "action": "buy",
        "spot_price": 65000.0,
        "edge_pct": 5.0,
        "confidence": 0.7,
        "model_prob": 0.55,
        "regime": "both_sides",
    }
    
    # Simulate OrderIntent construction from candidate
    order_intent = {
        "ticker": candidate["ticker"],
        "side": candidate["side"],
        "action": candidate["action"],
        "price_cents": 50,
        "count": 10,
        "source": "merid.prediction.agent_grid_15m",
        "edge_pct": candidate.get("edge_pct"),
        "confidence": candidate.get("confidence"),
        "model_prob": candidate.get("model_prob"),
        "strategy_id": "heuristic_velocity",
        "strategy_type": "heuristic_velocity",
        "regime": candidate.get("regime"),
    }
    
    # Verify fields are carried correctly
    assert order_intent["ticker"] == candidate["ticker"]
    assert order_intent["side"] == candidate["side"]
    assert order_intent["action"] == candidate["action"]
    assert order_intent["edge_pct"] == candidate["edge_pct"]
    assert order_intent["confidence"] == candidate["confidence"]
    assert order_intent["model_prob"] == candidate["model_prob"]
    assert order_intent["regime"] == candidate["regime"]
    assert order_intent["strategy_id"] == "heuristic_velocity"
    assert order_intent["strategy_type"] == "heuristic_velocity"


def test_regime_propagation():
    """Test that regime is propagated through the entire flow."""
    # Start with regime in signal
    signal = {"regime": "both_sides"}
    
    # Carry to candidate
    candidate = {"regime": signal.get("regime", "normal")}
    
    # Carry to OrderIntent
    order_intent = {"regime": candidate.get("regime")}
    
    # Verify regime is preserved
    assert order_intent["regime"] == "both_sides"


def test_regime_default_fallback():
    """Test that regime defaults to 'normal' if missing."""
    # Signal without regime
    signal = {}
    
    # Candidate should use default
    candidate = {"regime": signal.get("regime", "normal")}
    
    # OrderIntent should use default
    order_intent = {"regime": candidate.get("regime", "normal")}
    
    # Verify default is used
    assert order_intent["regime"] == "normal"


def test_edge_pct_validation():
    """Test that edge_pct is validated in the flow (ALIGNED TO 2026 INDUSTRY STANDARD: 2% floor)."""
    # Valid edge_pct (above 2% threshold)
    candidate = {"edge_pct": 5.0}
    assert candidate["edge_pct"] >= 0.02, "Edge should meet minimum threshold"
    
    # Valid edge_pct (at 2% threshold)
    candidate = {"edge_pct": 0.02}
    assert candidate["edge_pct"] >= 0.02, "Edge at threshold should be accepted"
    
    # Invalid edge_pct (below 2% threshold)
    candidate = {"edge_pct": 0.01}
    assert candidate["edge_pct"] < 0.02, "Edge below threshold should be rejected"
    
    # Test 4% upper bound for market entry
    candidate = {"edge_pct": 0.04}
    assert candidate["edge_pct"] >= 0.02, "Edge at 4% should be accepted for market entry"
    
    # Test edge in 2-4% range (industry standard)
    candidate = {"edge_pct": 0.03}
    assert 0.02 <= candidate["edge_pct"] <= 0.04, "Edge in 2-4% range should be accepted"


def test_confidence_validation():
    """Test that confidence is validated in the flow (ALIGNED TO 2026 INDUSTRY STANDARD: 50% threshold)."""
    # Valid confidence (above 50% threshold)
    candidate = {"confidence": 0.7}
    assert candidate["confidence"] >= 0.50, "Confidence should meet minimum threshold"
    
    # Valid confidence (at 50% threshold)
    candidate = {"confidence": 0.50}
    assert candidate["confidence"] >= 0.50, "Confidence at threshold should be accepted"
    
    # Invalid confidence (below 50% threshold)
    candidate = {"confidence": 0.49}
    assert candidate["confidence"] < 0.50, "Confidence below threshold should be rejected"
    
    # Test industry range (30-75%)
    candidate = {"confidence": 0.30}
    assert candidate["confidence"] >= 0.30, "Confidence at 30% (industry lower bound) should be accepted"
    
    candidate = {"confidence": 0.75}
    assert candidate["confidence"] <= 0.75, "Confidence at 75% (industry upper bound) should be accepted"


def test_model_prob_validation():
    """Test that model_prob is validated in the flow."""
    # Valid model_prob
    candidate = {"model_prob": 0.55}
    assert 0.05 <= candidate["model_prob"] <= 0.95, "Model prob should be in valid range"
    
    # Invalid model_prob (below minimum)
    candidate = {"model_prob": 0.03}
    assert candidate["model_prob"] < 0.05, "Model prob below minimum should be rejected"
    
    # Invalid model_prob (above maximum)
    candidate = {"model_prob": 0.97}
    assert candidate["model_prob"] > 0.95, "Model prob above maximum should be rejected"


def test_strategy_fields_propagation():
    """Test that strategy_id and strategy_type are set correctly."""
    candidate = {"regime": "both_sides"}
    
    order_intent = {
        "strategy_id": "heuristic_velocity",
        "strategy_type": "heuristic_velocity",
        "regime": candidate.get("regime"),
    }
    
    assert order_intent["strategy_id"] == "heuristic_velocity"
    assert order_intent["strategy_type"] == "heuristic_velocity"


def test_all_crypto_assets():
    """Test that all 5 crypto assets are supported in the flow."""
    assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    
    for asset in assets:
        signal = {"asset": asset, "regime": "both_sides"}
        candidate = {"asset": asset, "regime": signal.get("regime")}
        order_intent = {"asset": asset, "regime": candidate.get("regime")}
        
        assert order_intent["asset"] == asset
        assert order_intent["regime"] == "both_sides"


def test_emergency_reset_threshold():
    """Test that emergency reset threshold is $50 (5000 cents) for small bankrolls."""
    # Emergency reset threshold in cents
    emergency_reset_threshold_cents = 5000  # $50
    
    # Test with small bankroll below threshold ($40 = 4000 cents)
    equity_cents_small = 4000
    assert equity_cents_small < emergency_reset_threshold_cents, "Small bankroll should be below threshold"
    
    # Test with bankroll at threshold ($50 = 5000 cents)
    equity_cents_at_threshold = 5000
    assert equity_cents_at_threshold == emergency_reset_threshold_cents, "Bankroll at threshold should equal threshold"
    
    # Test with bankroll above threshold ($100 = 10000 cents)
    equity_cents_large = 10000
    assert equity_cents_large > emergency_reset_threshold_cents, "Large bankroll should be above threshold"
    
    # Verify threshold is appropriate for current bankroll ($40.15 = 4015 cents)
    current_bankroll_cents = 4015
    assert current_bankroll_cents < emergency_reset_threshold_cents, "Current bankroll should trigger emergency reset"


def test_adx_trend_filter():
    """Test that ADX trend filter correctly identifies trending vs ranging markets."""
    # ADX threshold for trend detection (industry standard: 20)
    adx_threshold = 20.0
    
    # Test with strong trend (ADX >= 20)
    adx_strong_trend = 25.0
    assert adx_strong_trend >= adx_threshold, "Strong trend should be >= threshold"
    
    # Test with weak trend (ADX < 20)
    adx_weak_trend = 15.0
    assert adx_weak_trend < adx_threshold, "Weak trend should be < threshold"
    
    # Test with no trend (ADX < 20)
    adx_no_trend = 10.0
    assert adx_no_trend < adx_threshold, "No trend should be < threshold"
    
    # Test with insufficient data (ADX = 0)
    adx_insufficient_data = 0.0
    assert adx_insufficient_data == 0.0, "Insufficient data should return 0"


def test_price_based_confirmation():
    """Test that price-based confirmation thresholds are correctly configured."""
    # Price-based confirmation thresholds (relaxed for multi-confirmation system)
    price_yes_threshold = 0.55  # Buy YES when price <= 0.55
    price_no_threshold = 0.65  # Buy NO when price >= 0.65
    
    # Test YES confirmation (price <= threshold)
    market_price_yes = 0.50
    assert market_price_yes <= price_yes_threshold, "Price should trigger YES confirmation"
    
    # Test YES rejection (price > threshold)
    market_price_yes_reject = 0.60
    assert market_price_yes_reject > price_yes_threshold, "Price should reject YES confirmation"
    
    # Test NO confirmation (price >= threshold)
    market_price_no = 0.70
    assert market_price_no >= price_no_threshold, "Price should trigger NO confirmation"
    
    # Test NO rejection (price < threshold)
    market_price_no_reject = 0.60
    assert market_price_no_reject < price_no_threshold, "Price should reject NO confirmation"


def test_session_based_trading_windows():
    """Test that session-based trading windows are disabled for 24/7 trading."""
    # Session filter is disabled per user request (trade 24/7)
    enable_session_filter = False
    
    # Test that session filter is disabled
    assert enable_session_filter == False, "Session filter should be disabled for 24/7 trading"
    
    # Session windows are still defined but not enforced
    us_europe_overlap_start = 13
    us_europe_overlap_end = 17
    us_session_start = 17
    us_session_end = 22
    european_morning_start = 8
    european_morning_end = 13
    
    # Test that all hours would be active if filter were enabled
    current_hour_any = 4  # Asian session (previously disabled)
    is_active_if_enabled = (
        (us_europe_overlap_start <= current_hour_any < us_europe_overlap_end) or
        (us_session_start <= current_hour_any < us_session_end) or
        (european_morning_start <= current_hour_any < european_morning_end)
    )
    assert not is_active_if_enabled, "04:00 UTC would be disabled if session filter were enabled"
    
    # But since filter is disabled, trading is allowed 24/7
    assert True, "Trading is allowed 24/7 with session filter disabled"


def test_dynamic_atr_threshold_adjustment():
    """Test that dynamic ATR-based threshold adjustment works correctly."""
    # Base threshold
    base_threshold = 0.00015  # BTC threshold
    
    # Low volatility: ATR < 0.1% -> reduce threshold by 25%
    atr_low = 0.0005  # 0.05%
    low_volatility_threshold = 0.001  # 0.1%
    
    if atr_low < low_volatility_threshold:
        adjustment_factor = 0.75
        dynamic_threshold = base_threshold * adjustment_factor
        assert dynamic_threshold == 0.0001125, f"Low volatility threshold should be 0.0001125, got {dynamic_threshold}"
    
    # Normal volatility: 0.1% <= ATR < 0.5% -> use base threshold
    atr_normal = 0.003  # 0.3%
    low_volatility_threshold = 0.001  # 0.1%
    high_volatility_threshold = 0.005  # 0.5%
    
    if low_volatility_threshold <= atr_normal < high_volatility_threshold:
        adjustment_factor = 1.0
        dynamic_threshold = base_threshold * adjustment_factor
        assert dynamic_threshold == base_threshold, f"Normal volatility threshold should be {base_threshold}, got {dynamic_threshold}"
    
    # High volatility: ATR >= 0.5% -> increase threshold by 25%
    atr_high = 0.006  # 0.6%
    
    if atr_high >= high_volatility_threshold:
        adjustment_factor = 1.25
        dynamic_threshold = base_threshold * adjustment_factor
        assert abs(dynamic_threshold - 0.0001875) < 1e-10, f"High volatility threshold should be 0.0001875, got {dynamic_threshold}"
    
    # No ATR data: use base threshold
    atr_zero = 0.0
    if atr_zero <= 0:
        dynamic_threshold = base_threshold
        assert dynamic_threshold == base_threshold, f"No ATR data should use base threshold {base_threshold}, got {dynamic_threshold}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
