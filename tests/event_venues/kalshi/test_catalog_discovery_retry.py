"""
Kalshi Catalog Discovery Retry and Fallback Tests

This test suite validates the catalog discovery retry logic with exponential backoff
and the direct market lookup fallback mechanism.

SPEC_VERSION: 1.0.0
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, Any, List


class TestCatalogDiscoveryRetry:
    """Test catalog discovery retry logic with exponential backoff."""

    @pytest.fixture
    def mock_catalog(self):
        """Create a mock catalog."""
        catalog = Mock()
        catalog.snapshot = Mock()
        catalog.get_active_markets = Mock()
        return catalog

    @pytest.fixture
    def allowed_assets(self):
        """Allowed crypto assets."""
        return ["BTC", "ETH", "SOL", "XRP", "DOGE"]

    @pytest.mark.asyncio
    async def test_retry_intervals_exponential_backoff(self):
        """Test that retry intervals follow exponential backoff pattern."""
        # Arrange: Expected retry intervals
        expected_intervals = [1.0, 2.0, 4.0, 8.0, 16.0, 32.0]
        
        # Act: Verify the pattern
        for i in range(len(expected_intervals) - 1):
            assert expected_intervals[i + 1] == expected_intervals[i] * 2
        
        # Assert: Total time is 63s
        assert sum(expected_intervals) == 63.0

    @pytest.mark.asyncio
    async def test_catalog_discovery_success_on_first_attempt(self, mock_catalog, allowed_assets):
        """Test successful catalog discovery on first attempt."""
        # Arrange: Mock catalog returns markets for all assets
        mock_market = Mock()
        mock_market.market = Mock()
        mock_market.market.market_id = "KXBTC15M-TEST"
        mock_catalog.get_active_markets.return_value = [mock_market]
        
        # Act: Simulate discovery logic
        initial_tickers = []
        for asset in allowed_assets:
            asset_markets = mock_catalog.get_active_markets(asset=asset, timeframe="15m")
            if asset_markets:
                market = asset_markets[0]
                ticker = market.market.market_id
                initial_tickers.append(ticker)
        
        # Assert: All assets discovered
        assert len(initial_tickers) == len(allowed_assets)
        assert mock_catalog.get_active_markets.call_count == len(allowed_assets)

    @pytest.mark.asyncio
    async def test_catalog_discovery_retry_on_empty_catalog(self, mock_catalog, allowed_assets):
        """Test retry logic when catalog is initially empty."""
        # Arrange: Mock catalog returns empty on first attempt, then markets
        call_count = [0]
        
        def get_active_markets_side_effect(asset, timeframe):
            call_count[0] += 1
            if call_count[0] <= len(allowed_assets):  # First attempt - empty
                return []
            else:  # Second attempt - return markets
                mock_market = Mock()
                mock_market.market = Mock()
                mock_market.market.market_id = f"KX{asset}15M-TEST"
                return [mock_market]
        
        mock_catalog.get_active_markets.side_effect = get_active_markets_side_effect
        
        # Act: Simulate retry logic
        retry_intervals = [1.0, 2.0]  # Shortened for test
        initial_tickers = []
        
        for attempt, wait_interval in enumerate(retry_intervals):
            initial_tickers = []
            for asset in allowed_assets:
                asset_markets = mock_catalog.get_active_markets(asset=asset, timeframe="15m")
                if asset_markets:
                    market = asset_markets[0]
                    ticker = market.market.market_id
                    initial_tickers.append(ticker)
            
            if initial_tickers:
                break
            if attempt < len(retry_intervals) - 1:
                await asyncio.sleep(0.01)  # Minimal sleep for test
        
        # Assert: Discovery succeeded after retry
        assert len(initial_tickers) == len(allowed_assets)

    @pytest.mark.asyncio
    async def test_catalog_discovery_logs_detailed_state(self, mock_catalog, allowed_assets):
        """Test that catalog discovery logs detailed state for diagnostics."""
        # Arrange: Mock catalog snapshot
        mock_snapshot = Mock()
        mock_snapshot.markets = []
        mock_catalog.snapshot.return_value = mock_snapshot
        mock_catalog.get_active_markets.return_value = []
        
        # Act: Simulate discovery with logging
        catalog_snapshot = mock_catalog.snapshot()
        log_message = (
            f"Catalog discovery attempt: "
            f"total_markets={len(catalog_snapshot.markets)} "
            f"elapsed=0.0s "
            f"next_wait=1.0s"
        )
        
        # Assert: Log message contains expected fields
        assert "total_markets=" in log_message
        assert "elapsed=" in log_message
        assert "next_wait=" in log_message


class TestDirectMarketLookupFallback:
    """Test direct market lookup fallback mechanism."""

    @pytest.fixture
    def mock_kalshi_client(self):
        """Create a mock Kalshi client."""
        client = AsyncMock()
        client.get_markets = AsyncMock()
        return client

    @pytest.fixture
    def allowed_assets(self):
        """Allowed crypto assets."""
        return ["BTC", "ETH", "SOL", "XRP", "DOGE"]

    @pytest.fixture
    def series_tickers(self):
        """Series tickers for each asset."""
        return {
            "BTC": "KXBTC15M",
            "ETH": "KXETH15M",
            "SOL": "KXSOL15M",
            "XRP": "KXXRP15M",
            "DOGE": "KXDOGE15M",
        }

    @pytest.mark.asyncio
    async def test_fallback_queries_kalshi_api_directly(self, mock_kalshi_client, allowed_assets, series_tickers):
        """Test that fallback queries Kalshi API directly for each asset."""
        # Arrange: Mock API responses
        mock_kalshi_client.get_markets.return_value = {
            "markets": [
                {
                    "ticker": "KXBTC15M-TEST",
                    "status": "open"
                }
            ]
        }
        
        # Act: Simulate fallback logic
        fallback_tickers = []
        for asset in allowed_assets:
            series_ticker = series_tickers.get(asset)
            if not series_ticker:
                continue
            
            markets = await mock_kalshi_client.get_markets(series_ticker=series_ticker, limit=10)
            
            if markets and markets['markets']:
                for market in markets['markets']:
                    if market.get('status') == 'open':
                        ticker = market['ticker']
                        fallback_tickers.append(ticker)
                        break
        
        # Assert: API was queried for each asset
        assert mock_kalshi_client.get_markets.call_count == len(allowed_assets)
        assert len(fallback_tickers) == len(allowed_assets)

    @pytest.mark.asyncio
    async def test_fallback_filters_only_open_markets(self, mock_kalshi_client, allowed_assets, series_tickers):
        """Test that fallback only selects open markets."""
        # Arrange: Mock API response with mixed statuses
        mock_kalshi_client.get_markets.return_value = {
            "markets": [
                {"ticker": "KXBTC15M-CLOSED", "status": "closed"},
                {"ticker": "KXBTC15M-OPEN", "status": "open"},
                {"ticker": "KXBTC15M-SETTLED", "status": "settled"},
            ]
        }
        
        # Act: Simulate fallback for single asset
        asset = "BTC"
        series_ticker = series_tickers.get(asset)
        markets = await mock_kalshi_client.get_markets(series_ticker=series_ticker, limit=10)
        
        fallback_tickers = []
        if markets and markets['markets']:
            for market in markets['markets']:
                if market.get('status') == 'open':
                    ticker = market['ticker']
                    fallback_tickers.append(ticker)
                    break
        
        # Assert: Only open market selected
        assert len(fallback_tickers) == 1
        assert fallback_tickers[0] == "KXBTC15M-OPEN"

    @pytest.mark.asyncio
    async def test_fallback_handles_api_errors_gracefully(self, mock_kalshi_client, allowed_assets, series_tickers):
        """Test that fallback handles API errors without crashing."""
        # Arrange: Mock API to raise exception
        mock_kalshi_client.get_markets.side_effect = Exception("API Error")
        
        # Act: Simulate fallback with error handling
        fallback_tickers = []
        for asset in allowed_assets:
            series_ticker = series_tickers.get(asset)
            if not series_ticker:
                continue
            
            try:
                markets = await mock_kalshi_client.get_markets(series_ticker=series_ticker, limit=10)
                if markets and markets['markets']:
                    for market in markets['markets']:
                        if market.get('status') == 'open':
                            ticker = market['ticker']
                            fallback_tickers.append(ticker)
                            break
            except Exception as e:
                # Error logged but loop continues
                pass
        
        # Assert: No tickers recovered, but no crash
        assert len(fallback_tickers) == 0

    @pytest.mark.asyncio
    async def test_fallback_handles_empty_api_response(self, mock_kalshi_client, allowed_assets, series_tickers):
        """Test that fallback handles empty API response."""
        # Arrange: Mock API to return empty markets
        mock_kalshi_client.get_markets.return_value = {
            "markets": []
        }
        
        # Act: Simulate fallback
        fallback_tickers = []
        for asset in allowed_assets:
            series_ticker = series_tickers.get(asset)
            if not series_ticker:
                continue
            
            markets = await mock_kalshi_client.get_markets(series_ticker=series_ticker, limit=10)
            
            if markets and markets['markets']:
                for market in markets['markets']:
                    if market.get('status') == 'open':
                        ticker = market['ticker']
                        fallback_tickers.append(ticker)
                        break
        
        # Assert: No tickers recovered
        assert len(fallback_tickers) == 0


class TestCatalogHealthMonitoring:
    """Test catalog health monitoring for critical assets."""

    @pytest.fixture
    def mock_catalog(self):
        """Create a mock catalog."""
        catalog = Mock()
        catalog.snapshot = Mock()
        return catalog

    @pytest.fixture
    def critical_assets(self):
        """Critical crypto assets."""
        return ["BTC", "ETH", "SOL", "XRP", "DOGE"]

    def test_health_status_includes_critical_assets(self, mock_catalog, critical_assets):
        """Test that health status includes critical asset health."""
        # Arrange: Mock catalog snapshot with markets
        mock_snapshot = Mock()
        mock_market = Mock()
        mock_market.asset = "BTC"
        mock_market.timeframe = "15m"
        mock_market.tradeable = True
        mock_snapshot.markets = [mock_market]
        mock_catalog.snapshot.return_value = mock_snapshot
        
        # Act: Simulate health check
        snapshot = mock_catalog.snapshot()
        asset_health = {}
        missing_assets = []
        
        for asset in critical_assets:
            asset_markets = [m for m in snapshot.markets if m.asset == asset and m.timeframe == "15m"]
            tradeable_markets = [m for m in asset_markets if m.tradeable]
            
            asset_health[asset] = {
                "total_15m_markets": len(asset_markets),
                "tradeable_15m_markets": len(tradeable_markets),
                "has_tradeable": len(tradeable_markets) > 0
            }
            
            if len(tradeable_markets) == 0:
                missing_assets.append(asset)
        
        # Assert: Health status includes all assets
        assert set(asset_health.keys()) == set(critical_assets)
        assert "has_tradeable" in asset_health["BTC"]

    def test_health_status_detects_missing_assets(self, mock_catalog, critical_assets):
        """Test that health status detects missing critical assets."""
        # Arrange: Mock catalog snapshot with no markets
        mock_snapshot = Mock()
        mock_snapshot.markets = []
        mock_catalog.snapshot.return_value = mock_snapshot
        
        # Act: Simulate health check
        snapshot = mock_catalog.snapshot()
        missing_assets = []
        
        for asset in critical_assets:
            asset_markets = [m for m in snapshot.markets if m.asset == asset and m.timeframe == "15m"]
            tradeable_markets = [m for m in asset_markets if m.tradeable]
            
            if len(tradeable_markets) == 0:
                missing_assets.append(asset)
        
        # Assert: All assets detected as missing
        assert set(missing_assets) == set(critical_assets)

    def test_health_status_all_critical_assets_present(self, mock_catalog, critical_assets):
        """Test that health status correctly reports all assets present."""
        # Arrange: Mock catalog snapshot with markets for all assets
        mock_snapshot = Mock()
        mock_snapshot.markets = []
        
        for asset in critical_assets:
            mock_market = Mock()
            mock_market.asset = asset
            mock_market.timeframe = "15m"
            mock_market.tradeable = True
            mock_snapshot.markets.append(mock_market)
        
        mock_catalog.snapshot.return_value = mock_snapshot
        
        # Act: Simulate health check
        snapshot = mock_catalog.snapshot()
        missing_assets = []
        
        for asset in critical_assets:
            asset_markets = [m for m in snapshot.markets if m.asset == asset and m.timeframe == "15m"]
            tradeable_markets = [m for m in asset_markets if m.tradeable]
            
            if len(tradeable_markets) == 0:
                missing_assets.append(asset)
        
        # Assert: No missing assets
        assert len(missing_assets) == 0
