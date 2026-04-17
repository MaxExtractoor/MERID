"""Integration test for Kalshi prediction market adapter.

Skips automatically if KALSHI_API_KEY_ID is not set.
Tests connect, get_balance, get_positions, get_markets.
"""

import os
import pytest
from decimal import Decimal

_has_creds = bool(os.getenv("KALSHI_API_KEY_ID")) and bool(
    os.getenv("KALSHI_PRIVATE_KEY_PATH") or os.getenv("KALSHI_PRIVATE_KEY_PEM")
)

pytestmark = pytest.mark.skipif(
    not _has_creds,
    reason="KALSHI_API_KEY_ID not set — skipping Kalshi integration",
)


@pytest.fixture
async def adapter():
    from core.venues.kalshi_adapter import KalshiAdapter
    a = KalshiAdapter()
    connected = await a.connect()
    assert connected, "Failed to connect to Kalshi — check credentials / key"
    yield a
    await a.disconnect()


@pytest.mark.asyncio
async def test_connect(adapter):
    """Adapter connects and reports connected state."""
    assert adapter.connected is True
    assert adapter._http is not None


@pytest.mark.asyncio
async def test_get_balance_structure(adapter):
    """get_balance returns USD and PAYOUT as Decimals."""
    balance = await adapter.get_balance()
    assert isinstance(balance, dict), f"Expected dict, got {type(balance)}"
    assert "USD" in balance, f"Missing 'USD' key, got keys: {list(balance.keys())}"
    for key, val in balance.items():
        assert isinstance(val, Decimal), f"{key} should be Decimal, got {type(val)}"
    assert balance["USD"] >= 0, "USD balance should be non-negative"


@pytest.mark.asyncio
async def test_get_positions_structure(adapter):
    """get_positions returns a list of Position dataclasses."""
    positions = await adapter.get_positions()
    assert isinstance(positions, list)
    for p in positions:
        assert hasattr(p, "symbol"), "Position must have symbol"
        assert hasattr(p, "size"), "Position must have size"
        assert hasattr(p, "venue"), "Position must have venue"
        assert p.venue == "kalshi"


@pytest.mark.asyncio
async def test_get_markets_structure(adapter):
    """get_markets returns a list of market dicts with expected keys."""
    markets = await adapter.get_markets(limit=5)
    assert isinstance(markets, list)
    if markets:
        m = markets[0]
        assert "ticker" in m, f"Market missing 'ticker', got keys: {list(m.keys())}"
        assert "title" in m, f"Market missing 'title'"
        assert "status" in m, f"Market missing 'status'"


@pytest.mark.asyncio
async def test_get_open_orders_structure(adapter):
    """get_open_orders returns a list."""
    orders = await adapter.get_open_orders()
    assert isinstance(orders, list)


@pytest.mark.asyncio
async def test_disconnect(adapter):
    """Adapter disconnects cleanly."""
    result = await adapter.disconnect()
    assert result is True
    assert adapter.connected is False
