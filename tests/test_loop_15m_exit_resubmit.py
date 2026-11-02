"""Tests for uncertain exit submissions and duplicate execution protection."""

import pytest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock

from merid.event_venues.kalshi.order_router import OrderResult, TradingMode
from merid.loop_15m import (
    _execute_exit_order,
    _exit_result_never_dispatched,
    _rearm_position_after_failed_exit,
)
from merid.position_management.exit_policy import ExitReason
from merid.position_management.position import Position, PositionSide


@pytest.fixture(autouse=True)
def _isolated_runtime_state(tmp_path, monkeypatch):
    from merid.observability import live_runtime_state

    monkeypatch.setattr(
        live_runtime_state, "_live_runtime_state",
        live_runtime_state.LiveRuntimeState(tmp_path / "runtime_state.json"),
    )


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
    pm._reconcile_exit_registry.return_value = []
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


@pytest.mark.parametrize("status", ["rejected", "not_submitted"])
@pytest.mark.parametrize(
    "evidence",
    [
        {"submission_attempted": True},
        {"exchange_request_sent": True},
        {"exchange_ack_received": True},
        {"order_id": "venue-order"},
        {"submission_certainty": "unknown"},
    ],
)
def test_never_dispatched_refuses_contradictory_evidence(status, evidence):
    result = OrderResult(status=status, mode=TradingMode.LIVE, **evidence)
    assert not _exit_result_never_dispatched(result, status)


@pytest.mark.parametrize("status", ["rejected", "not_submitted"])
def test_never_dispatched_accepts_proven_pre_submit(status):
    result = OrderResult(status=status, mode=TradingMode.LIVE)
    assert _exit_result_never_dispatched(result, status)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "not_submitted", "not_submitted_unknown", "not_submitted_ack",
        "not_submitted_order", "pre_submit_exhausted", "rejected",
        "missing_durable", "existing_attempt",
        "identity_mismatch", "filled_store_failure", "filled_exit_failure",
    ],
)
async def test_unproven_exit_outcome_retains_lock(
    self_mock, position, monkeypatch, tmp_path, failure
):
    """An empty lookup after a request cannot justify another exit."""

    # Durable arbiter state must not leak into repo data/ — redirect the
    # store paths and drop the singleton so it rebuilds under tmp_path.
    monkeypatch.setenv(
        "MERID_EXIT_ATTEMPTS_PATH", str(tmp_path / "exit_attempts.json"))
    monkeypatch.setenv(
        "MERID_EXIT_STATE_PATH", str(tmp_path / "exit_state.json"))
    monkeypatch.setattr(
        "merid.position_management.exit_arbiter._ARBITER", None)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_attempt_store.DEFAULT_DB_PATH",
        str(tmp_path / "attempts.db"),
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_attempt_store.OrderAttemptStore._instances", {}
    )
    if failure == "missing_durable":
        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_attempt_store.OrderAttemptStore.create_exit_attempt",
            MagicMock(side_effect=OSError("database unavailable")),
        )
    if failure == "existing_attempt":
        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_attempt_store.OrderAttemptStore.get_exit_attempt_by_client_order_id",
            lambda self, coid: SimpleNamespace(
                client_order_id=coid, attempt_id="exit-existing", state="SUBMITTING"
            ),
        )

    route_calls = []
    if failure == "filled_store_failure":
        self_mock._position_monitor._update_order_attempt_status.return_value = False
    if failure == "filled_exit_failure":
        self_mock._position_monitor._update_order_attempt_status.return_value = True
        self_mock._position_monitor._mark_exit_intent_reconciled.return_value = False

    async def _fake_route(intent):
        route_calls.append((intent.client_order_id, intent.order_attempt_id))
        if failure not in ("filled_store_failure", "filled_exit_failure"):
            if failure == "pre_submit_exhausted":
                return OrderResult(status="not_submitted", mode=TradingMode.LIVE)
            if failure.startswith("not_submitted_"):
                return OrderResult(
                    status="not_submitted",
                    mode=TradingMode.LIVE,
                    submission_certainty=(
                        "unknown" if failure == "not_submitted_unknown" else "pre_submit"
                    ),
                    exchange_ack_received=failure == "not_submitted_ack",
                    order_id="unexpected-order" if failure == "not_submitted_order" else None,
                )
            return OrderResult(
                status=failure,
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
        if failure == "identity_mismatch":
            intent.client_order_id = "different-client-id"
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

    if failure == "pre_submit_exhausted":
        assert len(route_calls) == 3
        assert len({coid for coid, _ in route_calls}) == 1
        self_mock._position_monitor._mark_exit_intent_reconciled.assert_called_once()
        self_mock._position_monitor._mark_exit_intent_submission_unknown.assert_not_called()
        self_mock._rearm_position_after_failed_exit.assert_called_once()
        return

    assert len(route_calls) == (
        0 if failure in ("missing_durable", "existing_attempt", "identity_mismatch") else 1
    )
    assert self_mock._rearm_position_after_failed_exit.called is False
    assert self_mock._position_monitor._mark_exit_intent_retryable.called is False
    if failure in ("missing_durable", "identity_mismatch"):
        self_mock._position_monitor._mark_exit_intent_reconciliation_required.assert_called_once()
    elif failure.startswith("not_submitted") or failure in ("rejected", "existing_attempt"):
        self_mock._position_monitor._mark_exit_intent_submission_unknown.assert_called_once()
    else:
        self_mock._position_monitor._update_order_attempt_status.assert_called_once()
    assert self_mock._position_monitor._mark_exit_intent_submitted.called is failure.startswith("filled_")
    assert self_mock._position_monitor._mark_exit_intent_in_flight.called is (failure != "missing_durable")
    assert self_mock._position_monitor.remove_position.called is False


@pytest.mark.asyncio
async def test_duplicate_worker_does_not_clear_existing_lock(self_mock, position):
    self_mock._position_monitor._get_position_lock.return_value.acquire.return_value = False
    await _execute_exit_order(self_mock, position, ExitReason.TAKE_PROFIT, 60)
    self_mock._position_monitor._clear_exit_intent_in_flight.assert_not_called()


def test_rearm_does_not_drop_unresolved_order(self_mock, position):
    monitor = self_mock._position_monitor
    monitor._clear_exit_intent_if_unsubmitted.return_value = False
    original_size = position.size
    _rearm_position_after_failed_exit(
        self_mock, position, ExitReason.TAKE_PROFIT, contracts_to_close=1,
    )
    monitor._clear_exit_intent_in_flight.assert_not_called()
    monitor.add_position.assert_not_called()
    assert position.size == original_size
