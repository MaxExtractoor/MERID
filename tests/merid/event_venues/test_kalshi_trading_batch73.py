"""Tests for merid/event_venues/kalshi/trading.py - Batch 73."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.kalshi.trading import KalshiTrader
from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.models import KalshiConfig


class TestKalshiTrader:
    """Tests for KalshiTrader."""

    def test_init_default(self):
        """Test initialization with default client."""
        trader = KalshiTrader()
        assert trader.client is not None

    def test_init_with_client(self):
        """Test initialization with provided client."""
        client = KalshiVenueClient(config=KalshiConfig())
        trader = KalshiTrader(client=client)
        assert trader.client is client

    @pytest.mark.asyncio
    async def test_connect(self):
        """Test connect delegates to client."""
        trader = KalshiTrader()
        with patch.object(trader.client, 'connect', new_callable=AsyncMock) as mock_connect:
            await trader.connect()
            mock_connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close delegates to client."""
        trader = KalshiTrader()
        with patch.object(trader.client, 'close', new_callable=AsyncMock) as mock_close:
            await trader.close()
            mock_close.assert_called_once()
