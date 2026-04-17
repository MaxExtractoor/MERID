"""Tests for streams/market.py."""
import pytest
import asyncio
import time
from unittest.mock import Mock, patch, AsyncMock
from streams.market import (
    MarketStreamConfig, ExchangeConnection, MarketStream,
    get_market_stream, start_market_stream, stop_market_stream, _market_stream
)


class TestMarketStreamConfig:
    """Test MarketStreamConfig dataclass."""

    def test_default_values(self):
        """Test default config values."""
        config = MarketStreamConfig()
        assert config.exchanges == ["binance", "coinbase"]
        assert config.symbols == ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
        assert config.ticker_interval_seconds == 1.0
        assert config.funding_interval_seconds == 60.0
        assert config.orderbook_depth == 10
        assert config.enable_tickers is True
        assert config.enable_funding is True
        assert config.enable_orderbook is False
        assert config.rate_limit_per_exchange == 10

    def test_custom_values(self):
        """Test custom config values."""
        config = MarketStreamConfig(
            exchanges=["kraken"],
            symbols=["BTC/USD"],
            ticker_interval_seconds=5.0,
            enable_tickers=False
        )
        assert config.exchanges == ["kraken"]
        assert config.symbols == ["BTC/USD"]
        assert config.ticker_interval_seconds == 5.0
        assert config.enable_tickers is False


    def test_from_asset_universe_non_empty(self):
        """from_asset_universe() returns a non-empty symbol list."""
        config = MarketStreamConfig.from_asset_universe()
        assert isinstance(config, MarketStreamConfig)
        assert len(config.symbols) > 0

    def test_from_asset_universe_no_perp_aliases(self):
        """from_asset_universe() must not include perp-alias symbols (contain ':')."""
        config = MarketStreamConfig.from_asset_universe()
        for sym in config.symbols:
            assert ":" not in sym, f"Perp alias leaked into stream config: {sym!r}"

    def test_from_asset_universe_contains_btc(self):
        """from_asset_universe() must include BTC/USDT (tier-1 high-signal asset)."""
        config = MarketStreamConfig.from_asset_universe()
        assert "BTC/USDT" in config.symbols

    def test_from_asset_universe_kwargs_forwarded(self):
        """from_asset_universe() forwards extra kwargs to MarketStreamConfig."""
        config = MarketStreamConfig.from_asset_universe(ticker_interval_seconds=5.0)
        assert config.ticker_interval_seconds == 5.0


class TestExchangeConnection:
    """Test ExchangeConnection dataclass."""

    def test_creation(self):
        """Test ExchangeConnection creation."""
        mock_exchange = Mock()
        conn = ExchangeConnection(
            exchange_id="binance",
            exchange=mock_exchange,
            connected=True
        )
        assert conn.exchange_id == "binance"
        assert conn.exchange == mock_exchange
        assert conn.connected is True
        assert conn.last_request == 0.0
        assert conn.request_count == 0

    def test_can_request_within_limit(self):
        """Test can_request when under rate limit."""
        mock_exchange = Mock()
        conn = ExchangeConnection(exchange_id="binance", exchange=mock_exchange)
        
        assert conn.can_request(10, 1.0) is True

    def test_can_request_exceeds_limit(self):
        """Test can_request when over rate limit."""
        mock_exchange = Mock()
        conn = ExchangeConnection(exchange_id="binance", exchange=mock_exchange)
        conn.request_count = 10
        conn.last_request = time.time()
        
        assert conn.can_request(10, 1.0) is False

    def test_can_request_window_reset(self):
        """Test can_request after window expires."""
        mock_exchange = Mock()
        conn = ExchangeConnection(exchange_id="binance", exchange=mock_exchange)
        conn.request_count = 10
        conn.last_request = time.time() - 2.0  # 2 seconds ago
        
        assert conn.can_request(10, 1.0) is True
        assert conn.request_count == 0

    def test_record_request(self):
        """Test record_request method."""
        mock_exchange = Mock()
        conn = ExchangeConnection(exchange_id="binance", exchange=mock_exchange)
        
        conn.record_request()
        
        assert conn.request_count == 1
        assert conn.last_request > 0


class TestMarketStream:
    """Test MarketStream class."""

    def test_initialization(self):
        """Test stream initialization."""
        stream = MarketStream(stream_id="test-market")
        assert stream.stream_id == "test-market"
        assert stream.stream_type == "market"
        assert stream._connections == {}
        assert stream._ticker_task is None
        assert stream._funding_task is None

    def test_initialization_with_config(self):
        """Test stream initialization with custom config."""
        config = MarketStreamConfig(exchanges=["kraken"], symbols=["BTC/USD"])
        stream = MarketStream(stream_id="test-market", config=config)
        assert stream._market_config.exchanges == ["kraken"]
        assert stream._market_config.symbols == ["BTC/USD"]

    def test_get_perp_symbol_with_colon(self):
        """Test _get_perp_symbol with already perpetual symbol."""
        stream = MarketStream()
        result = stream._get_perp_symbol("BTC/USDT:USDT")
        assert result == "BTC/USDT:USDT"

    def test_get_perp_symbol_conversion(self):
        """Test _get_perp_symbol conversion."""
        stream = MarketStream()
        result = stream._get_perp_symbol("BTC/USDT")
        assert result == "BTC/USDT:USDT"

    def test_get_perp_symbol_no_slash(self):
        """Test _get_perp_symbol without slash."""
        stream = MarketStream()
        result = stream._get_perp_symbol("BTC")
        assert result == "BTC"

    def test_create_ticker_event(self):
        """Test _create_ticker_event."""
        stream = MarketStream(stream_id="test-market")
        ticker = {
            "last": 50000.0,
            "bid": 49990.0,
            "ask": 50010.0,
            "baseVolume": 1000.0,
            "quoteVolume": 50000000.0,
            "high": 51000.0,
            "low": 49000.0,
            "change": 1000.0,
            "percentage": 2.0,
            "timestamp": 1234567890000
        }
        
        event = stream._create_ticker_event("binance", "BTC/USDT", ticker)
        
        assert event.event_type.value == "market_data"
        assert event.source == "binance:BTC/USDT"
        assert event.payload["symbol"] == "BTC/USDT"
        assert event.payload["price"] == 50000.0
        assert event.payload["bid"] == 49990.0
        assert event.payload["ask"] == 50010.0

    def test_create_ticker_event_no_last(self):
        """Test _create_ticker_event with no last price."""
        stream = MarketStream(stream_id="test-market")
        ticker = {
            "close": 50000.0,
            "bid": 49990.0,
            "ask": 50010.0
        }
        
        event = stream._create_ticker_event("binance", "BTC/USDT", ticker)
        
        assert event.payload["price"] == 50000.0

    def test_create_funding_event(self):
        """Test _create_funding_event."""
        stream = MarketStream(stream_id="test-market")
        funding = {
            "fundingRate": 0.0001,
            "fundingTimestamp": 1234567890000,
            "nextFundingTimestamp": 1234654290000,
            "markPrice": 50000.0,
            "indexPrice": 49995.0,
            "interestRate": 0.00001
        }
        
        event = stream._create_funding_event("binance", "BTC/USDT", funding)
        
        assert event.event_type.value == "market_data"
        assert event.source == "binance:BTC/USDT:funding"
        assert event.payload["symbol"] == "BTC/USDT"
        assert event.payload["funding_rate"] == 0.0001
        assert event.payload["mark_price"] == 50000.0

    def test_get_exchange_stats_empty(self):
        """Test get_exchange_stats with no connections."""
        stream = MarketStream(stream_id="test-market")
        stats = stream.get_exchange_stats()
        assert stats == {}

    def test_get_exchange_stats(self):
        """Test get_exchange_stats with connections."""
        stream = MarketStream(stream_id="test-market")
        mock_exchange = Mock()
        conn = ExchangeConnection(
            exchange_id="binance",
            exchange=mock_exchange,
            connected=True,
            request_count=10,
            error_count=2,
            last_request=1234567890.0
        )
        stream._connections["binance"] = conn
        
        stats = stream.get_exchange_stats()
        
        assert "binance" in stats
        assert stats["binance"]["connected"] is True
        assert stats["binance"]["request_count"] == 10
        assert stats["binance"]["error_count"] == 2


class TestGetMarketStream:
    """Test get_market_stream function."""

    def setup_method(self):
        """Reset singleton before each test."""
        global _market_stream
        import streams.market as m
        m._market_stream = None

    def test_singleton(self):
        """Test get_market_stream returns singleton."""
        with patch('streams.market.get_stream_registry') as mock_registry:
            mock_registry.return_value = Mock()
            stream1 = get_market_stream()
            stream2 = get_market_stream()
            assert stream1 is stream2


class TestStartStopMarketStream:
    """Test start_market_stream and stop_market_stream functions."""

    def setup_method(self):
        """Reset singleton before each test."""
        global _market_stream
        import streams.market as m
        m._market_stream = None

    @pytest.mark.asyncio
    async def test_start_market_stream(self):
        """Test starting market stream."""
        with patch('streams.market.get_stream_registry') as mock_registry:
            with patch.object(MarketStream, 'start', new_callable=AsyncMock) as mock_start:
                mock_registry.return_value = Mock()
                
                stream = await start_market_stream()
                
                assert stream is not None
                assert stream.stream_type == "market"

    @pytest.mark.asyncio
    async def test_stop_market_stream(self):
        """Test stopping market stream."""
        with patch('streams.market.get_stream_registry') as mock_registry:
            with patch.object(MarketStream, 'stop', new_callable=AsyncMock) as mock_stop:
                mock_registry.return_value = Mock()
                
                # First create a stream
                global _market_stream
                import streams.market as m
                m._market_stream = MarketStream()
                
                await stop_market_stream()
                
                # Should not raise
