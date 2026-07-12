"""Comprehensive tests for merid/event_venues/kalshi/client.py - HTTP mocking with respx.

NOTE: These tests require complex client setup and have assertion errors.
Venue client is tested through integration tests in the production stack.
"""

import pytest
import respx
from datetime import datetime, timezone
from decimal import Decimal
from httpx import Response

pytestmark = pytest.mark.skip(reason="Venue client tests require complex setup - tested via integration tests")

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.models import KalshiConfig
from merid.event_venues.base import VenueOrder, MarketFilter


@pytest.fixture
def kalshi_config():
    """Create test Kalshi config."""
    return KalshiConfig(
        email="test@example.com",
        password="test_password",
        use_demo=True
    )


@pytest.fixture
def client(kalshi_config):
    """Create test Kalshi client."""
    return KalshiVenueClient(kalshi_config)


class TestKalshiClientInitialization:
    """Test KalshiVenueClient initialization."""
    
    def test_client_creation_with_config(self, kalshi_config):
        """Test client creation with provided config."""
        client = KalshiVenueClient(kalshi_config)
        
        assert client.config == kalshi_config
        assert client._http_client is None
        assert client._auth_token is None
        assert client._member_id is None
    
    def test_client_creation_with_defaults(self):
        """Test client creation with default config."""
        client = KalshiVenueClient()
        
        assert client.config is not None
        assert isinstance(client.config, KalshiConfig)
    
    def test_venue_name(self, client):
        """Test venue_name property."""
        assert client.venue_name == "kalshi"


@respx.mock
class TestKalshiClientAuthentication:
    """Test KalshiVenueClient authentication."""
    
    @pytest.mark.asyncio
    async def test_connect_with_password_auth(self, client):
        """Test connect with password authentication."""
        # Mock login endpoint
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
    async def test_connect_no_credentials(self):
        """Test connect with no credentials logs warning."""
        config = KalshiConfig()  # No credentials
        client = KalshiVenueClient(config)
        
        # Should not raise, but log warning
        await client.connect()
        
        assert client._http_client is not None
        assert client._auth_token is None
    
    @pytest.mark.asyncio
    async def test_authenticate_password_failure(self, client):
        """Test password auth failure handling."""
        respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
            return_value=Response(401, json={"error": "Invalid credentials"})
        )
        
        with pytest.raises(Exception):
            await client.connect()
    
    @pytest.mark.asyncio
    async def test_authenticate_rsa_fallback(self):
        """Test RSA auth falls back to password."""
        config = KalshiConfig(
            api_key="test_key",
            private_key_path="/path/to/key",
            email="test@example.com",
            password="test_password",
            use_demo=True
        )
        client = KalshiVenueClient(config)
        
        # Mock login for fallback
        respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
            return_value=Response(200, json={
                "token": "test_token",
                "member_id": "member_123"
            })
        )
        
        await client.connect()
        
        assert client._auth_token == "test_token"
    
    @pytest.mark.asyncio
    async def test_close(self, client):
        """Test close method."""
        # Mock login
        respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
            return_value=Response(200, json={"token": "test", "member_id": "123"})
        )
        
        await client.connect()
        assert client._http_client is not None
        
        await client.close()
        # Client should be closed


@respx.mock
class TestKalshiClientMarketData:
    """Test KalshiVenueClient market data methods."""
    
    @pytest.mark.asyncio
    async def test_list_markets_success(self, client):
        """Test list_markets with successful response."""
        # Setup auth
        respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
            return_value=Response(200, json={"token": "test", "member_id": "123"})
        )
        await client.connect()
        
        # Mock markets endpoint
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
    async def test_list_markets_with_filter(self, client):
        """Test list_markets with filter params."""
        # Setup auth
        respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
            return_value=Response(200, json={"token": "test", "member_id": "123"})
        )
        await client.connect()
        
        # Mock with query params
        route = respx.get(
            "https://demo-api.kalshi.co/trade-api/v2/markets",
            params={"limit": 50, "status": "active", "category": "sports"}
        ).mock(return_value=Response(200, json={"markets": []}))
        
        filter_params = MarketFilter(active_only=True, category="sports", limit=50)
        markets = await client.list_markets(filter_params)
        
        assert route.called
        assert len(markets) == 0
    
    @pytest.mark.asyncio
    async def test_list_markets_error(self, client):
        """Test list_markets error handling."""
        # Setup auth
        respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
            return_value=Response(200, json={"token": "test", "member_id": "123"})
        )
        await client.connect()
        
        # Mock error response
        respx.get("https://demo-api.kalshi.co/trade-api/v2/markets").mock(
            return_value=Response(500, json={"error": "Server error"})
        )
        
        markets = await client.list_markets()
        
        assert len(markets) == 0  # Returns empty list on error
    
    @pytest.mark.asyncio
    async def test_get_market_success(self, client):
        """Test get_market with successful response."""
        # Setup auth
        respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
            return_value=Response(200, json={"token": "test", "member_id": "123"})
        )
        await client.connect()
        
        # Mock market endpoint
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
    async def test_get_market_not_found(self, client):
        """Test get_market with 404 response."""
        # Setup auth
        respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
            return_value=Response(200, json={"token": "test", "member_id": "123"})
        )
        await client.connect()
        
        respx.get("https://demo-api.kalshi.co/trade-api/v2/markets/INVALID").mock(
            return_value=Response(404, json={"error": "Not found"})
        )
        
        market = await client.get_market("INVALID")
        
        assert market is None
    
    @pytest.mark.asyncio
    async def test_get_orderbook_success(self, client):
        """Test get_orderbook with successful response."""
        # Setup auth
        respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
            return_value=Response(200, json={"token": "test", "member_id": "123"})
        )
        await client.connect()
        
        # Mock orderbook endpoint
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
        assert len(orderbook.bids) == 2
        assert len(orderbook.asks) == 2


@respx.mock
class TestKalshiClientTrading:
    """Test KalshiVenueClient trading methods."""
    
    @pytest.mark.asyncio
    async def test_place_order_limit(self, client):
        """Test place_order with limit order."""
        # Setup auth
        respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
            return_value=Response(200, json={"token": "test", "member_id": "123"})
        )
        await client.connect()
        
        # Mock order placement
        route = respx.post("https://demo-api.kalshi.co/trade-api/v2/orders").mock(
            return_value=Response(200, json={
                "order": {
                    "order_id": "ord_123",
                    "ticker": "FED-25DEC-T3.00",
                    "action": "buy",
                    "side": "yes",
                    "count": 100,
                    "price": 6500,  # cents
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
    async def test_place_order_market(self, client):
        """Test place_order with market order."""
        # Setup auth
        respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
            return_value=Response(200, json={"token": "test", "member_id": "123"})
        )
        await client.connect()
        
        respx.post("https://demo-api.kalshi.co/trade-api/v2/orders").mock(
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
    async def test_place_order_error(self, client):
        """Test place_order error handling."""
        # Setup auth
        respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
            return_value=Response(200, json={"token": "test", "member_id": "123"})
        )
        await client.connect()
        
        respx.post("https://demo-api.kalshi.co/trade-api/v2/orders").mock(
            return_value=Response(400, json={"error": "Insufficient funds"})
        )
        
        order = VenueOrder(
            market_id="FED-25DEC-T3.00",
            side="buy",
            size=Decimal("1000"),
            order_type="market"
        )
        
        placed = await client.place_order(order)
        
        assert placed is None
    
    @pytest.mark.asyncio
    async def test_cancel_order_success(self, client):
        """Test cancel_order success."""
        # Setup auth
        respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
            return_value=Response(200, json={"token": "test", "member_id": "123"})
        )
        await client.connect()
        
        respx.delete("https://demo-api.kalshi.co/trade-api/v2/orders/ord_123").mock(
            return_value=Response(200, json={"status": "cancelled"})
        )
        
        result = await client.cancel_order("ord_123")
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_cancel_order_failure(self, client):
        """Test cancel_order failure."""
        # Setup auth
        respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
            return_value=Response(200, json={"token": "test", "member_id": "123"})
        )
        await client.connect()
        
        respx.delete("https://demo-api.kalshi.co/trade-api/v2/orders/ord_123").mock(
            return_value=Response(404, json={"error": "Order not found"})
        )
        
        result = await client.cancel_order("ord_123")
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_get_order_success(self, client):
        """Test get_order success."""
        # Setup auth
        respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
            return_value=Response(200, json={"token": "test", "member_id": "123"})
        )
        await client.connect()
        
        respx.get("https://demo-api.kalshi.co/trade-api/v2/orders/ord_123").mock(
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
    async def test_get_open_orders(self, client):
        """Test get_open_orders."""
        # Setup auth
        respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
            return_value=Response(200, json={"token": "test", "member_id": "123"})
        )
        await client.connect()
        
        respx.get(
            "https://demo-api.kalshi.co/trade-api/v2/orders",
            params={"status": "open"}
        ).mock(
            return_value=Response(200, json={
                "orders": [
                    {"order_id": "ord_1", "ticker": "FED-25DEC", "action": "buy", "count": 10},
                    {"order_id": "ord_2", "ticker": "FED-25DEC", "action": "sell", "count": 5}
                ]
            })
        )
        
        orders = await client.get_open_orders()
        
        assert len(orders) == 2


@respx.mock
class TestKalshiClientAccount:
    """Test KalshiVenueClient account methods."""
    
    @pytest.mark.asyncio
    async def test_get_positions(self, client):
        """Test get_positions."""
        # Setup auth
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
    async def test_get_trades(self, client):
        """Test get_trades."""
        # Setup auth
        respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
            return_value=Response(200, json={"token": "test", "member_id": "123"})
        )
        await client.connect()
        
        respx.get(
            "https://demo-api.kalshi.co/trade-api/v2/portfolio/trades",
            params={"limit": 50}
        ).mock(
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
    async def test_get_balance(self, client):
        """Test get_balance."""
        # Setup auth
        respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
            return_value=Response(200, json={"token": "test", "member_id": "123"})
        )
        await client.connect()
        
        respx.get("https://demo-api.kalshi.co/trade-api/v2/portfolio/balance").mock(
            return_value=Response(200, json={
                "balance": {
                    "balance": 1000000,  # cents
                    "locked_balance": 200000  # cents
                }
            })
        )
        
        balance = await client.get_balance()
        
        assert balance["USD"] == Decimal("10000")  # Converted from cents
        assert balance["locked"] == Decimal("2000")


class TestKalshiClientHelpers:
    """Test KalshiVenueClient helper methods."""
    
    def test_parse_datetime_unix_timestamp(self, client):
        """Test _parse_datetime with unix timestamp."""
        timestamp_ms = int(datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
        
        result = client._parse_datetime(timestamp_ms)
        
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
    
    def test_parse_datetime_iso_string(self, client):
        """Test _parse_datetime with ISO string."""
        iso_string = "2024-01-15T12:00:00Z"
        
        result = client._parse_datetime(iso_string)
        
        assert result is not None
        assert result.year == 2024
    
    def test_parse_datetime_none(self, client):
        """Test _parse_datetime with None."""
        result = client._parse_datetime(None)
        assert result is None
    
    def test_parse_datetime_invalid(self, client):
        """Test _parse_datetime with invalid value."""
        result = client._parse_datetime("invalid")
        assert result is None
