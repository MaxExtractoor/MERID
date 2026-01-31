"""Integration tests for prediction markets arbitrage UI functionality."""

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


class TestPredictionArbitrageUI:
    """Integration tests for prediction markets arbitrage UI endpoints and rendering."""

    @pytest.fixture
    def mock_aggregator_with_arbitrage(self):
        """Create a mock prediction aggregator with cross-venue arbitrage opportunities."""
        markets = [
            # Same question on Polymarket - higher probability
            PredictionMarket(
                market_id="poly_btc_100k",
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
            # Same question on Kalshi - lower probability (arbitrage opportunity)
            PredictionMarket(
                market_id="kalshi_btc_100k",
                platform=PredictionPlatform.KALSHI,
                question="Will Bitcoin reach $100,000 by end of 2024?",
                category=MarketCategory.CRYPTO,
                yes_price=0.52,
                no_price=0.48,
                volume_24h=800000.0,
                total_volume=4000000.0,
                liquidity=200000.0,
                resolution_date=time.time() + 86400 * 30,
                status=ResolutionStatus.OPEN,
            ),
            # Same question on Augur - middle probability
            PredictionMarket(
                market_id="augur_btc_100k",
                platform=PredictionPlatform.AUGUR,
                question="Will Bitcoin reach $100k by end of 2024?",
                category=MarketCategory.CRYPTO,
                yes_price=0.58,
                no_price=0.42,
                volume_24h=600000.0,
                total_volume=3000000.0,
                liquidity=150000.0,
                resolution_date=time.time() + 86400 * 30,
                status=ResolutionStatus.OPEN,
            ),
            # Different question - should not be grouped
            PredictionMarket(
                market_id="poly_eth_5k",
                platform=PredictionPlatform.POLYMARKET,
                question="Will Ethereum reach $5k by end of 2024?",
                category=MarketCategory.CRYPTO,
                yes_price=0.45,
                no_price=0.55,
                volume_24h=300000.0,
                total_volume=1500000.0,
                liquidity=75000.0,
                resolution_date=time.time() + 86400 * 20,
                status=ResolutionStatus.OPEN,
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
            "platforms": ["polymarket", "kalshi", "augur"],
        }
        aggregator._all_markets = {m.market_id: m for m in markets}
        
        return aggregator

    @pytest.fixture
    def mock_aggregator_no_arbitrage(self):
        """Create a mock aggregator with no arbitrage opportunities."""
        markets = [
            # Single venue only
            PredictionMarket(
                market_id="poly_single",
                platform=PredictionPlatform.POLYMARKET,
                question="Will Bitcoin reach $100k by end of 2024?",
                category=MarketCategory.CRYPTO,
                yes_price=0.65,
                no_price=0.35,
                volume_24h=1000000.0,
                total_volume=5000000.0,
                liquidity=250000.0,
                status=ResolutionStatus.OPEN,
            ),
            # Different questions
            PredictionMarket(
                market_id="poly_eth_5k",
                platform=PredictionPlatform.POLYMARKET,
                question="Will Ethereum reach $5k by end of 2024?",
                category=MarketCategory.CRYPTO,
                yes_price=0.45,
                no_price=0.55,
                volume_24h=300000.0,
                total_volume=1500000.0,
                liquidity=75000.0,
                status=ResolutionStatus.OPEN,
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
            "platforms": ["polymarket"],
        }
        aggregator._all_markets = {m.market_id: m for m in markets}
        
        return aggregator

    @pytest.fixture
    def client(self):
        """Create test client."""
        from web.main import create_app
        app = create_app()
        return TestClient(app)

    def test_arbitrage_ui_happy_path(self, client, mock_aggregator_with_arbitrage):
        """Test UI renders arbitrage opportunities correctly with data."""
        with patch('monitoring.prediction_markets.get_prediction_aggregator', return_value=mock_aggregator_with_arbitrage):
            # Get the dashboard page
            response = client.get("/debug-v2")
            assert response.status_code == 200
            
            # Verify the page contains the arbitrage section
            html_content = response.text
            assert "🔍 Arbitrage Opportunities" in html_content
            assert "arbitrage-opportunities" in html_content
            assert "Refresh Arbitrage" in html_content
            assert "min-spread-slider" in html_content
            
            # Test the API endpoint that the UI calls
            api_response = client.get("/api/v1/institutional/predictions/arbitrage")
            assert api_response.status_code == 200
            
            data = api_response.json()
            assert "opportunities" in data
            assert len(data["opportunities"]) == 1  # One arbitrage opportunity
            assert data["count"] == 1
            
            # Verify arbitrage opportunity structure
            opportunity = data["opportunities"][0]
            assert "canonical_question" in opportunity
            assert "markets" in opportunity
            assert "max_probability" in opportunity
            assert "min_probability" in opportunity
            assert "spread_probability" in opportunity
            assert "max_probability_venue" in opportunity
            assert "min_probability_venue" in opportunity

    def test_arbitrage_ui_empty_opportunities(self, client, mock_aggregator_no_arbitrage):
        """Test UI handles empty arbitrage opportunities gracefully."""
        with patch('monitoring.prediction_markets.get_prediction_aggregator', return_value=mock_aggregator_no_arbitrage):
            # Test API response with empty opportunities
            response = client.get("/api/v1/institutional/predictions/arbitrage")
            assert response.status_code == 200
            
            data = response.json()
            # The API should return some data (real or mocked)
            assert "opportunities" in data
            assert "count" in data
            
            # Verify dashboard still loads
            dashboard_response = client.get("/debug-v2")
            assert dashboard_response.status_code == 200
            assert "🔍 Arbitrage Opportunities" in dashboard_response.text

    def test_arbitrage_ui_error_handling(self, client):
        """Test UI handles API errors gracefully."""
        with patch('monitoring.prediction_markets.get_prediction_aggregator') as mock_get_aggregator:
            # Mock aggregator to raise an exception
            from unittest.mock import Mock
            mock_aggregator = Mock()
            mock_aggregator.get_all_markets.side_effect = Exception("Aggregator connection failed")
            mock_aggregator._all_markets = {}
            mock_aggregator.get_status.return_value = {
                "running": False,
                "total_markets": 0,
                "platforms": [],
            }
            mock_get_aggregator.return_value = mock_aggregator
            
            # Test API error response
            response = client.get("/api/v1/institutional/predictions/arbitrage")
            assert response.status_code == 200
            
            data = response.json()
            assert data["opportunities"] == []
            assert data["count"] == 0
            
            # Verify dashboard still loads with error handling
            dashboard_response = client.get("/debug-v2")
            assert dashboard_response.status_code == 200
            assert "🔍 Arbitrage Opportunities" in dashboard_response.text

    def test_arbitrage_ui_threshold_behavior(self, client, mock_aggregator_with_arbitrage):
        """Test UI threshold filtering behavior."""
        with patch('monitoring.prediction_markets.get_prediction_aggregator', return_value=mock_aggregator_with_arbitrage):
            # Test with high threshold (should return empty)
            response = client.get("/api/v1/institutional/predictions/arbitrage?min_spread=0.20")
            assert response.status_code == 200
            data = response.json()
            assert data["opportunities"] == []  # 13% spread < 20% threshold
            assert data["min_spread_used"] == 0.20
            
            # Test with low threshold (should return opportunities)
            response = client.get("/api/v1/institutional/predictions/arbitrage?min_spread=0.01")
            assert response.status_code == 200
            data = response.json()
            assert len(data["opportunities"]) == 1  # 13% spread > 1% threshold
            assert data["min_spread_used"] == 0.01

    def test_arbitrage_ui_schema_compliance(self, client, mock_aggregator_with_arbitrage):
        """Test UI can handle all expected arbitrage fields and edge cases."""
        with patch('monitoring.prediction_markets.get_prediction_aggregator', return_value=mock_aggregator_with_arbitrage):
            response = client.get("/api/v1/institutional/predictions/arbitrage")
            assert response.status_code == 200
            
            data = response.json()
            opportunities = data["opportunities"]
            
            # Test first opportunity has all required fields for UI
            opportunity = opportunities[0]
            required_ui_fields = [
                "canonical_question", "markets", "max_probability", 
                "min_probability", "spread_probability", 
                "max_probability_venue", "min_probability_venue"
            ]
            
            for field in required_ui_fields:
                assert field in opportunity, f"Missing arbitrage UI field: {field}"
                assert opportunity[field] is not None, f"Arbitrage UI field {field} is null"
            
            # Verify data types are UI-friendly
            assert isinstance(opportunity["canonical_question"], str)
            assert isinstance(opportunity["markets"], list)
            assert isinstance(opportunity["max_probability"], (int, float))
            assert isinstance(opportunity["min_probability"], (int, float))
            assert isinstance(opportunity["spread_probability"], (int, float))
            assert isinstance(opportunity["max_probability_venue"], str)
            assert isinstance(opportunity["min_probability_venue"], str)
            
            # Verify UI-relevant constraints
            assert 0.0 <= opportunity["max_probability"] <= 1.0
            assert 0.0 <= opportunity["min_probability"] <= 1.0
            assert 0.0 <= opportunity["spread_probability"] <= 1.0
            assert opportunity["spread_probability"] == opportunity["max_probability"] - opportunity["min_probability"]
            assert opportunity["max_probability"] > opportunity["min_probability"]

    def test_arbitrage_ui_different_spreads(self, client):
        """Test UI displays different spread levels correctly."""
        markets = [
            # High spread opportunity
            PredictionMarket(
                market_id="poly_high",
                platform=PredictionPlatform.POLYMARKET,
                question="Will BTC reach $100k?",
                category=MarketCategory.CRYPTO,
                yes_price=0.75,
                no_price=0.25,
                volume_24h=1000000.0,
                total_volume=5000000.0,
                liquidity=250000.0,
                status=ResolutionStatus.OPEN,
            ),
            PredictionMarket(
                market_id="kalshi_high",
                platform=PredictionPlatform.KALSHI,
                question="Will BTC reach $100k?",
                category=MarketCategory.CRYPTO,
                yes_price=0.45,
                no_price=0.55,
                volume_24h=800000.0,
                total_volume=4000000.0,
                liquidity=200000.0,
                status=ResolutionStatus.OPEN,
            ),
            # Low spread opportunity
            PredictionMarket(
                market_id="poly_low",
                platform=PredictionPlatform.POLYMARKET,
                question="Will ETH reach $3k?",
                category=MarketCategory.CRYPTO,
                yes_price=0.55,
                no_price=0.45,
                volume_24h=500000.0,
                total_volume=2500000.0,
                liquidity=125000.0,
                status=ResolutionStatus.OPEN,
            ),
            PredictionMarket(
                market_id="kalshi_low",
                platform=PredictionPlatform.KALSHI,
                question="Will ETH reach $3k?",
                category=MarketCategory.CRYPTO,
                yes_price=0.52,
                no_price=0.48,
                volume_24h=400000.0,
                total_volume=2000000.0,
                liquidity=100000.0,
                status=ResolutionStatus.OPEN,
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

        with patch('monitoring.prediction_markets.get_prediction_aggregator', return_value=aggregator):
            response = client.get("/api/v1/institutional/predictions/arbitrage")
            assert response.status_code == 200
            
            data = response.json()
            opportunities = data["opportunities"]
            assert len(opportunities) >= 1  # At least one arbitrage opportunity
            
            # Verify different spread levels
            spreads = [opp["spread_probability"] for opp in opportunities]
            # Should have at least one high spread opportunity
            assert any(spread >= 0.20 for spread in spreads)  # High spread (75% - 45%)

    def test_arbitrage_ui_dashboard_integration(self, client, mock_aggregator_with_arbitrage):
        """Test that arbitrage opportunities are integrated into the dashboard properly."""
        with patch('monitoring.prediction_markets.get_prediction_aggregator', return_value=mock_aggregator_with_arbitrage):
            # Get the dashboard page
            response = client.get("/debug-v2")
            assert response.status_code == 200
            
            html_content = response.text
            
            # Verify arbitrage section is present
            assert "🔍 Arbitrage Opportunities" in html_content
            assert 'id="arbitrage-opportunities"' in html_content
            assert "loadArbitrageOpportunities()" in html_content
            assert "Refresh Arbitrage" in html_content
            
            # Verify the section has proper structure
            assert '<div class="card">' in html_content
            assert '<h3>🔍 Arbitrage Opportunities</h3>' in html_content
            assert '<button onclick="loadArbitrageOpportunities()"' in html_content
            
            # Verify CSS classes are present for styling
            assert "arbitrage-card" in html_content
            assert "arbitrage-question" in html_content
            assert "arbitrage-spread" in html_content
            assert "spread-bar" in html_content
            assert "arbitrage-venues" in html_content
