"""An empty or failed lookup must not resolve an uncertain submission."""

import time
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from merid.event_venues.kalshi import order_attempt_store as attempts
from merid.event_venues.kalshi import order_router as router


@pytest.fixture
def attempt_store(tmp_path, monkeypatch):
    monkeypatch.setattr(attempts, "DEFAULT_DB_PATH", str(tmp_path / "attempts.db"))
    monkeypatch.setattr(attempts.OrderAttemptStore, "_instances", {})
    store = attempts.OrderAttemptStore()
    now = time.time()
    store.persist_attempt(attempts.OrderAttemptRecord(
        order_attempt_id="oa-1", client_order_id="co-1", decision_id="dec-1",
        replaces_order_attempt_id=None, intent_id="intent-1", client_tag=None,
        run_id=None, process_id=None, fingerprint="fp-1",
        status="SUBMISSION_UNKNOWN", created_at=now, updated_at=now,
        payload_json="{}",
    ))
    return store


def _intent():
    return router.OrderIntent(
        ticker="KXBTC15M-TEST", price_cents=50, count=1,
        side="yes", action="buy", client_order_id="co-1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_fast_lookup_empty_or_failed_stays_unknown(monkeypatch, failure):
    get_order = AsyncMock(side_effect=RuntimeError("unavailable")) if failure else AsyncMock(return_value=None)
    get_fills = AsyncMock(side_effect=RuntimeError("unavailable")) if failure else AsyncMock(
        return_value=SimpleNamespace(fills=[])
    )
    apply = Mock()
    monkeypatch.setattr(router, "_apply_reconciled_order", apply)
    result = await router._reconcile_submission_unknown(
        _intent(), SimpleNamespace(get_order=get_order, get_fills=get_fills),
        router.TradingMode.LIVE, time.monotonic(),
    )
    assert result is None
    apply.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_full_lookup_empty_or_failed_keeps_durable_state(
    attempt_store, monkeypatch, failure,
):
    get_order = AsyncMock(side_effect=RuntimeError("unavailable")) if failure else AsyncMock(return_value=None)
    get_fills = AsyncMock(side_effect=RuntimeError("unavailable")) if failure else AsyncMock(
        return_value=SimpleNamespace(fills=[])
    )
    apply = Mock()
    monkeypatch.setattr(router, "_apply_reconciled_order", apply)
    result = await router.reconcile_submission_unknown_client_order_id(
        SimpleNamespace(get_order=get_order, get_fills=get_fills),
        "co-1", "KXBTC15M-TEST",
    )
    assert result is None
    assert attempt_store.get_by_client_order_id("co-1").status == "SUBMISSION_UNKNOWN"
    apply.assert_not_called()


@pytest.mark.asyncio
async def test_mismatched_order_is_not_applied(attempt_store, monkeypatch):
    order = SimpleNamespace(client_order_id="other", order_id="order-2")
    client = SimpleNamespace(
        get_order=AsyncMock(return_value=order),
        get_fills=AsyncMock(return_value=SimpleNamespace(fills=[])),
    )
    apply = Mock()
    monkeypatch.setattr(router, "_apply_reconciled_order", apply)
    assert await router.reconcile_submission_unknown_client_order_id(
        client, "co-1", "KXBTC15M-TEST",
    ) is None
    assert attempt_store.get_by_client_order_id("co-1").status == "SUBMISSION_UNKNOWN"
    apply.assert_not_called()


@pytest.mark.asyncio
async def test_matching_order_is_recovered(attempt_store, monkeypatch):
    order = SimpleNamespace(client_order_id="co-1", order_id="order-1")
    client = SimpleNamespace(
        get_order=AsyncMock(return_value=order),
        get_fills=AsyncMock(return_value=SimpleNamespace(fills=[])),
    )
    apply = Mock(return_value="recovered")
    monkeypatch.setattr(router, "_apply_reconciled_order", apply)
    assert await router.reconcile_submission_unknown_client_order_id(
        client, "co-1", "KXBTC15M-TEST",
    ) == "recovered"
    assert apply.call_args.args[0] is order


def test_empty_tag_does_not_match_an_unrelated_fill():
    fill = SimpleNamespace(
        client_order_id=None, client_tag="", order_id="other", size=Decimal("1"),
    )
    assert router._resolve_from_broker_evidence(None, [], [fill], "co-1", "") is None


@pytest.mark.asyncio
async def test_fill_order_with_empty_identity_does_not_match(monkeypatch):
    order = SimpleNamespace(client_order_id="", client_tag="", order_id="other")
    fill = SimpleNamespace(
        client_order_id=None, client_tag="", order_id="other", size=Decimal("1"),
    )
    client = SimpleNamespace(
        get_order=AsyncMock(side_effect=[None, order]),
        get_fills=AsyncMock(return_value=SimpleNamespace(fills=[fill])),
    )
    apply = Mock()
    monkeypatch.setattr(router, "_apply_reconciled_order", apply)
    result = await router._reconcile_submission_unknown(
        _intent(), client, router.TradingMode.LIVE, time.monotonic(),
    )
    assert result is None
    apply.assert_not_called()
