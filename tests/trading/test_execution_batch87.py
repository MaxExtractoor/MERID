"""Tests for trading/execution.py - Batch 87."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from trading.execution import (
    ExecutionMode, OrderSide, OrderType
)


class TestExecutionMode:
    """Tests for ExecutionMode enum."""

    def test_paper_value(self):
        assert ExecutionMode.PAPER.value == "paper"

    def test_live_value(self):
        assert ExecutionMode.LIVE.value == "live"

    def test_disabled_value(self):
        assert ExecutionMode.DISABLED.value == "disabled"


class TestOrderSide:
    """Tests for OrderSide enum."""

    def test_buy_value(self):
        assert OrderSide.BUY.value == "buy"

    def test_sell_value(self):
        assert OrderSide.SELL.value == "sell"


class TestOrderType:
    """Tests for OrderType enum."""

    def test_market_value(self):
        assert OrderType.MARKET.value == "market"

    def test_limit_value(self):
        assert OrderType.LIMIT.value == "limit"

    def test_stop_loss_value(self):
        assert OrderType.STOP_LOSS.value == "stop_loss"
