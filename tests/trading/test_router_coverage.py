"""Comprehensive tests for trading/router.py - Coverage improvement."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from trading.adapters.base import TradeSide, OrderResult
from trading.router import (
    _adapter_executor_factory, get_execution_router
)


# =============================================================================
# Adapter Executor Factory Tests
# =============================================================================

class TestAdapterExecutorFactory:
    """Test _adapter_executor_factory function."""

    def test_factory_returns_none_when_no_adapter(self):
        with patch("trading.router.get_adapter") as mock_get:
            mock_get.return_value = None
            
            result = _adapter_executor_factory("nonexistent")
        
        assert result is None

    def test_factory_returns_executor_for_valid_adapter(self):
        mock_adapter = MagicMock()
        mock_adapter.venue = "test_venue"
        
        with patch("trading.router.get_adapter") as mock_get:
            mock_get.return_value = mock_adapter
            
            executor = _adapter_executor_factory("test_venue")
        
        assert executor is not None
        assert executor.venue == "test_venue"

    @pytest.mark.asyncio
    async def test_executor_execute_trade_success(self):
        mock_adapter = MagicMock()
        mock_adapter.venue = "test_venue"
        mock_adapter.submit_order.return_value = OrderResult(
            venue="test_venue",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=1.0,
            executed_price=50000.0,
            status="executed",
            venue_order_id="order_123",
            metadata={}
        )
        
        with patch("trading.router.get_adapter") as mock_get:
            mock_get.return_value = mock_adapter
            
            executor = _adapter_executor_factory("test_venue")
            result = await executor.execute_trade(
                symbol="BTC/USD",
                side="buy",
                amount=1.0,
                order_type="market",
                price=50000.0
            )
        
        assert result.success is True
        assert result.venue == "test_venue"
        assert result.symbol == "BTC/USD"

    @pytest.mark.asyncio
    async def test_executor_execute_trade_with_metadata(self):
        mock_adapter = MagicMock()
        mock_adapter.venue = "test_venue"
        mock_adapter.submit_order.return_value = OrderResult(
            venue="test_venue",
            symbol="ETH/USD",
            side=TradeSide.SELL,
            quantity=10.0,
            executed_price=3000.0,
            status="executed",
            transaction_hash="0xabc123",
            metadata={"error": None}
        )
        
        with patch("trading.router.get_adapter") as mock_get:
            mock_get.return_value = mock_adapter
            
            executor = _adapter_executor_factory("test_venue")
            result = await executor.execute_trade(
                symbol="ETH/USD",
                side="sell",
                amount=10.0,
                metadata={"strategy": "momentum"}
            )
        
        assert result.success is True
        assert result.tx_id == "0xabc123"

    @pytest.mark.asyncio
    async def test_executor_execute_trade_failure(self):
        mock_adapter = MagicMock()
        mock_adapter.venue = "test_venue"
        mock_adapter.submit_order.return_value = OrderResult(
            venue="test_venue",
            symbol="BTC/USD",
            side=TradeSide.BUY,
            quantity=1.0,
            executed_price=0.0,
            status="rejected",
            metadata={"error": "Insufficient funds"}
        )
        
        with patch("trading.router.get_adapter") as mock_get:
            mock_get.return_value = mock_adapter
            
            executor = _adapter_executor_factory("test_venue")
            result = await executor.execute_trade(
                symbol="BTC/USD",
                side="buy",
                amount=1.0
            )
        
        assert result.success is False
        assert result.error == "Insufficient funds"


# =============================================================================
# Get Execution Router Tests
# =============================================================================

class TestGetExecutionRouter:
    """Test get_execution_router function."""

    def test_creates_router_singleton(self):
        import trading.router as module
        module._router = None
        
        with patch("trading.router._ExecutionRouter") as mock_router_cls:
            mock_router = MagicMock()
            mock_router_cls.return_value = mock_router
            
            router1 = get_execution_router()
            router2 = get_execution_router()
        
        assert router1 is router2

    def test_router_uses_adapter_factory(self):
        import trading.router as module
        module._router = None
        
        with patch("trading.router._ExecutionRouter") as mock_router_cls:
            mock_router = MagicMock()
            mock_router_cls.return_value = mock_router
            
            get_execution_router()
        
        mock_router_cls.assert_called_once()
        call_kwargs = mock_router_cls.call_args.kwargs
        assert "executor_factory" in call_kwargs
