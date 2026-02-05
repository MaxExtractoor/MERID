"""Tests for trading augur_trading_layer module - Batch 41 Coverage."""
import pytest
from unittest.mock import MagicMock, patch
import os

from trading.augur_trading_layer import AugurTradingLayer


class TestAugurTradingLayer:
    """Tests for AugurTradingLayer class."""

    @pytest.fixture
    def layer(self):
        return AugurTradingLayer()

    @pytest.fixture
    def mock_layer(self):
        return AugurTradingLayer(use_mock=True)

    def test_initialization(self, layer):
        assert layer.SUBGRAPH_URL == "https://api.thegraph.com/subgraphs/name/augurproject/augur-v2"
        assert layer.use_mock is False

    def test_initialization_mock(self, mock_layer):
        assert mock_layer.use_mock is True

    def test_initialization_env_mock(self):
        with patch.dict(os.environ, {"MERID_AUGUR_MOCK": "1"}):
            layer = AugurTradingLayer()
            assert layer.use_mock is True

    def test_fetch_markets_mock(self, mock_layer):
        markets = mock_layer.fetch_markets(limit=5)
        assert len(markets) == 5
        assert markets[0]["id"] == "mock-augur-0"
        assert "description" in markets[0]
        assert "volume" in markets[0]
        assert "yes_price" in markets[0]
        assert "no_price" in markets[0]

    def test_fetch_markets_mock_with_category(self, mock_layer):
        markets = mock_layer.fetch_markets(category="sports", limit=3)
        assert len(markets) == 3

    def test_find_negative_risk_opportunities_empty(self, mock_layer):
        opportunities = mock_layer.find_negative_risk_opportunities([])
        assert opportunities == []

    def test_find_negative_risk_opportunities_no_match(self, mock_layer):
        markets = [
            {"id": "1", "volume": 50.0, "yes_price": 0.5, "no_price": 0.5},  # Below min_volume
        ]
        opportunities = mock_layer.find_negative_risk_opportunities(markets, min_volume=100.0)
        assert opportunities == []

    def test_find_negative_risk_opportunities_with_match(self, mock_layer):
        markets = [
            {"id": "1", "description": "Test Market", "volume": 500.0, "yes_price": 0.3, "no_price": 0.8},
        ]
        opportunities = mock_layer.find_negative_risk_opportunities(markets, min_volume=100.0, yes_prob_threshold=0.05)
        assert len(opportunities) == 1
        assert opportunities[0]["id"] == "1"
        assert opportunities[0]["platform"] == "augur"
        assert "edge" in opportunities[0]

    def test_find_negative_risk_opportunities_sorted(self, mock_layer):
        markets = [
            {"id": "1", "description": "Market 1", "volume": 500.0, "yes_price": 0.3, "no_price": 0.8},
            {"id": "2", "description": "Market 2", "volume": 500.0, "yes_price": 0.2, "no_price": 0.9},
        ]
        opportunities = mock_layer.find_negative_risk_opportunities(markets)
        # Should be sorted by edge descending
        assert opportunities[0]["edge"] >= opportunities[1]["edge"]

    def test_find_negative_risk_opportunities_none_market(self, mock_layer):
        markets = [None, {"id": "1", "description": "Test", "volume": 500.0, "yes_price": 0.3, "no_price": 0.8}]
        opportunities = mock_layer.find_negative_risk_opportunities(markets)
        assert len(opportunities) == 1

    def test_place_trade(self, mock_layer):
        result = mock_layer.place_trade("market_123", "yes", 1.5)
        assert result["status"] == "queued"
        assert result["market_id"] == "market_123"
        assert result["outcome"] == "yes"
        assert result["amount_eth"] == 1.5
        assert result["tx_hash"] is None

    def test_extract_yes_price_empty(self, mock_layer):
        result = mock_layer._extract_yes_price([])
        assert result is None

    def test_extract_yes_price_with_outcomes(self, mock_layer):
        outcomes = [
            {"price": 0.3},
            {"price": 0.7},
        ]
        result = mock_layer._extract_yes_price(outcomes)
        assert result == 0.7  # Max price

    def test_extract_yes_price_exception(self, mock_layer):
        outcomes = [{"invalid": "data"}]
        result = mock_layer._extract_yes_price(outcomes)
        # Returns 0.0 when price key is missing (float(None) fallback)
        assert result == 0.0

    def test_mock_markets_structure(self, mock_layer):
        markets = mock_layer._mock_markets(3)
        assert len(markets) == 3
        for idx, market in enumerate(markets):
            assert market["id"] == f"mock-augur-{idx}"
            assert "description" in market
            assert "volume" in market
            assert "yes_price" in market
            assert "no_price" in market

    def test_fetch_markets_network_error(self, layer):
        """Test that fetch_markets falls back to mock on network error."""
        with patch.object(layer._client, 'post', side_effect=Exception("Network error")):
            markets = layer.fetch_markets(limit=3)
            # Should return mock markets on error
            assert len(markets) == 3
            assert markets[0]["id"] == "mock-augur-0"

    def test_fetch_markets_response_error(self, layer):
        """Test that fetch_markets falls back to mock on response error."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("HTTP error")
        with patch.object(layer._client, 'post', return_value=mock_response):
            markets = layer.fetch_markets(limit=3)
            # Should return mock markets on error
            assert len(markets) == 3
            assert markets[0]["id"] == "mock-augur-0"
