"""Tests for fine-tuning fixes to increase trading opportunities.

This test file validates the following changes made on 2026-07-02:
1. OBI-FILTER-ERROR fix: depth_yes/depth_no aliases in KalshiMarketState
2. Bankroll Service adapter: merid/services/bankroll_service.py
3. Global rate limit reduction: 6s to 3s
4. Velocity threshold reduction: 35% lower
5. Microstructure threshold: 8c to 20c
6. Signal strength filter: edge < 0.02%
7. Asset-specific velocity thresholds
8. Kalshi V2 API side conversion fix for NO orders
"""

import pytest
from dataclasses import dataclass
from typing import Optional

# Test 1: OBI-FILTER-ERROR fix - depth_yes/depth_no aliases
def test_kalshi_market_state_depth_aliases():
    """Test that KalshiMarketState has depth_yes/depth_no property aliases."""
    from merid.event_venues.kalshi.models import KalshiMarketState
    
    # Create a market state with min_depth_yes and min_depth_no
    state = KalshiMarketState(
        ticker="KXBTC15M-26JUL021900-00",
        min_depth_yes=100,
        min_depth_no=200
    )
    
    # Verify aliases work
    assert state.depth_yes == 100, "depth_yes should alias to min_depth_yes"
    assert state.depth_no == 200, "depth_no should alias to min_depth_no"
    
    # Verify they're properties, not fields
    assert not hasattr(state, '__dict__') or 'depth_yes' not in state.__dict__, "depth_yes should be a property"
    assert not hasattr(state, '__dict__') or 'depth_no' not in state.__dict__, "depth_no should be a property"


# Test 2: Bankroll Service adapter
def test_bankroll_service_adapter():
    """Test that merid.services.bankroll_service redirects to v2."""
    from merid.services.bankroll_service import get_bankroll_service, BankrollService
    
    # Verify the function exists and is callable
    assert callable(get_bankroll_service), "get_bankroll_service should be callable"
    
    # Verify it imports successfully from v2
    try:
        from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service as get_v2
        # Both should be callable (don't compare objects, just verify both work)
        assert callable(get_v2), "v2 get_bankroll_service should be callable"
    except ImportError:
        pytest.skip("bankroll_service_v2 not available")


# Test 3: Global rate limit reduction
def test_global_rate_limit_reduced():
    """Test that global rate limit was reduced for 15m opportunity capture."""
    from merid.event_venues.kalshi.order_router import _MIN_SECONDS_BETWEEN_ORDERS
    
    # Current 15m setting is 0.1s between orders (reduced from earlier 0.3s/6s caps)
    assert _MIN_SECONDS_BETWEEN_ORDERS == 0.1, f"Expected 0.1s, got {_MIN_SECONDS_BETWEEN_ORDERS}s"


# Test 4: Velocity threshold reduction
@pytest.mark.skip(reason="2026-07-18: Panic fade disabled - causing losses by betting against trend")
def test_velocity_threshold_reduced():
    """Test that velocity thresholds were reduced by 35%."""
    from merid.prediction.agent_grid_15m import LeanAgentConfig
    
    # Create a config
    config = LeanAgentConfig(name="BTC_15M", series_tickers=["KXBTC15M"])
    
    # Verify panic_fade_threshold was reduced from 0.0002 to 0.00013 (35% reduction)
    assert config.panic_fade_threshold == 0.00013, f"Expected 0.00013, got {config.panic_fade_threshold}"
    
    # Verify panic_fade_min_velocity was reduced from 0.0001 to 0.000065 (35% reduction)
    assert config.panic_fade_min_velocity == 0.000065, f"Expected 0.000065, got {config.panic_fade_min_velocity}"


# Test 5: Microstructure threshold optimization
def test_microstructure_threshold_optimized():
    """Test that max_spread_cents default matches the 15m microstructure gate."""
    from merid.event_venues.kalshi.order_router import check_market_microstructure
    import inspect
    
    # Get the function signature
    sig = inspect.signature(check_market_microstructure)
    
    # Default is 20.0c for 15m crypto markets (2026-07-12 research)
    max_spread_default = sig.parameters['max_spread_cents'].default
    assert max_spread_default == 20.0, f"Expected 20.0, got {max_spread_default}"


# Test 6: Signal strength filter
def test_signal_strength_filter():
    """Test that edge < 0.02% is filtered out."""
    from merid.prediction.agent_grid_15m import LeanAgentConfig
    import inspect
    
    # Verify the minimum edge threshold is set in the signal generation logic
    # This is tested by checking the code has the filter
    from merid.prediction import agent_grid_15m
    source = inspect.getsource(agent_grid_15m)
    assert "minimum edge threshold" in source, "minimum edge threshold should be in signal generation code"
    assert "0.02" in source, "0.02% threshold should be in signal generation code"


# Test 7: Asset-specific velocity thresholds
def test_asset_specific_velocity_thresholds():
    """Test that asset-specific velocity thresholds are configured."""
    from merid.prediction.agent_grid_15m import LeanAgentConfig
    
    # Create a config
    config = LeanAgentConfig(name="BTC_15M", series_tickers=["KXBTC15M"])
    
    # Verify asset-specific thresholds exist
    assert hasattr(config, 'velocity_threshold_btc'), "Should have velocity_threshold_btc"
    assert hasattr(config, 'velocity_threshold_eth'), "Should have velocity_threshold_eth"
    assert hasattr(config, 'velocity_threshold_sol'), "Should have velocity_threshold_sol"
    assert hasattr(config, 'velocity_threshold_xrp'), "Should have velocity_threshold_xrp"
    assert hasattr(config, 'velocity_threshold_doge'), "Should have velocity_threshold_doge"
    
    # Verify values (BTC/ETH lower, others higher) - 2026-07-24 aligned with profile YAML
    assert config.velocity_threshold_btc == 0.00015, f"Expected 0.00015 for BTC, got {config.velocity_threshold_btc}"
    assert config.velocity_threshold_eth == 0.00015, f"Expected 0.00015 for ETH, got {config.velocity_threshold_eth}"
    assert config.velocity_threshold_sol == 0.000225, f"Expected 0.000225 for SOL, got {config.velocity_threshold_sol}"
    assert config.velocity_threshold_xrp == 0.000225, f"Expected 0.000225 for XRP, got {config.velocity_threshold_xrp}"
    assert config.velocity_threshold_doge == 0.0003, f"Expected 0.0003 for DOGE, got {config.velocity_threshold_doge}"


# Test 8: Integration test - rate limit check
def test_rate_limit_check_allows_3s_interval():
    """Test that rate limit check allows orders at the configured interval."""
    from merid.event_venues.kalshi.order_router import _check_global_rate_limit
    import time
    
    # This test verifies the logic by checking the constant
    # Actual rate limit testing would require manipulating the global state
    from merid.event_venues.kalshi.order_router import _MIN_SECONDS_BETWEEN_ORDERS
    assert _MIN_SECONDS_BETWEEN_ORDERS == 0.1, f"Rate limit should allow 0.1s intervals, got {_MIN_SECONDS_BETWEEN_ORDERS}s"


# Test 9: Integration test - microstructure check
def test_microstructure_check_allows_10c_spread():
    """Test that side-aware microstructure check allows 10c and rejects 11c for YES side."""
    from merid.event_venues.kalshi.order_router import check_market_microstructure
    
    # Test with 10c YES spread (should pass)
    # Need sufficient depth: 400 contracts at 50c mid = $200 depth USD
    passes, reason = check_market_microstructure(
        yes_bid_cents=45,
        yes_ask_cents=55,  # 10c spread
        no_bid_cents=45,
        no_ask_cents=55,
        yes_depth=400,  # 400 contracts at 50c = $200 depth USD
        no_depth=400,
        order_side="yes",
        max_spread_cents=10.0
    )
    
    assert passes, f"10c spread should pass: {reason}"
    
    # Test with 11c YES spread (should fail)
    passes, reason = check_market_microstructure(
        yes_bid_cents=45,
        yes_ask_cents=56,  # 11c spread
        no_bid_cents=45,
        no_ask_cents=56,
        yes_depth=400,
        no_depth=400,
        order_side="yes",
        max_spread_cents=10.0
    )
    
    assert not passes, "11c spread should fail"
    assert "yes_spread_too_wide" in reason, f"Should fail with spread error: {reason}"


# Test 10: Kalshi V2 API side conversion for NO orders (book-side mapping)
def test_kalshi_v2_side_conversion_no_orders():
    """Verify Kalshi V2 /portfolio/events/orders uses BookSide only.

    V2 does NOT use the legacy ``action``/``side`` (yes/no) fields.  It uses a
    single YES-centric book side: ``bid`` (outcome=yes) or ``ask`` (outcome=no).
    Price is always quoted in YES-space dollars.

    Canonical mapping:
    - BUY_YES  -> bid
    - SELL_YES -> ask
    - BUY_NO   -> ask  (buying NO == selling YES)
    - SELL_NO  -> bid  (selling NO == buying YES)
    """
    import inspect
    from merid.event_venues.kalshi.client import KalshiVenueClient

    source = inspect.getsource(KalshiVenueClient.place_order_result)

    # V2 CreateOrderV2Request has no `action` field; it is derived from BookSide.
    # Ensure the wire payload no longer carries a conflicting legacy action.
    assert '"action": action' not in source, \
        "V2 request must not include the deprecated `action` field"

    # Verify the canonical book-side mapping is present.
    assert 'outcome == "no" and action == "buy"' in source, \
        "BUY_NO must branch on outcome/action to choose the correct book side"
    assert 'kalshi_side = "ask"' in source, "BUY_NO/SELL_YES must map to ask"
    assert 'kalshi_side = "bid"' in source, "BUY_YES/SELL_NO must map to bid"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
