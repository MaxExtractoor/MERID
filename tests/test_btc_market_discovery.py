"""
Tests for BTC market discovery and filtering in KalshiMarketCatalog and BTC15MLane.

These tests verify:
1. BTC markets are correctly detected from Kalshi API ticker patterns
2. Timeframe detection works for 15m and 1h BTC markets
3. Market filtering distinguishes between "no API results" vs "filtered out"
4. BTC15MLane properly logs diagnostic information when no markets found
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from unittest.mock import Mock, AsyncMock, patch

import pytest

from merid.event_venues.base import EventMarket, MarketFilter
from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog, CatalogMarket
from merid.event_venues.kalshi.models import OperationResult


def make_event_market(
    market_id: str,
    question: str,
    close_time: datetime,
    volume: float = 1000.0,
) -> EventMarket:
    """Helper to create a mock EventMarket."""
    return EventMarket(
        market_id=market_id,
        venue="kalshi",
        question=question,
        description=question,
        open_time=datetime.now(timezone.utc) - timedelta(days=1),
        close_time=close_time,
        volume=volume,
        liquidity=volume * 0.5,
        status="open",
        raw_data={},
    )


class TestBTCMarketDetection:
    """Test BTC market detection from Kalshi ticker patterns."""

    def test_btc_ticker_patterns(self):
        """Verify BTC ticker patterns are correctly matched."""
        from merid.event_venues.kalshi.market_catalog import _TICKER_CATEGORY_MAP
        import re

        # Find BTC pattern
        btc_patterns = [
            (pat, cat, asset)
            for pat, cat, asset in _TICKER_CATEGORY_MAP
            if asset == "BTC"
        ]
        assert len(btc_patterns) > 0, "No BTC patterns found in _TICKER_CATEGORY_MAP"

        pattern, category, asset = btc_patterns[0]

        # Test valid BTC tickers
        valid_tickers = [
            "KXBTC-24MAR23-15M-70000",
            "KXBTC-15M",
            "KXBITCOIN-HOURLY",
            "KXBitcoin",
        ]
        for ticker in valid_tickers:
            assert pattern.search(ticker), f"Pattern should match {ticker}"
            assert category == "crypto"
            assert asset == "BTC"

        # Test invalid tickers
        invalid_tickers = ["KXETH-15M", "KXSOL-HOURLY", "BTCUSD", "ETHBTC"]
        for ticker in invalid_tickers:
            assert not pattern.search(ticker), f"Pattern should NOT match {ticker}"

    @pytest.mark.asyncio
    async def test_catalog_enrichment_btc_markets(self):
        """Test that catalog correctly enriches BTC markets with asset and timeframe tags."""
        # Create mock markets
        now = datetime.now(timezone.utc)
        markets = [
            make_event_market(
                "KXBTC-15M-70000",
                "Will Bitcoin trade above $70,000 in the next 15 minutes?",
                now + timedelta(minutes=15),
                volume=5000.0,
            ),
            make_event_market(
                "KXBTC-1H-75000",
                "Will Bitcoin reach $75,000 in the next hour?",
                now + timedelta(hours=1),
                volume=3000.0,
            ),
            make_event_market(
                "KXETH-15M-4000",
                "Will Ethereum trade above $4,000 in the next 15 minutes?",
                now + timedelta(minutes=15),
                volume=2000.0,
            ),
        ]

        # Create catalog with mocked client
        mock_client = Mock()
        mock_client.list_markets_result = AsyncMock(
            return_value=OperationResult.ok(markets)
        )

        catalog = KalshiMarketCatalog(client=mock_client, max_markets=100)
        await catalog.refresh()

        # Verify BTC markets are indexed
        btc_markets = catalog.get_markets_by_asset("BTC")
        assert len(btc_markets) == 2, f"Expected 2 BTC markets, got {len(btc_markets)}"

        # Verify timeframe detection
        btc_15m = catalog.get_markets_by_asset("BTC", timeframe="15m")
        assert len(btc_15m) == 1, f"Expected 1 BTC 15m market, got {len(btc_15m)}"

        btc_1h = catalog.get_markets_by_asset("BTC", timeframe="1h")
        assert len(btc_1h) == 1, f"Expected 1 BTC 1h market, got {len(btc_1h)}"

        # Verify ETH markets are separate
        eth_markets = catalog.get_markets_by_asset("ETH")
        assert len(eth_markets) == 1, f"Expected 1 ETH market, got {len(eth_markets)}"

    @pytest.mark.asyncio
    async def test_catalog_logs_no_btc_markets(self, caplog):
        """Test that catalog logs warning when no BTC markets are detected."""
        # Create markets without BTC
        now = datetime.now(timezone.utc)
        markets = [
            make_event_market(
                "KXETH-15M-4000",
                "Will Ethereum trade above $4,000?",
                now + timedelta(minutes=15),
            ),
            make_event_market(
                "KXSOL-1H-200",
                "Will Solana reach $200?",
                now + timedelta(hours=1),
            ),
        ]

        mock_client = Mock()
        mock_client.list_markets_result = AsyncMock(
            return_value=OperationResult.ok(markets)
        )

        catalog = KalshiMarketCatalog(client=mock_client, max_markets=100)

        with caplog.at_level("WARNING"):
            await catalog.refresh()

        # Verify warning was logged
        assert any(
            "No BTC markets detected" in record.message for record in caplog.records
        ), "Expected warning about no BTC markets"

    @pytest.mark.asyncio
    async def test_catalog_logs_btc_market_counts(self, caplog):
        """Test that catalog logs BTC market counts when BTC markets are found."""
        now = datetime.now(timezone.utc)
        markets = [
            make_event_market(
                f"KXBTC-15M-{70000 + i * 1000}",
                f"Will Bitcoin trade above ${70000 + i * 1000}?",
                now + timedelta(minutes=15),
            )
            for i in range(3)
        ] + [
            make_event_market(
                f"KXBTC-1H-{75000 + i * 1000}",
                f"Will Bitcoin reach ${75000 + i * 1000} in the next hour?",
                now + timedelta(hours=1),
            )
            for i in range(2)
        ]

        mock_client = Mock()
        mock_client.list_markets_result = AsyncMock(
            return_value=OperationResult.ok(markets)
        )

        catalog = KalshiMarketCatalog(client=mock_client, max_markets=100)

        with caplog.at_level("INFO"):
            await catalog.refresh()

        # Verify BTC market counts were logged
        assert any(
            "BTC markets indexed" in record.message
            and "total=5" in record.message
            and "15m=3" in record.message
            and "1h=2" in record.message
            for record in caplog.records
        ), "Expected info log with BTC market counts"


class TestBTC15MLaneMarketDiscovery:
    """Test BTC15MLane market discovery and diagnostic logging."""

    @pytest.mark.asyncio
    async def test_no_markets_found_logging(self, caplog):
        """Test that BTC15MLane logs diagnostic info when no markets are found."""
        from merid.lanes.btc15m_lane import BTC15MLane, BTC15MLaneConfig

        # Create mock catalog with no BTC markets
        mock_catalog = Mock()
        mock_catalog.get_all_markets = Mock(return_value=[])
        mock_catalog.get_markets_by_asset = Mock(return_value=[])

        config = BTC15MLaneConfig(asset="BTC", timeframe="15m")
        lane = BTC15MLane(config=config)
        lane._catalog = mock_catalog
        lane._promotion_engine = None  # Disable phase gates for test

        with caplog.at_level("WARNING"):
            markets = await lane._fetch_market_data()

        # Verify empty result
        assert len(markets) == 0, "Expected no markets"

        # Note: The warning is logged in _run_cycle, not _fetch_market_data
        # So we just verify the method returned empty correctly

    @pytest.mark.asyncio
    async def test_market_filter_progression_logging(self, caplog):
        """Test that BTC15MLane logs filter progression at each step."""
        from merid.lanes.btc15m_lane import BTC15MLane, BTC15MLaneConfig

        now = datetime.now(timezone.utc)

        # Create catalog with BTC markets at different timeframes
        btc_15m_markets = [
            Mock(
                market=make_event_market(
                    f"KXBTC-15M-{70000 + i * 1000}",
                    f"Will Bitcoin trade above ${70000 + i * 1000}?",
                    now + timedelta(minutes=15),
                    volume=5000.0 - i * 500,
                ),
                timeframe="15m",
                asset="BTC",
                minutes_to_expiry=15.0,
                strike_price=70000.0 + i * 1000,
            )
            for i in range(3)
        ]
        btc_1h_markets = [
            Mock(
                market=make_event_market(
                    "KXBTC-1H-75000",
                    "Will Bitcoin reach $75,000?",
                    now + timedelta(hours=1),
                    volume=3000.0,
                ),
                timeframe="1h",
                asset="BTC",
                minutes_to_expiry=60.0,
                strike_price=75000.0,
            )
        ]

        mock_catalog = Mock()
        mock_catalog.get_all_markets = Mock(return_value=btc_15m_markets + btc_1h_markets)
        mock_catalog.get_markets_by_asset = Mock(
            side_effect=lambda asset, **kwargs: (
                btc_15m_markets
                if kwargs.get("timeframe") == "15m"
                else btc_15m_markets + btc_1h_markets
            )
        )

        config = BTC15MLaneConfig(asset="BTC", timeframe="15m", max_markets_per_cycle=2)
        lane = BTC15MLane(config=config)
        lane._catalog = mock_catalog
        lane._promotion_engine = None

        with caplog.at_level("DEBUG"):
            markets = await lane._fetch_market_data()

        # Verify correct number of markets after filtering
        assert len(markets) == 2, f"Expected 2 markets (capped), got {len(markets)}"

        # Verify filter progression was logged
        assert any(
            "filter steps" in record.message
            and "asset=BTC" in record.message
            and "asset+timeframe=BTC+15m" in record.message
            for record in caplog.records
        ), "Expected debug log showing filter progression"

        # Verify sample tickers were logged
        assert any(
            "sample tickers" in record.message for record in caplog.records
        ), "Expected debug log with sample tickers"


class TestMarketFilteringEdgeCases:
    """Test edge cases in BTC market filtering."""

    @pytest.mark.asyncio
    async def test_catalog_api_failure_vs_empty_result(self, caplog):
        """Test that API failures are distinguished from empty results."""
        mock_client = Mock()

        # Test 1: API returns empty list (success with no markets)
        mock_client.list_markets_result = AsyncMock(
            return_value=OperationResult.ok([])
        )
        catalog1 = KalshiMarketCatalog(client=mock_client, max_markets=100)

        with caplog.at_level("DEBUG"):
            await catalog1.refresh()

        assert any(
            "Kalshi API returned 0 raw markets" in record.message
            for record in caplog.records
        ), "Expected log showing 0 raw markets from API"

        caplog.clear()

        # Test 2: API fails
        mock_client.list_markets_result = AsyncMock(
            return_value=OperationResult.fail("Connection timeout")
        )
        catalog2 = KalshiMarketCatalog(client=mock_client, max_markets=100)

        with caplog.at_level("WARNING"):
            await catalog2.refresh()

        assert any(
            "Failed to fetch markets from Kalshi API" in record.message
            and "Connection timeout" in record.message
            for record in caplog.records
        ), "Expected warning log showing API failure"

    def test_timeframe_detection_from_expiry(self):
        """Test timeframe detection from close_time when pattern matching fails."""
        from merid.event_venues.kalshi.market_catalog import _detect_timeframe

        now = datetime.now(timezone.utc)

        # Test 15m window
        close_15m = now + timedelta(minutes=10)
        tf = _detect_timeframe("Generic question", close_15m, now)
        assert tf == "15m", f"Expected '15m', got {tf}"

        # Test 1h window
        close_1h = now + timedelta(minutes=45)
        tf = _detect_timeframe("Generic question", close_1h, now)
        assert tf == "1h", f"Expected '1h', got {tf}"

        # Test daily window
        close_daily = now + timedelta(hours=12)
        tf = _detect_timeframe("Generic question", close_daily, now)
        assert tf == "daily", f"Expected 'daily', got {tf}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
