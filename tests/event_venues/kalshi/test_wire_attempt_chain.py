"""Replacement wire IDs remain traceable to the original exit obligation."""

import pytest

from decimal import Decimal

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


def test_superseded_lookup_treats_wire_id_as_literal(tmp_path):
    store = OrderAttemptStore(tmp_path / "attempts.db")
    store.create_exit_attempt(
        exit_intent_id="intent-other", position_key="other", ticker="KXTEST",
        reason="exit", client_order_id="exitXabc:superseded:1", requested_quantity=100,
    )
    assert store.get_exit_attempt_by_wire_client_order_id("exit_abc") is None
    expected = store.create_exit_attempt(
        exit_intent_id="intent-1", position_key="position-1", ticker="KXTEST",
        reason="exit", client_order_id="exit_abc:superseded:2", requested_quantity=100,
    )
    assert store.get_exit_attempt_by_wire_client_order_id("exit_abc") == expected


def test_retry_identity_is_persisted_and_claimed_before_send(tmp_path, monkeypatch):
    from merid.event_venues.kalshi import order_attempt_store as attempts
    from merid.event_venues.kalshi.order_router import OrderIntent, _prepare_retry_wire_attempt
    from merid.event_venues.kalshi.port import CreateOrderRequest, CreateOrderResponse

    store = OrderAttemptStore(tmp_path / "attempts.db")
    monkeypatch.setattr(attempts, "OrderAttemptStore", lambda: store)
    store.persist_attempt(_attempt("root", "original"))
    intent = OrderIntent(
        ticker="KXTEST", side="yes", action="buy", count=1, price_cents=50,
        client_order_id="original", client_tag="original", intent_id="intent-1",
    )
    intent.order_attempt_id = "root"
    request = CreateOrderRequest(ticker="KXTEST", side="buy", outcome="yes", size=Decimal("1"))
    rejection = CreateOrderResponse(
        success=False, error="post only cross", submission_certainty="rejected",
    )

    wire = _prepare_retry_wire_attempt(intent, request, rejection, "reprice")
    child = store.get_by_client_order_id(wire)
    assert wire != "original"
    assert child.replaces_order_attempt_id == "root"
    assert child.status == "SUBMITTING"
    assert store.get_by_order_attempt_id("root").status == "REJECTED"
    assert request.client_order_id == request.idempotency_key == wire
    assert request.metadata["retry_of_client_order_id"] == "original"
    assert intent.client_order_id == intent.client_tag == "original"
    assert intent.order_attempt_id == child.order_attempt_id


@pytest.mark.parametrize("certainty", ["unknown", "pre_submit"])
def test_unproven_rejection_cannot_create_replacement(tmp_path, monkeypatch, certainty):
    from merid.event_venues.kalshi import order_attempt_store as attempts
    from merid.event_venues.kalshi.order_router import OrderIntent, _prepare_retry_wire_attempt
    from merid.event_venues.kalshi.port import CreateOrderRequest, CreateOrderResponse

    store = OrderAttemptStore(tmp_path / "attempts.db")
    monkeypatch.setattr(attempts, "OrderAttemptStore", lambda: store)
    store.persist_attempt(_attempt("root", "original"))
    intent = OrderIntent(
        ticker="KXTEST", side="yes", action="buy", count=1, price_cents=50,
        client_order_id="original", client_tag="original", intent_id="intent-1",
    )
    intent.order_attempt_id = "root"
    request = CreateOrderRequest(ticker="KXTEST", side="buy", outcome="yes", size=Decimal("1"))
    with pytest.raises(ValueError, match="confirmed"):
        _prepare_retry_wire_attempt(intent, request, CreateOrderResponse(
            success=False, error="post only cross", submission_certainty=certainty,
        ), "reprice")
    assert store.get_latest_wire_attempt("original").status == "SUBMITTING"


@pytest.mark.asyncio
async def test_unknown_retry_does_not_resolve_from_original_order(monkeypatch):
    import time
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock
    from merid.event_venues.kalshi import order_gate, order_router as router

    intent = router.OrderIntent(
        ticker="KXTEST", side="yes", action="buy", count=1, price_cents=50,
        client_order_id="original", client_tag="original", intent_id="intent-1",
    )
    intent._wire_client_order_id = "wire-child"
    monkeypatch.setattr(router, "_mark_attempt_status", MagicMock())
    monkeypatch.setattr(router, "_mark_canonical_entry_submitted", MagicMock())
    gate = MagicMock()
    monkeypatch.setattr(order_gate, "get_pre_trade_gate", lambda: gate)
    port = SimpleNamespace(
        get_order=AsyncMock(return_value=SimpleNamespace(
            client_order_id="original", status="canceled", order_id="old-order",
        )),
        get_fills=AsyncMock(return_value=SimpleNamespace(fills=[])),
    )
    result = await router._unknown_retry_result(
        intent, port, router.TradingMode.LIVE, time.monotonic(), "test",
    )
    assert result.status == "submission_unknown"
    assert result.wire_client_order_id == "wire-child"
    port.get_order.assert_awaited_once_with(client_order_id="wire-child", market_id=None)
    gate.mark_submission_unknown.assert_called_once_with("original")
