"""Tests for merid/event_venues/kalshi/client.py."""
import pytest
import respx
from httpx import Response
from unittest.mock import Mock, patch

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.models import KalshiConfig


class TestKalshiVenueClientInitialization:
    """Test KalshiVenueClient initialization."""

    def test_default_initialization(self):
        """Test default initialization."""
        client = KalshiVenueClient()
        assert client.config is not None
        assert client._http_client is None
        assert client._auth_token is None
        assert client._member_id is None

    def test_custom_config(self):
        """Test initialization with custom config."""
        config = KalshiConfig(use_demo=True)
        client = KalshiVenueClient(config)
        assert client.config is config
        assert client.config.use_demo is True

    def test_venue_name(self):
        """Test venue_name property."""
        client = KalshiVenueClient()
        assert client.venue_name == "kalshi"


class TestKalshiVenueClientConnect:
    """Test KalshiVenueClient connect method."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_connect_with_password_auth(self):
        """Test connect with email/password authentication."""
        config = KalshiConfig(
            email="test@example.com",
            password="secret",
            use_demo=True
        )
        client = KalshiVenueClient(config)
        
        # Mock login endpoint
        respx.post(f"{config.base_url}/login").mock(
            return_value=Response(200, json={
                "token": "auth_token_123",
                "member_id": "member_456"
            })
        )
        
        await client.connect()
        
        assert client._http_client is not None
        assert client._auth_token == "auth_token_123"
        assert client._member_id == "member_456"
        assert client._http_client.headers["Authorization"] == "Bearer auth_token_123"

    @pytest.mark.asyncio
    async def test_connect_no_credentials(self):
        """Test connect with no credentials logs warning."""
        config = KalshiConfig()
        client = KalshiVenueClient(config)
        
        # Should not raise, just log warning
        await client.connect()
        assert client._http_client is not None


class TestKalshiVenueClientClose:
    """Test KalshiVenueClient close method."""

    @pytest.mark.asyncio
    async def test_close(self):
        """Test closing the client."""
        client = KalshiVenueClient()
        await client.connect()
        
        # Should not raise
        await client.close()

    @pytest.mark.asyncio
    async def test_close_without_connect(self):
        """Test closing without connecting."""
        client = KalshiVenueClient()
        # Should not raise
        await client.close()


class TestKalshiVenueClientAuthErrors:
    """Test KalshiVenueClient authentication error handling."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_auth_failure_raises(self):
        """Test authentication failure raises error."""
        config = KalshiConfig(
            email="test@example.com",
            password="wrong",
            use_demo=True
        )
        client = KalshiVenueClient(config)
        
        respx.post(f"{config.base_url}/login").mock(
            return_value=Response(401, text="Unauthorized")
        )
        
        with pytest.raises(Exception):
            await client.connect()
