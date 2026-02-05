"""Comprehensive tests for trading/agents/execution_agent.py - Coverage improvement.

Focuses on testable components: enums, dataclasses, Order methods.
ExecutionAgent itself has import-time dependencies that make unit testing expensive.
"""

import pytest
import time

from trading.agents.execution_agent import (
    OrderType, OrderSide, OrderStatus, Order, TradeExecution,
)


# =============================================================================
# Enum Tests
# =============================================================================

class TestOrderType:
    """Test OrderType enum."""

    def test_all_values(self):
        assert OrderType.MARKET.value == "market"
        assert OrderType.LIMIT.value == "limit"
        assert OrderType.STOP_LOSS.value == "stop_loss"
        assert OrderType.TAKE_PROFIT.value == "take_profit"
        assert OrderType.TRAILING_STOP.value == "trailing_stop"

    def test_enum_count(self):
        assert len(OrderType) == 5


class TestOrderSide:
    """Test OrderSide enum."""

    def test_all_values(self):
        assert OrderSide.BUY.value == "buy"
        assert OrderSide.SELL.value == "sell"


class TestOrderStatus:
    """Test OrderStatus enum."""

    def test_all_values(self):
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.SUBMITTED.value == "submitted"
        assert OrderStatus.PARTIALLY_FILLED.value == "partially_filled"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.CANCELLED.value == "cancelled"
        assert OrderStatus.REJECTED.value == "rejected"

    def test_enum_count(self):
        assert len(OrderStatus) == 6


# =============================================================================
# Order Dataclass Tests
# =============================================================================

class TestOrder:
    """Test Order dataclass."""

    def test_order_creation(self):
        """Test Order creation with required fields."""
        order = Order(
            order_id="test_001",
            venue="binance",
            asset="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=100.0
        )
        assert order.order_id == "test_001"
        assert order.venue == "binance"
        assert order.side == OrderSide.BUY
        assert order.status == OrderStatus.PENDING

    def test_order_with_price(self):
        """Test Order with limit price."""
        order = Order(
            order_id="test_002",
            venue="coinbase",
            asset="ETH/USDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            size=50.0,
            price=3000.0
        )
        assert order.price == 3000.0
        assert order.order_type == OrderType.LIMIT

    def test_order_with_stop_price(self):
        """Test Order with stop price."""
        order = Order(
            order_id="test_003",
            venue="kraken",
            asset="SOL/USDT",
            side=OrderSide.SELL,
            order_type=OrderType.STOP_LOSS,
            size=200.0,
            stop_price=150.0
        )
        assert order.stop_price == 150.0
        assert order.order_type == OrderType.STOP_LOSS

    def test_order_execution_time_none(self):
        """Test execution_time_ms returns None when not filled."""
        order = Order(
            order_id="test_004",
            venue="binance",
            asset="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=100.0
        )
        assert order.execution_time_ms() is None

    def test_order_execution_time_calculated(self):
        """Test execution_time_ms calculation."""
        now = time.time()
        order = Order(
            order_id="test_005",
            venue="binance",
            asset="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=100.0,
            submitted_at=now,
            filled_at=now + 0.05  # 50ms later
        )
        exec_time = order.execution_time_ms()
        assert exec_time is not None
        assert exec_time == pytest.approx(50.0, rel=0.01)

    def test_order_defaults(self):
        """Test Order default values."""
        order = Order(
            order_id="test_006",
            venue="test",
            asset="TEST",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=10.0
        )
        assert order.price is None
        assert order.stop_price is None
        assert order.status == OrderStatus.PENDING
        assert order.submitted_at is None
        assert order.filled_at is None
        assert order.fill_price is None
        assert order.filled_size == 0.0
        assert order.fees == 0.0
        assert order.created_at > 0

    def test_order_status_transitions(self):
        """Test Order status can be modified."""
        order = Order(
            order_id="test_007",
            venue="test",
            asset="TEST",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=10.0
        )
        assert order.status == OrderStatus.PENDING
        
        order.status = OrderStatus.SUBMITTED
        assert order.status == OrderStatus.SUBMITTED
        
        order.status = OrderStatus.FILLED
        assert order.status == OrderStatus.FILLED


# =============================================================================
# Trade Execution Dataclass Tests
# =============================================================================

class TestTradeExecution:
    """Test TradeExecution dataclass."""

    def test_trade_execution_creation(self):
        """Test TradeExecution creation."""
        order = Order(
            order_id="order_123",
            venue="binance",
            asset="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=100.0
        )
        execution = TradeExecution(
            trade_id="trade_123",
            order=order,
            execution_time_ms=45.5,
            slippage_bps=3.2,
            expected_price=50000.0,
            actual_price=50016.0
        )
        
        assert execution.trade_id == "trade_123"
        assert execution.execution_time_ms == 45.5
        assert execution.slippage_bps == 3.2
        assert execution.pnl is None

    def test_trade_execution_with_pnl(self):
        """Test TradeExecution with PnL."""
        order = Order(
            order_id="order_124",
            venue="coinbase",
            asset="ETH/USDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            size=50.0,
            price=3000.0
        )
        execution = TradeExecution(
            trade_id="trade_124",
            order=order,
            execution_time_ms=30.0,
            slippage_bps=1.5,
            expected_price=3000.0,
            actual_price=2998.5,
            pnl=150.0
        )
        
        assert execution.pnl == 150.0
        assert execution.actual_price == 2998.5
