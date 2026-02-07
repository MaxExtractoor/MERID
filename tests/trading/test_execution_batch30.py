"""Tests for trading execution module - Batch 30 Coverage."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import time

from trading.execution import (
    ExecutionMode,
    OrderSide,
    OrderType,
    OrderStatus,
    PositionSide,
    Order,
    Position,
    ExecutionConfig,
    ExecutionError,
    InsufficientFundsError,
    PositionLimitError,
    OrderRejectedError,
    ExecutionEngine,
    _is_abort_action,
    _is_high_threat,
)
from trading.execution.defense import DefenseAction, ThreatLevel


class TestEnums:
    """Tests for execution enums."""

    def test_execution_mode_values(self):
        assert ExecutionMode.PAPER.value == "paper"
        assert ExecutionMode.LIVE.value == "live"
        assert ExecutionMode.DISABLED.value == "disabled"

    def test_order_side_values(self):
        assert OrderSide.BUY.value == "buy"
        assert OrderSide.SELL.value == "sell"

    def test_order_type_values(self):
        assert OrderType.MARKET.value == "market"
        assert OrderType.LIMIT.value == "limit"
        assert OrderType.STOP_LOSS.value == "stop_loss"
        assert OrderType.TAKE_PROFIT.value == "take_profit"

    def test_order_status_values(self):
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.SUBMITTED.value == "submitted"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.CANCELLED.value == "cancelled"
        assert OrderStatus.REJECTED.value == "rejected"
        assert OrderStatus.EXPIRED.value == "expired"

    def test_position_side_values(self):
        assert PositionSide.LONG.value == "long"
        assert PositionSide.SHORT.value == "short"
        assert PositionSide.FLAT.value == "flat"


class TestHelperFunctions:
    """Tests for module helper functions."""

    def test_is_abort_action(self):
        assert _is_abort_action(DefenseAction.ABORT) is True
        assert _is_abort_action(DefenseAction.PROCEED) is False
        assert _is_abort_action(DefenseAction.DELAY) is False

    def test_is_high_threat(self):
        assert _is_high_threat(ThreatLevel.HIGH) is True
        assert _is_high_threat(ThreatLevel.CRITICAL) is True
        assert _is_high_threat(ThreatLevel.LOW) is False
        assert _is_high_threat(ThreatLevel.MEDIUM) is False


class TestOrder:
    """Tests for Order dataclass."""

    @pytest.fixture
    def sample_order(self):
        return Order(
            order_id="order_123",
            symbol="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
            price=50000.0,
        )

    def test_order_creation(self, sample_order):
        assert sample_order.order_id == "order_123"
        assert sample_order.symbol == "BTC/USD"
        assert sample_order.side == OrderSide.BUY
        assert sample_order.quantity == 1.0
        assert sample_order.status == OrderStatus.PENDING

    def test_order_is_complete_filled(self, sample_order):
        sample_order.status = OrderStatus.FILLED
        assert sample_order.is_complete() is True

    def test_order_is_complete_cancelled(self, sample_order):
        sample_order.status = OrderStatus.CANCELLED
        assert sample_order.is_complete() is True

    def test_order_is_complete_rejected(self, sample_order):
        sample_order.status = OrderStatus.REJECTED
        assert sample_order.is_complete() is True

    def test_order_is_complete_expired(self, sample_order):
        sample_order.status = OrderStatus.EXPIRED
        assert sample_order.is_complete() is True

    def test_order_is_complete_pending(self, sample_order):
        sample_order.status = OrderStatus.PENDING
        assert sample_order.is_complete() is False

    def test_order_is_complete_submitted(self, sample_order):
        sample_order.status = OrderStatus.SUBMITTED
        assert sample_order.is_complete() is False

    def test_order_default_timestamps(self, sample_order):
        assert sample_order.created_at > 0
        assert sample_order.updated_at > 0


class TestPosition:
    """Tests for Position dataclass."""

    @pytest.fixture
    def long_position(self):
        return Position(
            position_id="pos_123",
            symbol="BTC/USD",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
        )

    @pytest.fixture
    def short_position(self):
        return Position(
            position_id="pos_456",
            symbol="BTC/USD",
            side=PositionSide.SHORT,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
        )

    def test_position_creation(self, long_position):
        assert long_position.position_id == "pos_123"
        assert long_position.symbol == "BTC/USD"
        assert long_position.side == PositionSide.LONG
        assert long_position.quantity == 1.0
        assert long_position.unrealized_pnl == 0.0

    def test_update_pnl_long_profit(self, long_position):
        long_position.update_pnl(55000.0)
        assert long_position.unrealized_pnl == 5000.0  # (55000 - 50000) * 1
        assert long_position.current_price == 55000.0

    def test_update_pnl_long_loss(self, long_position):
        long_position.update_pnl(45000.0)
        assert long_position.unrealized_pnl == -5000.0  # (45000 - 50000) * 1

    def test_update_pnl_short_profit(self, short_position):
        short_position.update_pnl(45000.0)
        assert short_position.unrealized_pnl == 5000.0  # (50000 - 45000) * 1

    def test_update_pnl_short_loss(self, short_position):
        short_position.update_pnl(55000.0)
        assert short_position.unrealized_pnl == -5000.0  # (50000 - 55000) * 1

    def test_update_pnl_flat(self):
        flat_position = Position(
            position_id="pos_789",
            symbol="BTC/USD",
            side=PositionSide.FLAT,
            quantity=0.0,
            entry_price=0.0,
            current_price=0.0,
        )
        flat_position.update_pnl(55000.0)
        assert flat_position.unrealized_pnl == 0.0

    def test_check_stop_loss_long_triggered(self, long_position):
        long_position.stop_loss = 48000.0
        assert long_position.check_stop_loss(47000.0) is True
        assert long_position.check_stop_loss(49000.0) is False

    def test_check_stop_loss_short_triggered(self, short_position):
        short_position.stop_loss = 52000.0
        assert short_position.check_stop_loss(53000.0) is True
        assert short_position.check_stop_loss(51000.0) is False

    def test_check_stop_loss_none(self, long_position):
        assert long_position.check_stop_loss(40000.0) is False

    def test_check_take_profit_long_triggered(self, long_position):
        long_position.take_profit = 55000.0
        assert long_position.check_take_profit(56000.0) is True
        assert long_position.check_take_profit(54000.0) is False

    def test_check_take_profit_short_triggered(self, short_position):
        short_position.take_profit = 45000.0
        assert short_position.check_take_profit(44000.0) is True
        assert short_position.check_take_profit(46000.0) is False

    def test_check_take_profit_none(self, long_position):
        assert long_position.check_take_profit(60000.0) is False


class TestExecutionConfig:
    """Tests for ExecutionConfig dataclass."""

    def test_default_config(self):
        config = ExecutionConfig()
        assert config.mode == ExecutionMode.PAPER
        assert config.exchange == "coinbase"
        assert config.sandbox is True
        assert config.max_position_size_usd == 10000.0
        assert config.max_total_exposure_usd == 50000.0
        assert config.max_leverage == 3.0
        assert config.default_stop_loss_pct == 0.05
        assert config.default_take_profit_pct == 0.10
        assert config.slippage_tolerance_pct == 0.005
        assert config.order_timeout_seconds == 60.0
        assert config.require_consensus is True
        assert config.min_consensus_confidence == 0.6

    def test_custom_config(self):
        config = ExecutionConfig(
            mode=ExecutionMode.LIVE,
            exchange="binance",
            max_position_size_usd=50000.0,
            require_consensus=False,
        )
        assert config.mode == ExecutionMode.LIVE
        assert config.exchange == "binance"
        assert config.max_position_size_usd == 50000.0
        assert config.require_consensus is False


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
            raise PositionLimitError("Position too large")

    def test_order_rejected_error(self):
        with pytest.raises(OrderRejectedError):
            raise OrderRejectedError("Order rejected")

    def test_exception_inheritance(self):
        assert issubclass(InsufficientFundsError, ExecutionError)
        assert issubclass(PositionLimitError, ExecutionError)
        assert issubclass(OrderRejectedError, ExecutionError)
