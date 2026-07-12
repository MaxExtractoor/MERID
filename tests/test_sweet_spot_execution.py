"""Test sweet spot order execution logic in order_router.

Tests verify:
- Market orders are used when price is in optimal range (40-55c)
- Limit orders are placed at sweet spot (40-45c) when price is below optimal
- Sweet spot logic is based on 2026 Turbine research
"""

import pytest
from unittest.mock import MagicMock, patch


def test_sweet_spot_market_order_in_optimal_range():
    """Test that market orders are used when price is in 40-55c range."""
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
    intent.order_type = "limit"  # Will be overridden by sweet spot logic
    
    # Import the function
    from merid.event_venues.kalshi.order_router import _determine_dynamic_order_type
    
    # Call the function
    order_type, tif = _determine_dynamic_order_type(intent, mock_state)
    
    # Should return market order
    assert order_type == "market", \
        f"Should use market order in optimal range, got {order_type}"


def test_sweet_spot_limit_order_below_optimal():
    """Test that limit orders are placed at sweet spot when price is below 40c."""
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
    
    # Should return limit order
    assert order_type == "limit", \
        f"Should use limit order below optimal range, got {order_type}"
    
    # Price should be adjusted to sweet spot (40-45c)
    assert 40 <= intent.price_cents <= 45, \
        f"Price should be adjusted to sweet spot (40-45c), got {intent.price_cents}c"


def test_sweet_spot_constants():
    """Test that sweet spot constants are defined correctly."""
    with open('merid/event_venues/kalshi/order_router.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify optimal entry range constants
    assert 'OPTIMAL_ENTRY_MIN = 40' in content, \
        "OPTIMAL_ENTRY_MIN should be 40"
    assert 'OPTIMAL_ENTRY_MAX = 55' in content, \
        "OPTIMAL_ENTRY_MAX should be 55"
    
    # Verify sweet spot constants
    assert 'SWEET_SPOT_MIN = 40' in content, \
        "SWEET_SPOT_MIN should be 40"
    assert 'SWEET_SPOT_MAX = 45' in content, \
        "SWEET_SPOT_MAX should be 45"


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
