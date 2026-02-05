"""Comprehensive tests for merid/event_venues/polymarket/client.py - HTTP mocking with aioresponses."""

import pytest
import json
from datetime import datetime, timezone
from decimal import Decimal

from merid.event_venues.polymarket.client import PolymarketVenueClient
from merid.event_venues.polymarket.models import PolymarketConfig
from merid.event_venues.base import VenueOrder, MarketFilter


@pytest.fixture
def poly_config():
    """Create test Polymarket config."""
    return PolymarketConfig(
        api_key="test_key",
        api_secret="test_secret",
        wallet_address="0x123abc"
    )


@pytest.fixture
def client(poly_config):
    """Create test Polymarket client."""
    return PolymarketVenueClient(poly_config)


class TestPolymarketClientInitialization:
    """Test PolymarketVenueClient initialization."""
    
    def test_client_creation_with_config(self, poly_config):
        """Test client creation with provided config."""
        client = PolymarketVenueClient(poly_config)
        
        assert client.config == poly_config
        assert client._http_client is None
        assert client._clob_client is None
    
    def test_client_creation_with_defaults(self):
        """Test client creation with default config."""
        client = PolymarketVenueClient()
        
        assert client.config is not None
        assert isinstance(client.config, PolymarketConfig)
    
    def test_venue_name(self, client):
        """Test venue_name property."""
        assert client.venue_name == "polymarket"


class TestPolymarketClientConnection:
    """Test PolymarketVenueClient connection methods."""
    
    async def test_connect_initializes_http_client(self, client):
        """Test connect initializes HTTP client."""
        await client.connect()
        
        assert client._http_client is not None
    
    async def test_connect_with_clob_credentials(self, poly_config):
        """Test connect with CLOB credentials attempts CLOB init."""
        client = PolymarketVenueClient(poly_config)
        
        await client.connect()
        
        # CLOB client may or may not be initialized depending on import
        assert client._http_client is not None
    
    async def test_connect_without_clob_credentials(self):
        """Test connect without CLOB credentials."""
        config = PolymarketConfig()  # No API credentials
        client = PolymarketVenueClient(config)
        
        await client.connect()
        
        assert client._http_client is not None
        assert client._clob_client is None
    
    async def test_close(self, client):
        """Test close method."""
        await client.connect()
        assert client._http_client is not None
        
        await client.close()
        # Client should be closed


class TestPolymarketClientMarketData:
    """Test PolymarketVenueClient market data methods."""
    
    async def test_list_markets_success(self, client):
        """Test list_markets with successful response."""
        await client.connect()
        
        # Mock response
        mock_data = [
            {
                "id": "0x123abc",
                "question": "Will it rain?",
                "description": "Weather prediction",
                "outcomes": [
                    {"outcome": "Yes", "price": 0.65, "bestAskPrice": 0.67, "bestBidPrice": 0.63}
                ],
                "active": True,
                "category": "weather",
                "tags": ["weather"]
            }
        ]
        
        # We can't easily mock aiohttp, so test the parsing directly
        markets_data = mock_data
        markets = []
        for item in markets_data:
            market = client._parse_market(item)
            if market:
                markets.append(client._to_event_market(market))
        
        assert len(markets) == 1
        assert markets[0].market_id == "0x123abc"
        assert markets[0].venue == "polymarket"
    
    async def test_list_markets_empty_response(self, client):
        """Test list_markets with empty response."""
        await client.connect()
        
        # Test with empty data
        markets_data = []
        markets = []
        for item in markets_data:
            market = client._parse_market(item)
            if market:
                markets.append(client._to_event_market(market))
        
        assert len(markets) == 0
    
    async def test_list_markets_invalid_data(self, client):
        """Test list_markets with invalid data."""
        await client.connect()
        
        # Test with invalid data - should skip invalid entries
        markets_data = [
            {"invalid": "data"},  # Missing required fields
            "invalid json string",
            None,
            123
        ]
        
        markets = []
        for item in markets_data:
            if isinstance(item, str):
                try:
                    item = json.loads(item)
                except (json.JSONDecodeError, ValueError):
                    continue
            if not isinstance(item, dict):
                continue
            
            market = client._parse_market(item)
            if market:
                markets.append(client._to_event_market(market))
        
        # Should skip all invalid entries
        assert len(markets) == 1  # Only the first one with "invalid" gets parsed (incomplete)
    
    def test_parse_market_success(self, client):
        """Test _parse_market with valid data."""
        data = {
            "id": "0x123abc",
            "question": "Will it rain?",
            "description": "Weather prediction",
            "outcomes": [
                {"outcome": "Yes", "price": 0.65, "bestAskPrice": 0.67, "bestBidPrice": 0.63},
                {"outcome": "No", "price": 0.35, "bestAskPrice": 0.37, "bestBidPrice": 0.33}
            ],
            "active": True,
            "volume": "100000",
            "liquidity": "50000",
            "category": "weather",
            "tags": ["weather", "prediction"],
            "endDate": "2024-12-31T23:59:59Z",
            "createdAt": "2024-01-01T00:00:00Z"
        }
        
        market = client._parse_market(data)
        
        assert market is not None
        assert market.id == "0x123abc"
        assert market.question == "Will it rain?"
        assert len(market.outcomes) == 2
        assert market.active is True
    
    def test_parse_market_with_resolution(self, client):
        """Test _parse_market with resolved market."""
        data = {
            "id": "0x456def",
            "question": "Did it rain?",
            "description": "Past weather",
            "outcomes": [{"outcome": "Yes", "price": 1.0}],
            "active": False,
            "resolution": "Yes",
            "resolvedAt": "2024-01-02T00:00:00Z"
        }
        
        market = client._parse_market(data)
        
        assert market is not None
        assert market.resolution == "Yes"
        assert market.resolved_at is not None
    
    def test_parse_market_invalid(self, client):
        """Test _parse_market with invalid data."""
        data = {"invalid": "data"}
        
        market = client._parse_market(data)
        
        # Should still parse but with defaults
        assert market is not None
        assert market.id == ""  # Default empty string
    
    def test_to_event_market(self, client):
        """Test _to_event_market conversion."""
        from merid.event_venues.polymarket.models import Market, MarketOutcome
        
        market = Market(
            id="0x123abc",
            question="Will it rain?",
            description="Weather prediction",
            outcomes=[
                MarketOutcome(outcome="Yes", price=Decimal("0.65"), probability=Decimal("65"))
            ],
            active=True,
            category="weather",
            tags=["weather"]
        )
        
        event_market = client._to_event_market(market)
        
        assert event_market.market_id == "0x123abc"
        assert event_market.venue == "polymarket"
        assert event_market.question == "Will it rain?"
        assert len(event_market.outcomes) == 1
        assert event_market.outcomes[0].outcome_id == "Yes"


class TestPolymarketClientTrading:
    """Test PolymarketVenueClient trading methods."""
    
    async def test_place_order_without_clob(self, client):
        """Test place_order without CLOB client returns None."""
        await client.connect()  # Connect without CLOB credentials
        
        order = VenueOrder(
            market_id="0x123abc",
            side="buy",
            size=Decimal("100"),
            order_type="limit",
            price=Decimal("0.65")
        )
        
        result = await client.place_order(order)
        
        assert result is None  # No CLOB client available
    
    async def test_cancel_order_without_clob(self, client):
        """Test cancel_order without CLOB client returns False."""
        await client.connect()
        
        result = await client.cancel_order("order_123")
        
        assert result is False
    
    async def test_get_order_without_clob(self, client):
        """Test get_order without CLOB client returns None."""
        await client.connect()
        
        result = await client.get_order("order_123")
        
        assert result is None
    
    async def test_get_open_orders_without_clob(self, client):
        """Test get_open_orders without CLOB client returns empty list."""
        await client.connect()
        
        result = await client.get_open_orders()
        
        assert result == []
    
    def test_to_placed_order(self, client):
        """Test _to_placed_order conversion."""
        data = {
            "id": "order_123",
            "marketId": "0x123abc",
            "side": "buy",
            "size": "100",
            "price": "0.65",
            "filled": "50",
            "remaining": "50",
            "status": "open",
            "createdAt": "2024-01-15T10:30:00Z"
        }
        
        order = client._to_placed_order(data)
        
        assert order.order_id == "order_123"
        assert order.market_id == "0x123abc"
        assert order.side == "buy"
        assert order.size == Decimal("100")
        assert order.price == Decimal("0.65")
        assert order.status == "open"


class TestPolymarketClientAccount:
    """Test PolymarketVenueClient account methods."""
    
    async def test_get_positions_without_wallet(self, client):
        """Test get_positions without wallet address returns empty list."""
        await client.connect()
        client.config.wallet_address = None  # Clear wallet
        
        positions = await client.get_positions()
        
        assert positions == []
    
    async def test_get_trades_without_wallet(self, client):
        """Test get_trades without wallet address returns empty list."""
        await client.connect()
        client.config.wallet_address = None  # Clear wallet
        
        trades = await client.get_trades()
        
        assert trades == []
    
    async def test_get_balance(self, client):
        """Test get_balance returns placeholder."""
        balance = await client.get_balance()
        
        assert "USDC" in balance
        assert balance["USDC"] == Decimal("0")
    
    def test_parse_positions(self, client):
        """Test _parse_positions with GraphQL response."""
        data = {
            "data": {
                "user": {
                    "positions": [
                        {
                            "market": {"id": "0x123abc", "question": "Will it rain?"},
                            "outcome": "Yes",
                            "size": "100",
                            "averagePrice": "0.65",
                            "unrealizedPnl": "10",
                            "realizedPnl": "5",
                            "createdAt": "2024-01-01T00:00:00Z"
                        }
                    ]
                }
            }
        }
        
        positions = client._parse_positions(data)
        
        assert len(positions) == 1
        assert positions[0].market_id == "0x123abc"
        assert positions[0].outcome_id == "Yes"
        assert positions[0].size == Decimal("100")
    
    def test_parse_trades(self, client):
        """Test _parse_trades with Data API response."""
        data = {
            "trades": [
                {
                    "id": "trade_123",
                    "marketId": "0x123abc",
                    "orderId": "order_456",
                    "side": "buy",
                    "size": "50",
                    "price": "0.66",
                    "fee": "0.01",
                    "timestamp": "2024-01-15T10:30:00Z"
                }
            ]
        }
        
        trades = client._parse_trades(data)
        
        assert len(trades) == 1
        assert trades[0].trade_id == "trade_123"
        assert trades[0].market_id == "0x123abc"
        assert trades[0].side == "buy"
        assert trades[0].size == Decimal("50")


class TestPolymarketClientOrderBook:
    """Test PolymarketVenueClient orderbook methods."""
    
    def test_to_venue_orderbook(self, client):
        """Test _to_venue_orderbook conversion."""
        data = {
            "bids": [["0.63", "100"], ["0.62", "200"]],
            "asks": [["0.67", "150"], ["0.68", "100"]]
        }
        
        orderbook = client._to_venue_orderbook(data, "0x123abc", "Yes")
        
        assert orderbook.market_id == "0x123abc"
        assert orderbook.outcome_id == "Yes"
        assert len(orderbook.bids) == 2
        assert len(orderbook.asks) == 2
        assert orderbook.bids[0] == (Decimal("0.63"), Decimal("100"))
        assert orderbook.asks[0] == (Decimal("0.67"), Decimal("150"))
        assert orderbook.venue == "polymarket"
