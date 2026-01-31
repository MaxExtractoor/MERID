"""Unit tests for the new ExecutionRouter."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from merid.execution.base import TradeResult, TradeSideLiteral
from merid.execution.router import ExecutionRouter, TraderIdentity


@pytest.fixture
def mock_executor():
    executor = MagicMock()
    executor.execute_trade = AsyncMock(return_value=TradeResult(
        success=True,
        venue="test",
        symbol="BTC-USDT",
        side="buy",
        size=0.1,
        price=50000.0,
    ))
    return executor


@pytest.fixture
def router(mock_executor):
    return ExecutionRouter(executors={"test": mock_executor})


@pytest.mark.asyncio
async def test_router_submit_trade_success(router, mock_executor):
    trader = TraderIdentity(trader_type="human", trader_id="test-user")
    result = await router.submit_trade(
        trader=trader,
        venue_id="test",
        symbol="BTC-USDT",
        side="buy",
        size=0.1,
        price=50000.0,
    )
    assert result.success is True
    assert result.venue == "test"
    mock_executor.execute_trade.assert_called_once()


@pytest.mark.asyncio
async def test_router_submit_trade_missing_executor():
    router = ExecutionRouter()
    trader = TraderIdentity(trader_type="human", trader_id="test-user")
    with pytest.raises(RuntimeError, match="No executor registered"):
        await router.submit_trade(
            trader=trader,
            venue_id="unknown",
            symbol="BTC-USDT",
            side="buy",
            size=0.1,
        )
