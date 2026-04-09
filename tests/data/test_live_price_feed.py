"""Tests for data/live_price_feed.py."""
import pytest
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from data.live_price_feed import (
    PriceData, LivePriceFeed, get_live_price_feed, _live_price_feed
)


class TestPriceData:
    """Test PriceData dataclass."""

    def test_creation(self):
        """Test PriceData creation."""
        timestamp = datetime.now()
        price_data = PriceData(
            symbol="BTC/USDT",
            price=50000.0,
            bid=49990.0,
            ask=50010.0,
            volume_24h=1000000.0,
            change_24h_pct=5.0,
            timestamp=timestamp,
            exchange="kraken"
        )
        assert price_data.symbol == "BTC/USDT"
        assert price_data.price == 50000.0
        assert price_data.bid == 49990.0
        assert price_data.ask == 50010.0
        assert price_data.volume_24h == 1000000.0
        assert price_data.change_24h_pct == 5.0
        assert price_data.timestamp == timestamp
        assert price_data.exchange == "kraken"


class TestLivePriceFeedInitialization:
    """Test LivePriceFeed initialization."""

    def test_default_initialization(self):
        """Test default feed initialization."""
        with patch('data.live_price_feed.get_network_client') as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            assert feed.symbols == ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'AVAX/USDT']
            assert feed.update_interval == 1.0
            assert feed.max_retries == 3
            assert feed.exchange_priority == ['kraken', 'coinbase', 'gemini']
            assert feed.running is False

    def test_custom_symbols(self):
        """Test initialization with custom symbols."""
        with patch('data.live_price_feed.get_network_client') as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed(symbols=['BTC/USDT', 'ETH/USDT'])
            
            assert feed.symbols == ['BTC/USDT', 'ETH/USDT']

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
        """Test getting current cached price."""
        with patch('data.live_price_feed.get_network_client') as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            price_data = PriceData(
                symbol="BTC/USDT",
                price=50000.0,
                bid=49990.0,
                ask=50010.0,
                volume_24h=1000000.0,
                change_24h_pct=5.0,
                timestamp=datetime.now(),
                exchange="kraken"
            )
            feed.price_cache["BTC/USDT"] = price_data
            
            result = feed.get_current_price("BTC/USDT")
            
            assert result == price_data

    def test_get_current_price_missing(self):
        """Test getting price for missing symbol."""
        with patch('data.live_price_feed.get_network_client') as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            result = feed.get_current_price("BTC/USDT")
            
            assert result is None

    def test_get_price_alias(self):
        """Test get_price alias for get_current_price."""
        with patch('data.live_price_feed.get_network_client') as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            price_data = PriceData(
                symbol="BTC/USDT",
                price=50000.0,
                bid=49990.0,
                ask=50010.0,
                volume_24h=1000000.0,
                change_24h_pct=5.0,
                timestamp=datetime.now(),
                exchange="kraken"
            )
            feed.price_cache["BTC/USDT"] = price_data
            
            result = feed.get_price("BTC/USDT")
            
            assert result == price_data

    def test_get_all_prices(self):
        """Test getting all cached prices."""
        with patch('data.live_price_feed.get_network_client') as mock_net:
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            price_data1 = PriceData(
                symbol="BTC/USDT", price=50000.0, bid=49990.0, ask=50010.0,
                volume_24h=1000000.0, change_24h_pct=5.0,
                timestamp=datetime.now(), exchange="kraken"
            )
            price_data2 = PriceData(
                symbol="ETH/USDT", price=3000.0, bid=2995.0, ask=3005.0,
                volume_24h=500000.0, change_24h_pct=3.0,
                timestamp=datetime.now(), exchange="kraken"
            )
            feed.price_cache["BTC/USDT"] = price_data1
            feed.price_cache["ETH/USDT"] = price_data2
            
            result = feed.get_all_prices()
            
            assert len(result) == 2
            assert result["BTC/USDT"] == price_data1
            assert result["ETH/USDT"] == price_data2


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
            mock_net.return_value = Mock()
            feed = LivePriceFeed()
            
            feed.exchange_failures["kraken"] = 10  # At threshold
            feed.last_successful_fetch["kraken"] = 0  # No successful fetch
            
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


# ── PATCH-1 / EGG-1 tests: get_spot_usd() ────────────────────────────────

class TestGetSpotUSD:
    """Unit tests for get_spot_usd() — the canonical Kalshi USD spot accessor.

    PATCH-1 / EGG-1: All prices used in the Kalshi trading path must be in
    USD, stored under bare asset keys.
    """

    def _make_feed(self):
        with patch('data.live_price_feed.get_network_client') as mock_net:
            mock_net.return_value = Mock()
            return LivePriceFeed()

    def test_get_spot_usd_returns_none_when_not_cached(self):
        """get_spot_usd returns None when no price has ever been fetched."""
        feed = self._make_feed()
        result = feed.get_spot_usd("BTC")
        assert result is None

    def test_get_spot_usd_returns_spot_data_from_coinbase(self):
        """get_spot_usd returns SpotUSDData for a fresh Coinbase USD price."""
        feed = self._make_feed()
        feed.price_cache["BTC"] = PriceData(
            symbol="BTC",
            price=95000.0,
            bid=94990.0,
            ask=95010.0,
            volume_24h=1_000_000.0,
            change_24h_pct=2.5,
            timestamp=datetime.now(),
            exchange="coinbase_usd",
        )
        result = feed.get_spot_usd("BTC")
        assert result is not None
        assert result.price_usd == pytest.approx(95000.0)
        assert result.spot_source == "coinbase_usd"
        assert result.asset == "BTC"

    def test_get_spot_usd_case_insensitive(self):
        """get_spot_usd accepts lowercase asset keys."""
        feed = self._make_feed()
        feed.price_cache["BTC"] = PriceData(
            symbol="BTC", price=95000.0, bid=94990.0, ask=95010.0,
            volume_24h=0.0, change_24h_pct=0.0, timestamp=datetime.now(),
            exchange="coinbase_usd",
        )
        result = feed.get_spot_usd("btc")
        assert result is not None
        assert result.asset == "BTC"

    def test_get_spot_usd_returns_none_for_depegged_usdt(self):
        """get_spot_usd returns price_usd=None and spot_source='usdt_depegged'."""
        feed = self._make_feed()
        # Sentinel written by depeg guard
        feed.price_cache["BTC"] = PriceData(
            symbol="BTC", price=0.0, bid=0.0, ask=0.0,
            volume_24h=0.0, change_24h_pct=0.0,
            timestamp=datetime.now(), exchange="usdt_depegged",
        )
        result = feed.get_spot_usd("BTC")
        assert result is not None
        assert result.price_usd is None
        assert result.spot_source == "usdt_depegged"

    def test_get_spot_usd_returns_stale_when_price_too_old(self):
        """get_spot_usd returns price_usd=None and spot_source='stale' for old prices."""
        import time as _time
        from datetime import timedelta
        feed = self._make_feed()
        old_ts = datetime.now() - timedelta(seconds=120)  # 2 min old > 60s threshold
        feed.price_cache["ETH"] = PriceData(
            symbol="ETH", price=3500.0, bid=3490.0, ask=3510.0,
            volume_24h=0.0, change_24h_pct=0.0, timestamp=old_ts,
            exchange="coinbase_usd",
        )
        result = feed.get_spot_usd("ETH")
        assert result is not None
        assert result.price_usd is None
        assert result.spot_source == "stale"

    def test_get_spot_usd_fresh_price_within_threshold(self):
        """get_spot_usd returns live price when timestamp is recent."""
        feed = self._make_feed()
        feed.price_cache["SOL"] = PriceData(
            symbol="SOL", price=155.0, bid=154.9, ask=155.1,
            volume_24h=0.0, change_24h_pct=0.0,
            timestamp=datetime.now(),
            exchange="kraken_usd",
        )
        result = feed.get_spot_usd("SOL")
        assert result is not None
        assert result.price_usd == pytest.approx(155.0)
        assert result.spot_source == "kraken_usd"

    def test_get_spot_usd_all_five_kalshi_assets(self):
        """get_spot_usd works for all five Kalshi assets."""
        feed = self._make_feed()
        assets_prices = {
            "BTC": 95000.0, "ETH": 3500.0, "SOL": 155.0,
            "XRP": 0.52, "DOGE": 0.105,
        }
        for asset, price in assets_prices.items():
            feed.price_cache[asset] = PriceData(
                symbol=asset, price=price, bid=price * 0.999, ask=price * 1.001,
                volume_24h=0.0, change_24h_pct=0.0, timestamp=datetime.now(),
                exchange="coingecko_usd",
            )
        for asset, expected_price in assets_prices.items():
            result = feed.get_spot_usd(asset)
            assert result is not None, f"Expected SpotUSDData for {asset}"
            assert result.price_usd == pytest.approx(expected_price), f"Price mismatch for {asset}"
            assert result.spot_source == "coingecko_usd"


class TestKalshiAssetConstants:
    """Verify KALSHI_ASSETS constant and CoinGecko mapping completeness."""

    def test_kalshi_assets_contains_all_five(self):
        """KALSHI_ASSETS must contain exactly BTC, ETH, SOL, XRP, DOGE."""
        from data.live_price_feed import KALSHI_ASSETS
        assert KALSHI_ASSETS == frozenset({"BTC", "ETH", "SOL", "XRP", "DOGE"})

    def test_coingecko_ids_cover_all_kalshi_assets(self):
        """_COINGECKO_IDS must have entries for all five Kalshi assets."""
        from data.live_price_feed import _COINGECKO_IDS, KALSHI_ASSETS
        for asset in KALSHI_ASSETS:
            assert asset in _COINGECKO_IDS, f"Missing CoinGecko ID for {asset}"

    def test_coingecko_xrp_mapping(self):
        """PATCH-8: XRP must map to 'ripple' in CoinGecko IDs."""
        from data.live_price_feed import _COINGECKO_IDS
        assert _COINGECKO_IDS["XRP"] == "ripple"

    def test_coingecko_doge_mapping(self):
        """PATCH-8: DOGE must map to 'dogecoin' in CoinGecko IDs."""
        from data.live_price_feed import _COINGECKO_IDS
        assert _COINGECKO_IDS["DOGE"] == "dogecoin"


class TestGetPriceDeprecation:
    """get_price() should log a deprecation warning for bare Kalshi asset keys."""

    def _make_feed(self):
        with patch('data.live_price_feed.get_network_client') as mock_net:
            mock_net.return_value = Mock()
            return LivePriceFeed()

    def test_get_price_bare_key_logs_deprecation(self):
        """get_price('BTC') must log a deprecation warning and delegate correctly."""
        feed = self._make_feed()
        feed.price_cache["BTC"] = PriceData(
            symbol="BTC", price=95000.0, bid=0.0, ask=0.0,
            volume_24h=0.0, change_24h_pct=0.0, timestamp=datetime.now(),
            exchange="coinbase_usd",
        )
        with patch.object(feed, 'logger', Mock()) as _mock_log:
            # Patch the module-level logger instead
            pass
        import logging
        with patch('data.live_price_feed.logger') as mock_logger:
            result = feed.get_price("BTC")
            # Should have emitted a deprecation warning
            mock_logger.warning.assert_called()
            call_args = str(mock_logger.warning.call_args)
            assert "DEPRECATED" in call_args or "get_spot_usd" in call_args
        assert result is not None
        assert result.price == pytest.approx(95000.0)


import pytest
