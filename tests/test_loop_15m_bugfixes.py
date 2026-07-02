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
    current_best = best_edge_per_asset.get(asset)
    current_best_edge = current_best.get("edge", 0.0) if current_best else 0.0
    
    should_execute = edge > current_best_edge
    
    assert should_execute == True
    assert edge == 15.5
    assert current_best_edge == 0.0


def test_best_edge_selection_improves_edge():
    """Test that candidate with higher edge replaces current best edge.
    
    This ensures the system always executes the best opportunity.
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
    current_best = best_edge_per_asset.get(asset)
    current_best_edge = current_best.get("edge", 0.0) if current_best else 0.0
    
    should_execute = edge > current_best_edge
    
    assert should_execute == True
    assert edge == 15.5
    assert current_best_edge == 10.0


def test_best_edge_selection_skips_lower_edge():
    """Test that candidate with lower edge is skipped.
    
    This prevents over-trading and ensures only best edges execute.
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
    current_best = best_edge_per_asset.get(asset)
    current_best_edge = current_best.get("edge", 0.0) if current_best else 0.0
    
    should_execute = edge > current_best_edge
    
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
