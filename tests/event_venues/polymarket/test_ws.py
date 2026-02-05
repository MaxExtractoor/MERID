"""Comprehensive tests for merid/event_venues/polymarket/ws.py - WebSocket mocking."""

import pytest
import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.polymarket.ws import PolymarketWebSocket
from merid.event_venues.polymarket.models import PolymarketConfig
from merid.event_venues.base import QuoteEvent


@pytest.fixture
def config():
    """Create test Polymarket config."""
    return PolymarketConfig(
        api_key="test_key",
        api_secret="test_secret",
        wallet_address="0x123abc"
    )


@pytest.fixture
def ws_client(config):
    """Create test Polymarket WebSocket client."""
    return PolymarketWebSocket(config)


class TestPolymarketWebSocketInitialization:
    """Test PolymarketWebSocket initialization."""
    
    def test_initialization_with_config(self, config):
        """Test initialization with provided config."""
        client = PolymarketWebSocket(config)
        
        assert client.config == config
        assert client._ws is None
        assert client._subscriptions == set()
        assert client._running is False
        assert client._reconnect_delay == 1.0
        assert client._max_reconnect_delay == 60.0
    
    def test_initialization_with_defaults(self):
        """Test initialization with default config."""
        client = PolymarketWebSocket()
        
        assert client.config is not None
        assert isinstance(client.config, PolymarketConfig)
    
    def test_venue_name(self, ws_client):
        """Test venue_name property."""
        assert ws_client.venue_name == "polymarket"


class TestPolymarketWebSocketConnection:
    """Test PolymarketWebSocket connection methods."""
    
    async def test_connect_success(self, ws_client):
        """Test successful connection."""
        mock_ws = AsyncMock()
        
        async def mock_connect(*args, **kwargs):
            return mock_ws
        
        with patch('websockets.connect', side_effect=mock_connect):
            await ws_client.connect()
            
            assert ws_client._ws == mock_ws
            assert ws_client._running is True
            assert ws_client._reconnect_delay == 1.0
    
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
        ws_client._subscriptions = {"0x123abc"}
        
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


class TestPolymarketWebSocketSubscriptions:
    """Test PolymarketWebSocket subscription methods."""
    
    async def test_subscribe_quotes_success(self, ws_client):
        """Test subscribe_quotes success."""
        mock_ws = AsyncMock()
        ws_client._ws = mock_ws
        
        await ws_client.subscribe_quotes(["0x123abc", "0x456def"])
        
        mock_ws.send.assert_called_once()
        call_args = mock_ws.send.call_args[0][0]
        message = json.loads(call_args)
        assert message["type"] == "subscribe"
        assert message["channel"] == "markets"
        assert "0x123abc" in message["market_ids"]
        
        # Check subscriptions tracked
        assert "0x123abc" in ws_client._subscriptions
        assert "0x456def" in ws_client._subscriptions
    
    async def test_subscribe_quotes_not_connected(self, ws_client):
        """Test subscribe_quotes when not connected."""
        with pytest.raises(RuntimeError, match="WebSocket not connected"):
            await ws_client.subscribe_quotes(["0x123abc"])
    
    async def test_subscribe_trades_success(self, ws_client):
        """Test subscribe_trades success."""
        mock_ws = AsyncMock()
        ws_client._ws = mock_ws
        
        await ws_client.subscribe_trades()
        
        mock_ws.send.assert_called_once()
        call_args = mock_ws.send.call_args[0][0]
        message = json.loads(call_args)
        assert message["type"] == "subscribe"
        assert message["channel"] == "trades"
    
    async def test_subscribe_trades_with_markets(self, ws_client):
        """Test subscribe_trades with specific markets."""
        mock_ws = AsyncMock()
        ws_client._ws = mock_ws
        
        await ws_client.subscribe_trades(["0x123abc"])
        
        call_args = mock_ws.send.call_args[0][0]
        message = json.loads(call_args)
        assert message["market_ids"] == ["0x123abc"]
    
    async def test_subscribe_orderbook_success(self, ws_client):
        """Test subscribe_orderbook success."""
        mock_ws = AsyncMock()
        ws_client._ws = mock_ws
        
        await ws_client.subscribe_orderbook("0x123abc")
        
        mock_ws.send.assert_called_once()
        call_args = mock_ws.send.call_args[0][0]
        message = json.loads(call_args)
        assert message["type"] == "subscribe"
        assert message["channel"] == "orderbook"
        assert message["market_id"] == "0x123abc"
        
        # Check subscription tracked with prefix
        assert "orderbook:0x123abc" in ws_client._subscriptions
    
    async def test_subscribe_orderbook_not_connected(self, ws_client):
        """Test subscribe_orderbook when not connected."""
        with pytest.raises(RuntimeError, match="WebSocket not connected"):
            await ws_client.subscribe_orderbook("0x123abc")


class TestPolymarketWebSocketListening:
    """Test PolymarketWebSocket listen method."""
    
    async def test_listen_quote_message(self, ws_client):
        """Test listen with quote message."""
        quote_message = {
            "channel": "markets",
            "market_id": "0x123abc",
            "outcome_id": "Yes",
            "bid": "0.65",
            "ask": "0.67",
            "last_price": "0.66",
            "volume": "100000"
        }
        
        event = ws_client._parse_message(quote_message)
        
        assert isinstance(event, QuoteEvent)
        assert event.market_id == "0x123abc"
        assert event.outcome_id == "Yes"
        assert event.bid_price == Decimal("0.65")
        assert event.ask_price == Decimal("0.67")
        assert event.venue == "polymarket"
    
    async def test_listen_trade_message(self, ws_client):
        """Test listen with trade message."""
        trade_message = {
            "channel": "trades",
            "trade_id": "trade_123",
            "market_id": "0x123abc",
            "order_id": "order_456",
            "side": "buy",
            "size": "100",
            "price": "0.65",
            "fee": "0.01",
            "timestamp": "2024-01-15T10:30:00Z"
        }
        
        event = ws_client._parse_message(trade_message)
        
        assert event is not None
        assert event.trade_id == "trade_123"
        assert event.market_id == "0x123abc"
        assert event.side == "buy"
        assert event.size == Decimal("100")
        assert event.price == Decimal("0.65")
    
    async def test_listen_not_connected(self, ws_client):
        """Test listen when not connected."""
        with pytest.raises(RuntimeError, match="WebSocket not connected"):
            await ws_client.listen(lambda x: x)


class TestPolymarketWebSocketReconnect:
    """Test PolymarketWebSocket reconnection logic."""
    
    async def test_reconnect_increases_delay(self, ws_client):
        """Test reconnect increases delay exponentially."""
        ws_client._running = True
        ws_client._reconnect_delay = 1.0
        
        with patch.object(ws_client, 'connect', new_callable=AsyncMock) as mock_connect:
            await ws_client._reconnect()
            
            # Delay should double
            assert ws_client._reconnect_delay == 2.0
            mock_connect.assert_called_once()
    
    async def test_reconnect_max_delay_cap(self, ws_client):
        """Test reconnect delay is capped at max."""
        ws_client._running = True
        ws_client._reconnect_delay = 40.0  # Close to max
        
        with patch.object(ws_client, 'connect', new_callable=AsyncMock):
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
        ws_client._subscriptions = {"0x123abc", "0x456def", "orderbook:0x123abc"}
        
        with patch.object(ws_client, 'connect', new_callable=AsyncMock):
            with patch.object(ws_client, 'subscribe_quotes', new_callable=AsyncMock) as mock_sub:
                await ws_client._reconnect()
                
                # Should resubscribe only to markets (not orderbook: prefixed ones)
                mock_sub.assert_called_once_with(["0x123abc", "0x456def"])
    
    async def test_reconnect_failure(self, ws_client):
        """Test reconnect failure handling."""
        ws_client._running = True
        ws_client._reconnect_delay = 1.0
        
        with patch.object(ws_client, 'connect', side_effect=ConnectionError("Failed")):
            # Should not raise, just log error
            await ws_client._reconnect()
            
            # Delay should still increase
            assert ws_client._reconnect_delay == 2.0


class TestPolymarketWebSocketParseMessage:
    """Test _parse_message method."""
    
    def test_parse_markets_message(self, ws_client):
        """Test parsing markets message."""
        data = {
            "channel": "markets",
            "market_id": "0x123abc",
            "outcome_id": "Yes",
            "bid": "0.65",
            "ask": "0.67",
            "last_price": "0.66",
            "volume": "100000"
        }
        
        event = ws_client._parse_message(data)
        
        assert isinstance(event, QuoteEvent)
        assert event.market_id == "0x123abc"
        assert event.outcome_id == "Yes"
        assert event.bid_price == Decimal("0.65")
        assert event.ask_price == Decimal("0.67")
        assert event.last_price == Decimal("0.66")
        assert event.volume == Decimal("100000")
        assert event.venue == "polymarket"
        assert event.raw_data == data
    
    def test_parse_markets_without_prices(self, ws_client):
        """Test parsing markets message without prices."""
        data = {
            "channel": "markets",
            "market_id": "0x123abc"
        }
        
        event = ws_client._parse_message(data)
        
        assert event.bid_price is None
        assert event.ask_price is None
        assert event.last_price is None
    
    def test_parse_trade_message(self, ws_client):
        """Test parsing trade message."""
        from merid.event_venues.base import VenueTrade
        
        data = {
            "channel": "trades",
            "trade_id": "trade_123",
            "market_id": "0x123abc",
            "order_id": "order_456",
            "side": "buy",
            "size": "100",
            "price": "0.65",
            "fee": "0.01",
            "timestamp": "2024-01-15T10:30:00Z"
        }
        
        event = ws_client._parse_message(data)
        
        assert isinstance(event, VenueTrade)
        assert event.trade_id == "trade_123"
        assert event.market_id == "0x123abc"
        assert event.side == "buy"
        assert event.size == Decimal("100")
        assert event.price == Decimal("0.65")
        assert event.fee == Decimal("0.01")
    
    def test_parse_empty_message(self, ws_client):
        """Test parsing empty message."""
        event = ws_client._parse_message({})
        
        assert event is None
    
    def test_parse_unknown_channel(self, ws_client):
        """Test parsing unknown channel message."""
        data = {
            "channel": "unknown",
            "data": "test"
        }
        
        event = ws_client._parse_message(data)
        
        assert event is None
