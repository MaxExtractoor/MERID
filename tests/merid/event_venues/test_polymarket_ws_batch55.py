"""Tests for merid/event_venues/polymarket/ws.py - Batch 55 (3-5 tests)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.polymarket.ws import PolymarketWebSocket
from merid.event_venues.polymarket.models import PolymarketConfig


class TestPolymarketWebSocket:
    """Tests for PolymarketWebSocket (small batch)."""

    def test_venue_name(self):
        """Test venue_name property."""
        ws = PolymarketWebSocket()
        assert ws.venue_name == "polymarket"

    def test_init_default_config(self):
        """Test initialization with default config."""
        ws = PolymarketWebSocket()
        assert ws.config is not None
        assert ws._ws is None
        assert ws._running is False
        assert ws._reconnect_delay == 1.0

    def test_init_custom_config(self):
        """Test initialization with custom config."""
        config = PolymarketConfig(api_key="test_key")
        ws = PolymarketWebSocket(config=config)
        assert ws.config.api_key == "test_key"

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close method."""
        ws = PolymarketWebSocket()
        mock_ws = MagicMock()
        mock_ws.close = AsyncMock()
        ws._ws = mock_ws
        ws._running = True
        ws._subscriptions = {"market1", "market2"}
        
        await ws.close()
        
        assert ws._running is False
        assert len(ws._subscriptions) == 0
        mock_ws.close.assert_called_once()
