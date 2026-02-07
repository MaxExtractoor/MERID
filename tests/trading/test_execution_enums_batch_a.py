"""Tests for trading/execution.py enums and dataclasses - Batch A."""
import pytest

from trading.execution import (
    ExecutionMode, OrderSide, OrderType, OrderStatus, PositionSide, Order
)


class TestExecutionModeEnum:
    """Tests for ExecutionMode enum."""

    def test_execution_mode_values(self):
        assert ExecutionMode.PAPER.value == "paper"
        assert ExecutionMode.LIVE.value == "live"
        assert ExecutionMode.DISABLED.value == "disabled"


class TestOrderSideEnum:
    """Tests for OrderSide enum."""

    def test_order_side_values(self):
        assert OrderSide.BUY.value == "buy"
        assert OrderSide.SELL.value == "sell"


class TestOrderTypeEnum:
    """Tests for OrderType enum."""

    def test_order_type_values(self):
        assert OrderType.MARKET.value == "market"
        assert OrderType.LIMIT.value == "limit"
        assert OrderType.STOP_LOSS.value == "stop_loss"
        assert OrderType.TAKE_PROFIT.value == "take_profit"


class TestOrderStatusEnum:
    """Tests for OrderStatus enum."""

    def test_order_status_values(self):
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.SUBMITTED.value == "submitted"
        assert OrderStatus.PARTIAL.value == "partial"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.CANCELLED.value == "cancelled"
        assert OrderStatus.REJECTED.value == "rejected"
        assert OrderStatus.EXPIRED.value == "expired"


class TestPositionSideEnum:
    """Tests for PositionSide enum."""

    def test_position_side_values(self):
        assert PositionSide.LONG.value == "long"
        assert PositionSide.SHORT.value == "short"
        assert PositionSide.FLAT.value == "flat"


class TestOrderDataclass:
    """Tests for Order dataclass."""

    def test_order_creation(self):
        order = Order(
            order_id="test_123",
            symbol="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0
        )
        assert order.order_id == "test_123"
        assert order.symbol == "BTC-USD"
        assert order.side == OrderSide.BUY
        assert order.order_type == OrderType.MARKET
        assert order.quantity == 1.0
        assert order.status == OrderStatus.PENDING
        assert order.filled_quantity == 0.0
        assert order.filled_price == 0.0

    def test_order_with_price(self):
        order = Order(
            order_id="test_456",
            symbol="ETH-USD",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=0.5,
            price=3500.0
        )
        assert order.price == 3500.0

    def test_order_with_stop_price(self):
        order = Order(
            order_id="test_789",
            symbol="BTC-USD",
            side=OrderSide.SELL,
            order_type=OrderType.STOP_LOSS,
            quantity=1.0,
            stop_price=40000.0
        )
        assert order.stop_price == 40000.0
