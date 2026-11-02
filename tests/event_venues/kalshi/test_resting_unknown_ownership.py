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
