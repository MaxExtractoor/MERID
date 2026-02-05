"""Comprehensive tests for trading/adapters/alpaca.py."""

import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch, PropertyMock

from trading.adapters.alpaca import AlpacaEquitiesAdapter
from trading.adapters.base import (
    TradeRequest,
    TradeSide,
    OrderType,
    BalanceSnapshot,
    PositionSnapshot,
    OrderResult,
    VenueHealth,
)


class TestAlpacaAdapterInitialization:
    """Test AlpacaEquitiesAdapter initialization."""

    def test_init_with_client_success(self):
        """Test initialization when client is available."""
        with patch('trading.adapters.alpaca.get_alpaca_client') as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            
            adapter = AlpacaEquitiesAdapter()
            
            assert adapter.venue == "alpaca"
            assert adapter.supports_trading is True
            assert adapter._client is mock_client
            assert adapter.use_mock is False

    def test_init_with_client_failure_uses_mock(self):
        """Test initialization falls back to mock when client unavailable."""
        with patch('trading.adapters.alpaca.get_alpaca_client') as mock_get_client:
            mock_get_client.side_effect = Exception("No credentials")
            
            adapter = AlpacaEquitiesAdapter()
            
            assert adapter._client is None
            assert adapter.use_mock is True

    def test_default_time_in_force(self):
        """Test default time in force is set."""
        with patch('trading.adapters.alpaca.get_alpaca_client'):
            adapter = AlpacaEquitiesAdapter()
            assert adapter._default_time_in_force == "day"


class TestAlpacaAdapterHealth:
    """Test AlpacaEquitiesAdapter health checks."""

    def test_get_health_mock_mode(self):
        """Test health status in mock mode."""
        with patch('trading.adapters.alpaca.get_alpaca_client'):
            adapter = AlpacaEquitiesAdapter()
            adapter.use_mock = True
            
            health = adapter.get_health()
            
            assert isinstance(health, VenueHealth)
            assert health.venue == "alpaca"
            assert health.status == "offline"
            assert health.metadata["supports_trading"] is True

    def test_get_health_live_mode(self):
        """Test health status in live mode."""
        with patch('trading.adapters.alpaca.get_alpaca_client'):
            adapter = AlpacaEquitiesAdapter()
            adapter.use_mock = False
            
            health = adapter.get_health()
            
            assert health.status == "online"

    def test_get_health_with_error(self):
        """Test health status after error."""
        with patch('trading.adapters.alpaca.get_alpaca_client'):
            adapter = AlpacaEquitiesAdapter()
            adapter._last_error = "Connection failed"
            
            health = adapter.get_health()
            
            assert health.status == "degraded"
            assert health.last_error == "Connection failed"


class TestAlpacaAdapterBalances:
    """Test AlpacaEquitiesAdapter balance operations."""

    def test_get_balances_mock_mode_returns_empty(self):
        """Test get_balances returns empty in mock mode."""
        with patch('trading.adapters.alpaca.get_alpaca_client'):
            adapter = AlpacaEquitiesAdapter()
            adapter.use_mock = True
            
            balances = adapter.get_balances()
            
            assert balances == []

    def test_get_balances_live_success(self):
        """Test get_balances in live mode."""
        with patch('trading.adapters.alpaca.get_alpaca_client'):
            with patch('trading.adapters.alpaca.fetch_account_snapshot') as mock_fetch:
                mock_fetch.return_value = {
                    "cash": "10000.50",
                    "portfolio_value": "25000.75"
                }
                
                adapter = AlpacaEquitiesAdapter()
                adapter.use_mock = False
                adapter._client = MagicMock()
                
                balances = adapter.get_balances()
                
                assert len(balances) == 1
                assert balances[0].asset == "USD"
                assert balances[0].total == 25000.75
                assert balances[0].available == 10000.50

    def test_get_balances_live_handles_string_values(self):
        """Test get_balances handles string values from API."""
        with patch('trading.adapters.alpaca.get_alpaca_client'):
            with patch('trading.adapters.alpaca.fetch_account_snapshot') as mock_fetch:
                mock_fetch.return_value = {
                    "cash": "5000.00",
                    "portfolio_value": "15000.00"
                }
                
                adapter = AlpacaEquitiesAdapter()
                adapter.use_mock = False
                adapter._client = MagicMock()
                
                balances = adapter._get_balances_live()
                
                assert balances[0].available == 5000.00
                assert balances[0].total == 15000.00

    def test_get_balances_live_missing_values_defaults_to_zero(self):
        """Test get_balances defaults to zero when values missing."""
        with patch('trading.adapters.alpaca.get_alpaca_client'):
            with patch('trading.adapters.alpaca.fetch_account_snapshot') as mock_fetch:
                mock_fetch.return_value = {}
                
                adapter = AlpacaEquitiesAdapter()
                adapter.use_mock = False
                adapter._client = MagicMock()
                
                balances = adapter._get_balances_live()
                
                assert balances[0].available == 0.0
                assert balances[0].total == 0.0


class TestAlpacaAdapterPositions:
    """Test AlpacaEquitiesAdapter position operations."""

    def test_get_positions_mock_mode_returns_empty(self):
        """Test get_positions returns empty in mock mode."""
        with patch('trading.adapters.alpaca.get_alpaca_client'):
            adapter = AlpacaEquitiesAdapter()
            adapter.use_mock = True
            
            positions = adapter.get_positions()
            
            assert positions == []

    def test_get_positions_no_client_returns_empty(self):
        """Test get_positions returns empty when no client."""
        with patch('trading.adapters.alpaca.get_alpaca_client'):
            adapter = AlpacaEquitiesAdapter()
            adapter._client = None
            
            positions = adapter._get_positions_live()
            
            assert positions == []

    def test_get_positions_live_success(self):
        """Test get_positions with successful API call."""
        with patch('trading.adapters.alpaca.get_alpaca_client'):
            adapter = AlpacaEquitiesAdapter()
            
            mock_position = MagicMock()
            mock_position.symbol = "AAPL"
            mock_position.qty = "10"
            mock_position._raw = {
                "symbol": "AAPL",
                "qty": "10",
                "avg_entry_price": "150.00",
                "current_price": "175.00",
                "unrealized_pl": "250.00"
            }
            
            adapter._client = MagicMock()
            adapter._client.list_positions.return_value = [mock_position]
            
            positions = adapter._get_positions_live()
            
            assert len(positions) == 1
            assert positions[0].symbol == "AAPL"
            assert positions[0].quantity == 10.0
            assert positions[0].entry_price == 150.0
            assert positions[0].mark_price == 175.0
            assert positions[0].unrealized_pnl == 250.0

    def test_get_positions_live_handles_errors(self):
        """Test get_positions handles API errors gracefully."""
        with patch('trading.adapters.alpaca.get_alpaca_client'):
            adapter = AlpacaEquitiesAdapter()
            adapter._client = MagicMock()
            adapter._client.list_positions.side_effect = Exception("API Error")
            
            positions = adapter._get_positions_live()
            
            assert positions == []

    def test_get_positions_skips_malformed_rows(self):
        """Test get_positions skips malformed position data."""
        with patch('trading.adapters.alpaca.get_alpaca_client'):
            adapter = AlpacaEquitiesAdapter()
            
            # One valid, one invalid
            mock_pos_valid = MagicMock()
            mock_pos_valid._raw = {"symbol": "AAPL", "qty": "10"}
            
            mock_pos_invalid = MagicMock()
            mock_pos_invalid._raw = None
            mock_pos_invalid.__dict__ = {}  # Missing required fields
            
            adapter._client = MagicMock()
            adapter._client.list_positions.return_value = [mock_pos_valid, mock_pos_invalid]
            
            positions = adapter._get_positions_live()
            
            assert len(positions) == 1


class TestAlpacaAdapterSubmitOrder:
    """Test AlpacaEquitiesAdapter order submission."""

    def test_submit_order_mock_mode_raises(self):
        """Test submit_order raises error in mock mode."""
        with patch('trading.adapters.alpaca.get_alpaca_client'):
            adapter = AlpacaEquitiesAdapter()
            adapter.use_mock = True
            
            request = TradeRequest(
                venue="alpaca",
                symbol="AAPL",
                side=TradeSide.BUY,
                quantity=10.0,
                order_type=OrderType.MARKET
            )
            
            with pytest.raises(RuntimeError) as exc_info:
                adapter.submit_order(request)
            
            assert "mock mode" in str(exc_info.value).lower()

    def test_submit_order_no_client_raises(self):
        """Test submit_order raises error when no client."""
        with patch('trading.adapters.alpaca.get_alpaca_client'):
            adapter = AlpacaEquitiesAdapter()
            adapter._client = None
            
            request = TradeRequest(
                venue="alpaca",
                symbol="AAPL",
                side=TradeSide.BUY,
                quantity=10.0
            )
            
            with pytest.raises(RuntimeError) as exc_info:
                adapter._submit_order_live(request)
            
            assert "unavailable" in str(exc_info.value).lower()

    def test_submit_market_order_success(self):
        """Test submitting market order."""
        with patch('trading.adapters.alpaca.get_alpaca_client'):
            adapter = AlpacaEquitiesAdapter()
            
            mock_order = MagicMock()
            mock_order.id = "order_123"
            mock_order._raw = {
                "id": "order_123",
                "status": "filled",
                "filled_qty": "10",
                "filled_avg_price": "150.00"
            }
            
            adapter._client = MagicMock()
            adapter._client.submit_order.return_value = mock_order
            
            request = TradeRequest(
                venue="alpaca",
                symbol="AAPL",
                side=TradeSide.BUY,
                quantity=10.0,
                order_type=OrderType.MARKET,
                client_reference="ref_123"
            )
            
            result = adapter._submit_order_live(request)
            
            assert isinstance(result, OrderResult)
            assert result.venue == "alpaca"
            assert result.symbol == "AAPL"
            assert result.side == TradeSide.BUY
            assert result.quantity == 10.0
            assert result.status == "filled"
            assert result.venue_order_id == "order_123"
            
            # Verify client called with correct payload
            call_kwargs = adapter._client.submit_order.call_args.kwargs
            assert call_kwargs["symbol"] == "AAPL"
            assert call_kwargs["qty"] == 10.0
            assert call_kwargs["side"] == "buy"
            assert call_kwargs["type"] == "market"
            assert call_kwargs["client_order_id"] == "ref_123"

    def test_submit_limit_order_success(self):
        """Test submitting limit order."""
        with patch('trading.adapters.alpaca.get_alpaca_client'):
            adapter = AlpacaEquitiesAdapter()
            
            mock_order = MagicMock()
            mock_order.id = "order_124"
            mock_order._raw = {"id": "order_124", "status": "new"}
            
            adapter._client = MagicMock()
            adapter._client.submit_order.return_value = mock_order
            
            request = TradeRequest(
                venue="alpaca",
                symbol="TSLA",
                side=TradeSide.SELL,
                quantity=5.0,
                order_type=OrderType.LIMIT,
                price=200.00
            )
            
            result = adapter._submit_order_live(request)
            
            call_kwargs = adapter._client.submit_order.call_args.kwargs
            assert call_kwargs["type"] == "limit"
            assert call_kwargs["limit_price"] == 200.00

    def test_submit_limit_order_without_price_raises(self):
        """Test submitting limit order without price raises error."""
        with patch('trading.adapters.alpaca.get_alpaca_client'):
            adapter = AlpacaEquitiesAdapter()
            adapter._client = MagicMock()
            
            request = TradeRequest(
                venue="alpaca",
                symbol="TSLA",
                side=TradeSide.BUY,
                quantity=5.0,
                order_type=OrderType.LIMIT
            )
            
            with pytest.raises(RuntimeError) as exc_info:
                adapter._submit_order_live(request)
            
            assert "price" in str(exc_info.value).lower()

    def test_submit_order_custom_time_in_force(self):
        """Test submitting order with custom TIF."""
        with patch('trading.adapters.alpaca.get_alpaca_client'):
            adapter = AlpacaEquitiesAdapter()
            
            mock_order = MagicMock()
            mock_order.id = "order_125"
            mock_order._raw = {"id": "order_125", "status": "new"}
            
            adapter._client = MagicMock()
            adapter._client.submit_order.return_value = mock_order
            
            request = TradeRequest(
                venue="alpaca",
                symbol="MSFT",
                side=TradeSide.BUY,
                quantity=100.0,
                metadata={"time_in_force": "gtc"}
            )
            
            adapter._submit_order_live(request)
            
            call_kwargs = adapter._client.submit_order.call_args.kwargs
            assert call_kwargs["time_in_force"] == "gtc"

    def test_submit_order_invalid_order_type_defaults_to_market(self):
        """Test invalid order type defaults to market."""
        with patch('trading.adapters.alpaca.get_alpaca_client'):
            adapter = AlpacaEquitiesAdapter()
            
            mock_order = MagicMock()
            mock_order.id = "order_126"
            mock_order._raw = {"id": "order_126", "status": "new"}
            
            adapter._client = MagicMock()
            adapter._client.submit_order.return_value = mock_order
            
            request = TradeRequest(
                venue="alpaca",
                symbol="GOOGL",
                side=TradeSide.BUY,
                quantity=1.0,
                order_type=OrderType.IOC  # Not directly supported
            )
            
            adapter._submit_order_live(request)
            
            call_kwargs = adapter._client.submit_order.call_args.kwargs
            assert call_kwargs["type"] == "market"


class TestAlpacaAdapterCancelOrder:
    """Test AlpacaEquitiesAdapter order cancellation."""

    def test_cancel_order_mock_mode_returns_false(self):
        """Test cancel_order returns False in mock mode."""
        with patch('trading.adapters.alpaca.get_alpaca_client'):
            adapter = AlpacaEquitiesAdapter()
            adapter.use_mock = True
            
            result = adapter.cancel_order("order_123")
            
            assert result is False

    def test_cancel_order_not_implemented(self):
        """Test cancel_order raises NotImplementedError."""
        with patch('trading.adapters.alpaca.get_alpaca_client'):
            adapter = AlpacaEquitiesAdapter()
            adapter.use_mock = False
            
            with pytest.raises(NotImplementedError):
                adapter._cancel_order_live("order_123")
