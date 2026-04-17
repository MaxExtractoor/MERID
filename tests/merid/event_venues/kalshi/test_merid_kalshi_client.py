"""Tests for merid/event_venues/kalshi/client.py."""
import pytest
import respx
from httpx import Response
from unittest.mock import Mock, MagicMock, patch

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
    async def test_connect_with_password_auth(self):
        """Test connect with email/password authentication."""
        from unittest.mock import AsyncMock, patch
        config = KalshiConfig(
            email="test@example.com",
            password="secret",
            use_demo=True
        )
        # Ensure RSA path is not triggered
        config.api_key = None
        config.private_key_path = None
        config.private_key_pem = None
        client = KalshiVenueClient(config)

        with patch.object(client, '_authenticate_password', new_callable=AsyncMock) as mock_pw:
            async def _set_token():
                client._auth_token = "auth_token_123"
                client._member_id = "member_456"
                if client._http_client:
                    client._http_client.headers["Authorization"] = "Bearer auth_token_123"
            mock_pw.side_effect = _set_token
            await client.connect()

        assert client._http_client is not None
        assert client._auth_token == "auth_token_123"
        assert client._member_id == "member_456"
        mock_pw.assert_called_once()

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
    async def test_auth_failure_raises(self):
        """Test authentication failure raises error."""
        from unittest.mock import AsyncMock, patch
        import httpx

        config = KalshiConfig(
            email="test@example.com",
            password="wrong",
            use_demo=True
        )
        config.api_key = None
        config.private_key_path = None
        config.private_key_pem = None
        client = KalshiVenueClient(config)

        with patch.object(client, '_authenticate_password', new_callable=AsyncMock,
                          side_effect=httpx.HTTPStatusError("401 Unauthorized",
                                                             request=MagicMock(),
                                                             response=MagicMock(status_code=401))):
            with pytest.raises(Exception):
                await client.connect()
