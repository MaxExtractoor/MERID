"""Tests for trading/agents/execution_agent.py - Batch 90."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from trading.agents.execution_agent import (
    OrderType, OrderSide, OrderStatus, Order
)


class TestOrderType:
    """Tests for OrderType enum."""

    def test_market_value(self):
        assert OrderType.MARKET.value == "market"

    def test_limit_value(self):
        assert OrderType.LIMIT.value == "limit"

    def test_stop_loss_value(self):
        assert OrderType.STOP_LOSS.value == "stop_loss"


class TestOrderSide:
    """Tests for OrderSide enum."""

    def test_buy_value(self):
        assert OrderSide.BUY.value == "buy"

    def test_sell_value(self):
        assert OrderSide.SELL.value == "sell"


class TestOrderStatus:
    """Tests for OrderStatus enum."""

    def test_pending_value(self):
        assert OrderStatus.PENDING.value == "pending"

    def test_filled_value(self):
        assert OrderStatus.FILLED.value == "filled"

    def test_cancelled_value(self):
        assert OrderStatus.CANCELLED.value == "cancelled"


class TestOrder:
    """Tests for Order dataclass."""

    def test_order_creation(self):
        order = Order(
            order_id="order123",
            venue="binance",
            asset="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=1.0
        )
        assert order.order_id == "order123"
        assert order.venue == "binance"
        assert order.size == 1.0
        assert order.status == OrderStatus.PENDING

    def test_execution_time_ms_not_filled(self):
        order = Order(
            order_id="order123",
            venue="binance",
            asset="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=1.0
        )
        assert order.execution_time_ms() is None

    def test_execution_time_ms_filled(self):
        order = Order(
            order_id="order123",
            venue="binance",
            asset="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=1.0,
            submitted_at=1000.0,
            filled_at=1001.5
        )
        assert order.execution_time_ms() == 1500.0
