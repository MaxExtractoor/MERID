"""Tests for merid/event_venues/kalshi/client.py - Batch A."""
import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.models import KalshiConfig
from merid.event_venues.base import VenueOrder, MarketFilter


@pytest.fixture
def mock_config():
    return KalshiConfig(
        api_key="test_key",
        private_key_path="/test/path",
        email="test@example.com",
        password="test_pass",
        use_demo=True
    )


@pytest.fixture
def client(mock_config):
    return KalshiVenueClient(config=mock_config)


class TestKalshiVenueClientLifecycle:
    """Test connect, auth, close methods."""
    
    @pytest.mark.asyncio
    async def test_connect_initializes_http_client(self, client):
        """Test connect creates httpx client with correct headers."""
        with patch.object(client, '_authenticate', new_callable=AsyncMock) as mock_auth:
            await client.connect()
            
            assert client._http_client is not None
            assert client._http_client.headers["User-Agent"] == "MERID-Kalshi-Client/1.0"
            assert client._http_client.headers["Content-Type"] == "application/json"
            mock_auth.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_close_closes_http_client(self, client):
        """Test close properly closes httpx client."""
        mock_http = AsyncMock()
        client._http_client = mock_http
        
        await client.close()
        
        mock_http.aclose.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_authenticate_with_password(self, client):
        """Test password authentication flow."""
        mock_http = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "token": "test_token_123",
            "member_id": "member_456"
        }
        mock_http.post.return_value = mock_response
        client._http_client = mock_http
        
        await client._authenticate_password()
        
        assert client._auth_token == "test_token_123"
        assert client._member_id == "member_456"
        # Headers is a MagicMock, verify __setitem__ was called
        client._http_client.headers.__setitem__.assert_called_with("Authorization", "Bearer test_token_123")
    
    @pytest.mark.asyncio
    async def test_authenticate_rsa_fallback_to_password(self, client):
        """Test RSA auth falls back to password when available."""
        with patch.object(client, '_authenticate_password', new_callable=AsyncMock) as mock_pw:
            await client._authenticate_rsa()
            mock_pw.assert_called_once()


class TestKalshiVenueClientMarketData:
    """Test market data methods."""
    
    @pytest.mark.asyncio
    async def test_list_markets_success(self, client):
        """Test list_markets returns parsed markets."""
        mock_http = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "markets": [
                {
                    "ticker": "MARKET-1",
                    "title": "Test Market",
                    "description": "A test market",
                    "yes_price": 55,
                    "no_price": 45,
                    "status": "active"
                }
            ]
        }
        mock_http.get.return_value = mock_response
        client._http_client = mock_http
        
        filter_params = MarketFilter(limit=10, active_only=True)
        markets = await client.list_markets(filter_params)
        
        assert len(markets) == 1
        assert markets[0].market_id == "MARKET-1"
        assert markets[0].venue == "kalshi"
        mock_http.get.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_list_markets_error_returns_empty(self, client):
        """Test list_markets returns empty list on error."""
        mock_http = AsyncMock()
        mock_http.get.side_effect = ConnectionError("Network error")
        client._http_client = mock_http
        
        markets = await client.list_markets()
        
        assert markets == []
    
    @pytest.mark.asyncio
    async def test_get_market_success(self, client):
        """Test get_market returns single market."""
        mock_http = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "market": {
                "ticker": "MARKET-1",
                "title": "Test Market",
                "yes_price": 60,
                "no_price": 40
            }
        }
        mock_http.get.return_value = mock_response
        client._http_client = mock_http
        
        market = await client.get_market("MARKET-1")
        
        assert market is not None
        assert market.market_id == "MARKET-1"
    
    @pytest.mark.asyncio
    async def test_get_orderbook_success(self, client):
        """Test get_orderbook returns VenueOrderBook."""
        mock_http = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "yes_bid": 50,
            "yes_ask": 55,
            "no_bid": 45,
            "no_ask": 50
        }
        mock_http.get.return_value = mock_response
        client._http_client = mock_http
        
        orderbook = await client.get_orderbook("MARKET-1")
        
        assert orderbook is not None
        assert orderbook.market_id == "MARKET-1"
        assert len(orderbook.bids) == 2
        assert len(orderbook.asks) == 2


class TestKalshiVenueClientTrading:
    """Test trading methods."""
    
    @pytest.mark.asyncio
    async def test_place_order_success(self, client):
        """Test place_order returns PlacedOrder."""
        mock_http = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "order": {
                "order_id": "order_123",
                "ticker": "MARKET-1",
                "action": "buy",
                "count": 10,
                "price": 50,
                "status": "pending"
            }
        }
        mock_http.post.return_value = mock_response
        client._http_client = mock_http
        
        order = VenueOrder(
            market_id="MARKET-1",
            side="buy",
            size=Decimal("10"),
            price=Decimal("0.5"),
            order_type="limit"
        )
        placed = await client.place_order(order)
        
        assert placed is not None
        assert placed.order_id == "order_123"
        assert placed.status == "pending"
    
    @pytest.mark.asyncio
    async def test_cancel_order_success(self, client):
        """Test cancel_order returns True on success."""
        mock_http = AsyncMock()
        mock_response = MagicMock()
        mock_http.delete.return_value = mock_response
        client._http_client = mock_http
        
        result = await client.cancel_order("order_123")
        
        assert result is True
        mock_http.delete.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_order_success(self, client):
        """Test get_order returns PlacedOrder."""
        mock_http = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "order": {
                "order_id": "order_123",
                "ticker": "MARKET-1",
                "action": "buy",
                "count": 5,
                "status": "filled"
            }
        }
        mock_http.get.return_value = mock_response
        client._http_client = mock_http
        
        order = await client.get_order("order_123")
        
        assert order is not None
        assert order.order_id == "order_123"
        assert order.status == "filled"


class TestKalshiVenueClientAccount:
    """Test account data methods."""
    
    @pytest.mark.asyncio
    async def test_get_positions_success(self, client):
        """Test get_positions returns list of positions."""
        mock_http = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "positions": [
                {
                    "ticker": "MARKET-1",
                    "side": "yes",
                    "count": 100,
                    "avg_price": 50
                }
            ]
        }
        mock_http.get.return_value = mock_response
        client._http_client = mock_http
        
        positions = await client.get_positions()
        
        assert len(positions) == 1
        assert positions[0].market_id == "MARKET-1"
    
    @pytest.mark.asyncio
    async def test_get_balance_success(self, client):
        """Test get_balance returns USD balance."""
        mock_http = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "balance": {
                "balance": 10000,  # cents
                "locked_balance": 2000
            }
        }
        mock_http.get.return_value = mock_response
        client._http_client = mock_http
        
        balance = await client.get_balance()
        
        assert balance["USD"] == Decimal("100")  # converted from cents
        assert balance["locked"] == Decimal("20")


class TestKalshiVenueClientHelpers:
    """Test helper methods."""
    
    def test_parse_datetime_unix_timestamp(self, client):
        """Test _parse_datetime with unix timestamp."""
        ts = int(datetime.now(timezone.utc).timestamp() * 1000)
        result = client._parse_datetime(ts)
        assert isinstance(result, datetime)
    
    def test_parse_datetime_iso_string(self, client):
        """Test _parse_datetime with ISO string."""
        dt_str = "2024-01-15T10:30:00Z"
        result = client._parse_datetime(dt_str)
        assert isinstance(result, datetime)
    
    def test_parse_datetime_none(self, client):
        """Test _parse_datetime returns None for None input."""
        result = client._parse_datetime(None)
        assert result is None
    
    def test_to_venue_orderbook_empty(self, client):
        """Test _to_venue_orderbook with minimal data."""
        data = {}
        result = client._to_venue_orderbook(data, "MARKET-1")
        assert result.market_id == "MARKET-1"
        assert result.bids == []
        assert result.asks == []
