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

    # An invalid FSM transition should return None.
    invalid = store.transition_exit_attempt(
        attempt.attempt_id,
        ExitOrderAttemptState.FILLED.value,
        actor="reconciler",
        reason="should_fail",
        expected_state_version=4,
    )
    assert invalid is None


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


def test_expired_market_sweep_terminalizes_orphaned_attempts(tmp_path, monkeypatch):
    """The observed orphan: an ACKNOWLEDGED order attempt on an expired market
    stayed unresolved forever because get_unresolved only looked back 300s.
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
    # No fills ledger -> no filled order ids; ticker resolves via client_tag.
    monkeypatch.setattr(fl, "get_fills_ledger", lambda: None)

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

    # Exit attempts: INTENT_PERSISTED on expired ticker -> CANCELED;
    # PARTIALLY_FILLED with unconfirmed remainder -> TERMINAL_UNFILLED.
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
    conn = store._get_conn()
    conn.execute(
        "UPDATE exit_order_attempts SET created_at = ?, confirmed_quantity = 50 WHERE attempt_id IN ('xa-1','xa-2')",
        (now - 7200,),
    )
    conn.commit()

    asyncio.run(FillsPoller._sweep_expired_market_attempts(SimpleNamespace()))

    statuses = {
        r["order_attempt_id"]: r["status"]
        for r in conn.execute(
            "SELECT order_attempt_id, status FROM order_attempts"
        ).fetchall()
    }
    assert statuses["oa_orphan"] == "CANCELED"
    assert statuses["oa_young"] == "ACKNOWLEDGED"
    assert statuses["oa_live"] == "ACKNOWLEDGED"

    ex_states = {
        r["attempt_id"]: r["state"]
        for r in conn.execute(
            "SELECT attempt_id, state FROM exit_order_attempts"
        ).fetchall()
    }
    assert ex_states["xa-1"] == ExitOrderAttemptState.CANCELED.value
    assert ex_states["xa-2"] == ExitOrderAttemptState.TERMINAL_UNFILLED.value

    # Idempotent: a second sweep changes nothing.
    asyncio.run(FillsPoller._sweep_expired_market_attempts(SimpleNamespace()))
    statuses2 = {
        r["order_attempt_id"]: r["status"]
        for r in conn.execute(
            "SELECT order_attempt_id, status FROM order_attempts"
        ).fetchall()
    }
    assert statuses2 == statuses
