"""Tests for trading router shim - Batch 29 Coverage."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from trading.router import (
    _adapter_executor_factory,
    get_execution_router,
    _router
)
from trading.adapters.base import TradeSide


class TestAdapterExecutorFactory:
    """Tests for _adapter_executor_factory function."""

    def test_factory_returns_none_for_unknown_venue(self):
        """Test factory returns None when adapter not found."""
        with patch('trading.router.get_adapter', return_value=None):
            result = _adapter_executor_factory("unknown_venue")
            assert result is None

    def test_factory_creates_executor(self):
        """Test factory creates adapter executor."""
        mock_adapter = MagicMock()
        mock_adapter.venue = "test_venue"
        
        with patch('trading.router.get_adapter', return_value=mock_adapter):
            executor = _adapter_executor_factory("test_venue")
            
            assert executor is not None
            assert executor.venue == "test_venue"
            assert executor._adapter == mock_adapter

    @pytest.mark.asyncio
    async def test_executor_get_quote_raises(self):
        """Test executor get_quote raises NotImplementedError."""
        mock_adapter = MagicMock()
        mock_adapter.venue = "test_venue"
        
        with patch('trading.router.get_adapter', return_value=mock_adapter):
            executor = _adapter_executor_factory("test_venue")
            
            with pytest.raises(NotImplementedError):
                await executor.get_quote("BTC", "buy", 1.0)

    @pytest.mark.asyncio
    async def test_executor_get_positions(self):
        """Test executor get_positions returns empty list."""
        mock_adapter = MagicMock()
        mock_adapter.venue = "test_venue"
        
        with patch('trading.router.get_adapter', return_value=mock_adapter):
            executor = _adapter_executor_factory("test_venue")
            positions = await executor.get_positions()
            
            assert positions == []


class TestGetExecutionRouter:
    """Tests for get_execution_router function."""

    def test_singleton(self):
        """Test that get_execution_router returns singleton."""
        # Reset module state
        import trading.router as router_module
        router_module._router = None
        
        with patch('trading.router._ExecutionRouter') as mock_router_class:
            mock_instance = MagicMock()
            mock_router_class.return_value = mock_instance
            
            router1 = get_execution_router()
            router2 = get_execution_router()
            
            assert router1 is router2
            assert router1 is mock_instance
            # Constructor should only be called once
            mock_router_class.assert_called_once()

    def test_router_initialized_with_factory(self):
        """Test router is initialized with adapter executor factory."""
        import trading.router as router_module
        router_module._router = None
        
        with patch('trading.router._ExecutionRouter') as mock_router_class:
            mock_instance = MagicMock()
            mock_router_class.return_value = mock_instance
            
            router = get_execution_router()
            
            # Verify factory function was passed
            call_kwargs = mock_router_class.call_args[1]
            assert 'executor_factory' in call_kwargs
            assert call_kwargs['executor_factory'] is _adapter_executor_factory


class TestModuleImports:
    """Tests that module imports work correctly."""

    def test_imports(self):
        """Test that all expected imports are available."""
        from trading.router import TradeExecutor, TradeResult
        from trading.router import TradeRequest, TradeSide
        from trading.router import get_adapter
        
        assert TradeExecutor is not None
        assert TradeResult is not None
        assert TradeRequest is not None
        assert TradeSide is not None
        assert get_adapter is not None
