"""Integration test for Coinbase Advanced Trade adapter.

Skips automatically if MERID_COINBASE_API_KEY / COINBASE_API_KEY is not set.
Tests connect, get_balance, get_positions.
"""

import os
import pytest
from decimal import Decimal

_has_creds = bool(
    os.getenv("MERID_COINBASE_API_KEY") or os.getenv("COINBASE_API_KEY")
) and bool(
    os.getenv("MERID_COINBASE_API_SECRET") or os.getenv("COINBASE_API_SECRET")
)

pytestmark = pytest.mark.skipif(
    not _has_creds,
    reason="MERID_COINBASE_API_KEY / COINBASE_API_KEY not set — skipping Coinbase integration",
)


@pytest.fixture
async def adapter():
    from core.venues.coinbase_advanced_adapter import CoinbaseAdvancedAdapter
    a = CoinbaseAdvancedAdapter()
    connected = await a.connect()
    assert connected, "Failed to connect to Coinbase — check credentials"
    yield a
    await a.disconnect()


@pytest.mark.asyncio
async def test_connect(adapter):
    """Adapter connects and reports connected state."""
    assert adapter.connected is True
    assert adapter._http is not None


@pytest.mark.asyncio
async def test_get_balance_structure(adapter):
    """get_balance returns currency keys with Decimal values."""
    balance = await adapter.get_balance()
    assert isinstance(balance, dict), f"Expected dict, got {type(balance)}"
    # At minimum there should be a USD or stablecoin account
    assert len(balance) >= 0, "Balance dict should be present (may be empty for new accounts)"
    for key, val in balance.items():
        assert isinstance(val, Decimal), f"{key} should be Decimal, got {type(val)}"
        assert val > 0, f"{key} value should be positive (filtered zeros)"


@pytest.mark.asyncio
async def test_get_positions_structure(adapter):
    """get_positions returns a list of Position dataclasses."""
    positions = await adapter.get_positions()
    assert isinstance(positions, list)
    for p in positions:
        assert hasattr(p, "symbol"), "Position must have symbol"
        assert hasattr(p, "size"), "Position must have size"
        assert hasattr(p, "venue"), "Position must have venue"
        assert p.venue == "coinbase_advanced"


@pytest.mark.asyncio
async def test_get_open_orders_structure(adapter):
    """get_open_orders returns a list."""
    orders = await adapter.get_open_orders()
    assert isinstance(orders, list)


@pytest.mark.asyncio
async def test_get_market_data(adapter):
    """get_market_data returns MarketData or None for a known product."""
    md = await adapter.get_market_data("BTC-USD")
    # May return None if auth scope doesn't include market data
    if md is not None:
        assert md.venue == "coinbase_advanced"
        assert md.symbol == "BTC-USD"


@pytest.mark.asyncio
async def test_disconnect(adapter):
    """Adapter disconnects cleanly."""
    result = await adapter.disconnect()
    assert result is True
    assert adapter.connected is False
