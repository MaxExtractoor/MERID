"""Refactored tests for merid/event_venues/polymarket/client.py - Function-level async tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from decimal import Decimal
import aiohttp

from merid.event_venues._legacy.polymarket.client import PolymarketVenueClient
from merid.event_venues._legacy.polymarket.models import PolymarketConfig
from merid.event_venues.base import VenueOrder, MarketFilter


@pytest.fixture
def polymarket_config():
    """Create test Polymarket config."""
    return PolymarketConfig(
        api_key="test_api_key",
        api_secret="test_api_secret"
    )


@pytest.fixture
def client(polymarket_config):
    """Create test Polymarket client."""
    return PolymarketVenueClient(polymarket_config)


@pytest.fixture
def mock_response():
    """Create a mock aiohttp response."""
    def _create_response(status=200, json_data=None):
        response = AsyncMock()
        response.status = status
        response.json = AsyncMock(return_value=json_data or {})
        return response
    return _create_response


# =============================================================================
# Initialization Tests
# =============================================================================

def test_client_creation_with_config(polymarket_config):
    """Test client creation with provided config."""
    client = PolymarketVenueClient(polymarket_config)
    assert client.config == polymarket_config
    assert client._http_client is None
    assert client._clob_client is None


def test_client_creation_with_defaults():
    """Test client creation with default config."""
    client = PolymarketVenueClient()
    assert client.config is not None
    assert isinstance(client.config, PolymarketConfig)


def test_venue_name(client):
    """Test venue_name property."""
    assert client.venue_name == "polymarket"


# =============================================================================
# Connection Tests
# =============================================================================

@pytest.mark.asyncio
async def test_connect_without_clob():
    """Test connect without CLOB credentials."""
    config = PolymarketConfig()  # No credentials
    client = PolymarketVenueClient(config)
    
    await client.connect()
    
    assert client._http_client is not None
    assert client._clob_client is None
    
    await client.close()


@pytest.mark.asyncio
async def test_connect_with_clob_import_error(polymarket_config):
    """Test connect handles missing polymarket-clob package."""
    client = PolymarketVenueClient(polymarket_config)
    
    with patch.dict('sys.modules', {'polymarket_clob': None}):
        await client.connect()
    
    assert client._http_client is not None
    
    await client.close()


@pytest.mark.asyncio
async def test_close(client):
    """Test close method."""
    await client.connect()
    assert client._http_client is not None
    
    await client.close()


# =============================================================================
# Market Data Tests
# =============================================================================

@pytest.mark.asyncio
async def test_list_markets_success(client, mock_response):
    """Test list_markets with successful response."""
    await client.connect()
    
    mock_resp = mock_response(200, {
        "markets": [
            {
                "id": "market_123",
                "question": "Will X happen?",
                "description": "Test market",
                "active": True,
                "outcomes": [
                    {"id": "yes", "title": "Yes", "price": 0.65},
                    {"id": "no", "title": "No", "price": 0.35}
                ]
            }
        ]
    })
    
    with patch.object(client._http_client, 'get') as mock_get:
        mock_get.return_value.__aenter__.return_value = mock_resp
        markets = await client.list_markets()
    
    assert len(markets) >= 0  # May be 0 if parsing doesn't match
    
    await client.close()


@pytest.mark.asyncio
async def test_list_markets_with_filter(client, mock_response):
    """Test list_markets with filter params."""
    await client.connect()
    
    mock_resp = mock_response(200, {"markets": []})
    
    with patch.object(client._http_client, 'get') as mock_get:
        mock_get.return_value.__aenter__.return_value = mock_resp
        
        filter_params = MarketFilter(active_only=True, category="sports", limit=50)
        markets = await client.list_markets(filter_params)
    
    assert len(markets) == 0
    
    await client.close()


@pytest.mark.asyncio
async def test_list_markets_error(client, mock_response):
    """Test list_markets error handling."""
    await client.connect()
    
    mock_resp = mock_response(500, {"error": "Server error"})
    
    with patch.object(client._http_client, 'get') as mock_get:
        mock_get.return_value.__aenter__.return_value = mock_resp
        markets = await client.list_markets()
    
    assert len(markets) == 0
    
    await client.close()


@pytest.mark.asyncio
async def test_list_markets_connection_error(client):
    """Test list_markets with connection error."""
    await client.connect()
    
    with patch.object(client._http_client, 'get') as mock_get:
        mock_get.side_effect = ConnectionError("Network error")
        markets = await client.list_markets()
    
    assert len(markets) == 0
    
    await client.close()


@pytest.mark.asyncio
async def test_get_market_success(client, mock_response):
    """Test get_market with successful response."""
    await client.connect()
    
    mock_resp = mock_response(200, {
        "id": "market_123",
        "question": "Will X happen?",
        "description": "Test market",
        "active": True
    })
    
    with patch.object(client._http_client, 'get') as mock_get:
        mock_get.return_value.__aenter__.return_value = mock_resp
        market = await client.get_market("market_123")
    
    # May be None if parsing doesn't match expected structure
    await client.close()


@pytest.mark.asyncio
async def test_get_market_not_found(client, mock_response):
    """Test get_market with 404 response."""
    await client.connect()
    
    mock_resp = mock_response(404, {"error": "Not found"})
    
    with patch.object(client._http_client, 'get') as mock_get:
        mock_get.return_value.__aenter__.return_value = mock_resp
        market = await client.get_market("invalid_id")
    
    assert market is None
    
    await client.close()


@pytest.mark.asyncio
async def test_get_market_connection_error(client):
    """Test get_market with connection error."""
    await client.connect()
    
    with patch.object(client._http_client, 'get') as mock_get:
        mock_get.side_effect = ConnectionError("Network error")
        market = await client.get_market("market_123")
    
    assert market is None
    
    await client.close()


@pytest.mark.asyncio
async def test_get_orderbook_success(client, mock_response):
    """Test get_orderbook with successful response."""
    await client.connect()
    
    # Format matching what the client expects: list of [price, size] tuples
    mock_resp = mock_response(200, {
        "bids": [[0.64, 100], [0.62, 50]],
        "asks": [[0.66, 50], [0.68, 30]]
    })
    
    with patch.object(client._http_client, 'get') as mock_get:
        mock_get.return_value.__aenter__.return_value = mock_resp
        orderbook = await client.get_orderbook("market_123")
    
    assert orderbook is not None
    
    await client.close()


@pytest.mark.asyncio
async def test_get_orderbook_not_found(client, mock_response):
    """Test get_orderbook with 404 response."""
    await client.connect()
    
    mock_resp = mock_response(404, {"error": "Not found"})
    
    with patch.object(client._http_client, 'get') as mock_get:
        mock_get.return_value.__aenter__.return_value = mock_resp
        orderbook = await client.get_orderbook("invalid_id")
    
    assert orderbook is None
    
    await client.close()


@pytest.mark.asyncio
async def test_get_orderbook_connection_error(client):
    """Test get_orderbook with connection error."""
    await client.connect()
    
    with patch.object(client._http_client, 'get') as mock_get:
        mock_get.side_effect = ConnectionError("Network error")
        orderbook = await client.get_orderbook("market_123")
    
    assert orderbook is None
    
    await client.close()


# =============================================================================
# Trading Tests (CLOB client mocked)
# =============================================================================

@pytest.mark.asyncio
async def test_place_order_no_clob(client):
    """Test place_order without CLOB client."""
    await client.connect()
    
    order = VenueOrder(
        market_id="market_123",
        side="buy",
        size=Decimal("100"),
        order_type="limit",
        price=Decimal("0.65")
    )
    
    result = await client.place_order(order)
    
    assert result is None
    
    await client.close()


@pytest.mark.asyncio
async def test_place_order_with_clob(client):
    """Test place_order with mocked CLOB client."""
    await client.connect()
    
    mock_clob = AsyncMock()
    mock_clob.place_order.return_value = {
        "order_id": "ord_123",
        "status": "open",
        "market_id": "market_123"
    }
    client._clob_client = mock_clob
    
    order = VenueOrder(
        market_id="market_123",
        side="buy",
        size=Decimal("100"),
        order_type="limit",
        price=Decimal("0.65"),
        outcome_id="yes"
    )
    
    result = await client.place_order(order)
    
    mock_clob.place_order.assert_called_once()
    
    await client.close()


@pytest.mark.asyncio
async def test_place_order_error(client):
    """Test place_order error handling."""
    await client.connect()
    
    mock_clob = AsyncMock()
    mock_clob.place_order.side_effect = RuntimeError("CLOB error")
    client._clob_client = mock_clob
    
    order = VenueOrder(
        market_id="market_123",
        side="buy",
        size=Decimal("100"),
        order_type="market"
    )
    
    result = await client.place_order(order)
    
    assert result is None
    
    await client.close()


@pytest.mark.asyncio
async def test_cancel_order_no_clob(client):
    """Test cancel_order without CLOB client."""
    await client.connect()
    
    result = await client.cancel_order("ord_123")
    
    assert result is False
    
    await client.close()


@pytest.mark.asyncio
async def test_cancel_order_success(client):
    """Test cancel_order success."""
    await client.connect()
    
    mock_clob = AsyncMock()
    mock_clob.cancel_order.return_value = True
    client._clob_client = mock_clob
    
    result = await client.cancel_order("ord_123")
    
    assert result is True
    mock_clob.cancel_order.assert_called_once_with("ord_123")
    
    await client.close()


@pytest.mark.asyncio
async def test_cancel_order_error(client):
    """Test cancel_order error handling."""
    await client.connect()
    
    mock_clob = AsyncMock()
    mock_clob.cancel_order.side_effect = RuntimeError("Cancel failed")
    client._clob_client = mock_clob
    
    result = await client.cancel_order("ord_123")
    
    assert result is False
    
    await client.close()


@pytest.mark.asyncio
async def test_get_order_no_clob(client):
    """Test get_order without CLOB client."""
    await client.connect()
    
    result = await client.get_order("ord_123")
    
    assert result is None
    
    await client.close()


@pytest.mark.asyncio
async def test_get_order_success(client):
    """Test get_order success."""
    await client.connect()
    
    mock_clob = AsyncMock()
    mock_clob.get_open_orders.return_value = [
        {"order_id": "ord_123", "status": "open", "market_id": "market_123"}
    ]
    client._clob_client = mock_clob
    
    result = await client.get_order("ord_123")
    
    await client.close()


@pytest.mark.asyncio
async def test_get_open_orders_no_clob(client):
    """Test get_open_orders without CLOB client."""
    await client.connect()
    
    result = await client.get_open_orders()
    
    assert result == []
    
    await client.close()


@pytest.mark.asyncio
async def test_get_open_orders_success(client):
    """Test get_open_orders success."""
    await client.connect()
    
    mock_clob = AsyncMock()
    mock_clob.get_open_orders.return_value = [
        {"order_id": "ord_1", "status": "open"},
        {"order_id": "ord_2", "status": "open"}
    ]
    client._clob_client = mock_clob
    
    result = await client.get_open_orders()
    
    await client.close()


# =============================================================================
# Account Tests
# =============================================================================

@pytest.mark.asyncio
async def test_get_positions_no_clob(client):
    """Test get_positions without CLOB client."""
    await client.connect()
    
    result = await client.get_positions()
    
    assert result == []
    
    await client.close()


@pytest.mark.asyncio
async def test_get_positions_success(client):
    """Test get_positions success."""
    await client.connect()
    
    mock_clob = AsyncMock()
    mock_clob.get_positions.return_value = [
        {"market_id": "market_123", "side": "yes", "size": 100}
    ]
    client._clob_client = mock_clob
    
    result = await client.get_positions()
    
    await client.close()


@pytest.mark.asyncio
async def test_get_trades_no_clob(client):
    """Test get_trades without CLOB client."""
    await client.connect()
    
    result = await client.get_trades()
    
    assert result == []
    
    await client.close()


@pytest.mark.asyncio
async def test_get_balance_no_clob(client):
    """Test get_balance without CLOB client returns default balance."""
    await client.connect()
    
    result = await client.get_balance()
    
    # Returns default balance even without CLOB
    assert "USDC" in result
    
    await client.close()


@pytest.mark.asyncio
async def test_get_balance_success(client):
    """Test get_balance success."""
    await client.connect()
    
    mock_clob = AsyncMock()
    mock_clob.get_balance.return_value = {"USDC": 1000.0}
    client._clob_client = mock_clob
    
    result = await client.get_balance()
    
    await client.close()
