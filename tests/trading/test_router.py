"""Comprehensive tests for trading/router.py - Legacy execution router shim."""

import pytest
from unittest.mock import MagicMock, patch

from trading.router import (
    get_execution_router,
    _adapter_executor_factory,
    _router,
)
from trading.adapters.base import TradeRequest, TradeSide, OrderType, OrderResult
from merid.execution.base import TradeResult as ExecutionTradeResult


@pytest.fixture(autouse=True)
def reset_router():
    """Reset global router singleton before each test."""
    import trading.router as router_module
    router_module._router = None
    yield


class TestGetExecutionRouter:
    """Test get_execution_router function."""

    def test_creates_singleton_on_first_call(self):
        """Test router singleton created on first call."""
        with patch('trading.router._ExecutionRouter') as mock_router_class:
            mock_instance = MagicMock()
            mock_router_class.return_value = mock_instance
            
            result = get_execution_router()
            
            assert result is mock_instance
            mock_router_class.assert_called_once()
            # Verify executor_factory was passed
            call_kwargs = mock_router_class.call_args.kwargs
            assert "executor_factory" in call_kwargs

    def test_returns_existing_singleton(self):
        """Test subsequent calls return same instance."""
        with patch('trading.router._ExecutionRouter') as mock_router_class:
            mock_instance = MagicMock()
            mock_router_class.return_value = mock_instance
            
            result1 = get_execution_router()
            result2 = get_execution_router()
            
            assert result1 is result2 is mock_instance
            # Should only create once
            mock_router_class.assert_called_once()


class TestAdapterExecutorFactory:
    """Test _adapter_executor_factory function."""

    def test_returns_none_when_no_adapter(self):
        """Test factory returns None when adapter not found."""
        with patch('trading.router.get_adapter') as mock_get_adapter:
            mock_get_adapter.return_value = None
            
            result = _adapter_executor_factory("unknown_venue")
            
            assert result is None
            mock_get_adapter.assert_called_once_with("unknown_venue")

    def test_creates_executor_wrapper(self):
        """Test factory creates AdapterExecutor wrapper."""
        with patch('trading.router.get_adapter') as mock_get_adapter:
            mock_adapter = MagicMock()
            mock_adapter.venue = "alpaca"
            mock_get_adapter.return_value = mock_adapter
            
            result = _adapter_executor_factory("alpaca")
            
            assert result is not None
            assert result.venue == "alpaca"
            assert result._adapter is mock_adapter

    def test_executor_wrapper_has_required_methods(self):
        """Test wrapper has TradeExecutor interface methods."""
        with patch('trading.router.get_adapter') as mock_get_adapter:
            mock_adapter = MagicMock()
            mock_adapter.venue = "test"
            mock_get_adapter.return_value = mock_adapter
            
            executor = _adapter_executor_factory("test")
            
            # Check required methods exist
            assert hasattr(executor, 'get_quote')
            assert hasattr(executor, 'execute_trade')
            assert hasattr(executor, 'get_positions')


class TestAdapterExecutorExecuteTrade:
    """Test AdapterExecutor.execute_trade method."""

    @pytest.mark.asyncio
    async def test_execute_trade_market_order(self):
        """Test executing market order through adapter."""
        with patch('trading.router.get_adapter') as mock_get_adapter:
            mock_adapter = MagicMock()
            mock_adapter.venue = "alpaca"
            
            # Mock order result from adapter
            mock_result = MagicMock()
            mock_result.status = "executed"
            mock_result.venue = "alpaca"
            mock_result.symbol = "AAPL"
            mock_result.side = TradeSide.BUY
            mock_result.quantity = 10.0
            mock_result.executed_price = 150.0
            mock_result.venue_order_id = "order_123"
            mock_result.transaction_hash = None
            mock_result.metadata = {}
            mock_adapter.submit_order.return_value = mock_result
            
            mock_get_adapter.return_value = mock_adapter
            
            executor = _adapter_executor_factory("alpaca")
            
            result = await executor.execute_trade(
                symbol="AAPL",
                side="buy",
                amount=10.0,
                order_type="market"
            )
            
            assert isinstance(result, ExecutionTradeResult)
            assert result.success is True
            assert result.venue == "alpaca"
            assert result.symbol == "AAPL"
            assert result.side == "buy"
            assert result.size == 10.0
            assert result.price == 150.0
            assert result.tx_id == "order_123"
            
            # Verify adapter was called correctly
            call_args = mock_adapter.submit_order.call_args[0][0]
            assert isinstance(call_args, TradeRequest)
            assert call_args.symbol == "AAPL"
            assert call_args.side == TradeSide.BUY
            assert call_args.quantity == 10.0

    @pytest.mark.asyncio
    async def test_execute_trade_limit_order(self):
        """Test executing limit order through adapter."""
        with patch('trading.router.get_adapter') as mock_get_adapter:
            mock_adapter = MagicMock()
            mock_adapter.venue = "alpaca"
            
            mock_result = MagicMock()
            mock_result.status = "executed"
            mock_result.venue = "alpaca"
            mock_result.symbol = "TSLA"
            mock_result.side = TradeSide.SELL
            mock_result.quantity = 5.0
            mock_result.executed_price = 200.0
            mock_result.venue_order_id = "order_456"
            mock_result.transaction_hash = None
            mock_result.metadata = {}
            mock_adapter.submit_order.return_value = mock_result
            
            mock_get_adapter.return_value = mock_adapter
            
            executor = _adapter_executor_factory("alpaca")
            
            result = await executor.execute_trade(
                symbol="TSLA",
                side="sell",
                amount=5.0,
                order_type="limit",
                price=200.0
            )
            
            assert result.success is True
            assert result.price == 200.0
            
            call_args = mock_adapter.submit_order.call_args[0][0]
            assert call_args.price == 200.0

    @pytest.mark.asyncio
    async def test_execute_trade_failed_order(self):
        """Test failed order execution."""
        with patch('trading.router.get_adapter') as mock_get_adapter:
            mock_adapter = MagicMock()
            mock_adapter.venue = "alpaca"
            
            mock_result = MagicMock()
            mock_result.status = "rejected"
            mock_result.venue = "alpaca"
            mock_result.symbol = "AAPL"
            mock_result.side = TradeSide.BUY
            mock_result.quantity = 0.0
            mock_result.executed_price = 0.0
            mock_result.venue_order_id = None
            mock_result.transaction_hash = None
            mock_result.metadata = {"error": "Insufficient funds"}
            mock_adapter.submit_order.return_value = mock_result
            
            mock_get_adapter.return_value = mock_adapter
            
            executor = _adapter_executor_factory("alpaca")
            
            result = await executor.execute_trade(
                symbol="AAPL",
                side="buy",
                amount=100.0
            )
            
            assert result.success is False
            assert result.error == "Insufficient funds"

    @pytest.mark.asyncio
    async def test_execute_trade_with_metadata(self):
        """Test order execution with custom metadata."""
        with patch('trading.router.get_adapter') as mock_get_adapter:
            mock_adapter = MagicMock()
            mock_adapter.venue = "alpaca"
            
            mock_result = MagicMock()
            mock_result.status = "executed"
            mock_result.venue = "alpaca"
            mock_result.symbol = "MSFT"
            mock_result.side = TradeSide.BUY
            mock_result.quantity = 50.0
            mock_result.executed_price = 300.0
            mock_result.venue_order_id = "order_789"
            mock_result.transaction_hash = None
            mock_result.metadata = {"time_in_force": "gtc"}
            mock_adapter.submit_order.return_value = mock_result
            
            mock_get_adapter.return_value = mock_adapter
            
            executor = _adapter_executor_factory("alpaca")
            
            result = await executor.execute_trade(
                symbol="MSFT",
                side="buy",
                amount=50.0,
                metadata={"time_in_force": "gtc"}
            )
            
            call_args = mock_adapter.submit_order.call_args[0][0]
            assert call_args.metadata == {"time_in_force": "gtc"}


class TestAdapterExecutorGetQuote:
    """Test AdapterExecutor.get_quote method."""

    @pytest.mark.asyncio
    async def test_get_quote_not_implemented(self):
        """Test get_quote raises NotImplementedError."""
        with patch('trading.router.get_adapter') as mock_get_adapter:
            mock_adapter = MagicMock()
            mock_adapter.venue = "alpaca"
            mock_get_adapter.return_value = mock_adapter
            
            executor = _adapter_executor_factory("alpaca")
            
            with pytest.raises(NotImplementedError) as exc_info:
                await executor.get_quote("AAPL", "buy", 10.0)
            
            assert "do not support get_quote" in str(exc_info.value)


class TestAdapterExecutorGetPositions:
    """Test AdapterExecutor.get_positions method."""

    @pytest.mark.asyncio
    async def test_get_positions_returns_empty(self):
        """Test get_positions returns empty list."""
        with patch('trading.router.get_adapter') as mock_get_adapter:
            mock_adapter = MagicMock()
            mock_adapter.venue = "alpaca"
            mock_get_adapter.return_value = mock_adapter
            
            executor = _adapter_executor_factory("alpaca")
            
            result = await executor.get_positions()
            
            assert result == []


class TestModuleImports:
    """Test module-level imports and setup."""

    def test_imports_execute_router_class(self):
        """Test _ExecutionRouter is imported from merid.execution.router."""
        from trading.router import _ExecutionRouter
        # Should be the same class
        from merid.execution.router import ExecutionRouter
        assert _ExecutionRouter is ExecutionRouter

    def test_imports_trader_identity(self):
        """Test TraderIdentity is imported."""
        from trading.router import TraderIdentity
        from merid.execution.router import TraderIdentity as RealTraderIdentity
        assert TraderIdentity is RealTraderIdentity

    def test_adapter_registration_import(self):
        """Test trading.adapters is imported for registration side effect."""
        # This test just verifies the import doesn't fail
        import trading.router
        # The module should have imported trading.adapters
        # which triggers adapter registration
