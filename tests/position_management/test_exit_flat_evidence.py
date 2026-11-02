"""An unresolved exit cannot be cleared from incomplete flat evidence."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from merid.position_management.position_monitor import PositionMonitor
from merid.resilience.result import OperationResult

TICKER = "KXTEST"


def _market(status):
    return SimpleNamespace(
        market_id=TICKER, venue="kalshi", raw_data={"status": status},
    )


@pytest.fixture
def setup(monkeypatch):
    monitor = object.__new__(PositionMonitor)
    monitor._mark_exit_intent_reconciled = MagicMock(return_value=True)
    monitor._clear_exit_intent_in_flight = MagicMock()
    client = SimpleNamespace(
        get_market_result=AsyncMock(return_value=OperationResult.ok(_market("closed"))),
        get_positions_with_filters=AsyncMock(return_value=OperationResult.ok({
            "market_positions": [],
        })),
    )
    monkeypatch.setattr("merid.event_venues.kalshi.client.get_kalshi_client", lambda: client)
    return monitor, client


@pytest.mark.asyncio
async def test_closed_market_and_complete_flat_snapshot_resolve(setup):
    monitor, _ = setup
    assert await monitor._resolve_exchange_confirmed_flat("pos", TICKER, "coid", "test")
    monitor._mark_exit_intent_reconciled.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["active", "unknown", ""])
async def test_active_or_unknown_market_keeps_lock(setup, status):
    monitor, client = setup
    client.get_market_result.return_value = OperationResult.ok(_market(status))
    assert not await monitor._resolve_exchange_confirmed_flat("pos", TICKER, "coid", "test")
    client.get_positions_with_filters.assert_not_awaited()
    monitor._mark_exit_intent_reconciled.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [
    None, {}, {"market_positions": None},
    {"market_positions": [], "cursor": "next"},
    {"market_positions": [], "truncated": True},
    {"market_positions": [{"ticker": TICKER, "position_fp": "bad"}]},
    {"market_positions": [{"ticker": TICKER, "position_fp": "NaN"}]},
    {"market_positions": [{"ticker": TICKER}]},
    {"market_positions": [{"ticker": "OTHER", "position_fp": "0"}]},
    {"market_positions": [{"ticker": TICKER, "position_fp": "0.01"}]},
    {"market_positions": [{"ticker": TICKER, "position_fp": "0", "position": "1"}]},
])
async def test_incomplete_malformed_or_nonzero_snapshot_keeps_lock(setup, data):
    monitor, client = setup
    client.get_positions_with_filters.return_value = OperationResult.ok(data)
    assert not await monitor._resolve_exchange_confirmed_flat("pos", TICKER, "coid", "test")
    monitor._mark_exit_intent_reconciled.assert_not_called()


@pytest.mark.asyncio
async def test_truncated_metadata_keeps_lock(setup):
    monitor, client = setup
    client.get_positions_with_filters.return_value = OperationResult.ok(
        {"market_positions": []}, truncated=True,
    )
    assert not await monitor._resolve_exchange_confirmed_flat("pos", TICKER, "coid", "test")
    monitor._mark_exit_intent_reconciled.assert_not_called()
