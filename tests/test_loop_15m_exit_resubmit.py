"""Tests for loop_15m _execute_exit_order resubmission on not_submitted."""

import pytest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock

from merid.event_venues.kalshi.order_router import OrderResult, TradingMode
from merid.loop_15m import _execute_exit_order
from merid.position_management.exit_policy import ExitReason
from merid.position_management.position import Position, PositionSide


@pytest.fixture
def self_mock():
    """Minimal Kalshi15mLoop stand-in for _execute_exit_order."""
    self = MagicMock()
    pm = MagicMock()
    pm._get_position_lock.return_value = MagicMock(
        acquire=MagicMock(return_value=True),
        release=MagicMock(),
    )
    pm._get_unresolved_exit_client_order_id.return_value = None
    pm._has_exit_order.return_value = False
    pm._get_exit_orders_for_position.return_value = []
    pm._get_total_exit_quantity.return_value = 0
    self._position_monitor = pm
    self._rearm_position_after_failed_exit = MagicMock()
    self._mark_exited = MagicMock()
    self._release_position_lock = MagicMock()
    return self


@pytest.fixture
def position():
    return Position(
        position_id="pos-resubmit-01",
        market_id="KXBTC15M-TEST-50000",
        side=PositionSide.YES,
        size=Decimal("5"),
        avg_entry_price_cents=50,
    )


@pytest.mark.asyncio
async def test_exit_not_submitted_resubmits_with_same_client_order_id(
    self_mock, position, monkeypatch
):
    """_execute_exit_order resubmits with the same ClOrdID on not_submitted,
    keeps the in-flight guard, and does not rearm or retry."""

    route_calls = []

    async def _fake_route(intent):
        route_calls.append((intent.client_order_id, intent.order_attempt_id))
        if len(route_calls) == 1:
            return OrderResult(
                status="not_submitted",
                mode=TradingMode.LIVE,
                reason="not_submitted:authoritative_lookup_empty",
                submission_attempted=True,
            )
        return OrderResult(
            status="filled_live",
            mode=TradingMode.LIVE,
            order_id="order-resubmit-01",
            fill={
                "quantity_cc": 500,
                "count": 5,
                "price_cents": 60,
                "client_tag": intent.client_order_id,
                "order_id": "order-resubmit-01",
            },
        )

    def _fake_finalize(intent):
        intent.client_order_id = "coid-resubmit-01"
        intent.client_tag = "coid-resubmit-01"
        intent.order_attempt_id = "oa-resubmit-01"

    monkeypatch.setattr("merid.event_venues.kalshi.order_router.route_order_async", _fake_route)
    monkeypatch.setattr("merid.event_venues.kalshi.order_identity.finalize_order_identity", _fake_finalize)
    monkeypatch.setattr("merid.event_venues.kalshi.order_intent_contract.persist_order_decision", lambda *a, **k: None)
    monkeypatch.setattr(
        "merid.loop_15m._run_exit_price_guard",
        lambda *a, **k: (True, 60, MagicMock(), "guard-1"),
    )
    async def _fake_post_position_cc(*a, **k):
        return 0

    monkeypatch.setattr("merid.loop_15m._get_canonical_post_position_cc", _fake_post_position_cc)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.canonical_portfolio_reconciler.get_canonical_portfolio_reconciler",
        lambda: MagicMock(build_snapshot=AsyncMock(return_value=SimpleNamespace())),
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.canonical_portfolio.get_canonical_portfolio_store",
        lambda: MagicMock(publish=lambda x: None),
    )
    monkeypatch.setattr("merid.event_venues.kalshi.exit_finalizer.can_finalize_full_exit", lambda *a, **k: (True, "test"))
    monkeypatch.setattr(
        "merid.event_venues.kalshi.resting_order_monitor.get_resting_order_monitor",
        lambda: MagicMock(get_orders_by_ticker=MagicMock(return_value=[])),
    )

    await _execute_exit_order(self_mock, position, ExitReason.TAKE_PROFIT, 60)

    # The same idempotency key was used for both attempts.
    assert len(route_calls) == 2
    assert route_calls[0][0] == route_calls[1][0] == "coid-resubmit-01"
    assert route_calls[0][1] == route_calls[1][1] == "oa-resubmit-01"

    # In-flight was preserved; no rearm/retry or submission_unknown.
    assert self_mock._rearm_position_after_failed_exit.called is False
    assert self_mock._position_monitor._mark_exit_intent_retryable.called is False
    assert self_mock._position_monitor._mark_exit_intent_submission_unknown.called is False
    assert self_mock._position_monitor._mark_exit_intent_submitted.called is True
    assert self_mock._position_monitor._mark_exit_intent_in_flight.called is True
    assert self_mock._position_monitor.remove_position.called is True
