"""
Tests for Polymarket integration
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from decimal import Decimal

from merid.polymarket_client import PolymarketClient, PolymarketConfig, Market, MarketOutcome
from merid.monitoring.polymarket_adapter import PolymarketAdapter, create_polymarket_adapter


class TestPolymarketConfig:
    """Test PolymarketConfig."""
    
    def test_config_initialization(self):
        """Test config initialization."""
        config = PolymarketConfig()
        
        assert config.gamma_api_base == "https://gamma-api.polymarket.com"
        assert config.clob_api_base == "https://clob.polymarket.com"
        assert config.data_api_base == "https://data.polymarket.com"
        assert config.graphql_url == "https://polymarket.com/graphql"
        assert config.ws_url == "wss://ws.polymarket.com"
        assert config.timeout == 30.0
        assert config.ws_timeout == 60.0


class TestPolymarketClient:
    """Test PolymarketClient."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        return PolymarketClient()
    
    @pytest.mark.asyncio
    async def test_client_context_manager(self, client):
        """Test async context manager."""
        async with client as c:
            assert c is client
            assert c._http_client is not None
    
    @pytest.mark.asyncio
    async def test_list_markets(self, client):
        """Test listing markets."""
        # Mock HTTP client
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = [
            {
                "id": "test-market",
                "question": "Test question",
                "description": "Test description",
                "outcomes": [
                    {"outcome": "Yes", "price": 0.6},
                    {"outcome": "No", "price": 0.4}
                ],
                "active": True,
                "volume": "1000.0",
                "liquidity": "500.0",
                "category": "test"
            }
        ]
        
        with patch.object(client._http_client, "get", return_value=mock_response):
            markets = await client.list_markets()
            
            assert len(markets) == 1
            assert markets[0].id == "test-market"
            assert markets[0].question == "Test question"
            assert len(markets[0].outcomes) == 2
            assert markets[0].outcomes[0].outcome == "Yes"
            assert markets[0].outcomes[0].price == Decimal("0.6")
    
    @pytest.mark.asyncio
    async def test_get_market_details(self, client):
        """Test getting market details."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {
            "id": "test-market",
            "question": "Test question",
            "description": "Test description",
            "outcomes": [
                {"outcome": "Yes", "price": 0.6},
                {"outcome": "No", "price": 0.4}
            ],
            "active": True
        }
        
        with patch.object(client._http_client, "get", return_value=mock_response):
            market = await client.get_market_details("test-market")
            
            assert market is not None
            assert market.id == "test-market"
            assert market.question == "Test question"
    
    @pytest.mark.asyncio
    async def test_place_order(self, client):
        """Test placing an order."""
        # Mock CLOB client
        mock_clob = AsyncMock()
        mock_clob.place_order.return_value = {
            "id": "test-order",
            "marketId": "test-market",
            "outcome": "Yes",
            "side": "buy",
            "size": "1.0",
            "price": "0.6",
            "status": "pending"
        }
        
        client._clob_client = mock_clob
        
        order = await client.place_order(
            market_id="test-market",
            outcome="Yes",
            side="buy",
            size=Decimal("1.0"),
            price=Decimal("0.6")
        )
        
        assert order is not None
        assert order.id == "test-order"
        assert order.market_id == "test-market"
        assert order.side == "buy"
    
    @pytest.mark.asyncio
    async def test_get_positions(self, client):
        """Test getting user positions."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {
            "data": {
                "user": {
                    "positions": [
                        {
                            "id": "test-position",
                            "market": {"id": "test-market"},
                            "outcome": "Yes",
                            "size": "1.0",
                            "averagePrice": "0.6",
                            "unrealizedPnl": "10.0",
                            "createdAt": "2024-01-01T00:00:00Z"
                        }
                    ]
                }
            }
        }
        
        with patch.object(client._http_client, "post", return_value=mock_response):
            positions = await client.get_positions("test-address")
            
            assert len(positions) == 1
            assert positions[0].market_id == "test-market"
            assert positions[0].outcome == "Yes"
            assert positions[0].size == Decimal("1.0")


class TestPolymarketAdapter:
    """Test PolymarketAdapter."""
    
    @pytest.fixture
    def adapter(self):
        """Create test adapter."""
        return PolymarketAdapter()
    
    @pytest.mark.asyncio
    async def test_fetch_polymarket_markets(self, adapter):
        """Test fetching markets through adapter."""
        # Mock client
        mock_client = AsyncMock()
        mock_market = Market(
            id="test-market",
            question="Test question",
            description="Test description",
            outcomes=[
                MarketOutcome("Yes", Decimal("0.6"), Decimal("60")),
                MarketOutcome("No", Decimal("0.4"), Decimal("40"))
            ],
            volume=Decimal("1000.0")
        )
        
        mock_client.list_markets.return_value = [mock_market]
        
        with patch.object(adapter, '_client', mock_client):
            with patch.object(adapter, '_client', mock_client):
                markets = await adapter.fetch_polymarket_markets(limit=10)
                
                assert len(markets) == 1
                assert markets[0].market_id == "test-market"
                assert markets[0].question == "Test question"
                assert markets[0].yes_price == 0.6
                assert markets[0].no_price == 0.4
    
    def test_convert_to_prediction_market(self, adapter):
        """Test converting Market to PredictionMarket."""
        market = Market(
            id="test-market",
            question="Test question",
            description="Test description",
            outcomes=[
                MarketOutcome("Yes", Decimal("0.6"), Decimal("60")),
                MarketOutcome("No", Decimal("0.4"), Decimal("40"))
            ],
            volume=Decimal("1000.0"),
            category="test"
        )
        
        pred_market = adapter._convert_to_prediction_market(market)
        
        assert pred_market is not None
        assert pred_market.market_id == "test-market"
        assert pred_market.question == "Test question"
        assert pred_market.yes_price == 0.6
        assert pred_market.no_price == 0.4
        assert pred_market.platform.value == "POLYMARKET"
    
    @pytest.mark.asyncio
    async def test_get_market_details(self, adapter):
        """Test getting market details through adapter."""
        mock_client = AsyncMock()
        mock_market = Market(
            id="test-market",
            question="Test question",
            description="Test description",
            outcomes=[
                MarketOutcome("Yes", Decimal("0.6"), Decimal("60"))
            ]
        )
        
        mock_client.get_market_details.return_value = mock_market
        
        with patch.object(adapter, '_client', mock_client):
            details = await adapter.get_market_details("test-market")
            
            assert details is not None
            assert details.market_id == "test-market"
    
    @pytest.mark.asyncio
    async def test_get_orderbook(self, adapter):
        """Test getting order book through adapter."""
        mock_client = AsyncMock()
        mock_orderbook = AsyncMock()
        mock_orderbook.market_id = "test-market"
        mock_orderbook.outcome = "Yes"
        mock_orderbook.bids = [(Decimal("0.5"), Decimal("1.0"))]
        mock_orderbook.asks = [(Decimal("0.7"), Decimal("1.0"))]
        
        mock_client.get_orderbook.return_value = mock_orderbook
        
        with patch.object(adapter, '_client', mock_client):
            orderbook = await adapter.get_orderbook("test-market")
            
            assert orderbook is not None
            assert orderbook["market_id"] == "test-market"
            assert orderbook["outcome"] == "Yes"
            assert len(orderbook["bids"]) == 1
            assert orderbook["bids"][0] == (0.5, 1.0)


class TestIntegration:
    """Integration tests."""
    
    @pytest.mark.asyncio
    async def test_adapter_creation(self):
        """Test adapter creation."""
        adapter = create_polymarket_adapter()
        assert isinstance(adapter, PolymarketAdapter)
    
    @pytest.mark.asyncio
    async def test_client_availability_check(self):
        """Test client availability check."""
        from merid.monitoring.polymarket_adapter import check_polymarket_client_availability
        
        # Should return False when packages are not installed
        result = check_polymarket_client_availability()
        assert isinstance(result, bool)


class TestErrorHandling:
    """Test error handling."""
    
    @pytest.mark.asyncio
    async def test_client_error_handling(self):
        """Test client error handling."""
        client = PolymarketClient()
        
        # Mock HTTP client that raises exception
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Network error")
        
        with patch.object(client, '_http_client', mock_client):
            markets = await client.list_markets()
            assert markets == []
    
    @pytest.mark.asyncio
    async def test_adapter_error_handling(self):
        """Test adapter error handling."""
        adapter = PolymarketAdapter()
        
        # Mock client that raises exception
        mock_client = AsyncMock()
        mock_client.list_markets.side_effect = Exception("Client error")
        
        with patch.object(adapter, '_client', mock_client):
            markets = await adapter.fetch_polymarket_markets()
            assert markets == []


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__])
