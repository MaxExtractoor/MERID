"""Tests for merid/event_venues/polymarket/client.py - Batch 53 (3-5 tests)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.polymarket.client import PolymarketVenueClient
from merid.event_venues.polymarket.models import PolymarketConfig


class TestPolymarketVenueClient:
    """Tests for PolymarketVenueClient (small batch)."""

    def test_venue_name(self):
        """Test venue_name property."""
        client = PolymarketVenueClient()
        assert client.venue_name == "polymarket"

    def test_init_default_config(self):
        """Test initialization with default config."""
        client = PolymarketVenueClient()
        assert client.config is not None
        assert client._http_client is None

    def test_init_custom_config(self):
        """Test initialization with custom config."""
        config = PolymarketConfig(api_key="test_key")
        client = PolymarketVenueClient(config=config)
        assert client.config.api_key == "test_key"

    @pytest.mark.asyncio
    async def test_connect(self):
        """Test connect method initializes client."""
        client = PolymarketVenueClient()
        
        await client.connect()
        
        assert client._http_client is not None
        await client.close()

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close method."""
        client = PolymarketVenueClient()
        
        await client.connect()
        assert client._http_client is not None
        
        await client.close()
        # Client should be closed
