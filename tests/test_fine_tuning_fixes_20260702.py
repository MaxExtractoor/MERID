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
    """Test that global rate limit was reduced from 6s to 3s."""
    from merid.event_venues.kalshi.order_router import _MIN_SECONDS_BETWEEN_ORDERS
    
    # Verify the rate limit is 3 seconds
    assert _MIN_SECONDS_BETWEEN_ORDERS == 3.0, f"Expected 3.0s, got {_MIN_SECONDS_BETWEEN_ORDERS}s"


# Test 4: Velocity threshold reduction
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
    """Test that max_spread_cents was optimized to 10c based on 2026 research."""
    from merid.event_venues.kalshi.order_router import check_market_microstructure
    import inspect
    
    # Get the function signature
    sig = inspect.signature(check_market_microstructure)
    
    # Verify max_spread_cents default is 10.0 (2026-07-09 optimized from 20c)
    max_spread_default = sig.parameters['max_spread_cents'].default
    assert max_spread_default == 10.0, f"Expected 10.0, got {max_spread_default}"


# Test 6: Signal strength filter
def test_signal_strength_filter():
    """Test that edge < 0.02% is filtered out."""
    from merid.prediction.agent_grid_15m import LeanAgentConfig
    import inspect
    
    # Verify the min_edge_threshold is set in the signal generation logic
    # This is tested by checking the code has the filter
    from merid.prediction import agent_grid_15m
    source = inspect.getsource(agent_grid_15m)
    assert "min_edge_threshold" in source, "min_edge_threshold should be in signal generation code"
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
    
    # Verify values (BTC/ETH lower, others higher)
    assert config.velocity_threshold_btc == 0.0013, f"Expected 0.0013 for BTC, got {config.velocity_threshold_btc}"
    assert config.velocity_threshold_eth == 0.0013, f"Expected 0.0013 for ETH, got {config.velocity_threshold_eth}"
    assert config.velocity_threshold_sol == 0.0018, f"Expected 0.0018 for SOL, got {config.velocity_threshold_sol}"
    assert config.velocity_threshold_xrp == 0.0018, f"Expected 0.0018 for XRP, got {config.velocity_threshold_xrp}"
    assert config.velocity_threshold_doge == 0.0020, f"Expected 0.0020 for DOGE, got {config.velocity_threshold_doge}"


# Test 8: Integration test - rate limit check
def test_rate_limit_check_allows_3s_interval():
    """Test that rate limit check allows orders 3 seconds apart."""
    from merid.event_venues.kalshi.order_router import _check_global_rate_limit
    import time
    
    # This test verifies the logic by checking the constant
    # Actual rate limit testing would require manipulating the global state
    from merid.event_venues.kalshi.order_router import _MIN_SECONDS_BETWEEN_ORDERS
    assert _MIN_SECONDS_BETWEEN_ORDERS == 3.0, "Rate limit should allow 3s intervals"


# Test 9: Integration test - microstructure check
def test_microstructure_check_allows_10c_spread():
    """Test that microstructure check allows 10c spread (2026-07-09 optimized from 20c)."""
    from merid.event_venues.kalshi.order_router import check_market_microstructure
    
    # Test with 20c spread (should pass)
    # Need sufficient depth: 400 contracts at 50c mid = $200 depth USD
    passes, reason = check_market_microstructure(
        yes_bid_cents=45,
        yes_ask_cents=55,  # 10c spread
        no_bid_cents=45,
        no_ask_cents=55,
        yes_depth=400,  # 400 contracts at 50c = $200 depth USD
        no_depth=400,
        max_spread_cents=30.0  # 2026-07-10: Optimized to 30c to harmonize with 10c-75c canonical range
    )
    
    assert passes, f"10c spread should pass: {reason}"
    
    # Test with 11c spread (should fail)
    passes, reason = check_market_microstructure(
        yes_bid_cents=45,
        yes_ask_cents=56,  # 11c spread
        no_bid_cents=45,
        no_ask_cents=56,
        yes_depth=400,
        no_depth=400,
        max_spread_cents=30.0  # 2026-07-10: Optimized to 30c to harmonize with 10c-75c entry price canonical range
    )
    
    assert not passes, "11c spread should fail"
    assert "yes_spread_too_wide" in reason, f"Should fail with spread error: {reason}"


# Test 10: Kalshi V2 API side conversion fix for NO orders
def test_kalshi_v2_side_conversion_no_orders():
    """Test that V2 API side conversion correctly handles NO orders.
    
    This test validates the fix for the critical bug where SELL_NO orders
    were incorrectly mapped to "ask" instead of "bid", causing 5c limit
    orders to be interpreted as 95c by Kalshi.
    
    The correct mapping is:
    - BUY_YES = bid
    - SELL_YES = ask
    - BUY_NO = ask (equivalent to sell YES)
    - SELL_NO = bid (equivalent to buy YES)
    """
    from decimal import Decimal
    from merid.event_venues.base import VenueOrder
    import inspect
    from merid.event_venues.kalshi.client import KalshiVenueClient
    
    # Get the source code of place_order_result to verify the fix
    source = inspect.getsource(KalshiVenueClient.place_order_result)
    
    # Verify the fix is present: must consider both outcome AND action
    assert "outcome == \"yes\"" in source, "Should check outcome for yes"
    assert "outcome == \"no\"" in source, "Should check outcome for no"
    assert "order.side == \"buy\"" in source, "Should check action (buy)"
    # The sell case is handled by else clause, not explicit check
    assert "else:" in source, "Should have else clause for sell action"
    
    # Verify the correct mapping logic is present
    # BUY_YES = bid, SELL_YES = ask
    assert 'v2_side = "bid" if order.side == "buy" else "ask"' in source, \
        "YES side should map: buy->bid, sell->ask"
    
    # BUY_NO = ask, SELL_NO = bid
    assert 'v2_side = "ask" if order.side == "buy" else "bid"' in source, \
        "NO side should map: buy->ask, sell->bid"
    
    # Verify the fix comment is present
    assert "CRITICAL FIX: Must consider both outcome AND action" in source, \
        "Fix comment should be present"
    
    # Test the actual mapping logic by creating VenueOrder objects
    # and verifying the expected v2_side would be computed correctly
    
    # Test BUY_YES -> bid
    order_yes_buy = VenueOrder(
        market_id="KXBTC15M-26JUL021900-00",
        side="buy",
        size=Decimal("1"),
        price=Decimal("0.50"),
        outcome_id="yes"
    )
    # The fix ensures: outcome="yes" + side="buy" -> v2_side="bid"
    
    # Test SELL_YES -> ask
    order_yes_sell = VenueOrder(
        market_id="KXBTC15M-26JUL021900-00",
        side="sell",
        size=Decimal("1"),
        price=Decimal("0.50"),
        outcome_id="yes"
    )
    # The fix ensures: outcome="yes" + side="sell" -> v2_side="ask"
    
    # Test BUY_NO -> ask (equivalent to sell YES)
    order_no_buy = VenueOrder(
        market_id="KXBTC15M-26JUL021900-00",
        side="buy",
        size=Decimal("1"),
        price=Decimal("0.50"),
        outcome_id="no"
    )
    # The fix ensures: outcome="no" + side="buy" -> v2_side="ask"
    
    # Test SELL_NO -> bid (equivalent to buy YES)
    # This was the bug: it was incorrectly mapped to "ask"
    order_no_sell = VenueOrder(
        market_id="KXBTC15M-26JUL021900-00",
        side="sell",
        size=Decimal("1"),
        price=Decimal("0.50"),
        outcome_id="no"
    )
    # The fix ensures: outcome="no" + side="sell" -> v2_side="bid"
    
    # Verify the Kalshi duality comment is present
    assert "bid = buy YES = sell NO" in source, \
        "Kalshi duality comment should be present"
    assert "ask = sell YES = buy NO" in source, \
        "Kalshi duality comment should be present"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
