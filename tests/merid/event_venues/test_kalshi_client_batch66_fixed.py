"""Tests for merid/event_venues/kalshi/client.py - Batch 66."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.models import KalshiConfig


class TestKalshiVenueClient:
    """Tests for KalshiVenueClient."""

    @pytest.fixture
    def client(self):
        return KalshiVenueClient(config=KalshiConfig())

    def test_venue_name(self, client):
        """Test venue_name property."""
        assert client.venue_name == "kalshi"

    def test_init_default(self, client):
        """Test initialization."""
        assert client.config is not None
        assert client._http_client is None
        assert client._auth_token is None

    @pytest.mark.asyncio
    async def test_connect(self, client):
        """Test connect initializes client."""
        with patch.object(client, '_authenticate', new_callable=AsyncMock):
            await client.connect()
            assert client._http_client is not None

    @pytest.mark.asyncio
    async def test_authenticate_no_credentials(self, client):
        """Test authentication with no credentials."""
        await client._authenticate()
        assert client._auth_token is None

    @pytest.mark.asyncio
    async def test_close(self, client):
        """Test close."""
        mock_client = MagicMock()
        mock_client.aclose = AsyncMock()
        client._http_client = mock_client
        
        await client.close()
        mock_client.aclose.assert_called_once()
