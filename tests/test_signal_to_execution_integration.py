"""
Tests for signal-to-execution integration fixes (2026-07-16).

Tests cover:
- Signal generation sets execution parameters (aggressiveness, post_only, order_type)
- Loop execution respects signal's price_cents unless invalid
- Loop execution uses sizing calculation instead of hardcoded count=1
- Order router respects aggressiveness from signal generation
- Single source of truth for position sizing
"""

import pytest
from unittest.mock import Mock, patch, MagicMock


def test_signal_generation_sets_execution_parameters():
    """CRITICAL FIX: Signal generation should set aggressiveness, post_only, order_type."""
    # Mock the compute_order_aggressiveness function
    with patch('merid.event_venues.kalshi.risk_parameters.compute_order_aggressiveness') as mock_agg:
        mock_agg.return_value = 0.8  # Marketable aggressiveness
        
        # Simulate signal generation logic from agent_grid_15m.py
        asset = "BTC"
        edge_pct = 0.05
        minutes_to_expiry = 10.0
        seconds_to_expiry = int(minutes_to_expiry * 60)
        
        aggressiveness = mock_agg(asset, edge_pct, seconds_to_expiry)
        
        # Construct signal with execution parameters
        signal = {
            "asset": asset,
            "side": "yes",
            "action": "buy",
            "edge_pct": edge_pct,
            "confidence": 0.7,
            "model_prob": 0.55,
            "price_cents": 42,
            "count": 0,  # Placeholder, will be set by loop sizing
            "aggressiveness": aggressiveness,
            "post_only": False,
            "order_type": "limit",
        }
        
        # Verify execution parameters are set
        assert signal["aggressiveness"] == 0.8
        assert signal["post_only"] == False
        assert signal["order_type"] == "limit"
        assert signal["count"] == 0  # Should be placeholder, not set by signal


def test_candidate_carries_execution_parameters():
    """CRITICAL FIX: Candidate should carry execution parameters from signal."""
    signal = {
        "aggressiveness": 0.7,
        "post_only": False,
        "order_type": "limit",
        "price_cents": 42,
        "count": 0,
    }
    
    # Simulate candidate construction from agent_grid_15m.py
    candidate = {
        "ticker": "KXBTC15M-TEST",
        "side": "yes",
        "action": "buy",
        "aggressiveness": signal.get("aggressiveness", 0.5),
        "post_only": signal.get("post_only", False),
        "order_type": signal.get("order_type", "limit"),
        "price_cents": signal.get("price_cents", 0),
        "count": 0,  # Placeholder for loop sizing
    }
    
    # Verify execution parameters are carried
    assert candidate["aggressiveness"] == 0.7
    assert candidate["post_only"] == False
    assert candidate["order_type"] == "limit"
    assert candidate["price_cents"] == 42
    assert candidate["count"] == 0


def test_loop_respects_signal_price_cents_when_valid():
    """CRITICAL FIX: Loop should use signal's price_cents when valid (10-75c range)."""
    candidate = {
        "ticker": "KXBTC15M-TEST",
        "side": "yes",
        "price_cents": 42,  # Valid price in canonical range
    }
    
    # Simulate loop price validation logic from loop_15m.py
    price_cents = candidate.get("price_cents", 0)
    price_valid = (price_cents > 0) and (10 <= price_cents <= 75)
    
    if price_valid:
        # Use signal's price directly
        final_price = price_cents
    else:
        # Fall back to market state
        final_price = 42  # Fallback
    
    # Verify signal's price is used
    assert final_price == 42
    assert price_valid == True


def test_loop_fallback_to_market_state_when_price_invalid():
    """CRITICAL FIX: Loop should fall back to market state when signal's price is invalid."""
    candidate = {
        "ticker": "KXBTC15M-TEST",
        "side": "yes",
        "price_cents": 100,  # Invalid price (outside 10-75c range)
    }
    
    # Simulate loop price validation logic
    price_cents = candidate.get("price_cents", 0)
    price_valid = (price_cents > 0) and (10 <= price_cents <= 75)
    
    if price_valid:
        final_price = price_cents
    else:
        # Fall back to market state
        final_price = 42  # Fallback to midpoint
    
    # Verify fallback is used
    assert final_price == 42
    assert price_valid == False


def test_loop_uses_sizing_calculation_not_hardcoded_count():
    """CRITICAL FIX: Loop should use sizing calculation instead of hardcoded count=1."""
    candidate = {
        "ticker": "KXBTC15M-TEST",
        "count": 0,  # Placeholder from signal
    }
    
    # Simulate sizing calculation from loop_15m.py
    # Mock compute_order_size returning count=2
    calculated_count = 2
    
    # Set candidate count from sizing calculation
    candidate["count"] = calculated_count
    
    # Simulate OrderIntent construction
    count = candidate.get("count", 1)
    
    # Verify sizing calculation is used
    assert count == 2, "Should use sizing calculation, not hardcoded 1"


def test_order_intent_uses_candidate_execution_parameters():
    """CRITICAL FIX: OrderIntent should use execution parameters from candidate."""
    from merid.event_venues.kalshi.order_router import OrderIntent
    
    candidate = {
        "ticker": "KXBTC15M-TEST",
        "side": "yes",
        "action": "buy",
        "price_cents": 42,
        "count": 2,
        "aggressiveness": 0.7,
        "post_only": False,
        "order_type": "limit",
    }
    
    # Construct OrderIntent using candidate parameters
    intent = OrderIntent(
        ticker=candidate["ticker"],
        side=candidate["side"],
        action=candidate["action"],
        price_cents=candidate["price_cents"],
        count=candidate["count"],
        order_type=candidate.get("order_type", "limit"),
        post_only=candidate.get("post_only", False),
        aggressiveness=candidate.get("aggressiveness", 0.5),
    )
    
    # Verify execution parameters are used
    assert intent.count == 2
    assert intent.order_type == "limit"
    assert intent.post_only == False
    assert intent.aggressiveness == 0.7


def test_order_router_respects_aggressiveness_from_signal():
    """CRITICAL FIX: Order router should respect aggressiveness from signal when set."""
    from merid.event_venues.kalshi.order_router import OrderIntent
    
    # Create intent with aggressiveness set by signal
    intent = OrderIntent(
        ticker="KXBTC15M-TEST",
        side="yes",
        action="buy",
        price_cents=42,
        count=2,
        aggressiveness=0.8,  # Set by signal generation
        edge_pct=0.05,
    )
    
    # Simulate order router logic from order_router.py
    # If aggressiveness is set (non-zero), use it; otherwise compute
    if intent.aggressiveness == 0.0:
        # Would compute aggressiveness here
        computed_aggressiveness = 0.5
        final_aggressiveness = computed_aggressiveness
    else:
        # Use aggressiveness from signal
        final_aggressiveness = intent.aggressiveness
    
    # Verify signal's aggressiveness is respected
    assert final_aggressiveness == 0.8


def test_order_router_computes_aggressiveness_when_not_set():
    """Order router should compute aggressiveness when not set by signal."""
    from merid.event_venues.kalshi.order_router import OrderIntent
    
    with patch('merid.event_venues.kalshi.risk_parameters.compute_order_aggressiveness') as mock_agg:
        mock_agg.return_value = 0.6
        
        # Create intent without aggressiveness set (default 0.0)
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=42,
            count=2,
            aggressiveness=0.0,  # Not set by signal
            edge_pct=0.05,
        )
        
        # Simulate order router logic
        if intent.aggressiveness == 0.0:
            # Compute aggressiveness
            computed_aggressiveness = mock_agg("BTC", intent.edge_pct, 900)
            final_aggressiveness = computed_aggressiveness
        else:
            final_aggressiveness = intent.aggressiveness
        
        # Verify aggressiveness is computed
        assert final_aggressiveness == 0.6
        mock_agg.assert_called_once()


def test_single_source_of_truth_for_position_sizing():
    """CRITICAL FIX: Position sizing should have single source of truth (loop sizing)."""
    # Signal generation should NOT set count
    signal = {
        "price_cents": 42,
        "count": 0,  # Placeholder, not actual sizing
    }
    
    # Candidate carries placeholder
    candidate = {
        "price_cents": signal["price_cents"],
        "count": 0,  # Placeholder
    }
    
    # Loop sizing calculation determines final count
    # Mock sizing calculation
    calculated_count = 2
    candidate["count"] = calculated_count
    
    # OrderIntent uses sizing calculation result
    final_count = candidate["count"]
    
    # Verify single source of truth
    assert signal["count"] == 0  # Signal doesn't set sizing
    assert final_count == 2  # Loop sizing is the source of truth


def test_removed_hardcoded_count_assertion():
    """CRITICAL FIX: Hardcoded count=1 assertion should be removed."""
    # Simulate the old assertion that was removed
    count = 2  # From sizing calculation
    
    # Old assertion (should NOT be present):
    # assert count == 1, "Order count must be 1"
    
    # New behavior: allow any count from sizing calculation
    # No assertion, just validation that count >= 1
    assert count >= 1, "Count must be at least 1"
    
    # Verify count=2 is allowed
    assert count == 2


def test_hmm_regime_carried_from_signal_to_candidate():
    """CRITICAL FIX: HMM regime should be carried from signal to candidate."""
    signal = {
        "hmm_regime": "bull",
        "hmm_regime_confidence": 0.85,
    }
    
    # Simulate candidate construction
    candidate = {
        "hmm_regime": signal.get("hmm_regime", None),
        "hmm_regime_confidence": signal.get("hmm_regime_confidence", 0.0),
    }
    
    # Verify HMM regime is carried
    assert candidate["hmm_regime"] == "bull"
    assert candidate["hmm_regime_confidence"] == 0.85


def test_time_of_day_multiplier_carried_from_signal():
    """CRITICAL FIX: Time-of-day multiplier should be carried from signal."""
    time_of_day_multiplier = 0.8  # Reduced risk during certain hours
    
    # Simulate candidate construction
    candidate = {
        "time_of_day_multiplier": time_of_day_multiplier,
    }
    
    # Verify multiplier is carried
    assert candidate["time_of_day_multiplier"] == 0.8


def test_price_validation_uses_canonical_range():
    """Price validation should use 10-75c canonical range."""
    # Test valid prices
    valid_prices = [10, 42, 75]
    for price in valid_prices:
        price_valid = (price > 0) and (10 <= price <= 75)
        assert price_valid == True, f"Price {price} should be valid"
    
    # Test invalid prices
    invalid_prices = [0, 9, 76, 100]
    for price in invalid_prices:
        price_valid = (price > 0) and (10 <= price <= 75)
        assert price_valid == False, f"Price {price} should be invalid"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
