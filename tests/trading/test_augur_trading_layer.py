"""Tests for trading/augur_trading_layer.py."""
import pytest
from unittest.mock import Mock, patch
from trading.augur_trading_layer import AugurTradingLayer


class TestAugurTradingLayerInitialization:
    """Test AugurTradingLayer initialization."""

    def test_default_initialization(self):
        """Test default initialization."""
        layer = AugurTradingLayer()
        assert layer.use_mock is False
        assert layer.SUBGRAPH_URL == "https://api.thegraph.com/subgraphs/name/augurproject/augur-v2"

    @patch('trading.augur_trading_layer.os.getenv')
    def test_mock_from_env(self, mock_getenv):
        """Test mock mode from environment variable."""
        mock_getenv.return_value = "1"
        layer = AugurTradingLayer()
        assert layer.use_mock is True

    def test_explicit_mock(self):
        """Test explicit mock parameter."""
        layer = AugurTradingLayer(use_mock=True)
        assert layer.use_mock is True


class TestAugurTradingLayerFetchMarkets:
    """Test fetch_markets method."""

    def test_fetch_mock_markets(self):
        """Test fetching mock markets."""
        layer = AugurTradingLayer(use_mock=True)
        markets = layer.fetch_markets(limit=5)
        
        assert len(markets) == 5
        assert markets[0]["id"] == "mock-augur-0"
        assert "description" in markets[0]
        assert "yes_price" in markets[0]
        assert "no_price" in markets[0]

    def test_fetch_live_markets_success(self):
        """Test fetching live markets."""
        layer = AugurTradingLayer(use_mock=False)
        
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": {
                "markets": [
                    {
                        "id": "m1",
                        "description": "Test Market",
                        "volume": "1000000",
                        "outcomes": [
                            {"id": "o1", "price": "0.6", "payoutNumerators": [60, 40]}
                        ]
                    }
                ]
            }
        }
        mock_response.raise_for_status = Mock()
        
        layer._client = Mock()
        layer._client.post.return_value = mock_response
        
        markets = layer.fetch_markets(limit=1)
        
        assert len(markets) == 1
        assert markets[0]["id"] == "m1"
        assert markets[0]["yes_price"] == 0.6
        assert markets[0]["no_price"] == 0.4

    def test_fetch_live_markets_error_fallback(self):
        """Test fallback to mock on error."""
        layer = AugurTradingLayer(use_mock=False)
        layer._client = Mock()
        layer._client.post.side_effect = Exception("Network error")
        
        markets = layer.fetch_markets(limit=3)
        
        # Should return mock markets
        assert len(markets) == 3
        assert "mock-augur" in markets[0]["id"]


class TestAugurTradingLayerFindNegativeRisk:
    """Test find_negative_risk_opportunities method."""

    def test_find_opportunities(self):
        """Test finding negative risk opportunities."""
        layer = AugurTradingLayer()
        markets = [
            {
                "id": "m1",
                "description": "Test",
                "volume": 1000.0,
                "yes_price": 0.8,
                "no_price": 0.3  # Sum > 1, indicates negative risk
            }
        ]
        
        opportunities = layer.find_negative_risk_opportunities(markets, min_volume=100.0)
        
        assert len(opportunities) == 1
        assert opportunities[0]["edge"] > 0
        assert opportunities[0]["platform"] == "augur"

    def test_filter_by_volume(self):
        """Test volume filtering."""
        layer = AugurTradingLayer()
        markets = [
            {"id": "m1", "volume": 50.0, "yes_price": 0.8, "no_price": 0.3}
        ]
        
        opportunities = layer.find_negative_risk_opportunities(markets, min_volume=100.0)
        
        assert len(opportunities) == 0

    def test_empty_markets(self):
        """Test with empty markets list."""
        layer = AugurTradingLayer()
        opportunities = layer.find_negative_risk_opportunities([])
        assert opportunities == []


class TestAugurTradingLayerPlaceTrade:
    """Test place_trade method."""

    def test_place_trade(self):
        """Test placing a trade."""
        layer = AugurTradingLayer()
        result = layer.place_trade("m1", "yes", 1.5)
        
        assert result["status"] == "queued"
        assert result["market_id"] == "m1"
        assert result["outcome"] == "yes"
        assert result["amount_eth"] == 1.5


class TestAugurTradingLayerExtractYesPrice:
    """Test _extract_yes_price method."""

    def test_extract_from_outcomes(self):
        """Test extracting yes price from outcomes."""
        layer = AugurTradingLayer()
        outcomes = [
            {"id": "o1", "price": "0.4"},
            {"id": "o2", "price": "0.6"}
        ]
        
        price = layer._extract_yes_price(outcomes)
        assert price == 0.6  # Max price

    def test_extract_empty_outcomes(self):
        """Test extracting from empty outcomes."""
        layer = AugurTradingLayer()
        price = layer._extract_yes_price([])
        assert price is None

    def test_extract_invalid_outcomes(self):
        """Test extracting from invalid outcomes."""
        layer = AugurTradingLayer()
        outcomes = [{"id": "o1"}]  # No price
        price = layer._extract_yes_price(outcomes)
        assert price == 0.0  # Default from float(None)


class TestAugurTradingLayerMockMarkets:
    """Test _mock_markets method."""

    def test_mock_markets_structure(self):
        """Test mock markets structure."""
        layer = AugurTradingLayer()
        markets = layer._mock_markets(3)
        
        assert len(markets) == 3
        for i, market in enumerate(markets):
            assert market["id"] == f"mock-augur-{i}"
            assert "description" in market
            assert "volume" in market
            assert "yes_price" in market
            assert "no_price" in market
