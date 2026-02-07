"""WebSocket reconnection tests for Polymarket.

Tests verify auto-reconnect behavior and subscription restoration.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.polymarket.ws import PolymarketWebSocket


class TestPolymarketWebSocketReconnect:
    """Tests for Polymarket WebSocket reconnection logic."""
    
    @pytest.fixture
    def ws_client(self):
        """Create WebSocket client for testing."""
        return PolymarketWebSocket()
    
    def test_initial_reconnect_delay(self, ws_client):
        """Initial reconnect delay is 1 second."""
        assert ws_client._reconnect_delay == 1.0
    
    def test_max_reconnect_delay(self, ws_client):
        """Max reconnect delay is 60 seconds."""
        assert ws_client._max_reconnect_delay == 60.0
    
    @pytest.mark.asyncio
    async def test_reconnect_increases_delay(self, ws_client):
        """Reconnect delay increases exponentially."""
        ws_client._running = True
        
        with patch.object(ws_client, 'connect', new_callable=AsyncMock) as mock_connect:
            mock_connect.side_effect = ConnectionError("Failed")
            
            initial_delay = ws_client._reconnect_delay
            
            with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
                await ws_client._reconnect()
                mock_sleep.assert_called_once()
                
            assert ws_client._reconnect_delay == initial_delay * 2
    
    @pytest.mark.asyncio
    async def test_reconnect_delay_capped_at_max(self, ws_client):
        """Reconnect delay is capped at max."""
        ws_client._running = True
        ws_client._reconnect_delay = 32.0
        
        with patch.object(ws_client, 'connect', new_callable=AsyncMock) as mock_connect:
            mock_connect.side_effect = ConnectionError("Failed")
            
            with patch('asyncio.sleep', new_callable=AsyncMock):
                await ws_client._reconnect()
                await ws_client._reconnect()
                
            assert ws_client._reconnect_delay <= ws_client._max_reconnect_delay
    
    @pytest.mark.asyncio
    async def test_reconnect_not_running_exits(self, ws_client):
        """Reconnect exits early if not running."""
        ws_client._running = False
        
        with patch.object(ws_client, 'connect', new_callable=AsyncMock) as mock_connect:
            await ws_client._reconnect()
            mock_connect.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_reconnect_restores_subscriptions(self, ws_client):
        """Reconnect restores market subscriptions."""
        ws_client._running = True
        ws_client._subscriptions = {"MARKET1", "MARKET2"}
        
        with patch.object(ws_client, 'connect', new_callable=AsyncMock):
            with patch.object(ws_client, 'subscribe_quotes', new_callable=AsyncMock) as mock_sub:
                with patch('asyncio.sleep', new_callable=AsyncMock):
                    await ws_client._reconnect()
                    
                mock_sub.assert_called_once()
                call_args = mock_sub.call_args[0][0]
                assert "MARKET1" in call_args
                assert "MARKET2" in call_args
    
    @pytest.mark.asyncio
    async def test_reconnect_skips_orderbook_in_quotes(self, ws_client):
        """Reconnect filters orderbook subscriptions from quotes."""
        ws_client._running = True
        ws_client._subscriptions = {"MARKET1", "orderbook:MARKET2"}
        
        with patch.object(ws_client, 'connect', new_callable=AsyncMock):
            with patch.object(ws_client, 'subscribe_quotes', new_callable=AsyncMock) as mock_sub:
                with patch('asyncio.sleep', new_callable=AsyncMock):
                    await ws_client._reconnect()
                    
                call_args = mock_sub.call_args[0][0]
                assert "MARKET1" in call_args
                assert "orderbook:MARKET2" not in call_args
    
    @pytest.mark.asyncio
    async def test_successful_connect_resets_delay(self, ws_client):
        """Successful connect resets reconnect delay."""
        ws_client._reconnect_delay = 16.0
        
        mock_ws = AsyncMock()
        with patch('websockets.connect', new_callable=AsyncMock, return_value=mock_ws):
            await ws_client.connect()
            
        assert ws_client._reconnect_delay == 1.0


class TestPolymarketWebSocketConnectionErrors:
    """Tests for connection error handling."""
    
    @pytest.fixture
    def ws_client(self):
        return PolymarketWebSocket()
    
    @pytest.mark.asyncio
    async def test_connect_failure_raises(self, ws_client):
        """Connect failure raises exception."""
        with patch('websockets.connect', new_callable=AsyncMock) as mock_connect:
            mock_connect.side_effect = ConnectionError("Connection refused")
            
            with pytest.raises(ConnectionError):
                await ws_client.connect()
    
    @pytest.mark.asyncio
    async def test_listen_reconnects_on_error(self, ws_client):
        """Listen triggers reconnect on connection error."""
        ws_client._running = True
        ws_client._ws = AsyncMock()
        
        async def raise_error():
            raise ConnectionError("Connection lost")
            yield
        
        ws_client._ws.__aiter__ = lambda self: raise_error()
        
        with patch.object(ws_client, '_reconnect', new_callable=AsyncMock) as mock_reconnect:
            async def stop_running():
                ws_client._running = False
            mock_reconnect.side_effect = stop_running
            
            await ws_client.listen(AsyncMock())
            mock_reconnect.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_close_clears_subscriptions(self, ws_client):
        """Close clears all subscriptions."""
        ws_client._subscriptions = {"MARKET1", "MARKET2", "orderbook:MARKET3"}
        ws_client._ws = AsyncMock()
        
        await ws_client.close()
        
        assert len(ws_client._subscriptions) == 0
        assert not ws_client._running


class TestPolymarketWebSocketMessageParsing:
    """Tests for WebSocket message parsing edge cases."""
    
    @pytest.fixture
    def ws_client(self):
        return PolymarketWebSocket()
    
    def test_parse_unknown_channel_returns_none(self, ws_client):
        """Unknown channel returns None."""
        result = ws_client._parse_message({"channel": "unknown"})
        assert result is None
    
    def test_parse_empty_message_returns_none(self, ws_client):
        """Empty message returns None."""
        result = ws_client._parse_message({})
        assert result is None
    
    def test_parse_markets_channel(self, ws_client):
        """Markets channel parses to QuoteEvent."""
        data = {
            "channel": "markets",
            "market_id": "TEST_MARKET",
            "bid": "0.45",
            "ask": "0.55",
        }
        result = ws_client._parse_message(data)
        
        assert result is not None
        assert result.market_id == "TEST_MARKET"
        assert result.venue == "polymarket"
    
    def test_parse_trades_channel(self, ws_client):
        """Trades channel parses to VenueTrade."""
        data = {
            "channel": "trades",
            "trade_id": "TRADE123",
            "market_id": "TEST_MARKET",
            "side": "buy",
            "size": "100",
            "price": "0.50",
            "fee": "0.01",
        }
        result = ws_client._parse_message(data)
        
        assert result is not None
        assert result.trade_id == "TRADE123"
        assert result.venue == "polymarket"
