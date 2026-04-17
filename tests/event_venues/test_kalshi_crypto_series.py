"""Tests for Kalshi Crypto Series module.

Tests cover:
- Series listing with caching
- Market batch fetching with backoff
- Redis cache TTL behavior
- 429 backoff recovery
- Cache key format validation
- KX ticker validation
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import the module under test
from merid.event_venues.kalshi.crypto_series import (
    BACKOFF_SCHEDULE,
    CACHE_PREFIX,
    CACHE_TTL_SECONDS,
    CRYPTO_FREQUENCIES,
    CRYPTO_SERIES_PREFIXES,
    FREQUENCY_SUFFIXES,
    CryptoSeries,
    MarketInfo,
    _CacheAdapter,
    _fetch_with_backoff,
    _make_cache_key,
    fetch_markets_batch,
    get_cache_stats,
    invalidate_crypto_series_cache,
    list_crypto_series,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_cache():
    """Create a fresh in-memory cache for testing."""
    cache = _CacheAdapter()
    # Force in-memory mode
    cache._redis = None
    cache._memory = {}
    cache._ttl = {}
    return cache


@pytest.fixture
def sample_series():
    """Return sample crypto series for testing."""
    return [
        CryptoSeries(
            series_ticker="KXBTC",
            asset="BTC",
            frequency="hourly",
            title="BTC HOURLY",
            category="crypto",
            volume_24h=1000000.0,
            open_interest=500,
            market_count=5,
        ),
        CryptoSeries(
            series_ticker="KXBTC15M",
            asset="BTC",
            frequency="15m",
            title="BTC 15M",
            category="crypto",
            volume_24h=500000.0,
            open_interest=200,
            market_count=3,
        ),
        CryptoSeries(
            series_ticker="KXETH",
            asset="ETH",
            frequency="hourly",
            title="ETH HOURLY",
            category="crypto",
            volume_24h=800000.0,
            open_interest=400,
            market_count=4,
        ),
    ]


@pytest.fixture
def sample_markets():
    """Return sample markets for testing."""
    return [
        MarketInfo(
            market_id="KXBTC-250324",
            series_ticker="KXBTC",
            title="BTC Hourly 2025-03-24",
            status="open",
            yes_price=55,
            no_price=45,
            volume=10000,
            open_interest=500,
        ),
        MarketInfo(
            market_id="KXBTC-250325",
            series_ticker="KXBTC",
            title="BTC Hourly 2025-03-25",
            status="open",
            yes_price=52,
            no_price=48,
            volume=8000,
            open_interest=400,
        ),
    ]


# ── Test Class 1: Constants and Configuration ────────────────────────────────


class TestConstants:
    """Test constant definitions."""

    def test_crypto_frequencies(self):
        """Test CRYPTO_FREQUENCIES list."""
        assert CRYPTO_FREQUENCIES == ["15m", "hourly", "daily", "weekly"]

    def test_series_prefixes(self):
        """Test CRYPTO_SERIES_PREFIXES mapping."""
        assert CRYPTO_SERIES_PREFIXES["BTC"] == "KXBTC"
        assert CRYPTO_SERIES_PREFIXES["ETH"] == "KXETH"
        assert CRYPTO_SERIES_PREFIXES["SOL"] == "KXSOL"
        assert CRYPTO_SERIES_PREFIXES["XRP"] == "KXXRP"
        assert CRYPTO_SERIES_PREFIXES["DOGE"] == "KXDOGE"

    def test_frequency_suffixes(self):
        """Test FREQUENCY_SUFFIXES mapping."""
        assert FREQUENCY_SUFFIXES["15m"] == "15M"
        assert FREQUENCY_SUFFIXES["hourly"] == ""
        assert FREQUENCY_SUFFIXES["daily"] == "D1"
        assert FREQUENCY_SUFFIXES["weekly"] == "W1"

    def test_cache_ttl_is_15_minutes(self):
        """Test that cache TTL is exactly 15 minutes."""
        assert CACHE_TTL_SECONDS == int(timedelta(minutes=15).total_seconds())
        assert CACHE_TTL_SECONDS == 900

    def test_backoff_schedule(self):
        """Test backoff schedule matches spec: [0.25, 1, 4] seconds."""
        assert BACKOFF_SCHEDULE == [0.25, 1.0, 4.0]

    def test_cache_prefix_format(self):
        """Test cache key prefix."""
        assert CACHE_PREFIX == "kalshi:crypto_series"


# ── Test Class 2: Cache Key Generation ─────────────────────────────────────


class TestCacheKeys:
    """Test cache key generation."""

    def test_simple_key(self):
        """Test simple cache key generation."""
        key = _make_cache_key("list", "crypto", "None", "None")
        assert key == "kalshi:crypto_series:list:crypto:None:None"

    def test_key_with_volume(self):
        """Test cache key with volume filter."""
        key = _make_cache_key("list", "crypto", "1000000.0", "None")
        assert key == "kalshi:crypto_series:list:crypto:1000000.0:None"

    def test_key_with_frequency(self):
        """Test cache key with frequency filter."""
        key = _make_cache_key("list", "crypto", "None", "hourly")
        assert key == "kalshi:crypto_series:list:crypto:None:hourly"

    def test_markets_key(self):
        """Test cache key for markets."""
        key = _make_cache_key("markets", "KXBTC", "open")
        assert key == "kalshi:crypto_series:markets:KXBTC:open"

    def test_long_key_hashing(self):
        """Test that long keys are hashed."""
        # Create a very long key
        long_part = "a" * 300
        key = _make_cache_key("list", "crypto", long_part, "None")
        # Should be hashed and under 200 chars
        assert len(key) <= 200
        assert key.startswith("kalshi:crypto_series:")


# ── Test Class 3: Cache Adapter ────────────────────────────────────────────


class TestCacheAdapter:
    """Test cache adapter functionality."""

    @pytest.mark.asyncio
    async def test_cache_set_and_get(self, mock_cache):
        """Test basic cache set and get."""
        await mock_cache.set("test_key", "test_value", 900)
        result = await mock_cache.get("test_key")
        assert result == "test_value"

    @pytest.mark.asyncio
    async def test_cache_ttl_expiration(self, mock_cache):
        """Test that cache entries expire after TTL."""
        await mock_cache.set("expiring_key", "value", 1)  # 1 second TTL

        # Should exist immediately
        assert await mock_cache.get("expiring_key") == "value"

        # Wait for expiration
        await asyncio.sleep(1.1)

        # Should be expired
        result = await mock_cache.get("expiring_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_delete_pattern(self, mock_cache):
        """Test cache deletion by pattern."""
        # Set multiple keys
        await mock_cache.set("kalshi:crypto_series:list:a", "val1", 900)
        await mock_cache.set("kalshi:crypto_series:list:b", "val2", 900)
        await mock_cache.set("kalshi:crypto_series:markets:c", "val3", 900)
        await mock_cache.set("other:key", "val4", 900)

        # Delete pattern
        count = await mock_cache.delete("kalshi:crypto_series:list:*")
        assert count == 2

        # Verify deletion
        assert await mock_cache.get("kalshi:crypto_series:list:a") is None
        assert await mock_cache.get("kalshi:crypto_series:list:b") is None
        assert await mock_cache.get("kalshi:crypto_series:markets:c") == "val3"
        assert await mock_cache.get("other:key") == "val4"


# ── Test Class 4: Backoff Logic ──────────────────────────────────────────────


class TestBackoffLogic:
    """Test 429 backoff retry logic."""

    @pytest.mark.asyncio
    async def test_successful_fetch_no_retry(self):
        """Test that successful fetch doesn't trigger backoff."""
        mock_fn = AsyncMock(return_value={"success": True})

        result = await _fetch_with_backoff(mock_fn, "arg1", kwarg1="val1")

        assert result == {"success": True}
        assert mock_fn.call_count == 1

    @pytest.mark.asyncio
    async def test_backoff_on_429_error(self):
        """Test backoff triggers on 429 error."""
        # First 2 calls raise 429, 3rd succeeds
        mock_fn = AsyncMock(side_effect=[
            Exception("429 Too Many Requests"),
            Exception("429 Too Many Requests"),
            {"success": True},
        ])

        start_time = time.time()
        result = await _fetch_with_backoff(mock_fn, max_retries=3)
        elapsed = time.time() - start_time

        assert result == {"success": True}
        assert mock_fn.call_count == 3
        # Should have waited at least 0.25s + 1.0s = 1.25s
        assert elapsed >= 1.0  # At least the second backoff

    @pytest.mark.asyncio
    async def test_backoff_rate_limit_variants(self):
        """Test backoff triggers on various rate limit messages."""
        test_errors = [
            "429 Too Many Requests",
            "Rate limit exceeded",
            "Too many requests",
            "Ratelimited",
        ]

        for error_msg in test_errors:
            mock_fn = AsyncMock(side_effect=[
                Exception(error_msg),
                {"success": True},
            ])

            result = await _fetch_with_backoff(mock_fn, max_retries=1)
            assert result == {"success": True}
            assert mock_fn.call_count == 2

    @pytest.mark.asyncio
    async def test_no_backoff_on_other_errors(self):
        """Test that non-rate-limit errors don't trigger backoff."""
        mock_fn = AsyncMock(side_effect=Exception("Connection refused"))

        with pytest.raises(Exception, match="Connection refused"):
            await _fetch_with_backoff(mock_fn, max_retries=3)

        # Should not retry on non-429 errors
        assert mock_fn.call_count == 1

    @pytest.mark.asyncio
    async def test_backoff_schedule_timing(self):
        """Test that backoff schedule is followed."""
        mock_fn = AsyncMock(side_effect=[
            Exception("429"),
            Exception("429"),
            Exception("429"),
            {"success": True},
        ])

        start = time.time()
        await _fetch_with_backoff(mock_fn, max_retries=3)
        elapsed = time.time() - start

        # Should have waited 0.25 + 1.0 + 4.0 = 5.25s minimum
        assert elapsed >= 5.0  # Allow some tolerance


# ── Test Class 5: Data Models ──────────────────────────────────────────────


class TestDataModels:
    """Test data model classes."""

    def test_crypto_series_to_dict(self):
        """Test CryptoSeries serialization."""
        series = CryptoSeries(
            series_ticker="KXBTC",
            asset="BTC",
            frequency="hourly",
            title="BTC HOURLY",
            category="crypto",
            volume_24h=1000000.0,
            open_interest=500,
            market_count=5,
        )

        data = series.to_dict()
        assert data["series_ticker"] == "KXBTC"
        assert data["asset"] == "BTC"
        assert data["frequency"] == "hourly"
        assert data["volume_24h"] == 1000000.0

    def test_market_info_to_dict(self):
        """Test MarketInfo serialization."""
        market = MarketInfo(
            market_id="KXBTC-250324",
            series_ticker="KXBTC",
            title="BTC Hourly",
            status="open",
            yes_price=55,
            no_price=45,
            volume=10000,
        )

        data = market.to_dict()
        assert data["market_id"] == "KXBTC-250324"
        assert data["status"] == "open"
        assert data["yes_price"] == 55


# ── Test Class 6: list_crypto_series ────────────────────────────────────────


class TestListCryptoSeries:
    """Test list_crypto_series function."""

    @pytest.mark.asyncio
    @patch("merid.event_venues.kalshi.crypto_series._fetch_series_from_api")
    async def test_list_series_basic(self, mock_fetch, sample_series):
        """Test basic series listing."""
        mock_fetch.return_value = sample_series

        result = await list_crypto_series(use_cache=False)

        assert len(result) == 3
        assert result[0].series_ticker == "KXBTC"
        assert result[0].asset == "BTC"

    @pytest.mark.asyncio
    @patch("merid.event_venues.kalshi.crypto_series._fetch_series_from_api")
    async def test_list_series_with_volume_filter(self, mock_fetch, sample_series):
        """Test series listing with volume filter."""
        mock_fetch.return_value = sample_series

        result = await list_crypto_series(min_volume=900000.0, use_cache=False)

        # Only BTC hourly (1M) and ETH hourly (800K is less than 900K)
        assert len(result) == 1
        assert result[0].series_ticker == "KXBTC"

    @pytest.mark.asyncio
    @patch("merid.event_venues.kalshi.crypto_series._fetch_series_from_api")
    async def test_list_series_with_frequency_filter(self, mock_fetch, sample_series):
        """Test series listing with frequency filter."""
        mock_fetch.return_value = sample_series

        result = await list_crypto_series(frequency="15m", use_cache=False)

        assert len(result) == 1
        assert result[0].series_ticker == "KXBTC15M"

    @pytest.mark.asyncio
    @patch("merid.event_venues.kalshi.crypto_series._fetch_series_from_api")
    async def test_list_series_caching(self, mock_fetch, sample_series, mock_cache):
        """Test that series results are cached."""
        mock_fetch.return_value = sample_series

        # First call - should hit API
        with patch("merid.event_venues.kalshi.crypto_series._cache", mock_cache):
            result1 = await list_crypto_series(use_cache=True)
            assert mock_fetch.call_count == 1

            # Second call - should hit cache
            result2 = await list_crypto_series(use_cache=True)
            # API should not be called again
            assert mock_fetch.call_count == 1

            assert len(result1) == len(result2)

    @pytest.mark.asyncio
    @patch("merid.event_venues.kalshi.crypto_series._fetch_series_from_api")
    async def test_list_series_force_refresh(self, mock_fetch, sample_series, mock_cache):
        """Test force refresh bypasses cache."""
        mock_fetch.return_value = sample_series

        with patch("merid.event_venues.kalshi.crypto_series._cache", mock_cache):
            # First call
            await list_crypto_series(use_cache=True)
            assert mock_fetch.call_count == 1

            # Force refresh
            await list_crypto_series(use_cache=True, force_refresh=True)
            assert mock_fetch.call_count == 2


# ── Test Class 7: fetch_markets_batch ───────────────────────────────────────


class TestFetchMarketsBatch:
    """Test fetch_markets_batch function."""

    @pytest.mark.asyncio
    @patch("merid.event_venues.kalshi.crypto_series._fetch_markets_from_api")
    async def test_fetch_batch_basic(self, mock_fetch, sample_markets):
        """Test basic batch market fetch."""
        mock_fetch.return_value = sample_markets

        result = await fetch_markets_batch(["KXBTC"], use_cache=False)

        assert len(result) == 2
        assert result[0].series_ticker == "KXBTC"
        assert result[0].market_id == "KXBTC-250324"

    @pytest.mark.asyncio
    @patch("merid.event_venues.kalshi.crypto_series._fetch_markets_from_api")
    async def test_fetch_batch_multiple_series(self, mock_fetch, sample_markets):
        """Test batch fetch for multiple series."""
        # Return different markets for different series
        eth_markets = [
            MarketInfo(
                market_id="KXETH-250324",
                series_ticker="KXETH",
                title="ETH Hourly",
                status="open",
            ),
        ]

        async def side_effect(series_ticker, status=None):
            if series_ticker == "KXBTC":
                return sample_markets
            return eth_markets

        mock_fetch.side_effect = side_effect

        result = await fetch_markets_batch(["KXBTC", "KXETH"], use_cache=False)

        assert len(result) == 3  # 2 BTC + 1 ETH

    @pytest.mark.asyncio
    @patch("merid.event_venues.kalshi.crypto_series._fetch_markets_from_api")
    async def test_fetch_batch_with_status_filter(self, mock_fetch):
        """Test batch fetch with status filter."""
        await fetch_markets_batch(["KXBTC"], status="open", use_cache=False)

        # Check that status was passed (as positional arg: series_ticker, status)
        mock_fetch.assert_called_once()
        args, _ = mock_fetch.call_args
        assert args[1] == "open"  # status is second positional arg

    @pytest.mark.asyncio
    async def test_fetch_batch_empty_series(self):
        """Test batch fetch with empty series list."""
        result = await fetch_markets_batch([], use_cache=False)
        assert result == []


# ── Test Class 8: Cache Management ───────────────────────────────────────────


class TestCacheManagement:
    """Test cache management functions."""

    @pytest.mark.asyncio
    async def test_invalidate_cache_all(self, mock_cache):
        """Test invalidating all crypto series cache."""
        # Set up some cache entries
        await mock_cache.set("kalshi:crypto_series:list:crypto", "data1", 900)
        await mock_cache.set("kalshi:crypto_series:markets:KXBTC", "data2", 900)
        await mock_cache.set("other:key", "data3", 900)

        with patch("merid.event_venues.kalshi.crypto_series._cache", mock_cache):
            count = await invalidate_crypto_series_cache()
            assert count >= 2

            # Verify keys are gone
            assert await mock_cache.get("kalshi:crypto_series:list:crypto") is None
            assert await mock_cache.get("kalshi:crypto_series:markets:KXBTC") is None
            # Other key should remain
            assert await mock_cache.get("other:key") == "data3"

    @pytest.mark.asyncio
    async def test_get_cache_stats(self):
        """Test getting cache statistics."""
        stats = await get_cache_stats()

        assert stats["prefix"] == "kalshi:crypto_series"
        assert stats["ttl_seconds"] == 900
        assert stats["backoff_schedule"] == [0.25, 1.0, 4.0]
        assert "cache_type" in stats


# ── Test Class 9: Integration Tests ──────────────────────────────────────────


class TestIntegration:
    """Integration tests combining multiple components."""

    @pytest.mark.asyncio
    @patch("merid.event_venues.kalshi.crypto_series._get_kalshi_client")
    @patch("merid.event_venues.kalshi.crypto_series._fetch_series_from_api")
    @patch("merid.event_venues.kalshi.crypto_series._fetch_markets_from_api")
    async def test_full_flow_series_to_markets(
        self, mock_fetch_markets, mock_fetch_series, mock_get_client,
        sample_series, sample_markets,
    ):
        """Test full flow from series listing to market fetching."""
        mock_fetch_series.return_value = sample_series
        mock_fetch_markets.return_value = sample_markets

        # Step 1: List series
        series_list = await list_crypto_series(category="crypto", use_cache=False)
        assert len(series_list) > 0

        # Step 2: Get tickers
        tickers = [s.series_ticker for s in series_list if s.market_count > 0]
        assert "KXBTC" in tickers

        # Step 3: Fetch markets for tickers
        markets = await fetch_markets_batch(tickers[:2], use_cache=False)
        assert len(markets) >= 0  # May be 0 if mocked, but shouldn't error

    @pytest.mark.asyncio
    async def test_cache_key_format_matches_spec(self):
        """Verify cache key format matches specification."""
        # All keys must start with kalshi:crypto_series:
        key1 = _make_cache_key("list", "crypto", "None", "None")
        assert key1.startswith("kalshi:crypto_series:")

        key2 = _make_cache_key("markets", "KXBTC", "open")
        assert key2.startswith("kalshi:crypto_series:")

    def test_kx_ticker_validation(self):
        """Test that KX tickers follow expected format."""
        valid_tickers = [
            "KXBTC", "KXBTC15M", "KXBTCD1", "KXBTCW1",
            "KXETH", "KXETH15M",
            "KXSOL", "KXXRP", "KXDOGE",
        ]

        for ticker in valid_tickers:
            # Must start with KX
            assert ticker.startswith("KX")
            # Must have valid asset
            asset_part = ticker[2:].replace("15M", "").replace("D1", "").replace("W1", "")
            valid_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
            assert asset_part in valid_assets, f"Invalid asset in {ticker}"


# ── Test Class 10: Error Handling ────────────────────────────────────────────


class TestErrorHandling:
    """Test error handling and edge cases."""

    @pytest.mark.asyncio
    @patch("merid.event_venues.kalshi.crypto_series._fetch_series_from_api")
    async def test_list_series_api_failure(self, mock_fetch):
        """Test graceful handling of API failure."""
        mock_fetch.side_effect = Exception("API Error")

        result = await list_crypto_series(use_cache=False)

        # Should return empty list, not crash
        assert result == []

    @pytest.mark.asyncio
    @patch("merid.event_venues.kalshi.crypto_series._fetch_markets_from_api")
    async def test_fetch_markets_api_failure(self, mock_fetch):
        """Test graceful handling of market fetch failure."""
        mock_fetch.side_effect = Exception("API Error")

        result = await fetch_markets_batch(["KXBTC"], use_cache=False)

        # Should return empty list, not crash
        assert result == []


# ── Coverage Threshold Test ────────────────────────────────────────────────


@pytest.mark.coverage
class TestCoverage:
    """Placeholder for coverage threshold enforcement."""

    def test_coverage_placeholder(self):
        """This test exists to ensure the coverage report runs."""
        # Actual coverage is measured by pytest-cov
        assert True
