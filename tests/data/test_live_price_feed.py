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
