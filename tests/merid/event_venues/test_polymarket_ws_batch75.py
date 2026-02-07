"""Tests for merid/event_venues/polymarket/ws.py - Batch 75."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.polymarket.ws import PolymarketWebSocket
from merid.event_venues.polymarket.models import PolymarketConfig


class TestPolymarketWebSocket:
    """Tests for PolymarketWebSocket."""

    def test_venue_name(self):
        """Test venue_name property."""
        ws = PolymarketWebSocket()
        assert ws.venue_name == "polymarket"

    def test_init_default(self):
        """Test initialization."""
        ws = PolymarketWebSocket()
        assert ws.config is not None
        assert ws._ws is None
        assert ws._running is False

    @pytest.mark.asyncio
    async def test_subscribe_quotes_not_connected(self):
        """Test subscribe_quotes raises when not connected."""
        ws = PolymarketWebSocket()
        with pytest.raises(RuntimeError, match="WebSocket not connected"):
            await ws.subscribe_quotes(["market1"])

    @pytest.mark.asyncio
    async def test_subscribe_trades_not_connected(self):
        """Test subscribe_trades raises when not connected."""
        ws = PolymarketWebSocket()
        with pytest.raises(RuntimeError, match="WebSocket not connected"):
            await ws.subscribe_trades()

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close."""
        ws = PolymarketWebSocket()
        mock_ws = MagicMock()
        mock_ws.close = AsyncMock()
        ws._ws = mock_ws
        ws._running = True
        ws._subscriptions = {"market1"}
        
        await ws.close()
        assert ws._running is False
