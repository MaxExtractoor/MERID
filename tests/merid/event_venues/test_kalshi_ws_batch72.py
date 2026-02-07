"""Tests for merid/event_venues/kalshi/ws.py - Batch 72."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.kalshi.ws import KalshiWebSocket
from merid.event_venues.kalshi.models import KalshiConfig


class TestKalshiWebSocket:
    """Tests for KalshiWebSocket."""

    def test_venue_name(self):
        """Test venue_name property."""
        ws = KalshiWebSocket()
        assert ws.venue_name == "kalshi"

    def test_init_default(self):
        """Test initialization."""
        ws = KalshiWebSocket()
        assert ws.config is not None
        assert ws._ws is None
        assert ws._running is False

    @pytest.mark.asyncio
    async def test_subscribe_quotes_not_connected(self):
        """Test subscribe_quotes raises when not connected."""
        ws = KalshiWebSocket()
        with pytest.raises(RuntimeError, match="WebSocket not connected"):
            await ws.subscribe_quotes(["FED-25DEC-T3.00"])

    @pytest.mark.asyncio
    async def test_subscribe_trades_not_connected(self):
        """Test subscribe_trades raises when not connected."""
        ws = KalshiWebSocket()
        with pytest.raises(RuntimeError, match="WebSocket not connected"):
            await ws.subscribe_trades()

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close."""
        ws = KalshiWebSocket()
        mock_ws = MagicMock()
        mock_ws.close = AsyncMock()
        ws._ws = mock_ws
        ws._running = True
        ws._subscriptions = {"market1"}
        
        await ws.close()
        assert ws._running is False
