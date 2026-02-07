"""Tests for trading/execution_engine.py - Coverage improvement."""

import pytest
import time
from unittest.mock import patch, MagicMock, AsyncMock

from trading.execution_engine import (
    OrderType,
    OrderSide,
    OrderStatus,
    TradeOrder,
    ExecutionResult,
    Position,
    TradingExecutionEngine,
)


# =============================================================================
# Enum Tests
# =============================================================================

class TestOrderType:
    """Test OrderType enum."""
    
    def test_values(self):
        """Test OrderType enum values."""
        assert OrderType.MARKET.value == "market"
        assert OrderType.LIMIT.value == "limit"
        assert OrderType.STOP_MARKET.value == "stop_market"
        assert OrderType.STOP_LIMIT.value == "stop_limit"


class TestOrderSide:
    """Test OrderSide enum."""
    
    def test_values(self):
        """Test OrderSide enum values."""
        assert OrderSide.BUY.value == "buy"
        assert OrderSide.SELL.value == "sell"


class TestOrderStatus:
    """Test OrderStatus enum."""
    
    def test_values(self):
        """Test OrderStatus enum values."""
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.SUBMITTED.value == "submitted"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.PARTIALLY_FILLED.value == "partially_filled"
        assert OrderStatus.CANCELLED.value == "cancelled"
        assert OrderStatus.REJECTED.value == "rejected"
        assert OrderStatus.FAILED.value == "failed"


# =============================================================================
# Dataclass Tests
# =============================================================================

class TestTradeOrder:
    """Test TradeOrder dataclass."""
    
    def test_creation_minimal(self):
        """Test minimal TradeOrder creation."""
        order = TradeOrder(
            order_id="order_123",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0
        )
        
        assert order.order_id == "order_123"
        assert order.symbol == "BTCUSDT"
        assert order.side == OrderSide.BUY
        assert order.order_type == OrderType.MARKET
        assert order.quantity == 1.0
        assert order.price is None
        assert order.time_in_force == "GTC"
        assert order.reduce_only is False
    
    def test_creation_full(self):
        """Test full TradeOrder creation."""
        order = TradeOrder(
            order_id="order_123",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=2.0,
            price=50000.0,
            stop_price=49000.0,
            time_in_force="IOC",
            reduce_only=True,
            metadata={"strategy": "test"}
        )
        
        assert order.price == 50000.0
        assert order.stop_price == 49000.0
        assert order.time_in_force == "IOC"
        assert order.reduce_only is True
        assert order.metadata == {"strategy": "test"}


class TestExecutionResult:
    """Test ExecutionResult dataclass."""
    
    def test_creation(self):
        """Test ExecutionResult creation."""
        result = ExecutionResult(
            order_id="order_123",
            status=OrderStatus.FILLED,
            executed_quantity=1.0,
            executed_price=50000.0,
            execution_fee=50.0,
            timestamp=time.time(),
            venue="binance"
        )
        
        assert result.order_id == "order_123"
        assert result.status == OrderStatus.FILLED
        assert result.executed_quantity == 1.0
        assert result.executed_price == 50000.0
        assert result.execution_fee == 50.0
        assert result.error_message is None


class TestPosition:
    """Test Position dataclass."""
    
    def test_creation(self):
        """Test Position creation."""
        pos = Position(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            size=50000.0,
            entry_price=50000.0,
            current_price=51000.0,
            unrealized_pnl=1000.0,
            realized_pnl=0.0,
            timestamp=time.time(),
            venue="binance"
        )
        
        assert pos.symbol == "BTCUSDT"
        assert pos.side == OrderSide.BUY
        assert pos.size == 50000.0
        assert pos.unrealized_pnl == 1000.0


# =============================================================================
# TradingExecutionEngine Tests
# =============================================================================

class TestTradingExecutionEngineInit:
    """Test TradingExecutionEngine initialization."""
    
    def test_default_init(self):
        """Test default initialization."""
        engine = TradingExecutionEngine(config={})
        
        assert engine.dry_run is True
        assert engine.max_position_size == 100000.0
        assert engine.max_daily_loss == 10000.0
        assert engine._orders == {}
        assert engine._positions == {}
    
    def test_custom_config(self):
        """Test custom configuration."""
        config = {
            "dry_run": False,
            "max_position_size": 50000.0,
            "max_daily_loss": 5000.0,
            "venues": {"binance": {"enabled": True}}
        }
        engine = TradingExecutionEngine(config=config)
        
        assert engine.dry_run is False
        assert engine.max_position_size == 50000.0
        assert engine.max_daily_loss == 5000.0


class TestTradingExecutionEngineSafetyCheck:
    """Test _safety_check method."""
    
    @pytest.mark.asyncio
    async def test_safety_check_passes(self):
        """Test safety check passes for valid order."""
        engine = TradingExecutionEngine(config={})
        engine._last_execution_time = time.time() - 1  # 1 second ago
        
        order = TradeOrder(
            order_id="order_123",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
            price=45000.0
        )
        
        result = await engine._safety_check(order)
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_safety_check_daily_loss_exceeded(self):
        """Test safety check fails when daily loss exceeded."""
        engine = TradingExecutionEngine(config={"max_daily_loss": 1000.0})
        engine._daily_pnl = -1500.0  # Exceeds limit
        
        order = TradeOrder(
            order_id="order_123",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0
        )
        
        result = await engine._safety_check(order)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_safety_check_position_too_large(self):
        """Test safety check fails when position too large."""
        engine = TradingExecutionEngine(config={"max_position_size": 10000.0})
        engine._last_execution_time = time.time() - 1
        
        order = TradeOrder(
            order_id="order_123",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10.0,  # 10 * 45000 = 450000 > 10000
            price=45000.0
        )
        
        result = await engine._safety_check(order)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_safety_check_rate_limit(self):
        """Test safety check fails when orders too frequent."""
        engine = TradingExecutionEngine(config={})
        engine._last_execution_time = time.time()  # Just executed
        
        order = TradeOrder(
            order_id="order_123",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.01
        )
        
        result = await engine._safety_check(order)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_safety_check_unsupported_symbol(self):
        """Test safety check fails for unsupported symbol."""
        engine = TradingExecutionEngine(config={})
        engine._last_execution_time = time.time() - 1
        
        order = TradeOrder(
            order_id="order_123",
            symbol="UNKNOWNUSDT",  # Not supported
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.01
        )
        
        result = await engine._safety_check(order)
        
        assert result is False


class TestTradingExecutionEngineExecuteOrder:
    """Test execute_order method."""
    
    @pytest.mark.asyncio
    async def test_execute_order_dry_run_market(self):
        """Test market order execution in dry-run mode."""
        engine = TradingExecutionEngine(config={"dry_run": True})
        engine._last_execution_time = time.time() - 1
        
        order = TradeOrder(
            order_id="order_123",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.01
        )
        
        result = await engine.execute_order(order)
        
        assert result.order_id == "order_123"
        assert result.status == OrderStatus.FILLED
        assert result.executed_quantity == 0.01
        assert result.executed_price is not None
        assert result.metadata.get("dry_run") is True
    
    @pytest.mark.asyncio
    async def test_execute_order_safety_check_fails(self):
        """Test order rejected when safety check fails."""
        engine = TradingExecutionEngine(config={"max_daily_loss": 100.0})
        engine._daily_pnl = -200.0  # Exceeds limit
        
        order = TradeOrder(
            order_id="order_123",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.01
        )
        
        result = await engine.execute_order(order)
        
        assert result.status == OrderStatus.REJECTED
        assert "safety" in result.error_message.lower()
    
    @pytest.mark.asyncio
    async def test_execute_order_updates_position(self):
        """Test position is updated after filled order."""
        engine = TradingExecutionEngine(config={"dry_run": True})
        engine._last_execution_time = time.time() - 1
        
        order = TradeOrder(
            order_id="order_123",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.01
        )
        
        await engine.execute_order(order)
        
        assert "BTCUSDT" in engine._positions


class TestTradingExecutionEngineDryRun:
    """Test _execute_dry_run method."""
    
    @pytest.mark.asyncio
    async def test_dry_run_market_order(self):
        """Test dry-run market order always fills."""
        engine = TradingExecutionEngine(config={})
        
        order = TradeOrder(
            order_id="order_123",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0
        )
        
        result = await engine._execute_dry_run(order)
        
        assert result.status == OrderStatus.FILLED
        assert result.executed_quantity == 1.0
        assert result.venue == "dry_run"
    
    @pytest.mark.asyncio
    async def test_dry_run_limit_order(self):
        """Test dry-run limit order execution."""
        engine = TradingExecutionEngine(config={})
        
        order = TradeOrder(
            order_id="order_123",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=1.0,
            price=45000.0
        )
        
        result = await engine._execute_dry_run(order)
        
        # Should be either filled or submitted
        assert result.status in [OrderStatus.FILLED, OrderStatus.SUBMITTED]
        assert result.venue == "dry_run"


class TestTradingExecutionEngineLive:
    """Test _execute_live method."""
    
    @pytest.mark.asyncio
    async def test_execute_live_falls_back_to_dry_run(self):
        """Test live execution falls back to dry-run."""
        engine = TradingExecutionEngine(config={"dry_run": False})
        
        order = TradeOrder(
            order_id="order_123",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0
        )
        
        result = await engine._execute_live(order)
        
        # Should fall back to dry-run
        assert result.venue == "dry_run"


class TestTradingExecutionEngineMockPrice:
    """Test _get_mock_price method."""
    
    def test_get_mock_price_known_symbol(self):
        """Test getting mock price for known symbol."""
        engine = TradingExecutionEngine(config={})
        
        price = engine._get_mock_price("BTCUSDT")
        
        # Should be approximately 45000 with small variation
        assert 44900 < price < 45100
    
    def test_get_mock_price_unknown_symbol(self):
        """Test getting mock price for unknown symbol."""
        engine = TradingExecutionEngine(config={})
        
        price = engine._get_mock_price("UNKNOWNUSDT")
        
        # Should default to approximately 1.0
        assert 0.99 < price < 1.01


class TestTradingExecutionEngineSymbolSupport:
    """Test _is_symbol_supported method."""
    
    def test_supported_symbol(self):
        """Test supported symbol returns True."""
        engine = TradingExecutionEngine(config={})
        
        assert engine._is_symbol_supported("BTCUSDT") is True
        assert engine._is_symbol_supported("ETHUSDT") is True
        assert engine._is_symbol_supported("SOLUSDT") is True
    
    def test_unsupported_symbol(self):
        """Test unsupported symbol returns False."""
        engine = TradingExecutionEngine(config={})
        
        assert engine._is_symbol_supported("UNKNOWNUSDT") is False
        assert engine._is_symbol_supported("") is False


class TestTradingExecutionEngineUpdatePosition:
    """Test _update_position method."""
    
    @pytest.mark.asyncio
    async def test_new_position(self):
        """Test creating new position."""
        engine = TradingExecutionEngine(config={})
        
        order = TradeOrder(
            order_id="order_123",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0
        )
        
        result = ExecutionResult(
            order_id="order_123",
            status=OrderStatus.FILLED,
            executed_quantity=1.0,
            executed_price=45000.0,
            execution_fee=45.0,
            timestamp=time.time(),
            venue="test"
        )
        
        await engine._update_position(order, result)
        
        assert "BTCUSDT" in engine._positions
        assert engine._positions["BTCUSDT"].size == 45000.0
    
    @pytest.mark.asyncio
    async def test_update_existing_position_buy(self):
        """Test updating existing position with buy."""
        engine = TradingExecutionEngine(config={})
        
        # Create initial position
        engine._positions["BTCUSDT"] = Position(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            size=45000.0,
            entry_price=45000.0,
            current_price=45000.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            timestamp=time.time(),
            venue="test"
        )
        
        order = TradeOrder(
            order_id="order_124",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0
        )
        
        result = ExecutionResult(
            order_id="order_124",
            status=OrderStatus.FILLED,
            executed_quantity=1.0,
            executed_price=46000.0,
            execution_fee=46.0,
            timestamp=time.time(),
            venue="test"
        )
        
        await engine._update_position(order, result)
        
        assert engine._positions["BTCUSDT"].size == 91000.0  # 45000 + 46000
    
    @pytest.mark.asyncio
    async def test_close_position(self):
        """Test closing position."""
        engine = TradingExecutionEngine(config={})
        
        # Create initial position
        engine._positions["BTCUSDT"] = Position(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            size=45000.0,
            entry_price=45000.0,
            current_price=45000.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            timestamp=time.time(),
            venue="test"
        )
        
        order = TradeOrder(
            order_id="order_125",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=1.0
        )
        
        result = ExecutionResult(
            order_id="order_125",
            status=OrderStatus.FILLED,
            executed_quantity=1.0,
            executed_price=45000.0,
            execution_fee=45.0,
            timestamp=time.time(),
            venue="test"
        )
        
        await engine._update_position(order, result)
        
        # Position should be removed (size < $1)
        assert "BTCUSDT" not in engine._positions
    
    @pytest.mark.asyncio
    async def test_update_position_not_filled(self):
        """Test no update when order not filled."""
        engine = TradingExecutionEngine(config={})
        
        order = TradeOrder(
            order_id="order_123",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=1.0,
            price=40000.0
        )
        
        result = ExecutionResult(
            order_id="order_123",
            status=OrderStatus.SUBMITTED,  # Not filled
            executed_quantity=0.0,
            executed_price=None,
            execution_fee=0.0,
            timestamp=time.time(),
            venue="test"
        )
        
        await engine._update_position(order, result)
        
        assert "BTCUSDT" not in engine._positions


class TestTradingExecutionEngineUpdateDailyPnl:
    """Test _update_daily_pnl method."""
    
    @pytest.mark.asyncio
    async def test_update_daily_pnl(self):
        """Test daily PnL is updated with fees."""
        engine = TradingExecutionEngine(config={})
        initial_pnl = engine._daily_pnl
        
        result = ExecutionResult(
            order_id="order_123",
            status=OrderStatus.FILLED,
            executed_quantity=1.0,
            executed_price=45000.0,
            execution_fee=45.0,
            timestamp=time.time(),
            venue="test"
        )
        
        await engine._update_daily_pnl(result)
        
        assert engine._daily_pnl == initial_pnl - 45.0
    
    @pytest.mark.asyncio
    async def test_daily_pnl_reset(self):
        """Test daily PnL reset after 24 hours."""
        engine = TradingExecutionEngine(config={})
        engine._daily_pnl = -1000.0
        engine._last_reset_time = time.time() - 90000  # > 24 hours ago
        
        result = ExecutionResult(
            order_id="order_123",
            status=OrderStatus.FILLED,
            executed_quantity=1.0,
            executed_price=45000.0,
            execution_fee=45.0,
            timestamp=time.time(),
            venue="test"
        )
        
        await engine._update_daily_pnl(result)
        
        # Should be reset then fee subtracted
        assert engine._daily_pnl == -45.0


class TestTradingExecutionEngineHelpers:
    """Test helper methods."""
    
    def test_create_rejected_result(self):
        """Test creating rejected result."""
        engine = TradingExecutionEngine(config={})
        
        order = TradeOrder(
            order_id="order_123",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0
        )
        
        result = engine._create_rejected_result(order, "Test rejection")
        
        assert result.status == OrderStatus.REJECTED
        assert result.error_message == "Test rejection"
        assert result.metadata.get("rejected") is True
    
    def test_create_failed_result(self):
        """Test creating failed result."""
        engine = TradingExecutionEngine(config={})
        
        order = TradeOrder(
            order_id="order_123",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0
        )
        
        result = engine._create_failed_result(order, "Test error")
        
        assert result.status == OrderStatus.FAILED
        assert result.error_message == "Test error"
        assert result.metadata.get("failed") is True


class TestTradingExecutionEngineQueries:
    """Test query methods."""
    
    def test_get_position(self):
        """Test getting position."""
        engine = TradingExecutionEngine(config={})
        
        engine._positions["BTCUSDT"] = Position(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            size=45000.0,
            entry_price=45000.0,
            current_price=45000.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            timestamp=time.time(),
            venue="test"
        )
        
        pos = engine.get_position("BTCUSDT")
        
        assert pos is not None
        assert pos.symbol == "BTCUSDT"
    
    def test_get_position_not_found(self):
        """Test getting nonexistent position."""
        engine = TradingExecutionEngine(config={})
        
        pos = engine.get_position("UNKNOWNUSDT")
        
        assert pos is None
    
    def test_get_all_positions(self):
        """Test getting all positions."""
        engine = TradingExecutionEngine(config={})
        
        engine._positions["BTCUSDT"] = Position(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            size=45000.0,
            entry_price=45000.0,
            current_price=45000.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            timestamp=time.time(),
            venue="test"
        )
        
        positions = engine.get_all_positions()
        
        assert "BTCUSDT" in positions
        assert len(positions) == 1
    
    def test_get_order_status(self):
        """Test getting order status."""
        engine = TradingExecutionEngine(config={})
        
        engine._executions["order_123"] = ExecutionResult(
            order_id="order_123",
            status=OrderStatus.FILLED,
            executed_quantity=1.0,
            executed_price=45000.0,
            execution_fee=45.0,
            timestamp=time.time(),
            venue="test"
        )
        
        result = engine.get_order_status("order_123")
        
        assert result is not None
        assert result.status == OrderStatus.FILLED
    
    def test_get_order_status_not_found(self):
        """Test getting nonexistent order status."""
        engine = TradingExecutionEngine(config={})
        
        result = engine.get_order_status("unknown_order")
        
        assert result is None
    
    def test_get_execution_metrics(self):
        """Test getting execution metrics."""
        engine = TradingExecutionEngine(config={})
        
        engine._executions["order_1"] = ExecutionResult(
            order_id="order_1",
            status=OrderStatus.FILLED,
            executed_quantity=1.0,
            executed_price=45000.0,
            execution_fee=45.0,
            timestamp=time.time(),
            venue="test"
        )
        engine._executions["order_2"] = ExecutionResult(
            order_id="order_2",
            status=OrderStatus.REJECTED,
            executed_quantity=0.0,
            executed_price=None,
            execution_fee=0.0,
            timestamp=time.time(),
            venue="test"
        )
        
        metrics = engine.get_execution_metrics()
        
        assert metrics["total_orders"] == 2
        assert metrics["filled_orders"] == 1
        assert metrics["fill_rate"] == 0.5
    
    def test_get_execution_metrics_empty(self):
        """Test getting metrics with no orders."""
        engine = TradingExecutionEngine(config={})
        
        metrics = engine.get_execution_metrics()
        
        assert metrics["total_orders"] == 0
        assert metrics["fill_rate"] == 0.0


class TestTradingExecutionEngineCancelOrder:
    """Test cancel_order method."""
    
    @pytest.mark.asyncio
    async def test_cancel_submitted_order(self):
        """Test cancelling submitted order."""
        engine = TradingExecutionEngine(config={})
        
        engine._executions["order_123"] = ExecutionResult(
            order_id="order_123",
            status=OrderStatus.SUBMITTED,
            executed_quantity=0.0,
            executed_price=None,
            execution_fee=0.0,
            timestamp=time.time(),
            venue="test"
        )
        
        result = await engine.cancel_order("order_123")
        
        assert result is True
        assert engine._executions["order_123"].status == OrderStatus.CANCELLED
    
    @pytest.mark.asyncio
    async def test_cancel_filled_order_fails(self):
        """Test cancelling filled order fails."""
        engine = TradingExecutionEngine(config={})
        
        engine._executions["order_123"] = ExecutionResult(
            order_id="order_123",
            status=OrderStatus.FILLED,
            executed_quantity=1.0,
            executed_price=45000.0,
            execution_fee=45.0,
            timestamp=time.time(),
            venue="test"
        )
        
        result = await engine.cancel_order("order_123")
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_cancel_unknown_order(self):
        """Test cancelling unknown order fails."""
        engine = TradingExecutionEngine(config={})
        
        result = await engine.cancel_order("unknown_order")
        
        assert result is False


class TestTradingExecutionEngineResetMetrics:
    """Test reset_daily_metrics method."""
    
    def test_reset_daily_metrics(self):
        """Test resetting daily metrics."""
        engine = TradingExecutionEngine(config={})
        engine._daily_pnl = -500.0
        
        engine.reset_daily_metrics()
        
        assert engine._daily_pnl == 0.0
