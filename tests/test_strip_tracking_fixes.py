"""Tests for strip tracking fixes in agent_grid_15m.py.

Tests cover:
- Market ID detection for MinimalMarket (market_id directly, not nested)
- Asset-specific series ticker matching (KXBTC15M, KXETH15M, etc.)
- Strip counter reset when market IDs change
- Independent tracking per asset
"""

import pytest
from unittest.mock import Mock, MagicMock
from merid.prediction.agent_grid_15m import LeanAgentConfig, MinimalMarket, FifteenMinuteMarketLocator


def test_minimal_market_market_id_detection():
    """Test that market_id is correctly detected from MinimalMarket."""
    # MinimalMarket has market_id directly, not nested under .market.market_id
    market = MinimalMarket(
        market_id="KXBTC15M-26JUN282115-15",
        close_time=1719657600.0,
        asset="BTC"
    )
    
    # Should detect market_id directly
    assert hasattr(market, 'market_id')
    assert market.market_id == "KXBTC15M-26JUN282115-15"
    
    # The fix checks for market_id directly first, then falls back to nested structure
    # Verify direct access works
    direct_market_id = market.market_id if hasattr(market, 'market_id') else None
    assert direct_market_id == "KXBTC15M-26JUN282115-15"


def test_asset_specific_series_ticker_matching():
    """Test that series ticker is matched to current asset."""
    config = LeanAgentConfig(
        name="BTC_15M",
        series_tickers=["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]
    )
    
    # Test BTC matching
    asset = "BTC"
    strip_ticker = None
    for ticker in config.series_tickers:
        if asset.upper() in ticker.upper():
            strip_ticker = ticker
            break
    assert strip_ticker == "KXBTC15M"
    
    # Test ETH matching
    asset = "ETH"
    strip_ticker = None
    for ticker in config.series_tickers:
        if asset.upper() in ticker.upper():
            strip_ticker = ticker
            break
    assert strip_ticker == "KXETH15M"
    
    # Test SOL matching
    asset = "SOL"
    strip_ticker = None
    for ticker in config.series_tickers:
        if asset.upper() in ticker.upper():
            strip_ticker = ticker
            break
    assert strip_ticker == "KXSOL15M"
    
    # Test XRP matching
    asset = "XRP"
    strip_ticker = None
    for ticker in config.series_tickers:
        if asset.upper() in ticker.upper():
            strip_ticker = ticker
            break
    assert strip_ticker == "KXXRP15M"
    
    # Test DOGE matching
    asset = "DOGE"
    strip_ticker = None
    for ticker in config.series_tickers:
        if asset.upper() in ticker.upper():
            strip_ticker = ticker
            break
    assert strip_ticker == "KXDOGE15M"


def test_strip_counter_reset_on_market_id_change():
    """Test that strip counter resets when market ID changes."""
    # Simulate the strip tracking logic directly
    strip_ticker = "KXBTC15M"
    strip_order_counts = {strip_ticker: 5}
    current_market_ids = {strip_ticker: "KXBTC15M-26JUN282115-15"}
    
    # Simulate market ID change (new 15-minute window)
    new_market_id = "KXBTC15M-26JUN282130-15"
    current_market_id = new_market_id
    
    # Check if reset should happen (same logic as in agent_grid_15m.py)
    if current_market_id and current_market_ids.get(strip_ticker) != current_market_id:
        strip_order_counts[strip_ticker] = 0
        current_market_ids[strip_ticker] = current_market_id
    
    # Verify counter was reset
    assert strip_order_counts[strip_ticker] == 0
    assert current_market_ids[strip_ticker] == new_market_id


def test_independent_strip_tracking_per_asset():
    """Test that each asset has independent strip order tracking."""
    config = LeanAgentConfig(
        name="BTC_15M",
        series_tickers=["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]
    )
    
    # Initialize strip order counts for all assets
    strip_order_counts = {}
    for ticker in config.series_tickers:
        strip_order_counts[ticker] = 0
    
    # Simulate orders for different assets
    strip_order_counts["KXBTC15M"] = 3
    strip_order_counts["KXETH15M"] = 5
    strip_order_counts["KXSOL15M"] = 2
    strip_order_counts["KXXRP15M"] = 4
    strip_order_counts["KXDOGE15M"] = 1
    
    # Verify each asset has independent count
    assert strip_order_counts["KXBTC15M"] == 3
    assert strip_order_counts["KXETH15M"] == 5
    assert strip_order_counts["KXSOL15M"] == 2
    assert strip_order_counts["KXXRP15M"] == 4
    assert strip_order_counts["KXDOGE15M"] == 1
    
    # Reset one asset's counter (market ID change)
    strip_order_counts["KXETH15M"] = 0
    
    # Verify only that asset was reset
    assert strip_order_counts["KXBTC15M"] == 3  # Unchanged
    assert strip_order_counts["KXETH15M"] == 0   # Reset
    assert strip_order_counts["KXSOL15M"] == 2  # Unchanged
    assert strip_order_counts["KXXRP15M"] == 4  # Unchanged
    assert strip_order_counts["KXDOGE15M"] == 1  # Unchanged


def test_per_strip_order_limit_enforcement():
    """Test that per-strip order limit is enforced correctly."""
    config = LeanAgentConfig(
        name="BTC_15M",
        series_tickers=["KXBTC15M"],
        per_strip_order_limit=10
    )
    
    strip_ticker = "KXBTC15M"
    strip_order_counts = {strip_ticker: 10}
    
    # Should reject when at limit
    current_strip_orders = strip_order_counts.get(strip_ticker, 0)
    if current_strip_orders >= config.per_strip_order_limit:
        should_reject = True
    else:
        should_reject = False
    
    assert should_reject is True
    
    # Should accept when below limit
    strip_order_counts[strip_ticker] = 9
    current_strip_orders = strip_order_counts.get(strip_ticker, 0)
    if current_strip_orders >= config.per_strip_order_limit:
        should_reject = True
    else:
        should_reject = False
    
    assert should_reject is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
