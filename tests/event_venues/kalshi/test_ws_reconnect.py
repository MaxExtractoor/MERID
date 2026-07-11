"""WebSocket reconnection tests for Kalshi.

Tests verify auto-reconnect behavior and subscription restoration.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.kalshi.ws import KalshiWebSocket
from core.fault_manager import reset_fault_manager


@pytest.fixture(autouse=True)
def _isolate_fault_manager():
    """Reset the process-wide ``FaultManager`` around each test.

    ``KalshiWebSocket._reconnect`` consults ``can_attempt_reconnect("kalshi")``
    and short-circuits once the venue circuit breaker opens.  Without this
    fixture, failure state from earlier tests in the session leaks into
    later tests and silently blocks reconnects — breaking assertions that
    are otherwise correct for the code under test.
    """
    reset_fault_manager()
    try:
        yield
    finally:
        reset_fault_manager()


class TestKalshiWebSocketReconnect:
    """Tests for Kalshi WebSocket reconnection logic."""
    
    @pytest.fixture
    def ws_client(self):
        """Create WebSocket client for testing."""
        return KalshiWebSocket()
    
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
            
            # First reconnect attempt
            initial_delay = ws_client._reconnect_delay
            
            with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
                await ws_client._reconnect()
                mock_sleep.assert_called_once()
                
            # Delay should double
            assert ws_client._reconnect_delay == initial_delay * 2
    
    @pytest.mark.asyncio
    async def test_reconnect_delay_capped_at_max(self, ws_client):
        """Reconnect delay is capped at max."""
        ws_client._running = True
        ws_client._reconnect_delay = 32.0  # Already high
        
        with patch.object(ws_client, 'connect', new_callable=AsyncMock) as mock_connect:
            mock_connect.side_effect = ConnectionError("Failed")
            
            with patch('asyncio.sleep', new_callable=AsyncMock):
                await ws_client._reconnect()
                await ws_client._reconnect()
                
            # Should be capped at 60
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
        ws_client._ticker_subscriptions = {"MARKET1", "MARKET2"}
        
        with patch.object(ws_client, 'connect', new_callable=AsyncMock):
            with patch.object(ws_client, 'subscribe_quotes', new_callable=AsyncMock) as mock_sub:
                with patch('asyncio.sleep', new_callable=AsyncMock):
                    await ws_client._reconnect()
                    
                # Should resubscribe to markets
                mock_sub.assert_called_once()
                ids = mock_sub.call_args.kwargs.get("market_ids") or []
                assert "MARKET1" in ids
                assert "MARKET2" in ids
    
    @pytest.mark.asyncio
    async def test_reconnect_skips_orderbook_in_quotes(self, ws_client):
        """Reconnect filters orderbook subscriptions from quotes."""
        ws_client._running = True
        ws_client._ticker_subscriptions = {"MARKET1"}
        ws_client._orderbook_tickers = {"MARKET2"}
        
        with patch.object(ws_client, 'connect', new_callable=AsyncMock):
            with patch.object(ws_client, 'subscribe_quotes', new_callable=AsyncMock) as mock_sub:
                with patch.object(ws_client, 'subscribe_orderbooks_batch', new_callable=AsyncMock):
                    with patch('asyncio.sleep', new_callable=AsyncMock):
                        await ws_client._reconnect()
                    
                # Should only subscribe to MARKET1 for quotes; orderbook uses separate batch call
                ids = mock_sub.call_args.kwargs.get("market_ids") or []
                assert "MARKET1" in ids
                assert "MARKET2" not in ids
    
    @pytest.mark.asyncio
    async def test_successful_connect_resets_delay(self, ws_client):
        """Successful connect resets reconnect delay."""
        ws_client._reconnect_delay = 16.0  # Elevated from previous failures
        
        mock_ws = AsyncMock()
        with patch('websockets.connect', new_callable=AsyncMock, return_value=mock_ws):
            await ws_client.connect()
            
        assert ws_client._reconnect_delay == 1.0


class TestKalshiWebSocketConnectionErrors:
    """Tests for connection error handling."""
    
    @pytest.fixture
    def ws_client(self):
        return KalshiWebSocket()
    
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

        # Simulate connection error during listen
        async def raise_error():
            raise ConnectionError("Connection lost")
            yield  # Make it a generator

        ws_client._ws.__aiter__ = lambda self: raise_error()

        with patch.object(ws_client, '_reconnect', new_callable=AsyncMock) as mock_reconnect:
            # Stop after first reconnect attempt
            async def stop_running():
                ws_client._running = False
            mock_reconnect.side_effect = stop_running

            try:
                await ws_client.listen(AsyncMock())
                mock_reconnect.assert_called_once()
            finally:
                # Ensure proper cleanup
                ws_client._running = False
    
    @pytest.mark.asyncio
    async def test_close_clears_subscriptions(self, ws_client):
        """Close clears all subscriptions."""
        ws_client._subscriptions = {"MARKET1", "MARKET2", "orderbook:MARKET3"}
        ws_client._ws = AsyncMock()
        
        await ws_client.close()
        
        assert len(ws_client._subscriptions) == 0
        assert not ws_client._running


class TestKalshiWebSocketAuth:
    """Tests for WebSocket authentication."""

    @pytest.fixture
    def ws_client(self):
        return KalshiWebSocket()

    @pytest.mark.asyncio
    async def test_connect_sends_kalshi_auth_headers(self, ws_client):
        """connect() always passes KALSHI-ACCESS-KEY/SIGNATURE/TIMESTAMP headers.

        The WS implementation uses RSA-PSS signing (not Bearer token), so headers
        will always contain the three Kalshi-specific keys.
        """
        mock_ws = AsyncMock()
        with patch('websockets.connect', new_callable=AsyncMock, return_value=mock_ws) as mock_connect:
            try:
                await ws_client.connect()

                call_kwargs = mock_connect.call_args[1]
                headers = call_kwargs.get("additional_headers") or call_kwargs.get("extra_headers") or {}
                assert 'KALSHI-ACCESS-KEY' in headers
                assert 'KALSHI-ACCESS-SIGNATURE' in headers
                assert 'KALSHI-ACCESS-TIMESTAMP' in headers
            finally:
                # Ensure proper cleanup
                ws_client._running = False
                if ws_client._ws:
                    await ws_client.close()

    @pytest.mark.asyncio
    async def test_connect_raises_when_no_private_key_path(self):
        """connect() raises ValueError when private_key_path is not configured."""
        cfg = MagicMock()
        cfg.private_key_path = None
        cfg.private_key_pem = None
        cfg.api_key = "test-key"
        cfg.ws_url = "wss://example.com/ws"

        client = KalshiWebSocket.__new__(KalshiWebSocket)
        client.config = cfg
        client._ws = None
        client._subscriptions = set()
        client._running = False
        client._reconnect_delay = 1.0
        client._max_reconnect_delay = 60.0
        client._auth_token = None

        with pytest.raises((ValueError, AttributeError)):
            await client.connect()
