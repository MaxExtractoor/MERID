"""Comprehensive tests for trading/polymarket_adapter.py - Coverage improvement."""

import pytest
from unittest.mock import MagicMock, patch
import httpx

from trading.polymarket_adapter import (
    PolymarketAdapter, get_polymarket_adapter
)


@pytest.fixture
def adapter():
    """Create PolymarketAdapter with mocked HTTP client."""
    with patch.object(httpx, 'Client') as mock_client:
        adapter = PolymarketAdapter()
        adapter.client = MagicMock()
        return adapter


# =============================================================================
# Initialization Tests
# =============================================================================

class TestPolymarketAdapterInit:
    """Test PolymarketAdapter initialization."""

    def test_init_defaults(self, monkeypatch):
        monkeypatch.delenv("POLYMARKET_API_KEY", raising=False)
        
        with patch.object(httpx, 'Client'):
            adapter = PolymarketAdapter()
        
        assert adapter.base_url == "https://clob.polymarket.com"
        assert adapter.gamma_url == "https://gamma-api.polymarket.com"

    def test_init_with_api_key(self, monkeypatch):
        monkeypatch.setenv("POLYMARKET_API_KEY", "test_api_key")
        
        with patch.object(httpx, 'Client'):
            adapter = PolymarketAdapter()
        
        assert adapter.api_key == "test_api_key"


# =============================================================================
# Fetch Markets Tests
# =============================================================================

class TestFetchMarkets:
    """Test fetch_markets method."""

    def test_fetch_markets_success(self, adapter):
        """Test successful market fetch."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "condition_id": "market_1",
                "question": "Will BTC hit 100k?",
                "description": "Test market",
                "tags": ["crypto"],
                "end_date_iso": "2024-12-31",
                "volume": 1000000,
                "liquidity": 50000,
                "tokens": [
                    {"outcome": "Yes", "price": 0.65, "token_id": "token_1"},
                    {"outcome": "No", "price": 0.35, "token_id": "token_2"}
                ],
                "active": True,
                "closed": False
            }
        ]
        adapter.client.get.return_value = mock_response
        
        markets = adapter.fetch_markets()
        
        assert len(markets) == 1
        assert markets[0]["market_id"] == "market_1"
        assert markets[0]["question"] == "Will BTC hit 100k?"
        assert len(markets[0]["outcomes"]) == 2

    def test_fetch_markets_with_category(self, adapter):
        """Test market fetch with category filter."""
        mock_response = MagicMock()
        mock_response.json.return_value = []
        adapter.client.get.return_value = mock_response
        
        markets = adapter.fetch_markets(category="politics", limit=25)
        
        adapter.client.get.assert_called_once()
        call_args = adapter.client.get.call_args
        assert call_args.kwargs["params"]["tag"] == "politics"
        assert call_args.kwargs["params"]["limit"] == 25

    def test_fetch_markets_error_handling(self, adapter):
        """Test market fetch error handling."""
        adapter.client.get.side_effect = Exception("Network error")
        
        markets = adapter.fetch_markets()
        
        assert markets == []

    def test_fetch_markets_http_error(self, adapter):
        """Test market fetch with HTTP error."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500 Server Error", request=MagicMock(), response=MagicMock()
        )
        adapter.client.get.return_value = mock_response
        
        markets = adapter.fetch_markets()
        
        assert markets == []

    def test_fetch_markets_market_with_id_fallback(self, adapter):
        """Test market with 'id' instead of 'condition_id'."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "id": "market_alt",
                "question": "Test question",
                "tokens": []
            }
        ]
        adapter.client.get.return_value = mock_response
        
        markets = adapter.fetch_markets()
        
        assert markets[0]["market_id"] == "market_alt"

    def test_fetch_markets_empty_tags(self, adapter):
        """Test market with empty tags."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "condition_id": "market_1",
                "question": "Test",
                "tags": [],
                "tokens": []
            }
        ]
        adapter.client.get.return_value = mock_response
        
        markets = adapter.fetch_markets()
        
        assert markets[0]["category"] == ""

    def test_fetch_markets_no_tags(self, adapter):
        """Test market with no tags field."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "condition_id": "market_1",
                "question": "Test",
                "tokens": []
            }
        ]
        adapter.client.get.return_value = mock_response
        
        markets = adapter.fetch_markets()
        
        assert markets[0]["category"] == ""


# =============================================================================
# Extract Outcomes Tests
# =============================================================================

class TestExtractOutcomes:
    """Test _extract_outcomes method."""

    def test_extract_outcomes_with_tokens(self, adapter):
        """Test outcome extraction with tokens."""
        market = {
            "tokens": [
                {"outcome": "Yes", "price": 0.75, "token_id": "token_yes"},
                {"outcome": "No", "price": 0.25, "token_id": "token_no"}
            ]
        }
        
        outcomes = adapter._extract_outcomes(market)
        
        assert len(outcomes) == 2
        assert outcomes[0]["outcome"] == "Yes"
        assert outcomes[0]["price"] == 0.75

    def test_extract_outcomes_no_tokens(self, adapter):
        """Test outcome extraction with no tokens (default binary)."""
        market = {"tokens": []}
        
        outcomes = adapter._extract_outcomes(market)
        
        assert len(outcomes) == 2
        assert outcomes[0]["outcome"] == "Yes"
        assert outcomes[1]["outcome"] == "No"

    def test_extract_outcomes_missing_tokens_key(self, adapter):
        """Test outcome extraction with missing tokens key."""
        market = {}
        
        outcomes = adapter._extract_outcomes(market)
        
        assert len(outcomes) == 2  # Default binary outcomes


# =============================================================================
# Get Market Details Tests
# =============================================================================

class TestGetMarketDetails:
    """Test get_market_details method."""

    def test_get_market_details_success(self, adapter):
        """Test successful market details fetch."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "condition_id": "market_1",
            "question": "Test market",
            "volume": 500000
        }
        adapter.client.get.return_value = mock_response
        
        details = adapter.get_market_details("market_1")
        
        assert details is not None
        assert details["condition_id"] == "market_1"

    def test_get_market_details_not_found(self, adapter):
        """Test market details for non-existent market."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404 Not Found", request=MagicMock(), response=MagicMock()
        )
        adapter.client.get.return_value = mock_response
        
        details = adapter.get_market_details("invalid_market")
        
        assert details is None

    def test_get_market_details_error(self, adapter):
        """Test market details with error."""
        adapter.client.get.side_effect = Exception("Connection error")
        
        details = adapter.get_market_details("market_1")
        
        assert details is None


# =============================================================================
# Cleanup Tests
# =============================================================================

class TestCleanup:
    """Test cleanup functionality."""

    def test_del_closes_client(self):
        """Test __del__ closes the HTTP client."""
        with patch.object(httpx, 'Client') as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            
            adapter = PolymarketAdapter()
            adapter.__del__()
            
            mock_client.close.assert_called_once()

    def test_del_handles_exception(self):
        """Test __del__ handles exceptions gracefully."""
        with patch.object(httpx, 'Client') as mock_client_class:
            mock_client = MagicMock()
            mock_client.close.side_effect = Exception("Already closed")
            mock_client_class.return_value = mock_client
            
            adapter = PolymarketAdapter()
            # Should not raise
            adapter.__del__()


# =============================================================================
# Singleton Tests
# =============================================================================

class TestGetPolymarketAdapter:
    """Test get_polymarket_adapter singleton."""

    def test_returns_same_instance(self):
        import trading.polymarket_adapter as module
        module._polymarket_adapter = None
        
        with patch.object(httpx, 'Client'):
            adapter1 = get_polymarket_adapter()
            adapter2 = get_polymarket_adapter()
        
        assert adapter1 is adapter2

    def test_creates_instance(self):
        import trading.polymarket_adapter as module
        module._polymarket_adapter = None
        
        with patch.object(httpx, 'Client'):
            adapter = get_polymarket_adapter()
        
        assert isinstance(adapter, PolymarketAdapter)
