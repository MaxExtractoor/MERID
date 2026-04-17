"""Tests for trading/router.py - Coverage improvement."""

import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock

from trading.router import (
    _adapter_executor_factory,
    get_execution_router,
)
from trading.adapters.base import TradeSide, OrderResult


# =============================================================================
# _adapter_executor_factory Tests
# =============================================================================

class TestAdapterExecutorFactory:
    """Test _adapter_executor_factory function."""
    
    def test_returns_none_for_unknown_venue(self):
        """Test returns None for unknown venue."""
        with patch("trading.router.get_adapter", return_value=None):
            executor = _adapter_executor_factory("unknown_venue")
        
        assert executor is None
    
    def test_returns_executor_for_known_venue(self):
        """Test returns executor for known venue."""
        mock_adapter = Mock()
        mock_adapter.venue = "test_venue"
        
        with patch("trading.router.get_adapter", return_value=mock_adapter):
            executor = _adapter_executor_factory("test_venue")
        
        assert executor is not None
        assert executor.venue == "test_venue"
    
    @pytest.mark.asyncio
    async def test_executor_execute_trade(self):
        """Test executor execute_trade method."""
        mock_adapter = Mock()
        mock_adapter.venue = "test_venue"
        mock_adapter.submit_order.return_value = OrderResult(
            venue="test_venue",
            symbol="AAPL",
            side=TradeSide.BUY,
            quantity=10.0,
            executed_price=150.0,
            status="executed",
            venue_order_id="order_123",
            metadata={}
        )
        
        with patch("trading.router.get_adapter", return_value=mock_adapter):
            executor = _adapter_executor_factory("test_venue")
            result = await executor.execute_trade(
                symbol="AAPL",
                side="buy",
                amount=10.0,
                order_type="market",
                price=None,
                metadata={"test": True}
            )
        
        assert result.success is True
        assert result.venue == "test_venue"
        assert result.symbol == "AAPL"
        assert result.size == 10.0
        assert result.price == 150.0
    
    @pytest.mark.asyncio
    async def test_executor_execute_trade_failed(self):
        """Test executor execute_trade with failed order."""
        mock_adapter = Mock()
        mock_adapter.venue = "test_venue"
        mock_adapter.submit_order.return_value = OrderResult(
            venue="test_venue",
            symbol="AAPL",
            side=TradeSide.BUY,
            quantity=10.0,
            executed_price=0.0,
            status="rejected",
            venue_order_id=None,
            transaction_hash="tx_123",
            metadata={"error": "Insufficient funds"}
        )
        
        with patch("trading.router.get_adapter", return_value=mock_adapter):
            executor = _adapter_executor_factory("test_venue")
            result = await executor.execute_trade(
                symbol="AAPL",
                side="sell",
                amount=10.0
            )
        
        assert result.success is False
        assert result.error == "Insufficient funds"
        assert result.tx_id == "tx_123"


# =============================================================================
# get_execution_router Tests
# =============================================================================

class TestGetExecutionRouter:
    """Test get_execution_router function."""
    
    def test_returns_router(self):
        """Test get_execution_router returns a router."""
        import trading.router as router_module
        router_module._router = None  # Reset singleton
        
        router = get_execution_router()
        
        assert router is not None
    
    def test_returns_singleton(self):
        """Test get_execution_router returns singleton."""
        import trading.router as router_module
        router_module._router = None  # Reset singleton
        
        router1 = get_execution_router()
        router2 = get_execution_router()
        
        assert router1 is router2
