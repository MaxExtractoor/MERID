"""
Unit tests for orderbook ladder walking depth-adjusted edge calculation.

Tests the orderbook ladder walking implementation for slippage estimation
and depth-adjusted edge calculation based on SimpleFunctions best practices.
"""

import pytest
from merid.event_venues.kalshi.unified_market_state import OrderbookLevel, OrderbookSnapshot
from merid.event_venues.kalshi.spread_edge_analytics import (
    walk_orderbook_ladder,
    compute_depth_adjusted_edges,
    PerSideEdgeMetrics,
    PerSideSpreadMetrics
)


def test_walk_orderbook_ladder_yes_side():
    """Test orderbook ladder walking for YES side."""
    # Create orderbook with multiple levels
    yes_bids = (
        OrderbookLevel(price_cents=40, size=1000),
        OrderbookLevel(price_cents=39, size=500),
        OrderbookLevel(price_cents=38, size=300),
    )
    no_bids = (
        OrderbookLevel(price_cents=60, size=800),  # YES ask = 100 - 60 = 40
        OrderbookLevel(price_cents=61, size=400),  # YES ask = 100 - 61 = 39
        OrderbookLevel(price_cents=62, size=200),  # YES ask = 100 - 62 = 38
    )
    orderbook = OrderbookSnapshot(
        ticker="KXBTC15M-26JUL211745-45",
        yes_bids=yes_bids,
        no_bids=no_bids
    )
    
    # Walk orderbook for 100 contracts
    avg_fill, slippage, depth = walk_orderbook_ladder(orderbook, "yes", 100, max_price_window_cents=5)
    
    # Should fill at cheapest available price (38c) due to ladder walking
    # Algorithm fills at cheapest price within window for limit orders
    assert avg_fill is not None, f"Should have average fill price"
    assert slippage is not None, f"Should have slippage cost"
    assert depth >= 100, f"Depth should be >= order size"
    assert avg_fill == 38.0, f"Should fill at cheapest available (38c), got {avg_fill}c"
    # Slippage is negative when filling below best ask (favorable)
    assert slippage <= 0.0, f"Slippage should be <= 0 when filling below best ask, got {slippage}c"


def test_walk_orderbook_ladder_yes_side_with_slippage():
    """Test orderbook ladder walking for YES side with slippage."""
    # Create orderbook with limited depth at best price
    yes_bids = (
        OrderbookLevel(price_cents=40, size=50),  # Limited depth at best bid
        OrderbookLevel(price_cents=39, size=500),
    )
    no_bids = (
        OrderbookLevel(price_cents=60, size=50),  # Limited depth at best ask (YES ask = 40c)
        OrderbookLevel(price_cents=61, size=400),  # Next level (YES ask = 39c)
    )
    orderbook = OrderbookSnapshot(
        ticker="KXBTC15M-26JUL211745-45",
        yes_bids=yes_bids,
        no_bids=no_bids
    )
    
    # Walk orderbook for 100 contracts (more than best ask depth)
    avg_fill, slippage, depth = walk_orderbook_ladder(orderbook, "yes", 100, max_price_window_cents=5)
    
    # Should fill at blended price due to slippage
    assert avg_fill is not None, f"Should have average fill price"
    assert slippage is not None, f"Should have slippage cost"
    # Algorithm fills at cheapest available within window
    assert avg_fill == 39.0, f"Should fill at 39c (50@40c + 50@39c), got {avg_fill}c"
    # Slippage is negative when filling below best ask (favorable)
    assert slippage < 0.0, f"Slippage should be negative when filling below best ask, got {slippage}c"


def test_walk_orderbook_ladder_insufficient_depth():
    """Test orderbook ladder walking with insufficient depth."""
    # Create orderbook with very limited depth
    yes_bids = (
        OrderbookLevel(price_cents=40, size=10),
    )
    no_bids = (
        OrderbookLevel(price_cents=60, size=10),
    )
    orderbook = OrderbookSnapshot(
        ticker="KXBTC15M-26JUL211745-45",
        yes_bids=yes_bids,
        no_bids=no_bids
    )
    
    # Walk orderbook for 100 contracts (more than available depth)
    avg_fill, slippage, depth = walk_orderbook_ladder(orderbook, "yes", 100, max_price_window_cents=5)
    
    # Should return None for insufficient liquidity
    assert avg_fill is None, f"Should return None for insufficient depth"
    assert slippage is None, f"Should return None for insufficient depth"
    assert depth < 100, f"Depth should be < order size"


def test_walk_orderbook_ladder_no_side():
    """Test orderbook ladder walking for NO side."""
    # Create orderbook with multiple levels
    yes_bids = (
        OrderbookLevel(price_cents=40, size=800),  # NO ask = 100 - 40 = 60
        OrderbookLevel(price_cents=39, size=400),  # NO ask = 100 - 39 = 61
    )
    no_bids = (
        OrderbookLevel(price_cents=60, size=1000),
        OrderbookLevel(price_cents=59, size=500),
    )
    orderbook = OrderbookSnapshot(
        ticker="KXBTC15M-26JUL211745-45",
        yes_bids=yes_bids,
        no_bids=no_bids
    )
    
    # Walk orderbook for 100 contracts
    avg_fill, slippage, depth = walk_orderbook_ladder(orderbook, "no", 100, max_price_window_cents=5)
    
    # Should fill at best NO ask (60c)
    assert avg_fill is not None, f"Should have average fill price"
    assert slippage is not None, f"Should have slippage cost"
    assert avg_fill == 60.0, f"Should fill at best NO ask (60c), got {avg_fill}c"
    assert slippage == 0.0, f"No slippage when filling at best price, got {slippage}c"


def test_walk_orderbook_ladder_price_window():
    """Test orderbook ladder walking respects price window for adverse slippage."""
    # Create orderbook with levels that would require walking UP (more expensive)
    yes_bids = (
        OrderbookLevel(price_cents=40, size=10),
    )
    no_bids = (
        OrderbookLevel(price_cents=60, size=10),  # YES ask = 40c (best ask)
        OrderbookLevel(price_cents=55, size=1000),  # YES ask = 45c (5c up from best)
        OrderbookLevel(price_cents=50, size=1000),  # YES ask = 50c (10c up - should be excluded)
    )
    orderbook = OrderbookSnapshot(
        ticker="KXBTC15M-26JUL211745-45",
        yes_bids=yes_bids,
        no_bids=no_bids
    )
    
    # Walk orderbook with 5c price window
    avg_fill, slippage, depth = walk_orderbook_ladder(orderbook, "yes", 100, max_price_window_cents=5)
    
    # Should only consider levels within 5c window above best ask (40c to 45c)
    # 45c is within 5c window, 50c is outside (10c away)
    assert depth == 1010, f"Should include levels within 5c window (10 + 1000), got {depth}"


def test_compute_depth_adjusted_edges():
    """Test depth-adjusted edge calculation."""
    # Create base edge metrics
    spread_metrics = PerSideSpreadMetrics(
        yes_bid_cents=40,
        yes_ask_cents=41,
        no_bid_cents=59,
        no_ask_cents=60,
        yes_spread_cents=1,
        no_spread_cents=1
    )
    
    yes_edge = PerSideEdgeMetrics(
        side="yes",
        raw_edge_cents=10.0,
        spread_cents=1,
        executable_edge_cents=8.0,
        spread_cost_cents=0.5,
        taker_fee_cents=1.5,
        spread_to_edge_ratio=0.1,
        p_hat_yes_cents=50.0
    )
    
    no_edge = PerSideEdgeMetrics(
        side="no",
        raw_edge_cents=10.0,
        spread_cents=1,
        executable_edge_cents=8.0,
        spread_cost_cents=0.5,
        taker_fee_cents=1.5,
        spread_to_edge_ratio=0.1,
        p_hat_yes_cents=50.0
    )
    
    # Create orderbook
    yes_bids = (OrderbookLevel(price_cents=40, size=1000),)
    no_bids = (OrderbookLevel(price_cents=60, size=1000),)
    orderbook = OrderbookSnapshot(
        ticker="KXBTC15M-26JUL211745-45",
        yes_bids=yes_bids,
        no_bids=no_bids
    )
    
    # Compute depth-adjusted edges
    yes_adj, no_adj = compute_depth_adjusted_edges(yes_edge, no_edge, orderbook, order_size=1)
    
    # Verify depth-adjusted fields are populated
    assert yes_adj.avg_fill_price_cents is not None, f"YES avg fill should be populated"
    assert yes_adj.slippage_cost_cents is not None, f"YES slippage should be populated"
    assert yes_adj.depth_adjusted_edge_cents is not None, f"YES depth-adjusted edge should be populated"
    
    # Depth-adjusted edge should be <= executable edge (with slippage)
    assert yes_adj.depth_adjusted_edge_cents <= yes_adj.executable_edge_cents, \
        f"Depth-adjusted edge ({yes_adj.depth_adjusted_edge_cents}c) should be <= executable edge ({yes_adj.executable_edge_cents}c)"


def test_compute_depth_adjusted_edges_no_orderbook():
    """Test depth-adjusted edge calculation with no orderbook."""
    # Create base edge metrics
    spread_metrics = PerSideSpreadMetrics(
        yes_bid_cents=40,
        yes_ask_cents=41,
        no_bid_cents=59,
        no_ask_cents=60,
        yes_spread_cents=1,
        no_spread_cents=1
    )
    
    yes_edge = PerSideEdgeMetrics(
        side="yes",
        raw_edge_cents=10.0,
        spread_cents=1,
        executable_edge_cents=8.0,
        spread_cost_cents=0.5,
        taker_fee_cents=1.5,
        spread_to_edge_ratio=0.1,
        p_hat_yes_cents=50.0
    )
    
    no_edge = PerSideEdgeMetrics(
        side="no",
        raw_edge_cents=10.0,
        spread_cents=1,
        executable_edge_cents=8.0,
        spread_cost_cents=0.5,
        taker_fee_cents=1.5,
        spread_to_edge_ratio=0.1,
        p_hat_yes_cents=50.0
    )
    
    # Compute depth-adjusted edges with no orderbook
    yes_adj, no_adj = compute_depth_adjusted_edges(yes_edge, no_edge, None, order_size=1)
    
    # Depth-adjusted fields should be None when no orderbook
    assert yes_adj.avg_fill_price_cents is None, f"YES avg fill should be None without orderbook"
    assert yes_adj.slippage_cost_cents is None, f"YES slippage should be None without orderbook"
    assert yes_adj.depth_adjusted_edge_cents is None, f"YES depth-adjusted edge should be None without orderbook"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
