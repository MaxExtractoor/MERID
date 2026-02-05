"""
Tests for TradingExecutionEngine - Batch 1 Coverage Improvement
"""
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch

from trading.execution_engine import (
    TradingExecutionEngine, TradeOrder, ExecutionResult, 
    OrderStatus, OrderSide, OrderType
)


@pytest.fixture
def execution_config():
    """Default execution config for testing."""
    return {
        "dry_run": True,
        "max_position_size": 100000.0,
        "max_daily_loss": 10000.0,
        "venues": {},
    }


@pytest.fixture
def execution_engine(execution_config):
    """Create a TradingExecutionEngine instance."""
    return TradingExecutionEngine(execution_config)


@pytest.fixture
def sample_trade_order():
    """Create a sample trade order."""
    return TradeOrder(
        order_id="test-123",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.1,
        price=45000.0,
    )


class TestTradingExecutionEngine:
    """Tests for TradingExecutionEngine core functionality."""

    @pytest.mark.asyncio
    async def test_execute_order_safety_check_pass(self, execution_engine, sample_trade_order):
        """Test order execution when safety checks pass."""
        result = await execution_engine.execute_order(sample_trade_order)
        
        assert result is not None
        assert result.order_id == sample_trade_order.order_id
        assert result.status in [OrderStatus.FILLED, OrderStatus.PENDING]
        assert execution_engine._order_count == 1
        assert sample_trade_order.order_id in execution_engine._orders

    @pytest.mark.asyncio
    async def test_execute_order_safety_check_fail_daily_loss(self, execution_engine, sample_trade_order):
        """Test order blocked when daily loss limit exceeded."""
        # Set daily loss above threshold
        execution_engine._daily_pnl = -15000.0
        
        result = await execution_engine.execute_order(sample_trade_order)
        
        assert result is not None
        assert result.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_execute_order_safety_check_fail_position_size(self, execution_engine):
        """Test order blocked when position size too large."""
        large_order = TradeOrder(
            order_id="test-large",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10.0,  # $450,000 at $45k price
            price=45000.0,
        )
        
        result = await execution_engine.execute_order(large_order)
        
        assert result is not None
        assert result.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_execute_order_dry_run(self, execution_engine, sample_trade_order):
        """Test dry run execution mode."""
        assert execution_engine.dry_run is True
        
        result = await execution_engine.execute_order(sample_trade_order)
        
        assert result is not None
        assert result.status == OrderStatus.FILLED
        # In dry run, should get simulated fill
        assert result.executed_price is not None
        assert result.executed_quantity == sample_trade_order.quantity

    @pytest.mark.asyncio
    async def test_execute_order_unsupported_symbol(self, execution_engine):
        """Test order rejected for unsupported symbol."""
        unsupported_order = TradeOrder(
            order_id="test-unsupported",
            symbol="UNKNOWN-XXX",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
            price=100.0,
        )
        
        result = await execution_engine.execute_order(unsupported_order)
        
        assert result is not None
        assert result.status == OrderStatus.REJECTED

    def test_initialization(self, execution_config):
        """Test engine initialization with config."""
        engine = TradingExecutionEngine(execution_config)
        
        assert engine.dry_run is True
        assert engine.max_position_size == 100000.0
        assert engine.max_daily_loss == 10000.0
        assert engine._daily_pnl == 0.0
        assert engine._order_count == 0
        assert engine._error_count == 0

    def test_initialization_defaults(self):
        """Test engine initialization with minimal config."""
        config = {}
        engine = TradingExecutionEngine(config)
        
        assert engine.dry_run is True  # Default should be safe
        assert engine.max_position_size > 0
        assert engine.max_daily_loss > 0

    @pytest.mark.asyncio
    async def test_get_position_and_metrics(self, execution_engine, sample_trade_order):
        """Test getting position and execution metrics."""
        # Execute an order first
        await execution_engine.execute_order(sample_trade_order)
        
        # Get metrics
        metrics = execution_engine.get_execution_metrics()
        
        assert metrics["total_orders"] == 1
        assert metrics["dry_run"] is True
        assert "fill_rate" in metrics
        
        # Get position
        position = execution_engine.get_position("BTCUSDT")
        # Position may or may not exist depending on fill

    def test_reset_daily_metrics(self, execution_engine):
        """Test resetting daily metrics."""
        execution_engine._daily_pnl = -1000.0
        
        execution_engine.reset_daily_metrics()
        
        assert execution_engine._daily_pnl == 0.0
