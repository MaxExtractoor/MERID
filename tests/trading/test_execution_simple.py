"""Simple tests for trading/execution.py - Coverage improvement.

Tests enums, dataclasses, and Position/Order methods without complex mocking.
"""

import pytest
import time

from trading.execution import (
    ExecutionMode, OrderSide, OrderType, OrderStatus, PositionSide,
    Order, Position, ExecutionConfig,
    ExecutionError, InsufficientFundsError, PositionLimitError, OrderRejectedError,
    _is_abort_action, _is_high_threat
)
from trading.execution.defense import DefenseAction, ThreatLevel


# =============================================================================
# Enum Tests
# =============================================================================

class TestExecutionMode:
    def test_paper(self):
        assert ExecutionMode.PAPER.value == "paper"

    def test_live(self):
        assert ExecutionMode.LIVE.value == "live"

    def test_disabled(self):
        assert ExecutionMode.DISABLED.value == "disabled"


class TestOrderSide:
    def test_buy(self):
        assert OrderSide.BUY.value == "buy"

    def test_sell(self):
        assert OrderSide.SELL.value == "sell"


class TestOrderType:
    def test_market(self):
        assert OrderType.MARKET.value == "market"

    def test_limit(self):
        assert OrderType.LIMIT.value == "limit"

    def test_stop_loss(self):
        assert OrderType.STOP_LOSS.value == "stop_loss"

    def test_take_profit(self):
        assert OrderType.TAKE_PROFIT.value == "take_profit"


class TestOrderStatus:
    def test_pending(self):
        assert OrderStatus.PENDING.value == "pending"

    def test_submitted(self):
        assert OrderStatus.SUBMITTED.value == "submitted"

    def test_partial(self):
        assert OrderStatus.PARTIAL.value == "partial"

    def test_filled(self):
        assert OrderStatus.FILLED.value == "filled"

    def test_cancelled(self):
        assert OrderStatus.CANCELLED.value == "cancelled"

    def test_rejected(self):
        assert OrderStatus.REJECTED.value == "rejected"

    def test_expired(self):
        assert OrderStatus.EXPIRED.value == "expired"


class TestPositionSide:
    def test_long(self):
        assert PositionSide.LONG.value == "long"

    def test_short(self):
        assert PositionSide.SHORT.value == "short"

    def test_flat(self):
        assert PositionSide.FLAT.value == "flat"


# =============================================================================
# Helper Function Tests
# =============================================================================

class TestHelperFunctions:
    def test_is_abort_action_abort(self):
        assert _is_abort_action(DefenseAction.ABORT) is True

    def test_is_abort_action_proceed(self):
        assert _is_abort_action(DefenseAction.PROCEED) is False

    def test_is_abort_action_delay(self):
        assert _is_abort_action(DefenseAction.DELAY) is False

    def test_is_high_threat_high(self):
        assert _is_high_threat(ThreatLevel.HIGH) is True

    def test_is_high_threat_critical(self):
        assert _is_high_threat(ThreatLevel.CRITICAL) is True

    def test_is_high_threat_low(self):
        assert _is_high_threat(ThreatLevel.LOW) is False

    def test_is_high_threat_medium(self):
        assert _is_high_threat(ThreatLevel.MEDIUM) is False


# =============================================================================
# Order Dataclass Tests
# =============================================================================

class TestOrder:
    def test_creation_minimal(self):
        order = Order(
            order_id="test_001",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1
        )
        assert order.order_id == "test_001"
        assert order.symbol == "BTC/USDT"
        assert order.side == OrderSide.BUY
        assert order.order_type == OrderType.MARKET
        assert order.quantity == 0.1
        assert order.status == OrderStatus.PENDING
        assert order.filled_quantity == 0.0

    def test_creation_full(self):
        order = Order(
            order_id="test_002",
            symbol="ETH/USDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=1.0,
            price=3000.0,
            stop_price=2900.0,
            status=OrderStatus.FILLED,
            filled_quantity=1.0,
            filled_price=3000.0,
            consensus_round_id="round_001",
            metadata={"strategy": "momentum"}
        )
        assert order.price == 3000.0
        assert order.stop_price == 2900.0

    def test_is_complete_pending(self):
        order = Order(
            order_id="test",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
            status=OrderStatus.PENDING
        )
        assert order.is_complete() is False

    def test_is_complete_submitted(self):
        order = Order(
            order_id="test",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
            status=OrderStatus.SUBMITTED
        )
        assert order.is_complete() is False

    def test_is_complete_partial(self):
        order = Order(
            order_id="test",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
            status=OrderStatus.PARTIAL
        )
        assert order.is_complete() is False

    def test_is_complete_filled(self):
        order = Order(
            order_id="test",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
            status=OrderStatus.FILLED
        )
        assert order.is_complete() is True

    def test_is_complete_cancelled(self):
        order = Order(
            order_id="test",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
            status=OrderStatus.CANCELLED
        )
        assert order.is_complete() is True

    def test_is_complete_rejected(self):
        order = Order(
            order_id="test",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
            status=OrderStatus.REJECTED
        )
        assert order.is_complete() is True

    def test_is_complete_expired(self):
        order = Order(
            order_id="test",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
            status=OrderStatus.EXPIRED
        )
        assert order.is_complete() is True


# =============================================================================
# Position Dataclass Tests
# =============================================================================

class TestPosition:
    def test_creation(self):
        position = Position(
            position_id="pos_001",
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            quantity=0.5,
            entry_price=50000.0,
            current_price=50000.0
        )
        assert position.position_id == "pos_001"
        assert position.unrealized_pnl == 0.0

    def test_update_pnl_long_profit(self):
        position = Position(
            position_id="pos_001",
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0
        )
        position.update_pnl(51000.0)
        assert position.current_price == 51000.0
        assert position.unrealized_pnl == 1000.0

    def test_update_pnl_long_loss(self):
        position = Position(
            position_id="pos_002",
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0
        )
        position.update_pnl(49000.0)
        assert position.unrealized_pnl == -1000.0

    def test_update_pnl_short_profit(self):
        position = Position(
            position_id="pos_003",
            symbol="BTC/USDT",
            side=PositionSide.SHORT,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0
        )
        position.update_pnl(49000.0)
        assert position.unrealized_pnl == 1000.0

    def test_update_pnl_short_loss(self):
        position = Position(
            position_id="pos_004",
            symbol="BTC/USDT",
            side=PositionSide.SHORT,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0
        )
        position.update_pnl(51000.0)
        assert position.unrealized_pnl == -1000.0

    def test_update_pnl_flat(self):
        position = Position(
            position_id="pos_005",
            symbol="BTC/USDT",
            side=PositionSide.FLAT,
            quantity=0.0,
            entry_price=50000.0,
            current_price=50000.0
        )
        position.update_pnl(55000.0)
        assert position.unrealized_pnl == 0.0

    def test_check_stop_loss_long_triggered(self):
        position = Position(
            position_id="pos_006",
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
            stop_loss=48000.0
        )
        assert position.check_stop_loss(47000.0) is True

    def test_check_stop_loss_long_not_triggered(self):
        position = Position(
            position_id="pos_007",
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
            stop_loss=48000.0
        )
        assert position.check_stop_loss(49000.0) is False

    def test_check_stop_loss_short_triggered(self):
        position = Position(
            position_id="pos_008",
            symbol="BTC/USDT",
            side=PositionSide.SHORT,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
            stop_loss=52000.0
        )
        assert position.check_stop_loss(53000.0) is True

    def test_check_stop_loss_short_not_triggered(self):
        position = Position(
            position_id="pos_009",
            symbol="BTC/USDT",
            side=PositionSide.SHORT,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
            stop_loss=52000.0
        )
        assert position.check_stop_loss(51000.0) is False

    def test_check_stop_loss_no_stop_set(self):
        position = Position(
            position_id="pos_010",
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0
        )
        assert position.check_stop_loss(40000.0) is False

    def test_check_stop_loss_flat_side(self):
        position = Position(
            position_id="pos_011",
            symbol="BTC/USDT",
            side=PositionSide.FLAT,
            quantity=0.0,
            entry_price=50000.0,
            current_price=50000.0,
            stop_loss=48000.0
        )
        assert position.check_stop_loss(40000.0) is False

    def test_check_take_profit_long_triggered(self):
        position = Position(
            position_id="pos_012",
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
            take_profit=55000.0
        )
        assert position.check_take_profit(56000.0) is True

    def test_check_take_profit_long_not_triggered(self):
        position = Position(
            position_id="pos_013",
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
            take_profit=55000.0
        )
        assert position.check_take_profit(54000.0) is False

    def test_check_take_profit_short_triggered(self):
        position = Position(
            position_id="pos_014",
            symbol="BTC/USDT",
            side=PositionSide.SHORT,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
            take_profit=45000.0
        )
        assert position.check_take_profit(44000.0) is True

    def test_check_take_profit_short_not_triggered(self):
        position = Position(
            position_id="pos_015",
            symbol="BTC/USDT",
            side=PositionSide.SHORT,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
            take_profit=45000.0
        )
        assert position.check_take_profit(46000.0) is False

    def test_check_take_profit_no_target_set(self):
        position = Position(
            position_id="pos_016",
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0
        )
        assert position.check_take_profit(100000.0) is False

    def test_check_take_profit_flat_side(self):
        position = Position(
            position_id="pos_017",
            symbol="BTC/USDT",
            side=PositionSide.FLAT,
            quantity=0.0,
            entry_price=50000.0,
            current_price=50000.0,
            take_profit=55000.0
        )
        assert position.check_take_profit(60000.0) is False


# =============================================================================
# ExecutionConfig Tests
# =============================================================================

class TestExecutionConfig:
    def test_defaults(self):
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
            api_key="test_key",
            api_secret="test_secret",
            max_position_size_usd=50000.0
        )
        assert config.mode == ExecutionMode.LIVE
        assert config.exchange == "binance"
        assert config.api_key == "test_key"
        assert config.max_position_size_usd == 50000.0


# =============================================================================
# Exception Tests
# =============================================================================

class TestExceptions:
    def test_execution_error(self):
        error = ExecutionError("Test error")
        assert "Test error" in str(error)
        assert isinstance(error, Exception)

    def test_insufficient_funds_error(self):
        error = InsufficientFundsError("No funds available")
        assert isinstance(error, ExecutionError)
        assert "No funds" in str(error)

    def test_position_limit_error(self):
        error = PositionLimitError("Position limit exceeded")
        assert isinstance(error, ExecutionError)
        assert "limit" in str(error)

    def test_order_rejected_error(self):
        error = OrderRejectedError("Order rejected by exchange")
        assert isinstance(error, ExecutionError)
        assert "rejected" in str(error)
