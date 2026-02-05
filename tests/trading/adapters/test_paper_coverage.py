"""Comprehensive tests for trading/adapters/paper.py - Coverage improvement."""

import pytest
from unittest.mock import MagicMock, patch
from enum import Enum

from trading.adapters.base import TradeRequest, TradeSide, OrderType
from trading.adapters.paper import PaperTradingAdapter


class MockOrderStatus(Enum):
    FILLED = "filled"
    PENDING = "pending"


@pytest.fixture
def adapter():
    """Create PaperTradingAdapter with mocked engine."""
    with patch("trading.adapters.paper.get_paper_engine") as mock_get:
        mock_engine = MagicMock()
        mock_get.return_value = mock_engine
        adapter = PaperTradingAdapter()
        adapter._engine = mock_engine
        return adapter


# =============================================================================
# Initialization Tests
# =============================================================================

class TestPaperTradingAdapterInit:
    """Test PaperTradingAdapter initialization."""

    def test_init_creates_engine(self):
        with patch("trading.adapters.paper.get_paper_engine") as mock_get:
            mock_engine = MagicMock()
            mock_get.return_value = mock_engine
            
            adapter = PaperTradingAdapter()
        
        assert adapter.venue == "paper"
        assert adapter.supports_trading is True
        assert adapter._engine is not None


# =============================================================================
# Submit Order Tests
# =============================================================================

class TestSubmitOrderLive:
    """Test _submit_order_live method."""

    def test_submit_buy_order(self, adapter):
        """Test buy order submission."""
        mock_order = MagicMock()
        mock_order.fill_price = 50000.0
        mock_order.filled_size = 100.0
        mock_order.status = MockOrderStatus.FILLED
        adapter._engine.place_order.return_value = mock_order
        
        request = TradeRequest(
            venue="paper",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=0.002,
            price=50000.0
        )
        
        result = adapter._submit_order_live(request)
        
        assert result.venue == "paper"
        assert result.symbol == "BTC/USD"
        assert result.side == TradeSide.BUY
        assert result.status == "executed"
        assert result.executed_price == 50000.0

    def test_submit_sell_order(self, adapter):
        """Test sell order submission (short side)."""
        mock_order = MagicMock()
        mock_order.fill_price = 3000.0
        mock_order.filled_size = 50.0
        mock_order.status = MockOrderStatus.FILLED
        adapter._engine.place_order.return_value = mock_order
        
        request = TradeRequest(
            venue="paper",
            symbol="ETH/USD",
            side=TradeSide.SELL,
            quantity=1.0,
            price=3000.0
        )
        
        result = adapter._submit_order_live(request)
        
        # Verify side was converted to "short"
        call_args = adapter._engine.place_order.call_args
        assert call_args.kwargs["side"] == "short"

    def test_submit_order_with_trader_id(self, adapter):
        """Test order with custom trader_id."""
        mock_order = MagicMock()
        mock_order.fill_price = 100.0
        mock_order.filled_size = 10.0
        mock_order.status = MockOrderStatus.FILLED
        adapter._engine.place_order.return_value = mock_order
        
        request = TradeRequest(
            venue="paper",
            symbol="SOL/USD",
            side=TradeSide.BUY,
            quantity=10.0,
            price=100.0,
            metadata={"trader_id": "custom_trader"}
        )
        
        result = adapter._submit_order_live(request)
        
        call_args = adapter._engine.place_order.call_args
        assert call_args.kwargs["user_id"] == "custom_trader"

    def test_submit_order_with_notional(self, adapter):
        """Test order with notional_usd in metadata."""
        mock_order = MagicMock()
        mock_order.fill_price = 150.0
        mock_order.filled_size = 1500.0
        mock_order.status = MockOrderStatus.FILLED
        adapter._engine.place_order.return_value = mock_order
        
        request = TradeRequest(
            venue="paper",
            symbol="AAPL",
            side=TradeSide.BUY,
            quantity=10.0,
            price=150.0,
            metadata={"notional_usd": 1500.0}
        )
        
        result = adapter._submit_order_live(request)
        
        call_args = adapter._engine.place_order.call_args
        assert call_args.kwargs["size_usd"] == 1500.0

    def test_submit_order_with_leverage(self, adapter):
        """Test order with leverage."""
        mock_order = MagicMock()
        mock_order.fill_price = 50000.0
        mock_order.filled_size = 500.0
        mock_order.status = MockOrderStatus.FILLED
        adapter._engine.place_order.return_value = mock_order
        
        request = TradeRequest(
            venue="paper",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=0.01,
            price=50000.0,
            metadata={"leverage": 5}
        )
        
        result = adapter._submit_order_live(request)
        
        call_args = adapter._engine.place_order.call_args
        assert call_args.kwargs["leverage"] == 5

    def test_submit_order_pending_status(self, adapter):
        """Test order with pending status."""
        mock_order = MagicMock()
        mock_order.fill_price = 0.0
        mock_order.filled_size = 0.0
        mock_order.status = MockOrderStatus.PENDING
        adapter._engine.place_order.return_value = mock_order
        
        request = TradeRequest(
            venue="paper",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=0.1,
            price=50000.0
        )
        
        result = adapter._submit_order_live(request)
        
        assert result.status == "pending"

    def test_submit_order_no_price(self, adapter):
        """Test order without price (market order)."""
        mock_order = MagicMock()
        mock_order.fill_price = 51000.0
        mock_order.filled_size = 0.0
        mock_order.status = MockOrderStatus.FILLED
        adapter._engine.place_order.return_value = mock_order
        
        request = TradeRequest(
            venue="paper",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=0.1,
            price=None
        )
        
        result = adapter._submit_order_live(request)
        
        # Notional calculated as (price or 0) * quantity = 0
        call_args = adapter._engine.place_order.call_args
        assert call_args.kwargs["size_usd"] == 0.0

    def test_submit_order_none_fill_price(self, adapter):
        """Test order with None fill_price."""
        mock_order = MagicMock()
        mock_order.fill_price = None
        mock_order.filled_size = None
        mock_order.status = MockOrderStatus.FILLED
        adapter._engine.place_order.return_value = mock_order
        
        request = TradeRequest(
            venue="paper",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=0.1,
            price=50000.0
        )
        
        result = adapter._submit_order_live(request)
        
        assert result.executed_price == 0.0


# =============================================================================
# Class Attributes Tests
# =============================================================================

class TestClassAttributes:
    """Test class-level attributes."""

    def test_venue_name(self):
        assert PaperTradingAdapter.venue == "paper"

    def test_supports_trading(self):
        assert PaperTradingAdapter.supports_trading is True
