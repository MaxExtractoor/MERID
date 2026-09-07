"""Regression tests for durable order-attempt terminalization at route cleanup.

Background (2026-09-07 audit): 62 order attempts were left in ``PERSISTED``
and 4 in ``SUBMITTING`` forever because:

- Pre-submit rejection paths (idempotency gate, quote-mode block, risk guards)
  produced a terminal ``OrderResult`` but never updated the durable
  ``order_attempts`` row.
- The route-level ``asyncio.wait_for`` timeout cancels ``_route_live`` via
  ``CancelledError``, bypassing the inner ``except asyncio.TimeoutError`` that
  marks ``SUBMISSION_UNKNOWN``.

``_post_route_canonical_idempotency_cleanup`` now calls
``_finalize_attempt_store_for_result`` on every route outcome so the durable
audit trail can distinguish "never sent" from "in flight".
"""

from __future__ import annotations

import json
import time

import pytest

import merid.event_venues.kalshi.order_attempt_store as attempt_store_module
from merid.event_venues.kalshi.order_attempt_store import (
    OrderAttemptRecord,
    OrderAttemptStore,
)
from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    OrderResult,
    TradingMode,
    _finalize_attempt_store_for_result,
)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Isolated attempt store backed by a tmp sqlite db."""
    monkeypatch.setattr(
        attempt_store_module, "DEFAULT_DB_PATH", str(tmp_path / "attempts.db")
    )
    monkeypatch.setattr(OrderAttemptStore, "_instances", {})
    return OrderAttemptStore()


def _persist(store: OrderAttemptStore, status: str = "PERSISTED") -> OrderAttemptRecord:
    rec = OrderAttemptRecord(
        order_attempt_id=f"oa_{status.lower()}_{time.time_ns()}",
        client_order_id=f"coid_{time.time_ns()}",
        decision_id="dec-1",
        replaces_order_attempt_id=None,
        intent_id="intent-1",
        client_tag=None,
        run_id="run-1",
        process_id="pid-1",
        fingerprint="fp-1",
        status=status,
        created_at=time.time(),
        updated_at=time.time(),
        payload_json=json.dumps({"fingerprint_source": "finalize_order_identity"}),
    )
    store.persist_attempt(rec)
    return rec


def _intent_for(rec: OrderAttemptRecord) -> OrderIntent:
    intent = OrderIntent(
        ticker="KXBTC15M-TEST",
        price_cents=50,
        count=1,
        side="no",
        action="buy",
    )
    intent.order_attempt_id = rec.order_attempt_id
    intent.client_order_id = rec.client_order_id
    return intent


def _result(status: str, **kwargs) -> OrderResult:
    return OrderResult(status=status, mode=TradingMode.LIVE, **kwargs)


def test_persisted_pre_submit_rejection_becomes_rejected(store):
    rec = _persist(store, "PERSISTED")
    _finalize_attempt_store_for_result(
        _intent_for(rec),
        _result("rejected", reason="insufficient_balance", submission_attempted=False),
    )
    updated = store.get_by_order_attempt_id(rec.order_attempt_id)
    assert updated.status == "REJECTED"
    payload = json.loads(updated.payload_json)
    # Original identity payload is preserved, not clobbered.
    assert payload["fingerprint_source"] == "finalize_order_identity"
    assert payload["terminalized_by"] == "post_route_cleanup"
    assert payload["route_reason"] == "insufficient_balance"


def test_persisted_route_exception_becomes_rejected(store):
    rec = _persist(store, "PERSISTED")
    _finalize_attempt_store_for_result(_intent_for(rec), None)
    assert store.get_by_order_attempt_id(rec.order_attempt_id).status == "REJECTED"


def test_persisted_submission_unknown_result_becomes_rejected(store):
    """A route-timeout result on a PERSISTED attempt is provably not sent."""
    rec = _persist(store, "PERSISTED")
    _finalize_attempt_store_for_result(
        _intent_for(rec),
        _result(
            "submission_unknown",
            reason="route_timeout:25.0s",
            submission_attempted=True,
            submission_certainty="unknown",
        ),
    )
    assert store.get_by_order_attempt_id(rec.order_attempt_id).status == "REJECTED"


def test_submitting_route_timeout_becomes_submission_unknown(store):
    """The CancelledError path bypassed the in-route SUBMISSION_UNKNOWN marker."""
    rec = _persist(store, "SUBMITTING")
    _finalize_attempt_store_for_result(
        _intent_for(rec),
        _result(
            "submission_unknown",
            reason="route_timeout:25.0s",
            submission_attempted=True,
            submission_certainty="unknown",
        ),
    )
    assert (
        store.get_by_order_attempt_id(rec.order_attempt_id).status
        == "SUBMISSION_UNKNOWN"
    )


def test_submitting_route_exception_becomes_submission_unknown(store):
    rec = _persist(store, "SUBMITTING")
    _finalize_attempt_store_for_result(_intent_for(rec), None)
    assert (
        store.get_by_order_attempt_id(rec.order_attempt_id).status
        == "SUBMISSION_UNKNOWN"
    )


def test_submitting_resting_result_becomes_acknowledged(store):
    rec = _persist(store, "SUBMITTING")
    _finalize_attempt_store_for_result(_intent_for(rec), _result("resting"))
    assert store.get_by_order_attempt_id(rec.order_attempt_id).status == "ACKNOWLEDGED"


def test_persisted_filled_result_becomes_filled(store):
    """Recovery found a fill for an attempt whose in-route marker failed."""
    rec = _persist(store, "PERSISTED")
    _finalize_attempt_store_for_result(
        _intent_for(rec),
        _result("filled_live", fill={"filled_count": 1, "price_cents": 50}),
    )
    assert store.get_by_order_attempt_id(rec.order_attempt_id).status == "FILLED"


def test_terminal_records_are_never_downgraded(store):
    rec = _persist(store, "REJECTED")
    _finalize_attempt_store_for_result(_intent_for(rec), _result("resting"))
    assert store.get_by_order_attempt_id(rec.order_attempt_id).status == "REJECTED"


def test_acknowledged_record_not_regressed_by_rejection(store):
    rec = _persist(store, "ACKNOWLEDGED")
    _finalize_attempt_store_for_result(
        _intent_for(rec), _result("rejected", reason="late_reject")
    )
    assert store.get_by_order_attempt_id(rec.order_attempt_id).status == "ACKNOWLEDGED"


def test_no_attempt_id_is_noop(store):
    intent = OrderIntent(ticker="KXBTC15M-TEST", price_cents=50, count=1)
    _finalize_attempt_store_for_result(intent, _result("rejected"))  # no raise
