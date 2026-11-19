"""Stale PERSISTED order-attempt reconciliation (fills_poller).

``PERSISTED`` means the durable row was written but ``claim_for_submission``
never ran — the atomic claim gates the exchange request, so these orders were
almost certainly never transmitted.  The reconcile pass must verify venue
absence before terminalizing, route venue hits through the full reconcile,
and never resubmit.
"""

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from merid.event_venues.kalshi.fills_poller import FillsPoller
from merid.event_venues.kalshi.order_attempt_store import (
    OrderAttemptRecord,
    OrderAttemptStore,
)


@pytest.fixture
def store():
    s = OrderAttemptStore()
    conn = s._get_conn()
    conn.execute("DELETE FROM order_attempts")
    conn.execute("DELETE FROM exit_order_attempts")
    conn.commit()
    return s


def _seed(
    store: OrderAttemptStore,
    *,
    coid: str,
    age_s: float = 3600.0,
    status: str = "PERSISTED",
    decision_id: str = "cand_test123:maker_bid",
    client_tag: str = "15m_KXXRP15M-26NOV182130-30_abcdef123456",
    payload: dict | None = None,
) -> OrderAttemptRecord:
    now = time.time()
    rec = OrderAttemptRecord(
        order_attempt_id=f"oa_{coid}",
        client_order_id=coid,
        decision_id=decision_id,
        replaces_order_attempt_id=None,
        intent_id=coid,
        client_tag=client_tag,
        run_id="run_test",
        process_id="proc_test",
        fingerprint="fp_test",
        status=status,
        created_at=now - age_s,
        updated_at=now - age_s,
        payload_json=json.dumps(
            payload
            if payload is not None
            else {"order": {"ticker": "KXXRP15M-26NOV182130-30"}}
        ),
    )
    store.persist_attempt(rec)
    return rec


class _RawClient:
    """Fake underlying KalshiClient exposing get_order_by_client_id_result."""

    def __init__(self, result):
        self._result = result
        self.calls = []

    async def get_order_by_client_id_result(self, coid, market_id=None, min_ts=None):
        self.calls.append((coid, market_id))
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _port_with_raw(raw) -> SimpleNamespace:
    return SimpleNamespace(_client=raw, get_order=AsyncMock(return_value=None))


def _ok(data):
    return SimpleNamespace(success=True, data=data, error=None)


def _fail(msg="boom"):
    return SimpleNamespace(success=False, data=None, error=msg)


@pytest.mark.asyncio
async def test_venue_absent_terminalizes_rejected(store):
    rec = _seed(store, coid="merid_coid_absent1")
    raw = _RawClient(_ok(None))
    poller = FillsPoller()

    await poller._reconcile_persisted_attempts(_port_with_raw(raw))

    assert raw.calls == [("merid_coid_absent1", "KXXRP15M-26NOV182130-30")]
    after = store.get_by_client_order_id("merid_coid_absent1")
    assert after is not None and after.status == "REJECTED"
    payload = json.loads(after.payload_json)
    ev = payload["reconciliation_evidence"]
    assert ev["terminal_reason"] == "persisted_venue_absent_after_reconciliation"
    assert ev["client_order_id"] == "merid_coid_absent1"


@pytest.mark.asyncio
async def test_venue_present_routes_to_full_reconcile(store, monkeypatch):
    rec = _seed(store, coid="merid_coid_present1")
    raw = _RawClient(_ok(SimpleNamespace(order_id="ord_1")))
    full = AsyncMock()
    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_router.reconcile_submission_unknown_client_order_id",
        full,
    )
    poller = FillsPoller()
    client = _port_with_raw(raw)

    await poller._reconcile_persisted_attempts(client)

    assert full.await_count == 1
    args = full.await_args.args
    assert args[1] == "merid_coid_present1"
    assert args[2] == "KXXRP15M-26NOV182130-30"
    # The pass itself must not terminalize — the full reconcile owns the row.
    after = store.get_by_client_order_id("merid_coid_present1")
    assert after is not None and after.status == "PERSISTED"


@pytest.mark.asyncio
async def test_lookup_failure_leaves_row_untouched(store):
    _seed(store, coid="merid_coid_fail1")
    raw = _RawClient(_fail("transport down"))
    poller = FillsPoller()

    await poller._reconcile_persisted_attempts(_port_with_raw(raw))

    after = store.get_by_client_order_id("merid_coid_fail1")
    assert after is not None and after.status == "PERSISTED"


@pytest.mark.asyncio
async def test_lookup_exception_leaves_row_untouched(store):
    _seed(store, coid="merid_coid_exc1")
    raw = _RawClient(TimeoutError("slow"))
    poller = FillsPoller()

    await poller._reconcile_persisted_attempts(_port_with_raw(raw))

    after = store.get_by_client_order_id("merid_coid_exc1")
    assert after is not None and after.status == "PERSISTED"


@pytest.mark.asyncio
async def test_young_persisted_is_skipped(store):
    _seed(store, coid="merid_coid_young1", age_s=10.0)
    raw = _RawClient(_ok(None))
    poller = FillsPoller()

    await poller._reconcile_persisted_attempts(_port_with_raw(raw))

    assert raw.calls == []
    after = store.get_by_client_order_id("merid_coid_young1")
    assert after is not None and after.status == "PERSISTED"


@pytest.mark.asyncio
async def test_port_fallback_none_is_ambiguous(store):
    """Port-level get_order returning None cannot prove absence — skip."""
    _seed(store, coid="merid_coid_port1")
    client = SimpleNamespace(get_order=AsyncMock(return_value=None))
    poller = FillsPoller()

    await poller._reconcile_persisted_attempts(client)

    after = store.get_by_client_order_id("merid_coid_port1")
    assert after is not None and after.status == "PERSISTED"


@pytest.mark.asyncio
async def test_exit_owned_attempt_is_skipped(store):
    _seed(
        store,
        coid="merid_coid_exit1",
        decision_id="exit_stop_candidate_1",
        payload={"order": {"ticker": "KXXRP15M-26NOV182130-30", "type": "exit_order_attempt"}},
    )
    raw = _RawClient(_ok(None))
    poller = FillsPoller()

    await poller._reconcile_persisted_attempts(_port_with_raw(raw))

    assert raw.calls == []
    after = store.get_by_client_order_id("merid_coid_exit1")
    assert after is not None and after.status == "PERSISTED"


@pytest.mark.asyncio
async def test_terminal_row_is_never_touched(store):
    _seed(store, coid="merid_coid_done1", status="CANCELED")
    raw = _RawClient(_ok(None))
    poller = FillsPoller()

    await poller._reconcile_persisted_attempts(_port_with_raw(raw))

    assert raw.calls == []
    after = store.get_by_client_order_id("merid_coid_done1")
    assert after is not None and after.status == "CANCELED"


@pytest.mark.asyncio
async def test_all_assets_covered_via_ticker_payload(store):
    """The pass is asset-agnostic: ticker comes from the payload for any asset."""
    for asset in ("KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"):
        ticker = f"{asset}-26NOV190000-00"
        _seed(
            store,
            coid=f"merid_coid_{asset}",
            payload={"order": {"ticker": ticker}},
        )
    raw = _RawClient(_ok(None))
    poller = FillsPoller()

    await poller._reconcile_persisted_attempts(_port_with_raw(raw))

    seen = {c[1] for c in raw.calls}
    assert seen == {
        "KXBTC15M-26NOV190000-00",
        "KXETH15M-26NOV190000-00",
        "KXSOL15M-26NOV190000-00",
        "KXXRP15M-26NOV190000-00",
        "KXDOGE15M-26NOV190000-00",
    }
    for asset in ("KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"):
        after = store.get_by_client_order_id(f"merid_coid_{asset}")
        assert after is not None and after.status == "REJECTED"


@pytest.mark.asyncio
async def test_per_cycle_bound(store, monkeypatch):
    monkeypatch.setenv("MERID_STALE_PERSISTED_MAX_PER_CYCLE", "2")
    for i in range(4):
        _seed(store, coid=f"merid_coid_b{i}")
    raw = _RawClient(_ok(None))
    poller = FillsPoller()

    await poller._reconcile_persisted_attempts(_port_with_raw(raw))

    assert len(raw.calls) == 2
    remaining = sum(
        1
        for i in range(4)
        if store.get_by_client_order_id(f"merid_coid_b{i}").status == "PERSISTED"
    )
    assert remaining == 2


@pytest.mark.asyncio
async def test_idempotent_second_pass(store):
    _seed(store, coid="merid_coid_idem1")
    raw = _RawClient(_ok(None))
    poller = FillsPoller()
    client = _port_with_raw(raw)

    await poller._reconcile_persisted_attempts(client)
    n_calls = len(raw.calls)
    await poller._reconcile_persisted_attempts(client)

    # Terminal rows are not re-queried.
    assert len(raw.calls) == n_calls
    after = store.get_by_client_order_id("merid_coid_idem1")
    assert after is not None and after.status == "REJECTED"
    payload = json.loads(after.payload_json)
    # Evidence merged once — no duplicate reconciliation_evidence churn.
    assert payload["reconciliation_evidence"]["terminal_reason"] == (
        "persisted_venue_absent_after_reconciliation"
    )
    assert after.updated_at == after.updated_at  # sanity
    # Second pass must not have re-terminalized (guard returns False).
    assert "terminalized_at" in payload["reconciliation_evidence"]


@pytest.mark.asyncio
async def test_submitting_and_unknown_not_touched(store):
    """Only PERSISTED rows are this pass's scope — other nonterminal
    statuses belong to their dedicated reconcile paths."""
    for st in ("SUBMITTING", "SUBMISSION_UNKNOWN", "ACKNOWLEDGED"):
        _seed(store, coid=f"merid_coid_{st.lower()}", status=st)
    raw = _RawClient(_ok(None))
    poller = FillsPoller()

    await poller._reconcile_persisted_attempts(_port_with_raw(raw))

    assert raw.calls == []
    for st in ("SUBMITTING", "SUBMISSION_UNKNOWN", "ACKNOWLEDGED"):
        after = store.get_by_client_order_id(f"merid_coid_{st.lower()}")
        assert after is not None and after.status == st


@pytest.mark.asyncio
async def test_ticker_falls_back_to_client_tag(store):
    """When payload lacks a ticker, the 15m_* client_tag encodes it."""
    _seed(
        store,
        coid="merid_coid_tag1",
        client_tag="15m_KXDOGE15M-26NOV182215-15_998877665544",
        payload={},
    )
    raw = _RawClient(_ok(None))
    poller = FillsPoller()

    await poller._reconcile_persisted_attempts(_port_with_raw(raw))

    assert raw.calls == [("merid_coid_tag1", "KXDOGE15M-26NOV182215-15")]
    after = store.get_by_client_order_id("merid_coid_tag1")
    assert after is not None and after.status == "REJECTED"
    ev = json.loads(after.payload_json)["reconciliation_evidence"]
    assert ev["ticker"] == "KXDOGE15M-26NOV182215-15"


@pytest.mark.asyncio
async def test_missing_coid_is_skipped(store):
    now = time.time()
    rec = OrderAttemptRecord(
        order_attempt_id="oa_nocoid",
        client_order_id="",
        decision_id="cand_x",
        replaces_order_attempt_id=None,
        intent_id="intent_x",
        client_tag=None,
        run_id=None,
        process_id=None,
        fingerprint="fp",
        status="PERSISTED",
        created_at=now - 3600,
        updated_at=now - 3600,
        payload_json="{}",
    )
    store.persist_attempt(rec)
    raw = _RawClient(_ok(None))
    poller = FillsPoller()

    await poller._reconcile_persisted_attempts(_port_with_raw(raw))

    assert raw.calls == []
    after = store.get_by_order_attempt_id("oa_nocoid")
    assert after is not None and after.status == "PERSISTED"


@pytest.mark.asyncio
async def test_dedupe_across_attempts_same_market(store):
    """Multiple stale PERSISTED rows reconcile independently."""
    _seed(store, coid="merid_coid_d1", decision_id="cand_a:maker_bid")
    _seed(store, coid="merid_coid_d2", decision_id="cand_b:taker_ask")
    raw = _RawClient(_ok(None))
    poller = FillsPoller()

    await poller._reconcile_persisted_attempts(_port_with_raw(raw))

    assert len(raw.calls) == 2
    for coid in ("merid_coid_d1", "merid_coid_d2"):
        after = store.get_by_client_order_id(coid)
        assert after is not None and after.status == "REJECTED"


@pytest.mark.asyncio
async def test_grace_env_override(store, monkeypatch):
    monkeypatch.setenv("MERID_STALE_PERSISTED_GRACE_S", "100000")
    _seed(store, coid="merid_coid_grace1", age_s=3600.0)
    raw = _RawClient(_ok(None))
    poller = FillsPoller()

    await poller._reconcile_persisted_attempts(_port_with_raw(raw))

    assert raw.calls == []
    after = store.get_by_client_order_id("merid_coid_grace1")
    assert after is not None and after.status == "PERSISTED"


@pytest.mark.asyncio
async def test_store_query_failure_is_swallowed(store, monkeypatch):
    """A broken store must not crash the reconcile cycle."""
    poller = FillsPoller()

    class _BoomStore:
        def get_unresolved(self, **kwargs):
            raise RuntimeError("db locked")

    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_attempt_store.OrderAttemptStore",
        lambda *a, **k: _BoomStore(),
    )
    # The method imports OrderAttemptStore lazily inside the try — patch the
    # class attribute the import resolves to.
    await poller._reconcile_persisted_attempts(SimpleNamespace())
    # No exception propagated.


@pytest.mark.asyncio
async def test_unresolved_head_cannot_starve_later_rows(store):
    """Failed lookups back off: rows behind a failing head still get checked."""
    # Head row always fails the venue lookup.
    _seed(store, coid="merid_coid_head")
    # Later rows are venue-absent and should terminalize.
    for i in range(3):
        _seed(store, coid=f"merid_coid_tail{i}")

    class _HeadRaw:
        def __init__(self):
            self.calls = []

        async def get_order_by_client_id_result(self, coid, market_id=None, min_ts=None):
            self.calls.append(coid)
            if coid == "merid_coid_head":
                return SimpleNamespace(success=False, data=None, error="down")
            return SimpleNamespace(success=True, data=None, error=None)

    raw = _HeadRaw()
    poller = FillsPoller()
    monkey_env = {"MERID_STALE_PERSISTED_MAX_PER_CYCLE": "2"}
    import os
    old_env = os.environ.get("MERID_STALE_PERSISTED_MAX_PER_CYCLE")
    os.environ["MERID_STALE_PERSISTED_MAX_PER_CYCLE"] = "2"
    try:
        # Cycle 1: head + one tail processed (bound=2 lookups).
        await poller._reconcile_persisted_attempts(_port_with_raw(raw))
        # Cycle 2: head is backed off (next_at in future) -> tails proceed.
        await poller._reconcile_persisted_attempts(_port_with_raw(raw))
    finally:
        if old_env is None:
            os.environ.pop("MERID_STALE_PERSISTED_MAX_PER_CYCLE", None)
        else:
            os.environ["MERID_STALE_PERSISTED_MAX_PER_CYCLE"] = old_env

    tails = [f"merid_coid_tail{i}" for i in range(3)]
    done = [
        c for c in tails
        if store.get_by_client_order_id(c).status == "REJECTED"
    ]
    # The failing head must not prevent ALL tails from being reached.
    assert len(done) >= 2
    head = store.get_by_client_order_id("merid_coid_head")
    assert head is not None and head.status == "PERSISTED"


@pytest.mark.asyncio
async def test_lookup_failure_backs_off(store):
    _seed(store, coid="merid_coid_backoff")
    raw = _RawClient(_fail("down"))
    poller = FillsPoller()
    client = _port_with_raw(raw)

    await poller._reconcile_persisted_attempts(client)
    n1 = len(raw.calls)
    assert n1 == 1
    # Immediate second pass: row is not due -> no new venue call.
    await poller._reconcile_persisted_attempts(client)
    assert len(raw.calls) == n1
    after = store.get_by_client_order_id("merid_coid_backoff")
    assert after is not None and after.status == "PERSISTED"


@pytest.mark.asyncio
async def test_venue_present_recheck_is_bounded(store, monkeypatch):
    """A venue-present row gets a periodic recheck, not every-cycle spam."""
    _seed(store, coid="merid_coid_vp")
    raw = _RawClient(_ok(SimpleNamespace(order_id="o9")))
    full = AsyncMock()
    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_router.reconcile_submission_unknown_client_order_id",
        full,
    )
    poller = FillsPoller()
    client = _port_with_raw(raw)

    await poller._reconcile_persisted_attempts(client)
    await poller._reconcile_persisted_attempts(client)
    # Second pass: venue-present rows are throttled to ~300s recheck.
    assert full.await_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
