"""Unit tests for the TradeExecutor ABC and concrete executors."""

from __future__ import annotations

import pytest

from merid.execution.base import TradeExecutor
from merid.execution.executors import CoinbaseExecutor, JupiterExecutor


def test_trade_executor_is_abstract():
    with pytest.raises(TypeError):
        TradeExecutor()


def test_concrete_executors_instantiate():
    CoinbaseExecutor()
    JupiterExecutor()


@pytest.mark.asyncio
async def test_concrete_executors_raise_not_implemented():
    executors = [CoinbaseExecutor(), JupiterExecutor()]
    for executor in executors:
        with pytest.raises(NotImplementedError):
            await executor.get_quote("BTC-USDT", "buy", 0.1)
        with pytest.raises(NotImplementedError):
            await executor.execute_trade("BTC-USDT", "buy", 0.1)
        with pytest.raises(NotImplementedError):
            await executor.get_positions()
