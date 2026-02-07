"""Tests for merid/event_venues/polymarket/ws.py - Batch A."""
import pytest
import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.polymarket.ws import PolymarketWebSocket
from merid.event_venues.polymarket.models import PolymarketConfig


@pytest.fixture
def mock_config():
    return PolymarketConfig(api_key="test_key", api_secret="test_secret")


@pytest.fixture
def ws_client(mock_config):
    return PolymarketWebSocket(config=mock_config)


class TestPolymarketWebSocketLifecycle:
    """Test connect, close methods."""

    @pytest.mark.asyncio
    async def test_connect_establishes_websocket(self, ws_client, mocker):
        """Test connect creates websocket connection."""
        mock_ws = AsyncMock()
        async def mock_connect(*args, **kwargs):
            return mock_ws
        mocker.patch("websockets.connect", side_effect=mock_connect)

        await ws_client.connect()

        assert ws_client._ws is not None
        assert ws_client._running is True

    @pytest.mark.asyncio
    async def test_connect_raises_on_error(self, ws_client, mocker):
        """Test connect raises exception on connection error."""
        async def mock_connect(*args, **kwargs):
            raise ConnectionError("Failed")
        mocker.patch("websockets.connect", side_effect=mock_connect)

        with pytest.raises(ConnectionError):
            await ws_client.connect()

    @pytest.mark.asyncio
    async def test_close_cleans_up(self, ws_client):
        """Test close properly cleans up connection."""
        mock_ws = AsyncMock()
        ws_client._ws = mock_ws
        ws_client._running = True
        ws_client._subscriptions.add("MARKET-1")

        await ws_client.close()

        assert ws_client._running is False
        assert ws_client._ws is None
        assert len(ws_client._subscriptions) == 0
        mock_ws.close.assert_called_once()


class TestPolymarketWebSocketSubscriptions:
    """Test subscription methods."""

    @pytest.mark.asyncio
    async def test_subscribe_quotes_sends_message(self, ws_client):
        """Test subscribe_quotes sends correct message."""
        mock_ws = AsyncMock()
        ws_client._ws = mock_ws

        await ws_client.subscribe_quotes(["MARKET-1", "MARKET-2"])

        mock_ws.send.assert_called_once()
        sent_msg = json.loads(mock_ws.send.call_args[0][0])
        assert sent_msg["type"] == "subscribe"
        assert sent_msg["channel"] == "markets"
        assert "MARKET-1" in sent_msg["market_ids"]

    @pytest.mark.asyncio
    async def test_subscribe_quotes_raises_when_not_connected(self, ws_client):
        """Test subscribe_quotes raises when not connected."""
        with pytest.raises(RuntimeError, match="WebSocket not connected"):
            await ws_client.subscribe_quotes(["MARKET-1"])

    @pytest.mark.asyncio
    async def test_subscribe_trades_sends_message(self, ws_client):
        """Test subscribe_trades sends correct message."""
        mock_ws = AsyncMock()
        ws_client._ws = mock_ws

        await ws_client.subscribe_trades()

        mock_ws.send.assert_called_once()
        sent_msg = json.loads(mock_ws.send.call_args[0][0])
        assert sent_msg["type"] == "subscribe"
        assert sent_msg["channel"] == "trades"

    @pytest.mark.asyncio
    async def test_subscribe_trades_with_market_ids(self, ws_client):
        """Test subscribe_trades with specific markets."""
        mock_ws = AsyncMock()
        ws_client._ws = mock_ws

        await ws_client.subscribe_trades(["MARKET-1"])

        sent_msg = json.loads(mock_ws.send.call_args[0][0])
        assert sent_msg["market_ids"] == ["MARKET-1"]

    @pytest.mark.asyncio
    async def test_subscribe_orderbook_sends_message(self, ws_client):
        """Test subscribe_orderbook sends correct message."""
        mock_ws = AsyncMock()
        ws_client._ws = mock_ws

        await ws_client.subscribe_orderbook("MARKET-1")

        mock_ws.send.assert_called_once()
        sent_msg = json.loads(mock_ws.send.call_args[0][0])
        assert sent_msg["channel"] == "orderbook"
        assert sent_msg["market_id"] == "MARKET-1"


class TestPolymarketWebSocketListen:
    """Test listen method."""

    @pytest.mark.asyncio
    async def test_listen_raises_when_not_connected(self, ws_client):
        """Test listen raises when not connected."""
        with pytest.raises(RuntimeError, match="WebSocket not connected"):
            await ws_client.listen(lambda x: None)


class TestPolymarketWebSocketReconnect:
    """Test reconnection logic."""

    @pytest.mark.asyncio
    async def test_reconnect_skips_if_not_running(self, ws_client):
        """Test reconnect does nothing if not running."""
        ws_client._running = False

        # Should not raise
        await ws_client._reconnect()

    @pytest.mark.asyncio
    async def test_reconnect_resubscribes(self, ws_client, mocker):
        """Test reconnect resubscribes to previous subscriptions."""
        async def mock_connect(*args, **kwargs):
            return AsyncMock()
        mocker.patch("websockets.connect", side_effect=mock_connect)
        mocker.patch("asyncio.sleep")

        ws_client._running = True
        ws_client._subscriptions.add("MARKET-1")
        ws_client._subscriptions.add("MARKET-2")

        await ws_client._reconnect()


class TestPolymarketWebSocketParseMessage:
    """Test message parsing."""

    def test_parse_markets_message(self, ws_client):
        """Test parsing markets message."""
        data = {
            "channel": "markets",
            "market_id": "MARKET-1",
            "bid": 0.55,
            "ask": 0.60,
            "last_price": 0.57,
            "volume": 1000
        }

        result = ws_client._parse_message(data)

        assert result is not None
        assert result.market_id == "MARKET-1"
        assert result.bid_price == Decimal("0.55")
        assert result.ask_price == Decimal("0.60")
        assert result.venue == "polymarket"

    def test_parse_trades_message(self, ws_client):
        """Test parsing trades message."""
        data = {
            "channel": "trades",
            "trade_id": "t1",
            "market_id": "MARKET-1",
            "order_id": "o1",
            "side": "buy",
            "size": 10,
            "price": 0.55,
            "fee": 0.01,
            "timestamp": "2024-01-15T10:00:00Z"
        }

        result = ws_client._parse_message(data)

        assert result is not None
        assert result.trade_id == "t1"
        assert result.size == Decimal("10")
        assert result.venue == "polymarket"

    def test_parse_unknown_message(self, ws_client):
        """Test parsing unknown message type."""
        data = {"channel": "unknown"}
        result = ws_client._parse_message(data)
        assert result is None

    def test_parse_markets_message_with_none_values(self, ws_client):
        """Test parsing markets message with None values."""
        data = {
            "channel": "markets",
            "market_id": "MARKET-1"
        }

        result = ws_client._parse_message(data)

        assert result is not None
        assert result.market_id == "MARKET-1"
        assert result.bid_price is None
        assert result.ask_price is None
