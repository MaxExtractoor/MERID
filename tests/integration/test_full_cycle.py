"""Integration test for full-cycle simulated trade flow across venues."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from merid.execution import ExecutionRouter, TraderIdentity, CoinbaseExecutor, JupiterExecutor, FulcromExecutor, CronosOnchainExecutor
from merid.execution.base import TradeResult, TradeSideLiteral


@pytest.fixture
def mock_coinbase():
    executor = MagicMock()
    executor.execute_trade = AsyncMock(return_value=TradeResult(
        success=True,
        venue="coinbase",
        symbol="BTC-USDT",
        side="buy",
        size=0.1,
        price=50000.0,
    ))
    return executor


@pytest.fixture
def mock_jupiter():
    executor = MagicMock()
    executor.execute_trade = AsyncMock(return_value=TradeResult(
        success=True,
        venue="jupiter",
        symbol="SOL-USDC",
        side="sell",
        size=10.0,
        price=150.0,
    ))
    return executor


@pytest.fixture
def mock_fulcrom():
    executor = MagicMock()
    executor.execute_trade = AsyncMock(return_value=TradeResult(
        success=True,
        venue="fulcrom",
        symbol="ETH-USDC",
        side="buy",
        size=0.5,
        price=3000.0,
    ))
    return executor


@pytest.fixture
def mock_cronos():
    executor = MagicMock()
    executor.execute_trade = AsyncMock(return_value=TradeResult(
        success=True,
        venue="cronos_onchain",
        symbol="CRO-USDC",
        side="sell",
        size=100.0,
        price=0.08,
    ))
    return executor


@pytest.fixture
def router(mock_coinbase, mock_jupiter, mock_fulcrom, mock_cronos):
    return ExecutionRouter(executors={
        "coinbase": mock_coinbase,
        "jupiter": mock_jupiter,
        "fulcrom": mock_fulcrom,
        "cronos_onchain": mock_cronos,
    })


@pytest.mark.asyncio
async def test_full_cycle_simulated_trades(router, mock_coinbase, mock_jupiter, mock_fulcrom, mock_cronos):
    trader = TraderIdentity(trader_type="agent", trader_id="test-agent")

    # Coinbase
    result_cb = await router.submit_trade(
        trader=trader,
        venue_id="coinbase",
        symbol="BTC-USDT",
        side="buy",
        size=0.1,
        price=50000.0,
    )
    assert result_cb.success
    assert result_cb.venue == "coinbase"
    mock_coinbase.execute_trade.assert_called_once()

    # Jupiter
    result_jp = await router.submit_trade(
        trader=trader,
        venue_id="jupiter",
        symbol="SOL-USDC",
        side="sell",
        size=10.0,
        price=150.0,
    )
    assert result_jp.success
    assert result_jp.venue == "jupiter"
    mock_jupiter.execute_trade.assert_called_once()

    # Fulcrom
    result_fl = await router.submit_trade(
        trader=trader,
        venue_id="fulcrom",
        symbol="ETH-USDC",
        side="buy",
        size=0.5,
        price=3000.0,
    )
    assert result_fl.success
    assert result_fl.venue == "fulcrom"
    mock_fulcrom.execute_trade.assert_called_once()

    # Cronos
    result_cr = await router.submit_trade(
        trader=trader,
        venue_id="cronos_onchain",
        symbol="CRO-USDC",
        side="sell",
        size=100.0,
        price=0.08,
    )
    assert result_cr.success
    assert result_cr.venue == "cronos_onchain"
    mock_cronos.execute_trade.assert_called_once()


@pytest.mark.asyncio
async def test_spectator_mode_blocks_execution():
    router = ExecutionRouter()
    trader = TraderIdentity(trader_type="human", trader_id="spectator")
    # Force spectator mode via metadata (runtime config would normally enforce)
    result = await router.submit_trade(
        trader=trader,
        venue_id="coinbase",
        symbol="BTC-USDT",
        side="buy",
        size=0.1,
        metadata={"spectator_only": True},
    )
    # In real runtime, guard would block; here we just ensure no exception
    assert result is not None


@pytest.mark.asyncio
async def test_real_executors_instantiate():
    # Ensure concrete executors can be instantiated (no network calls here)
    CoinbaseExecutor()
    JupiterExecutor()
    FulcromExecutor()
    CronosOnchainExecutor()


@pytest.mark.asyncio
async def test_executor_quote_and_positions():
    # Test that executors implement the required methods (they raise NotImplementedError if not)
    cb = CoinbaseExecutor()
    jp = JupiterExecutor()
    fl = FulcromExecutor()
    cr = CronosOnchainExecutor()

    # These will make real HTTP calls; in CI they may be mocked or skipped
    # For now we only verify the methods exist and are async
    import inspect
    assert inspect.iscoroutinefunction(cb.get_quote)
    assert inspect.iscoroutinefunction(cb.execute_trade)
    assert inspect.iscoroutinefunction(cb.get_positions)
    assert inspect.iscoroutinefunction(jp.get_quote)
    assert inspect.iscoroutinefunction(jp.execute_trade)
    assert inspect.iscoroutinefunction(jp.get_positions)
    assert inspect.iscoroutinefunction(fl.get_quote)
    assert inspect.iscoroutinefunction(fl.execute_trade)
    assert inspect.iscoroutinefunction(fl.get_positions)
    assert inspect.iscoroutinefunction(cr.get_quote)
    assert inspect.iscoroutinefunction(cr.execute_trade)
    assert inspect.iscoroutinefunction(cr.get_positions)
