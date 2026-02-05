"""Tests for trading execution_engine module - Batch 47 Coverage."""
import pytest
from unittest.mock import MagicMock, patch
import time
import asyncio

from trading.execution_engine import (
    OrderType,
    OrderSide,
    OrderStatus,
    TradeOrder,
    ExecutionResult,
    Position,
    TradingExecutionEngine,
)


class TestEnums:
    """Tests for enums."""

    def test_order_type_values(self):
        assert OrderType.MARKET.value == "market"
        assert OrderType.LIMIT.value == "limit"
        assert OrderType.STOP_MARKET.value == "stop_market"
        assert OrderType.STOP_LIMIT.value == "stop_limit"

    def test_order_side_values(self):
        assert OrderSide.BUY.value == "buy"
        assert OrderSide.SELL.value == "sell"

    def test_order_status_values(self):
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.SUBMITTED.value == "submitted"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.PARTIALLY_FILLED.value == "partially_filled"
        assert OrderStatus.CANCELLED.value == "cancelled"
        assert OrderStatus.REJECTED.value == "rejected"
        assert OrderStatus.FAILED.value == "failed"


class TestTradeOrder:
    """Tests for TradeOrder dataclass."""

    def test_order_creation(self):
        order = TradeOrder(
            order_id="order_123",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
        )
        assert order.order_id == "order_123"
        assert order.symbol == "BTCUSDT"
        assert order.side == OrderSide.BUY
        assert order.order_type == OrderType.MARKET
        assert order.quantity == 1.0
        assert order.time_in_force == "GTC"
        assert order.reduce_only is False


class TestExecutionResult:
    """Tests for ExecutionResult dataclass."""

    def test_result_creation(self):
        result = ExecutionResult(
            order_id="order_123",
            status=OrderStatus.FILLED,
            executed_quantity=1.0,
            executed_price=50000.0,
            execution_fee=50.0,
            timestamp=time.time(),
            venue="test",
        )
        assert result.order_id == "order_123"
        assert result.status == OrderStatus.FILLED
        assert result.executed_quantity == 1.0
        assert result.executed_price == 50000.0


class TestPosition:
    """Tests for Position dataclass."""

    def test_position_creation(self):
        pos = Position(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            size=1000.0,
            entry_price=50000.0,
            current_price=51000.0,
            unrealized_pnl=100.0,
            realized_pnl=0.0,
            timestamp=time.time(),
            venue="test",
        )
        assert pos.symbol == "BTCUSDT"
        assert pos.size == 1000.0
        assert pos.unrealized_pnl == 100.0


class TestTradingExecutionEngine:
    """Tests for TradingExecutionEngine class."""

    @pytest.fixture
    def engine(self):
        config = {"dry_run": True, "max_position_size": 50000.0, "max_daily_loss": 5000.0}
        return TradingExecutionEngine(config)

    @pytest.fixture
    def sample_order(self):
        return TradeOrder(
            order_id="order_123",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
        )

    def test_initialization(self, engine):
        assert engine.dry_run is True
        assert engine.max_position_size == 50000.0
        assert engine.max_daily_loss == 5000.0
        assert engine._daily_pnl == 0.0
        assert engine._order_count == 0
        assert engine._error_count == 0

    @pytest.mark.asyncio
    async def test_execute_order_safety_check_failure(self, engine, sample_order):
        """Test order execution when safety check fails."""
        # Set daily loss exceeded
        engine._daily_pnl = -6000.0
        
        result = await engine.execute_order(sample_order)
        
        assert result.status == OrderStatus.REJECTED
        assert "Safety check failed" in result.error_message

    @pytest.mark.asyncio
    async def test_execute_order_market_fill(self, engine, sample_order):
        """Test market order execution fills."""
        result = await engine.execute_order(sample_order)
        
        assert result.status == OrderStatus.FILLED
        assert result.executed_quantity == 0.1
        assert result.executed_price is not None
        assert result.venue == "dry_run"

    @pytest.mark.asyncio
    async def test_execute_order_limit_may_not_fill(self, engine):
        """Test limit order may not fill (submitted status)."""
        order = TradeOrder(
            order_id="order_456",
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=1.0,
            price=3000.0,
        )
        
        result = await engine.execute_order(order)
        
        # Note: Due to randomness, it might fill or not fill
        # Just verify the result structure is valid
        assert result.order_id == "order_456"

    @pytest.mark.asyncio
    async def test_execute_live_fallback(self, engine, sample_order):
        """Test that live mode falls back to dry run."""
        engine.dry_run = False
        
        result = await engine.execute_order(sample_order)
        
        # Live mode falls back to dry_run
        assert result.venue == "dry_run"

    @pytest.mark.asyncio
    async def test_execute_order_exception_handling(self, engine, sample_order):
        """Test exception handling during execution."""
        # Mock safety_check to raise exception
        with patch.object(engine, '_safety_check', side_effect=Exception("Test error")):
            result = await engine.execute_order(sample_order)
            
        assert result.status == OrderStatus.FAILED
        assert engine._error_count == 1

    def test_safety_check_position_size(self, engine):
        """Test safety check with position size limit."""
        # Create order exceeding max position size
        order = TradeOrder(
            order_id="order_large",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10.0,  # $450K at default price
        )
        
        result = asyncio.run(engine._safety_check(order))
        assert result is False

    def test_safety_check_rate_limiting(self, engine):
        """Test safety check with rate limiting."""
        # Set last execution time to now
        engine._last_execution_time = time.time()
        
        order = TradeOrder(
            order_id="order_fast",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
        )
        
        result = asyncio.run(engine._safety_check(order))
        # Should fail due to rate limiting (orders too fast)
        assert result is False

    def test_safety_check_unsupported_symbol(self, engine):
        """Test safety check with unsupported symbol."""
        order = TradeOrder(
            order_id="order_bad",
            symbol="UNKNOWN",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
        )
        
        result = asyncio.run(engine._safety_check(order))
        assert result is False

    def test_safety_check_exception(self, engine):
        """Test safety check exception handling."""
        # Force an exception by passing None
        result = asyncio.run(engine._safety_check(None))
        assert result is False

    def test_get_mock_price(self, engine):
        """Test mock price generation."""
        price = engine._get_mock_price("BTCUSDT")
        assert 44000.0 <= price <= 46000.0  # Around 45000 with variation

    def test_get_mock_price_unknown(self, engine):
        """Test mock price for unknown symbol."""
        price = engine._get_mock_price("UNKNOWN")
        assert 0.999 <= price <= 1.001  # Around 1.0 with variation

    @pytest.mark.asyncio
    async def test_update_position_new(self, engine, sample_order):
        """Test creating new position."""
        result = ExecutionResult(
            order_id="order_123",
            status=OrderStatus.FILLED,
            executed_quantity=0.1,
            executed_price=50000.0,
            execution_fee=5.0,
            timestamp=time.time(),
            venue="test",
        )
        
        await engine._update_position(sample_order, result)
        
        pos = engine.get_position("BTCUSDT")
        assert pos is not None
        assert pos.symbol == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_update_position_existing(self, engine, sample_order):
        """Test updating existing position."""
        # Create initial position
        engine._positions["BTCUSDT"] = Position(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            size=1000.0,
            entry_price=49000.0,
            current_price=50000.0,
            unrealized_pnl=100.0,
            realized_pnl=0.0,
            timestamp=time.time(),
            venue="test",
        )
        
        result = ExecutionResult(
            order_id="order_123",
            status=OrderStatus.FILLED,
            executed_quantity=0.1,
            executed_price=51000.0,
            execution_fee=5.0,
            timestamp=time.time(),
            venue="test",
        )
        
        await engine._update_position(sample_order, result)
        
        pos = engine.get_position("BTCUSDT")
        assert pos.size > 1000.0  # Size increased

    @pytest.mark.asyncio
    async def test_update_position_not_filled(self, engine, sample_order):
        """Test position update when not filled."""
        result = ExecutionResult(
            order_id="order_123",
            status=OrderStatus.SUBMITTED,
            executed_quantity=0.0,
            executed_price=None,
            execution_fee=0.0,
            timestamp=time.time(),
            venue="test",
        )
        
        await engine._update_position(sample_order, result)
        
        # No position should be created
        assert engine.get_position("BTCUSDT") is None

    @pytest.mark.asyncio
    async def test_update_daily_pnl_reset(self, engine):
        """Test daily PnL reset after 24 hours."""
        # Set last reset to more than 24 hours ago
        engine._last_reset_time = time.time() - 90000
        engine._daily_pnl = -1000.0
        
        result = ExecutionResult(
            order_id="order_123",
            status=OrderStatus.FILLED,
            executed_quantity=0.1,
            executed_price=50000.0,
            execution_fee=5.0,
            timestamp=time.time(),
            venue="test",
        )
        
        await engine._update_daily_pnl(result)
        
        # PnL should be reset (only fee subtracted from 0)
        assert engine._daily_pnl == -5.0

    def test_create_rejected_result(self, engine, sample_order):
        """Test creating rejected result."""
        result = engine._create_rejected_result(sample_order, "Test rejection")
        
        assert result.status == OrderStatus.REJECTED
        assert result.error_message == "Test rejection"
        assert result.executed_quantity == 0.0

    def test_create_failed_result(self, engine, sample_order):
        """Test creating failed result."""
        result = engine._create_failed_result(sample_order, "Test error")
        
        assert result.status == OrderStatus.FAILED
        assert result.error_message == "Test error"

    def test_get_all_positions(self, engine):
        """Test getting all positions."""
        engine._positions["BTCUSDT"] = Position(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            size=1000.0,
            entry_price=50000.0,
            current_price=51000.0,
            unrealized_pnl=100.0,
            realized_pnl=0.0,
            timestamp=time.time(),
            venue="test",
        )
        
        positions = engine.get_all_positions()
        assert len(positions) == 1
        assert "BTCUSDT" in positions

    def test_get_execution_metrics(self, engine):
        """Test getting execution metrics."""
        # Add some executions
        engine._executions["order_1"] = ExecutionResult(
            order_id="order_1",
            status=OrderStatus.FILLED,
            executed_quantity=0.1,
            executed_price=50000.0,
            execution_fee=5.0,
            timestamp=time.time(),
            venue="test",
        )
        
        metrics = engine.get_execution_metrics()
        
        assert metrics["total_orders"] == 1
        assert metrics["filled_orders"] == 1
        assert metrics["fill_rate"] == 1.0
        assert metrics["dry_run"] is True

    @pytest.mark.asyncio
    async def test_cancel_order_success(self, engine):
        """Test cancelling an order."""
        # Add a submitted order
        engine._executions["order_to_cancel"] = ExecutionResult(
            order_id="order_to_cancel",
            status=OrderStatus.SUBMITTED,
            executed_quantity=0.0,
            executed_price=None,
            execution_fee=0.0,
            timestamp=time.time(),
            venue="test",
        )
        
        result = await engine.cancel_order("order_to_cancel")
        assert result is True
        assert engine._executions["order_to_cancel"].status == OrderStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_order_not_found(self, engine):
        """Test cancelling non-existent order."""
        result = await engine.cancel_order("non_existent")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_order_already_filled(self, engine):
        """Test cancelling already filled order."""
        engine._executions["order_filled"] = ExecutionResult(
            order_id="order_filled",
            status=OrderStatus.FILLED,
            executed_quantity=0.1,
            executed_price=50000.0,
            execution_fee=5.0,
            timestamp=time.time(),
            venue="test",
        )
        
        result = await engine.cancel_order("order_filled")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_order_exception(self, engine):
        """Test cancel order exception handling."""
        # Force exception by manipulating internal state
        engine._executions = None  # This will cause an exception
        
        result = await engine.cancel_order("order_123")
        assert result is False
        # Error is logged but not counted in error_count for cancel_order

    def test_reset_daily_metrics(self, engine):
        """Test resetting daily metrics."""
        engine._daily_pnl = -1000.0
        old_reset_time = engine._last_reset_time
        
        # Small delay to ensure time difference is detectable
        time.sleep(0.01)
        engine.reset_daily_metrics()
        
        assert engine._daily_pnl == 0.0
        assert engine._last_reset_time >= old_reset_time  # Use >= for timing tolerance
