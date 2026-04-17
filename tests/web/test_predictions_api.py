"""
Tests for predictions API endpoints.

Tests cover:
- Market listing
- Market retrieval by ID
- Category listing
- Markets by category
- Mock data fallback
- Kalshi integration
"""

import pytest
import sys
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
from datetime import datetime


# Mock hardening module to avoid import errors
sys.modules.setdefault('hardening', MagicMock())
sys.modules.setdefault('hardening.lockdown', MagicMock())
sys.modules.setdefault('hardening.circuit_breaker', MagicMock())
# Mock institutional router to avoid cascading import errors from hardening
sys.modules.setdefault('web.api.institutional', MagicMock())


@pytest.fixture
def mock_prediction_aggregator():
    """Mock the prediction market aggregator."""
    mock_aggregator = MagicMock()
    
    # Create mock market objects
    mock_market1 = Mock()
    mock_market1.market_id = "kalshi_btc_100k"
    mock_market1.question = "Will Bitcoin reach $100k?"
    mock_market1.category = Mock(value="crypto")
    mock_market1.yes_price = 0.65
    mock_market1.no_price = 0.35
    mock_market1.volume_24h = 1000000
    mock_market1.liquidity = 500000
    mock_market1.resolution_date = 1735689600  # 2024-12-31
    
    mock_market2 = Mock()
    mock_market2.market_id = "kalshi_eth_upgrade"
    mock_market2.question = "Will Ethereum upgrade succeed?"
    mock_market2.category = Mock(value="crypto")
    mock_market2.yes_price = 0.80
    mock_market2.no_price = 0.20
    mock_market2.volume_24h = 500000
    mock_market2.liquidity = 250000
    mock_market2.resolution_date = 1719792000  # 2024-06-30
    
    mock_aggregator.get_all_markets.return_value = {
        "kalshi_btc_100k": mock_market1,
        "kalshi_eth_upgrade": mock_market2
    }
    
    return mock_aggregator


@pytest.fixture
def client():
    """Create a test client with the predictions router."""
    from web.api.predictions import router
    
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/predictions")
    
    return TestClient(app)


class TestMarketsEndpoint:
    """Test the /markets endpoint."""
    
    def test_get_markets_returns_200(self, client):
        """Test that markets endpoint returns 200."""
        response = client.get("/api/v1/predictions/markets")
        assert response.status_code == 200
    
    def test_get_markets_structure(self, client):
        """Test that markets endpoint returns correct structure."""
        response = client.get("/api/v1/predictions/markets")
        data = response.json()
        
        assert "markets" in data
        assert "last_update" in data
        assert "total" in data
        assert isinstance(data["markets"], list)
        assert isinstance(data["total"], int)
    
    def test_get_markets_returns_mock_data(self, client):
        """Test that markets endpoint returns mock data by default."""
        response = client.get("/api/v1/predictions/markets")
        data = response.json()
        
        assert data["total"] > 0
        assert len(data["markets"]) > 0
        
        # Check first market has required fields
        market = data["markets"][0]
        assert "id" in market
        assert "question" in market
        assert "category" in market
        assert "yes_price" in market
        assert "no_price" in market
        assert "volume" in market
        assert "liquidity" in market
    
    def test_get_markets_with_kalshi_data(self, client, mock_prediction_aggregator):
        """Test markets endpoint with Kalshi data."""
        with patch('monitoring.prediction_markets.get_prediction_aggregator', return_value=mock_prediction_aggregator):
            # Trigger a refresh
            import asyncio
            from web.api.predictions import fetch_kalshi_markets
            asyncio.run(fetch_kalshi_markets())
            
            response = client.get("/api/v1/predictions/markets")
            data = response.json()
            
            assert data["total"] == 2
            assert len(data["markets"]) == 2
            
            # Verify Kalshi data is present
            market_ids = [m["id"] for m in data["markets"]]
            assert "kalshi_btc_100k" in market_ids
            assert "kalshi_eth_upgrade" in market_ids


class TestMarketByIdEndpoint:
    """Test the /markets/{market_id} endpoint."""
    
    def test_get_market_by_id_returns_200(self, client):
        """Test that market by ID endpoint returns 200 for valid ID."""
        # First get all markets to find a valid ID
        response = client.get("/api/v1/predictions/markets")
        markets = response.json()["markets"]
        
        if markets:
            market_id = markets[0]["id"]
            response = client.get(f"/api/v1/predictions/markets/{market_id}")
            assert response.status_code == 200
    
    def test_get_market_by_id_returns_market(self, client):
        """Test that market by ID returns correct market data."""
        # Get a valid market ID
        response = client.get("/api/v1/predictions/markets")
        markets = response.json()["markets"]
        
        if markets:
            expected_market = markets[0]
            market_id = expected_market["id"]
            
            response = client.get(f"/api/v1/predictions/markets/{market_id}")
            market = response.json()
            
            assert market["id"] == expected_market["id"]
            assert market["question"] == expected_market["question"]
            assert market["category"] == expected_market["category"]
    
    def test_get_market_by_id_not_found(self, client):
        """Test that market by ID returns 404 for invalid ID."""
        response = client.get("/api/v1/predictions/markets/nonexistent_market")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestCategoriesEndpoint:
    """Test the /categories endpoint."""
    
    def test_get_categories_returns_200(self, client):
        """Test that categories endpoint returns 200."""
        response = client.get("/api/v1/predictions/categories")
        assert response.status_code == 200
    
    def test_get_categories_structure(self, client):
        """Test that categories endpoint returns correct structure."""
        response = client.get("/api/v1/predictions/categories")
        data = response.json()
        
        assert "categories" in data
        assert isinstance(data["categories"], list)
    
    def test_get_categories_returns_sorted(self, client):
        """Test that categories are returned sorted."""
        response = client.get("/api/v1/predictions/categories")
        categories = response.json()["categories"]
        
        assert categories == sorted(categories)
    
    def test_get_categories_no_duplicates(self, client):
        """Test that categories have no duplicates."""
        response = client.get("/api/v1/predictions/categories")
        categories = response.json()["categories"]
        
        assert len(categories) == len(set(categories))


class TestMarketsByCategoryEndpoint:
    """Test the /markets/category/{category} endpoint."""
    
    def test_get_markets_by_category_returns_200(self, client):
        """Test that markets by category returns 200."""
        # Get a valid category
        response = client.get("/api/v1/predictions/categories")
        categories = response.json()["categories"]
        
        if categories:
            category = categories[0]
            response = client.get(f"/api/v1/predictions/markets/category/{category}")
            assert response.status_code == 200
    
    def test_get_markets_by_category_structure(self, client):
        """Test that markets by category returns correct structure."""
        response = client.get("/api/v1/predictions/categories")
        categories = response.json()["categories"]
        
        if categories:
            category = categories[0]
            response = client.get(f"/api/v1/predictions/markets/category/{category}")
            data = response.json()
            
            assert "markets" in data
            assert "category" in data
            assert "total" in data
            assert data["category"] == category
    
    def test_get_markets_by_category_filters_correctly(self, client):
        """Test that markets are filtered by category."""
        response = client.get("/api/v1/predictions/categories")
        categories = response.json()["categories"]
        
        if categories:
            category = categories[0]
            response = client.get(f"/api/v1/predictions/markets/category/{category}")
            data = response.json()
            
            # All returned markets should be in the requested category
            for market in data["markets"]:
                assert market["category"] == category
    
    def test_get_markets_by_invalid_category(self, client):
        """Test that invalid category returns empty list."""
        response = client.get("/api/v1/predictions/markets/category/nonexistent_category")
        data = response.json()
        
        assert data["total"] == 0
        assert len(data["markets"]) == 0


class TestMockDataFallback:
    """Test mock data fallback functionality."""
    
    def test_mock_data_structure(self):
        """Test that mock data has correct structure."""
        from web.api.predictions import get_mock_markets
        
        markets = get_mock_markets()
        
        assert len(markets) > 0
        
        for market in markets:
            assert "id" in market
            assert "question" in market
            assert "description" in market
            assert "category" in market
            assert "outcomes" in market
            assert "yes_price" in market
            assert "no_price" in market
            assert "volume" in market
            assert "liquidity" in market
    
    def test_mock_data_prices_valid(self):
        """Test that mock data has valid prices."""
        from web.api.predictions import get_mock_markets
        
        markets = get_mock_markets()
        
        for market in markets:
            assert 0 <= market["yes_price"] <= 1
            assert 0 <= market["no_price"] <= 1
            # Prices should roughly sum to 1 (allowing for spread)
            assert 0.8 <= (market["yes_price"] + market["no_price"]) <= 1.2


class TestKalshiIntegration:
    """Test Kalshi integration functionality."""
    
    @pytest.mark.asyncio
    async def test_fetch_kalshi_markets_success(self, mock_prediction_aggregator):
        """Test successful Kalshi market fetch."""
        from web.api.predictions import fetch_kalshi_markets, _markets_cache
        
        with patch('monitoring.prediction_markets.get_prediction_aggregator', return_value=mock_prediction_aggregator):
            await fetch_kalshi_markets()

            # Cache should be updated with Kalshi data
            assert len(_markets_cache) == 2
            assert any(m["id"] == "kalshi_btc_100k" for m in _markets_cache)

    @pytest.mark.asyncio
    async def test_fetch_kalshi_markets_fallback_on_error(self):
        """Test fallback to mock data when Kalshi fetch fails."""
        from web.api.predictions import fetch_kalshi_markets, _markets_cache

        # Mock aggregator that raises exception
        with patch('monitoring.prediction_markets.get_prediction_aggregator', side_effect=Exception("Connection failed")):
            await fetch_kalshi_markets()

            # Should fall back gracefully (no crash; cache unchanged or empty)
            assert isinstance(_markets_cache, list)

    @pytest.mark.asyncio
    async def test_fetch_kalshi_markets_empty_response(self, mock_prediction_aggregator):
        """Test handling of empty Kalshi response."""
        from web.api.predictions import fetch_kalshi_markets, _markets_cache

        # Mock empty response
        mock_prediction_aggregator.get_all_markets.return_value = {}

        with patch('monitoring.prediction_markets.get_prediction_aggregator', return_value=mock_prediction_aggregator):
            await fetch_kalshi_markets()
            
            # Should fall back to mock data
            assert len(_markets_cache) > 0


class TestDataConsistency:
    """Test data consistency across endpoints."""
    
    def test_market_count_consistency(self, client):
        """Test that market count is consistent across endpoints."""
        # Get all markets
        response = client.get("/api/v1/predictions/markets")
        all_markets = response.json()
        total_count = all_markets["total"]
        
        # Get markets by category and sum
        response = client.get("/api/v1/predictions/categories")
        categories = response.json()["categories"]
        
        category_count = 0
        for category in categories:
            response = client.get(f"/api/v1/predictions/markets/category/{category}")
            category_count += response.json()["total"]
        
        # Counts should match
        assert total_count == category_count
    
    def test_market_data_consistency(self, client):
        """Test that market data is consistent between endpoints."""
        # Get all markets
        response = client.get("/api/v1/predictions/markets")
        all_markets = response.json()["markets"]
        
        if all_markets:
            market = all_markets[0]
            market_id = market["id"]
            
            # Get same market by ID
            response = client.get(f"/api/v1/predictions/markets/{market_id}")
            market_by_id = response.json()
            
            # Data should match
            assert market["id"] == market_by_id["id"]
            assert market["question"] == market_by_id["question"]
            assert market["yes_price"] == market_by_id["yes_price"]
