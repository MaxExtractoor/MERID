"""Canonical portfolio snapshot and reconciliation tests.

These tests enforce the single-authoritative-exposure invariants described in
AGENTS.md and the canonical portfolio snapshot design.  They do not require a
live Kalshi connection; all external calls are mocked.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

from merid.event_venues.base import PlacedOrder, VenuePosition
from merid.event_venues.kalshi.canonical_portfolio import (
    CanonicalPortfolioSnapshot,
    CanonicalPortfolioStore,
    CanonicalPosition,
    PaginationIncomplete,
    ReconciliationReason,
    ReconciliationStatus,
    SourceCompleteness,
    collect_all_pages,
    get_canonical_portfolio_store,
)
from merid.resilience import OperationResult
from merid.event_venues.kalshi.canonical_portfolio_reconciler import (
    CanonicalPortfolioReconciler,
    get_canonical_portfolio_reconciler,
)


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset store and reconciler between tests for isolation."""
    store = get_canonical_portfolio_store()
    store._current = None
    store._version = 0
    store._publish_count = 0
    reconciler = get_canonical_portfolio_reconciler()
    reconciler._version = 0
    reconciler._ws_positions.clear()
    reconciler._ws_orders.clear()
    reconciler._ws_fills.clear()
    reconciler._ws_healthy = True
    reconciler._kalshi_client = None
    reconciler._fills_ledger = None
    reconciler._position_cache = None
    reconciler._running = False
    reconciler._task = None
    reconciler._last_snapshot = None
    reconciler._last_authoritative_at_mono = 0.0
    reconciler._first_mismatch_at_mono = None
    reconciler._last_mismatch_reason = None
    reconciler._reconcile_attempt = 0
    reconciler._mismatch_reconcile_attempt = 0
    reconciler._last_recovery_at_mono = None
    reconciler._last_mismatch_heartbeat_at_mono = 0.0
    reconciler._recovery_state = "IDLE"
    reconciler._store = store
    yield


@dataclass
class _FakeCachedPosition:
    """Minimal stand-in for ``KalshiPositionCache.CachedPosition``."""

    market_id: str
    contracts: int
    side: str
    outcome: str
    avg_price_cents: Optional[int]
    quantity_cc: int = 0
    entry_order_id: Optional[str] = None
    entry_fill_id: Optional[str] = None


class _FakePositionCache:
    """In-memory position cache for tests."""

    def __init__(self, positions: Dict[str, _FakeCachedPosition]):
        self._positions = positions

    def get_all_positions(self, validate_freshness: bool = True):
        return dict(self._positions)


class _FakeFillsLedger:
    """In-memory fills ledger for tests."""

    def __init__(self, positions: Dict[str, Dict[str, Any]]):
        self._positions = positions

    def compute_net_positions(self, since_hours: int = 24):
        return dict(self._positions)


class _FakeKalshiClient:
    """Mock Kalshi client for tests."""

    def __init__(
        self,
        positions: List[VenuePosition],
        open_orders: List[PlacedOrder],
        positions_result: Optional[OperationResult] = None,
        open_orders_result: Optional[OperationResult] = None,
        fills_result: Optional[OperationResult] = None,
    ):
        self._positions = positions
        self._open_orders = open_orders
        self._positions_result = positions_result
        self._open_orders_result = open_orders_result
        self._fills_result = fills_result

    async def get_positions(self) -> List[VenuePosition]:
        return list(self._positions)

    async def get_positions_result(self) -> OperationResult[List[VenuePosition]]:
        if self._positions_result is not None:
            return self._positions_result
        return OperationResult.ok(list(self._positions))

    async def get_open_orders(self, market_id: Optional[str] = None) -> List[PlacedOrder]:
        return list(self._open_orders)

    async def get_open_orders_result(self, market_id: Optional[str] = None) -> OperationResult[List[PlacedOrder]]:
        if self._open_orders_result is not None:
            return self._open_orders_result
        return OperationResult.ok(list(self._open_orders))

    async def get_fills(
        self,
        limit: int = 200,
        since_ts: Optional[int] = None,
        ticker: Optional[str] = None,
        order_id: Optional[str] = None,
    ) -> OperationResult[List[Dict[str, Any]]]:
        if self._fills_result is not None:
            return self._fills_result
        return OperationResult.ok([])


def _make_reconciler(
    client: Optional[_FakeKalshiClient] = None,
    cache: Optional[_FakePositionCache] = None,
    ledger: Optional[_FakeFillsLedger] = None,
):
    """Return a reconciler with injected test dependencies."""
    reconciler = get_canonical_portfolio_reconciler()
    reconciler._kalshi_client = client
    reconciler._fills_ledger = ledger
    reconciler._position_cache = cache or _FakePositionCache({})
    reconciler._ws_healthy = True
    return reconciler


@pytest.mark.asyncio
async def test_matched_snapshot_when_all_sources_agree():
    """Exchange, ledger, and cache all report the same position."""
    ticker = "KXBTC15M-26AUG192030-30"
    qty = Decimal("0.62")
    qcc = int(qty * Decimal("100"))

    client = _FakeKalshiClient(
        positions=[
            VenuePosition(
                market_id=ticker,
                outcome_id="yes",
                size=qty,
                average_entry_price=Decimal("0.45"),
            )
        ],
        open_orders=[],
    )
    ledger = _FakeFillsLedger({
        ticker: {
            "side": "yes",
            "contracts": float(qty),
            "avg_price_cents": 45,
        },
    })
    cache = _FakePositionCache({
        ticker: _FakeCachedPosition(
            market_id=ticker,
            contracts=0,  # display floor is intentionally lossy; canonical uses quantity_cc
            side="yes",
            outcome="yes",
            avg_price_cents=45,
            quantity_cc=qcc,
        ),
    })

    reconciler = _make_reconciler(client, cache, ledger)
    snapshot = await reconciler.build_snapshot()

    assert snapshot.reconciliation_status == ReconciliationStatus.MATCHED
    assert snapshot.positions_count == 1
    assert snapshot.exchange_exposure_cc == qcc
    assert snapshot.local_ledger_exposure_cc == qcc
    assert snapshot.reserved_exposure_cc == 0
    assert snapshot.positions_by_ticker[ticker].quantity_fp == qty


@pytest.mark.asyncio
async def test_mismatch_when_rest_has_position_cache_is_zero():
    """REST says 0.62 contracts; local cache says zero."""
    ticker = "KXETH15M-26AUG192030-30"
    qty = Decimal("0.62")
    qcc = int(qty * Decimal("100"))

    client = _FakeKalshiClient(
        positions=[
            VenuePosition(
                market_id=ticker,
                outcome_id="yes",
                size=qty,
                average_entry_price=Decimal("0.82"),
            )
        ],
        open_orders=[],
    )
    ledger = _FakeFillsLedger({})  # ledger not yet updated
    cache = _FakePositionCache({})  # cache empty

    reconciler = _make_reconciler(client, cache, ledger)
    snapshot = await reconciler.build_snapshot()

    assert snapshot.reconciliation_status == ReconciliationStatus.MISMATCH
    assert snapshot.reconciliation_reason == ReconciliationReason.MISMATCH_LEDGER
    assert snapshot.exchange_exposure_cc == qcc
    assert snapshot.local_ledger_exposure_cc == 0
    assert any(ticker in m for m in snapshot.mismatches)


@pytest.mark.asyncio
async def test_mismatch_when_cache_has_position_absent_from_rest():
    """Local cache has a position that REST does not confirm."""
    ticker = "KXDOGE15M-26AUG192030-30"

    client = _FakeKalshiClient(positions=[], open_orders=[])
    ledger = _FakeFillsLedger({})
    cache = _FakePositionCache({
        ticker: _FakeCachedPosition(
            market_id=ticker,
            contracts=1,
            side="yes",
            outcome="yes",
            avg_price_cents=74,
            quantity_cc=100,
        ),
    })

    reconciler = _make_reconciler(client, cache, ledger)
    snapshot = await reconciler.build_snapshot()

    assert snapshot.reconciliation_status == ReconciliationStatus.MISMATCH
    assert snapshot.reconciliation_reason == ReconciliationReason.MISMATCH_POSITION
    assert snapshot.positions_count == 1
    assert snapshot.positions_by_ticker[ticker].provenance == "cache"


@pytest.mark.asyncio
async def test_working_order_creates_reserved_exposure_not_position():
    """A working order contributes reserved exposure but not a confirmed position."""
    ticker = "KXXRP15M-26AUG192030-30"
    order_size = Decimal("1.55")

    client = _FakeKalshiClient(
        positions=[],
        open_orders=[
            PlacedOrder(
                order_id="ord-123",
                market_id=ticker,
                side="yes",
                size=order_size,
                price=Decimal("0.50"),
                filled_size=Decimal("0"),
                remaining_size=order_size,
                status="resting",
            )
        ],
    )
    ledger = _FakeFillsLedger({})
    cache = _FakePositionCache({})

    reconciler = _make_reconciler(client, cache, ledger)
    snapshot = await reconciler.build_snapshot()

    assert snapshot.reconciliation_status == ReconciliationStatus.MATCHED
    assert snapshot.positions_count == 0
    assert snapshot.exchange_exposure_cc == 0
    assert snapshot.reserved_exposure_cc == int(order_size * Decimal("100"))
    assert "ord-123" in snapshot.working_orders_by_id
    assert snapshot.working_orders_by_id["ord-123"].remaining_quantity_fp == order_size


@pytest.mark.asyncio
async def test_unfilled_ioc_has_zero_remainder_position_remains():
    """An IOC with zero remaining does not create a new position; old one stays."""
    ticker = "KXSOL15M-26AUG192030-30"
    existing = Decimal("0.75")

    client = _FakeKalshiClient(
        positions=[
            VenuePosition(
                market_id=ticker,
                outcome_id="yes",
                size=existing,
                average_entry_price=Decimal("0.60"),
            )
        ],
        open_orders=[
            PlacedOrder(
                order_id="ord-ioc",
                market_id=ticker,
                side="yes",
                size=Decimal("1.00"),
                price=Decimal("0.50"),
                filled_size=Decimal("1.00"),
                remaining_size=Decimal("0"),
                status="filled",
            )
        ],
    )
    ledger = _FakeFillsLedger({
        ticker: {
            "side": "yes",
            "contracts": float(existing),
            "avg_price_cents": 60,
        },
    })
    cache = _FakePositionCache({
        ticker: _FakeCachedPosition(
            market_id=ticker,
            contracts=0,
            side="yes",
            outcome="yes",
            avg_price_cents=60,
            quantity_cc=int(existing * Decimal("100")),
        ),
    })

    reconciler = _make_reconciler(client, cache, ledger)
    snapshot = await reconciler.build_snapshot()

    assert snapshot.reconciliation_status == ReconciliationStatus.MATCHED
    assert snapshot.positions_by_ticker[ticker].quantity_fp == existing


@pytest.mark.asyncio
async def test_partial_fill_changes_exposure_by_fractional_count_fp():
    """A fractional partial fill is preserved in centi-contract exposure."""
    ticker = "KXBTC15M-26AUG192030-30"
    partial = Decimal("0.49")
    qcc = int(partial * Decimal("100"))

    client = _FakeKalshiClient(
        positions=[
            VenuePosition(
                market_id=ticker,
                outcome_id="yes",
                size=partial,
                average_entry_price=Decimal("0.51"),
            )
        ],
        open_orders=[],
    )
    ledger = _FakeFillsLedger({
        ticker: {
            "side": "yes",
            "contracts": float(partial),
            "avg_price_cents": 51,
        },
    })
    cache = _FakePositionCache({
        ticker: _FakeCachedPosition(
            market_id=ticker,
            contracts=0,  # display floor is intentionally lossy
            side="yes",
            outcome="yes",
            avg_price_cents=51,
            quantity_cc=int(partial * Decimal("100")),
        ),
    })

    reconciler = _make_reconciler(client, cache, ledger)
    snapshot = await reconciler.build_snapshot()

    assert snapshot.reconciliation_status == ReconciliationStatus.MATCHED
    assert snapshot.exchange_exposure_cc == qcc
    assert snapshot.positions_by_ticker[ticker].quantity_fp == partial


@pytest.mark.asyncio
async def test_all_consumers_see_same_version():
    """Publishing a snapshot makes the same version visible to all readers."""
    reconciler = _make_reconciler(
        _FakeKalshiClient([], []),
        _FakePositionCache({}),
        _FakeFillsLedger({}),
    )

    snapshot = await reconciler.build_snapshot()
    get_canonical_portfolio_store().publish(snapshot)

    current = get_canonical_portfolio_store().current()
    assert current is not None
    assert current.version == snapshot.version
    assert current is snapshot  # exact object, atomic reference


@pytest.mark.asyncio
async def test_concurrent_reconciliations_publish_monotonic_versions():
    """Two concurrent build calls must publish monotonic versions."""
    reconciler = _make_reconciler(
        _FakeKalshiClient([], []),
        _FakePositionCache({}),
        _FakeFillsLedger({}),
    )

    snapshots = []

    async def build():
        snap = await reconciler.build_snapshot()
        snapshots.append(snap)

    await asyncio.gather(build(), build())
    assert snapshots[0].version != snapshots[1].version
    assert {snapshots[0].version, snapshots[1].version} == {1, 2}


@pytest.mark.asyncio
async def test_exchange_rest_pagination_aggregates_multiple_pages():
    """Multiple pages of REST positions are aggregated into one snapshot."""
    tickers = [
        f"KXBTC15M-26AUG192030-{i:02d}"
        for i in range(5)
    ]

    positions = [
        VenuePosition(
            market_id=t,
            outcome_id="yes",
            size=Decimal("0.10"),
            average_entry_price=Decimal("0.50"),
        )
        for t in tickers
    ]
    client = _FakeKalshiClient(positions, [])
    ledger = _FakeFillsLedger({t: {"side": "yes", "contracts": 0.10, "avg_price_cents": 50} for t in tickers})
    cache = _FakePositionCache({
        t: _FakeCachedPosition(
            market_id=t,
            contracts=0,
            side="yes",
            outcome="yes",
            avg_price_cents=50,
            quantity_cc=10,
        )
        for t in tickers
    })

    reconciler = _make_reconciler(client, cache, ledger)
    snapshot = await reconciler.build_snapshot()

    assert snapshot.reconciliation_status == ReconciliationStatus.MATCHED
    assert snapshot.positions_count == 5
    assert snapshot.exchange_exposure_cc == 5 * 10


@pytest.mark.asyncio
async def test_out_of_order_ws_fill_and_duplicate_events():
    """Out-of-order and duplicate WS fill events do not change final exposure."""
    reconciler = _make_reconciler(
        _FakeKalshiClient([], []),
        _FakePositionCache({}),
        _FakeFillsLedger({}),
    )

    fill = {
        "fill_id": "fill-1",
        "order_id": "ord-1",
        "ticker": "KXBTC15M-26AUG192030-30",
        "side": "yes",
        "action": "buy",
        "quantity": Decimal("0.50"),
        "price_cents": 50,
        "fee_cents": 0,
        "timestamp": time.monotonic(),
        "source": "ws_fill",
    }

    reconciler.ingest_fill_event("fill-1", fill)
    reconciler.ingest_fill_event("fill-1", fill)  # duplicate

    snapshot = await reconciler.build_snapshot()

    assert snapshot.pending_fills_by_id["fill-1"].quantity_fp == Decimal("0.50")
    assert snapshot.exchange_exposure_cc == 0  # WS fills are pending, not authoritative


@pytest.mark.asyncio
async def test_stale_private_ws_does_not_override_matched_rest():
    """A matched REST snapshot remains MATCHED even when the private WS is stale.

    The P0 fix (2026-08-24) treats the authenticated REST fetch as the source of
    truth for position data; a slow or stale private WebSocket is a delivery
    channel, not a reason to make the portfolio non-authoritative.
    """
    ticker = "KXBTC15M-26AUG192030-30"
    qty = Decimal("0.62")

    client = _FakeKalshiClient(
        positions=[
            VenuePosition(
                market_id=ticker,
                outcome_id="yes",
                size=qty,
                average_entry_price=Decimal("0.45"),
            )
        ],
        open_orders=[],
    )
    ledger = _FakeFillsLedger({
        ticker: {"side": "yes", "contracts": float(qty), "avg_price_cents": 45},
    })
    cache = _FakePositionCache({
        ticker: _FakeCachedPosition(
            market_id=ticker,
            contracts=0,
            side="yes",
            outcome="yes",
            avg_price_cents=45,
            quantity_cc=int(qty * Decimal("100")),
        ),
    })

    reconciler = _make_reconciler(client, cache, ledger)
    reconciler._ws_healthy = False
    snapshot = await reconciler.build_snapshot()

    assert snapshot.reconciliation_status == ReconciliationStatus.MATCHED
    assert snapshot.reconciliation_reason == ReconciliationReason.MATCHED
    assert snapshot.is_authoritative
    assert not snapshot.private_ws_healthy


@pytest.mark.asyncio
async def test_no_exchange_data_marks_unknown():
    """If REST positions cannot be fetched, status is UNKNOWN and entry should fail."""
    reconciler = _make_reconciler(
        _FakeKalshiClient([], []),
        _FakePositionCache({}),
        _FakeFillsLedger({}),
    )

    # Override client to fail
    async def _fail():
        raise RuntimeError("network down")

    reconciler._kalshi_client.get_positions = _fail
    reconciler._kalshi_client.get_positions_result = _fail

    snapshot = await reconciler.build_snapshot()
    assert snapshot.reconciliation_status == ReconciliationStatus.UNKNOWN
    assert snapshot.reconciliation_reason == ReconciliationReason.UNKNOWN_NETWORK
    assert snapshot.source == "no_exchange_data"


@pytest.mark.asyncio
async def test_snapshot_to_dict_contains_required_telemetry():
    """Snapshot serializes fields required for decision logging."""
    reconciler = _make_reconciler(
        _FakeKalshiClient([], []),
        _FakePositionCache({}),
        _FakeFillsLedger({}),
    )

    snapshot = await reconciler.build_snapshot()
    d = snapshot.to_dict()

    assert "version" in d
    assert "reconciliation_status" in d
    assert "exchange_exposure_cc" in d
    assert "reserved_exposure_cc" in d
    assert "signed_exposure_cc" in d
    assert "gross_exposure_cc" in d
    assert "gross_reserved_exposure_cc" in d
    assert "gross_notional_cents" in d
    assert "source_age_ms" in d
    assert "age_ms" in d


@pytest.mark.asyncio
async def test_entry_gate_blocks_on_mismatch():
    """The canonical snapshot exposes is_matched so gates can reject entries."""
    store = get_canonical_portfolio_store()
    snapshot = CanonicalPortfolioSnapshot(
        version=1,
        captured_at_wall_ns=0,
        captured_at_mono_ns=0,
        positions_by_ticker={},
        working_orders_by_id={},
        pending_fills_by_id={},
        exchange_exposure_cc=62,
        local_ledger_exposure_cc=0,
        reserved_exposure_cc=0,
        reconciliation_status=ReconciliationStatus.MISMATCH,
        source="test",
        source_age_ms=0,
        private_ws_healthy=True,
        mismatches=("KXETH:exchange=62:ledger=0",),
    )
    store.publish(snapshot)

    assert not get_canonical_portfolio_store().current().is_matched


@pytest.mark.asyncio
async def test_gross_exposure_accounts_for_opposing_positions():
    """Signed net can cancel; gross must sum absolute exposure for capital limits."""
    yes_ticker = "KXBTC15M-26AUG192030-Y"
    no_ticker = "KXBTC15M-26AUG192030-N"

    client = _FakeKalshiClient(
        positions=[
            VenuePosition(market_id=yes_ticker, outcome_id="yes", size=Decimal("1.00"), average_entry_price=Decimal("0.55")),
            VenuePosition(market_id=no_ticker, outcome_id="no", size=Decimal("1.00"), average_entry_price=Decimal("0.45")),
        ],
        open_orders=[],
    )
    ledger = _FakeFillsLedger({
        yes_ticker: {"side": "yes", "contracts": 1.0, "avg_price_cents": 55},
        no_ticker: {"side": "no", "contracts": 1.0, "avg_price_cents": 45},
    })
    cache = _FakePositionCache({
        yes_ticker: _FakeCachedPosition(yes_ticker, contracts=1, side="yes", outcome="yes", avg_price_cents=55, quantity_cc=100),
        no_ticker: _FakeCachedPosition(no_ticker, contracts=1, side="no", outcome="no", avg_price_cents=45, quantity_cc=100),
    })

    reconciler = _make_reconciler(client, cache, ledger)
    snapshot = await reconciler.build_snapshot()

    assert snapshot.signed_exposure_cc == 0
    assert snapshot.gross_exposure_cc == 200
    assert snapshot.gross_notional_cents == (100 * 55 + 100 * 45)
    assert snapshot.reconciliation_status == ReconciliationStatus.MATCHED


def test_store_rejects_stale_publication():
    """An older snapshot finishing later cannot overwrite a newer one."""
    store = get_canonical_portfolio_store()
    store.publish(
        CanonicalPortfolioSnapshot(
            version=2,
            captured_at_wall_ns=0,
            captured_at_mono_ns=0,
            positions_by_ticker={},
            working_orders_by_id={},
            pending_fills_by_id={},
            exchange_exposure_cc=0,
            local_ledger_exposure_cc=0,
            reserved_exposure_cc=0,
            reconciliation_status=ReconciliationStatus.MATCHED,
            source="test",
            source_age_ms=0,
            private_ws_healthy=True,
        )
    )

    assert store.current().version == 2

    stale = CanonicalPortfolioSnapshot(
        version=1,
        captured_at_wall_ns=0,
        captured_at_mono_ns=0,
        positions_by_ticker={},
        working_orders_by_id={},
        pending_fills_by_id={},
        exchange_exposure_cc=0,
        local_ledger_exposure_cc=0,
        reserved_exposure_cc=0,
        reconciliation_status=ReconciliationStatus.MATCHED,
        source="test",
        source_age_ms=0,
        private_ws_healthy=True,
    )
    published = store.publish(stale)
    assert published is False
    assert store.current().version == 2


# ── collect_all_pages unit tests ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_collect_all_pages_aggregates_multiple_pages():
    """A three-page position list is aggregated with one SourceCompleteness."""
    tickers = [f"KXBTC15M-{i:02d}" for i in range(5)]

    pages = {
        None: {"items": [{"ticker": tickers[0]}, {"ticker": tickers[1]}], "cursor": "c1"},
        "c1": {"items": [{"ticker": tickers[2]}, {"ticker": tickers[3]}], "cursor": "c2"},
        "c2": {"items": [{"ticker": tickers[4]}], "cursor": None},
    }

    async def fetch_page(cursor=None):
        return pages.get(cursor, {"items": [], "cursor": None})

    records, complete = await collect_all_pages("positions_test", fetch_page)
    assert [r["ticker"] for r in records] == tickers
    assert complete.complete is True
    assert complete.pages_fetched == 3
    assert complete.records_fetched == 5


@pytest.mark.asyncio
async def test_collect_all_pages_empty_response_is_complete():
    """A complete empty response is authoritative zero."""
    async def fetch_page(cursor=None):
        return {"items": [], "cursor": None}

    records, complete = await collect_all_pages("empty_test", fetch_page)
    assert records == []
    assert complete.complete is True
    assert complete.records_fetched == 0


@pytest.mark.asyncio
async def test_collect_all_pages_rejects_page_timeout():
    """A failing page is not treated as a complete empty result."""
    async def fetch_page(cursor=None):
        raise TimeoutError("Kalshi slow")

    with pytest.raises(PaginationIncomplete) as exc_info:
        await collect_all_pages("timeout_test", fetch_page)
    assert exc_info.value.error_code == "PAGE_FETCH_FAILED"


@pytest.mark.asyncio
async def test_collect_all_pages_rejects_cursor_loop():
    """A repeated cursor is a pagination loop and must fail."""
    async def fetch_page(cursor=None):
        return {"items": [{"ticker": "loop"}], "cursor": "same"}

    with pytest.raises(PaginationIncomplete) as exc_info:
        await collect_all_pages("loop_test", fetch_page)
    assert exc_info.value.error_code == "CURSOR_LOOP"


@pytest.mark.asyncio
async def test_collect_all_pages_rejects_malformed_response():
    """A response missing ``items`` is not a valid page."""
    async def fetch_page(cursor=None):
        return {"cursor": None}

    with pytest.raises(PaginationIncomplete) as exc_info:
        await collect_all_pages("malformed_test", fetch_page)
    assert exc_info.value.error_code == "MISSING_ITEMS"


@pytest.mark.asyncio
async def test_collect_all_pages_rejects_max_pages():
    """Hitting the maximum page count with more data is incomplete."""
    async def fetch_page(cursor=None):
        return {"items": [{"ticker": "more"}], "cursor": f"c{cursor}"}

    with pytest.raises(PaginationIncomplete) as exc_info:
        await collect_all_pages("max_test", fetch_page, max_pages=2)
    assert exc_info.value.error_code == "MAX_PAGES"
    assert exc_info.value.pages_fetched == 2


@pytest.mark.asyncio
async def test_collect_all_pages_idempotent_duplicates():
    """Identical records across pages are deduplicated without conflict."""
    pages = [
        {"items": [{"id": "a", "ticker": "T"}], "cursor": "c1"},
        {"items": [{"id": "a", "ticker": "T"}], "cursor": None},
    ]
    page_iter = iter(pages)

    async def fetch_page(cursor=None):
        return next(page_iter)

    records, _ = await collect_all_pages("dup_test", fetch_page)
    assert len(records) == 2  # raw collector is append-only; deduplication is downstream


# ── Reconciler pagination tests ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_truncated_positions_result_marks_unknown_pagination():
    """If the exchange positions result is truncated, status is UNKNOWN_PAGINATION."""
    ticker = "KXBTC15M-26AUG192030-30"
    pos = VenuePosition(market_id=ticker, outcome_id="yes", size=Decimal("0.50"), average_entry_price=Decimal("0.50"))

    result = OperationResult.fail(
        PaginationIncomplete("MAX_PAGES"),
        data=[pos],
        metadata={"truncated": True, "pages_fetched": 10, "records_fetched": 1},
    )
    client = _FakeKalshiClient([], [], positions_result=result)
    reconciler = _make_reconciler(client, _FakePositionCache({}), _FakeFillsLedger({}))

    snapshot = await reconciler.build_snapshot()
    assert snapshot.reconciliation_status == ReconciliationStatus.UNKNOWN
    assert snapshot.reconciliation_reason == ReconciliationReason.UNKNOWN_PAGINATION
    assert snapshot.positions_source_complete is not None
    assert snapshot.positions_source_complete.complete is False
    assert snapshot.pagination_complete is False
    assert not snapshot.is_authoritative


@pytest.mark.asyncio
async def test_incomplete_fills_block_authoritative_snapshot():
    """An incomplete fills source makes the snapshot non-authoritative."""
    ticker = "KXBTC15M-26AUG192030-30"
    pos = VenuePosition(market_id=ticker, outcome_id="yes", size=Decimal("0.50"), average_entry_price=Decimal("0.50"))
    fill_result = OperationResult.fail(
        PaginationIncomplete("MAX_PAGES"),
        data=[],
        metadata={"truncated": True, "pages_fetched": 50, "records_fetched": 0},
    )

    client = _FakeKalshiClient([pos], [], fills_result=fill_result)
    cache = _FakePositionCache({
        ticker: _FakeCachedPosition(
            market_id=ticker,
            contracts=0,
            side="yes",
            outcome="yes",
            avg_price_cents=50,
            quantity_cc=50,
        ),
    })
    reconciler = _make_reconciler(client, cache, _FakeFillsLedger({
        ticker: {"side": "yes", "contracts": 0.5, "avg_price_cents": 50},
    }))

    snapshot = await reconciler.build_snapshot()
    assert snapshot.reconciliation_status == ReconciliationStatus.UNKNOWN
    assert snapshot.reconciliation_reason == ReconciliationReason.UNKNOWN_PAGINATION
    assert snapshot.fills_source_complete is not None
    assert snapshot.fills_source_complete.complete is False
    assert not snapshot.is_authoritative


@pytest.mark.asyncio
async def test_complete_empty_response_is_authoritative_zero():
    """A complete, successful empty positions response is zero, not unknown."""
    client = _FakeKalshiClient([], [], positions_result=OperationResult.ok([]))
    reconciler = _make_reconciler(client, _FakePositionCache({}), _FakeFillsLedger({}))

    snapshot = await reconciler.build_snapshot()
    assert snapshot.reconciliation_status == ReconciliationStatus.MATCHED
    assert snapshot.reconciliation_reason == ReconciliationReason.MATCHED
    assert snapshot.positions_source_complete is not None
    assert snapshot.positions_source_complete.complete is True
    assert snapshot.positions_count == 0
    assert snapshot.is_authoritative


@pytest.mark.asyncio
async def test_incomplete_orders_source_blocks_authoritative_snapshot():
    """Working orders must be fully fetched before entries are allowed."""
    ticker = "KXBTC15M-26AUG192030-30"
    order = PlacedOrder(
        order_id="ord-1",
        market_id=ticker,
        side="yes",
        size=Decimal("1.0"),
        price=Decimal("0.50"),
        filled_size=Decimal("0"),
        remaining_size=Decimal("1.0"),
        status="resting",
    )
    orders_result = OperationResult.fail(
        PaginationIncomplete("PAGE_FETCH_FAILED"),
        data=[order],
        metadata={"truncated": True},
    )

    client = _FakeKalshiClient([], [order], open_orders_result=orders_result)
    reconciler = _make_reconciler(client, _FakePositionCache({}), _FakeFillsLedger({}))

    snapshot = await reconciler.build_snapshot()
    assert snapshot.reconciliation_status == ReconciliationStatus.UNKNOWN
    assert snapshot.reconciliation_reason == ReconciliationReason.UNKNOWN_PAGINATION
    assert snapshot.orders_source_complete is not None
    assert snapshot.orders_source_complete.complete is False
    assert not snapshot.is_authoritative


# ── Authority transition instrumentation (2026-08-24) ──────────────────────

@pytest.mark.asyncio
async def test_authority_transition_log_emits_on_mismatch(caplog):
    """A MISMATCH_LEDGER transition emits a structured PORTFOLIO-AUTHORITY-TRANSITION."""
    ticker = "KXBTC15M-26AUG192030-30"
    qty = Decimal("0.62")

    client = _FakeKalshiClient(
        positions=[
            VenuePosition(
                market_id=ticker,
                outcome_id="yes",
                size=qty,
                average_entry_price=Decimal("0.45"),
            )
        ],
        open_orders=[],
    )
    # Ledger is empty → mismatch
    ledger = _FakeFillsLedger({})
    cache = _FakePositionCache({})

    reconciler = _make_reconciler(client, cache, ledger)
    with caplog.at_level(logging.WARNING, logger="merid.event_venues.kalshi.canonical_portfolio_reconciler"):
        snapshot = await reconciler.build_snapshot()

    assert snapshot.reconciliation_status == ReconciliationStatus.MISMATCH
    assert snapshot.reconciliation_reason == ReconciliationReason.MISMATCH_LEDGER
    assert not snapshot.is_authoritative

    transition_records = [
        r for r in caplog.records
        if "PORTFOLIO-AUTHORITY-TRANSITION" in r.getMessage()
    ]
    assert transition_records, "expected PORTFOLIO-AUTHORITY-TRANSITION log"
    record = transition_records[0]
    assert "old_authoritative=True" in record.getMessage()
    assert "new_authoritative=false" in record.getMessage()
    assert record.event == "PORTFOLIO-AUTHORITY-TRANSITION"  # type: ignore[attr-defined]
    assert record.state == "MISMATCH"  # type: ignore[attr-defined]
    assert record.reconcile_attempt == 1  # type: ignore[attr-defined]
    assert record.diff_hash  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_authority_transition_log_contains_position_diff(caplog):
    """The transition log lists exchange/ledger/cache positions and notional."""
    ticker = "KXBTC15M-26AUG192030-30"
    qty = Decimal("0.62")

    client = _FakeKalshiClient(
        positions=[
            VenuePosition(
                market_id=ticker,
                outcome_id="yes",
                size=qty,
                average_entry_price=Decimal("0.45"),
            )
        ],
        open_orders=[],
    )
    ledger = _FakeFillsLedger({})
    cache = _FakePositionCache({})

    reconciler = _make_reconciler(client, cache, ledger)
    with caplog.at_level(logging.WARNING, logger="merid.event_venues.kalshi.canonical_portfolio_reconciler"):
        await reconciler.build_snapshot()

    record = next(
        r for r in caplog.records if "PORTFOLIO-AUTHORITY-TRANSITION" in r.getMessage()
    )
    extra = getattr(record, "exchange_positions", None)
    assert extra is not None
    assert record.exchange_positions[0]["ticker"] == ticker
    assert record.notional_exchange_cents == int(qty * Decimal("100")) * 45
    assert record.state == "MISMATCH"  # type: ignore[attr-defined]
    assert record.diff_hash  # type: ignore[attr-defined]
    assert record.reconcile_attempt == 1  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_authority_transition_resets_first_mismatch_on_recovery(caplog):
    """Transitioning back to authoritative clears the first-mismatch timestamp."""
    ticker = "KXBTC15M-26AUG192030-30"
    qty = Decimal("0.62")
    qcc = int(qty * Decimal("100"))

    # First build: mismatch
    client_mismatch = _FakeKalshiClient(
        positions=[
            VenuePosition(
                market_id=ticker,
                outcome_id="yes",
                size=qty,
                average_entry_price=Decimal("0.45"),
            )
        ],
        open_orders=[],
    )
    ledger_mismatch = _FakeFillsLedger({})
    cache = _FakePositionCache({})
    reconciler = _make_reconciler(client_mismatch, cache, ledger_mismatch)
    await reconciler.build_snapshot()
    assert reconciler._first_mismatch_at_mono is not None

    # Second build: agreement
    client_match = _FakeKalshiClient(
        positions=[
            VenuePosition(
                market_id=ticker,
                outcome_id="yes",
                size=qty,
                average_entry_price=Decimal("0.45"),
            )
        ],
        open_orders=[],
    )
    ledger_match = _FakeFillsLedger({
        ticker: {"side": "yes", "contracts": float(qty), "avg_price_cents": 45},
    })
    cache_match = _FakePositionCache({
        ticker: _FakeCachedPosition(
            market_id=ticker,
            contracts=0,
            side="yes",
            outcome="yes",
            avg_price_cents=45,
            quantity_cc=qcc,
        ),
    })
    reconciler._kalshi_client = client_match
    reconciler._fills_ledger = ledger_match
    reconciler._position_cache = cache_match

    with caplog.at_level(logging.WARNING, logger="merid.event_venues.kalshi.canonical_portfolio_reconciler"):
        snapshot = await reconciler.build_snapshot()

    assert snapshot.reconciliation_status == ReconciliationStatus.MATCHED
    assert snapshot.is_authoritative
    assert reconciler._first_mismatch_at_mono is None

    recovery_records = [
        r for r in caplog.records
        if "PORTFOLIO-AUTHORITY-TRANSITION" in r.getMessage()
        and "new_authoritative=true" in r.getMessage()
    ]
    assert recovery_records
    record = recovery_records[-1]
    assert record.state == "RECOVERED"  # type: ignore[attr-defined]
    assert record.previous_reason == "MISMATCH_LEDGER"  # type: ignore[attr-defined]
    assert record.recovery_latency_ms >= 0  # type: ignore[attr-defined]
    assert record.diff_hash  # type: ignore[attr-defined]
