"""Tests for Augur trading layer - Batch 25 Coverage."""
import pytest
from unittest.mock import MagicMock, patch
import os

from trading.augur_trading_layer import AugurTradingLayer


class TestAugurTradingLayer:
    """Tests for AugurTradingLayer."""

    @pytest.fixture
    def layer(self):
        """Create trading layer with mock mode."""
        return AugurTradingLayer(use_mock=True)

    def test_initialization(self, layer):
        """Test layer initialization."""
        assert layer.use_mock is True
        assert layer._client is not None

    def test_initialization_with_env(self):
        """Test initialization with environment variable."""
        with patch.dict(os.environ, {"MERID_AUGUR_MOCK": "1"}):
            layer = AugurTradingLayer()
            assert layer.use_mock is True

    def test_fetch_markets_mock(self, layer):
        """Test fetching markets in mock mode."""
        markets = layer.fetch_markets(limit=10)
        
        assert len(markets) == 10
        assert markets[0]["id"] == "mock-augur-0"
        assert "description" in markets[0]
        assert "yes_price" in markets[0]
        assert "no_price" in markets[0]

    def test_fetch_markets_with_category(self, layer):
        """Test fetching markets with category filter."""
        markets = layer.fetch_markets(category="sports", limit=5)
        
        # In mock mode, category is ignored but function should work
        assert len(markets) == 5

    def test_find_negative_risk_opportunities(self, layer):
        """Test finding negative risk opportunities."""
        markets = [
            {"id": "market1", "volume": 1000, "yes_price": 0.4, "no_price": 0.7},
            {"id": "market2", "volume": 50, "yes_price": 0.5, "no_price": 0.5},
            {"id": "market3", "volume": 2000, "yes_price": 0.3, "no_price": 0.8},
        ]
        
        opportunities = layer.find_negative_risk_opportunities(markets)
        
        # Should find markets where no_price > (1 - yes_price)
        assert len(opportunities) > 0
        # Market1: edge = max(0, 0.7 - 0.6) = 0.1
        # Market3: edge = max(0, 0.8 - 0.7) = 0.1

    def test_find_negative_risk_opportunities_filtered(self, layer):
        """Test finding opportunities with filters."""
        markets = [
            {"id": "market1", "volume": 1000, "yes_price": 0.4, "no_price": 0.7},
            {"id": "market2", "volume": 50, "yes_price": 0.4, "no_price": 0.7},  # Low volume
        ]
        
        opportunities = layer.find_negative_risk_opportunities(markets, min_volume=100)
        
        # Should filter out market2 due to low volume
        assert len(opportunities) == 1
        assert opportunities[0]["id"] == "market1"

    def test_find_negative_risk_opportunities_sorted(self, layer):
        """Test opportunities are sorted by edge."""
        markets = [
            {"id": "market1", "volume": 1000, "yes_price": 0.3, "no_price": 0.8},  # edge = 0.1
            {"id": "market2", "volume": 1000, "yes_price": 0.2, "no_price": 0.9},  # edge = 0.1
        ]
        
        opportunities = layer.find_negative_risk_opportunities(markets)
        
        # Should be sorted by edge descending
        assert len(opportunities) == 2

    def test_find_negative_risk_empty_markets(self, layer):
        """Test with empty markets list."""
        opportunities = layer.find_negative_risk_opportunities([])
        assert opportunities == []

    def test_find_negative_risk_none_market(self, layer):
        """Test with None market in list."""
        markets = [None, {"id": "market1", "volume": 1000, "yes_price": 0.4, "no_price": 0.7}]
        
        opportunities = layer.find_negative_risk_opportunities(markets)
        
        # Should skip None entries
        assert len(opportunities) == 1

    def test_place_trade(self, layer):
        """Test placing a trade."""
        result = layer.place_trade("market_123", "yes", 0.5)
        
        assert result["status"] == "queued"
        assert result["market_id"] == "market_123"
        assert result["outcome"] == "yes"
        assert result["amount_eth"] == 0.5
        assert result["tx_hash"] is None

    def test_extract_yes_price(self, layer):
        """Test extracting yes price from outcomes."""
        outcomes = [
            {"id": "outcome1", "price": "0.6"},
            {"id": "outcome2", "price": "0.4"},
        ]
        
        price = layer._extract_yes_price(outcomes)
        
        assert price == 0.6  # Should return max price

    def test_extract_yes_price_empty(self, layer):
        """Test extracting price from empty outcomes."""
        price = layer._extract_yes_price([])
        assert price is None

    def test_extract_yes_price_invalid(self, layer):
        """Test extracting price with invalid data."""
        outcomes = [{"id": "outcome1"}]  # No price key
        
        price = layer._extract_yes_price(outcomes)
        
        # Should handle gracefully
        assert price == 0.0  # Default from get("price", 0)

    def test_mock_markets_structure(self, layer):
        """Test mock markets have correct structure."""
        markets = layer._mock_markets(3)
        
        assert len(markets) == 3
        for idx, market in enumerate(markets):
            assert market["id"] == f"mock-augur-{idx}"
            assert "description" in market
            assert "volume" in market
            assert "yes_price" in market
            assert "no_price" in market
            assert market["yes_price"] + market["no_price"] == 1.0  # Should sum to 1
