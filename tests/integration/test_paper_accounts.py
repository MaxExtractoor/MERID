"""End-to-end integration tests against paper/testnet accounts."""

from __future__ import annotations

import os
import pytest
from unittest.mock import AsyncMock, MagicMock

from merid.execution import (
    AlpacaExecutor,
    CoinbaseExecutor,
    CryptoComExecutor,
    CronosOnchainExecutor,
    ExecutionRouter,
    FulcromExecutor,
    JupiterExecutor,
    KalshiExecutor,
    TraderIdentity,
    WebullExecutor,
)
from merid.execution.base import TradeResult, TradeSideLiteral


@pytest.fixture(scope="module")
def router():
    # Register real executors (will use paper/testnet if env vars are set)
    executors = {}
    if os.getenv("ALPACA_API_KEY"):
        executors["alpaca"] = AlpacaExecutor()
    if os.getenv("COINBASE_API_KEY"):
        executors["coinbase"] = CoinbaseExecutor()
    if os.getenv("SOLANA_PRIVATE_KEY"):
        executors["jupiter"] = JupiterExecutor()
    if os.getenv("CRONOS_PRIVATE_KEY"):
        executors["fulcrom"] = FulcromExecutor()
        executors["cronos_onchain"] = CronosOnchainExecutor()
    if os.getenv("KALSHI_API_KEY_ID"):
        executors["kalshi"] = KalshiExecutor()
    if os.getenv("WEBULL_USERNAME"):
        executors["webull"] = WebullExecutor()
    if os.getenv("CRYPTO_COM_API_KEY"):
        executors["crypto_com"] = CryptoComExecutor()
    return ExecutionRouter(executors=executors)


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("ALPACA_API_KEY"), reason="ALPACA_API_KEY not set")
async def test_alpaca_paper_trade(router):
    trader = TraderIdentity(trader_type="agent", trader_id="test-alpaca")
    result = await router.submit_trade(
        trader=trader,
        venue_id="alpaca",
        symbol="AAPL",
        side="buy",
        size=1,
        order_type="market",
        metadata={"paper": True},
    )
    assert result.success
    assert result.venue == "alpaca"
    assert result.symbol == "AAPL"


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("COINBASE_API_KEY"), reason="COINBASE_API_KEY not set")
async def test_coinbase_sandbox_trade(router):
    trader = TraderIdentity(trader_type="agent", trader_id="test-coinbase")
    result = await router.submit_trade(
        trader=trader,
        venue_id="coinbase",
        symbol="BTC-USDT",
        side="buy",
        size=0.0001,
        order_type="market",
        metadata={"sandbox": True},
    )
    assert result.success
    assert result.venue == "coinbase"


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("SOLANA_PRIVATE_KEY"), reason="SOLANA_PRIVATE_KEY not set")
async def test_jupiter_swap(router):
    trader = TraderIdentity(trader_type="agent", trader_id="test-jupiter")
    result = await router.submit_trade(
        trader=trader,
        venue_id="jupiter",
        symbol="SOL-USDC",
        side="sell",
        size=0.01,
        order_type="market",
        metadata={"test": True},
    )
    assert result.success
    assert result.venue == "jupiter"


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("KALSHI_API_KEY_ID"), reason="KALSHI_API_KEY_ID not set")
async def test_kalshi_market(router):
    trader = TraderIdentity(trader_type="agent", trader_id="test-kalshi")
    result = await router.submit_trade(
        trader=trader,
        venue_id="kalshi",
        symbol="PRES-2024-DEM",
        side="buy",
        size=1,
        order_type="market",
        metadata={"paper": True},
    )
    assert result.success
    assert result.venue == "kalshi"


@pytest.mark.asyncio
async def test_portfolio_aggregation(router):
    snapshot = await router.get_portfolio_snapshot()
    assert isinstance(snapshot.total_unrealized_pnl, (int, float))
    assert isinstance(snapshot.total_notional, (int, float))
    assert isinstance(snapshot.positions, list)


@pytest.mark.asyncio
async def test_dev_chat_portfolio_endpoint():
    from web.api.dev_chat import execute_chat_command, ChatCommand
    cmd = ChatCommand(command="portfolio_snapshot")
    response = await execute_chat_command(cmd)
    assert response.status == "ok"
    assert "total_unrealized_pnl" in response.data
    assert "total_notional" in response.data
    assert "positions" in response.data
