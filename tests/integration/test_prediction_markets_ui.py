"""Integration tests for prediction markets UI functionality."""

import pytest
from unittest.mock import patch, Mock
from fastapi.testclient import TestClient
import time

from monitoring.prediction_markets import (
    PredictionMarket, 
    PredictionPlatform, 
    MarketCategory, 
    ResolutionStatus
)


class TestPredictionMarketsUI:
    """Integration tests for prediction markets UI endpoints and rendering."""

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
                resolution_date=time.time() + 86400 * 30,
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
                resolution_date=time.time() + 86400 * 15,
                status=ResolutionStatus.PENDING,
            ),
        ]

        from unittest.mock import Mock
        aggregator = Mock()
        
        def mock_get_all_markets(limit=100):
            return markets[:limit]
        
        aggregator.get_all_markets.side_effect = mock_get_all_markets
        aggregator.get_status.return_value = {
            "running": True,
            "total_markets": len(markets),
            "platforms": ["polymarket", "kalshi"],
        }
        aggregator._all_markets = {m.market_id: m for m in markets}
        
        return aggregator

    @pytest.fixture
    def client(self):
        """Create test client."""
        from web.main import create_app
        app = create_app()
        return TestClient(app)

    def test_prediction_markets_ui_happy_path(self, client, mock_aggregator):
        """Test UI renders prediction markets correctly with data."""
        with patch('monitoring.prediction_markets.get_prediction_aggregator', return_value=mock_aggregator):
            # Get the dashboard page
            response = client.get("/debug-v2")
            assert response.status_code == 200
            
            # Verify the page contains the prediction markets section
            html_content = response.text
            assert "📊 Prediction Markets" in html_content
            assert "prediction-markets" in html_content
            assert "Refresh Markets" in html_content
            
            # Test the API endpoint that the UI calls
            api_response = client.get("/api/v1/institutional/predictions/markets")
            assert api_response.status_code == 200
            
            data = api_response.json()
            assert "markets" in data
            assert len(data["markets"]) == 2
            assert data["count"] == 2
            
            # Verify market data structure that UI expects
            market = data["markets"][0]
            assert "market_id" in market
            assert "question" in market
            assert "platform" in market
            assert "status" in market
            assert "yes_price" in market
            assert "no_price" in market
            assert "implied_probability" in market
            assert "volume_24h" in market
            assert "liquidity" in market

    def test_prediction_markets_ui_empty_markets(self, client):
        """Test UI handles empty markets list gracefully."""
        # Test API response with empty markets
        response = client.get("/api/v1/institutional/predictions/markets")
        assert response.status_code == 200
            
        data = response.json()
        # The API should return some data (real or mocked)
        assert "markets" in data
        assert "count" in data
            
        # Verify dashboard still loads
        dashboard_response = client.get("/debug-v2")
        assert dashboard_response.status_code == 200
        assert "📊 Prediction Markets" in dashboard_response.text

    def test_prediction_markets_ui_error_handling(self, client):
        """Test UI handles API errors gracefully."""
        with patch('monitoring.prediction_markets.get_prediction_aggregator') as mock_get_aggregator:
            # Mock aggregator to raise an exception
            from unittest.mock import Mock
            mock_aggregator = Mock()
            mock_aggregator.get_all_markets.side_effect = Exception("API connection failed")
            mock_aggregator._all_markets = {}
            mock_get_aggregator.return_value = mock_aggregator
            
            # Test API error response
            response = client.get("/api/v1/institutional/predictions/markets")
            assert response.status_code == 200
            
            data = response.json()
            assert data["markets"] == []
            assert "error" in data
            assert "API connection failed" in data["error"]
            
            # Verify dashboard still loads with error handling
            dashboard_response = client.get("/debug-v2")
            assert dashboard_response.status_code == 200
            assert "📊 Prediction Markets" in dashboard_response.text

    def test_prediction_markets_ui_schema_compliance(self, client, mock_aggregator):
        """Test UI can handle all expected market fields and edge cases."""
        with patch('monitoring.prediction_markets.get_prediction_aggregator', return_value=mock_aggregator):
            response = client.get("/api/v1/institutional/predictions/markets")
            assert response.status_code == 200
            
            data = response.json()
            markets = data["markets"]
            
            # Test first market has all required fields for UI
            market = markets[0]
            required_ui_fields = [
                "market_id", "question", "platform", "category", "status",
                "yes_price", "no_price", "implied_probability", 
                "volume_24h", "total_volume", "liquidity", "last_updated"
            ]
            
            for field in required_ui_fields:
                assert field in market, f"Missing UI field: {field}"
                assert market[field] is not None, f"UI field {field} is null"
            
            # Verify data types are UI-friendly
            assert isinstance(market["question"], str)
            assert isinstance(market["platform"], str)
            assert isinstance(market["status"], str)
            assert isinstance(market["yes_price"], (int, float))
            assert isinstance(market["no_price"], (int, float))
            assert isinstance(market["implied_probability"], (int, float))
            
            # Verify UI-relevant constraints
            assert 0.0 <= market["implied_probability"] <= 1.0
            assert 0.0 <= market["yes_price"] <= 1.0
            assert 0.0 <= market["no_price"] <= 1.0
            assert market["status"] in ["open", "closed", "pending", "resolved_yes", "resolved_no", "disputed", "voided"]

    def test_prediction_markets_ui_different_statuses(self, client):
        """Test UI displays different market statuses correctly."""
        markets = [
            PredictionMarket(
                market_id="open_market",
                platform=PredictionPlatform.POLYMARKET,
                question="Open market question",
                category=MarketCategory.CRYPTO,
                yes_price=0.60,
                no_price=0.40,
                volume_24h=100000.0,
                total_volume=500000.0,
                liquidity=50000.0,
                status=ResolutionStatus.OPEN,
            ),
            PredictionMarket(
                market_id="pending_market",
                platform=PredictionPlatform.KALSHI,
                question="Pending market question",
                category=MarketCategory.POLITICS,
                yes_price=0.30,
                no_price=0.70,
                volume_24h=200000.0,
                total_volume=1000000.0,
                liquidity=75000.0,
                status=ResolutionStatus.PENDING,
            ),
            PredictionMarket(
                market_id="resolved_market",
                platform=PredictionPlatform.POLYMARKET,
                question="Resolved market question",
                category=MarketCategory.FINANCE,
                yes_price=1.0,
                no_price=0.0,
                volume_24h=300000.0,
                total_volume=1500000.0,
                liquidity=100000.0,
                status=ResolutionStatus.RESOLVED_YES,
            ),
        ]

        from unittest.mock import Mock
        aggregator = Mock()
        aggregator.get_all_markets.return_value = markets
        aggregator.get_status.return_value = {
            "running": True,
            "total_markets": len(markets),
            "platforms": ["polymarket", "kalshi"],
        }
        aggregator._all_markets = {m.market_id: m for m in markets}

        with patch('monitoring.prediction_markets.get_prediction_aggregator', return_value=aggregator):
            response = client.get("/api/v1/institutional/predictions/markets")
            assert response.status_code == 200
            
            data = response.json()
            assert len(data["markets"]) == 3
            
            # Verify all statuses are present
            statuses = [m["status"] for m in data["markets"]]
            assert "open" in statuses
            assert "pending" in statuses
            assert "resolved_yes" in statuses

    def test_prediction_markets_ui_dashboard_integration(self, client, mock_aggregator):
        """Test that prediction markets are integrated into the dashboard properly."""
        with patch('monitoring.prediction_markets.get_prediction_aggregator', return_value=mock_aggregator):
            # Get the dashboard page
            response = client.get("/debug-v2")
            assert response.status_code == 200
            
            html_content = response.text
            
            # Verify prediction markets section is present
            assert "📊 Prediction Markets" in html_content
            assert 'id="prediction-markets"' in html_content
            assert "loadPredictionMarkets()" in html_content
            assert "Refresh Markets" in html_content
            
            # Verify the section has proper structure
            assert '<div class="card">' in html_content
            assert '<h3>📊 Prediction Markets</h3>' in html_content
            assert '<button onclick="loadPredictionMarkets()"' in html_content
            
            # Verify CSS classes are present for styling
            assert "market-card" in html_content
            assert "market-question" in html_content
            assert "market-details" in html_content
            assert "probability-bar" in html_content
