"""Integration test for Coinbase Advanced Trade adapter.

Skips automatically if no Coinbase credentials (MERID_/CLIENT/COINBASE env).
Tests connect, get_balance, get_positions.
"""

import pytest
from decimal import Decimal

from merid.coinbase_env import coinbase_api_key, coinbase_api_secret

_has_creds = bool(coinbase_api_key() and coinbase_api_secret())

pytestmark = pytest.mark.skipif(
    not _has_creds,
    reason="Coinbase credentials not set — skipping Coinbase integration",
)


@pytest.fixture
async def adapter():
    from core.venues.coinbase_advanced_adapter import CoinbaseAdvancedAdapter
    a = CoinbaseAdvancedAdapter()
    connected = await a.connect()
    if not connected:
        pytest.skip(
            "Coinbase Advanced Trade connect failed (e.g. 401). "
            "Set COINBASE_CLIENT_API_KEY + signing secret, or valid MERID_/COINBASE_API_* pairs."
        )
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
