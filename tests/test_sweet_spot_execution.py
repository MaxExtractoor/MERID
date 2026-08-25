"""Test sweet spot order execution logic in order_router.

SWEET-SPOT-EXECUTION is now bypassed for BUY NO / BUY YES to avoid blind
repricing (e.g. 40c/48c -> 55c) that was crossing the spread and causing
rejections. SELL orders may still use the block. These tests reflect the
new bypass behavior.
"""

import pytest
from unittest.mock import MagicMock, patch


def test_sweet_spot_bypassed_for_buy_yes():
    """Test that BUY YES bypasses the sweet spot block (returns limit)."""
    # Mock the state with price in optimal range
    mock_state = MagicMock()
    mock_state.mid_cents = 50  # In optimal range
    
    # Create a mock intent
    from merid.event_venues.kalshi.order_router import OrderIntent
    intent = OrderIntent(
        ticker="KXBTC15M-TEST",
        side="yes",
        action="buy",
        price_cents=50,
        count=10,
    )
    intent.order_type = "limit"
    
    # Import the function
    from merid.event_venues.kalshi.order_router import _determine_dynamic_order_type
    
    # Call the function
    order_type, tif = _determine_dynamic_order_type(intent, mock_state)
    
    # BUY orders now bypass SWEET-SPOT-EXECUTION and keep limit/gtc
    assert order_type == "limit", \
        f"BUY YES should bypass sweet spot and return limit, got {order_type}"
    assert tif == "gtc", f"Expected gtc, got {tif}"
    assert intent.price_cents == 50, f"BUY price should not be adjusted, got {intent.price_cents}c"


def test_sweet_spot_buy_bypassed_below_optimal():
    """Test that BUY orders below the optimal range are not repriced."""
    # Mock the state with price below optimal range
    mock_state = MagicMock()
    mock_state.mid_cents = 35  # Below optimal range
    
    # Create a mock intent
    from merid.event_venues.kalshi.order_router import OrderIntent
    intent = OrderIntent(
        ticker="KXBTC15M-TEST",
        side="buy",
        action="buy",
        price_cents=35,
        count=10,
    )
    intent.order_type = "limit"
    
    # Import the function
    from merid.event_venues.kalshi.order_router import _determine_dynamic_order_type
    
    # Call the function
    order_type, tif = _determine_dynamic_order_type(intent, mock_state)
    
    # BUY orders bypass SWEET-SPOT-EXECUTION and keep the original price
    assert order_type == "limit", \
        f"BUY should bypass sweet spot and return limit, got {order_type}"
    assert intent.price_cents == 35, \
        f"BUY price should not be adjusted by sweet spot, got {intent.price_cents}c"


def test_sweet_spot_constants():
    """Test that side-aware sweet spot constants are defined correctly."""
    with open('merid/event_venues/kalshi/order_router.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify side-aware optimal entry range constants (YES-space and NO-space)
    assert 'OPTIMAL_ENTRY_MIN_YES = 40' in content, \
        "OPTIMAL_ENTRY_MIN_YES should be 40"
    assert 'OPTIMAL_ENTRY_MAX_YES = 55' in content, \
        "OPTIMAL_ENTRY_MAX_YES should be 55"
    
    # Verify side-aware sweet spot constants
    assert 'SWEET_SPOT_MIN_YES = 40' in content, \
        "SWEET_SPOT_MIN_YES should be 40"
    assert 'SWEET_SPOT_MAX_YES = 45' in content, \
        "SWEET_SPOT_MAX_YES should be 45"


def test_sweet_spot_research_comment():
    """Test that sweet spot logic references Turbine research."""
    with open('merid/event_venues/kalshi/order_router.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify the comment mentions Turbine research
    assert 'Turbine' in content or 'RESEARCH-BASED' in content, \
        "Should reference Turbine research in comments"
    
    # Verify the comment mentions optimal entry range
    assert 'optimal entry range' in content or '40-55c' in content, \
        "Should mention optimal entry range in comments"


def test_sweet_spot_no_state():
    """Test that sweet spot logic defaults to limit when no state available."""
    # Create a mock intent
    from merid.event_venues.kalshi.order_router import OrderIntent
    intent = OrderIntent(
        ticker="KXBTC15M-TEST",
        side="yes",
        action="buy",
        price_cents=50,
        count=10,
    )
    intent.order_type = "limit"
    
    # Import the function
    from merid.event_venues.kalshi.order_router import _determine_dynamic_order_type
    
    # Call with no state
    order_type, tif = _determine_dynamic_order_type(intent, None)
    
    # Should default to limit with GTC
    assert order_type == "limit", \
        f"Should default to limit when no state, got {order_type}"
    assert tif == "gtc", \
        f"Should use GTC TIF when no state, got {tif}"


def test_sweet_spot_market_order_preserved():
    """Test that existing market orders are preserved."""
    # Mock the state
    mock_state = MagicMock()
    mock_state.mid_cents = 50
    
    # Create a mock intent with market order type
    from merid.event_venues.kalshi.order_router import OrderIntent
    intent = OrderIntent(
        ticker="KXBTC15M-TEST",
        side="yes",
        action="buy",
        price_cents=50,
        count=10,
    )
    intent.order_type = "market"  # Already market
    
    # Import the function
    from merid.event_venues.kalshi.order_router import _determine_dynamic_order_type
    
    # Call the function
    order_type, tif = _determine_dynamic_order_type(intent, mock_state)
    
    # Should preserve market order
    assert order_type == "market", \
        f"Should preserve existing market order, got {order_type}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
