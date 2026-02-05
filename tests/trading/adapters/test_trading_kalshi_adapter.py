"""Tests for trading/adapters/kalshi.py."""
import pytest
from unittest.mock import Mock, patch
from trading.adapters.kalshi import KalshiPredictionAdapter
from trading.adapters.base import TradeRequest, TradeSide


class TestKalshiPredictionAdapter:
    """Test KalshiPredictionAdapter class."""

    def test_initialization(self):
        """Test adapter initialization."""
        with patch('trading.adapters.kalshi.get_kalshi_client') as mock_get_client:
            mock_client = Mock()
            mock_get_client.return_value = mock_client
            
            adapter = KalshiPredictionAdapter()
            assert adapter.venue == "kalshi"
            assert adapter.supports_trading is False
            assert adapter._client is mock_client

    @patch('trading.adapters.kalshi.get_kalshi_client')
    def test_initialization_client_error(self, mock_get_client):
        """Test initialization when client fails."""
        mock_get_client.side_effect = Exception("Connection failed")
        
        adapter = KalshiPredictionAdapter()
        assert adapter.use_mock is True
        assert adapter._client is None

    @patch('trading.adapters.kalshi.fetch_kalshi_balance')
    def test_get_balances_live(self, mock_fetch_balance):
        """Test getting balances."""
        mock_fetch_balance.return_value = {
            "balance": 10000,  # In cents
            "raw": {"account_id": "acc_123"}
        }
        
        with patch('trading.adapters.kalshi.get_kalshi_client'):
            adapter = KalshiPredictionAdapter()
            balances = adapter._get_balances_live()
        
        assert len(balances) == 1
        assert balances[0].asset == "USD"
        assert balances[0].total == 100.0  # Converted from cents
        assert balances[0].available == 100.0
        assert balances[0].usd_value == 100.0
        assert balances[0].metadata == {"account_id": "acc_123"}

    @patch('trading.adapters.kalshi.fetch_kalshi_balance')
    def test_get_balances_with_none_balance(self, mock_fetch_balance):
        """Test getting balances when balance is None."""
        mock_fetch_balance.return_value = {
            "balance": None,
            "raw": {}
        }
        
        with patch('trading.adapters.kalshi.get_kalshi_client'):
            adapter = KalshiPredictionAdapter()
            balances = adapter._get_balances_live()
        
        assert len(balances) == 1
        assert balances[0].total == 0.0

    @patch('trading.adapters.kalshi.fetch_kalshi_balance')
    def test_get_balances_conversion_error(self, mock_fetch_balance):
        """Test getting balances with conversion error."""
        mock_fetch_balance.return_value = {
            "balance": "invalid",  # Will cause conversion error
            "raw": {}
        }
        
        with patch('trading.adapters.kalshi.get_kalshi_client'):
            adapter = KalshiPredictionAdapter()
            balances = adapter._get_balances_live()
        
        # Should handle error gracefully
        assert len(balances) == 1
        assert balances[0].total == 0.0

    def test_submit_order_not_implemented(self):
        """Test that submit_order raises NotImplementedError."""
        with patch('trading.adapters.kalshi.get_kalshi_client'):
            adapter = KalshiPredictionAdapter()
            
            request = TradeRequest(
                venue="kalshi",
                symbol="MARKET-XYZ",
                side=TradeSide.BUY,
                quantity=10.0
            )
            
            with pytest.raises(NotImplementedError, match="not yet implemented"):
                adapter._submit_order_live(request)
