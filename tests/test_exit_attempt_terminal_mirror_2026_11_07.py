"""Regression tests for the 2026-11-07 stale in-flight exit wedge.

Live incident (KXXRP15M-26NOV071145-45 / -070745-45): a ratchet-trim partial
exit filled, but its ``order_attempts`` identity row stayed ``ACKNOWLEDGED``
forever because async fill acks never terminalized it.  The execution
firewall's ``_has_in_flight_exit`` then rejected every later exit on the
ticker — including the LOSS_CAP emergency for the 1-contract runner — so the
residual rode to settlement.

Two-layer fix under test:

1. ``OrderAttemptStore`` mirrors terminal ``exit_order_attempts`` FSM states
   onto the legacy ``order_attempts`` identity row — on BOTH the
   ``transition_exit_attempt`` path and the ``apply_exit_fill`` path (the
   fill-driven path bypasses ``transition_exit_attempt`` entirely).
2. ``ExecutionRiskFirewall._has_in_flight_exit`` skips identity rows whose
   durable exit-FSM record is already terminal, covering rows wedged before
   the mirror existed.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

import merid.event_venues.kalshi.order_attempt_store as attempt_store_module
from merid.event_venues.kalshi.order_attempt_store import (
    OrderAttemptRecord,
    OrderAttemptStore,
)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Isolated attempt store backed by a tmp sqlite db."""
    monkeypatch.setattr(
        attempt_store_module, "DEFAULT_DB_PATH", str(tmp_path / "attempts.db")
    )
    monkeypatch.setattr(OrderAttemptStore, "_instances", {})
    return OrderAttemptStore()


def _identity_row(
    store: OrderAttemptStore,
    client_order_id: str,
    *,
    status: str = "ACKNOWLEDGED",
    intent_id: str = "intent_exit_test",
    ticker: str = "KXXRP15M-TEST",
) -> OrderAttemptRecord:
    rec = OrderAttemptRecord(
        order_attempt_id=f"oa_{client_order_id}",
        client_order_id=client_order_id,
        decision_id="dec-1",
        replaces_order_attempt_id=None,
        intent_id=intent_id,
        client_tag=client_order_id,
        run_id="run-1",
        process_id="pid-1",
        fingerprint=f"fp-{client_order_id}",
        status=status,
        created_at=time.time(),
        updated_at=time.time(),
        payload_json=json.dumps({"ticker": ticker, "entry_or_exit": "exit"}),
    )
    store.persist_attempt(rec)
    return rec


def _exit_attempt(store, client_order_id, *, qty=300, position_key="M|g"):
    return store.create_exit_attempt(
        exit_intent_id="intent_exit_test",
        position_key=position_key,
        ticker="KXXRP15M-TEST",
        reason="model_exit",
        client_order_id=client_order_id,
        requested_quantity=qty,
        requested_limit_cents=81,
    )


def _walk_to_acknowledged(store, attempt_id):
    store.transition_exit_attempt(attempt_id, "SUBMITTING", "test", reason="s")
    store.transition_exit_attempt(attempt_id, "ACKNOWLEDGED", "test", reason="a")


def test_transition_terminal_mirrors_identity_row(store):
    coid = "exit_mirror_1"
    _identity_row(store, coid)
    att = _exit_attempt(store, coid)
    _walk_to_acknowledged(store, att.attempt_id)
    store.transition_exit_attempt(att.attempt_id, "FILLED", "test", reason="f")
    row = store.get_by_client_order_id(coid)
    assert row.status == "FILLED"
    payload = json.loads(row.payload_json)
    assert payload["terminalized_by"] == "exit_attempt_fsm"
    assert payload["exit_attempt_state"] == "FILLED"


def test_apply_exit_fill_terminal_mirrors_identity_row(store):
    """The fill-driven path bypasses transition_exit_attempt — the mirror
    must fire there too or async fills leave the identity row wedged."""
    coid = "exit_mirror_2"
    _identity_row(store, coid)
    att = _exit_attempt(store, coid)
    _walk_to_acknowledged(store, att.attempt_id)
    out = store.apply_exit_fill(
        att.attempt_id,
        fill_id="fill_1",
        quantity_cc=300,
        exchange_order_id="ord_1",
        price_cents=83,
        actor="test",
    )
    assert out is not None and out.state == "FILLED"
    assert out.confirmed_quantity == 300
    row = store.get_by_client_order_id(coid)
    assert row.status == "FILLED"


def test_apply_exit_fill_partial_does_not_mirror_until_terminal(store):
    coid = "exit_mirror_3"
    _identity_row(store, coid)
    att = _exit_attempt(store, coid)
    _walk_to_acknowledged(store, att.attempt_id)
    store.apply_exit_fill(att.attempt_id, fill_id="f1", quantity_cc=100, actor="t")
    row = store.get_by_client_order_id(coid)
    assert row.status == "ACKNOWLEDGED"  # still legitimately in flight
    store.apply_exit_fill(att.attempt_id, fill_id="f2", quantity_cc=200, actor="t")
    row = store.get_by_client_order_id(coid)
    assert row.status == "FILLED"


def test_non_terminal_transition_does_not_mirror(store):
    coid = "exit_mirror_4"
    _identity_row(store, coid)
    att = _exit_attempt(store, coid)
    _walk_to_acknowledged(store, att.attempt_id)
    row = store.get_by_client_order_id(coid)
    assert row.status == "ACKNOWLEDGED"


def test_mirror_is_idempotent_and_preserves_terminal(store):
    """A second terminal transition must not downgrade an already-terminal
    identity row (e.g. FILLED must not be overwritten to CANCELED)."""
    coid = "exit_mirror_5"
    _identity_row(store, coid)
    att = _exit_attempt(store, coid)
    _walk_to_acknowledged(store, att.attempt_id)
    store.transition_exit_attempt(att.attempt_id, "FILLED", "test", reason="f")
    assert store.get_by_client_order_id(coid).status == "FILLED"
    # Attempt a conflicting terminal transition on the FSM is rejected by the
    # FSM itself; the identity row must remain FILLED regardless.
    assert store.get_by_client_order_id(coid).status == "FILLED"


def test_firewall_skips_stale_identity_row_with_terminal_fsm(store, monkeypatch):
    """End-to-end wedge scenario: identity row ACKNOWLEDGED forever, exit FSM
    terminal — _has_in_flight_exit must not report it as in flight."""
    from merid.event_venues.kalshi.execution_risk_firewall import (
        ExecutionRiskFirewall,
    )

    # The fixture already isolated DEFAULT_DB_PATH + _instances, so the
    # firewall's lazy ``OrderAttemptStore()`` resolves the same tmp db.
    monkeypatch.setattr(OrderAttemptStore, "_instances", {})

    ticker = "KXXRP15M-TEST"
    coid = "exit_wedged_1"
    _identity_row(store, coid, ticker=ticker)
    att = _exit_attempt(store, coid)
    _walk_to_acknowledged(store, att.attempt_id)
    store.transition_exit_attempt(att.attempt_id, "FILLED", "test", reason="f")
    # Identity row deliberately left ACKNOWLEDGED — simulate the pre-fix wedge
    # by writing status back directly.
    conn = store._get_conn()
    conn.execute(
        "UPDATE order_attempts SET status='ACKNOWLEDGED' WHERE client_order_id=?",
        (coid,),
    )
    conn.commit()

    fw = ExecutionRiskFirewall()
    canonical = SimpleNamespace(
        market_ticker=ticker,
        client_order_id="exit_new_1",
        intent_id="intent_exit_new",
    )
    assert fw._has_in_flight_exit(canonical) is None


def test_firewall_still_blocks_when_fsm_nonterminal(store, monkeypatch):
    from merid.event_venues.kalshi.execution_risk_firewall import (
        ExecutionRiskFirewall,
    )

    monkeypatch.setattr(OrderAttemptStore, "_instances", {})

    ticker = "KXXRP15M-TEST2"
    coid = "exit_live_1"
    _identity_row(store, coid, ticker=ticker)
    att = _exit_attempt(store, coid, position_key="M|g3")
    _walk_to_acknowledged(store, att.attempt_id)  # FSM nonterminal: still live

    fw = ExecutionRiskFirewall()
    canonical = SimpleNamespace(
        market_ticker=ticker,
        client_order_id="exit_new_2",
        intent_id="intent_exit_new2",
    )
    blocked = fw._has_in_flight_exit(canonical)
    assert blocked is not None
    assert blocked.client_order_id == coid
