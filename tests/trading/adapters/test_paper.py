"""Tests for trading/adapters/paper.py."""
import pytest
from unittest.mock import Mock, patch
from trading.adapters.paper import PaperTradingAdapter
from trading.adapters.base import TradeRequest, TradeSide, OrderType


class TestPaperTradingAdapter:
    """Test PaperTradingAdapter class."""

    def test_initialization(self):
        """Test adapter initialization."""
        adapter = PaperTradingAdapter()
        assert adapter.venue == "paper"
        assert adapter.supports_trading is True
        assert adapter._engine is not None

    @patch('trading.adapters.paper.get_paper_engine')
    def test_submit_order_buy(self, mock_get_engine):
        """Test submitting a buy order."""
        mock_engine = Mock()
        mock_order = Mock()
        mock_order.status.value = "filled"
        mock_order.fill_price = 50000.0
        mock_order.filled_size = 1000.0
        mock_engine.place_order.return_value = mock_order
        mock_get_engine.return_value = mock_engine

        adapter = PaperTradingAdapter()
        request = TradeRequest(
            venue="paper",
            symbol="BTC",
            side=TradeSide.BUY,
            quantity=0.1,
            order_type=OrderType.MARKET,
            price=50000.0,
            metadata={"trader_id": "user_123", "notional_usd": 5000.0}
        )

        result = adapter._submit_order_live(request)

        assert result.venue == "paper"
        assert result.symbol == "BTC"
        assert result.side == TradeSide.BUY
        assert result.executed_price == 50000.0
        assert result.status == "executed"
        mock_engine.place_order.assert_called_once()

    @patch('trading.adapters.paper.get_paper_engine')
    def test_submit_order_sell(self, mock_get_engine):
        """Test submitting a sell order."""
        mock_engine = Mock()
        mock_order = Mock()
        mock_order.status.value = "pending"
        mock_order.fill_price = None
        mock_order.filled_size = None
        mock_engine.place_order.return_value = mock_order
        mock_get_engine.return_value = mock_engine

        adapter = PaperTradingAdapter()
        request = TradeRequest(
            venue="paper",
            symbol="ETH",
            side=TradeSide.SELL,
            quantity=1.0,
            order_type=OrderType.MARKET,
            metadata={"trader_id": "user_456"}
        )

        result = adapter._submit_order_live(request)

        assert result.venue == "paper"
        assert result.symbol == "ETH"
        assert result.side == TradeSide.SELL
        # Should pass side as "short" for sells
        call_args = mock_engine.place_order.call_args[1]
        assert call_args["side"] == "short"

    @patch('trading.adapters.paper.get_paper_engine')
    def test_submit_order_default_trader(self, mock_get_engine):
        """Test order with default trader_id."""
        mock_engine = Mock()
        mock_order = Mock()
        mock_order.status.value = "filled"
        mock_order.fill_price = 100.0
        mock_order.filled_size = 100.0
        mock_engine.place_order.return_value = mock_order
        mock_get_engine.return_value = mock_engine

        adapter = PaperTradingAdapter()
        request = TradeRequest(
            venue="paper",
            symbol="SOL",
            side=TradeSide.BUY,
            quantity=10.0,
            metadata={}  # No trader_id
        )

        adapter._submit_order_live(request)

        call_args = mock_engine.place_order.call_args[1]
        assert call_args["user_id"] == "paper_router"
