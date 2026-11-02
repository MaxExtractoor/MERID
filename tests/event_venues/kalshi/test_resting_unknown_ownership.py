"""Missing order snapshots must never release a working order."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from merid.event_venues.kalshi.resting_order_monitor import (
    RestingOrderMonitor, RestingOrderRecord,
)
from merid.resilience.result import OperationResult


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [
    OperationResult.ok(None), OperationResult.fail(RuntimeError("offline")),
])
async def test_repeated_missing_snapshots_retain_order(monkeypatch, result):
    client = SimpleNamespace(get_order_result=AsyncMock(return_value=result))
    monkeypatch.setattr("merid.event_venues.kalshi.client.get_kalshi_client", lambda: client)
    monitor = RestingOrderMonitor()
    record = RestingOrderRecord(
        kalshi_order_id="order-1", ticker="KXTEST", original_size=1, remaining_size=1,
    )
    for _ in range(5):
        assert not await monitor._sync_order_status(record)
    assert record.missing_data_count == 5
    assert record.remaining_size == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("remaining", ["0.75", "1.25", None, "NaN", "-1", "bad"])
async def test_unsupported_remaining_never_removes_order(monkeypatch, remaining):
    snapshot = SimpleNamespace(status="resting", remaining_size=remaining)
    client = SimpleNamespace(
        get_order_result=AsyncMock(return_value=OperationResult.ok(snapshot)),
    )
    monkeypatch.setattr("merid.event_venues.kalshi.client.get_kalshi_client", lambda: client)
    monitor = RestingOrderMonitor()
    record = RestingOrderRecord(
        kalshi_order_id="order-1", ticker="KXTEST", original_size=2, remaining_size=2,
    )
    assert not await monitor._sync_order_status(record)
    assert record.remaining_size == 2


@pytest.mark.asyncio
async def test_zero_remaining_with_working_status_stays_tracked(monkeypatch):
    snapshot = SimpleNamespace(status="resting", remaining_size=0, filled_size=0)
    client = SimpleNamespace(
        get_order_result=AsyncMock(return_value=OperationResult.ok(snapshot)),
    )
    ledger = SimpleNamespace(
        get_canonical_fills=lambda **_: SimpleNamespace(authoritative=[]),
    )
    monkeypatch.setattr("merid.event_venues.kalshi.client.get_kalshi_client", lambda: client)
    monkeypatch.setattr("merid.event_venues.kalshi.fills_ledger.get_fills_ledger", lambda: ledger)
    monitor = RestingOrderMonitor()
    record = RestingOrderRecord(
        kalshi_order_id="order-1", ticker="KXTEST", original_size=2, remaining_size=2,
    )
    assert not await monitor._sync_order_status(record)
    assert record.status == "resting"
    assert record.remaining_size == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("filled", [None, "bad", "NaN", "-1", "0.001"])
async def test_terminal_order_with_invalid_fill_evidence_stays_tracked(monkeypatch, filled):
    snapshot = SimpleNamespace(status="canceled", remaining_size=0, filled_size=filled)
    client = SimpleNamespace(
        get_order_result=AsyncMock(return_value=OperationResult.ok(snapshot)),
    )
    monkeypatch.setattr("merid.event_venues.kalshi.client.get_kalshi_client", lambda: client)
    monitor = RestingOrderMonitor()
    record = RestingOrderRecord(
        kalshi_order_id="order-1", ticker="KXTEST", original_size=2, remaining_size=2,
    )
    assert not await monitor._sync_order_status(record)
    assert record.remaining_size == 2
