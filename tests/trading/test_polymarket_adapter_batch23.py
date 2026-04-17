"""Tests for Polymarket adapter - Batch 23 Coverage."""
import pytest
from unittest.mock import MagicMock, patch, Mock
import os

from trading.polymarket_adapter import PolymarketAdapter, get_polymarket_adapter


class TestPolymarketAdapter:
    """Tests for PolymarketAdapter."""

    @pytest.fixture
    def adapter(self):
        """Create adapter with mocked HTTP client."""
        with patch.dict(os.environ, {"POLYMARKET_API_KEY": "test_key"}):
            with patch('httpx.Client') as mock_client:
                mock_client.return_value = MagicMock()
                return PolymarketAdapter()

    def test_initialization(self, adapter):
        """Test adapter initialization."""
        assert adapter.api_key == "test_key"
        assert adapter.base_url == "https://clob.polymarket.com"
        assert adapter.gamma_url == "https://gamma-api.polymarket.com"

    @patch.dict(os.environ, {}, clear=True)
    def test_initialization_no_api_key(self):
        """Test adapter initialization without API key."""
        with patch('httpx.Client'):
            adapter = PolymarketAdapter()
            assert adapter.api_key is None

    def test_fetch_markets_success(self, adapter):
        """Test fetching markets successfully."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "condition_id": "market_123",
                "question": "Will BTC hit 100k?",
                "description": "Bitcoin price prediction",
                "tags": ["crypto"],
                "end_date_iso": "2024-12-31",
                "volume": 1000000,
                "liquidity": 500000,
                "tokens": [
                    {"outcome": "Yes", "price": 0.6, "token_id": "token_yes"},
                    {"outcome": "No", "price": 0.4, "token_id": "token_no"}
                ],
                "active": True,
                "closed": False
            }
        ]
        mock_response.raise_for_status = Mock()
        adapter.client.get.return_value = mock_response

        markets = adapter.fetch_markets(limit=10)

        assert len(markets) == 1
        assert markets[0]["market_id"] == "market_123"
        assert markets[0]["question"] == "Will BTC hit 100k?"
        assert len(markets[0]["outcomes"]) == 2

    def test_fetch_markets_with_category(self, adapter):
        """Test fetching markets with category filter."""
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()
        adapter.client.get.return_value = mock_response

        markets = adapter.fetch_markets(category="crypto", limit=20)

        # Verify correct parameters were passed
        adapter.client.get.assert_called_once()
        call_args = adapter.client.get.call_args
        assert call_args[1]["params"]["tag"] == "crypto"
        assert call_args[1]["params"]["limit"] == 20

    def test_fetch_markets_failure(self, adapter):
        """Test fetching markets with API failure."""
        adapter.client.get.side_effect = Exception("Network error")

        markets = adapter.fetch_markets()

        assert markets == []

    def test_fetch_markets_empty_response(self, adapter):
        """Test fetching markets with empty response."""
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()
        adapter.client.get.return_value = mock_response

        markets = adapter.fetch_markets()

        assert markets == []

    def test_extract_outcomes_with_tokens(self, adapter):
        """Test extracting outcomes from market with tokens."""
        market = {
            "tokens": [
                {"outcome": "Yes", "price": 0.7, "token_id": "yes_token"},
                {"outcome": "No", "price": 0.3, "token_id": "no_token"}
            ]
        }

        outcomes = adapter._extract_outcomes(market)

        assert len(outcomes) == 2
        assert outcomes[0]["outcome"] == "Yes"
        assert outcomes[0]["price"] == 0.7

    def test_extract_outcomes_no_tokens(self, adapter):
        """Test extracting outcomes when no tokens present."""
        market = {}

        outcomes = adapter._extract_outcomes(market)

        assert len(outcomes) == 2
        assert outcomes[0]["outcome"] == "Yes"
        assert outcomes[1]["outcome"] == "No"
        assert outcomes[0]["price"] == 0.5

    def test_get_market_details_success(self, adapter):
        """Test getting market details successfully."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "condition_id": "market_123",
            "question": "Test question",
            "description": "Test description"
        }
        mock_response.raise_for_status = Mock()
        adapter.client.get.return_value = mock_response

        details = adapter.get_market_details("market_123")

        assert details is not None
        assert details["condition_id"] == "market_123"

    def test_get_market_details_failure(self, adapter):
        """Test getting market details with failure."""
        adapter.client.get.side_effect = Exception("Network error")

        details = adapter.get_market_details("market_123")

        assert details is None

    def test_get_market_details_404(self, adapter):
        """Test getting market details for non-existent market."""
        from httpx import HTTPStatusError
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = HTTPStatusError(
            "Not found", request=MagicMock(), response=MagicMock()
        )
        adapter.client.get.return_value = mock_response

        details = adapter.get_market_details("nonexistent")

        assert details is None


class TestGetPolymarketAdapter:
    """Tests for get_polymarket_adapter singleton."""

    @patch('httpx.Client')
    @patch.dict(os.environ, {"POLYMARKET_API_KEY": "test_key"})
    def test_singleton(self, mock_client):
        """Test singleton pattern."""
        # Reset singleton for test
        import trading.polymarket_adapter as pm_module
        pm_module._polymarket_adapter = None

        adapter1 = get_polymarket_adapter()
        adapter2 = get_polymarket_adapter()

        assert adapter1 is adapter2

    @patch('httpx.Client')
    @patch.dict(os.environ, {"POLYMARKET_API_KEY": "test_key"})
    def test_singleton_returns_existing(self, mock_client):
        """Test singleton returns existing instance."""
        # Create first instance
        adapter1 = get_polymarket_adapter()
        # Should return same instance
        adapter2 = get_polymarket_adapter()

        assert adapter1 is adapter2
