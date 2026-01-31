"""Integration tests for prediction markets arbitrage analytics."""

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


class TestPredictionArbitrage:
    """Integration tests for prediction markets arbitrage analytics."""

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

    def test_arbitrage_happy_path(self, client, mock_aggregator_with_arbitrage):
        """Test arbitrage endpoint with cross-venue opportunities."""
        with patch('monitoring.prediction_markets.get_prediction_aggregator', return_value=mock_aggregator_with_arbitrage):
            response = client.get("/api/v1/institutional/predictions/arbitrage")
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify response structure
            assert "opportunities" in data
            assert "count" in data
            assert "min_spread_used" in data
            assert "status" in data
            
            opportunities = data["opportunities"]
            assert len(opportunities) == 1  # One arbitrage opportunity
            
            # Verify arbitrage opportunity structure
            opp = opportunities[0]
            assert "canonical_question" in opp
            assert "markets" in opp
            assert "max_probability" in opp
            assert "min_probability" in opp
            assert "spread_probability" in opp
            assert "max_probability_venue" in opp
            assert "min_probability_venue" in opp
            
            # Verify values
            assert opp["max_probability"] == 0.65  # Polymarket
            assert opp["min_probability"] == 0.52  # Kalshi
            assert opp["spread_probability"] == 0.13  # 13% spread
            assert opp["max_probability_venue"] == "polymarket"
            assert opp["min_probability_venue"] == "kalshi"
            
            # Verify markets list
            markets = opp["markets"]
            assert len(markets) == 3  # 3 venues for this question
            venues = [m["venue"] for m in markets]
            assert "polymarket" in venues
            assert "kalshi" in venues
            assert "augur" in venues
            
            # Verify market structure
            for market in markets:
                assert "venue" in market
                assert "market_id" in market
                assert "question" in market
                assert "implied_probability" in market
                assert "yes_price" in market
                assert "no_price" in market
                assert "liquidity" in market

    def test_arbitrage_no_opportunities(self, client, mock_aggregator_no_arbitrage):
        """Test arbitrage endpoint with no cross-venue opportunities."""
        with patch('monitoring.prediction_markets.get_prediction_aggregator', return_value=mock_aggregator_no_arbitrage):
            response = client.get("/api/v1/institutional/predictions/arbitrage")
            
            assert response.status_code == 200
            data = response.json()
            
            # Should return empty opportunities list
            assert data["opportunities"] == []
            assert data["count"] == 0
            assert data["min_spread_used"] == 0.05  # Default threshold

    def test_arbitrage_threshold_behavior(self, client, mock_aggregator_with_arbitrage):
        """Test arbitrage threshold filtering."""
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

    def test_arbitrage_limit_parameter(self, client, mock_aggregator_with_arbitrage):
        """Test arbitrage limit parameter."""
        with patch('monitoring.prediction_markets.get_prediction_aggregator', return_value=mock_aggregator_with_arbitrage):
            response = client.get("/api/v1/institutional/predictions/arbitrage?limit=1")
            assert response.status_code == 200
            data = response.json()
            assert len(data["opportunities"]) <= 1

    def test_arbitrage_error_handling(self, client):
        """Test arbitrage endpoint error handling."""
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
            
            response = client.get("/api/v1/institutional/predictions/arbitrage")
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify error response structure - analytics function catches errors and returns empty list
            assert data["opportunities"] == []
            assert data["count"] == 0
            assert data["min_spread_used"] == 0.05
            assert data["status"]["running"] == False

    def test_arbitrage_schema_compliance(self, client, mock_aggregator_with_arbitrage):
        """Test arbitrage response schema compliance."""
        with patch('monitoring.prediction_markets.get_prediction_aggregator', return_value=mock_aggregator_with_arbitrage):
            response = client.get("/api/v1/institutional/predictions/arbitrage")
            assert response.status_code == 200
            
            data = response.json()
            opportunities = data["opportunities"]
            
            # Test first opportunity has all required fields
            opp = opportunities[0]
            required_fields = [
                "canonical_question", "markets", "max_probability", 
                "min_probability", "spread_probability", 
                "max_probability_venue", "min_probability_venue"
            ]
            
            for field in required_fields:
                assert field in opp, f"Missing arbitrage field: {field}"
                assert opp[field] is not None, f"Arbitrage field {field} is null"
            
            # Verify data types
            assert isinstance(opp["canonical_question"], str)
            assert isinstance(opp["markets"], list)
            assert isinstance(opp["max_probability"], (int, float))
            assert isinstance(opp["min_probability"], (int, float))
            assert isinstance(opp["spread_probability"], (int, float))
            assert isinstance(opp["max_probability_venue"], str)
            assert isinstance(opp["min_probability_venue"], str)
            
            # Verify logical constraints
            assert 0.0 <= opp["max_probability"] <= 1.0
            assert 0.0 <= opp["min_probability"] <= 1.0
            assert 0.0 <= opp["spread_probability"] <= 1.0
            assert opp["spread_probability"] == opp["max_probability"] - opp["min_probability"]
            assert opp["max_probability"] > opp["min_probability"]

    def test_arbitrage_canonical_grouping(self, client):
        """Test that markets are correctly grouped by canonical question."""
        # Create markets with similar but not identical questions
        markets = [
            PredictionMarket(
                market_id="poly_1",
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
            PredictionMarket(
                market_id="kalshi_1",
                platform=PredictionPlatform.KALSHI,
                question="Will Bitcoin reach $100,000 by end of 2024?",  # Slight variation
                category=MarketCategory.CRYPTO,
                yes_price=0.52,
                no_price=0.48,
                volume_24h=800000.0,
                total_volume=4000000.0,
                liquidity=200000.0,
                status=ResolutionStatus.OPEN,
            ),
            PredictionMarket(
                market_id="poly_2",
                platform=PredictionPlatform.POLYMARKET,
                question="Will ETH reach $5k by end of 2024?",  # Different question
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
            "platforms": ["polymarket", "kalshi"],
        }
        aggregator._all_markets = {m.market_id: m for m in markets}

        with patch('monitoring.prediction_markets.get_prediction_aggregator', return_value=aggregator):
            response = client.get("/api/v1/institutional/predictions/arbitrage")
            assert response.status_code == 200
            
            data = response.json()
            opportunities = data["opportunities"]
            
            # Should find one arbitrage opportunity for Bitcoin question
            assert len(opportunities) == 1
            opp = opportunities[0]
            
            # Canonical question should be normalized
            assert "bitcoin" in opp["canonical_question"].lower()
            assert "100k" in opp["canonical_question"].lower()
            
            # Should include both Bitcoin markets
            venues = [m["venue"] for m in opp["markets"]]
            assert len(venues) == 2
            assert "polymarket" in venues
            assert "kalshi" in venues
