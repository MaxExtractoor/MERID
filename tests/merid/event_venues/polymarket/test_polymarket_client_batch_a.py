"""Tests for merid/event_venues/polymarket/client.py - Batch A."""
import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.polymarket.client import PolymarketVenueClient
from merid.event_venues.polymarket.models import PolymarketConfig
from merid.event_venues.base import VenueOrder, MarketFilter


@pytest.fixture
def mock_config():
    return PolymarketConfig(
        api_key="test_key",
        api_secret="test_secret",
        wallet_address="0x123",
        private_key="0xabc"
    )


@pytest.fixture
def client(mock_config):
    return PolymarketVenueClient(config=mock_config)


class TestPolymarketVenueClientLifecycle:
    """Test connect, close methods."""
    
    @pytest.mark.asyncio
    async def test_connect_initializes_http_client(self, client):
        """Test connect creates aiohttp client."""
        with patch("merid.event_venues.polymarket.client.aiohttp.ClientSession") as mock_session:
            mock_instance = MagicMock()
            mock_instance.close = AsyncMock()
            mock_session.return_value = mock_instance
            await client.connect()
            mock_session.assert_called_once()
            assert client._http_client is not None
    
    @pytest.mark.asyncio
    async def test_close_closes_http_client(self, client):
        """Test close properly closes aiohttp client."""
        mock_http = AsyncMock()
        client._http_client = mock_http
        
        await client.close()
        
        mock_http.close.assert_called_once()


class TestPolymarketVenueClientMarketData:
    """Test market data methods."""
    
    @pytest.mark.asyncio
    async def test_list_markets_success(self, client, mocker):
        """Test list_markets returns parsed markets."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=[
            {
                "id": "market-1",
                "question": "Test Question?",
                "description": "A test market",
                "outcomes": [{"outcome": "Yes", "price": 0.55}],
                "active": True
            }
        ])
        
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        
        mock_http = MagicMock()
        mock_http.get = MagicMock(return_value=mock_cm)
        client._http_client = mock_http
        
        filter_params = MarketFilter(limit=10, active_only=True)
        markets = await client.list_markets(filter_params)
        
        assert len(markets) == 1
        assert markets[0].market_id == "market-1"
    
    @pytest.mark.asyncio
    async def test_list_markets_error_returns_empty(self, client):
        """Test list_markets returns empty list on error."""
        mock_response = MagicMock()
        mock_response.status = 500
        
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        
        mock_http = MagicMock()
        mock_http.get = MagicMock(return_value=mock_cm)
        client._http_client = mock_http
        
        markets = await client.list_markets()
        
        assert markets == []
    
    @pytest.mark.asyncio
    async def test_get_market_success(self, client):
        """Test get_market returns single market."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "id": "market-1",
            "question": "Test?",
            "outcomes": [{"outcome": "Yes", "price": 0.6}]
        })
        
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        
        mock_http = MagicMock()
        mock_http.get = MagicMock(return_value=mock_cm)
        client._http_client = mock_http
        
        market = await client.get_market("market-1")
        
        assert market is not None
        assert market.market_id == "market-1"


class TestPolymarketVenueClientTrading:
    """Test trading methods."""
    
    @pytest.mark.asyncio
    async def test_place_order_no_clob_returns_none(self, client):
        """Test place_order returns None when CLOB not initialized."""
        order = VenueOrder(market_id="m1", side="buy", size=Decimal("1"))
        result = await client.place_order(order)
        assert result is None
    
    @pytest.mark.asyncio
    async def test_cancel_order_no_clob_returns_false(self, client):
        """Test cancel_order returns False when CLOB not initialized."""
        result = await client.cancel_order("order_123")
        assert result is False
    
    @pytest.mark.asyncio
    async def test_get_order_no_clob_returns_none(self, client):
        """Test get_order returns None when CLOB not initialized."""
        result = await client.get_order("order_123")
        assert result is None
    
    @pytest.mark.asyncio
    async def test_get_open_orders_no_clob_returns_empty(self, client):
        """Test get_open_orders returns empty list when CLOB not initialized."""
        result = await client.get_open_orders()
        assert result == []


class TestPolymarketVenueClientAccount:
    """Test account data methods."""
    
    @pytest.mark.asyncio
    async def test_get_positions_no_wallet_returns_empty(self, client):
        """Test get_positions returns empty list without wallet."""
        client.config.wallet_address = None
        result = await client.get_positions()
        assert result == []
    
    @pytest.mark.asyncio
    async def test_get_trades_no_wallet_returns_empty(self, client):
        """Test get_trades returns empty list without wallet."""
        client.config.wallet_address = None
        result = await client.get_trades()
        assert result == []
    
    @pytest.mark.asyncio
    async def test_get_balance_returns_usdc(self, client):
        """Test get_balance returns USDC placeholder."""
        result = await client.get_balance()
        assert result["USDC"] == Decimal("0")


class TestPolymarketVenueClientHelpers:
    """Test helper methods."""
    
    def test_parse_market_with_outcomes(self, client):
        """Test _parse_market with outcome data."""
        from datetime import datetime, timezone
        data = {
            "id": "m1",
            "question": "Test?",
            "outcomes": [
                {"outcome": "Yes", "price": 0.6, "bestAskPrice": 0.61, "bestBidPrice": 0.59}
            ]
        }
        result = client._parse_market(data)
        assert result is not None
        assert result.id == "m1"
        assert len(result.outcomes) == 1
    
    def test_to_placed_order(self, client):
        """Test _to_placed_order conversion."""
        from datetime import datetime, timezone
        data = {
            "id": "order_1",
            "marketId": "m1",
            "side": "buy",
            "size": 10,
            "price": 0.5,
            "filled": 5,
            "remaining": 5,
            "status": "partially_filled"
        }
        result = client._to_placed_order(data)
        assert result.order_id == "order_1"
        assert result.status == "partially_filled"
    
    def test_parse_positions_empty(self, client):
        """Test _parse_positions with empty data."""
        data = {"data": {"user": {"positions": []}}}
        result = client._parse_positions(data)
        assert result == []
    
    def test_parse_trades_empty(self, client):
        """Test _parse_trades with empty data."""
        data = {"trades": []}
        result = client._parse_trades(data)
        assert result == []
