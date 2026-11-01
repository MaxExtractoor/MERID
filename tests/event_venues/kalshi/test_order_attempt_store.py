"""Tests for the durable exit-order attempt lifecycle store."""

from __future__ import annotations

import pytest

from merid.event_venues.kalshi.order_attempt_store import (
    ExitOrderAttemptConflict,
    ExitOrderAttemptState,
    OrderAttemptStore,
)


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


def test_expired_market_sweep_preserves_unproven_outcomes(tmp_path, monkeypatch):
    """An expired market and an empty local ledger cannot prove cancellation."""
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
    assert statuses["oa_orphan"] == "ACKNOWLEDGED"
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
