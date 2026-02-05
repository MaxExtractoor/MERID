"""Tests for merid/event_venues/kalshi/client.py - Batch 52 (3-5 tests)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.models import KalshiConfig


class TestKalshiVenueClient:
    """Tests for KalshiVenueClient (small batch)."""

    def test_venue_name(self):
        """Test venue_name property."""
        client = KalshiVenueClient()
        assert client.venue_name == "kalshi"

    def test_init_default_config(self):
        """Test initialization with default config."""
        client = KalshiVenueClient()
        assert client.config is not None
        assert client._http_client is None
        assert client._auth_token is None

    def test_init_custom_config(self):
        """Test initialization with custom config."""
        config = KalshiConfig(api_key="test_key")
        client = KalshiVenueClient(config=config)
        assert client.config.api_key == "test_key"

    @pytest.mark.asyncio
    async def test_connect(self):
        """Test connect method initializes client."""
        client = KalshiVenueClient()
        
        with patch.object(client, '_authenticate', new_callable=AsyncMock):
            await client.connect()
            
        assert client._http_client is not None

    @pytest.mark.asyncio
    async def test_connect_with_context(self):
        """Test connect creates client with proper headers."""
        client = KalshiVenueClient()
        
        with patch.object(client, '_authenticate', new_callable=AsyncMock):
            await client.connect()
            
        assert "User-Agent" in client._http_client.headers
        assert "MERID-Kalshi" in client._http_client.headers["User-Agent"]
