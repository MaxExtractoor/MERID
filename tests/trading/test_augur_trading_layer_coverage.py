"""Comprehensive tests for trading/augur_trading_layer.py - Coverage improvement."""

import pytest
from unittest.mock import MagicMock, patch
import httpx

from trading.augur_trading_layer import AugurTradingLayer


@pytest.fixture
def layer():
    """Create AugurTradingLayer with mocked HTTP client."""
    with patch.object(httpx, 'Client') as mock_client:
        layer = AugurTradingLayer()
        layer._client = MagicMock()
        return layer


@pytest.fixture
def mock_layer():
    """Create AugurTradingLayer in mock mode."""
    with patch.object(httpx, 'Client'):
        return AugurTradingLayer(use_mock=True)


# =============================================================================
# Initialization Tests
# =============================================================================

class TestAugurTradingLayerInit:
    """Test AugurTradingLayer initialization."""

    def test_init_defaults(self, monkeypatch):
        monkeypatch.delenv("MERID_AUGUR_MOCK", raising=False)
        
        with patch.object(httpx, 'Client') as mock_client:
            layer = AugurTradingLayer()
        
        assert layer.use_mock is False
        assert layer.SUBGRAPH_URL == "https://api.thegraph.com/subgraphs/name/augurproject/augur-v2"

    def test_init_with_mock(self):
        with patch.object(httpx, 'Client'):
            layer = AugurTradingLayer(use_mock=True)
        
        assert layer.use_mock is True

    def test_init_from_env(self, monkeypatch):
        monkeypatch.setenv("MERID_AUGUR_MOCK", "1")
        
        with patch.object(httpx, 'Client'):
            layer = AugurTradingLayer()
        
        assert layer.use_mock is True

    def test_init_custom_timeout(self):
        with patch.object(httpx, 'Client') as mock_client:
            layer = AugurTradingLayer(timeout=30.0)
            mock_client.assert_called_once_with(timeout=30.0)


# =============================================================================
# Fetch Markets Tests
# =============================================================================

class TestFetchMarkets:
    """Test fetch_markets method."""

    def test_fetch_markets_mock_mode(self, mock_layer):
        """Test fetch_markets in mock mode."""
        markets = mock_layer.fetch_markets(limit=5)
        
        assert len(markets) == 5
        assert markets[0]["id"] == "mock-augur-0"
        assert "description" in markets[0]
        assert "yes_price" in markets[0]

    def test_fetch_markets_live_success(self, layer):
        """Test successful live market fetch."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "markets": [
                    {
                        "id": "market_1",
                        "description": "Test market",
                        "volume": "1000",
                        "outcomes": [
                            {"id": "1", "price": "0.65", "payoutNumerators": []},
                            {"id": "2", "price": "0.35", "payoutNumerators": []}
                        ]
                    }
                ]
            }
        }
        layer._client.post.return_value = mock_response
        
        markets = layer.fetch_markets()
        
        assert len(markets) == 1
        assert markets[0]["id"] == "market_1"
        assert markets[0]["yes_price"] == 0.65

    def test_fetch_markets_with_category(self, layer):
        """Test fetch_markets with category filter."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": {"markets": []}}
        layer._client.post.return_value = mock_response
        
        markets = layer.fetch_markets(category="sports", limit=10)
        
        layer._client.post.assert_called_once()
        call_args = layer._client.post.call_args
        assert "sports" in call_args.kwargs["json"]["query"]

    def test_fetch_markets_error_fallback_to_mock(self, layer):
        """Test fetch_markets falls back to mock on error."""
        layer._client.post.side_effect = Exception("Network error")
        
        markets = layer.fetch_markets(limit=3)
        
        # Should return mock data
        assert len(markets) == 3
        assert markets[0]["id"].startswith("mock-augur")

    def test_fetch_markets_no_outcomes(self, layer):
        """Test fetch_markets with market having no outcomes."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "markets": [
                    {
                        "id": "market_1",
                        "description": "No outcomes market",
                        "volume": "500",
                        "outcomes": None
                    }
                ]
            }
        }
        layer._client.post.return_value = mock_response
        
        markets = layer.fetch_markets()
        
        assert len(markets) == 1
        assert markets[0]["yes_price"] == 0.5  # Default when no outcomes


# =============================================================================
# Find Negative Risk Opportunities Tests
# =============================================================================

class TestFindNegativeRiskOpportunities:
    """Test find_negative_risk_opportunities method."""

    def test_find_opportunities_empty_list(self, layer):
        """Test with empty market list."""
        opportunities = layer.find_negative_risk_opportunities([])
        assert opportunities == []

    def test_find_opportunities_none_market(self, layer):
        """Test with None in market list."""
        opportunities = layer.find_negative_risk_opportunities([None, None])
        assert opportunities == []

    def test_find_opportunities_below_volume(self, layer):
        """Test market below minimum volume threshold."""
        markets = [
            {"id": "low_vol", "volume": 50, "yes_price": 0.3, "no_price": 0.8}
        ]
        
        opportunities = layer.find_negative_risk_opportunities(markets, min_volume=100.0)
        
        assert opportunities == []

    def test_find_opportunities_no_edge(self, layer):
        """Test market with no edge."""
        markets = [
            {"id": "no_edge", "volume": 1000, "yes_price": 0.5, "no_price": 0.5}
        ]
        
        opportunities = layer.find_negative_risk_opportunities(markets)
        
        assert opportunities == []

    def test_find_opportunities_with_edge(self, layer):
        """Test market with sufficient edge."""
        markets = [
            {
                "id": "edge_market",
                "description": "Good opportunity",
                "volume": 500,
                "yes_price": 0.3,
                "no_price": 0.8  # edge = 0.8 - (1 - 0.3) = 0.1
            }
        ]
        
        opportunities = layer.find_negative_risk_opportunities(
            markets, min_volume=100.0, yes_prob_threshold=0.05
        )
        
        assert len(opportunities) == 1
        assert opportunities[0]["id"] == "edge_market"
        assert opportunities[0]["platform"] == "augur"

    def test_find_opportunities_sorted_by_edge(self, layer):
        """Test opportunities are sorted by edge descending."""
        # edge = max(0, no_price - (1 - yes_price))
        # low_edge: 0.7 - 0.6 = 0.1
        # high_edge: 0.95 - 0.7 = 0.25
        markets = [
            {"id": "low_edge", "volume": 500, "yes_price": 0.4, "no_price": 0.7},
            {"id": "high_edge", "volume": 500, "yes_price": 0.3, "no_price": 0.95},
        ]
        
        opportunities = layer.find_negative_risk_opportunities(
            markets, min_volume=100.0, yes_prob_threshold=0.05
        )
        
        assert len(opportunities) == 2
        assert opportunities[0]["id"] == "high_edge"

    def test_find_opportunities_missing_no_price(self, layer):
        """Test with market missing no_price (calculated from yes_price)."""
        markets = [
            {"id": "calc_no", "volume": 500, "yes_price": 0.3}
        ]
        
        opportunities = layer.find_negative_risk_opportunities(markets)
        
        # no_price calculated as 1 - yes_price = 0.7, edge = 0


# =============================================================================
# Place Trade Tests
# =============================================================================

class TestPlaceTrade:
    """Test place_trade method."""

    def test_place_trade_returns_queued(self, layer):
        """Test place_trade returns queued status."""
        result = layer.place_trade("market_123", "yes", 0.5)
        
        assert result["status"] == "queued"
        assert result["market_id"] == "market_123"
        assert result["outcome"] == "yes"
        assert result["amount_eth"] == 0.5
        assert result["tx_hash"] is None


# =============================================================================
# Extract Yes Price Tests
# =============================================================================

class TestExtractYesPrice:
    """Test _extract_yes_price method."""

    def test_extract_yes_price_empty(self, layer):
        """Test with empty outcomes."""
        result = layer._extract_yes_price([])
        assert result is None

    def test_extract_yes_price_single(self, layer):
        """Test with single outcome."""
        outcomes = [{"id": "1", "price": "0.65"}]
        result = layer._extract_yes_price(outcomes)
        assert result == 0.65

    def test_extract_yes_price_multiple(self, layer):
        """Test with multiple outcomes - returns max price."""
        outcomes = [
            {"id": "1", "price": "0.35"},
            {"id": "2", "price": "0.65"}
        ]
        result = layer._extract_yes_price(outcomes)
        assert result == 0.65

    def test_extract_yes_price_error(self, layer):
        """Test with invalid data returns None."""
        outcomes = [{"id": "1", "price": "invalid"}]
        result = layer._extract_yes_price(outcomes)
        assert result is None


# =============================================================================
# Mock Markets Tests
# =============================================================================

class TestMockMarkets:
    """Test _mock_markets method."""

    def test_mock_markets_returns_correct_count(self, layer):
        """Test mock_markets returns correct number of markets."""
        markets = layer._mock_markets(10)
        assert len(markets) == 10

    def test_mock_markets_structure(self, layer):
        """Test mock_markets returns correct structure."""
        markets = layer._mock_markets(1)
        
        assert markets[0]["id"] == "mock-augur-0"
        assert "description" in markets[0]
        assert "volume" in markets[0]
        assert "yes_price" in markets[0]
        assert "no_price" in markets[0]
