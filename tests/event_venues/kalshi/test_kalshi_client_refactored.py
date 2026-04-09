"""Refactored tests for merid/event_venues/kalshi/client.py - Function-level async tests."""

import pytest
import respx
from datetime import datetime, timezone
from decimal import Decimal
from httpx import Response

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.models import KalshiConfig
from merid.event_venues.base import VenueOrder, MarketFilter


@pytest.fixture
def kalshi_config():
    """Create test Kalshi config with password auth."""
    return KalshiConfig(
        email="test@example.com",
        password="test_password",
        use_demo=True
    )


@pytest.fixture
def client(kalshi_config):
    """Create test Kalshi client."""
    return KalshiVenueClient(kalshi_config)


# =============================================================================
# Initialization Tests
# =============================================================================

def test_client_creation_with_config(kalshi_config):
    """Test client creation with provided config."""
    client = KalshiVenueClient(kalshi_config)
    assert client.config == kalshi_config
    assert client._http_client is None
    assert client._auth_token is None


def test_client_creation_with_defaults():
    """Test client creation with default config."""
    client = KalshiVenueClient()
    assert client.config is not None
    assert isinstance(client.config, KalshiConfig)


def test_venue_name(client):
    """Test venue_name property."""
    assert client.venue_name == "kalshi"


# =============================================================================
# Authentication Tests
# =============================================================================

@pytest.mark.asyncio
@respx.mock
async def test_connect_with_password_auth(client):
    """Test connect with password authentication."""
    login_route = respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
        return_value=Response(200, json={
            "token": "test_token_123",
            "member_id": "member_456"
        })
    )
    
    await client.connect()
    
    assert client._auth_token == "test_token_123"
    assert client._member_id == "member_456"
    assert client._http_client is not None
    assert login_route.called


@pytest.mark.asyncio
@respx.mock
async def test_connect_no_credentials():
    """Test connect with no credentials logs warning."""
    config = KalshiConfig()
    client = KalshiVenueClient(config)
    
    await client.connect()
    
    assert client._http_client is not None
    assert client._auth_token is None


@pytest.mark.asyncio
@respx.mock
async def test_authenticate_password_failure(client):
    """Test password auth failure handling."""
    respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
        return_value=Response(401, json={"error": "Invalid credentials"})
    )
    
    with pytest.raises(Exception):
        await client.connect()


@pytest.mark.asyncio
@respx.mock
async def test_close(client):
    """Test close method."""
    respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
        return_value=Response(200, json={"token": "test", "member_id": "123"})
    )
    
    await client.connect()
    assert client._http_client is not None
    
    await client.close()


# =============================================================================
# Market Data Tests
# =============================================================================

@pytest.mark.asyncio
@respx.mock
async def test_list_markets_success(client):
    """Test list_markets with successful response."""
    respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
        return_value=Response(200, json={"token": "test", "member_id": "123"})
    )
    await client.connect()
    
    respx.get("https://demo-api.kalshi.co/trade-api/v2/markets").mock(
        return_value=Response(200, json={
            "markets": [
                {
                    "ticker": "FED-25DEC-T3.00",
                    "title": "Fed Rate Decision",
                    "description": "Will Fed raise rates?",
                    "yes_price": 65,
                    "status": "active",
                    "category": "finance"
                }
            ]
        })
    )
    
    markets = await client.list_markets()
    
    assert len(markets) == 1
    assert markets[0].market_id == "FED-25DEC-T3.00"
    assert markets[0].venue == "kalshi"


@pytest.mark.asyncio
@respx.mock
async def test_list_markets_with_filter(client):
    """Test list_markets with filter params."""
    respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
        return_value=Response(200, json={"token": "test", "member_id": "123"})
    )
    await client.connect()
    
    route = respx.get("https://demo-api.kalshi.co/trade-api/v2/markets").mock(
        return_value=Response(200, json={"markets": []})
    )
    
    filter_params = MarketFilter(active_only=True, category="sports", limit=50)
    markets = await client.list_markets(filter_params)
    
    assert route.called
    assert len(markets) == 0


@pytest.mark.asyncio
@respx.mock
async def test_list_markets_error(client):
    """Test list_markets error handling returns empty list (resilient fallback)."""
    respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
        return_value=Response(200, json={"token": "test", "member_id": "123"})
    )
    await client.connect()
    
    # Mock 500 error - with resilience, this will retry then return []
    respx.get("https://demo-api.kalshi.co/trade-api/v2/markets").mock(
        return_value=Response(500, json={"error": "Server error"})
    )
    
    # Backward-compatible method returns empty list on failure
    markets = await client.list_markets()
    assert markets == []
    
    # Use _result method for explicit error handling
    result = await client.list_markets_result()
    assert not result.success
    assert result.error is not None


@pytest.mark.asyncio
@respx.mock
async def test_get_market_success(client):
    """Test get_market with successful response."""
    respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
        return_value=Response(200, json={"token": "test", "member_id": "123"})
    )
    await client.connect()
    
    respx.get("https://demo-api.kalshi.co/trade-api/v2/markets/FED-25DEC-T3.00").mock(
        return_value=Response(200, json={
            "market": {
                "ticker": "FED-25DEC-T3.00",
                "title": "Fed Rate Decision",
                "yes_price": 65,
                "status": "active"
            }
        })
    )
    
    market = await client.get_market("FED-25DEC-T3.00")
    
    assert market is not None
    assert market.market_id == "FED-25DEC-T3.00"


@pytest.mark.asyncio
@respx.mock
async def test_get_market_not_found(client):
    """Test get_market with 404 response returns None (resilient fallback)."""
    respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
        return_value=Response(200, json={"token": "test", "member_id": "123"})
    )
    await client.connect()
    
    respx.get("https://demo-api.kalshi.co/trade-api/v2/markets/INVALID").mock(
        return_value=Response(404, json={"error": "Not found"})
    )
    
    # Backward-compatible method returns None on failure
    market = await client.get_market("INVALID")
    assert market is None
    
    # Use _result method for explicit error handling
    result = await client.get_market_result("INVALID")
    assert not result.success


@pytest.mark.asyncio
@respx.mock
async def test_get_orderbook_success(client):
    """Test get_orderbook with successful response."""
    respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
        return_value=Response(200, json={"token": "test", "member_id": "123"})
    )
    await client.connect()
    
    respx.get("https://demo-api.kalshi.co/trade-api/v2/markets/FED-25DEC-T3.00/orderbook").mock(
        return_value=Response(200, json={
            "yes_bid": 64,
            "yes_ask": 66,
            "no_bid": 34,
            "no_ask": 36
        })
    )
    
    orderbook = await client.get_orderbook("FED-25DEC-T3.00")
    
    assert orderbook is not None
    assert orderbook.market_id == "FED-25DEC-T3.00"


# =============================================================================
# Trading Tests
# =============================================================================

@pytest.mark.asyncio
@respx.mock
async def test_place_order_limit(client):
    """Test place_order with limit order."""
    respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
        return_value=Response(200, json={"token": "test", "member_id": "123"})
    )
    await client.connect()
    
    route = respx.post("https://demo-api.kalshi.co/trade-api/v2/portfolio/orders").mock(
        return_value=Response(200, json={
            "order": {
                "order_id": "ord_123",
                "ticker": "FED-25DEC-T3.00",
                "action": "buy",
                "side": "yes",
                "count": 100,
                "price": 6500,
                "status": "resting"
            }
        })
    )
    
    order = VenueOrder(
        market_id="FED-25DEC-T3.00",
        side="buy",
        size=Decimal("100"),
        order_type="limit",
        price=Decimal("65"),
        outcome_id="yes"
    )
    
    placed = await client.place_order(order)
    
    assert placed is not None
    assert placed.order_id == "ord_123"
    assert placed.status == "resting"
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_place_order_market(client):
    """Test place_order with market order."""
    respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
        return_value=Response(200, json={"token": "test", "member_id": "123"})
    )
    await client.connect()
    
    respx.post("https://demo-api.kalshi.co/trade-api/v2/portfolio/orders").mock(
        return_value=Response(200, json={
            "order": {
                "order_id": "ord_456",
                "ticker": "FED-25DEC-T3.00",
                "action": "buy",
                "side": "yes",
                "count": 50,
                "status": "executed"
            }
        })
    )
    
    order = VenueOrder(
        market_id="FED-25DEC-T3.00",
        side="buy",
        size=Decimal("50"),
        order_type="market"
    )
    
    placed = await client.place_order(order)
    
    assert placed is not None
    assert placed.order_id == "ord_456"


@pytest.mark.asyncio
@respx.mock
async def test_place_order_error(client):
    """Test place_order error handling returns None (resilient fallback)."""
    respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
        return_value=Response(200, json={"token": "test", "member_id": "123"})
    )
    await client.connect()
    
    respx.post("https://demo-api.kalshi.co/trade-api/v2/portfolio/orders").mock(
        return_value=Response(400, json={"error": "Insufficient funds"})
    )
    
    order = VenueOrder(
        market_id="FED-25DEC-T3.00",
        side="buy",
        size=Decimal("1000"),
        order_type="market"
    )
    
    # Backward-compatible method returns None on failure
    placed = await client.place_order(order)
    assert placed is None
    
    # Use _result method for explicit error handling
    result = await client.place_order_result(order)
    assert not result.success


@pytest.mark.asyncio
@respx.mock
async def test_cancel_order_success(client):
    """Test cancel_order success."""
    respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
        return_value=Response(200, json={"token": "test", "member_id": "123"})
    )
    await client.connect()
    
    respx.post("https://demo-api.kalshi.co/trade-api/v2/portfolio/orders/ord_123/cancel").mock(
        return_value=Response(200, json={"status": "cancelled"})
    )
    
    result = await client.cancel_order("ord_123")
    assert result is True


@pytest.mark.asyncio
@respx.mock
async def test_cancel_order_failure(client):
    """Test cancel_order failure returns False (resilient fallback)."""
    respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
        return_value=Response(200, json={"token": "test", "member_id": "123"})
    )
    await client.connect()
    
    respx.post("https://demo-api.kalshi.co/trade-api/v2/portfolio/orders/ord_123/cancel").mock(
        return_value=Response(404, json={"error": "Order not found"})
    )
    
    # Backward-compatible method returns False on failure
    result = await client.cancel_order("ord_123")
    assert result is False
    
    # Use _result method for explicit error handling
    op_result = await client.cancel_order_result("ord_123")
    assert not op_result.success


@pytest.mark.asyncio
@respx.mock
async def test_get_order_success(client):
    """Test get_order success."""
    respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
        return_value=Response(200, json={"token": "test", "member_id": "123"})
    )
    await client.connect()
    
    respx.get("https://demo-api.kalshi.co/trade-api/v2/portfolio/orders/ord_123").mock(
        return_value=Response(200, json={
            "order": {
                "order_id": "ord_123",
                "ticker": "FED-25DEC-T3.00",
                "action": "buy",
                "side": "yes",
                "count": 100,
                "status": "resting"
            }
        })
    )
    
    order = await client.get_order("ord_123")
    
    assert order is not None
    assert order.order_id == "ord_123"


@pytest.mark.asyncio
@respx.mock
async def test_get_open_orders(client):
    """Test get_open_orders."""
    respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
        return_value=Response(200, json={"token": "test", "member_id": "123"})
    )
    await client.connect()
    
    respx.get("https://demo-api.kalshi.co/trade-api/v2/portfolio/orders").mock(
        return_value=Response(200, json={
            "orders": [
                {"order_id": "ord_1", "ticker": "FED-25DEC", "action": "buy", "count": 10},
                {"order_id": "ord_2", "ticker": "FED-25DEC", "action": "sell", "count": 5}
            ],
            "cursor": ""
        })
    )
    
    orders = await client.get_open_orders()
    assert len(orders) == 2


# =============================================================================
# Account Tests
# =============================================================================

@pytest.mark.asyncio
@respx.mock
async def test_get_positions(client):
    """Test get_positions."""
    respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
        return_value=Response(200, json={"token": "test", "member_id": "123"})
    )
    await client.connect()
    
    respx.get("https://demo-api.kalshi.co/trade-api/v2/portfolio/positions").mock(
        return_value=Response(200, json={
            "positions": [
                {
                    "ticker": "FED-25DEC-T3.00",
                    "side": "yes",
                    "count": 100,
                    "avg_price": 6500,
                    "total_cost": 650000
                }
            ]
        })
    )
    
    positions = await client.get_positions()
    
    assert len(positions) == 1
    assert positions[0].market_id == "FED-25DEC-T3.00"


@pytest.mark.asyncio
@respx.mock
async def test_get_trades(client):
    """Test get_trades."""
    respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
        return_value=Response(200, json={"token": "test", "member_id": "123"})
    )
    await client.connect()
    
    respx.get("https://demo-api.kalshi.co/trade-api/v2/portfolio/trades").mock(
        return_value=Response(200, json={
            "trades": [
                {
                    "trade_id": "trade_1",
                    "ticker": "FED-25DEC-T3.00",
                    "side": "yes",
                    "count": 50,
                    "price": 6500,
                    "fee": 10,
                    "created_at": int(datetime.now(timezone.utc).timestamp() * 1000)
                }
            ]
        })
    )
    
    trades = await client.get_trades(limit=50)
    
    assert len(trades) == 1
    assert trades[0].trade_id == "trade_1"


@pytest.mark.asyncio
@respx.mock
async def test_get_balance(client):
    """Test get_balance."""
    respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
        return_value=Response(200, json={"token": "test", "member_id": "123"})
    )
    await client.connect()
    
    respx.get("https://demo-api.kalshi.co/trade-api/v2/portfolio/balance").mock(
        return_value=Response(200, json={
            "balance": {
                "balance": 1000000,
                "locked_balance": 200000
            }
        })
    )
    
    balance = await client.get_balance()
    
    assert balance["USD"] == Decimal("10000")
    assert balance["locked"] == Decimal("2000")


# =============================================================================
# Helper Method Tests
# =============================================================================

def test_parse_datetime_unix_timestamp(client):
    """Test _parse_datetime with unix timestamp."""
    timestamp_ms = int(datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    result = client._parse_datetime(timestamp_ms)
    
    assert result is not None
    assert result.year == 2024
    assert result.month == 1
    assert result.day == 15


def test_parse_datetime_iso_string(client):
    """Test _parse_datetime with ISO string."""
    iso_string = "2024-01-15T12:00:00Z"
    result = client._parse_datetime(iso_string)
    
    assert result is not None
    assert result.year == 2024


def test_parse_datetime_none(client):
    """Test _parse_datetime with None."""
    result = client._parse_datetime(None)
    assert result is None


def test_parse_datetime_invalid(client):
    """Test _parse_datetime with invalid value."""
    result = client._parse_datetime("invalid")
    assert result is None
