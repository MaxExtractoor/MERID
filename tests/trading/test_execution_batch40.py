"""Tests for trading execution module - Batch 40 Coverage."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import time

# Import from the package (which re-exports from the core module)
from trading.execution import (
    ExecutionMode,
    OrderSide,
    OrderType,
    OrderStatus,
    PositionSide,
    _is_abort_action,
    _is_high_threat,
    Order,
    Position,
    ExecutionConfig,
    ExecutionError,
    InsufficientFundsError,
    PositionLimitError,
    OrderRejectedError,
    ExecutionEngine,
)
from trading.execution.defense import DefenseAction, ThreatLevel


class TestExecutionMode:
    """Tests for ExecutionMode enum."""

    def test_mode_values(self):
        assert ExecutionMode.PAPER.value == "paper"
        assert ExecutionMode.LIVE.value == "live"
        assert ExecutionMode.DISABLED.value == "disabled"


class TestOrderSide:
    """Tests for OrderSide enum."""

    def test_side_values(self):
        assert OrderSide.BUY.value == "buy"
        assert OrderSide.SELL.value == "sell"


class TestOrderType:
    """Tests for OrderType enum."""

    def test_type_values(self):
        assert OrderType.MARKET.value == "market"
        assert OrderType.LIMIT.value == "limit"
        assert OrderType.STOP_LOSS.value == "stop_loss"
        assert OrderType.TAKE_PROFIT.value == "take_profit"


class TestOrderStatus:
    """Tests for OrderStatus enum."""

    def test_status_values(self):
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.SUBMITTED.value == "submitted"
        assert OrderStatus.PARTIAL.value == "partial"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.CANCELLED.value == "cancelled"
        assert OrderStatus.REJECTED.value == "rejected"
        assert OrderStatus.EXPIRED.value == "expired"


class TestPositionSide:
    """Tests for PositionSide enum."""

    def test_side_values(self):
        assert PositionSide.LONG.value == "long"
        assert PositionSide.SHORT.value == "short"
        assert PositionSide.FLAT.value == "flat"


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_is_abort_action_true(self):
        assert _is_abort_action(DefenseAction.ABORT) is True

    def test_is_abort_action_false(self):
        assert _is_abort_action(DefenseAction.PROCEED) is False
        assert _is_abort_action(DefenseAction.DELAY) is False

    def test_is_high_threat_true(self):
        assert _is_high_threat(ThreatLevel.HIGH) is True
        assert _is_high_threat(ThreatLevel.CRITICAL) is True

    def test_is_high_threat_false(self):
        assert _is_high_threat(ThreatLevel.LOW) is False
        assert _is_high_threat(ThreatLevel.MEDIUM) is False
        assert _is_high_threat(ThreatLevel.NONE) is False


class TestOrder:
    """Tests for Order dataclass."""

    @pytest.fixture
    def sample_order(self):
        return Order(
            order_id="order_123",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
        )

    def test_order_creation(self, sample_order):
        assert sample_order.order_id == "order_123"
        assert sample_order.symbol == "BTC/USDT"
        assert sample_order.side == OrderSide.BUY
        assert sample_order.order_type == OrderType.MARKET
        assert sample_order.quantity == 1.0
        assert sample_order.status == OrderStatus.PENDING

    def test_order_is_complete_filled(self, sample_order):
        sample_order.status = OrderStatus.FILLED
        assert sample_order.is_complete() is True

    def test_order_is_complete_cancelled(self, sample_order):
        sample_order.status = OrderStatus.CANCELLED
        assert sample_order.is_complete() is True

    def test_order_is_complete_pending(self, sample_order):
        sample_order.status = OrderStatus.PENDING
        assert sample_order.is_complete() is False


class TestPosition:
    """Tests for Position dataclass."""

    @pytest.fixture
    def long_position(self):
        return Position(
            position_id="pos_123",
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
        )

    @pytest.fixture
    def short_position(self):
        return Position(
            position_id="pos_456",
            symbol="BTC/USDT",
            side=PositionSide.SHORT,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
        )

    def test_position_creation(self, long_position):
        assert long_position.position_id == "pos_123"
        assert long_position.symbol == "BTC/USDT"
        assert long_position.side == PositionSide.LONG
        assert long_position.quantity == 1.0

    def test_update_pnl_long_profit(self, long_position):
        long_position.update_pnl(51000.0)
        assert long_position.unrealized_pnl == 1000.0
        assert long_position.current_price == 51000.0

    def test_update_pnl_long_loss(self, long_position):
        long_position.update_pnl(49000.0)
        assert long_position.unrealized_pnl == -1000.0

    def test_update_pnl_short_profit(self, short_position):
        short_position.update_pnl(49000.0)
        assert short_position.unrealized_pnl == 1000.0

    def test_check_stop_loss_long_triggered(self, long_position):
        long_position.stop_loss = 48000.0
        assert long_position.check_stop_loss(47000.0) is True

    def test_check_stop_loss_long_not_triggered(self, long_position):
        long_position.stop_loss = 48000.0
        assert long_position.check_stop_loss(49000.0) is False

    def test_check_take_profit_long_triggered(self, long_position):
        long_position.take_profit = 55000.0
        assert long_position.check_take_profit(56000.0) is True

    def test_check_take_profit_no_target(self, long_position):
        long_position.take_profit = None
        assert long_position.check_take_profit(60000.0) is False


class TestExecutionConfig:
    """Tests for ExecutionConfig dataclass."""

    def test_config_defaults(self):
        config = ExecutionConfig()
        assert config.mode == ExecutionMode.PAPER
        assert config.exchange == "coinbase"
        assert config.max_position_size_usd == 10000.0
        assert config.max_total_exposure_usd == 50000.0
        assert config.max_leverage == 3.0
        assert config.sandbox is True

    def test_config_custom_values(self):
        config = ExecutionConfig(
            mode=ExecutionMode.LIVE,
            exchange="binance",
            max_position_size_usd=50000.0,
        )
        assert config.mode == ExecutionMode.LIVE
        assert config.exchange == "binance"
        assert config.max_position_size_usd == 50000.0


class TestExceptions:
    """Tests for custom exceptions."""

    def test_execution_error(self):
        with pytest.raises(ExecutionError):
            raise ExecutionError("Test error")

    def test_insufficient_funds_error(self):
        with pytest.raises(InsufficientFundsError):
            raise InsufficientFundsError("Not enough funds")

    def test_position_limit_error(self):
        with pytest.raises(PositionLimitError):
            raise PositionLimitError("Position limit exceeded")

    def test_order_rejected_error(self):
        with pytest.raises(OrderRejectedError):
            raise OrderRejectedError("Order rejected")


class TestExecutionEngineBasics:
    """Basic tests for ExecutionEngine that don't require complex mocking."""

    @pytest.fixture
    def engine(self):
        # Patch at the source modules where these functions are imported from
        with patch('core.error_handling.get_error_handler') as mock_error_handler, \
             patch('core.state_recovery.get_state_manager') as mock_state_manager, \
             patch('core.state_recovery.get_self_healing') as mock_self_healing, \
             patch('core.error_handling.get_health_monitor') as mock_health_monitor:
            
            mock_error_handler.return_value.register_circuit_breaker = MagicMock(return_value=MagicMock())
            mock_state_manager.return_value = MagicMock()
            mock_self_healing.return_value = MagicMock()
            mock_health_monitor.return_value = MagicMock()
            
            config = ExecutionConfig(mode=ExecutionMode.PAPER)
            return ExecutionEngine(config)

    def test_initialization(self, engine):
        assert engine.config.mode == ExecutionMode.PAPER
        assert engine._balance == 100000.0
        assert engine._equity == 100000.0
        assert engine._running is False

    def test_resolve_execution_mode_paper(self, engine):
        mode = engine._resolve_execution_mode()
        assert mode == ExecutionMode.PAPER

    def test_resolve_execution_mode_live_no_credentials(self, engine):
        engine.config.mode = ExecutionMode.LIVE
        engine.config.api_key = None
        mode = engine._resolve_execution_mode()
        assert mode == ExecutionMode.PAPER

    def test_update_price(self, engine):
        engine.update_price("BTC/USDT", 51000.0)
        assert engine._price_cache["BTC/USDT"] == 51000.0

    def test_update_price_with_position(self, engine):
        position = Position(
            position_id="pos_123",
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
        )
        engine._positions["BTC/USDT"] = position
        engine.update_price("BTC/USDT", 51000.0)
        assert position.unrealized_pnl == 1000.0

    def test_get_position_exists(self, engine):
        position = Position(
            position_id="pos_123",
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
        )
        engine._positions["BTC/USDT"] = position
        assert engine.get_position("BTC/USDT") is position

    def test_get_position_not_exists(self, engine):
        assert engine.get_position("NONEXISTENT") is None

    def test_get_all_positions(self, engine):
        position = Position(
            position_id="pos_123",
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
        )
        engine._positions["BTC/USDT"] = position
        positions = engine.get_all_positions()
        assert len(positions) == 1
        assert positions[0] is position

    def test_get_order_exists(self, engine):
        order = Order(
            order_id="order_123",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
        )
        engine._orders["order_123"] = order
        assert engine.get_order("order_123") is order

    def test_get_order_not_exists(self, engine):
        assert engine.get_order("NONEXISTENT") is None

    def test_get_open_orders(self, engine):
        order1 = Order(
            order_id="order_1",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
            status=OrderStatus.PENDING,
        )
        order2 = Order(
            order_id="order_2",
            symbol="ETH/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
            status=OrderStatus.FILLED,
        )
        engine._orders["order_1"] = order1
        engine._orders["order_2"] = order2
        open_orders = engine.get_open_orders()
        assert len(open_orders) == 1
        assert open_orders[0].order_id == "order_1"

    def test_get_account_summary(self, engine):
        engine._balance = 50000.0
        engine._equity = 55000.0
        summary = engine.get_account_summary()
        assert summary["balance"] == 50000.0
        assert summary["equity"] == 55000.0
        assert summary["mode"] == "paper"

    def test_calculate_default_stop_long(self, engine):
        stop = engine._calculate_default_stop(50000.0, PositionSide.LONG)
        assert stop == 47500.0  # 5% below entry

    def test_calculate_default_stop_short(self, engine):
        stop = engine._calculate_default_stop(50000.0, PositionSide.SHORT)
        assert stop == 52500.0  # 5% above entry

    def test_calculate_default_target_long(self, engine):
        target = engine._calculate_default_target(50000.0, PositionSide.LONG)
        assert target == 55000.0  # 10% above entry

    def test_update_equity(self, engine):
        position = Position(
            position_id="pos_123",
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=51000.0,
            unrealized_pnl=1000.0,
        )
        engine._positions["BTC/USDT"] = position
        engine._balance = 100000.0
        engine._update_equity()
        assert engine._equity == 101000.0

    @pytest.mark.asyncio
    async def test_cancel_order_success(self, engine):
        order = Order(
            order_id="order_123",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
            status=OrderStatus.PENDING,
        )
        engine._orders["order_123"] = order
        result = await engine.cancel_order("order_123")
        assert result is True
        assert order.status == OrderStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_order_not_found(self, engine):
        result = await engine.cancel_order("NONEXISTENT")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_order_already_complete(self, engine):
        order = Order(
            order_id="order_123",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
            status=OrderStatus.FILLED,
        )
        engine._orders["order_123"] = order
        result = await engine.cancel_order("order_123")
        assert result is False
