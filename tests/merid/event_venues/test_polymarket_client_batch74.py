"""Tests for merid/event_venues/polymarket/client.py - Batch 74."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.polymarket.client import PolymarketVenueClient
from merid.event_venues.polymarket.models import PolymarketConfig


class TestPolymarketVenueClient:
    """Tests for PolymarketVenueClient."""

    def test_venue_name(self):
        """Test venue_name property."""
        client = PolymarketVenueClient()
        assert client.venue_name == "polymarket"

    def test_init_default(self):
        """Test initialization."""
        client = PolymarketVenueClient()
        assert client.config is not None
        assert client._http_client is None

    @pytest.mark.asyncio
    async def test_connect(self):
        """Test connect creates session."""
        client = PolymarketVenueClient()
        await client.connect()
        assert client._http_client is not None
        await client.close()

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close."""
        client = PolymarketVenueClient()
        await client.connect()
        assert client._http_client is not None
        await client.close()
