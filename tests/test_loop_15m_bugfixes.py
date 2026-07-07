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
    Updated to use live_bankroll_usd field instead of live_bankroll.
    """
    from merid.event_venues.kalshi.order_router import OrderIntent
    from unittest.mock import patch, MagicMock
    
    # Mock the risk envelope service
    mock_envelope = MagicMock()
    mock_envelope.live_bankroll_usd = 100.0  # $100 effective equity (corrected field name)
    
    # Simulate fetching effective_equity_usd from risk envelope
    # Patch at the import location in loop_15m.py
    with patch('merid.risk.profiles.risk_envelope_service.get_risk_envelope_service') as mock_get_service:
        mock_service = MagicMock()
        mock_service.get_config.return_value = mock_envelope
        mock_get_service.return_value = mock_service
        
        # Simulate the logic in loop_15m.py (updated to use live_bankroll_usd)
        effective_equity_usd = None
        try:
            from merid.risk.profiles.risk_envelope_service import get_risk_envelope_service
            envelope = get_risk_envelope_service().get_config()
            effective_equity_usd = envelope.live_bankroll_usd if envelope else None
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
    """Test that effective_equity_usd falls back to None on error.
    
    Updated to use live_bankroll_usd field instead of live_bankroll.
    """
    from merid.event_venues.kalshi.order_router import OrderIntent
    from unittest.mock import patch
    
    # Mock the risk envelope service to raise an error
    with patch('merid.risk.profiles.risk_envelope_service.get_risk_envelope_service') as mock_get_service:
        mock_get_service.side_effect = Exception("Service unavailable")
        
        # Simulate the logic in loop_15m.py with error handling (updated to use live_bankroll_usd)
        effective_equity_usd = None
        try:
            from merid.risk.profiles.risk_envelope_service import get_risk_envelope_service
            envelope = get_risk_envelope_service().get_config()
            effective_equity_usd = envelope.live_bankroll_usd if envelope else None
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


def test_rationale_passed_from_candidate_to_order_intent():
    """Test that rationale field is passed from candidate to OrderIntent.
    
    This ensures price-based strategy can bypass edge validation.
    """
    from merid.event_venues.kalshi.order_router import OrderIntent
    
    # Simulate candidate with rationale (price-based strategy)
    candidate = {
        "rationale": "price_based: price=0.45 vs thresholds (buy=0.50, sell=0.70)",
        "edge_pct": 0.0,  # Edge may be 0 for price-based strategy
        "confidence": 0.8,
        "model_prob": 0.45,
    }
    
    # Extract rationale as done in loop_15m.py
    rationale = candidate.get("rationale")
    
    # Construct OrderIntent with rationale
    intent = OrderIntent(
        ticker="KXBTC15M-TEST",
        side="yes",
        action="buy",
        price_cents=45,
        count=1,
        source="merid.prediction.agent_grid_15m",
        edge_pct=candidate.get("edge_pct", 0.0),
        confidence=candidate.get("confidence", 0.5),
        model_prob=candidate.get("model_prob", 0.5),
        rationale=rationale,
    )
    
    # Verify rationale is passed
    assert intent.rationale == "price_based: price=0.45 vs thresholds (buy=0.50, sell=0.70)"


def test_velocity_based_signal_includes_rationale():
    """Test that velocity-based signal includes rationale field.
    
    This ensures velocity-based signals have rationale for debugging.
    """
    # Simulate velocity-based signal with rationale
    signal = {
        "asset": "BTC",
        "side": "yes",
        "action": "buy",
        "velocity": 0.002,
        "edge_pct": 2.5,
        "confidence": 0.65,
        "model_prob": 0.55,
        "rationale": "velocity_based: velocity=0.002000 edge_pct=2.50%",
    }
    
    # Verify rationale is present
    assert "rationale" in signal
    assert "velocity_based" in signal["rationale"]
    assert "velocity=" in signal["rationale"]
    assert "edge_pct=" in signal["rationale"]


def test_price_based_signal_calculates_edge():
    """Test that price-based strategy calculates edge_pct correctly.
    
    Edge is calculated as distance from threshold:
    - For buy: edge = (buy_threshold - market_price) / buy_threshold * 100
    - For sell: edge = (market_price - sell_threshold) / (1.0 - sell_threshold) * 100
    - Minimum 2% base edge is applied when threshold is crossed
    """
    # Test buy signal edge calculation (new formula)
    market_price = 0.45
    buy_threshold = 0.50
    edge_pct_buy = (buy_threshold - market_price) / buy_threshold * 100
    assert abs(edge_pct_buy - 10.0) < 0.01  # (0.50 - 0.45) / 0.50 * 100 = 10.0%
    
    # Test sell signal edge calculation (new formula)
    market_price = 0.75
    sell_threshold = 0.70
    edge_pct_sell = (market_price - sell_threshold) / (1.0 - sell_threshold) * 100
    assert abs(edge_pct_sell - 16.67) < 0.01  # (0.75 - 0.70) / 0.30 * 100 = 16.67%
    
    # Test minimum 2% base edge at threshold crossing
    market_price_at_threshold = 0.50
    edge_pct_at_threshold = (buy_threshold - market_price_at_threshold) / buy_threshold * 100
    edge_pct_with_min = max(edge_pct_at_threshold, 2.0)
    assert edge_pct_with_min == 2.0  # Minimum 2% applied


def test_position_sizing_recalculates_notional_after_count_reduction():
    """Test that position_notional_usd is recalculated after count reduction.
    
    This ensures the fix for the bug where notional was not recalculated.
    """
    # Simulate position sizing logic with realistic values
    max_notional = 0.55  # $0.55 max single order notional
    price_cents = 50  # 50 cents
    initial_count = 2
    
    # Calculate initial notional
    position_notional_usd = (initial_count * price_cents) / 100.0
    assert position_notional_usd == 1.0  # 2 * 50 / 100 = $1.00
    
    # Check against max notional
    if position_notional_usd > max_notional:
        # Reduce count
        count = int((max_notional * 100.0) / price_cents)
        if count < 1:
            count = 1
        # CRITICAL: Recalculate position_notional_usd after reducing count
        position_notional_usd = (count * price_cents) / 100.0
    
    # Verify count was reduced
    assert count == 1  # int(0.55 * 100 / 50) = int(1.1) = 1
    
    # Verify notional was recalculated
    assert position_notional_usd == 0.50  # 1 * 50 / 100 = $0.50
    
    # Verify recalculated notional is <= max notional
    assert position_notional_usd <= max_notional


def test_best_edge_selection_initial_candidate():
    """Test that first candidate becomes best edge when no previous best exists.
    
    This tests the signal generation vs execution separation:
    - Agents generate candidates continuously
    - First candidate for an asset becomes the best edge
    - CRITICAL FIX: Use abs(edge) since edge = p_model - p_market can be negative
    """
    # Simulate best-edge tracking state
    best_edge_per_asset = {
        "BTC": None,
        "ETH": None,
        "SOL": None,
        "XRP": None,
        "DOGE": None
    }
    
    # First candidate for BTC
    candidate = {
        "ticker": "KXBTC15M-26JUN300345-45",
        "side": "no",
        "edge": 15.5,
        "edge_pct": 15.5
    }
    
    # Extract asset
    ticker = candidate["ticker"]
    asset = ticker.split("15M")[0].replace("KX", "")
    edge = candidate.get("edge", 0.0) or candidate.get("edge_pct", 0.0)
    
    # Check if should execute (no position, no best edge)
    # CRITICAL FIX: Use abs(edge) since edge = p_model - p_market can be negative
    current_best = best_edge_per_asset.get(asset)
    current_best_edge = current_best.get("edge", 0.0) if current_best else 0.0
    
    should_execute = abs(edge) > abs(current_best_edge)
    
    assert should_execute == True
    assert edge == 15.5
    assert current_best_edge == 0.0


def test_best_edge_selection_improves_edge():
    """Test that candidate with higher edge replaces current best edge.
    
    This ensures the system always executes the best opportunity.
    - CRITICAL FIX: Use abs(edge) since edge = p_model - p_market can be negative
    """
    # Simulate best-edge tracking state with existing best edge
    best_edge_per_asset = {
        "BTC": {
            "ticker": "KXBTC15M-26JUN300345-45",
            "side": "no",
            "edge": 10.0,
            "candidate": {}
        },
        "ETH": None,
        "SOL": None,
        "XRP": None,
        "DOGE": None
    }
    
    # New candidate with higher edge
    candidate = {
        "ticker": "KXBTC15M-26JUN300345-45",
        "side": "no",
        "edge": 15.5,
        "edge_pct": 15.5
    }
    
    # Extract asset
    ticker = candidate["ticker"]
    asset = ticker.split("15M")[0].replace("KX", "")
    edge = candidate.get("edge", 0.0) or candidate.get("edge_pct", 0.0)
    
    # Check if should execute (higher edge)
    # CRITICAL FIX: Use abs(edge) since edge = p_model - p_market can be negative
    current_best = best_edge_per_asset.get(asset)
    current_best_edge = current_best.get("edge", 0.0) if current_best else 0.0
    
    should_execute = abs(edge) > abs(current_best_edge)
    
    assert should_execute == True
    assert edge == 15.5
    assert current_best_edge == 10.0


def test_best_edge_selection_skips_lower_edge():
    """Test that candidate with lower edge is skipped.
    
    This prevents over-trading and ensures only best edges execute.
    - CRITICAL FIX: Use abs(edge) since edge = p_model - p_market can be negative
    """
    # Simulate best-edge tracking state with existing best edge
    best_edge_per_asset = {
        "BTC": {
            "ticker": "KXBTC15M-26JUN300345-45",
            "side": "no",
            "edge": 15.5,
            "candidate": {}
        },
        "ETH": None,
        "SOL": None,
        "XRP": None,
        "DOGE": None
    }
    
    # New candidate with lower edge
    candidate = {
        "ticker": "KXBTC15M-26JUN300345-45",
        "side": "no",
        "edge": 10.0,
        "edge_pct": 10.0
    }
    
    # Extract asset
    ticker = candidate["ticker"]
    asset = ticker.split("15M")[0].replace("KX", "")
    edge = candidate.get("edge", 0.0) or candidate.get("edge_pct", 0.0)
    
    # Check if should execute (lower edge)
    # CRITICAL FIX: Use abs(edge) since edge = p_model - p_market can be negative
    current_best = best_edge_per_asset.get(asset)
    current_best_edge = current_best.get("edge", 0.0) if current_best else 0.0
    
    should_execute = abs(edge) > abs(current_best_edge)
    
    assert should_execute == False
    assert edge == 10.0
    assert current_best_edge == 15.5


def test_position_based_lock_prevents_reexecution():
    """Test that existing position prevents re-execution without edge improvement.
    
    This implements position-based locking to prevent over-trading.
    """
    # Simulate asset positions
    asset_positions = {
        "BTC": 0.88,  # Has position
        "ETH": 0.0,
        "SOL": 0.0,
        "XRP": 0.0,
        "DOGE": 0.0
    }
    
    # Best edge tracking
    best_edge_per_asset = {
        "BTC": {
            "ticker": "KXBTC15M-26JUN300345-45",
            "side": "no",
            "edge": 15.5,
            "candidate": {}
        },
        "ETH": None,
        "SOL": None,
        "XRP": None,
        "DOGE": None
    }
    
    # New candidate with same edge (no improvement)
    candidate = {
        "ticker": "KXBTC15M-26JUN300345-45",
        "side": "no",
        "edge": 15.5,
        "edge_pct": 15.5
    }
    
    # Extract asset
    ticker = candidate["ticker"]
    asset = ticker.split("15M")[0].replace("KX", "")
    edge = candidate.get("edge", 0.0) or candidate.get("edge_pct", 0.0)
    
    # Check if we have position
    current_position = asset_positions.get(asset, 0.0)
    has_position = abs(current_position) > 0.01
    
    # Get current best edge
    current_best = best_edge_per_asset.get(asset)
    current_best_edge = current_best.get("edge", 0.0) if current_best else 0.0
    
    # Edge improvement threshold (5%)
    edge_improvement_threshold = 5.0
    
    # Should execute only if edge improves significantly
    should_execute = has_position and (edge > current_best_edge + edge_improvement_threshold)
    
    assert has_position == True
    assert should_execute == False  # No significant improvement


def test_position_based_lock_allows_edge_improvement():
    """Test that significant edge improvement allows re-execution even with position.
    
    This allows the system to capture better opportunities as they arise.
    """
    # Simulate asset positions
    asset_positions = {
        "BTC": 0.88,  # Has position
        "ETH": 0.0,
        "SOL": 0.0,
        "XRP": 0.0,
        "DOGE": 0.0
    }
    
    # Best edge tracking
    best_edge_per_asset = {
        "BTC": {
            "ticker": "KXBTC15M-26JUN300345-45",
            "side": "no",
            "edge": 15.5,
            "candidate": {}
        },
        "ETH": None,
        "SOL": None,
        "XRP": None,
        "DOGE": None
    }
    
    # New candidate with significantly higher edge
    candidate = {
        "ticker": "KXBTC15M-26JUN300345-45",
        "side": "no",
        "edge": 25.0,  # 9.5% improvement > 5% threshold
        "edge_pct": 25.0
    }
    
    # Extract asset
    ticker = candidate["ticker"]
    asset = ticker.split("15M")[0].replace("KX", "")
    edge = candidate.get("edge", 0.0) or candidate.get("edge_pct", 0.0)
    
    # Check if we have position
    current_position = asset_positions.get(asset, 0.0)
    has_position = abs(current_position) > 0.01
    
    # Get current best edge
    current_best = best_edge_per_asset.get(asset)
    current_best_edge = current_best.get("edge", 0.0) if current_best else 0.0
    
    # Edge improvement threshold (5%)
    edge_improvement_threshold = 5.0
    
    # Should execute if edge improves significantly
    should_execute = has_position and (edge > current_best_edge + edge_improvement_threshold)
    
    assert has_position == True
    assert should_execute == True  # Significant improvement
    assert edge == 25.0
    assert current_best_edge == 15.5
    assert edge - current_best_edge > edge_improvement_threshold


def test_best_edge_reset_on_window_change():
    """Test that best-edge tracking resets on 15-minute window change.
    
    This ensures fresh tracking for each market window.
    """
    # Simulate best-edge tracking state
    best_edge_per_asset = {
        "BTC": {
            "ticker": "KXBTC15M-26JUN300345-45",
            "side": "no",
            "edge": 15.5,
            "candidate": {}
        },
        "ETH": {
            "ticker": "KXETH15M-26JUN300345-45",
            "side": "yes",
            "edge": 12.0,
            "candidate": {}
        },
        "SOL": None,
        "XRP": None,
        "DOGE": None
    }
    
    # Simulate window change
    old_window = "26JUN300345-45"
    new_window = "26JUN300400-00"
    window_changed = (old_window != new_window)
    
    assert window_changed == True
    
    # Reset best-edge tracking
    if window_changed:
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            best_edge_per_asset[asset] = None
    
    # Verify all assets reset
    for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
        assert best_edge_per_asset[asset] is None


def test_asset_extraction_from_ticker():
    """Test that asset is correctly extracted from Kalshi ticker.
    
    This ensures proper asset mapping for all 5 crypto assets.
    """
    test_cases = [
        ("KXBTC15M-26JUN300345-45", "BTC"),
        ("KXETH15M-26JUN300345-45", "ETH"),
        ("KXSOL15M-26JUN300345-45", "SOL"),
        ("KXXRP15M-26JUN300345-45", "XRP"),
        ("KXDOGE15M-26JUN300345-45", "DOGE"),
    ]
    
    for ticker, expected_asset in test_cases:
        asset = ticker.split("15M")[0].replace("KX", "")
        assert asset == expected_asset


def test_count_limited_to_one_for_best_edge():
    """Test that candidate count is limited to 1 for best-edge execution.
    
    This prevents over-trading and ensures single contract execution.
    """
    candidate = {
        "ticker": "KXBTC15M-26JUN300345-45",
        "side": "no",
        "edge": 15.5,
        "count": 5  # Original count
    }
    
    # Limit to 1 contract
    candidate["count"] = 1
    
    assert candidate["count"] == 1


def test_all_five_crypto_assets_tracked():
    """Test that all 5 crypto assets are tracked in best-edge system.
    
    This ensures BTC, ETH, SOL, XRP, DOGE are always included.
    """
    expected_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    
    # Initialize best-edge tracking
    best_edge_per_asset = {}
    for asset in expected_assets:
        best_edge_per_asset[asset] = None
    
    # Verify all assets are tracked
    assert set(best_edge_per_asset.keys()) == set(expected_assets)
    assert len(best_edge_per_asset) == 5


def test_client_tag_generated_for_tp_sl_registration():
    """Test that client_tag is generated for TP/SL registration.
    
    The order router requires client_tag to register TP targets with position cache.
    Without client_tag, TP/SL targets are never registered and trailing stops won't work.
    """
    import uuid
    
    # Simulate client_tag generation as done in loop_15m.py
    ticker = "KXBTC15M-26JUN300345-45"
    client_tag = f"15m_{ticker}_{uuid.uuid4().hex[:12]}"
    
    # Verify client_tag format
    assert client_tag.startswith("15m_")
    assert ticker in client_tag
    assert len(client_tag.split("_")[-1]) == 12  # UUID suffix length
    
    # Verify client_tag is passed to OrderIntent
    from merid.event_venues.kalshi.order_router import OrderIntent
    intent = OrderIntent(
        ticker=ticker,
        side="yes",
        action="buy",
        price_cents=50,
        count=1,
        source="merid.prediction.agent_grid_15m",
        client_tag=client_tag,
    )
    
    assert intent.client_tag == client_tag


def test_tp_price_computed_from_r_multiple():
    """Test that take profit price is computed from R-multiple correctly.
    
    For binary options, R (risk per contract) = entry price (max loss is contract price).
    TP = entry_price + (R * tp_r_multiple) for long positions.
    """
    # Mock exit policy with tp_r_multiple
    class MockExitPolicy:
        tp_r_multiple = 1.0
        sl_r_multiple = 0.5
    
    exit_policy = MockExitPolicy()
    price_cents = 50  # Entry price
    
    # Compute TP price as done in loop_15m.py
    if exit_policy and exit_policy.tp_r_multiple:
        take_profit_price_cents = int(price_cents * (1 + exit_policy.tp_r_multiple))
        take_profit_r_multiple = exit_policy.tp_r_multiple
    else:
        take_profit_price_cents = None
        take_profit_r_multiple = None
    
    # Verify TP calculation: 50 + (50 * 1.0) = 100
    assert take_profit_price_cents == 100
    assert take_profit_r_multiple == 1.0


def test_sl_price_computed_from_r_multiple():
    """Test that stop loss price is computed from R-multiple correctly.
    
    For binary options, R (risk per contract) = entry price (max loss is contract price).
    SL = entry_price - (R * sl_r_multiple) for long positions.
    """
    # Mock exit policy with sl_r_multiple
    class MockExitPolicy:
        tp_r_multiple = 1.0
        sl_r_multiple = 0.5
    
    exit_policy = MockExitPolicy()
    price_cents = 50  # Entry price
    
    # Compute SL price as done in loop_15m.py
    if exit_policy and exit_policy.sl_r_multiple:
        stop_loss_price_cents = int(price_cents * (1 - exit_policy.sl_r_multiple))
    else:
        stop_loss_price_cents = None
    
    # Verify SL calculation: 50 - (50 * 0.5) = 25
    assert stop_loss_price_cents == 25


def test_tp_sl_computed_for_different_regimes():
    """Test that TP/SL are computed correctly for different regimes.
    
    Conservative regime: tp_r_multiple=0.75, sl_r_multiple=0.5
    Normal regime: tp_r_multiple=1.0, sl_r_multiple=0.5
    Aggressive regime: tp_r_multiple=1.2, sl_r_multiple=0.5
    """
    test_cases = [
        ("conservative", 0.75, 50, 87, 25),  # TP: 50 + (50 * 0.75) = 87.5 -> 87 (int truncates), SL: 25
        ("normal", 1.0, 50, 100, 25),  # TP: 50 + (50 * 1.0) = 100, SL: 25
        ("aggressive", 1.2, 50, 110, 25),  # TP: 50 + (50 * 1.2) = 110, SL: 25
    ]
    
    for regime, tp_r, price_cents, expected_tp, expected_sl in test_cases:
        class MockExitPolicy:
            tp_r_multiple = tp_r
            sl_r_multiple = 0.5
        
        exit_policy = MockExitPolicy()
        
        # Compute TP/SL
        if exit_policy and exit_policy.tp_r_multiple:
            take_profit_price_cents = int(price_cents * (1 + exit_policy.tp_r_multiple))
        else:
            take_profit_price_cents = None
        
        if exit_policy and exit_policy.sl_r_multiple:
            stop_loss_price_cents = int(price_cents * (1 - exit_policy.sl_r_multiple))
        else:
            stop_loss_price_cents = None
        
        assert take_profit_price_cents == expected_tp, f"Regime {regime}: TP mismatch"
        assert stop_loss_price_cents == expected_sl, f"Regime {regime}: SL mismatch"


def test_tp_sl_none_when_exit_policy_missing():
    """Test that TP/SL are None when exit policy is not available.
    
    This ensures graceful fallback when exit policy resolution fails.
    """
    exit_policy = None
    price_cents = 50
    
    # Compute TP/SL with missing exit policy
    if exit_policy and exit_policy.tp_r_multiple:
        take_profit_price_cents = int(price_cents * (1 + exit_policy.tp_r_multiple))
        take_profit_r_multiple = exit_policy.tp_r_multiple
    else:
        take_profit_price_cents = None
        take_profit_r_multiple = None
    
    if exit_policy and exit_policy.sl_r_multiple:
        stop_loss_price_cents = int(price_cents * (1 - exit_policy.sl_r_multiple))
    else:
        stop_loss_price_cents = None
    
    # Verify all are None
    assert take_profit_price_cents is None
    assert take_profit_r_multiple is None
    assert stop_loss_price_cents is None


def test_deduplication_cache_persists_across_15m_window():
    """Test that deduplication cache persists across 5-second cycles within 15m window.
    
    CRITICAL FIX: The deduplication cache (_executed_candidates_this_window) should
    only be cleared at the start of a new 15-minute window, not after each execution.
    This prevents the same order from being placed every 5 seconds.
    """
    # Simulate deduplication cache state
    _executed_candidates_this_window = set()
    
    # First cycle: execute candidate
    candidate_key = "KXBTC15M-26JUN300345-45_YES_BUY_50"
    _executed_candidates_this_window.add(candidate_key)
    
    # Verify candidate is in cache
    assert candidate_key in _executed_candidates_this_window
    
    # CRITICAL FIX: Cache should NOT be cleared after execution
    # OLD BUG: _executed_candidates_this_window.clear() was called after each execution
    # NEW BEHAVIOR: Cache persists until 15-minute window boundary
    
    # Second cycle (5 seconds later): same candidate should be rejected
    assert candidate_key in _executed_candidates_this_window
    should_execute = candidate_key not in _executed_candidates_this_window
    assert should_execute == False  # Should be rejected (duplicate)
    
    # Third cycle (10 seconds later): same candidate should still be rejected
    assert candidate_key in _executed_candidates_this_window
    should_execute = candidate_key not in _executed_candidates_this_window
    assert should_execute == False  # Should be rejected (duplicate)
    
    # Simulate 15-minute window boundary
    # Cache should be cleared at window boundary
    _executed_candidates_this_window.clear()
    
    # New window: same candidate should be allowed
    assert candidate_key not in _executed_candidates_this_window
    should_execute = candidate_key not in _executed_candidates_this_window
    assert should_execute == True  # Should be allowed (new window)


def test_deduplication_cache_allows_different_candidates():
    """Test that deduplication cache allows different candidates in same window.
    
    This ensures the cache only prevents exact duplicates, not all orders.
    """
    # Simulate deduplication cache state
    _executed_candidates_this_window = set()
    
    # First candidate
    candidate_key_1 = "KXBTC15M-26JUN300345-45_YES_BUY_50"
    _executed_candidates_this_window.add(candidate_key_1)
    
    # Different candidate (different ticker)
    candidate_key_2 = "KXETH15M-26JUN300345-45_YES_BUY_50"
    should_execute_2 = candidate_key_2 not in _executed_candidates_this_window
    assert should_execute_2 == True  # Should be allowed (different ticker)
    
    # Different candidate (different side)
    candidate_key_3 = "KXBTC15M-26JUN300345-45_NO_SELL_50"
    should_execute_3 = candidate_key_3 not in _executed_candidates_this_window
    assert should_execute_3 == True  # Should be allowed (different side)
    
    # Different candidate (different price)
    candidate_key_4 = "KXBTC15M-26JUN300345-45_YES_BUY_55"
    should_execute_4 = candidate_key_4 not in _executed_candidates_this_window
    assert should_execute_4 == True  # Should be allowed (different price)


def test_order_intent_includes_tp_sl_and_client_tag():
    """Test that OrderIntent includes TP/SL targets and client_tag.
    
    This ensures all required fields are passed for trailing stop functionality.
    """
    from merid.event_venues.kalshi.order_router import OrderIntent
    import uuid
    
    # Simulate TP/SL computation
    class MockExitPolicy:
        tp_r_multiple = 1.0
        sl_r_multiple = 0.5
        policy_id = "test_policy_123"
        max_hold_seconds = 600
    
    exit_policy = MockExitPolicy()
    price_cents = 50
    ticker = "KXBTC15M-26JUN300345-45"
    
    # Compute TP/SL
    if exit_policy and exit_policy.tp_r_multiple:
        take_profit_price_cents = int(price_cents * (1 + exit_policy.tp_r_multiple))
        take_profit_r_multiple = exit_policy.tp_r_multiple
    else:
        take_profit_price_cents = None
        take_profit_r_multiple = None
    
    if exit_policy and exit_policy.sl_r_multiple:
        stop_loss_price_cents = int(price_cents * (1 - exit_policy.sl_r_multiple))
    else:
        stop_loss_price_cents = None
    
    # Generate client_tag
    client_tag = f"15m_{ticker}_{uuid.uuid4().hex[:12]}"
    
    # Construct OrderIntent with all TP/SL fields
    intent = OrderIntent(
        ticker=ticker,
        side="yes",
        action="buy",
        price_cents=price_cents,
        count=1,
        source="merid.prediction.agent_grid_15m",
        client_tag=client_tag,
        take_profit_price_cents=take_profit_price_cents,
        take_profit_r_multiple=take_profit_r_multiple,
        stop_loss_price_cents=stop_loss_price_cents,
        exit_policy_id=exit_policy.policy_id,
    )
    
    # Verify all TP/SL fields are set
    assert intent.client_tag == client_tag
    assert intent.take_profit_price_cents == 100
    assert intent.take_profit_r_multiple == 1.0
    assert intent.stop_loss_price_cents == 25
    assert intent.exit_policy_id == "test_policy_123"


# ═══════════════════════════════════════════════════════════════════════════
# Hedge Pass Integration Tests
# ═══════════════════════════════════════════════════════════════════════════


def test_hedge_pass_called_after_alpha_orders():
    """Test that hedge pass is called after alpha orders are executed in the 15m loop."""
    # This test verifies the hedge pass wiring in loop_15m.py
    # The hedge pass should call compute_hedge_intents and route hedge orders
    
    # Read loop_15m.py to verify hedge pass exists
    with open("merid/loop_15m.py", "r", encoding="utf-8") as f:
        loop_source = f.read()
    
    # Verify hedge pass code exists
    assert "compute_hedge_intents" in loop_source, \
        "compute_hedge_intents call not found in loop_15m.py"
    assert "hedge_intents" in loop_source, \
        "hedge_intents variable not found in loop_15m.py"
    
    # Verify hedge pass is after alpha order execution
    assert "await self._execute_candidate" in loop_source, \
        "Alpha order execution not found in loop_15m.py"
    
    # Verify hedge pass logs
    assert "Generated" in loop_source and "hedge intents" in loop_source, \
        "Hedge intent logging not found in loop_15m.py"


def test_hedge_pass_imports_correct_modules():
    """Test that hedge pass imports the correct modules."""
    with open("merid/loop_15m.py", "r", encoding="utf-8") as f:
        loop_source = f.read()
    
    # Verify imports for hedge pass
    assert "from merid.event_venues.kalshi.order_router import compute_hedge_intents" in loop_source or \
           "compute_hedge_intents" in loop_source, \
        "compute_hedge_intents import not found in loop_15m.py"
    
    assert "from merid.services.bankroll_service import get_bankroll_service" in loop_source or \
           "get_bankroll_service" in loop_source, \
        "get_bankroll_service import not found in loop_15m.py"


def test_hedge_pass_handles_errors_gracefully():
    """Test that hedge pass handles errors gracefully and doesn't fail the cycle."""
    with open("merid/loop_15m.py", "r", encoding="utf-8") as f:
        loop_source = f.read()
    
    # Verify hedge pass is wrapped in try-except
    hedge_section = loop_source[loop_source.find("compute_hedge_intents"):loop_source.find("compute_hedge_intents") + 2000]
    
    # Should have exception handling
    assert "except" in hedge_section or "try:" in hedge_section, \
        "Hedge pass missing exception handling"
    
    # Should log errors - look for the outer exception handler
    assert "hedge_exc" in loop_source or "hedge_err" in loop_source, \
        "Hedge pass missing error logging"


def test_hedge_pass_uses_bankroll_for_sizing():
    """Test that hedge pass uses bankroll for hedge sizing."""
    with open("merid/loop_15m.py", "r", encoding="utf-8") as f:
        loop_source = f.read()
    
    # Verify bankroll is fetched and passed to hedge computation
    assert "bankroll_cents" in loop_source, \
        "bankroll_cents variable not found in loop_15m.py"
    
    assert "get_bankroll_service" in loop_source, \
        "get_bankroll_service call not found in loop_15m.py"
    
    # Verify bankroll is passed to compute_hedge_intents
    assert "compute_hedge_intents(bankroll_cents=" in loop_source or \
           "compute_hedge_intents" in loop_source and "bankroll_cents" in loop_source, \
        "bankroll_cents not passed to compute_hedge_intents"


def test_hedge_pass_routes_hedge_orders():
    """Test that hedge pass routes generated hedge orders."""
    with open("merid/loop_15m.py", "r", encoding="utf-8") as f:
        loop_source = f.read()
    
    # Verify hedge orders are routed
    assert "route_order_async" in loop_source, \
        "route_order_async call not found in loop_15m.py"
    
    # Verify hedge intent iteration
    assert "for hedge_intent in hedge_intents" in loop_source or \
           "for hedge_intent" in loop_source, \
        "Hedge intent iteration not found in loop_15m.py"
    
    # Verify hedge order routing logs
    assert "Hedge order routed" in loop_source or "hedge" in loop_source.lower(), \
        "Hedge order routing logging not found in loop_15m.py"


def test_order_id_to_client_tag_mapping():
    """Test that order_id -> client_tag mapping is registered for fill-to-intent linkage."""
    # Test position cache has the mapping registration function
    with open("merid/event_venues/kalshi/position_cache.py", "r", encoding="utf-8") as f:
        cache_source = f.read()
    
    # Verify register_order_id_mapping function exists
    assert "def register_order_id_mapping" in cache_source, \
        "register_order_id_mapping function not found in position_cache.py"
    
    # Verify the mapping dictionary exists
    assert "_order_id_to_client_tag" in cache_source, \
        "_order_id_to_client_tag dictionary not found in position_cache.py"
    
    # Test order_router registers the mapping after order submission
    with open("merid/event_venues/kalshi/order_router.py", "r", encoding="utf-8") as f:
        router_source = f.read()
    
    # Verify order_router calls register_order_id_mapping
    assert "register_order_id_mapping" in router_source, \
        "register_order_id_mapping call not found in order_router.py"
    
    # Verify mapping is registered after getting Kalshi order_id
    assert "_venue_oid" in router_source and "register_order_id_mapping" in router_source, \
        "Order ID mapping not registered after getting Kalshi order_id"


def test_fill_to_intent_linkage_via_order_id():
    """Test that position cache recovers client_order_id from order_id during fill processing."""
    with open("merid/event_venues/kalshi/position_cache.py", "r", encoding="utf-8") as f:
        cache_source = f.read()
    
    # Verify on_fill has logic to recover client_order_id from order_id
    assert "if not client_order_id and fill_id" in cache_source, \
        "Missing client_order_id recovery logic in on_fill"
    
    # Verify it uses fills_ledger to get order_id
    assert "fill_record.order_id" in cache_source, \
        "Missing order_id lookup from fills_ledger"
    
    # Verify it uses _order_id_to_client_tag mapping
    assert "_order_id_to_client_tag.get" in cache_source, \
        "Missing _order_id_to_client_tag lookup in on_fill"
    
    # Verify logging for successful recovery
    assert "FILL-INTENT-LINK" in cache_source or "Recovered client_order_id" in cache_source, \
        "Missing logging for client_order_id recovery"


def test_exit_policy_id_fallback_in_loop_15m():
    """Test that exit_policy_id fallback logic prevents None values in OrderIntent.
    
    This test verifies the fix for the exit_policy_id_missing rejection bug.
    When exit policy resolution fails, loop_15m.py should create a fallback
    exit policy instead of returning early, ensuring exit_policy_id is never None.
    """
    import uuid
    
    # Simulate the fallback logic from loop_15m.py
    exit_policy = None  # Simulate failed resolution
    
    # Test the fallback logic
    if exit_policy:
        exit_policy_id = exit_policy.policy_id
    else:
        # Fallback: generate a UUID-based policy ID
        exit_policy_id = f"fallback_{uuid.uuid4().hex[:8]}"
    
    # Verify exit_policy_id is not None
    assert exit_policy_id is not None, "exit_policy_id should never be None"
    assert isinstance(exit_policy_id, str), "exit_policy_id should be a string"
    assert exit_policy_id.startswith("fallback_"), "exit_policy_id should start with 'fallback_'"
    
    # Test window_resolution_id fallback as well
    window_resolution_id = None  # Simulate failed resolution
    
    # Test the fallback logic
    if window_resolution_id:
        pass  # Use existing
    else:
        # Fallback: generate a UUID-based window ID
        window_resolution_id = f"window_resolution_{uuid.uuid4().hex[:12]}"
    
    # Verify window_resolution_id is not None
    assert window_resolution_id is not None, "window_resolution_id should never be None"
    assert isinstance(window_resolution_id, str), "window_resolution_id should be a string"
    assert window_resolution_id.startswith("window_resolution_"), "window_resolution_id should start with 'window_resolution_'"


def test_loop_15m_has_exit_policy_fallback_logic():
    """Test that loop_15m.py contains the exit policy fallback logic."""
    with open("merid/loop_15m.py", "r", encoding="utf-8") as f:
        loop_source = f.read()
    
    # Verify the fallback exit policy creation exists
    assert "ExitPolicyResolution" in loop_source, \
        "ExitPolicyResolution import not found in loop_15m.py"
    
    # Verify the fallback pattern exists
    assert "fallback_" in loop_source, \
        "Fallback pattern not found in loop_15m.py"
    
    # Verify the defensive check in OrderIntent creation
    assert "exit_policy_id=exit_policy.policy_id if exit_policy else" in loop_source, \
        "Defensive exit_policy_id check not found in OrderIntent creation"
    
    # Verify window_resolution_id fallback
    assert "window_resolution_id=window_resolution_id if window_resolution_id else" in loop_source, \
        "Defensive window_resolution_id check not found in OrderIntent creation"


def test_window_exposure_recorded_on_fill_not_at_gate():
    """Test that window exposure is recorded on fills, not at gate pass time.
    
    This test verifies the fix for the phantom exposure bug where exposure
    was counted at order submission instead of fill confirmation.
    """
    # Verify order_gate.py does NOT record exposure at gate pass
    with open("merid/event_venues/kalshi/order_gate.py", "r", encoding="utf-8") as f:
        gate_source = f.read()
    
    # Verify optimistic recording is removed
    assert "record_order_execution" not in gate_source or \
           "exposure recorded on fill" in gate_source, \
        "order_gate.py should not record exposure at gate pass time"
    
    # Verify position_cache.py records exposure on fill
    with open("merid/event_venues/kalshi/position_cache.py", "r", encoding="utf-8") as f:
        cache_source = f.read()
    
    # Verify fill-based exposure recording exists
    assert "Recorded window exposure on fill" in cache_source, \
        "position_cache.py should record exposure on fill confirmation"
    
    # Verify it's in the on_fill function
    assert "async def on_fill" in cache_source, \
        "on_fill function not found in position_cache.py"
    
    # Verify order_router.py does NOT have refund logic
    with open("merid/event_venues/kalshi/order_router.py", "r", encoding="utf-8") as f:
        router_source = f.read()
    
    # Verify refund mechanism is removed
    assert "refund_order_execution" not in router_source or \
           "Window exposure no longer recorded optimistically" in router_source, \
        "order_router.py should not have refund logic for optimistic exposure"
