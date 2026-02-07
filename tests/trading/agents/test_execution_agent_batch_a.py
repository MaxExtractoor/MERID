"""Tests for trading/agents/execution_agent.py - Batch A simplified."""
import pytest
from decimal import Decimal

from trading.agents.execution_agent import (
    OrderType, OrderSide, OrderStatus, Order, TradeExecution
)


class TestOrderTypeEnum:
    """Tests for OrderType enum."""

    def test_order_type_values(self):
        assert OrderType.MARKET.value == "market"
        assert OrderType.LIMIT.value == "limit"
        assert OrderType.STOP_LOSS.value == "stop_loss"
        assert OrderType.TAKE_PROFIT.value == "take_profit"
        assert OrderType.TRAILING_STOP.value == "trailing_stop"


class TestOrderSideEnum:
    """Tests for OrderSide enum."""

    def test_order_side_values(self):
        assert OrderSide.BUY.value == "buy"
        assert OrderSide.SELL.value == "sell"


class TestOrderStatusEnum:
    """Tests for OrderStatus enum."""

    def test_order_status_values(self):
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.SUBMITTED.value == "submitted"
        assert OrderStatus.PARTIALLY_FILLED.value == "partially_filled"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.CANCELLED.value == "cancelled"
        assert OrderStatus.REJECTED.value == "rejected"


class TestOrderDataclass:
    """Tests for Order dataclass."""

    def test_order_creation(self):
        order = Order(
            order_id="test_123",
            venue="hyperliquid",
            asset="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=1.0
        )
        assert order.order_id == "test_123"
        assert order.venue == "hyperliquid"
        assert order.asset == "BTC-USD"
        assert order.side == OrderSide.BUY
        assert order.order_type == OrderType.MARKET
        assert order.size == 1.0
        assert order.status == OrderStatus.PENDING
        assert order.filled_size == 0.0
        assert order.fees == 0.0

    def test_order_with_price(self):
        order = Order(
            order_id="test_456",
            venue="hyperliquid",
            asset="ETH-USD",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            size=0.5,
            price=3500.0
        )
        assert order.price == 3500.0

    def test_order_with_stop_price(self):
        order = Order(
            order_id="test_789",
            venue="hyperliquid",
            asset="BTC-USD",
            side=OrderSide.SELL,
            order_type=OrderType.STOP_LOSS,
            size=1.0,
            stop_price=40000.0
        )
        assert order.stop_price == 40000.0

    def test_execution_time_ms_no_fill(self):
        order = Order(
            order_id="test_123",
            venue="hyperliquid",
            asset="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=1.0
        )
        assert order.execution_time_ms() is None

    def test_execution_time_ms_with_fill(self):
        import time
        order = Order(
            order_id="test_123",
            venue="hyperliquid",
            asset="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=1.0,
            submitted_at=time.time(),
            filled_at=time.time() + 0.1
        )
        exec_time = order.execution_time_ms()
        assert exec_time is not None
        assert exec_time > 0


class TestTradeExecutionDataclass:
    """Tests for TradeExecution dataclass."""

    def test_trade_execution_creation(self):
        order = Order(
            order_id="test_123",
            venue="hyperliquid",
            asset="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=1.0
        )
        trade = TradeExecution(
            trade_id="trade_456",
            order=order,
            execution_time_ms=150.0,
            slippage_bps=5.0,
            expected_price=50000.0,
            actual_price=50025.0
        )
        assert trade.trade_id == "trade_456"
        assert trade.order == order
        assert trade.execution_time_ms == 150.0
        assert trade.slippage_bps == 5.0
        assert trade.expected_price == 50000.0
        assert trade.actual_price == 50025.0
        assert trade.pnl is None

    def test_trade_execution_with_pnl(self):
        order = Order(
            order_id="test_123",
            venue="hyperliquid",
            asset="BTC-USD",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            size=1.0,
            price=51000.0
        )
        trade = TradeExecution(
            trade_id="trade_789",
            order=order,
            execution_time_ms=200.0,
            slippage_bps=3.0,
            expected_price=51000.0,
            actual_price=51015.0,
            pnl=100.0
        )
        assert trade.pnl == 100.0
