"""Tests for trading/polymarket_adapter.py."""
import pytest
from unittest.mock import Mock, patch, MagicMock
from trading.polymarket_adapter import PolymarketAdapter, get_polymarket_adapter


class TestPolymarketAdapterInitialization:
    """Test PolymarketAdapter initialization."""

    def test_initialization(self):
        """Test adapter initialization."""
        adapter = PolymarketAdapter()
        assert adapter.base_url == "https://clob.polymarket.com"
        assert adapter.gamma_url == "https://gamma-api.polymarket.com"

    @patch('trading.polymarket_adapter.os.getenv')
    def test_api_key_from_env(self, mock_getenv):
        """Test API key loaded from environment."""
        mock_getenv.return_value = "test_api_key"
        adapter = PolymarketAdapter()
        assert adapter.api_key == "test_api_key"


class TestPolymarketAdapterFetchMarkets:
    """Test fetch_markets method."""

    def test_fetch_markets_success(self):
        """Test successful market fetch."""
        adapter = PolymarketAdapter()
        
        mock_response = Mock()
        mock_response.json.return_value = [
            {
                "condition_id": "market1",
                "question": "Will it rain?",
                "description": "Weather prediction",
                "tags": ["weather"],
                "end_date_iso": "2024-12-31",
                "volume": 1000000,
                "liquidity": 500000,
                "active": True,
                "closed": False,
                "tokens": [
                    {"outcome": "Yes", "price": 0.6, "token_id": "token1"},
                    {"outcome": "No", "price": 0.4, "token_id": "token2"}
                ]
            }
        ]
        mock_response.raise_for_status = Mock()
        
        adapter.client = Mock()
        adapter.client.get.return_value = mock_response
        
        markets = adapter.fetch_markets()
        
        assert len(markets) == 1
        assert markets[0]["market_id"] == "market1"
        assert markets[0]["question"] == "Will it rain?"
        assert len(markets[0]["outcomes"]) == 2

    def test_fetch_markets_with_category(self):
        """Test fetching markets with category filter."""
        adapter = PolymarketAdapter()
        
        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()
        
        adapter.client = Mock()
        adapter.client.get.return_value = mock_response
        
        markets = adapter.fetch_markets(category="crypto", limit=10)
        
        # Verify correct params were passed
        call_args = adapter.client.get.call_args
        assert call_args[1]["params"]["tag"] == "crypto"
        assert call_args[1]["params"]["limit"] == 10

    def test_fetch_markets_error(self):
        """Test fetch markets handles errors gracefully."""
        adapter = PolymarketAdapter()
        adapter.client = Mock()
        adapter.client.get.side_effect = Exception("Network error")
        
        markets = adapter.fetch_markets()
        
        assert markets == []


class TestPolymarketAdapterExtractOutcomes:
    """Test _extract_outcomes method."""

    def test_extract_with_tokens(self):
        """Test extracting outcomes from tokens."""
        adapter = PolymarketAdapter()
        market = {
            "tokens": [
                {"outcome": "Yes", "price": 0.7, "token_id": "t1"},
                {"outcome": "No", "price": 0.3, "token_id": "t2"}
            ]
        }
        
        outcomes = adapter._extract_outcomes(market)
        
        assert len(outcomes) == 2
        assert outcomes[0]["outcome"] == "Yes"
        assert outcomes[0]["price"] == 0.7

    def test_extract_without_tokens(self):
        """Test default outcomes when no tokens."""
        adapter = PolymarketAdapter()
        market = {}
        
        outcomes = adapter._extract_outcomes(market)
        
        assert len(outcomes) == 2
        assert outcomes[0]["outcome"] == "Yes"
        assert outcomes[1]["outcome"] == "No"


class TestPolymarketAdapterGetMarketDetails:
    """Test get_market_details method."""

    def test_get_market_details_success(self):
        """Test successful market details fetch."""
        adapter = PolymarketAdapter()
        
        mock_response = Mock()
        mock_response.json.return_value = {"market_id": "m1", "question": "Test?"}
        mock_response.raise_for_status = Mock()
        
        adapter.client = Mock()
        adapter.client.get.return_value = mock_response
        
        details = adapter.get_market_details("m1")
        
        assert details["market_id"] == "m1"

    def test_get_market_details_error(self):
        """Test error handling for market details."""
        adapter = PolymarketAdapter()
        adapter.client = Mock()
        adapter.client.get.side_effect = Exception("Network error")
        
        details = adapter.get_market_details("m1")
        
        assert details is None


class TestGetPolymarketAdapter:
    """Test get_polymarket_adapter singleton."""

    def test_singleton(self):
        """Test get_polymarket_adapter returns singleton."""
        adapter1 = get_polymarket_adapter()
        adapter2 = get_polymarket_adapter()
        assert adapter1 is adapter2
