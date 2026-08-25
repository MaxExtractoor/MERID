"""Tests for merid/event_venues/kalshi/client.py - Batch 71."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.models import KalshiConfig


class TestKalshiVenueClient:
    """Tests for KalshiVenueClient."""

    def test_venue_name(self):
        """Test venue_name property."""
        client = KalshiVenueClient()
        assert client.venue_name == "kalshi"

    def test_init_default(self):
        """Test initialization."""
        client = KalshiVenueClient()
        assert client.config is not None
        assert client._http_client is None
        assert client._auth_token is None

    @pytest.mark.asyncio
    async def test_connect(self):
        """Test connect initializes client."""
        client = KalshiVenueClient()
        with patch.object(client, '_authenticate', new_callable=AsyncMock):
            await client.connect()
            assert client._http_client is not None

    @pytest.mark.asyncio
    async def test_authenticate_no_credentials(self):
        """Test authentication with no credentials."""
        client = KalshiVenueClient()
        client._http_client = MagicMock()
        await client._authenticate()
        assert client._auth_token is None

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close."""
        client = KalshiVenueClient()
        mock_client = MagicMock()
        mock_client.aclose = AsyncMock()
        mock_client.is_closed = False
        client._http_client = mock_client
        
        await client.close()
        mock_client.aclose.assert_called_once()
