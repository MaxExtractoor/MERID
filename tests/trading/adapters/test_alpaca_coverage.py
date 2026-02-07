"""Comprehensive tests for trading/adapters/alpaca.py - Coverage improvement."""

import pytest
from unittest.mock import MagicMock, patch

from trading.adapters.base import (
    BalanceSnapshot, OrderResult, PositionSnapshot,
    TradeRequest, TradeSide, OrderType
)
from trading.adapters.alpaca import AlpacaEquitiesAdapter


@pytest.fixture
def adapter():
    """Create AlpacaEquitiesAdapter with mocked client."""
    with patch("trading.adapters.alpaca.get_alpaca_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        adapter = AlpacaEquitiesAdapter()
        adapter._client = mock_client
        return adapter


@pytest.fixture
def mock_adapter():
    """Create AlpacaEquitiesAdapter in mock mode (no client)."""
    with patch("trading.adapters.alpaca.get_alpaca_client") as mock_get_client:
        mock_get_client.side_effect = Exception("No credentials")
        adapter = AlpacaEquitiesAdapter()
        return adapter


# =============================================================================
# Initialization Tests
# =============================================================================

class TestAlpacaEquitiesAdapterInit:
    """Test AlpacaEquitiesAdapter initialization."""

    def test_init_with_client(self):
        with patch("trading.adapters.alpaca.get_alpaca_client") as mock_get:
            mock_client = MagicMock()
            mock_get.return_value = mock_client
            
            adapter = AlpacaEquitiesAdapter()
        
        assert adapter.venue == "alpaca"
        assert adapter.supports_trading is True
        assert adapter._client is not None

    def test_init_without_client(self):
        with patch("trading.adapters.alpaca.get_alpaca_client") as mock_get:
            mock_get.side_effect = Exception("No API key")
            
            adapter = AlpacaEquitiesAdapter()
        
        assert adapter._client is None
        assert adapter.use_mock is True


# =============================================================================
# Get Balances Tests
# =============================================================================

class TestGetBalancesLive:
    """Test _get_balances_live method."""

    def test_get_balances_success(self, adapter):
        with patch("trading.adapters.alpaca.fetch_account_snapshot") as mock_fetch:
            mock_fetch.return_value = {
                "cash": "10000.50",
                "portfolio_value": "25000.75"
            }
            
            balances = adapter._get_balances_live()
        
        assert len(balances) == 1
        assert balances[0].asset == "USD"
        assert balances[0].available == 10000.50
        assert balances[0].total == 25000.75

    def test_get_balances_missing_values(self, adapter):
        with patch("trading.adapters.alpaca.fetch_account_snapshot") as mock_fetch:
            mock_fetch.return_value = {}
            
            balances = adapter._get_balances_live()
        
        assert len(balances) == 1
        assert balances[0].available == 0.0


# =============================================================================
# Get Positions Tests
# =============================================================================

class TestGetPositionsLive:
    """Test _get_positions_live method."""

    def test_get_positions_no_client(self, mock_adapter):
        """Test positions with no client returns empty list."""
        positions = mock_adapter._get_positions_live()
        assert positions == []

    def test_get_positions_success(self, adapter):
        """Test successful position fetch."""
        mock_position = MagicMock()
        mock_position._raw = {
            "symbol": "AAPL",
            "qty": "100",
            "avg_entry_price": "150.00",
            "current_price": "155.00",
            "unrealized_pl": "500.00"
        }
        mock_position.symbol = "AAPL"
        mock_position.qty = "100"
        
        adapter._client.list_positions.return_value = [mock_position]
        
        positions = adapter._get_positions_live()
        
        assert len(positions) == 1
        assert positions[0].symbol == "AAPL"
        assert positions[0].quantity == 100.0
        assert positions[0].entry_price == 150.0

    def test_get_positions_with_dict_fallback(self, adapter):
        """Test position with __dict__ fallback when _raw is None."""
        class MockPosition:
            _raw = None
            symbol = "MSFT"
            qty = "50"
            
            def __init__(self):
                self.__dict__.update({
                    "symbol": "MSFT",
                    "qty": "50",
                    "avg_entry_price": "300.00",
                    "market_price": "310.00",
                    "unrealized_pl": "500.00"
                })
        
        mock_position = MockPosition()
        adapter._client.list_positions.return_value = [mock_position]
        
        positions = adapter._get_positions_live()
        
        assert len(positions) == 1


# =============================================================================
# Submit Order Tests
# =============================================================================

class TestSubmitOrderLive:
    """Test _submit_order_live method."""

    def test_submit_order_no_client(self, mock_adapter):
        """Test order submission with no client raises error."""
        request = TradeRequest(
            venue="alpaca",
            symbol="AAPL",
            side=TradeSide.BUY,
            quantity=10.0
        )
        
        with pytest.raises(RuntimeError, match="verify API credentials"):
            mock_adapter._submit_order_live(request)

    def test_submit_market_order_success(self, adapter):
        """Test successful market order submission."""
        mock_order = MagicMock()
        mock_order._raw = {
            "id": "order_123",
            "status": "filled",
            "filled_avg_price": "155.50",
            "filled_qty": "10"
        }
        mock_order.id = "order_123"
        adapter._client.submit_order.return_value = mock_order
        
        request = TradeRequest(
            venue="alpaca",
            symbol="AAPL",
            side=TradeSide.BUY,
            quantity=10.0
        )
        
        result = adapter._submit_order_live(request)
        
        assert result.venue == "alpaca"
        assert result.symbol == "AAPL"
        assert result.side == TradeSide.BUY
        assert result.status == "filled"

    def test_submit_sell_order(self, adapter):
        """Test sell order submission."""
        mock_order = MagicMock()
        mock_order._raw = {"id": "order_456", "status": "submitted"}
        mock_order.id = "order_456"
        adapter._client.submit_order.return_value = mock_order
        
        request = TradeRequest(
            venue="alpaca",
            symbol="TSLA",
            side=TradeSide.SELL,
            quantity=5.0
        )
        
        result = adapter._submit_order_live(request)
        
        assert result.side == TradeSide.SELL

    def test_submit_limit_order_success(self, adapter):
        """Test successful limit order submission."""
        mock_order = MagicMock()
        mock_order._raw = {"id": "order_789", "status": "accepted"}
        mock_order.id = "order_789"
        adapter._client.submit_order.return_value = mock_order
        
        request = TradeRequest(
            venue="alpaca",
            symbol="AAPL",
            side=TradeSide.BUY,
            quantity=10.0,
            order_type=OrderType.LIMIT,
            price=150.0
        )
        
        result = adapter._submit_order_live(request)
        
        # Verify limit_price was included in payload
        call_args = adapter._client.submit_order.call_args
        assert call_args.kwargs["limit_price"] == 150.0

    def test_submit_limit_order_no_price_raises(self, adapter):
        """Test limit order without price raises error."""
        request = TradeRequest(
            venue="alpaca",
            symbol="AAPL",
            side=TradeSide.BUY,
            quantity=10.0,
            order_type=OrderType.LIMIT,
            price=None
        )
        
        with pytest.raises(RuntimeError, match="Limit orders require price"):
            adapter._submit_order_live(request)

    def test_submit_order_with_custom_tif(self, adapter):
        """Test order with custom time in force."""
        mock_order = MagicMock()
        mock_order._raw = {"id": "order_tif", "status": "submitted"}
        mock_order.id = "order_tif"
        adapter._client.submit_order.return_value = mock_order
        
        request = TradeRequest(
            venue="alpaca",
            symbol="AAPL",
            side=TradeSide.BUY,
            quantity=10.0,
            metadata={"time_in_force": "gtc"}
        )
        
        result = adapter._submit_order_live(request)
        
        call_args = adapter._client.submit_order.call_args
        assert call_args.kwargs["time_in_force"] == "gtc"

    def test_submit_order_with_client_reference(self, adapter):
        """Test order with client reference."""
        mock_order = MagicMock()
        mock_order._raw = {"id": "order_ref", "status": "submitted"}
        mock_order.id = "order_ref"
        adapter._client.submit_order.return_value = mock_order
        
        request = TradeRequest(
            venue="alpaca",
            symbol="AAPL",
            side=TradeSide.BUY,
            quantity=10.0,
            client_reference="my_order_123"
        )
        
        result = adapter._submit_order_live(request)
        
        call_args = adapter._client.submit_order.call_args
        assert call_args.kwargs["client_order_id"] == "my_order_123"

    def test_submit_order_ioc_falls_to_market(self, adapter):
        """Test IOC order type falls back to market."""
        mock_order = MagicMock()
        mock_order._raw = {"id": "order_ioc", "status": "submitted"}
        mock_order.id = "order_ioc"
        adapter._client.submit_order.return_value = mock_order
        
        request = TradeRequest(
            venue="alpaca",
            symbol="AAPL",
            side=TradeSide.BUY,
            quantity=10.0,
            order_type=OrderType.IOC
        )
        
        result = adapter._submit_order_live(request)
        
        call_args = adapter._client.submit_order.call_args
        assert call_args.kwargs["type"] == "market"


# =============================================================================
# Class Attributes Tests
# =============================================================================

class TestClassAttributes:
    """Test class-level attributes."""

    def test_venue_name(self):
        assert AlpacaEquitiesAdapter.venue == "alpaca"

    def test_supports_trading(self):
        assert AlpacaEquitiesAdapter.supports_trading is True
