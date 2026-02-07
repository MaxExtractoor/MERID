"""Comprehensive tests for trading/adapters/kalshi.py - Coverage improvement."""

import pytest
from unittest.mock import MagicMock, patch

from trading.adapters.base import TradeRequest, TradeSide
from trading.adapters.kalshi import KalshiPredictionAdapter


@pytest.fixture
def adapter():
    """Create KalshiPredictionAdapter with mocked client."""
    with patch("trading.adapters.kalshi.get_kalshi_client") as mock_get:
        mock_client = MagicMock()
        mock_get.return_value = mock_client
        adapter = KalshiPredictionAdapter()
        adapter._client = mock_client
        return adapter


@pytest.fixture
def mock_adapter():
    """Create KalshiPredictionAdapter in mock mode (no client)."""
    with patch("trading.adapters.kalshi.get_kalshi_client") as mock_get:
        mock_get.side_effect = Exception("No credentials")
        adapter = KalshiPredictionAdapter()
        return adapter


# =============================================================================
# Initialization Tests
# =============================================================================

class TestKalshiPredictionAdapterInit:
    """Test KalshiPredictionAdapter initialization."""

    def test_init_with_client(self):
        with patch("trading.adapters.kalshi.get_kalshi_client") as mock_get:
            mock_client = MagicMock()
            mock_get.return_value = mock_client
            
            adapter = KalshiPredictionAdapter()
        
        assert adapter.venue == "kalshi"
        assert adapter.supports_trading is False
        assert adapter._client is not None

    def test_init_without_client(self):
        with patch("trading.adapters.kalshi.get_kalshi_client") as mock_get:
            mock_get.side_effect = Exception("No API key")
            
            adapter = KalshiPredictionAdapter()
        
        assert adapter._client is None
        assert adapter.use_mock is True


# =============================================================================
# Get Balances Tests
# =============================================================================

class TestGetBalancesLive:
    """Test _get_balances_live method."""

    def test_get_balances_success(self, adapter):
        with patch("trading.adapters.kalshi.fetch_kalshi_balance") as mock_fetch:
            mock_fetch.return_value = {
                "balance": 10000,  # In cents
                "raw": {"account_id": "123"}
            }
            
            balances = adapter._get_balances_live()
        
        assert len(balances) == 1
        assert balances[0].asset == "USD"
        assert balances[0].total == 100.0  # Converted from cents
        assert balances[0].available == 100.0

    def test_get_balances_zero_balance(self, adapter):
        with patch("trading.adapters.kalshi.fetch_kalshi_balance") as mock_fetch:
            mock_fetch.return_value = {"balance": 0}
            
            balances = adapter._get_balances_live()
        
        assert len(balances) == 1
        assert balances[0].total == 0.0

    def test_get_balances_no_balance_key(self, adapter):
        with patch("trading.adapters.kalshi.fetch_kalshi_balance") as mock_fetch:
            mock_fetch.return_value = {}
            
            balances = adapter._get_balances_live()
        
        assert len(balances) == 1
        assert balances[0].total == 0.0

    def test_get_balances_no_raw_key(self, adapter):
        with patch("trading.adapters.kalshi.fetch_kalshi_balance") as mock_fetch:
            mock_fetch.return_value = {"balance": 5000}
            
            balances = adapter._get_balances_live()
        
        assert len(balances) == 1
        assert balances[0].metadata == {}


# =============================================================================
# Submit Order Tests
# =============================================================================

class TestSubmitOrderLive:
    """Test _submit_order_live method."""

    def test_submit_order_not_implemented(self, adapter):
        """Test order submission raises NotImplementedError."""
        request = TradeRequest(
            venue="kalshi",
            symbol="INXD-23DEC31-B4200",
            side=TradeSide.BUY,
            quantity=10.0
        )
        
        with pytest.raises(NotImplementedError, match="not yet implemented"):
            adapter._submit_order_live(request)


# =============================================================================
# Class Attributes Tests
# =============================================================================

class TestClassAttributes:
    """Test class-level attributes."""

    def test_venue_name(self):
        assert KalshiPredictionAdapter.venue == "kalshi"

    def test_supports_trading_false(self):
        assert KalshiPredictionAdapter.supports_trading is False
