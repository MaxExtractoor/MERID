"""Integration tests for prediction markets API endpoints."""

import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
import time

from monitoring.prediction_markets import (
    PredictionMarket, 
    PredictionPlatform, 
    MarketCategory, 
    ResolutionStatus
)


class TestPredictionMarketsAPI:
    """Integration tests for prediction markets endpoints."""

    @pytest.fixture
    def mock_aggregator(self):
        """Create a mock prediction aggregator with deterministic data."""
        markets = [
            PredictionMarket(
                market_id="poly_001",
                platform=PredictionPlatform.POLYMARKET,
                question="Will Bitcoin reach $100k by end of 2024?",
                category=MarketCategory.CRYPTO,
                yes_price=0.65,
                no_price=0.35,
                volume_24h=1000000.0,
                total_volume=5000000.0,
                liquidity=250000.0,
                resolution_date=time.time() + 86400 * 30,  # 30 days
                status=ResolutionStatus.OPEN,
            ),
            PredictionMarket(
                market_id="kalshi_002",
                platform=PredictionPlatform.KALSHI,
                question="Will Q4 GDP exceed 3% growth?",
                category=MarketCategory.ECONOMICS,
                yes_price=0.45,
                no_price=0.55,
                volume_24h=500000.0,
                total_volume=2000000.0,
                liquidity=100000.0,
                resolution_date=time.time() + 86400 * 15,  # 15 days
                status=ResolutionStatus.OPEN,
            ),
            PredictionMarket(
                market_id="poly_003",
                platform=PredictionPlatform.POLYMARKET,
                question="Will the next Fed meeting raise rates?",
                category=MarketCategory.FINANCE,
                yes_price=0.30,
                no_price=0.70,
                volume_24h=750000.0,
                total_volume=3000000.0,
                liquidity=150000.0,
                resolution_date=time.time() + 86400 * 7,  # 7 days
                status=ResolutionStatus.OPEN,
            ),
        ]

        from unittest.mock import Mock
        aggregator = Mock()
        
        # Mock methods to handle limit parameter
        def mock_get_all_markets(limit=100):
            return markets[:limit]
        
        def mock_get_markets_by_category(category, limit=50):
            return markets[:limit]
        
        aggregator.get_all_markets.side_effect = mock_get_all_markets
        aggregator.get_markets_by_category.side_effect = mock_get_markets_by_category
        aggregator.get_status.return_value = {
            "running": True,
            "total_markets": len(markets),
            "platforms": ["polymarket", "kalshi", "augur"],
            "markets_by_platform": {
                "polymarket": 2,
                "kalshi": 1,
                "augur": 0
            }
        }
        aggregator._all_markets = {m.market_id: m for m in markets}
        
        return aggregator

    @pytest.fixture
    def client(self):
        """Create test client."""
        from web.main import create_app
        app = create_app()
        return TestClient(app)

    def test_prediction_markets_happy_path(self, client, mock_aggregator):
        """Test successful prediction markets request."""
        with patch('monitoring.prediction_markets.get_prediction_aggregator', return_value=mock_aggregator):
            response = client.get("/api/v1/institutional/predictions/markets")
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify response structure
            assert "markets" in data
            assert "count" in data
            assert "status" in data
            
            # Verify data content
            markets = data["markets"]
            assert len(markets) == 3
            assert data["count"] == 3
            
            # Verify each market has required schema fields
            for market in markets:
                self._verify_market_schema(market)
            
            # Verify aggregator status
            status = data["status"]
            assert status["running"] is True
            assert status["total_markets"] == 3

    def test_prediction_markets_limit_parameter(self, client, mock_aggregator):
        """Test limit parameter behavior."""
        with patch('monitoring.prediction_markets.get_prediction_aggregator', return_value=mock_aggregator):
            response = client.get("/api/v1/institutional/predictions/markets?limit=2")
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify limit is respected
            markets = data["markets"]
            assert len(markets) == 2
            assert data["count"] == 2
            
            # Verify each market still has required schema
            for market in markets:
                self._verify_market_schema(market)

    def test_prediction_markets_category_filter(self, client, mock_aggregator):
        """Test category filtering."""
        with patch('monitoring.prediction_markets.get_prediction_aggregator', return_value=mock_aggregator):
            response = client.get("/api/v1/institutional/predictions/markets?category=crypto")
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify response structure
            assert "markets" in data
            assert "count" in data
            assert "status" in data

    def test_prediction_markets_aggregator_failure(self, client):
        """Test error handling when aggregator fails."""
        with patch('monitoring.prediction_markets.get_prediction_aggregator') as mock_get_aggregator:
            # Make aggregator raise an exception
            from unittest.mock import Mock
            mock_aggregator = Mock()
            mock_aggregator.get_all_markets.side_effect = Exception("Aggregator connection failed")
            mock_aggregator._all_markets = {}  # Add the _all_markets attribute to avoid len() error
            mock_get_aggregator.return_value = mock_aggregator
            
            response = client.get("/api/v1/institutional/predictions/markets")
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify error response structure
            assert data["markets"] == []
            assert "error" in data
            assert "Aggregator connection failed" in data["error"]

    def test_prediction_markets_invalid_category(self, client, mock_aggregator):
        """Test handling of invalid category parameter."""
        with patch('monitoring.prediction_markets.get_prediction_aggregator', return_value=mock_aggregator):
            response = client.get("/api/v1/institutional/predictions/markets?category=invalid_category")
            
            assert response.status_code == 200
            data = response.json()
            
            # Should fall back to all markets when category is invalid
            assert len(data["markets"]) == 3
            assert data["count"] == 3

    def test_prediction_markets_schema_compliance(self, client, mock_aggregator):
        """Test that market schema matches expected structure."""
        with patch('monitoring.prediction_markets.get_prediction_aggregator', return_value=mock_aggregator):
            response = client.get("/api/v1/institutional/predictions/markets")
            
            assert response.status_code == 200
            data = response.json()
            markets = data["markets"]
            
            # Test the first market in detail
            market = markets[0]
            
            # Verify all required fields are present and have correct types
            required_fields = {
                "market_id": str,
                "platform": str,
                "question": str,
                "category": str,
                "yes_price": (int, float),
                "no_price": (int, float),
                "implied_probability": (int, float),
                "volume_24h": (int, float),
                "total_volume": (int, float),
                "liquidity": (int, float),
                "status": str,
                "last_updated": (int, float),
            }
            
            for field, expected_type in required_fields.items():
                assert field in market, f"Missing required field: {field}"
                assert isinstance(market[field], expected_type), f"Field {field} has wrong type: {type(market[field])}"
            
            # Verify specific values make sense
            assert market["market_id"].startswith("poly_") or market["market_id"].startswith("kalshi_")
            assert market["platform"] in ["polymarket", "kalshi", "augur"]
            assert market["category"] in ["crypto", "politics", "economics", "sports", "weather", "entertainment", "science", "finance"]
            assert market["status"] in ["open", "pending", "resolved_yes", "resolved_no", "disputed", "voided"]
            assert 0.0 <= market["implied_probability"] <= 1.0
            assert market["yes_price"] + market["no_price"] == 1.0  # Should sum to 1.0

    def _verify_market_schema(self, market):
        """Helper method to verify market schema compliance."""
        required_fields = [
            "market_id",
            "platform", 
            "question",
            "category",
            "yes_price",
            "no_price",
            "implied_probability",
            "volume_24h",
            "total_volume",
            "liquidity",
            "status",
            "last_updated"
        ]
        
        for field in required_fields:
            assert field in market, f"Missing required field: {field}"
        
        # Verify logical constraints
        assert isinstance(market["market_id"], str)
        assert isinstance(market["question"], str)
        assert isinstance(market["platform"], str)
        assert isinstance(market["status"], str)
        assert isinstance(market["yes_price"], (int, float))
        assert isinstance(market["no_price"], (int, float))
        assert isinstance(market["implied_probability"], (int, float))
        
        # Verify probability constraints
        assert 0.0 <= market["implied_probability"] <= 1.0
        assert 0.0 <= market["yes_price"] <= 1.0
        assert 0.0 <= market["no_price"] <= 1.0
        assert abs(market["yes_price"] + market["no_price"] - 1.0) < 0.01  # Allow small rounding errors
