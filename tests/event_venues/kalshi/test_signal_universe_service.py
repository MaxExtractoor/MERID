"""
Unit tests for SignalUniverseService.

Tests the thin layer over MarketUniverse for signal generation.
"""

import pytest
from typing import List, Dict, Any

from merid.event_venues.kalshi.market_universe import MarketUniverse
from merid.event_venues.kalshi.signal_universe_service import (
    SignalUniverseService,
    initialize_signal_universe_service,
    get_signal_universe_service,
)


def create_fake_markets(count: int = 5) -> List[Dict[str, Any]]:
    """Create fake market data for testing."""
    assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    markets = []
    for i in range(count):
        asset = assets[i % len(assets)]
        markets.append({
            "ticker": f"KX{asset}15M-26JAN24-{5000 + i}",
            "asset": asset,
            "category": "crypto",
            "series": f"KX{asset}15M",
        })
    return markets


class TestSignalUniverseService:
    """Unit tests for SignalUniverseService."""

    def test_initialization_with_universe(self):
        """Test that SignalUniverseService initializes correctly with a universe."""
        markets = create_fake_markets(5)
        universe = MarketUniverse.from_markets(markets)
        service = SignalUniverseService(universe)
        
        assert service.get_market_count() == 5
        assert service.get_asset_count() == 5

    def test_get_markets_for_asset(self):
        """Test getting markets for a specific asset."""
        markets = create_fake_markets(5)
        universe = MarketUniverse.from_markets(markets)
        service = SignalUniverseService(universe)
        
        btc_markets = service.get_markets_for_asset("BTC")
        assert len(btc_markets) == 1
        assert btc_markets[0]["asset"] == "BTC"

    def test_get_market_by_ticker(self):
        """Test getting a market by ticker."""
        markets = create_fake_markets(5)
        universe = MarketUniverse.from_markets(markets)
        service = SignalUniverseService(universe)
        
        market = service.get_market_by_ticker("KXBTC15M-26JAN24-5000")
        assert market is not None
        assert market["ticker"] == "KXBTC15M-26JAN24-5000"

    def test_get_available_assets(self):
        """Test getting all available assets."""
        markets = create_fake_markets(5)
        universe = MarketUniverse.from_markets(markets)
        service = SignalUniverseService(universe)
        
        assets = service.get_available_assets()
        assert assets == {"BTC", "ETH", "SOL", "XRP", "DOGE"}

    def test_get_available_tickers(self):
        """Test getting all available tickers."""
        markets = create_fake_markets(5)
        universe = MarketUniverse.from_markets(markets)
        service = SignalUniverseService(universe)
        
        tickers = service.get_available_tickers()
        assert len(tickers) == 5
        assert "KXBTC15M-26JAN24-5000" in tickers

    def test_is_market_allowed(self):
        """Test checking if a market is allowed."""
        markets = create_fake_markets(5)
        universe = MarketUniverse.from_markets(markets)
        service = SignalUniverseService(universe)
        
        assert service.is_market_allowed("KXBTC15M-26JAN24-5000")
        assert not service.is_market_allowed("KXADA15M-26JAN24-5000")

    def test_is_asset_allowed(self):
        """Test checking if an asset is allowed."""
        markets = create_fake_markets(5)
        universe = MarketUniverse.from_markets(markets)
        service = SignalUniverseService(universe)
        
        assert service.is_asset_allowed("BTC")
        assert not service.is_asset_allowed("ADA")

    def test_get_all_markets(self):
        """Test getting all markets."""
        markets = create_fake_markets(5)
        universe = MarketUniverse.from_markets(markets)
        service = SignalUniverseService(universe)
        
        all_markets = service.get_all_markets()
        assert len(all_markets) == 5

    def test_empty_universe(self):
        """Test service behavior with empty universe."""
        markets = []
        universe = MarketUniverse.from_markets(markets)
        service = SignalUniverseService(universe)
        
        assert service.get_market_count() == 0
        assert service.get_asset_count() == 0
        assert service.get_available_assets() == set()
        assert service.get_available_tickers() == set()
        assert service.get_markets_for_asset("BTC") == []
        assert service.get_market_by_ticker("KXBTC15M-26JAN24-5000") is None

    def test_none_universe(self):
        """Test service behavior with None universe."""
        service = SignalUniverseService(None)
        
        assert service.get_market_count() == 0
        assert service.get_asset_count() == 0
        assert service.get_available_assets() == set()
        assert service.get_available_tickers() == set()
        assert service.get_markets_for_asset("BTC") == []
        assert service.get_market_by_ticker("KXBTC15M-26JAN24-5000") is None
        assert not service.is_market_allowed("KXBTC15M-26JAN24-5000")
        assert not service.is_asset_allowed("BTC")

    def test_log_summary(self):
        """Test logging the universe summary."""
        markets = create_fake_markets(5)
        universe = MarketUniverse.from_markets(markets)
        service = SignalUniverseService(universe)
        
        # Should not raise an exception
        service.log_summary()

    def test_global_singleton(self):
        """Test global singleton pattern."""
        markets = create_fake_markets(3)
        universe = MarketUniverse.from_markets(markets)
        
        # Initialize global service
        service1 = initialize_signal_universe_service(universe)
        service2 = get_signal_universe_service()
        
        # Should return the same instance
        assert service1 is service2
        assert service2.get_market_count() == 3
