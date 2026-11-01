"""Regression tests for the 2026-10-09 fill-confirmation lifecycle hardening.

Covers the invariants the poller/ledger lifecycle must hold after the
backgrounded-restore fix (6d7d5dee) and the canonical WS/REST ingestion
convergence:

- ``ensure_loaded`` shares ONE in-flight restore — a second caller (poller
  restore task or an ingest path) never spawns a concurrent load.
- An ingest that arrives while restore is in flight waits for the shared
  restore and then applies — no interleaved writes, no double-apply.
- A provisional ``live_router_`` row restored late cannot undo promotion:
  the merge guard skips fill_ids already in memory, and a stale provisional
  resurrected under a new id is superseded (excluded) rather than refiring
  the unresolved-fill gate.
- An authenticated WS fill promotes a provisional row even when REST never
  delivers the twin (REST-unavailable promotion parity).
- REST catch-up still promotes a provisional the WS stream missed.
- A crashed poller task demotes readiness to DEGRADED with an attributable
  reason, and shutdown cancels/awaits every spawned task (no orphans).
- REST fill pagination walks multiple cursor pages and aggregates.
- A maker admission that resolves taker produces an attributable execution
  contract (lane + resolved mode + reason) instead of a silent conversion.
- The immutable ``ExecutionPolicy`` post-only contract is honored by the
  pre-wire gate predicate.
"""

import asyncio
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal

import pytest


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """Isolated ledger pointed at a tmp SQLite DB."""
    db_path = tmp_path / "kalshi_fills.db"
    monkeypatch.setenv("MERID_FILLS_DB_PATH", str(db_path))
    monkeypatch.setenv("POSTGRES_PASSWORD", "")
    from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger

    return KalshiFillsLedger()


def _provisional(order_id: str, qty_cc: int = 100) -> "KalshiFill":
    """Provisional router-mirror row for a BUY_NO order (delta -qty)."""
    from merid.event_venues.kalshi.fills_ledger import KalshiFill

    return KalshiFill(
        fill_id=f"live_router_{order_id}_0",
        order_id=order_id,
        market_ticker="KXBTC15M-TEST",
        side="no",
        action="buy",
        count_fp=Decimal(qty_cc) / Decimal("100"),
        quantity_cc=qty_cc,
        yes_price_dollars=Decimal("0.30"),
        no_price_dollars=Decimal("0.70"),
        fee_cost=Decimal("0.02"),
        proceeds_dollars=Decimal("-0.72"),
        canonical_position_side="no",
        canonical_position_action="buy",
        canonical_leg_price_cents=70,
        canonical_yes_delta_cc=-qty_cc,
        canonicalization_state="TRUSTED_LIVE_V1",
        is_live=True,
        created_time=datetime.now(timezone.utc),
    )


def _counterparty_raw(fill_id: str, order_id: str, qty_cc: int) -> dict:
    """Exchange fill dict for the same order in counterparty SELL_YES form.

    The user's BUY_NO 100cc arrives from the venue as SELL YES 90cc — the
    parsed canonical delta is -90, matching the provisional's direction.
    """
    return {
        "fill_id": fill_id,
        "trade_id": fill_id,
        "order_id": order_id,
        "market_ticker": "KXBTC15M-TEST",
        "ticker": "KXBTC15M-TEST",
        "side": "yes",
        "action": "sell",
        "outcome_side": "yes",
        "yes_price_dollars": "0.31",
        "no_price_dollars": "0.69",
        "count_fp": str(Decimal(qty_cc) / Decimal("100")),
        "quantity_cc": qty_cc,
        "fee_cost": "0.005",
        "created_time": datetime.now(timezone.utc).isoformat(),
    }


# ── Restore / ingest concurrency ───────────────────────────────────────────


class TestRestoreIngestRace:
    """ensure_loaded() shares a single in-flight restore across all callers."""

    @pytest.mark.asyncio
    async def test_shared_inflight_restore(self, ledger, monkeypatch):
        calls = []
        gate = asyncio.Event()

        async def slow_load():
            calls.append(1)
            await gate.wait()
            ledger._load_complete = True
            return 5

        monkeypatch.setattr(ledger, "load_from_db", slow_load)

        t1 = asyncio.create_task(ledger.ensure_loaded())
        t2 = asyncio.create_task(ledger.ensure_loaded())
        gate.set()

        assert await t1 == 5
        assert await t2 == 5
        assert len(calls) == 1, "two callers must share one restore task"

    @pytest.mark.asyncio
    async def test_ingest_waits_for_inflight_restore(self, ledger, monkeypatch):
        """A WS fill arriving mid-restore applies once, after restore finishes."""
        restore_gate = asyncio.Event()
        order = {"restore_done": False, "ingest_done": False}
        load_calls = []

        async def slow_load():
            load_calls.append(1)
            await restore_gate.wait()
            order["restore_done"] = True
            ledger._load_complete = True
            return 3

        monkeypatch.setattr(ledger, "load_from_db", slow_load)

        async def no_exchange_lookup(*args, **kwargs):
            return None

        monkeypatch.setattr(ledger, "_maybe_halt_on_unmatched_fill", no_exchange_lookup)

        restore_task = asyncio.create_task(ledger.ensure_loaded())
        await asyncio.sleep(0)
        shared_task = ledger._load_task

        async def _ingest():
            ok = await ledger.ingest_ws_fill(
                _counterparty_raw("ws_fill_1", "order-w1", 90)
            )
            order["ingest_done"] = True
            return ok

        ingest_task = asyncio.create_task(_ingest())
        for _ in range(10):
            await asyncio.sleep(0)
        # Ingest is blocked behind the shared restore — same inner task.
        assert shared_task is not None and not shared_task.done()
        assert ledger._load_task is shared_task
        assert order["ingest_done"] is False

        restore_gate.set()
        assert await ingest_task is True
        assert await restore_task == 3
        assert order["restore_done"] and order["ingest_done"]
        assert len(load_calls) == 1

    @pytest.mark.asyncio
    async def test_failed_restore_task_retries_cleanly(self, ledger, monkeypatch):
        attempts = []

        async def flaky_load():
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("simulated restore failure")
            ledger._load_complete = True
            return 2

        monkeypatch.setattr(ledger, "load_from_db", flaky_load)
        with pytest.raises(RuntimeError):
            await ledger.ensure_loaded()
        # The failed task is cleared — the next call retries.
        assert await ledger.ensure_loaded() == 2
        assert len(attempts) == 2


class TestRestoreCompleteness:
    @pytest.mark.asyncio
    async def test_empty_restore_is_complete_and_not_repeated(self, ledger, monkeypatch):
        assert await ledger.ensure_loaded() == 0
        assert ledger._load_complete

        async def unexpected_reload():
            raise AssertionError("complete empty restore must not repeat")

        monkeypatch.setattr(ledger, "load_from_db", unexpected_reload)
        assert await ledger.ensure_loaded() == 0

    @pytest.mark.asyncio
    async def test_restore_limit_is_reported_as_incomplete(self, ledger, monkeypatch):
        import merid.event_venues.kalshi.fills_ledger as ledger_module

        monkeypatch.setattr(ledger_module, "_FILLS_RESTORE_MAX_ROWS", 2)
        await ledger._init_db()
        with sqlite3.connect(ledger._db_path) as conn:
            conn.executemany(
                "INSERT INTO kalshi_fills (fill_id, market_ticker, created_time) VALUES (?, ?, ?)",
                [(f"venue_{i}", "KXBTC15M-TEST", datetime.now(timezone.utc).isoformat())
                 for i in range(3)],
            )
        assert await ledger.ensure_loaded() == 0
        assert not ledger._load_complete
        assert "complete history was not loaded" in ledger._last_load_error
        assert not ledger._fills


class TestDurableFillProvenance:
    def test_unknown_provisional_provenance_remains_unresolved(self, ledger):
        fill = _provisional("order-unknown")
        fill.is_live = None
        ledger._fills[fill.fill_id] = fill
        assert ledger.unresolved_router_fills() == [fill]

    @pytest.mark.asyncio
    async def test_sqlite_round_trip_preserves_safety_flags(self, ledger):
        from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger

        await ledger._init_db()
        fill = _provisional("order-provenance")
        fill.fill_id = "venue-provenance"
        fill.ingestion_source = "http_poller"
        fill.is_live = True
        fill.unmatched = True
        fill.unmatched_reason = "identity_unresolved"
        fill.derived_id = True
        fill.confirmed_by_rest = True
        fill.side_conflict = True
        fill.side_conflict_reason = "conflicting_sides"
        fill.exposure_mismatch = True
        fill.exchange_index = 2
        await ledger._flush_to_sqlite([fill])

        restored = KalshiFillsLedger()
        assert await restored.load_from_db() == 1
        actual = restored._fills[fill.fill_id]
        assert actual.is_live is True
        assert actual.unmatched and actual.unmatched_reason == "identity_unresolved"
        assert actual.derived_id and actual.confirmed_by_rest
        assert actual.side_conflict and actual.side_conflict_reason == "conflicting_sides"
        assert actual.exposure_mismatch and actual.exchange_index == 2

    @pytest.mark.asyncio
    async def test_legacy_null_provenance_stays_unknown(self, ledger):
        await ledger._init_db()
        with sqlite3.connect(ledger._db_path) as conn:
            conn.execute(
                """INSERT INTO kalshi_fills
                   (fill_id, market_ticker, side, action, count_fp, quantity_cc,
                    created_time, canonical_position_side, canonical_position_action,
                    canonical_yes_delta_cc, canonicalization_state)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("venue-legacy", "KXBTC15M-TEST", "yes", "buy", "1", 100,
                 datetime.now(timezone.utc).isoformat(), "yes", "buy", 100,
                 "TRUSTED_LIVE_V1"),
            )
        assert await ledger.load_from_db() == 1
        restored = ledger._fills["venue-legacy"]
        assert restored.is_live is None
        assert restored.unmatched
        assert restored.unmatched_reason == "legacy_identity_unverified"


class TestLateRestoredProvisional:
    """A stale DB row arriving after promotion cannot resurrect the gate."""

    def test_resurrected_provisional_is_excluded_not_provisional(self, ledger):
        order_id = "order-promoted-1"
        prov = _provisional(order_id)
        auth = _provisional(order_id)
        # Simulate promotion: provisional renamed to the authoritative id.
        auth.fill_id = "auth_venue_1"
        auth.trade_id = "auth_venue_1"
        auth.ingestion_source = "websocket"
        ledger._fills[auth.fill_id] = auth
        ledger._index_fill(auth)

        # A restore (or any late path) re-inserts the stale provisional row.
        ledger._fills[prov.fill_id] = prov
        ledger._index_fill(prov)

        # The resurrected provisional is superseded by the authoritative
        # sibling — never provisional, never gate-firing.
        assert ledger._canonical_fill_class(prov) == "excluded"
        assert ledger.unresolved_router_fills() == []
        view = ledger.get_canonical_fills()
        assert [f.fill_id for f in view.authoritative] == ["auth_venue_1"]

    @pytest.mark.asyncio
    async def test_real_db_merge_preserves_inmemory_promotion(self, ledger):
        """End-to-end: DB holds the stale provisional; memory holds the
        promoted authoritative fill; load must not revert it."""
        order_id = "order-merge-1"
        prov_id = f"live_router_{order_id}_0"

        # Seed a real SQLite DB with the stale provisional row.
        await ledger._init_db()
        conn = sqlite3.connect(ledger._db_path)
        try:
            conn.execute(
                """INSERT INTO kalshi_fills
                   (fill_id, order_id, market_ticker, side, action,
                    count_fp, quantity_cc, yes_price_dollars, no_price_dollars,
                    fee_cost, created_time, ingestion_source)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    prov_id, order_id, "KXBTC15M-TEST", "no", "buy",
                    "1.0", 100, "0.30", "0.70", "0.02",
                    datetime.now(timezone.utc).isoformat(), "order_router",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        # In-memory state already promoted: authoritative fill for the order.
        auth = _provisional(order_id)
        auth.fill_id = "auth_venue_m1"
        auth.trade_id = "auth_venue_m1"
        auth.ingestion_source = "websocket"
        auth.confirmed_by_rest = True
        ledger._fills[auth.fill_id] = auth
        ledger._index_fill(auth)
        ledger._live_router_fill_ids[order_id] = auth.fill_id

        loaded = await ledger.load_from_db()
        assert loaded >= 1
        # The in-memory authoritative row is untouched.
        assert ledger._fills["auth_venue_m1"].confirmed_by_rest is True
        # The restored stale provisional is superseded — gate stays clear.
        assert ledger.unresolved_router_fills() == []


# ── Canonical WS/REST ingestion ────────────────────────────────────────────


class TestCanonicalIngestionPaths:
    """WS and REST fills converge on the same promotion path."""

    @pytest.mark.asyncio
    async def test_ws_promotes_provisional_without_rest(self, ledger):
        """REST-unavailable: the WS fill alone must merge+promote the
        provisional row (fees, provenance, id rekey) — not merely supersede."""
        order_id = "order-ws-promo"
        prov = _provisional(order_id)
        ledger._fills[prov.fill_id] = prov
        ledger._live_router_fill_ids[order_id] = prov.fill_id
        ledger._index_fill(prov)

        ok = await ledger.ingest_ws_fill(
            _counterparty_raw("ws_venue_fill_1", order_id, 90)
        )
        # Consumed by promotion — not a duplicate ledger row.
        assert ok is False
        assert "live_router_" not in "\n".join(ledger._fills.keys())
        promoted = ledger._fills["ws_venue_fill_1"]
        assert promoted.confirmed_by_rest is True
        assert promoted.ingestion_source == "websocket"
        assert promoted.quantity_cc == 90  # authoritative partial qty overlaid
        assert ledger.unresolved_router_fills() == []

    @pytest.mark.asyncio
    async def test_rest_catches_fill_missed_by_ws(self, ledger):
        order_id = "order-rest-promo"
        prov = _provisional(order_id)
        ledger._fills[prov.fill_id] = prov
        ledger._live_router_fill_ids[order_id] = prov.fill_id
        ledger._index_fill(prov)

        new_count, new_ids = await ledger.ingest_http_fills(
            [_counterparty_raw("http_venue_fill_1", order_id, 100)],
            {},
        )
        # The fill was consumed by promotion — no net-new canonical row.
        assert "http_venue_fill_1" in ledger._fills
        promoted = ledger._fills["http_venue_fill_1"]
        assert promoted.confirmed_by_rest is True
        assert promoted.quantity_cc == 100
        assert ledger.unresolved_router_fills() == []

    @pytest.mark.asyncio
    async def test_ws_then_rest_same_fill_not_double_applied(self, ledger):
        """A fill confirmed by WS then redelivered by REST applies once."""
        raw = _counterparty_raw("dup_fill_1", "order-dup", 50)
        assert await ledger.ingest_ws_fill(dict(raw)) is True
        # REST twin: same fill_id → dedupe drop, no second mutation.
        count_before = len(ledger._fills)
        new_count, _ = await ledger.ingest_http_fills([dict(raw)], {})
        assert len(ledger._fills) == count_before
        assert ledger._processed_fill_ids.__contains__("dup_fill_1")


# ── Poller lifecycle ───────────────────────────────────────────────────────


class TestPollerLifecycle:
    """Readiness reflects task health; shutdown leaves no orphans."""

    @pytest.mark.asyncio
    async def test_incomplete_restore_degrades_even_when_zero_is_returned(
        self, ledger, monkeypatch
    ):
        from merid.event_venues.kalshi import fills_poller as fp_mod

        monkeypatch.setattr(
            "merid.event_venues.kalshi.fills_ledger.get_fills_ledger",
            lambda: ledger,
        )

        async def incomplete_restore():
            ledger._load_complete = False
            ledger._last_load_error = "complete history was not loaded"
            return 0

        monkeypatch.setattr(ledger, "ensure_loaded", incomplete_restore)
        poller = fp_mod.FillsPoller()

        async def idle():
            await poller._shutdown.wait()

        for name in ("_poll_loop", "_reconcile_loop", "_backfill_loop", "_cache_cleanup_loop"):
            monkeypatch.setattr(poller, name, idle)
        await poller.start()
        try:
            await poller._restore_task
            await asyncio.sleep(0)
            poller._first_reconcile_done = True
            poller._transition_readiness()
            assert poller._readiness == "DEGRADED"
            assert not poller._restore_done
            assert "restore_incomplete" in poller._degraded_reason
        finally:
            await poller.stop()

    @pytest.mark.asyncio
    async def test_crashed_poll_task_demotes_readiness(
        self, ledger, monkeypatch
    ):
        from merid.event_venues.kalshi import fills_poller as fp_mod
        from merid.event_venues.kalshi.fills_ledger import (
            get_fills_ledger as _real_get,
        )

        # Route the poller's ledger access at the isolated test ledger.
        monkeypatch.setattr(
            "merid.event_venues.kalshi.fills_ledger.get_fills_ledger",
            lambda: ledger,
        )
        poller = fp_mod.FillsPoller()

        async def _boom():
            raise RuntimeError("simulated poll loop crash")

        async def _idle():
            await poller._shutdown.wait()

        monkeypatch.setattr(poller, "_poll_loop", _boom)
        for name in ("_reconcile_loop", "_backfill_loop", "_cache_cleanup_loop"):
            monkeypatch.setattr(poller, name, _idle)
        ledger._loaded_count = 1  # skip real DB load
        ledger._load_complete = True

        await poller.start()
        # Let the crashed task's done-callback run.
        for _ in range(10):
            await asyncio.sleep(0)
            if poller._degraded_reason:
                break
        try:
            assert poller._readiness == "DEGRADED"
            assert poller._degraded_reason is not None
            assert "fills-poller" in poller._degraded_reason
            ready = poller.readiness()
            assert ready["state"] == "DEGRADED"
            assert ready["task_states"]["poll"] == "crashed"
        finally:
            await poller.stop()

    @pytest.mark.asyncio
    async def test_shutdown_cancels_all_tasks(self, ledger, monkeypatch):
        from merid.event_venues.kalshi import fills_poller as fp_mod

        monkeypatch.setattr(
            "merid.event_venues.kalshi.fills_ledger.get_fills_ledger",
            lambda: ledger,
        )
        ledger._loaded_count = 1
        ledger._load_complete = True
        poller = fp_mod.FillsPoller()

        async def _idle():
            await poller._shutdown.wait()

        for name in ("_poll_loop", "_reconcile_loop", "_backfill_loop", "_cache_cleanup_loop"):
            monkeypatch.setattr(poller, name, _idle)
        await poller.start()

        tasks = [
            poller._poll_task,
            poller._reconcile_task,
            poller._backfill_task,
            poller._cache_cleanup_task,
            poller._restore_task,
        ]
        assert all(t is not None for t in tasks)
        await poller.stop()
        for t in tasks:
            assert t is None or t.done() or t.cancelled(), (
                f"orphan task after stop(): {t}"
            )

    @pytest.mark.asyncio
    async def test_readiness_progression_to_ready(self, ledger, monkeypatch):
        """READY requires restore done AND first reconcile done."""
        from merid.event_venues.kalshi import fills_poller as fp_mod

        monkeypatch.setattr(
            "merid.event_venues.kalshi.fills_ledger.get_fills_ledger",
            lambda: ledger,
        )
        ledger._loaded_count = 1
        ledger._load_complete = True
        poller = fp_mod.FillsPoller()

        async def _idle():
            await poller._shutdown.wait()

        for name in ("_poll_loop", "_reconcile_loop", "_backfill_loop", "_cache_cleanup_loop"):
            monkeypatch.setattr(poller, name, _idle)
        assert poller._readiness == "STARTING"
        await poller.start()
        try:
            for _ in range(200):
                await asyncio.sleep(0.05)
                if poller._restore_done:
                    break
            assert poller._restore_done is True
            # Before the first reconcile: RECONCILING, not READY.
            if not poller._first_reconcile_done:
                assert poller._readiness == "RECONCILING"
            poller._first_reconcile_done = True
            poller._transition_readiness()
            assert poller._readiness == "READY"
        finally:
            await poller.stop()


# ── REST pagination ────────────────────────────────────────────────────────


class TestRestPagination:
    """client.get_fills walks cursor pages and aggregates the results."""

    @pytest.mark.asyncio
    async def test_multi_page_aggregation(self):
        from merid.event_venues.kalshi.client import KalshiVenueClient
        from merid.resilience.result import OperationResult

        client = object.__new__(KalshiVenueClient)
        calls = []

        async def fake_request(method, path, params=None, operation_name=None):
            page = len(calls)
            calls.append(dict(params or {}))
            if page == 0:
                return OperationResult.ok(
                    {"fills": [{"fill_id": "f1"}], "cursor": "cur_a"}
                )
            if page == 1:
                return OperationResult.ok(
                    {"fills": [{"fill_id": "f2"}], "cursor": "cur_b"}
                )
            return OperationResult.ok({"fills": [{"fill_id": "f3"}]})

        client._request_with_resilience = fake_request
        result = await client.get_fills(limit=200, since_ts=123)

        assert result.success
        assert [f["fill_id"] for f in result.data] == ["f1", "f2", "f3"]
        assert len(calls) == 3
        assert calls[0].get("cursor") is None
        assert calls[1]["cursor"] == "cur_a"
        assert calls[2]["cursor"] == "cur_b"

    @pytest.mark.asyncio
    async def test_empty_page_with_cursor_continues(self):
        """A continuation cursor is not proof that a short page is terminal."""
        from merid.event_venues.kalshi.client import KalshiVenueClient
        from merid.resilience.result import OperationResult

        client = object.__new__(KalshiVenueClient)
        calls = []

        async def fake_request(method, path, params=None, operation_name=None):
            calls.append(1)
            if len(calls) == 1:
                return OperationResult.ok(
                    {"fills": [{"fill_id": "f1"}], "cursor": "cur_x"}
                )
            if len(calls) == 2:
                return OperationResult.ok({"fills": [], "cursor": "cur_y"})
            return OperationResult.ok({"fills": [{"fill_id": "f2"}], "cursor": None})

        client._request_with_resilience = fake_request
        result = await client.get_fills(limit=200)
        assert result.success
        assert [f["fill_id"] for f in result.data] == ["f1", "f2"]
        assert len(calls) == 3

    @pytest.mark.asyncio
    @pytest.mark.parametrize("since_ts", [1793457600, 1793457600123])
    async def test_since_timestamp_is_sent_in_seconds(self, since_ts):
        from merid.event_venues.kalshi.client import KalshiVenueClient
        from merid.resilience.result import OperationResult

        client = object.__new__(KalshiVenueClient)
        calls = []

        async def fake_request(method, path, params=None, operation_name=None):
            calls.append(params)
            return OperationResult.ok({"fills": [], "cursor": None})

        client._request_with_resilience = fake_request
        result = await client.get_fills(since_ts=since_ts)
        assert result.success
        assert calls[0]["min_ts"] == 1793457600

    @pytest.mark.asyncio
    async def test_partial_failure_is_not_complete(self):
        from merid.event_venues.kalshi.client import KalshiVenueClient
        from merid.resilience.result import OperationResult

        client = object.__new__(KalshiVenueClient)
        calls = []

        async def fake_request(method, path, params=None, operation_name=None):
            calls.append(params)
            if len(calls) == 1:
                return OperationResult.ok({"fills": [{"fill_id": "f1"}], "cursor": "next"})
            return OperationResult.fail(RuntimeError("page failed"))

        client._request_with_resilience = fake_request
        result = await client.get_fills()
        assert not result.success
        assert result.metadata["truncated"]
        assert result.data == [{"fill_id": "f1"}]

    @pytest.mark.asyncio
    async def test_repeated_cursor_fails_closed(self):
        from merid.event_venues.kalshi.client import KalshiVenueClient
        from merid.resilience.result import OperationResult

        client = object.__new__(KalshiVenueClient)

        async def fake_request(method, path, params=None, operation_name=None):
            return OperationResult.ok({"fills": [], "cursor": "same"})

        client._request_with_resilience = fake_request
        result = await client.get_fills()
        assert not result.success
        assert result.metadata["truncated"]
        assert result.error.error_code == "REPEATED_CURSOR"

    @pytest.mark.asyncio
    async def test_port_propagates_failed_fills_lookup(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from merid.event_venues.kalshi.venue_client_port import KalshiVenueClientExecutionPort
        from merid.resilience.result import OperationResult

        client = SimpleNamespace(get_fills=AsyncMock(
            return_value=OperationResult.fail(RuntimeError("offline")),
        ))
        port = KalshiVenueClientExecutionPort(client)
        with pytest.raises(RuntimeError, match="fills lookup failed"):
            await port.get_fills()

    @pytest.mark.asyncio
    async def test_open_orders_queries_resting_status(self):
        from merid.event_venues.kalshi.client import KalshiVenueClient
        from merid.resilience.result import OperationResult

        client = object.__new__(KalshiVenueClient)
        calls = []

        async def fake_request(method, path, params=None, operation_name=None):
            calls.append(params)
            return OperationResult.ok({"orders": [], "cursor": None})

        client._request_with_resilience = fake_request
        result = await client.get_open_orders_result()
        assert result.success
        assert calls[0]["status"] == "resting"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("operation,method", [
        ("get_open_orders", "get_open_orders_result"),
        ("get_positions", "get_positions_result"),
    ])
    async def test_port_does_not_treat_failed_account_lookup_as_flat(self, operation, method):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from merid.event_venues.kalshi.venue_client_port import KalshiVenueClientExecutionPort
        from merid.resilience.result import OperationResult

        client = SimpleNamespace(**{method: AsyncMock(
            return_value=OperationResult.fail(RuntimeError("offline")),
        )})
        port = KalshiVenueClientExecutionPort(client)
        with pytest.raises(RuntimeError, match="lookup failed"):
            await getattr(port, operation)()


# ── Execution-mode contract ────────────────────────────────────────────────


class TestExecutionContract:
    """The resolved execution contract attributes every maker->taker path."""

    def _intent(self, **kw):
        from merid.event_venues.kalshi.order_router import OrderIntent

        base = dict(
            ticker="KXBTC15M-TEST",
            price_cents=55,
            count=1,
            side="no",
            action="buy",
        )
        base.update(kw)
        return OrderIntent(**base)

    def test_maker_admission_resolving_taker_is_attributed(self):
        from merid.event_venues.kalshi.order_router import _execution_contract

        intent = self._intent(
            post_only=False,
            aggressiveness=1.0,
            time_in_force="ioc",
            expected_role="maker",
            decision_id="cand_abc:maker",
        )
        c = _execution_contract(intent)
        assert c["admission_lane"] == "maker"
        assert c["resolved_execution_mode"] == "taker"
        assert c["resolution_reason"] == "marketable_posture_overrides_maker_policy"
        assert c["selected_side_limit"] == 55
        assert "chase_cap" in c and "economic_cap" in c

    def test_maker_admission_staying_maker_has_policy_reason(self):
        from merid.event_venues.kalshi.order_router import _execution_contract

        intent = self._intent(
            post_only=True,
            aggressiveness=0.0,
            time_in_force="gtc",
            expected_role="maker",
        )
        c = _execution_contract(intent)
        assert c["admission_lane"] == "maker"
        assert c["resolved_execution_mode"] in ("maker", "passive_quote")
        assert c["resolution_reason"] == "policy_role:maker"

    def test_admission_lane_from_decision_id_route(self):
        from merid.event_venues.kalshi.order_router import _execution_contract

        intent = self._intent(decision_id="cand_zzz:taker")
        c = _execution_contract(intent)
        assert c["admission_lane"] == "taker"

    def test_apply_execution_mode_updates_contract(self, monkeypatch):
        from merid.event_venues.kalshi.order_router import (
            _apply_execution_mode,
            _execution_contract,
        )

        # Maker-enabled env so the coercion does not fire.
        monkeypatch.setenv("MERID_ENTRY_MAKER_ENABLED", "1")
        intent = self._intent(
            post_only=True,
            aggressiveness=0.0,
            time_in_force="gtc",
            expected_role="maker",
        )
        post_only, aggr, _, tif = _apply_execution_mode(intent)
        c = _execution_contract(intent)
        assert c["resolved_execution_mode"] in ("maker", "passive_quote")
        assert c["post_only"] is True
        assert post_only is True and aggr == 0.0

    def test_post_only_policy_lane_requires_post_only(self):
        """A bounded lane's immutable post-only contract is enforced by the
        pre-wire predicate — a post_only=False intent under it rejects."""
        from merid.event_venues.kalshi.order_router import (
            ExecutionPolicy,
            _intent_requires_post_only,
        )

        intent = self._intent(
            post_only=False,
            aggressiveness=1.0,
            time_in_force="ioc",
        )
        intent.execution_policy = ExecutionPolicy(
            lane="threshold_cell",
            required_post_only=True,
            required_liquidity_role="maker",
            allow_taker_fallback=False,
        )
        assert _intent_requires_post_only(intent) is True
        assert not intent.post_only  # the pre-wire gate rejects this pair

        # Contract exposes the immutable policy requirements.
        from merid.event_venues.kalshi.order_router import _execution_contract

        c = _execution_contract(intent)
        assert c["admission_lane"] == "threshold_cell"
        assert c["required_post_only"] is True
        assert c["allow_taker_fallback"] is False


# ── Revalidation veto provenance ───────────────────────────────────────────


class TestRevalidationVetoProvenance:
    """Every stale-decision veto logs the accumulated fresh-input context."""

    @pytest.mark.asyncio
    async def test_veto_logs_provenance_fields(self, caplog, monkeypatch):
        from merid.event_venues.kalshi import order_router as or_mod

        # Force the fresh-book fetch to fail so the earliest veto fires.
        monkeypatch.setattr(
            "merid.event_venues.kalshi.port.get_kalshi_execution_port",
            lambda: (_ for _ in ()).throw(RuntimeError("no port")),
            raising=False,
        )
        intent = or_mod.OrderIntent(
            ticker="KXBTC15M-TEST",
            price_cents=55,
            count=1,
            side="no",
            action="buy",
            ev_net_cents=5.0,
            selected_outcome_price_cents=55,
            p_selected=0.70,
        )
        import logging

        with caplog.at_level(logging.WARNING):
            res = await or_mod._revalidate_entry_economics(
                intent, mode=None, t0=__import__("time").monotonic()
            )
        assert res.status == "rejected"
        assert "stale_decision_refresh_failed" in res.reason
        veto_lines = [
            r.message
            for r in caplog.records
            if "EXEC-REVALIDATION-VETO" in r.message
        ]
        assert veto_lines, "veto must emit the provenance record"
        line = veto_lines[0]
        for field in (
            "reason=", "sel_px", "exec_px", "p_sel0", "ev_new", "spot",
        ):
            assert field in line

# ── Test-environment isolation guards ───────────────────────────────────────
#
# 2026-10-09 incident: a non-isolated verification harness let an unmatched
# test fill (fill_id "dup1", order "o7", ticker KXBTC15M-TEST) reach the REAL
# trading circuit breaker, which persisted a halt to data/ that survived the
# process and gated every live cycle after the next restart.  These guards
# make that class of leak structurally impossible.


class TestTestEnvIsolation:
    @pytest.mark.asyncio
    async def test_ledger_refuses_prod_db_under_testing_env(
        self, tmp_path, monkeypatch
    ):
        """MERID_ENV=testing + production db path must raise, not write."""
        monkeypatch.setenv("MERID_ENV", "testing")
        monkeypatch.setenv(
            "MERID_FILLS_DB_PATH", "data/kalshi_fills.db"
        )
        monkeypatch.setenv("POSTGRES_PASSWORD", "")
        from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger

        # Construction itself must fail fast — a test pointed at the prod DB
        # never gets to the lazy _init_db write path.
        with pytest.raises(RuntimeError, match="production data"):
            KalshiFillsLedger()

    def test_breaker_halt_write_refuses_default_path(self, monkeypatch):
        monkeypatch.setenv("MERID_ENV", "testing")
        monkeypatch.delenv("MERID_CB_HALT_STATE_PATH", raising=False)
        from merid.governance import trading_circuit_breaker as tcb

        rec = tcb.HaltRecord(reason="t", timestamp=tcb._now())
        with pytest.raises(RuntimeError, match="MERID_CB_HALT_STATE_PATH"):
            tcb._save_halt_record(rec)

    def test_breaker_watermark_write_refuses_default_path(self, monkeypatch):
        monkeypatch.setenv("MERID_ENV", "testing")
        monkeypatch.delenv("MERID_CB_HTTP_WATERMARK_PATH", raising=False)
        from merid.governance import trading_circuit_breaker as tcb

        with pytest.raises(RuntimeError, match="MERID_CB_HTTP_WATERMARK_PATH"):
            tcb._save_watermark(tcb._now())

    @pytest.mark.asyncio
    async def test_ledger_allows_redirected_test_db(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MERID_ENV", "testing")
        monkeypatch.setenv(
            "MERID_FILLS_DB_PATH", str(tmp_path / "kalshi_fills.db")
        )
        monkeypatch.setenv("POSTGRES_PASSWORD", "")
        from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger

        ledger = KalshiFillsLedger()
        await ledger._init_db()  # must not raise
        assert (tmp_path / "kalshi_fills.db").exists()
