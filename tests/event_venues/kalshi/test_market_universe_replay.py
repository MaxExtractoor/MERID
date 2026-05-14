"""
Replay test for market universe integration.

This test simulates the full pipeline:
catalog → MarketUniverse → SignalUniverseService → trading agent

It ensures that only the 5 allowed assets (BTC/ETH/SOL/XRP/DOGE 15m)
are processed through the pipeline and no disallowed markets leak through.
"""

import pytest
from typing import List, Dict, Any

from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
from merid.event_venues.kalshi.market_universe import MarketUniverse
from merid.event_venues.kalshi.signal_universe_service import (
    SignalUniverseService,
    initialize_signal_universe_service,
)
from merid.event_venues.kalshi.allowed_market_policy import (
    is_market_allowed,
    filter_allowed_markets,
    ALLOWED_ASSETS,
    ALLOWED_TIMEFRAME,
    ALLOWED_CATEGORY,
)


def create_historical_markets_for_5_assets() -> List[Dict[str, Any]]:
    """
    Create historical market data fixture for the 5 allowed assets only.
    
    Returns:
        List of market dicts for BTC, ETH, SOL, XRP, DOGE 15m markets
    """
    markets = []
    for asset in ALLOWED_ASSETS:
        markets.append({
            "ticker": f"KX{asset}15M-26JAN24-{5000 + ALLOWED_ASSETS.index(asset)}",
            "asset": asset,
            "category": ALLOWED_CATEGORY,
            "timeframe": ALLOWED_TIMEFRAME,
            "market_id": f"market_{asset.lower()}_15m",
            "title": f"{asset} > $50000 on Jan 26, 2024",
        })
    return markets


def create_historical_markets_with_disallowed() -> List[Dict[str, Any]]:
    """
    Create historical market data with disallowed assets mixed in.
    
    Returns:
        List of market dicts with both allowed and disallowed assets
    """
    markets = create_historical_markets_for_5_assets()
    
    # Add disallowed markets
    disallowed_assets = ["ADA", "DOT", "AVAX", "MATIC", "LINK"]
    for asset in disallowed_assets:
        markets.append({
            "ticker": f"KX{asset}15M-26JAN24-{6000 + disallowed_assets.index(asset)}",
            "asset": asset,
            "category": ALLOWED_CATEGORY,
            "timeframe": ALLOWED_TIMEFRAME,
            "market_id": f"market_{asset.lower()}_15m",
            "title": f"{asset} > $50000 on Jan 26, 2024",
        })
    
    return markets


class TestMarketUniverseReplay:
    """Replay test for the full market universe pipeline."""

    def test_catalog_to_market_universe_pipeline(self):
        """
        Test catalog → MarketUniverse pipeline with 5 allowed assets.
        
        This simulates the catalog refresh filtering step.
        """
        raw_markets = create_historical_markets_for_5_assets()
        
        # Apply AllowedMarketPolicy filter (catalog refresh step)
        filtered_markets = filter_allowed_markets(raw_markets)
        
        # Create MarketUniverse from filtered markets
        universe = MarketUniverse.from_markets(filtered_markets)
        
        # Validate universe
        assert universe.validate_universe()
        assert universe.get_market_count() == 5
        assert universe.get_assets() == ALLOWED_ASSETS
        
        # Verify all markets are allowed
        for market in universe.markets:
            assert is_market_allowed(market)

    def test_catalog_filters_disallowed_markets(self):
        """
        Test that catalog filters out disallowed markets.
        
        This ensures the "5000 in, 5 out" scenario works correctly.
        """
        raw_markets = create_historical_markets_with_disallowed()
        assert len(raw_markets) == 10  # 5 allowed + 5 disallowed
        
        # Apply AllowedMarketPolicy filter
        filtered_markets = filter_allowed_markets(raw_markets)
        
        # Verify only 5 markets remain
        assert len(filtered_markets) == 5
        
        # Verify all remaining markets are for allowed assets
        for market in filtered_markets:
            assert market["asset"] in ALLOWED_ASSETS

    def test_market_universe_to_signal_service_pipeline(self):
        """
        Test MarketUniverse → SignalUniverseService pipeline.
        
        This ensures signal generation only sees allowed markets.
        """
        raw_markets = create_historical_markets_for_5_assets()
        filtered_markets = filter_allowed_markets(raw_markets)
        universe = MarketUniverse.from_markets(filtered_markets)
        
        # Create SignalUniverseService from universe
        signal_service = SignalUniverseService(universe)
        
        # Verify signal service only sees allowed assets
        assert signal_service.get_asset_count() == 5
        assert signal_service.get_available_assets() == ALLOWED_ASSETS
        
        # Verify signal service can query by asset
        for asset in ALLOWED_ASSETS:
            markets = signal_service.get_markets_for_asset(asset)
            assert len(markets) == 1
            assert markets[0]["asset"] == asset

    def test_signal_service_rejects_disallowed_ticker(self):
        """
        Test that SignalUniverseService rejects disallowed tickers.
        
        This ensures no leakage in the signal generation layer.
        """
        raw_markets = create_historical_markets_for_5_assets()
        filtered_markets = filter_allowed_markets(raw_markets)
        universe = MarketUniverse.from_markets(filtered_markets)
        signal_service = SignalUniverseService(universe)
        
        # Test allowed ticker
        assert signal_service.is_market_allowed("KXBTC15M-26JAN24-5000")
        
        # Test disallowed ticker
        assert not signal_service.is_market_allowed("KXADA15M-26JAN24-6000")
        
        # Test disallowed asset
        assert not signal_service.is_asset_allowed("ADA")

    def test_full_pipeline_no_leakage(self):
        """
        Test the full pipeline: catalog → MarketUniverse → SignalUniverseService.
        
        This is the end-to-end check that ensures no disallowed markets
        leak through any layer.
        """
        # Step 1: Catalog with mixed markets
        raw_markets = create_historical_markets_with_disallowed()
        
        # Step 2: Apply AllowedMarketPolicy (catalog refresh)
        filtered_markets = filter_allowed_markets(raw_markets)
        assert len(filtered_markets) == 5
        
        # Step 3: Create MarketUniverse
        universe = MarketUniverse.from_markets(filtered_markets)
        assert universe.get_market_count() == 5
        assert universe.get_assets() == ALLOWED_ASSETS
        
        # Step 4: Create SignalUniverseService
        signal_service = SignalUniverseService(universe)
        
        # Step 5: Verify no disallowed assets in signal service
        assert signal_service.get_available_assets() == ALLOWED_ASSETS
        
        # Step 6: Verify all tickers are allowed
        for ticker in signal_service.get_available_tickers():
            assert signal_service.is_market_allowed(ticker)
        
        # Step 7: Verify disallowed ticker is rejected
        assert not signal_service.is_market_allowed("KXADA15M-26JAN24-6000")

    def test_empty_pipeline_graceful_degradation(self):
        """
        Test pipeline behavior with empty/unavailable universe.
        
        This ensures the system degrades gracefully when no markets are available.
        """
        # Empty universe
        universe = MarketUniverse.from_markets([])
        signal_service = SignalUniverseService(universe)
        
        # Verify graceful degradation
        assert signal_service.get_market_count() == 0
        assert signal_service.get_asset_count() == 0
        assert signal_service.get_markets_for_asset("BTC") == []
        assert signal_service.get_market_by_ticker("KXBTC15M-26JAN24-5000") is None

    def test_global_singleton_initialization(self):
        """
        Test global SignalUniverseService singleton initialization.
        
        This ensures the service can be initialized globally for use
        across the application.
        """
        raw_markets = create_historical_markets_for_5_assets()
        filtered_markets = filter_allowed_markets(raw_markets)
        universe = MarketUniverse.from_markets(filtered_markets)
        
        # Initialize global service
        service = initialize_signal_universe_service(universe)
        
        # Verify global instance
        from merid.event_venues.kalshi.signal_universe_service import get_signal_universe_service
        global_service = get_signal_universe_service()
        
        assert global_service is service
        assert global_service.get_market_count() == 5

    def test_asset_consistency_across_pipeline(self):
        """
        Test that assets are consistent across all pipeline stages.
        
        This ensures no asset drift occurs as data flows through
        catalog → MarketUniverse → SignalUniverseService.
        """
        raw_markets = create_historical_markets_for_5_assets()
        
        # Stage 1: Catalog assets
        catalog_assets = set(m["asset"] for m in raw_markets)
        
        # Stage 2: Filtered assets
        filtered_markets = filter_allowed_markets(raw_markets)
        filtered_assets = set(m["asset"] for m in filtered_markets)
        
        # Stage 3: MarketUniverse assets
        universe = MarketUniverse.from_markets(filtered_markets)
        universe_assets = universe.get_assets()
        
        # Stage 4: SignalUniverseService assets
        signal_service = SignalUniverseService(universe)
        signal_assets = signal_service.get_available_assets()
        
        # Verify consistency across all stages
        assert catalog_assets == ALLOWED_ASSETS
        assert filtered_assets == ALLOWED_ASSETS
        assert universe_assets == ALLOWED_ASSETS
        assert signal_assets == ALLOWED_ASSETS
