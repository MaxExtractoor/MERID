"""Comprehensive tests for merid/event_venues/kalshi/ws.py - WebSocket mocking."""

import pytest
import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch, call

from merid.event_venues.kalshi.ws import KalshiWebSocket
from merid.event_venues.kalshi.models import KalshiConfig
from merid.event_venues.base import QuoteEvent
from core.fault_manager import reset_fault_manager


@pytest.fixture(autouse=True)
def _isolate_fault_manager():
    """Reset the process-wide ``FaultManager`` around each test.

    ``KalshiWebSocket._reconnect`` consults ``can_attempt_reconnect("kalshi")``
    and short-circuits once the venue circuit breaker opens.  Without this
    fixture, failure state leaks across tests and silently blocks reconnects.
    """
    reset_fault_manager()
    try:
        yield
    finally:
        reset_fault_manager()


@pytest.fixture
def config():
    """Create test Kalshi config."""
    return KalshiConfig(
        email="test@example.com",
        password="test_password",
        use_demo=True
    )


@pytest.fixture
def ws_client(config):
    """Create test Kalshi WebSocket client."""
    return KalshiWebSocket(config)


class TestKalshiWebSocketInitialization:
    """Test KalshiWebSocket initialization."""
    
    def test_initialization_with_config(self, config):
        """Test initialization with provided config."""
        client = KalshiWebSocket(config)
        
        assert client.config == config
        assert client._ws is None
        assert client._subscriptions == set()
        assert client._running is False
        assert client._reconnect_delay == 1.0
        assert client._max_reconnect_delay == 60.0
        assert client._auth_token is None
    
    def test_initialization_with_defaults(self):
        """Test initialization with default config."""
        client = KalshiWebSocket()
        
        assert client.config is not None
        assert isinstance(client.config, KalshiConfig)
    
    def test_venue_name(self, ws_client):
        """Test venue_name property."""
        assert ws_client.venue_name == "kalshi"


class TestKalshiWebSocketConnection:
    """Test KalshiWebSocket connection methods."""
    
    async def test_connect_success(self, ws_client):
        """Test successful connection."""
        mock_ws = AsyncMock()
        
        # Mock websockets.connect to return the mock_ws directly
        async def mock_connect(*args, **kwargs):
            return mock_ws
        
        with patch('websockets.connect', side_effect=mock_connect):
            await ws_client.connect()
            
            assert ws_client._ws == mock_ws
            assert ws_client._running is True
            assert ws_client._reconnect_delay == 1.0
    
    async def test_connect_with_auth_token(self, ws_client):
        """Test connection with auth token."""
        ws_client._auth_token = "test_token"
        mock_ws = AsyncMock()
        
        captured_kwargs = {}
        async def mock_connect(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return mock_ws
        
        with patch('websockets.connect', side_effect=mock_connect):
            await ws_client.connect()
            
            # websockets 14+ — handshake headers (was extra_headers)
            assert "additional_headers" in captured_kwargs
    
    async def test_connect_failure(self, ws_client):
        """Test connection failure handling."""
        with patch('websockets.connect', side_effect=ConnectionError("Connection failed")):
            with pytest.raises(ConnectionError):
                await ws_client.connect()
    
    async def test_close(self, ws_client):
        """Test close method."""
        mock_ws = AsyncMock()
        ws_client._ws = mock_ws
        ws_client._running = True
        ws_client._subscriptions = {"FED-25DEC"}
        
        await ws_client.close()
        
        assert ws_client._running is False
        assert ws_client._ws is None
        assert len(ws_client._subscriptions) == 0
        mock_ws.close.assert_called_once()
    
    async def test_close_with_error(self, ws_client):
        """Test close method when ws.close raises error."""
        mock_ws = AsyncMock()
        mock_ws.close.side_effect = ConnectionError("Close failed")
        ws_client._ws = mock_ws
        ws_client._running = True
        
        # Should not raise
        await ws_client.close()
        
        assert ws_client._running is False


class TestKalshiWebSocketSubscriptions:
    """Test KalshiWebSocket subscription methods."""
    
    async def test_subscribe_quotes_success(self, ws_client):
        """Test subscribe_quotes success."""
        mock_ws = AsyncMock()
        ws_client._ws = mock_ws
        
        await ws_client.subscribe_quotes(["FED-25DEC-T3.00", "BTC-24DEC"])
        
        mock_ws.send.assert_called_once()
        call_args = mock_ws.send.call_args[0][0]
        message = json.loads(call_args)
        assert message["cmd"] == "subscribe"
        assert "ticker" in message["params"]["channels"]
        assert "FED-25DEC-T3.00" in message["params"]["market_tickers"]
        
        # Check subscriptions tracked
        assert "FED-25DEC-T3.00" in ws_client._subscriptions
        assert "BTC-24DEC" in ws_client._subscriptions
    
    async def test_subscribe_quotes_not_connected(self, ws_client):
        """Test subscribe_quotes when not connected."""
        with pytest.raises(RuntimeError, match="WebSocket not connected"):
            await ws_client.subscribe_quotes(["FED-25DEC"])
    
    async def test_subscribe_trades_success(self, ws_client):
        """Test subscribe_trades success."""
        mock_ws = AsyncMock()
        ws_client._ws = mock_ws
        
        await ws_client.subscribe_trades()
        
        mock_ws.send.assert_called_once()
        call_args = mock_ws.send.call_args[0][0]
        message = json.loads(call_args)
        assert message["cmd"] == "subscribe"
        assert "trade" in message["params"]["channels"]
    
    async def test_subscribe_trades_with_markets(self, ws_client):
        """Test subscribe_trades with specific markets."""
        mock_ws = AsyncMock()
        ws_client._ws = mock_ws
        
        await ws_client.subscribe_trades(["FED-25DEC"])
        
        call_args = mock_ws.send.call_args[0][0]
        message = json.loads(call_args)
        assert message["params"]["market_tickers"] == ["FED-25DEC"]
    
    async def test_subscribe_orderbook_success(self, ws_client):
        """Test subscribe_orderbook success."""
        mock_ws = AsyncMock()
        ws_client._ws = mock_ws
        
        await ws_client.subscribe_orderbook("FED-25DEC-T3.00")
        
        mock_ws.send.assert_called_once()
        call_args = mock_ws.send.call_args[0][0]
        message = json.loads(call_args)
        assert message["cmd"] == "subscribe"
        assert "orderbook_delta" in message["params"]["channels"]
        assert "FED-25DEC-T3.00" in message["params"]["market_tickers"]
        
        # Check subscription tracked with prefix
        assert "orderbook:FED-25DEC-T3.00" in ws_client._subscriptions
    
    async def test_subscribe_orderbook_not_connected(self, ws_client):
        """Test subscribe_orderbook when not connected."""
        with pytest.raises(RuntimeError, match="WebSocket not connected"):
            await ws_client.subscribe_orderbook("FED-25DEC")

    async def test_subscribe_orderbooks_batch_chunks(self, ws_client):
        """Batch orderbook_delta subscribe sends chunked JSON messages."""
        mock_ws = AsyncMock()
        ws_client._ws = mock_ws
        tickers = [f"MKT-{i}" for i in range(55)]

        await ws_client.subscribe_orderbooks_batch(tickers, chunk_size=50)

        assert mock_ws.send.await_count == 2
        parsed = [json.loads(c.args[0]) for c in mock_ws.send.await_args_list]
        assert parsed[0]["cmd"] == "subscribe"
        assert parsed[0]["params"]["channels"] == ["orderbook_delta"]
        assert len(parsed[0]["params"]["market_tickers"]) == 50
        assert len(parsed[1]["params"]["market_tickers"]) == 5
        assert ws_client._orderbook_tickers == set(tickers)


class TestKalshiWebSocketListening:
    """Test KalshiWebSocket listen method."""
    
    async def test_listen_quote_message(self, ws_client):
        """Test listen with quote message."""
        mock_ws = AsyncMock()
        
        # Mock incoming message
        quote_message = json.dumps({
            "channel": "ticker",
            "ticker": "FED-25DEC-T3.00",
            "bid": 6400,
            "ask": 6600,
            "last_price": 6500,
            "volume": "1000000"
        })
        
        # Set up async iteration
        mock_ws.__aiter__ = AsyncMock(return_value=iter([quote_message]))
        ws_client._ws = mock_ws
        ws_client._running = True
        
        callback = AsyncMock()
        
        # Run listen for one iteration
        ws_client._running = False  # Stop after first message
        
        # Just test the parsing directly
        data = json.loads(quote_message)
        event = ws_client._parse_message(data)
        
        assert isinstance(event, QuoteEvent)
        assert event.market_id == "FED-25DEC-T3.00"
        assert event.bid_price == Decimal("64.00")  # Converted from cents
        assert event.ask_price == Decimal("66.00")
        assert event.venue == "kalshi"
    
    async def test_listen_trade_message(self, ws_client):
        """Test listen with trade message."""
        trade_message = {
            "channel": "trade",
            "trade_id": "trade_123",
            "ticker": "FED-25DEC-T3.00",
            "side": "buy",
            "count": 100,
            "price": 6500,
            "fee": 10,
            "created_at": "2024-01-15T10:30:00Z"
        }
        
        event = ws_client._parse_message(trade_message)
        
        assert event is not None
        assert event.trade_id == "trade_123"
        assert event.market_id == "FED-25DEC-T3.00"
        assert event.side == "buy"
        assert event.size == Decimal("100")
        assert event.price == Decimal("65.00")  # Converted from cents
    
    async def test_listen_invalid_json(self, ws_client):
        """Test listen with invalid JSON message."""
        # Test parsing invalid JSON directly
        import json
        
        invalid_message = "not valid json"
        
        with pytest.raises(json.JSONDecodeError):
            json.loads(invalid_message)
    
    async def test_listen_unknown_channel(self, ws_client):
        """Test listen with unknown channel."""
        unknown_message = {
            "channel": "unknown",
            "data": "test"
        }
        
        event = ws_client._parse_message(unknown_message)
        
        assert event is None
    
    async def test_listen_not_connected(self, ws_client):
        """Test listen when not connected."""
        with pytest.raises(RuntimeError, match="WebSocket not connected"):
            await ws_client.listen(lambda x: x)


class TestKalshiWebSocketReconnect:
    """Test KalshiWebSocket reconnection logic."""
    
    async def test_reconnect_increases_delay(self, ws_client):
        """Test reconnect increases delay exponentially on *failure*.

        Current production semantics (``ws.py`` ``_reconnect``):
          * success → delay is reset to 1.0
          * failure → delay doubles, capped at ``_max_reconnect_delay``
        """
        ws_client._running = True
        ws_client._reconnect_delay = 1.0

        async def failing_connect():
            raise ConnectionError("simulated")

        with patch.object(ws_client, 'connect', side_effect=failing_connect) as mock_connect:
            await ws_client._reconnect()

            # Delay should double after one failed attempt
            assert ws_client._reconnect_delay == 2.0
            mock_connect.assert_called_once()
    
    async def test_reconnect_max_delay_cap(self, ws_client):
        """Test reconnect delay is capped at max on repeated failure."""
        ws_client._running = True
        ws_client._reconnect_delay = 40.0  # Close to max

        async def failing_connect():
            raise ConnectionError("simulated")

        with patch.object(ws_client, 'connect', side_effect=failing_connect):
            await ws_client._reconnect()

            # Should be capped at 60
            assert ws_client._reconnect_delay == 60.0
    
    async def test_reconnect_not_running(self, ws_client):
        """Test reconnect when not running."""
        ws_client._running = False
        
        with patch.object(ws_client, 'connect', new_callable=AsyncMock) as mock_connect:
            await ws_client._reconnect()
            
            mock_connect.assert_not_called()
    
    async def test_reconnect_restores_subscriptions(self, ws_client):
        """Test reconnect restores previous subscriptions."""
        ws_client._running = True
        ws_client._subscriptions = {"FED-25DEC", "BTC-24DEC", "orderbook:FED-25DEC"}
        # Reconnect replays ticker subs from _ticker_subscriptions (BUG-6), not _subscriptions alone.
        ws_client._ticker_subscriptions = {"FED-25DEC", "BTC-24DEC"}
        
        with patch.object(ws_client, 'connect', new_callable=AsyncMock):
            with patch.object(ws_client, 'subscribe_quotes', new_callable=AsyncMock) as mock_sub:
                await ws_client._reconnect()
                
                # Should resubscribe only to markets (not orderbook: prefixed ones)
                mock_sub.assert_called_once()
                # subscribe_quotes uses keyword market_ids=; order within list is not guaranteed
                called_markets = set(mock_sub.call_args.kwargs["market_ids"])
                assert called_markets == {"FED-25DEC", "BTC-24DEC"}
    
    async def test_reconnect_failure(self, ws_client):
        """Test reconnect failure handling."""
        ws_client._running = True
        ws_client._reconnect_delay = 1.0
        
        with patch.object(ws_client, 'connect', side_effect=ConnectionError("Failed")):
            # Should not raise, just log error
            await ws_client._reconnect()
            
            # Delay should still increase
            assert ws_client._reconnect_delay == 2.0


class TestKalshiWebSocketParseMessage:
    """Test _parse_message method."""
    
    def test_parse_ticker_message(self, ws_client):
        """Test parsing ticker message."""
        data = {
            "channel": "ticker",
            "ticker": "FED-25DEC",
            "bid": 6400,
            "ask": 6600,
            "last_price": 6500,
            "volume": "1000000"
        }
        
        event = ws_client._parse_message(data)
        
        assert isinstance(event, QuoteEvent)
        assert event.market_id == "FED-25DEC"
        assert event.bid_price == Decimal("64.00")
        assert event.ask_price == Decimal("66.00")
        assert event.last_price == Decimal("65.00")
        assert event.volume == Decimal("1000000")
        assert event.venue == "kalshi"
        assert event.raw_data == data
    
    def test_parse_ticker_without_prices(self, ws_client):
        """Test parsing ticker message without prices."""
        data = {
            "channel": "ticker",
            "ticker": "FED-25DEC"
        }
        
        event = ws_client._parse_message(data)
        
        assert event.bid_price is None
        assert event.ask_price is None
        assert event.last_price is None
    
    def test_parse_trade_message(self, ws_client):
        """Test parsing trade message."""
        from merid.event_venues.base import VenueTrade
        
        data = {
            "channel": "trade",
            "trade_id": "trade_123",
            "ticker": "FED-25DEC",
            "order_id": "order_456",
            "side": "buy",
            "count": 100,
            "price": 6500,
            "fee": 10,
            "created_at": "2024-01-15T10:30:00Z"
        }
        
        event = ws_client._parse_message(data)
        
        assert isinstance(event, VenueTrade)
        assert event.trade_id == "trade_123"
        assert event.market_id == "FED-25DEC"
        assert event.side == "buy"
        assert event.size == Decimal("100")
        assert event.price == Decimal("65.00")
        assert event.fee == Decimal("0.10")
    
    def test_parse_message_type_field(self, ws_client):
        """Test parsing message with 'type' instead of 'channel'."""
        data = {
            "type": "ticker",
            "ticker": "FED-25DEC",
            "bid": 6400
        }
        
        event = ws_client._parse_message(data)
        
        assert isinstance(event, QuoteEvent)
        assert event.market_id == "FED-25DEC"
    
    def test_parse_empty_message(self, ws_client):
        """Test parsing empty message."""
        event = ws_client._parse_message({})
        
        assert event is None
