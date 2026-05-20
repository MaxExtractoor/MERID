"""
Kalshi 15m Crypto WS Bridge and Market State Tests

Tests that verify WS bridge configuration and market state logic
for the 5×15m grid (BTC/ETH/SOL/XRP/DOGE at 15m timeframe).

Tagged with @pytest.mark.kalshi_15m_critical for CI enforcement.
"""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.kalshi_15m_critical


class TestKalshiCryptoWSBridgeConfiguration:
    """Test WS bridge configuration for 5×15m grid."""

    def test_kalshi_crypto_config_has_5_assets(self):
        """Test that ACTIVE_CRYPTO_ASSETS contains 5 assets."""
        from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS
        
        expected_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        assert len(ACTIVE_CRYPTO_ASSETS) == 5
        assert all(asset in ACTIVE_CRYPTO_ASSETS for asset in expected_assets)

    def test_kalshi_crypto_config_has_15m_timeframe(self):
        """Test that ACTIVE_CRYPTO_WS_TIMEFRAMES contains 15m."""
        from config.kalshi_crypto_config import ACTIVE_CRYPTO_WS_TIMEFRAMES
        
        assert "15m" in ACTIVE_CRYPTO_WS_TIMEFRAMES

    def test_kalshi_agent_grid_catalog_series_tickers_uses_15m(self):
        """Test that catalog series tickers use 15M suffix."""
        from config.kalshi_universe import kalshi_agent_grid_catalog_series_tickers
        
        series_tickers = kalshi_agent_grid_catalog_series_tickers()
        
        # Verify series tickers use 15M suffix
        expected_tickers = ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]
        assert all(ticker in series_tickers for ticker in expected_tickers)


class TestKalshiMarketStateLogic:
    """Test market state logic for 5×15m grid."""

    def test_market_state_store_exists(self):
        """Test that KalshiMarketStateStore can be imported."""
        from merid.event_venues.kalshi.market_state import KalshiMarketStateStore, get_kalshi_market_state_store
        
        # Verify the store can be instantiated
        store = get_kalshi_market_state_store()
        assert store is not None
        assert isinstance(store, KalshiMarketStateStore)

    def test_market_state_has_is_trading_enabled_method(self):
        """Test that market state has is_trading_enabled method."""
        from merid.event_venues.kalshi.market_state import KalshiMarketStateStore
        
        # Verify the method exists
        assert hasattr(KalshiMarketStateStore, 'is_trading_enabled')

    def test_market_state_has_log_book_health_method(self):
        """Test that market state has log_book_health method."""
        from merid.event_venues.kalshi.market_state import KalshiMarketStateStore
        
        # Verify the method exists
        assert hasattr(KalshiMarketStateStore, 'log_book_health')
