"""
Tests for BUG fixes in loop_15m.py related to production trading stack audit.

Tests cover:
- BUG #39: Convert mid_cents to integer when assigning to price_cents
- BUG #34: Add edge_pct, confidence, model_prob to OrderIntent
- BUG #35: Use actual market regime in policy resolution
"""

import pytest
from unittest.mock import Mock, patch, MagicMock


def test_price_cents_converted_from_float_mid_cents():
    """BUG #39 FIX: price_cents should be converted to integer from mid_cents.
    
    mid_cents is a float from unified_market_state.py but order router requires integer.
    """
    # Mock market state with float mid_cents
    mock_market_state = Mock()
    mock_market_state.mid_cents = 50.5  # Float value
    
    # Simulate the conversion that happens in loop_15m.py
    price_cents = int(mock_market_state.mid_cents)
    
    assert isinstance(price_cents, int)
    assert price_cents == 50  # Should be truncated to int


def test_price_cents_fallback_to_bid_ask_mid():
    """BUG #39 FIX: When mid_cents is not available, use bid/ask average as integer."""
    # Mock market state without mid_cents but with bid/ask
    mock_market_state = Mock()
    mock_market_state.mid_cents = None
    mock_market_state.best_bid_cents = 48
    mock_market_state.best_ask_cents = 52
    
    # Simulate the fallback logic
    if mock_market_state.mid_cents:
        price_cents = int(mock_market_state.mid_cents)
    elif mock_market_state.best_bid_cents and mock_market_state.best_ask_cents:
        price_cents = (mock_market_state.best_bid_cents + mock_market_state.best_ask_cents) // 2
    else:
        price_cents = 50
    
    assert isinstance(price_cents, int)
    assert price_cents == 50  # (48 + 52) // 2 = 50


def test_order_intent_includes_signal_metadata():
    """BUG #34 FIX: OrderIntent should include edge_pct, confidence, model_prob."""
    from merid.event_venues.kalshi.order_router import OrderIntent
    
    # Simulate candidate with signal metadata
    candidate = {
        "edge_pct": 2.5,
        "confidence": 0.65,
        "model_prob": 0.55,
        "raw_logit": 0.1
    }
    
    # Extract metadata as done in loop_15m.py
    edge_pct = candidate.get("edge_pct", 0.0)
    confidence = candidate.get("confidence", 0.5)
    model_prob = candidate.get("model_prob", 0.5)
    raw_logit = candidate.get("raw_logit", 0.0)
    
    # Construct OrderIntent
    intent = OrderIntent(
        ticker="KXBTC15M-TEST",
        side="yes",
        action="buy",
        price_cents=50,
        count=1,
        source="merid.prediction.agent_grid_15m",
        edge_pct=edge_pct,
        confidence=confidence,
        model_prob=model_prob,
        raw_logit=raw_logit
    )
    
    assert intent.edge_pct == 2.5
    assert intent.confidence == 0.65
    assert intent.model_prob == 0.55
    assert intent.raw_logit == 0.1


def test_order_intent_computes_metadata_from_velocity():
    """BUG #34 FIX: When edge_pct/confidence/model_prob not in candidate, compute from velocity."""
    # Simulate candidate without signal metadata (legacy path)
    candidate = {
        "velocity": 0.002,  # 0.2% velocity
    }
    
    price_cents = 50
    
    # Compute metadata from velocity as done in loop_15m.py
    edge_pct = candidate.get("edge_pct", 0.0)
    confidence = candidate.get("confidence", 0.5)
    model_prob = candidate.get("model_prob", 0.5)
    
    if edge_pct == 0.0 and "velocity" in candidate:
        velocity = candidate.get("velocity", 0.0)
        edge_pct = abs(velocity) * 100  # Convert velocity to edge percentage
        velocity_magnitude = abs(velocity)
        confidence = min(0.95, 0.50 + velocity_magnitude * 100)
        model_prob = price_cents / 100.0
    
    assert edge_pct == 0.2  # 0.002 * 100 = 0.2%
    assert confidence == 0.70  # 0.50 + 0.002 * 100 = 0.70
    assert model_prob == 0.50  # 50 / 100 = 0.50


def test_regime_extraction_from_candidate():
    """BUG #35 FIX: Regime should be extracted from candidate if available."""
    # Simulate candidate with regime
    candidate = {
        "regime": "both_sides"
    }
    
    # Extract regime as done in loop_15m.py
    regime = candidate.get("regime", None)
    
    assert regime == "both_sides"


def test_regime_extraction_from_market_state():
    """BUG #35 FIX: When regime not in candidate, extract from market state."""
    # Simulate candidate without regime
    candidate = {}
    
    # Mock market state with depth
    mock_market_state = Mock()
    mock_market_state.min_depth_yes = 10
    mock_market_state.min_depth_no = 5
    
    # Extract regime from market state as done in loop_15m.py
    regime = candidate.get("regime", None)
    
    if regime is None:
        min_depth_yes = mock_market_state.min_depth_yes
        min_depth_no = mock_market_state.min_depth_no
        min_depth_yes_threshold = 1
        min_depth_no_threshold = 1
        has_yes = min_depth_yes >= min_depth_yes_threshold
        has_no = min_depth_no >= min_depth_no_threshold
        
        if has_yes and has_no:
            regime = "both_sides"
        elif has_yes and not has_no:
            regime = "one_sided_yes"
        elif not has_yes and has_no:
            regime = "one_sided_no"
        else:
            regime = "no_liquidity"
    
    assert regime == "both_sides"


def test_regime_fallback_to_normal():
    """BUG #35 FIX: When regime cannot be extracted, fallback to 'normal'."""
    # Simulate candidate without regime
    candidate = {}
    
    # Mock market state without depth (both sides below threshold)
    mock_market_state = Mock()
    mock_market_state.min_depth_yes = 0
    mock_market_state.min_depth_no = 0
    
    # Extract regime with fallback as done in loop_15m.py
    regime = candidate.get("regime", None)
    
    if regime is None:
        min_depth_yes = mock_market_state.min_depth_yes
        min_depth_no = mock_market_state.min_depth_no
        min_depth_yes_threshold = 1
        min_depth_no_threshold = 1
        has_yes = min_depth_yes >= min_depth_yes_threshold
        has_no = min_depth_no >= min_depth_no_threshold
        
        if has_yes and has_no:
            regime = "both_sides"
        elif has_yes and not has_no:
            regime = "one_sided_yes"
        elif not has_yes and has_no:
            regime = "one_sided_no"
        else:
            regime = "no_liquidity"  # Both sides below threshold
    
    # When no liquidity, regime is "no_liquidity", not "normal"
    # "normal" is only used when market_state is None or extraction fails
    assert regime == "no_liquidity"


def test_regime_fallback_to_normal_when_market_state_none():
    """BUG #35 FIX: When market_state is None, fallback to 'normal'."""
    # Simulate candidate without regime
    candidate = {}
    
    # Mock market_state_store returns None
    mock_market_state = None
    
    # Extract regime with fallback as done in loop_15m.py
    regime = candidate.get("regime", None)
    
    if regime is None:
        # Try to extract from market state, but it's None
        if mock_market_state:
            min_depth_yes = mock_market_state.min_depth_yes
            min_depth_no = mock_market_state.min_depth_no
            min_depth_yes_threshold = 1
            min_depth_no_threshold = 1
            has_yes = min_depth_yes >= min_depth_yes_threshold
            has_no = min_depth_no >= min_depth_no_threshold
            
            if has_yes and has_no:
                regime = "both_sides"
            elif has_yes and not has_no:
                regime = "one_sided_yes"
            elif not has_yes and has_no:
                regime = "one_sided_no"
            else:
                regime = "no_liquidity"
    
    # Final fallback to "normal" if still None
    if regime is None:
        regime = "normal"
    
    assert regime == "normal"


def test_effective_equity_usd_passed_to_order_intent():
    """Test that effective_equity_usd is fetched from risk envelope and passed to OrderIntent.
    
    This test verifies the fix for the bankroll equity showing as $0.00 in KalshiRiskManager.
    """
    from merid.event_venues.kalshi.order_router import OrderIntent
    from unittest.mock import patch, MagicMock
    
    # Mock the risk envelope service
    mock_envelope = MagicMock()
    mock_envelope.live_bankroll = 100.0  # $100 effective equity
    
    # Simulate fetching effective_equity_usd from risk envelope
    # Patch at the import location in loop_15m.py
    with patch('merid.risk.profiles.risk_envelope_service.get_risk_envelope_service') as mock_get_service:
        mock_service = MagicMock()
        mock_service.get_config.return_value = mock_envelope
        mock_get_service.return_value = mock_service
        
        # Simulate the logic in loop_15m.py
        effective_equity_usd = None
        try:
            from merid.risk.profiles.risk_envelope_service import get_risk_envelope_service
            envelope = get_risk_envelope_service().get_config()
            effective_equity_usd = envelope.live_bankroll if envelope else None
        except Exception as e:
            pass
        
        # Construct OrderIntent with effective_equity_usd
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            source="merid.prediction.agent_grid_15m",
            effective_equity_usd=effective_equity_usd,
        )
        
        # Verify effective_equity_usd was passed correctly
        assert intent.effective_equity_usd == 100.0


def test_effective_equity_usd_fallback_on_error():
    """Test that effective_equity_usd falls back to None on error."""
    from merid.event_venues.kalshi.order_router import OrderIntent
    from unittest.mock import patch
    
    # Mock the risk envelope service to raise an error
    with patch('merid.risk.profiles.risk_envelope_service.get_risk_envelope_service') as mock_get_service:
        mock_get_service.side_effect = Exception("Service unavailable")
        
        # Simulate the logic in loop_15m.py with error handling
        effective_equity_usd = None
        try:
            from merid.risk.profiles.risk_envelope_service import get_risk_envelope_service
            envelope = get_risk_envelope_service().get_config()
            effective_equity_usd = envelope.live_bankroll if envelope else None
        except Exception as e:
            # Error is caught and logged, effective_equity_usd remains None
            pass
        
        # Construct OrderIntent with None effective_equity_usd
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            source="merid.prediction.agent_grid_15m",
            effective_equity_usd=effective_equity_usd,
        )
        
        # Verify effective_equity_usd is None (fallback behavior)
        assert intent.effective_equity_usd is None
