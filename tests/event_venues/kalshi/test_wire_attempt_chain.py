"""Replacement wire IDs remain traceable to the original exit obligation."""

import pytest

from merid.event_venues.kalshi.order_attempt_store import (
    OrderAttemptRecord,
    OrderAttemptStore,
)


def _attempt(attempt_id, coid, parent=None, intent_id="intent-1"):
    return OrderAttemptRecord(
        order_attempt_id=attempt_id, client_order_id=coid,
        decision_id=None, replaces_order_attempt_id=parent, intent_id=intent_id,
        client_tag="original", run_id=None, process_id=None, fingerprint="fp",
        status="SUBMITTING", created_at=1, updated_at=1, payload_json="{}",
    )


def test_wire_chain_finds_latest_and_attributes_fills_to_exit(tmp_path):
    store = OrderAttemptStore(tmp_path / "attempts.db")
    store.persist_attempt(_attempt("root", "original"))
    store.persist_attempt(_attempt("reprice", "wire-r", "root"))
    store.persist_attempt(_attempt("conversion", "wire-t", "reprice"))
    exit_attempt = store.create_exit_attempt(
        exit_intent_id="intent-1", position_key="position-1", ticker="KXTEST",
        reason="exit", client_order_id="original", requested_quantity=100,
        requested_limit_cents=50,
    )
    assert store.get_latest_wire_attempt("original").client_order_id == "wire-t"
    assert store.get_exit_attempt_by_wire_client_order_id("wire-r") == exit_attempt
    assert store.get_exit_attempt_by_wire_client_order_id("wire-t") == exit_attempt


def test_wire_chain_rejects_forks_and_wrong_intent(tmp_path):
    store = OrderAttemptStore(tmp_path / "attempts.db")
    store.persist_attempt(_attempt("root", "original"))
    store.persist_attempt(_attempt("child-1", "wire-1", "root"))
    store.persist_attempt(_attempt("child-2", "wire-2", "root"))
    with pytest.raises(ValueError, match="ambiguous"):
        store.get_latest_wire_attempt("original")

    store.persist_attempt(_attempt("other-root", "other"))
    store.persist_attempt(_attempt("wrong-child", "wrong", "other-root", "different"))
    with pytest.raises(ValueError, match="different intent"):
        store.get_latest_wire_attempt("other")
    with pytest.raises(ValueError, match="invalid"):
        store.get_exit_attempt_by_wire_client_order_id("wrong")
