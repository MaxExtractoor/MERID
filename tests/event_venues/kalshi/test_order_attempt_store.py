"""Tests for the durable exit-order attempt lifecycle store."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from merid.event_venues.kalshi.order_attempt_store import (
    ExitOrderAttemptConflict,
    ExitOrderAttemptState,
    OrderAttemptStore,
)

def test_concurrent_exit_creation_has_one_active_attempt(tmp_path):
    store = OrderAttemptStore(str(tmp_path / "concurrent_exits.db"))
    barrier = Barrier(8)

    def create(index):
        barrier.wait(timeout=10)
        try:
            return store.create_exit_attempt(
                exit_intent_id=f"intent-{index}", position_key="same-position",
                ticker="KXBTC15M", reason="risk", client_order_id=f"coid-{index}",
                requested_quantity=100,
            )
        except ExitOrderAttemptConflict:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(create, range(8)))
    assert sum(record is not None for record in results) == 1
    assert len(store.list_nonterminal_exit_attempts()) == 1


def test_exit_attempt_lifecycle_and_concurrency(tmp_path):
    db_path = tmp_path / "test_exit_attempts.db"
    store = OrderAttemptStore(str(db_path))

    attempt = store.create_exit_attempt(
        exit_intent_id="intent-1",
        position_key="pos-1",
        ticker="KXBTC15M",
        reason="TAKE_PROFIT",
        client_order_id="co-1",
        requested_quantity=100,
        requested_limit_cents=75,
        attempt_id="attempt-1",
    )
    assert attempt is not None
    assert attempt.state == ExitOrderAttemptState.INTENT_PERSISTED.value
    assert attempt.state_version == 1
    assert store.is_terminal_state(attempt.state) is False

    active = store.get_active_exit_attempt_for_position("pos-1")
    assert active is not None
    assert active.attempt_id == attempt.attempt_id

    nonterminal = store.list_nonterminal_exit_attempts()
    assert len(nonterminal) == 1
    assert nonterminal[0].attempt_id == attempt.attempt_id

    by_coid = store.get_exit_attempt_by_client_order_id("co-1")
    assert by_coid is not None
    assert by_coid.attempt_id == attempt.attempt_id

    # Active conflict: a second attempt for the same position should raise.
    with pytest.raises(ExitOrderAttemptConflict):
        store.create_exit_attempt(
            exit_intent_id="intent-2",
            position_key="pos-1",
            ticker="KXBTC15M",
            reason="STOP_LOSS",
            client_order_id="co-2",
            requested_quantity=50,
            attempt_id="attempt-2",
        )

    # Valid FSM transitions.
    updated = store.transition_exit_attempt(
        attempt.attempt_id,
        ExitOrderAttemptState.SUBMITTING.value,
        actor="router",
        reason="submitting",
        expected_state_version=1,
    )
    assert updated is not None
    assert updated.state == ExitOrderAttemptState.SUBMITTING.value
    assert updated.state_version == 2

    updated = store.transition_exit_attempt(
        attempt.attempt_id,
        ExitOrderAttemptState.SUBMISSION_UNKNOWN.value,
        actor="router",
        reason="ack_lost",
        expected_state_version=2,
    )
    assert updated is not None
    assert updated.state == ExitOrderAttemptState.SUBMISSION_UNKNOWN.value
    assert updated.state_version == 3

    updated = store.transition_exit_attempt(
        attempt.attempt_id,
        ExitOrderAttemptState.NOT_ACCEPTED_CONFIRMED.value,
        actor="reconciler",
        reason="lookup_found_no_order",
        expected_state_version=3,
    )
    assert updated is not None
    assert updated.state == ExitOrderAttemptState.NOT_ACCEPTED_CONFIRMED.value
    assert updated.state_version == 4
    assert store.is_terminal_state(updated.state) is True

    # Once terminal, no active attempt remains.
    active = store.get_active_exit_attempt_for_position("pos-1")
    assert active is None

    # Optimistic concurrency failure: stale state version.
    stale = store.transition_exit_attempt(
        attempt.attempt_id,
        ExitOrderAttemptState.SUPERSEDED_AFTER_CONFIRMED_TERMINAL.value,
        actor="reconciler",
        reason="stale_superseded",
        expected_state_version=3,
    )
    assert stale is None

    # A genuinely invalid FSM transition still returns None: a
    # NOT_ACCEPTED_CONFIRMED order was never venue-live, so it cannot rest.
    invalid = store.transition_exit_attempt(
        attempt.attempt_id,
        ExitOrderAttemptState.RESTING.value,
        actor="reconciler",
        reason="should_fail",
        expected_state_version=4,
    )
    assert invalid is None

    # NOT_ACCEPTED_CONFIRMED -> FILLED is a deliberate edge, not a bug: the
    # not-accepted verdict comes from a REST lookup that can lag an
    # already-resting order, and an authoritative exchange fill must be
    # recordable over the local terminal verdict (incident 2026-10-18).
    late_fill = store.transition_exit_attempt(
        attempt.attempt_id,
        ExitOrderAttemptState.FILLED.value,
        actor="reconciler",
        reason="authoritative_late_fill",
        expected_state_version=4,
    )
    assert late_fill is not None
    assert late_fill.state == ExitOrderAttemptState.FILLED.value
    assert late_fill.state_version == 5


def test_superseded_attempt_releases_client_order_id(tmp_path):
    """A superseded terminal attempt must free its client_order_id so the
    re-armed exit retry can create a fresh attempt with the same idempotency
    key, and lookups must resolve to the new attempt."""
    db_path = tmp_path / "test_exit_attempts_supersede.db"
    store = OrderAttemptStore(str(db_path))

    a1 = store.create_exit_attempt(
        exit_intent_id="intent-exit-1",
        position_key="pos-9",
        ticker="KXBTC15M-X",
        reason="settlement_guard",
        client_order_id="exit_abc123",
        requested_quantity=100,
        attempt_id="attempt-old",
    )
    store.transition_exit_attempt(
        a1.attempt_id, ExitOrderAttemptState.SUBMITTING.value,
        actor="t", reason="t",
    )
    store.transition_exit_attempt(
        a1.attempt_id, ExitOrderAttemptState.SUBMISSION_UNKNOWN.value,
        actor="t", reason="t",
    )
    store.transition_exit_attempt(
        a1.attempt_id, ExitOrderAttemptState.NOT_ACCEPTED_CONFIRMED.value,
        actor="t", reason="t",
    )

    sup = store.transition_exit_attempt(
        a1.attempt_id,
        ExitOrderAttemptState.SUPERSEDED_AFTER_CONFIRMED_TERMINAL.value,
        actor="loop_15m",
        reason="superseded_for_rearm",
    )
    assert sup is not None
    assert sup.state == ExitOrderAttemptState.SUPERSEDED_AFTER_CONFIRMED_TERMINAL.value

    # The same client_order_id must be reusable without an IntegrityError.
    a2 = store.create_exit_attempt(
        exit_intent_id="intent-exit-1",
        position_key="pos-9",
        ticker="KXBTC15M-X",
        reason="settlement_guard",
        client_order_id="exit_abc123",
        requested_quantity=100,
        attempt_id="attempt-new",
    )
    assert a2.attempt_id != a1.attempt_id
    assert a2.state == ExitOrderAttemptState.INTENT_PERSISTED.value

    # Lookup by client_order_id resolves to the live attempt, not the tombstone.
    got = store.get_exit_attempt_by_client_order_id("exit_abc123")
    assert got is not None
    assert got.attempt_id == a2.attempt_id

    # The new attempt can run the full lifecycle.
    store.transition_exit_attempt(
        a2.attempt_id, ExitOrderAttemptState.SUBMITTING.value,
        actor="t", reason="t",
    )
    final = store.transition_exit_attempt(
        a2.attempt_id, ExitOrderAttemptState.FILLED.value,
        actor="t", reason="t",
    )
    assert final is not None
    assert final.state == ExitOrderAttemptState.FILLED.value


def test_terminal_exit_state_mirrors_to_order_attempts(tmp_path):
    """2026-11-07 XRP-1145: an exit that fills asynchronously leaves its
    ``order_attempts`` identity row ACKNOWLEDGED forever, which wedged the
    firewall's in-flight-exit check against every later exit on the ticker.
    Terminal exit-FSM states must mirror onto the identity row."""
    store = OrderAttemptStore(str(tmp_path / "mirror.db"))

    def _identity(coid):
        from merid.event_venues.kalshi.order_attempt_store import OrderAttemptRecord
        import time as _t
        return OrderAttemptRecord(
            order_attempt_id=f"oa-{coid}", client_order_id=coid,
            decision_id=None, replaces_order_attempt_id=None,
            intent_id=f"intent-{coid}", client_tag=coid, run_id=None,
            process_id=None, fingerprint=coid, status="ACKNOWLEDGED",
            created_at=_t.time(), updated_at=_t.time(), payload_json="{}",
        )

    # FILLED mirrors to FILLED.
    store.persist_attempt(_identity("co-filled"))
    ex = store.create_exit_attempt(
        exit_intent_id="xi-f", position_key="pos-f", ticker="KXXRP15M-T",
        reason="ratchet_trim", client_order_id="co-filled",
        requested_quantity=300, attempt_id="xa-f",
    )
    store.transition_exit_attempt("xa-f", "SUBMITTING", actor="t", reason="t")
    store.transition_exit_attempt("xa-f", "ACKNOWLEDGED", actor="t", reason="t")
    store.transition_exit_attempt("xa-f", "FILLED", actor="t", reason="t")
    assert store.get_by_client_order_id("co-filled").status == "FILLED"

    # TERMINAL_UNFILLED (never dispatched) mirrors to CANCELED.
    store.persist_attempt(_identity("co-never"))
    ex2 = store.create_exit_attempt(
        exit_intent_id="xi-n", position_key="pos-n", ticker="KXXRP15M-T",
        reason="loss_cap", client_order_id="co-never",
        requested_quantity=100, attempt_id="xa-n",
    )
    store.transition_exit_attempt("xa-n", "SUBMITTING", actor="t", reason="t")
    store.transition_exit_attempt("xa-n", "TERMINAL_UNFILLED", actor="t", reason="never_dispatched")
    assert store.get_by_client_order_id("co-never").status == "CANCELED"

    # Non-terminal transitions leave the identity row untouched.
    store.persist_attempt(_identity("co-resting"))
    ex3 = store.create_exit_attempt(
        exit_intent_id="xi-r", position_key="pos-r", ticker="KXXRP15M-T",
        reason="trail", client_order_id="co-resting",
        requested_quantity=100, attempt_id="xa-r",
    )
    store.transition_exit_attempt("xa-r", "SUBMITTING", actor="t", reason="t")
    store.transition_exit_attempt("xa-r", "ACKNOWLEDGED", actor="t", reason="t")
    store.transition_exit_attempt("xa-r", "RESTING", actor="t", reason="t")
    assert store.get_by_client_order_id("co-resting").status == "ACKNOWLEDGED"

    # Missing identity row is a no-op, not an error.
    ex4 = store.create_exit_attempt(
        exit_intent_id="xi-m", position_key="pos-m", ticker="KXXRP15M-T",
        reason="trail", client_order_id="co-orphan",
        requested_quantity=100, attempt_id="xa-m",
    )
    store.transition_exit_attempt("xa-m", "SUBMITTING", actor="t", reason="t")
    store.transition_exit_attempt("xa-m", "CANCELED", actor="t", reason="t")
    assert store.get_by_client_order_id("co-orphan") is None

    # An already-terminal identity row is left alone.
    from merid.event_venues.kalshi.order_attempt_store import OrderAttemptRecord
    import time as _t2
    store.persist_attempt(OrderAttemptRecord(
        order_attempt_id="oa-done", client_order_id="co-done",
        decision_id=None, replaces_order_attempt_id=None,
        intent_id="intent-co-done", client_tag="co-done", run_id=None,
        process_id=None, fingerprint="co-done", status="FILLED",
        created_at=_t2.time(), updated_at=_t2.time(), payload_json="{}",
    ))
    ex5 = store.create_exit_attempt(
        exit_intent_id="xi-d", position_key="pos-d", ticker="KXXRP15M-T",
        reason="trail", client_order_id="co-done",
        requested_quantity=100, attempt_id="xa-d",
    )
    store.transition_exit_attempt("xa-d", "SUBMITTING", actor="t", reason="t")
    store.transition_exit_attempt("xa-d", "REJECTED_EXCHANGE", actor="t", reason="t")
    assert store.get_by_client_order_id("co-done").status == "FILLED"


def test_expired_market_sweep_preserves_unproven_outcomes(tmp_path, monkeypatch):
    """Expired-market sweep: proven-dead entries terminalize; unproven stay.

    ``oa_orphan`` carries an expired ticker (via its ``15m_*`` client_tag)
    and the fake ledger has no fill on that ticker — a proven non-fill, so
    it terminalizes CANCELED.  Young, live-ticker, and non-ACKNOWLEDGED
    rows are preserved, as is any attempt whose ticker shows plausible fill
    activity (covered by the companion test below).
    """
    import asyncio
    import time
    from types import SimpleNamespace

    import merid.event_venues.kalshi.order_attempt_store as oas
    import merid.event_venues.kalshi.fills_ledger as fl
    from merid.event_venues.kalshi.fills_poller import FillsPoller
    from merid.event_venues.kalshi.order_attempt_store import OrderAttemptRecord

    db_path = str(tmp_path / "oa_sweep.db")
    monkeypatch.setattr(oas, "DEFAULT_DB_PATH", db_path)
    def _fill(order_id, quantity, **overrides):
        fields = dict(
            order_id=order_id, quantity_cc=quantity, fill_id=f"fill-{order_id}",
            market_ticker="KXBTC15M-UNRELATED",
            is_live=True, unmatched=False, canonicalization_state="TRUSTED_LIVE_V1",
            fill_source="alpha", ingestion_source="websocket",
        )
        fields.update(overrides)
        return SimpleNamespace(**fields)

    ledger = SimpleNamespace(get_canonical_fills=lambda: SimpleNamespace(
        authoritative=[
            _fill("order-x2", 50),
            _fill("order-x4", 100),
            _fill("order-x5", 100, canonicalization_state="UNTRUSTED_RAW"),
            _fill("order-x6", 100, fill_id="settlement:order-x6", fill_source="settlement"),
        ],
        provisional=[_fill("order-x7", 100, fill_id="live_router_x7")],
    ))
    monkeypatch.setattr(fl, "get_fills_ledger", lambda: ledger)

    store = OrderAttemptStore(str(db_path))
    now = time.time()

    expired_ticker = "KXBTC15M-26SEP210000-00"  # 2026-09-21 00:00 ET, expired
    live_ticker = "KXBTC15M-30JAN010000-00"     # far future, not expired

    def _attempt(aid, coid, tag, status, age_s):
        return OrderAttemptRecord(
            order_attempt_id=aid,
            client_order_id=coid,
            decision_id=None,
            replaces_order_attempt_id=None,
            intent_id=f"intent_{aid}",
            client_tag=tag,
            run_id=None,
            process_id=None,
            fingerprint="fp",
            status=status,
            created_at=now - age_s,
            updated_at=now - age_s,
            payload_json="{}",
        )

    # Orphan mirroring the observed ACKNOWLEDGED-on-expired-market order.
    store.persist_attempt(_attempt(
        "oa_orphan", "merid_orphan01", f"15m_{expired_ticker}_0a1b2c",
        "ACKNOWLEDGED", 7200,
    ))
    # Fresh attempt on an expired ticker — inside the grace window, skip.
    store.persist_attempt(_attempt(
        "oa_young", "merid_young001", f"15m_{expired_ticker}_1b2c3d",
        "ACKNOWLEDGED", 60,
    ))
    # Old attempt on a live ticker — must not be swept.
    store.persist_attempt(_attempt(
        "oa_live", "merid_live0001", f"15m_{live_ticker}_2c3d4e",
        "ACKNOWLEDGED", 7200,
    ))
    for status in ("SUBMITTING", "SUBMISSION_UNKNOWN"):
        store.persist_attempt(_attempt(
            f"oa_{status}", f"coid_{status}", f"15m_{expired_ticker}_3c4d5e",
            status, 7200,
        ))

    # An unconfirmed exit and a partial exit must also retain their states.
    ex1 = store.create_exit_attempt(
        exit_intent_id="xi-1", position_key="pos-1", ticker=expired_ticker,
        reason="SETTLEMENT_GUARD", client_order_id="co-x1",
        requested_quantity=100, attempt_id="xa-1",
    )
    ex2 = store.create_exit_attempt(
        exit_intent_id="xi-2", position_key="pos-2", ticker=expired_ticker,
        reason="SETTLEMENT_GUARD", client_order_id="co-x2",
        requested_quantity=100, attempt_id="xa-2",
    )
    store.transition_exit_attempt("xa-2", "SUBMITTING", actor="test", reason="t")
    store.transition_exit_attempt("xa-2", "PARTIALLY_FILLED", actor="test", reason="t")
    store.create_exit_attempt(
        exit_intent_id="xi-3", position_key="pos-3", ticker=expired_ticker,
        reason="SETTLEMENT_GUARD", client_order_id="co-x3",
        requested_quantity=100, attempt_id="xa-3",
    )
    store.transition_exit_attempt("xa-3", "SUBMITTING", actor="test", reason="t")
    store.transition_exit_attempt("xa-3", "SUBMISSION_UNKNOWN", actor="test", reason="t")
    store.create_exit_attempt(
        exit_intent_id="xi-4", position_key="pos-4", ticker=expired_ticker,
        reason="SETTLEMENT_GUARD", client_order_id="co-x4",
        requested_quantity=100, attempt_id="xa-4",
    )
    store.transition_exit_attempt("xa-4", "SUBMITTING", actor="test", reason="t")
    store.transition_exit_attempt("xa-4", "PARTIALLY_FILLED", actor="test", reason="t")
    for number in (5, 6, 7):
        store.create_exit_attempt(
            exit_intent_id=f"xi-{number}", position_key=f"pos-{number}",
            ticker=expired_ticker, reason="SETTLEMENT_GUARD",
            client_order_id=f"co-x{number}", requested_quantity=100,
            attempt_id=f"xa-{number}",
        )
        store.transition_exit_attempt(f"xa-{number}", "SUBMITTING", actor="test", reason="t")
        store.transition_exit_attempt(f"xa-{number}", "PARTIALLY_FILLED", actor="test", reason="t")
    conn = store._get_conn()
    conn.execute(
        "UPDATE exit_order_attempts SET created_at = ?, confirmed_quantity = 50",
        (now - 7200,),
    )
    conn.execute("UPDATE exit_order_attempts SET exchange_order_id='order-x2' WHERE attempt_id='xa-2'")
    for number in (4, 5, 6, 7):
        conn.execute(
            "UPDATE exit_order_attempts SET exchange_order_id=?, confirmed_quantity=100 WHERE attempt_id=?",
            (f"order-x{number}", f"xa-{number}"),
        )
    conn.commit()

    FillsPoller._sweep_expired_market_attempts(SimpleNamespace())

    statuses = {
        r["order_attempt_id"]: r["status"]
        for r in conn.execute(
            "SELECT order_attempt_id, status FROM order_attempts"
        ).fetchall()
    }
    # Proven dead: expired ticker (parsed from client_tag), zero fills on
    # that ticker in the ledger -> the order cannot have filled.
    assert statuses["oa_orphan"] == "CANCELED"
    assert statuses["oa_young"] == "ACKNOWLEDGED"
    assert statuses["oa_live"] == "ACKNOWLEDGED"
    assert statuses["oa_SUBMITTING"] == "SUBMITTING"
    assert statuses["oa_SUBMISSION_UNKNOWN"] == "SUBMISSION_UNKNOWN"

    ex_states = {
        r["attempt_id"]: r["state"]
        for r in conn.execute(
            "SELECT attempt_id, state FROM exit_order_attempts"
        ).fetchall()
    }
    assert ex_states["xa-1"] == ExitOrderAttemptState.INTENT_PERSISTED.value
    assert ex_states["xa-2"] == ExitOrderAttemptState.PARTIALLY_FILLED.value
    assert ex_states["xa-3"] == ExitOrderAttemptState.SUBMISSION_UNKNOWN.value
    assert ex_states["xa-4"] == ExitOrderAttemptState.FILLED.value
    for number in (5, 6, 7):
        assert ex_states[f"xa-{number}"] == ExitOrderAttemptState.PARTIALLY_FILLED.value

    # Idempotent: a second sweep changes nothing.
    FillsPoller._sweep_expired_market_attempts(SimpleNamespace())
    statuses2 = {
        r["order_attempt_id"]: r["status"]
        for r in conn.execute(
            "SELECT order_attempt_id, status FROM order_attempts"
        ).fetchall()
    }
    assert statuses2 == statuses


def _entry_attempt_record(store, aid, coid, status, payload=None, age_s=0.0, tag=None, intent=None):
    import json as _json
    import time as _time
    from merid.event_venues.kalshi.order_attempt_store import OrderAttemptRecord
    rec = OrderAttemptRecord(
        order_attempt_id=aid,
        client_order_id=coid,
        decision_id=None,
        replaces_order_attempt_id=None,
        intent_id=intent or f"intent_{aid}",
        client_tag=tag,
        run_id=None,
        process_id=None,
        fingerprint="fp",
        status=status,
        created_at=_time.time() - age_s,
        updated_at=_time.time() - age_s,
        payload_json=_json.dumps(payload or {}),
    )
    store.persist_attempt(rec)
    return rec


class TestApplyEntryFill:
    """Entry-side fill mirror onto order_attempts identity rows."""

    def _store(self, tmp_path):
        return OrderAttemptStore(str(tmp_path / "entry_fills.db"))

    def test_partial_then_full_coverage_promotes_to_filled(self, tmp_path):
        store = self._store(tmp_path)
        _entry_attempt_record(
            store, "oa_e1", "merid_e1", "ACKNOWLEDGED",
            payload={"order": {"count_fp": "4.0", "ticker": "KXETH15M-1"}},
        )
        # 200cc of a 400cc order -> still ACKNOWLEDGED, coverage stamped.
        rec = store.apply_entry_fill(
            client_order_id="merid_e1", fill_id="fill-a", quantity_cc=200,
        )
        assert rec.status == "ACKNOWLEDGED"
        assert store.entry_confirmed_quantity_cc("oa_e1") == 200
        # Remaining 200cc -> FILLED.
        rec = store.apply_entry_fill(
            client_order_id="merid_e1", fill_id="fill-b", quantity_cc=200,
        )
        assert rec.status == "FILLED"
        assert store.entry_confirmed_quantity_cc("oa_e1") == 400

    def test_apply_entry_fill_is_exactly_once_per_fill_id(self, tmp_path):
        store = self._store(tmp_path)
        _entry_attempt_record(
            store, "oa_e2", "merid_e2", "ACKNOWLEDGED",
            payload={"order": {"count_fp": "2.0"}},
        )
        store.apply_entry_fill(client_order_id="merid_e2", fill_id="fill-x", quantity_cc=200)
        store.apply_entry_fill(client_order_id="merid_e2", fill_id="fill-x", quantity_cc=200)
        assert store.entry_confirmed_quantity_cc("oa_e2") == 200

    def test_apply_entry_fill_unknown_coid_returns_none(self, tmp_path):
        store = self._store(tmp_path)
        assert store.apply_entry_fill(
            client_order_id="merid_missing", fill_id="fill-y", quantity_cc=100
        ) is None

    def test_apply_entry_fill_rejects_fill_owned_by_other_attempt(self, tmp_path):
        store = self._store(tmp_path)
        _entry_attempt_record(store, "oa_e3a", "merid_e3a", "ACKNOWLEDGED",
                              payload={"order": {"count_fp": "1.0"}})
        _entry_attempt_record(store, "oa_e3b", "merid_e3b", "ACKNOWLEDGED",
                              payload={"order": {"count_fp": "1.0"}})
        store.apply_entry_fill(client_order_id="merid_e3a", fill_id="fill-shared", quantity_cc=100)
        rec_b = store.apply_entry_fill(
            client_order_id="merid_e3b", fill_id="fill-shared", quantity_cc=100
        )
        # The fill stays owned by the first attempt only.
        assert store.entry_confirmed_quantity_cc("oa_e3a") == 100
        assert store.entry_confirmed_quantity_cc("oa_e3b") == 0
        assert rec_b.status == "ACKNOWLEDGED"

    def test_late_fill_resurrects_canceled_attempt_on_full_coverage(self, tmp_path):
        """Exchange truth wins: a CANCELED attempt with complete fill
        coverage is corrected to FILLED (same contract as exit FSM)."""
        store = self._store(tmp_path)
        _entry_attempt_record(
            store, "oa_e4", "merid_e4", "CANCELED",
            payload={"order": {"count_fp": "3.0"}},
        )
        rec = store.apply_entry_fill(
            client_order_id="merid_e4", fill_id="fill-late", quantity_cc=300
        )
        assert rec.status == "FILLED"

    def test_terminalize_entry_attempt_guards_terminal_rows(self, tmp_path):
        store = self._store(tmp_path)
        _entry_attempt_record(store, "oa_e5", "merid_e5", "ACKNOWLEDGED")
        _entry_attempt_record(store, "oa_e6", "merid_e6", "FILLED")
        assert store.terminalize_entry_attempt(
            "oa_e5", "CANCELED", actor="test", reason="r", evidence={"k": 1}
        ) is True
        # Terminal rows are never overwritten by reconciliation.
        assert store.terminalize_entry_attempt(
            "oa_e6", "CANCELED", actor="test", reason="r"
        ) is False
        rec = store.get_by_order_attempt_id("oa_e5")
        assert rec.status == "CANCELED"
        assert "reconciliation_evidence" in rec.payload_json


def test_expired_market_sweep_entry_coverage_paths(tmp_path, monkeypatch):
    """Entry sweep: FILLED on proven coverage, CANCELED on proven dead,
    preserved when plausible fill activity exists on the ticker."""
    import time
    from types import SimpleNamespace

    import merid.event_venues.kalshi.order_attempt_store as oas
    import merid.event_venues.kalshi.fills_ledger as fl
    from merid.event_venues.kalshi.fills_poller import FillsPoller
    from merid.event_venues.kalshi.order_attempt_store import OrderAttemptRecord

    db_path = str(tmp_path / "oa_entry_sweep.db")
    monkeypatch.setattr(oas, "DEFAULT_DB_PATH", db_path)

    expired_btc = "KXBTC15M-26SEP210000-00"
    expired_eth = "KXETH15M-26SEP210000-00"
    now = time.time()

    def _efill(fid, qty, ticker, coid=None, tag=None, intent=None,
               side="yes", action="buy", ts=None):
        return SimpleNamespace(
            fill_id=fid, order_id=f"ord-{fid}", quantity_cc=qty,
            market_ticker=ticker, client_order_id=coid, client_tag=tag,
            intent_id=intent, canonical_position_side=side,
            canonical_position_action=action, created_time=ts,
            created_at=ts, ingested_at=ts,
            is_live=True, unmatched=False,
            canonicalization_state="TRUSTED_LIVE_V1",
            fill_source="alpha", ingestion_source="websocket",
            is_exit=False, reduce_only=False, entry_or_exit="entry",
        )

    ledger = SimpleNamespace(get_canonical_fills=lambda: SimpleNamespace(
        authoritative=[
            # Full coverage for oa_filled (400cc requested, 400cc filled).
            _efill("fill-full", 400, expired_eth, coid="merid_full01",
                   side="yes", action="buy", ts=now - 7000),
            # Partial coverage for oa_partial (1000cc requested, 400cc filled).
            _efill("fill-part", 400, expired_eth, coid="merid_part01",
                   side="yes", action="buy", ts=now - 7000),
            # Unrelated activity on the ETH ticker -> plausible for oa_plausible.
            _efill("fill-other", 100, expired_eth,
                   side="no", action="sell", ts=now - 6900),
        ],
        provisional=[],
    ))
    monkeypatch.setattr(fl, "get_fills_ledger", lambda: ledger)

    store = OrderAttemptStore(str(db_path))

    # FILLED: expired ticker, requested 4.0 -> 400cc, linked fill covers it.
    _entry_attempt_record(
        store, "oa_filled", "merid_full01", "ACKNOWLEDGED", age_s=7200,
        payload={"order": {"ticker": expired_eth, "count_fp": "4.0",
                           "side": "buy_yes", "action": "buy"}},
    )
    # CANCELED (partial): 10.0 -> 1000cc requested, only 400cc covered.
    _entry_attempt_record(
        store, "oa_partial", "merid_part01", "ACKNOWLEDGED", age_s=7200,
        payload={"order": {"ticker": expired_eth, "count_fp": "10.0",
                           "side": "buy_yes", "action": "buy"}},
    )
    # PRESERVED: expired ticker via tag, no linkage, but plausible fill
    # activity exists on that ticker within the window.
    _entry_attempt_record(
        store, "oa_plausible", "merid_plaus01", "ACKNOWLEDGED", age_s=7200,
        tag=f"15m_{expired_eth}_abc123",
    )
    # CANCELED (proven non-fill): expired BTC ticker via tag, no fills on it.
    _entry_attempt_record(
        store, "oa_dead", "merid_dead01", "ACKNOWLEDGED", age_s=7200,
        tag=f"15m_{expired_btc}_def456",
    )
    # PRESERVED: ticker-less but only 2 days old (< 7d legacy threshold).
    _entry_attempt_record(
        store, "oa_recent_legacy", "merid_leg01", "ACKNOWLEDGED", age_s=2 * 86400,
    )
    # CANCELED (legacy age-out): ticker-less, 30 days old, no linkage.
    _entry_attempt_record(
        store, "oa_ancient", "merid_anc01", "ACKNOWLEDGED", age_s=30 * 86400,
    )

    FillsPoller._sweep_expired_market_attempts(SimpleNamespace())

    statuses = {
        r["order_attempt_id"]: r["status"]
        for r in store._get_conn().execute(
            "SELECT order_attempt_id, status FROM order_attempts"
        ).fetchall()
    }
    assert statuses["oa_filled"] == "FILLED"
    assert statuses["oa_partial"] == "CANCELED"
    assert statuses["oa_plausible"] == "ACKNOWLEDGED"
    assert statuses["oa_dead"] == "CANCELED"
    assert statuses["oa_recent_legacy"] == "ACKNOWLEDGED"
    assert statuses["oa_ancient"] == "CANCELED"

    # Evidence payloads record the audit trail.
    rec = store.get_by_order_attempt_id("oa_partial")
    assert "reconciliation_evidence" in rec.payload_json
    assert "confirmed_quantity_cc" in rec.payload_json
