"""Integration test for Alpaca paper trading adapter.

Skips automatically if MERID_ALPACA_API_KEY / ALPACA_API_KEY is not set.
Tests connect, get_balance, get_positions, and optionally a tiny paper order.
"""

import os
import pytest
from decimal import Decimal

# Skip entire module if no Alpaca credentials
_has_creds = bool(
    os.getenv("MERID_ALPACA_API_KEY") or os.getenv("ALPACA_API_KEY")
) and bool(
    os.getenv("MERID_ALPACA_API_SECRET") or os.getenv("ALPACA_API_SECRET")
)

pytestmark = pytest.mark.skipif(
    not _has_creds,
    reason="MERID_ALPACA_API_KEY / ALPACA_API_KEY not set — skipping Alpaca integration",
)


@pytest.fixture
async def adapter():
    from core.venues.alpaca_adapter import AlpacaAdapter
    a = AlpacaAdapter(paper=True)
    connected = await a.connect()
    assert connected, "Failed to connect to Alpaca paper — check credentials"
    yield a
    await a.disconnect()


@pytest.mark.asyncio
async def test_connect(adapter):
    """Adapter connects and reports connected state."""
    assert adapter.connected is True
    assert adapter._trading_client is not None


@pytest.mark.asyncio
async def test_get_balance_structure(adapter):
    """get_balance returns expected keys with Decimal values."""
    balance = await adapter.get_balance()
    assert isinstance(balance, dict), f"Expected dict, got {type(balance)}"
    assert "USD" in balance, f"Missing 'USD' key, got keys: {list(balance.keys())}"
    assert "EQUITY" in balance, f"Missing 'EQUITY' key"
    assert "BUYING_POWER" in balance, f"Missing 'BUYING_POWER' key"
    for key, val in balance.items():
        assert isinstance(val, Decimal), f"{key} should be Decimal, got {type(val)}"
    assert balance["EQUITY"] >= 0, "Equity should be non-negative"


@pytest.mark.asyncio
async def test_get_positions_structure(adapter):
    """get_positions returns a list of Position dataclasses."""
    positions = await adapter.get_positions()
    assert isinstance(positions, list)
    for p in positions:
        assert hasattr(p, "symbol"), "Position must have symbol"
        assert hasattr(p, "size"), "Position must have size"
        assert hasattr(p, "venue"), "Position must have venue"
        assert p.venue == "alpaca"


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
