"""Tests for trading agents execution_agent module - Batch 33 Coverage."""
import pytest
from unittest.mock import MagicMock, patch
import time

from trading.agents.execution_agent import (
    OrderType,
    OrderSide,
    OrderStatus,
    Order,
    TradeExecution,
)


class TestEnums:
    """Tests for execution agent enums."""

    def test_order_type_values(self):
        assert OrderType.MARKET.value == "market"
        assert OrderType.LIMIT.value == "limit"
        assert OrderType.STOP_LOSS.value == "stop_loss"
        assert OrderType.TAKE_PROFIT.value == "take_profit"
        assert OrderType.TRAILING_STOP.value == "trailing_stop"

    def test_order_side_values(self):
        assert OrderSide.BUY.value == "buy"
        assert OrderSide.SELL.value == "sell"

    def test_order_status_values(self):
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.SUBMITTED.value == "submitted"
        assert OrderStatus.PARTIALLY_FILLED.value == "partially_filled"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.CANCELLED.value == "cancelled"
        assert OrderStatus.REJECTED.value == "rejected"


class TestOrder:
    """Tests for Order dataclass."""

    @pytest.fixture
    def sample_order(self):
        return Order(
            order_id="order_123",
            venue="hyperliquid",
            asset="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=1.0,
            price=50000.0,
        )

    def test_order_creation(self, sample_order):
        assert sample_order.order_id == "order_123"
        assert sample_order.venue == "hyperliquid"
        assert sample_order.asset == "BTC/USD"
        assert sample_order.side == OrderSide.BUY
        assert sample_order.status == OrderStatus.PENDING
        assert sample_order.filled_size == 0.0
        assert sample_order.fees == 0.0

    def test_execution_time_not_filled(self, sample_order):
        assert sample_order.execution_time_ms() is None

    def test_execution_time_filled(self, sample_order):
        sample_order.submitted_at = time.time()
        sample_order.filled_at = sample_order.submitted_at + 0.5
        exec_time = sample_order.execution_time_ms()
        assert exec_time is not None
        assert exec_time > 0

    def test_order_default_timestamps(self, sample_order):
        assert sample_order.created_at > 0


class TestTradeExecution:
    """Tests for TradeExecution dataclass."""

    def test_trade_execution_creation(self):
        order = Order(
            order_id="order_123",
            venue="hyperliquid",
            asset="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=1.0,
        )
        execution = TradeExecution(
            trade_id="trade_123",
            order=order,
            execution_time_ms=150.0,
            slippage_bps=5.0,
            expected_price=50000.0,
            actual_price=50002.5,
        )
        assert execution.trade_id == "trade_123"
        assert execution.execution_time_ms == 150.0
        assert execution.slippage_bps == 5.0
        assert execution.expected_price == 50000.0
        assert execution.actual_price == 50002.5
        assert execution.pnl is None

    def test_trade_execution_with_pnl(self):
        order = Order(
            order_id="order_123",
            venue="hyperliquid",
            asset="BTC/USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=1.0,
        )
        execution = TradeExecution(
            trade_id="trade_123",
            order=order,
            execution_time_ms=150.0,
            slippage_bps=5.0,
            expected_price=50000.0,
            actual_price=50002.5,
            pnl=100.0,
        )
        assert execution.pnl == 100.0
