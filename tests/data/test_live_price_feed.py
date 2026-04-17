"""Tests for data/live_price_feed.py."""
import time
import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock, patch, AsyncMock, MagicMock

import httpx
import pytest

from data.live_price_feed import (
    PriceData, LivePriceFeed, get_live_price_feed, _live_price_feed,
    check_price_source_health, test_public_price_sources
)


class TestPriceData:
    """Test PriceData dataclass."""

    def test_creation(self):
        """Test PriceData creation with USD pairs (Kalshi BRTI alignment)."""
        timestamp = datetime.now(timezone.utc)
        price_data = PriceData(
            symbol="BTC/USD",  # USD pairs for Kalshi BRTI
            price=50000.0,
            bid=49990.0,
            ask=50010.0,
            volume_24h=1000000.0,
            change_24h_pct=5.0,
            high_24h=51000.0,
            low_24h=49000.0,
            timestamp=timestamp,
            exchange="kraken_public"
        )
        assert price_data.symbol == "BTC/USD"
        assert price_data.price == 50000.0
        assert price_data.bid == 49990.0
        assert price_data.ask == 50010.0
        assert price_data.volume_24h == 1000000.0
        assert price_data.change_24h_pct == 5.0
        assert price_data.timestamp == timestamp
        assert price_data.exchange == "kraken_public"


class TestLivePriceFeedInitialization:
    """Test LivePriceFeed initialization."""

    def test_default_initialization(self):
        """Test default feed initialization with USD pairs for Kalshi."""
        with patch('data.live_price_feed.get_network_client') as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            # Updated to USD pairs for Kalshi BRTI alignment
            assert feed.symbols == ['BTC/USD', 'ETH/USD', 'SOL/USD', 'XRP/USD', 'DOGE/USD']
            assert feed.update_interval == 1.0
            assert feed.max_retries == 3
            # Extended exchange priority with binance/bybit/okx
            assert feed.exchange_priority == ['kraken', 'coinbase', 'gemini', 'binance', 'bybit', 'okx']
            assert feed.running is False
            
            # Verify public API pair mappings
            assert feed._COINBASE_PUBLIC_PAIRS["BTC/USD"] == "BTC-USD"
            assert feed._COINBASE_PUBLIC_PAIRS["ETH/USD"] == "ETH-USD"
            assert feed._KRAKEN_PUBLIC_PAIRS["BTC/USD"] == "XXBTZUSD"
            assert feed._KRAKEN_PUBLIC_PAIRS["ETH/USD"] == "XETHZUSD"

    def test_custom_symbols(self):
        """Test initialization with custom symbols."""
        with patch('data.live_price_feed.get_network_client') as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed(symbols=['BTC/USD', 'ETH/USD'])
            
            assert feed.symbols == ['BTC/USD', 'ETH/USD']

    def test_initial_state(self):
        """Test initial state of feed."""
        with patch('data.live_price_feed.get_network_client') as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            assert feed.price_cache == {}
            assert feed.subscribers == []
            assert feed.exchanges == {}
            assert feed.exchange_failures == {}


class TestLivePriceFeedSubscription:
    """Test LivePriceFeed subscription methods."""

    def test_subscribe(self):
        """Test subscribing to price updates."""
        with patch('data.live_price_feed.get_network_client') as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            callback = Mock()
            feed.subscribe(callback)
            
            assert callback in feed.subscribers
            assert len(feed.subscribers) == 1

    def test_unsubscribe(self):
        """Test unsubscribing from price updates."""
        with patch('data.live_price_feed.get_network_client') as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            callback = Mock()
            feed.subscribe(callback)
            feed.unsubscribe(callback)
            
            assert callback not in feed.subscribers
            assert len(feed.subscribers) == 0

    def test_unsubscribe_nonexistent(self):
        """Test unsubscribing callback that was never subscribed."""
        with patch('data.live_price_feed.get_network_client') as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            callback = Mock()
            feed.unsubscribe(callback)  # Should not raise
            
            assert len(feed.subscribers) == 0


class TestLivePriceFeedPriceCache:
    """Test LivePriceFeed price caching."""

    def test_get_current_price(self):
        """Test getting current cached price with USD pairs."""
        with patch('data.live_price_feed.get_network_client') as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            price_data = PriceData(
                symbol="BTC/USD",
                price=50000.0,
                bid=49990.0,
                ask=50010.0,
                volume_24h=1000000.0,
                change_24h_pct=5.0,
                high_24h=51000.0,
                low_24h=49000.0,
                timestamp=datetime.now(timezone.utc),
                exchange="coinbase_public"
            )
            feed.price_cache["BTC/USD"] = price_data
            
            result = feed.get_current_price("BTC/USD")
            
            assert result == price_data

    def test_get_current_price_missing(self):
        """Test getting price for missing symbol."""
        with patch('data.live_price_feed.get_network_client') as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            result = feed.get_current_price("BTC/USD")
            
            assert result is None

    def test_get_price_alias(self):
        """Test get_price alias for get_current_price."""
        with patch('data.live_price_feed.get_network_client') as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            price_data = PriceData(
                symbol="BTC/USD",
                price=50000.0,
                bid=49990.0,
                ask=50010.0,
                volume_24h=1000000.0,
                change_24h_pct=5.0,
                high_24h=51000.0,
                low_24h=49000.0,
                timestamp=datetime.now(timezone.utc),
                exchange="coinbase_public"
            )
            feed.price_cache["BTC/USD"] = price_data
            
            result = feed.get_price("BTC/USD")
            
            assert result == price_data

    def test_get_all_prices(self):
        """Test getting all cached prices."""
        with patch('data.live_price_feed.get_network_client') as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            price_data1 = PriceData(
                symbol="BTC/USD", price=50000.0, bid=49990.0, ask=50010.0,
                volume_24h=1000000.0, change_24h_pct=5.0,
                high_24h=51000.0, low_24h=49000.0,
                timestamp=datetime.now(timezone.utc), exchange="coinbase_public"
            )
            price_data2 = PriceData(
                symbol="ETH/USD", price=3000.0, bid=2995.0, ask=3005.0,
                volume_24h=500000.0, change_24h_pct=3.0,
                high_24h=3100.0, low_24h=2900.0,
                timestamp=datetime.now(timezone.utc), exchange="kraken_public"
            )
            feed.price_cache["BTC/USD"] = price_data1
            feed.price_cache["ETH/USD"] = price_data2
            
            result = feed.get_all_prices()
            
            assert len(result) == 2
            assert result["BTC/USD"] == price_data1
            assert result["ETH/USD"] == price_data2


class TestLivePriceFeedCircuitBreaker:
    """Test LivePriceFeed circuit breaker logic."""

    def test_circuit_breaker_inactive(self):
        """Test circuit breaker is inactive below threshold."""
        with patch('data.live_price_feed.get_network_client') as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            feed.exchange_failures["kraken"] = 5  # Below threshold of 10
            
            assert feed._is_circuit_breaker_active("kraken") is False

    def test_circuit_breaker_active(self):
        """Test circuit breaker is active at threshold."""
        with patch('data.live_price_feed.get_network_client') as mock_net:
            import time
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            feed.exchange_failures["kraken"] = 10  # At threshold
            # Set last success to very recent time so circuit breaker doesn't reset
            feed.last_successful_fetch["kraken"] = time.time() - 10  # 10 seconds ago
            
            assert feed._is_circuit_breaker_active("kraken") is True

    def test_circuit_breaker_reset(self):
        """Test circuit breaker resets after time."""
        with patch('data.live_price_feed.get_network_client') as mock_net:
            import time
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            feed.exchange_failures["kraken"] = 10
            feed.last_successful_fetch["kraken"] = time.time() - 400  # > 5 min ago
            
            assert feed._is_circuit_breaker_active("kraken") is False
            assert feed.exchange_failures["kraken"] == 0  # Reset


class TestLivePriceFeedStats:
    """Test LivePriceFeed statistics."""

    def test_get_stats(self):
        """Test getting feed statistics."""
        with patch('data.live_price_feed.get_network_client') as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            feed.symbols = ['BTC/USDT', 'ETH/USDT']
            feed.subscribers = [Mock(), Mock()]
            feed.price_cache = {"BTC/USDT": Mock()}
            feed.exchange_failures["kraken"] = 2
            
            stats = feed.get_stats()
            
            assert stats["running"] is False
            assert stats["symbols_tracked"] == 2
            assert stats["subscribers"] == 2
            assert stats["cached_prices"] == 1
            assert stats["update_interval"] == 1.0
            assert "exchange_health" in stats


class TestLivePriceFeedControl:
    """Test LivePriceFeed control methods."""

    def test_stop_streaming(self):
        """Test stopping price streaming."""
        with patch('data.live_price_feed.get_network_client') as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            feed.running = True
            feed.stop_streaming()
            
            assert feed.running is False


class TestGetLivePriceFeed:
    """Test get_live_price_feed function."""

    def setup_method(self):
        """Reset singleton before each test."""
        global _live_price_feed
        import data.live_price_feed as lpf
        lpf._live_price_feed = None

    def test_singleton(self):
        """Test get_live_price_feed returns singleton."""
        with patch('data.live_price_feed.get_network_client') as mock_net:
            mock_net.return_value = Mock()
            feed1 = get_live_price_feed()
            feed2 = get_live_price_feed()
            
            assert feed1 is feed2


class TestPmFeedHealthSnapshot:
    """get_pm_feed_health_snapshot — stream tick age vs PM/cache TTL."""

    def test_warming_without_tick_not_flagged_unhealthy(self):
        with patch("data.live_price_feed.get_network_client") as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            feed.running = True
            feed._stream_start_monotonic = time.monotonic()
            snap = feed.get_pm_feed_health_snapshot(["BTC"])
            assert snap["live_feed_warming"] is True
            pa = snap["per_asset"]["BTC/USD"]
            assert pa["warming"] is True
            assert pa["live_price_feed_healthy"] is True

    def test_stale_stream_tick_unhealthy(self):
        with patch("data.live_price_feed.get_network_client") as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            feed.running = True
            feed._stream_start_monotonic = time.monotonic() - 500.0
            stale = time.monotonic() - 300.0
            feed._last_tick_monotonic["BTC/USD"] = stale
            feed._last_global_tick_monotonic = stale
            snap = feed.get_pm_feed_health_snapshot(["BTC"])
            pa = snap["per_asset"]["BTC/USD"]
            assert pa["live_price_feed_healthy"] is False
            assert pa["last_stream_tick_age_seconds"] is not None
            assert pa["last_stream_tick_age_seconds"] > 120.0


class TestCoinbasePublicAPI:
    """Test Coinbase public API price fetching."""

    @pytest.mark.asyncio
    async def test_fetch_from_coinbase_public_success(self):
        """Test successful fetch from Coinbase public API."""
        with patch("data.live_price_feed.get_network_client") as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            # Mock successful API response
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": {"base": "BTC", "currency": "USD", "amount": "65000.00"}
            }
            mock_response.raise_for_status = Mock()
            
            with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
                result = await feed._fetch_from_coinbase_public("BTC/USD")
                
                assert result is not None
                assert result.symbol == "BTC/USD"
                assert result.price == 65000.00
                assert result.exchange == "coinbase_public"
                assert result.bid == 65000.00 * 0.999  # Estimated
                assert result.ask == 65000.00 * 1.001  # Estimated

    @pytest.mark.asyncio
    async def test_fetch_from_coinbase_public_rate_limited(self):
        """Test Coinbase public API rate limiting."""
        with patch("data.live_price_feed.get_network_client") as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            # Mock rate limit response
            mock_response = Mock()
            mock_response.status_code = 429
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Rate limited", request=Mock(), response=mock_response
            )
            
            with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
                with patch("data.live_price_feed.logger") as mock_logger:
                    result = await feed._fetch_from_coinbase_public("BTC/USD")
                    
                    assert result is None

    @pytest.mark.asyncio
    async def test_fetch_from_coinbase_public_invalid_price(self):
        """Test handling of invalid/zero price from Coinbase."""
        with patch("data.live_price_feed.get_network_client") as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            # Mock invalid price response
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": {"base": "BTC", "currency": "USD", "amount": "0.00"}
            }
            mock_response.raise_for_status = Mock()
            
            with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
                result = await feed._fetch_from_coinbase_public("BTC/USD")
                
                assert result is None

    @pytest.mark.asyncio
    async def test_fetch_from_coinbase_public_unmapped_symbol(self):
        """Test fetch attempt for unmapped symbol."""
        with patch("data.live_price_feed.get_network_client") as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            result = await feed._fetch_from_coinbase_public("UNKNOWN/USD")
            
            assert result is None


class TestKrakenPublicAPI:
    """Test Kraken public API price fetching."""

    @pytest.mark.asyncio
    async def test_fetch_from_kraken_public_success(self):
        """Test successful fetch from Kraken public API."""
        with patch("data.live_price_feed.get_network_client") as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            # Mock successful Kraken API response
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "error": [],
                "result": {
                    "XXBTZUSD": {
                        "c": ["64000.0", "1.5"],  # last trade [price, volume]
                        "b": ["63990.0", "5.0"],  # best bid [price, volume]
                        "a": ["64010.0", "3.0"],  # best ask [price, volume]
                        "v": ["1000.0", "5000.0"],  # volume [today, 24h]
                        "p": ["63500.0", "63800.0"],  # VWAP [today, 24h]
                        "l": ["63000.0", "62500.0"],  # low [today, 24h]
                        "h": ["64500.0", "65000.0"],  # high [today, 24h]
                        "o": "63000.0",  # opening price
                    }
                }
            }
            mock_response.raise_for_status = Mock()
            
            with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
                result = await feed._fetch_from_kraken_public("BTC/USD")
                
                assert result is not None
                assert result.symbol == "BTC/USD"
                assert result.price == 64000.0
                assert result.exchange == "kraken_public"
                assert result.bid == 63990.0
                assert result.ask == 64010.0
                assert result.volume_24h == 5000.0

    @pytest.mark.asyncio
    async def test_fetch_from_kraken_public_error_response(self):
        """Test Kraken API error handling."""
        with patch("data.live_price_feed.get_network_client") as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            # Mock error response
            mock_response = Mock()
            mock_response.status_code = 200  # HTTP OK but API returns error
            mock_response.json.return_value = {
                "error": ["EGeneral:Invalid arguments"],
                "result": {}
            }
            mock_response.raise_for_status = Mock()
            
            with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
                result = await feed._fetch_from_kraken_public("BTC/USD")
                
                assert result is None

    @pytest.mark.asyncio
    async def test_fetch_from_kraken_public_rate_limited(self):
        """Test Kraken public API rate limiting."""
        with patch("data.live_price_feed.get_network_client") as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            # Mock rate limit response
            mock_response = Mock()
            mock_response.status_code = 429
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Rate limited", request=Mock(), response=mock_response
            )
            
            with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
                result = await feed._fetch_from_kraken_public("BTC/USD")
                
                assert result is None


class TestPriceSourceHealthCheck:
    """Test price source health check functionality."""

    @pytest.mark.asyncio
    async def test_check_price_source_health_all_healthy(self):
        """Test health check when all sources are healthy."""
        with patch("data.live_price_feed.get_network_client") as mock_net:
            mock_net.return_value = Mock()
            
            # Mock all successful responses
            mock_cb_response = Mock()
            mock_cb_response.status_code = 200
            mock_cb_response.json.return_value = {
                "data": {"base": "BTC", "currency": "USD", "amount": "65000.00"}
            }
            mock_cb_response.raise_for_status = Mock()
            
            async def mock_get(*args, **kwargs):
                return mock_cb_response
            
            with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=mock_get):
                result = await check_price_source_health()
                
                assert result["healthy"] is True
                assert result["summary"]["healthy_assets"] == 5
                assert "coinbase_public" in result["summary"]["sources_used"]

    @pytest.mark.asyncio
    async def test_check_price_source_health_fallback_to_kraken(self):
        """Test health check fallback when Coinbase fails."""
        with patch("data.live_price_feed.get_network_client") as mock_net:
            mock_net.return_value = Mock()
            
            # Create proper mock responses
            cb_error_response = Mock()
            cb_error_response.status_code = 429
            cb_error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Rate limited", request=Mock(), response=cb_error_response
            )
            
            kraken_response = Mock()
            kraken_response.status_code = 200
            kraken_response.json.return_value = {
                "error": [],
                "result": {
                    "XXBTZUSD": {
                        "c": ["64000.0", "1.5"],
                        "b": ["63990.0", "5.0"],
                        "a": ["64010.0", "3.0"],
                        "v": ["1000.0", "5000.0"],
                        "p": ["63500.0", "63800.0"],
                        "l": ["63000.0", "62500.0"],
                        "h": ["64500.0", "65000.0"],
                        "o": "63000.0",
                    },
                    "XETHZUSD": {
                        "c": ["3500.0", "1.5"],
                        "b": ["3490.0", "5.0"],
                        "a": ["3510.0", "3.0"],
                        "v": ["1000.0", "5000.0"],
                        "p": ["3400.0", "3450.0"],
                        "l": ["3300.0", "3200.0"],
                        "h": ["3600.0", "3700.0"],
                        "o": "3300.0",
                    },
                    "SOLUSD": {
                        "c": ["150.0", "1.5"],
                        "b": ["149.0", "5.0"],
                        "a": ["151.0", "3.0"],
                        "v": ["1000.0", "5000.0"],
                        "p": ["140.0", "145.0"],
                        "l": ["130.0", "120.0"],
                        "h": ["160.0", "170.0"],
                        "o": "130.0",
                    },
                    "XXRPZUSD": {
                        "c": ["0.60", "1.5"],
                        "b": ["0.59", "5.0"],
                        "a": ["0.61", "3.0"],
                        "v": ["1000.0", "5000.0"],
                        "p": ["0.55", "0.58"],
                        "l": ["0.50", "0.45"],
                        "h": ["0.65", "0.70"],
                        "o": "0.50",
                    },
                    "XDGUSD": {
                        "c": ["0.15", "1.5"],
                        "b": ["0.14", "5.0"],
                        "a": ["0.16", "3.0"],
                        "v": ["1000.0", "5000.0"],
                        "p": ["0.13", "0.14"],
                        "l": ["0.12", "0.11"],
                        "h": ["0.18", "0.20"],
                        "o": "0.12",
                    },
                }
            }
            kraken_response.raise_for_status = Mock()
            
            async def mock_get(*args, **kwargs):
                url = str(args[0]) if args else ""
                if "coinbase" in url:
                    return cb_error_response
                return kraken_response
            
            with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=mock_get):
                result = await check_price_source_health()
                
                # Should be healthy because Kraken provides data
                assert result["healthy"] is True
                assert "kraken_public" in result["summary"]["sources_used"]

    @pytest.mark.asyncio
    async def test_test_public_price_sources(self):
        """Test the public price sources test helper."""
        with patch("data.live_price_feed.get_network_client") as mock_net:
            mock_net.return_value = Mock()
            
            # Mock successful Coinbase responses
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": {"base": "BTC", "currency": "USD", "amount": "65000.00"}
            }
            mock_response.raise_for_status = Mock()
            
            with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
                result = await test_public_price_sources()
                
                assert result["success"] is True
                assert result["all_prices_positive"] is True
                assert result["all_prices_recent"] is True
                assert "health_report" in result


class TestPriceSourceMappings:
    """Test asset-to-pair mappings for public APIs."""

    def test_coinbase_public_pair_mappings(self):
        """Verify all assets have Coinbase public API pair mappings."""
        with patch("data.live_price_feed.get_network_client") as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            expected_mappings = {
                "BTC/USD": "BTC-USD",
                "ETH/USD": "ETH-USD",
                "SOL/USD": "SOL-USD",
                "XRP/USD": "XRP-USD",
                "DOGE/USD": "DOGE-USD",
            }
            
            for symbol, expected_pair in expected_mappings.items():
                assert feed._COINBASE_PUBLIC_PAIRS.get(symbol) == expected_pair, \
                    f"Missing or incorrect Coinbase mapping for {symbol}"

    def test_kraken_public_pair_mappings(self):
        """Verify all assets have Kraken public API pair mappings."""
        with patch("data.live_price_feed.get_network_client") as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            expected_mappings = {
                "BTC/USD": "XXBTZUSD",
                "ETH/USD": "XETHZUSD",
                "SOL/USD": "SOLUSD",
                "XRP/USD": "XXRPZUSD",
                "DOGE/USD": "XDGUSD",
            }
            
            for symbol, expected_pair in expected_mappings.items():
                assert feed._KRAKEN_PUBLIC_PAIRS.get(symbol) == expected_pair, \
                    f"Missing or incorrect Kraken mapping for {symbol}"

    def test_kraken_reverse_mappings(self):
        """Verify Kraken reverse mappings for response parsing."""
        with patch("data.live_price_feed.get_network_client") as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            # Verify each Kraken pair maps back to the correct symbol
            for symbol, kraken_pair in feed._KRAKEN_PUBLIC_PAIRS.items():
                reverse = feed._KRAKEN_PAIR_TO_SYMBOL.get(kraken_pair)
                assert reverse == symbol, \
                    f"Kraken reverse mapping error: {kraken_pair} -> {reverse}, expected {symbol}"
