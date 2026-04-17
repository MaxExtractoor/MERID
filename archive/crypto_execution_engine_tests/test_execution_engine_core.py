"""Core tests for trading/execution.py ExecutionEngine internals.

Focuses on pure methods and state management without async collaborator mocking.
Complements test_execution_simple.py with ExecutionEngine-specific tests.
"""

import pytest
from unittest.mock import MagicMock

from trading.execution import (
    ExecutionConfig, ExecutionMode,
    Order, OrderSide, OrderType, OrderStatus,
    Position, PositionSide,
    ExecutionError, PositionLimitError, InsufficientFundsError
)


# =============================================================================
# ExecutionConfig Tests - Extended
# =============================================================================

class TestExecutionConfigExtended:
    """Extended ExecutionConfig tests."""

    def test_live_mode_config(self):
        config = ExecutionConfig(
            mode=ExecutionMode.LIVE,
            exchange="binance",
            api_key="test_api_key",
            api_secret="test_api_secret",
            sandbox=False
        )
        assert config.mode == ExecutionMode.LIVE
        assert config.api_key == "test_api_key"
        assert config.sandbox is False

    def test_disabled_mode_config(self):
        config = ExecutionConfig(mode=ExecutionMode.DISABLED)
        assert config.mode == ExecutionMode.DISABLED


# =============================================================================
# Order State Tests
# =============================================================================

class TestOrderStates:
    """Test Order state transitions and attributes."""

    def test_order_with_stop_price(self):
        order = Order(
            order_id="order_001",
            symbol="BTC/USDT",
            side=OrderSide.SELL,
            order_type=OrderType.STOP_LOSS,
            quantity=0.5,
            stop_price=45000.0
        )
        assert order.stop_price == 45000.0
        assert order.order_type == OrderType.STOP_LOSS

    def test_order_with_metadata(self):
        order = Order(
            order_id="order_002",
            symbol="ETH/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
            metadata={"strategy_id": "momentum_v1", "signal_strength": 0.85}
        )
        assert order.metadata["strategy_id"] == "momentum_v1"
        assert order.metadata["signal_strength"] == 0.85

    def test_order_fill_attributes(self):
        order = Order(
            order_id="order_003",
            symbol="SOL/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=10.0,
            price=150.0,
            status=OrderStatus.FILLED,
            filled_quantity=10.0,
            filled_price=149.5
        )
        assert order.filled_quantity == 10.0
        assert order.filled_price == 149.5


# =============================================================================
# Position State Tests
# =============================================================================

class TestPositionStates:
    """Test Position state calculations."""

    def test_position_with_stop_loss_and_take_profit(self):
        position = Position(
            position_id="pos_001",
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
            stop_loss=47500.0,
            take_profit=55000.0
        )
        assert position.stop_loss == 47500.0
        assert position.take_profit == 55000.0

    def test_position_pnl_calculation_long_profit(self):
        position = Position(
            position_id="pos_002",
            symbol="ETH/USDT",
            side=PositionSide.LONG,
            quantity=10.0,
            entry_price=3000.0,
            current_price=3000.0
        )
        position.update_pnl(3200.0)
        # 10 * (3200 - 3000) = 2000
        assert position.unrealized_pnl == 2000.0

    def test_position_pnl_calculation_short_profit(self):
        position = Position(
            position_id="pos_003",
            symbol="ETH/USDT",
            side=PositionSide.SHORT,
            quantity=10.0,
            entry_price=3000.0,
            current_price=3000.0
        )
        position.update_pnl(2800.0)
        # 10 * (3000 - 2800) = 2000
        assert position.unrealized_pnl == 2000.0

    def test_position_stop_loss_edge_case_exact_price(self):
        position = Position(
            position_id="pos_004",
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
            stop_loss=48000.0
        )
        # At exactly stop price
        assert position.check_stop_loss(48000.0) is True

    def test_position_take_profit_edge_case_exact_price(self):
        position = Position(
            position_id="pos_005",
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
            take_profit=55000.0
        )
        # At exactly take profit price
        assert position.check_take_profit(55000.0) is True

    def test_position_metadata(self):
        position = Position(
            position_id="pos_006",
            symbol="AAPL",
            side=PositionSide.LONG,
            quantity=100.0,
            entry_price=150.0,
            current_price=150.0,
            metadata={"strategy": "value", "sector": "tech"}
        )
        assert position.metadata["strategy"] == "value"


# =============================================================================
# Order Status Completeness Tests
# =============================================================================

class TestOrderStatusComplete:
    """Test all OrderStatus values for is_complete()."""

    @pytest.mark.parametrize("status,expected", [
        (OrderStatus.PENDING, False),
        (OrderStatus.SUBMITTED, False),
        (OrderStatus.PARTIAL, False),
        (OrderStatus.FILLED, True),
        (OrderStatus.CANCELLED, True),
        (OrderStatus.REJECTED, True),
        (OrderStatus.EXPIRED, True),
    ])
    def test_is_complete_parametrized(self, status, expected):
        order = Order(
            order_id="test",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
            status=status
        )
        assert order.is_complete() is expected


# =============================================================================
# Position Side Tests
# =============================================================================

class TestPositionSideLogic:
    """Test position side-specific logic."""

    def test_long_stop_loss_below_entry(self):
        """Long positions should trigger stop loss when price falls below stop."""
        position = Position(
            position_id="pos_long",
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
            stop_loss=48000.0
        )
        # Price above stop - not triggered
        assert position.check_stop_loss(49000.0) is False
        # Price at stop - triggered
        assert position.check_stop_loss(48000.0) is True
        # Price below stop - triggered
        assert position.check_stop_loss(47000.0) is True

    def test_short_stop_loss_above_entry(self):
        """Short positions should trigger stop loss when price rises above stop."""
        position = Position(
            position_id="pos_short",
            symbol="BTC/USDT",
            side=PositionSide.SHORT,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
            stop_loss=52000.0
        )
        # Price below stop - not triggered
        assert position.check_stop_loss(51000.0) is False
        # Price at stop - triggered
        assert position.check_stop_loss(52000.0) is True
        # Price above stop - triggered
        assert position.check_stop_loss(53000.0) is True

    def test_long_take_profit_above_entry(self):
        """Long positions should trigger take profit when price rises above target."""
        position = Position(
            position_id="pos_long_tp",
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
            take_profit=55000.0
        )
        # Price below target - not triggered
        assert position.check_take_profit(54000.0) is False
        # Price at target - triggered
        assert position.check_take_profit(55000.0) is True
        # Price above target - triggered
        assert position.check_take_profit(56000.0) is True

    def test_short_take_profit_below_entry(self):
        """Short positions should trigger take profit when price falls below target."""
        position = Position(
            position_id="pos_short_tp",
            symbol="BTC/USDT",
            side=PositionSide.SHORT,
            quantity=1.0,
            entry_price=50000.0,
            current_price=50000.0,
            take_profit=45000.0
        )
        # Price above target - not triggered
        assert position.check_take_profit(46000.0) is False
        # Price at target - triggered
        assert position.check_take_profit(45000.0) is True
        # Price below target - triggered
        assert position.check_take_profit(44000.0) is True


# =============================================================================
# Exception Message Tests
# =============================================================================

class TestExceptionMessages:
    """Test exception classes preserve messages."""

    def test_execution_error_message(self):
        try:
            raise ExecutionError("Order failed: connection timeout")
        except ExecutionError as e:
            assert "connection timeout" in str(e)

    def test_position_limit_error_message(self):
        try:
            raise PositionLimitError("Max exposure 50000 USD exceeded")
        except PositionLimitError as e:
            assert "50000" in str(e)

    def test_insufficient_funds_error_message(self):
        try:
            raise InsufficientFundsError("Balance 1000 < required 5000")
        except InsufficientFundsError as e:
            assert "Balance" in str(e)


# =============================================================================
# Order Type Tests
# =============================================================================

class TestOrderTypes:
    """Test different order type configurations."""

    def test_limit_order_requires_price(self):
        order = Order(
            order_id="limit_001",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=0.5,
            price=48000.0
        )
        assert order.price == 48000.0
        assert order.order_type == OrderType.LIMIT

    def test_take_profit_order(self):
        order = Order(
            order_id="tp_001",
            symbol="ETH/USDT",
            side=OrderSide.SELL,
            order_type=OrderType.TAKE_PROFIT,
            quantity=10.0,
            price=3500.0
        )
        assert order.order_type == OrderType.TAKE_PROFIT


# =============================================================================
# Position Quantity Tests
# =============================================================================

class TestPositionQuantity:
    """Test position quantity edge cases."""

    def test_zero_quantity_pnl(self):
        """Zero quantity should result in zero PnL."""
        position = Position(
            position_id="pos_zero",
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            quantity=0.0,
            entry_price=50000.0,
            current_price=50000.0
        )
        position.update_pnl(60000.0)
        assert position.unrealized_pnl == 0.0

    def test_fractional_quantity(self):
        """Fractional quantities should work correctly."""
        position = Position(
            position_id="pos_frac",
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            quantity=0.001,
            entry_price=50000.0,
            current_price=50000.0
        )
        position.update_pnl(51000.0)
        # 0.001 * (51000 - 50000) = 1.0
        assert position.unrealized_pnl == pytest.approx(1.0)
