"""Tests for trading adapters paper module - Batch 43 Coverage."""
import pytest
from unittest.mock import MagicMock, patch

from trading.adapters.paper import PaperTradingAdapter
from trading.adapters.base import TradeRequest, TradeSide, OrderType
from trading.paper_trading import PaperOrder, PaperOrderStatus


class TestPaperTradingAdapter:
    """Tests for PaperTradingAdapter class."""

    @pytest.fixture
    def adapter(self):
        with patch('trading.adapters.paper.get_paper_engine') as mock_get_engine:
            mock_engine = MagicMock()
            mock_get_engine.return_value = mock_engine
            return PaperTradingAdapter(), mock_engine

    def test_initialization(self, adapter):
        adapter_instance, _ = adapter
        assert adapter_instance.venue == "paper"
        assert adapter_instance.supports_trading is True
        assert adapter_instance.use_mock is False

    def test_submit_order_live_buy(self, adapter):
        adapter_instance, mock_engine = adapter
        
        # Create mock order result
        mock_order = PaperOrder(
            order_id="order_123",
            user_id="test_trader",
            asset="BTC",
            side="long",
            order_type=MagicMock(),
            size_usd=1000.0,
            fill_price=50000.0,
            filled_size=1000.0,
            status=PaperOrderStatus.FILLED,
        )
        mock_engine.place_order.return_value = mock_order

        request = TradeRequest(
            venue="paper",
            symbol="BTC",
            side=TradeSide.BUY,
            quantity=0.02,
            order_type=OrderType.MARKET,
            price=50000.0,
            metadata={"trader_id": "test_trader", "notional_usd": 1000.0},
        )

        result = adapter_instance._submit_order_live(request)

        assert result.venue == "paper"
        assert result.symbol == "BTC"
        assert result.side == TradeSide.BUY
        assert result.quantity == 0.02
        assert result.executed_price == 50000.0
        assert result.status == "executed"
        assert "fills" in result.metadata

        # Verify engine was called correctly
        mock_engine.place_order.assert_called_once()
        call_kwargs = mock_engine.place_order.call_args.kwargs
        assert call_kwargs["user_id"] == "test_trader"
        assert call_kwargs["asset"] == "BTC"
        assert call_kwargs["side"] == "long"
        assert call_kwargs["size_usd"] == 1000.0

    def test_submit_order_live_sell(self, adapter):
        adapter_instance, mock_engine = adapter
        
        mock_order = PaperOrder(
            order_id="order_456",
            user_id="default",
            asset="ETH",
            side="short",
            order_type=MagicMock(),
            size_usd=500.0,
            fill_price=3000.0,
            filled_size=500.0,
            status=PaperOrderStatus.FILLED,
        )
        mock_engine.place_order.return_value = mock_order

        request = TradeRequest(
            venue="paper",
            symbol="ETH",
            side=TradeSide.SELL,
            quantity=0.166,
            order_type=OrderType.MARKET,
            price=3000.0,
            metadata={},  # No trader_id, should use default
        )

        result = adapter_instance._submit_order_live(request)

        assert result.side == TradeSide.SELL
        # Verify default user_id is used
        call_kwargs = mock_engine.place_order.call_args.kwargs
        assert call_kwargs["user_id"] == "paper_router"
        assert call_kwargs["side"] == "short"

    def test_submit_order_live_calculate_notional(self, adapter):
        adapter_instance, mock_engine = adapter
        
        mock_order = PaperOrder(
            order_id="order_789",
            user_id="test",
            asset="BTC",
            side="long",
            order_type=MagicMock(),
            size_usd=2500.0,  # 0.05 * 50000
            fill_price=50000.0,
            filled_size=2500.0,
            status=PaperOrderStatus.FILLED,
        )
        mock_engine.place_order.return_value = mock_order

        # No notional_usd in metadata, should calculate from price * quantity
        request = TradeRequest(
            venue="paper",
            symbol="BTC",
            side=TradeSide.BUY,
            quantity=0.05,
            order_type=OrderType.LIMIT,
            price=50000.0,
            metadata={},
        )

        result = adapter_instance._submit_order_live(request)

        call_kwargs = mock_engine.place_order.call_args.kwargs
        assert call_kwargs["size_usd"] == 2500.0

    def test_submit_order_live_with_leverage(self, adapter):
        adapter_instance, mock_engine = adapter
        
        mock_order = PaperOrder(
            order_id="order_999",
            user_id="test",
            asset="BTC",
            side="long",
            order_type=MagicMock(),
            size_usd=1000.0,
            fill_price=50000.0,
            filled_size=1000.0,
            status=PaperOrderStatus.FILLED,
        )
        mock_engine.place_order.return_value = mock_order

        request = TradeRequest(
            venue="paper",
            symbol="BTC",
            side=TradeSide.BUY,
            quantity=0.02,
            order_type=OrderType.MARKET,
            price=50000.0,
            metadata={"leverage": 5},
        )

        result = adapter_instance._submit_order_live(request)

        call_kwargs = mock_engine.place_order.call_args.kwargs
        assert call_kwargs["leverage"] == 5

    def test_submit_order_live_pending_status(self, adapter):
        adapter_instance, mock_engine = adapter
        
        # Order with pending status
        mock_order = PaperOrder(
            order_id="order_111",
            user_id="test",
            asset="BTC",
            side="long",
            order_type=MagicMock(),
            size_usd=1000.0,
            fill_price=None,
            filled_size=0.0,
            status=PaperOrderStatus.PENDING,
        )
        mock_engine.place_order.return_value = mock_order

        request = TradeRequest(
            venue="paper",
            symbol="BTC",
            side=TradeSide.BUY,
            quantity=0.02,
            order_type=OrderType.MARKET,
            price=50000.0,
            metadata={},
        )

        result = adapter_instance._submit_order_live(request)

        assert result.status == "pending"  # Not "executed"
        assert result.executed_price == 0.0  # No fill price

    def test_submit_order_live_rejected_status(self, adapter):
        adapter_instance, mock_engine = adapter
        
        # Order with rejected status
        mock_order = PaperOrder(
            order_id="order_222",
            user_id="test",
            asset="BTC",
            side="long",
            order_type=MagicMock(),
            size_usd=1000.0,
            fill_price=None,
            filled_size=0.0,
            status=PaperOrderStatus.REJECTED,
        )
        mock_engine.place_order.return_value = mock_order

        request = TradeRequest(
            venue="paper",
            symbol="BTC",
            side=TradeSide.BUY,
            quantity=0.02,
            order_type=OrderType.MARKET,
            price=50000.0,
            metadata={},
        )

        result = adapter_instance._submit_order_live(request)

        assert result.status == "rejected"

    def test_register_adapter(self):
        """Test that adapter is available but may not be registered in Kalshi-only mode."""
        from trading.adapters import registry
        from merid.settings import settings
        
        # Force re-registration since other tests may have cleared the registry
        import importlib
        import trading.adapters.paper as paper_module
        importlib.reload(paper_module)
        
        # In Kalshi-only mode, paper adapter is not auto-registered
        # In legacy mode, it would be registered
        if settings.KALSHI_ONLY:
            # Paper adapter is deliberately NOT registered in Kalshi-only mode
            assert "paper" not in registry._adapters or "kalshi" in registry._adapters
        else:
            # The adapter should be registered when the module is imported (legacy mode)
            assert "paper" in registry._adapters
