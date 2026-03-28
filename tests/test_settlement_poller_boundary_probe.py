"""Settlement poller boundary probe — upstream, downstream, and chaos tests.

Tests the KalshiSettlementPoller across three failure scenarios:

UPSTREAM (Kalshi API):
  - Normal delivery: settlements arrive and are dispatched.
  - Empty response: poller survives gracefully.
  - Cursor advancement on new data.

DOWNSTREAM (handlers / consumers):
  - Slow/crashing handler doesn't stop subsequent handlers.
  - All handlers called for each new settlement.
  - Duplicate settlement_ids are never re-dispatched.

CHAOS (restarts / partial data):
  - Cursor persistence survives restart simulation.
  - Settlement with missing id is skipped.
  - Rapid re-poll doesn't duplicate settlements.
  - Handler error during dispatch doesn't corrupt cursor.

Usage::

    py -m pytest tests/test_settlement_poller_boundary_probe.py -v -k "upstream"
    py -m pytest tests/test_settlement_poller_boundary_probe.py -v -k "downstream"
    py -m pytest tests/test_settlement_poller_boundary_probe.py -v -k "chaos"
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from merid.event_venues.kalshi.settlement_poller import (
    KalshiSettlementPoller,
    Settlement,
)


# ── Helpers ───────────────────────────────────────────────────────────────

def _make_settlement(sid: str, ticker: str = "KXBTC-15M-T95000", result: str = "yes") -> Dict[str, Any]:
    return {
        "id": sid,
        "ticker": ticker,
        "result": result,
        "settled_price": 100,
        "settled_at": time.time(),
    }


def _make_client(settlements: List[dict], cursor: Optional[str] = None) -> Any:
    """Create a duck-typed client that returns a fixed settlements page."""
    client = MagicMock()
    client.get_settlements = AsyncMock(return_value={
        "settlements": settlements,
        "cursor": cursor,
    })
    return client


# ── UPSTREAM tests ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upstream_normal_delivery_dispatches() -> None:
    """Normal upstream: settlements are fetched and dispatched to handlers."""
    items = [
        _make_settlement("s-001"),
        _make_settlement("s-002"),
        _make_settlement("s-003"),
    ]
    client = _make_client(items, cursor="cursor-1")
    poller = KalshiSettlementPoller(client=client)

    received: List[Settlement] = []
    poller.add_handler(received.append)

    count = await poller._poll_once()

    assert count == 3
    assert len(received) == 3
    assert {s.settlement_id for s in received} == {"s-001", "s-002", "s-003"}


@pytest.mark.asyncio
async def test_upstream_empty_response_survives() -> None:
    """Empty settlements list is handled gracefully — no crash, no dispatch."""
    client = _make_client([], cursor=None)
    poller = KalshiSettlementPoller(client=client)

    received: List[Settlement] = []
    poller.add_handler(received.append)

    count = await poller._poll_once()

    assert count == 0
    assert received == []


@pytest.mark.asyncio
async def test_upstream_cursor_advances_on_new_data() -> None:
    """Cursor is updated when the API returns a new cursor value."""
    client = _make_client([_make_settlement("s-100")], cursor="next-cursor-abc")
    poller = KalshiSettlementPoller(client=client)

    await poller._poll_once()

    assert poller._last_cursor == "next-cursor-abc"


@pytest.mark.asyncio
async def test_upstream_cursor_not_advanced_on_empty() -> None:
    """Cursor stays None when no settlements are returned."""
    client = _make_client([], cursor=None)
    poller = KalshiSettlementPoller(client=client)

    await poller._poll_once()

    assert poller._last_cursor is None


@pytest.mark.asyncio
async def test_upstream_fetch_error_returns_zero() -> None:
    """Client exception → poll_once returns 0 and doesn't propagate."""
    client = MagicMock()
    client.get_settlements = AsyncMock(side_effect=RuntimeError("API down"))
    poller = KalshiSettlementPoller(client=client)

    count = await poller._poll_once()
    assert count == 0


# ── DOWNSTREAM tests ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_downstream_all_handlers_called() -> None:
    """All registered handlers receive each new settlement."""
    client = _make_client([_make_settlement("s-h1")])
    poller = KalshiSettlementPoller(client=client)

    received_a: List[Settlement] = []
    received_b: List[Settlement] = []
    poller.add_handler(received_a.append)
    poller.add_handler(received_b.append)

    await poller._poll_once()

    assert len(received_a) == 1
    assert len(received_b) == 1


@pytest.mark.asyncio
async def test_downstream_crashing_handler_does_not_stop_others() -> None:
    """A handler that raises doesn't prevent subsequent handlers from running."""
    client = _make_client([_make_settlement("s-crash")])
    poller = KalshiSettlementPoller(client=client)

    def _crash(_: Settlement) -> None:
        raise RuntimeError("handler exploded")

    received: List[Settlement] = []
    poller.add_handler(_crash)
    poller.add_handler(received.append)

    # Should NOT raise
    count = await poller._poll_once()
    assert count == 1
    assert len(received) == 1


@pytest.mark.asyncio
async def test_downstream_async_handler_awaited() -> None:
    """Async handlers are awaited properly."""
    client = _make_client([_make_settlement("s-async")])
    poller = KalshiSettlementPoller(client=client)

    received: List[Settlement] = []

    async def _async_handler(s: Settlement) -> None:
        received.append(s)

    poller.add_handler(_async_handler)
    await poller._poll_once()

    assert len(received) == 1


@pytest.mark.asyncio
async def test_downstream_duplicate_id_not_redispatched() -> None:
    """Re-delivered settlement_id is not sent to handlers again."""
    items = [_make_settlement("s-dup")]
    client = _make_client(items)
    poller = KalshiSettlementPoller(client=client)

    received: List[Settlement] = []
    poller.add_handler(received.append)

    await poller._poll_once()
    await poller._poll_once()  # same id again

    assert len(received) == 1  # dispatched exactly once


# ── CHAOS tests ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chaos_cursor_history_grows_with_advances() -> None:
    """_cursor_history accumulates every distinct cursor checkpoint."""
    calls = 0

    async def _fetch(cursor: Optional[str] = None) -> dict:
        nonlocal calls
        calls += 1
        return {
            "settlements": [_make_settlement(f"s-{calls:04d}")],
            "cursor": f"cursor-{calls}",
        }

    client = MagicMock()
    client.get_settlements = _fetch
    poller = KalshiSettlementPoller(client=client)

    for _ in range(3):
        await poller._poll_once()

    assert len(poller._cursor_history) == 3
    assert poller._cursor_history[-1] == "cursor-3"


@pytest.mark.asyncio
async def test_chaos_restart_simulation_resumes_from_cursor() -> None:
    """Simulate restart: poller initialized with in-memory cursor from a previous run."""
    # First poller run, advances cursor
    client1 = _make_client([_make_settlement("s-pre")], cursor="saved-cursor")
    p1 = KalshiSettlementPoller(client=client1)
    await p1._poll_once()
    saved_cursor = p1._last_cursor

    # Second poller (restart) restores cursor; duplicate s-pre is ignored
    client2 = _make_client([_make_settlement("s-pre")], cursor=None)
    p2 = KalshiSettlementPoller(client=client2)
    p2._last_cursor = saved_cursor  # simulated Redis restore
    p2._seen_ids.add("s-pre")       # simulated seen_ids restore

    received: List[Settlement] = []
    p2.add_handler(received.append)
    count = await p2._poll_once()

    assert count == 0  # nothing new across restart
    assert received == []


@pytest.mark.asyncio
async def test_chaos_settlement_with_missing_id_skipped() -> None:
    """Settlements without any id field are silently skipped."""
    items = [
        {"ticker": "KXBTC", "result": "yes", "settled_price": 100},  # no id
        _make_settlement("s-ok"),
    ]
    client = _make_client(items)
    poller = KalshiSettlementPoller(client=client)

    received: List[Settlement] = []
    poller.add_handler(received.append)

    count = await poller._poll_once()

    assert count == 1
    assert received[0].settlement_id == "s-ok"


@pytest.mark.asyncio
async def test_chaos_rapid_repoll_no_duplicates() -> None:
    """Rapid consecutive polls with same data produce exactly one dispatch."""
    client = _make_client([_make_settlement("s-rapid")])
    poller = KalshiSettlementPoller(client=client)

    received: List[Settlement] = []
    poller.add_handler(received.append)

    for _ in range(5):
        await poller._poll_once()

    assert len(received) == 1


@pytest.mark.asyncio
async def test_chaos_handler_error_does_not_corrupt_cursor() -> None:
    """Even when a handler crashes, the cursor is still advanced."""
    client = _make_client([_make_settlement("s-err")], cursor="cursor-after-err")
    poller = KalshiSettlementPoller(client=client)

    def _boom(_: Settlement) -> None:
        raise ValueError("boom")

    poller.add_handler(_boom)
    await poller._poll_once()

    assert poller._last_cursor == "cursor-after-err"


@pytest.mark.asyncio
async def test_chaos_status_reflects_activity() -> None:
    """status() accurately reflects poll and settlement counts."""
    items = [_make_settlement("s-stat-1"), _make_settlement("s-stat-2")]
    client = _make_client(items)
    poller = KalshiSettlementPoller(client=client)

    await poller._poll_once()

    s = poller.status()
    assert s["poll_count"] == 1
    assert s["settlement_count"] == 2
    assert s["seen_ids_count"] == 2

