"""
Regression tests for 2026-08-27 forced exit / stale in-flight reconciliation.

Covers the two critical patches:
1. Empty or failed lookups preserve a SUBMISSION_UNKNOWN lock.
2. Forced exits reconcile the prior order before allowing a new exit.
"""

import asyncio
import os
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from merid.position_management.position import Position, PositionSide
from merid.position_management.position_monitor import PositionMonitor
from merid.position_management.exit_policy import ExitReason
from merid.resilience.result import OperationResult
from merid.event_venues.base import PlacedOrder


@pytest.fixture
def monitor(monkeypatch):
    """Fresh PositionMonitor for each test; treat all markets as tradeable."""
    monkeypatch.setattr(
        "merid.position_management.position_monitor._is_expired_ticker",
        lambda _: False,
    )
    return PositionMonitor()


def _make_position(market_id: str = "KXSOL15M-01SEP270845-45") -> Position:
    return Position(
        market_id=market_id,
        series_ticker="KXSOL15M",
        side=PositionSide.YES,
        size=Decimal("1"),
        avg_entry_price_cents=50,
        take_profit_price_cents=80,
        stop_loss_price_cents=40,
    )


def test_forced_exit_reason_settlement_guard():
    """Settlement guard must be treated as a forced / safety exit."""
    from merid.position_management.position_monitor import _is_forced_exit_reason
    assert _is_forced_exit_reason(ExitReason.SETTLEMENT_GUARD) is True
    assert _is_forced_exit_reason(ExitReason.LOSS_CAP) is True
    assert _is_forced_exit_reason(ExitReason.TAKE_PROFIT) is False
    assert _is_forced_exit_reason(None) is False


def test_settlement_guard_env_override(monkeypatch):
    """MERID_SETTLEMENT_BYPASS_IN_FLIGHT makes settlement guard bypass the in-flight lock."""
    from merid.position_management.position_monitor import _is_settlement_guard_override
    monkeypatch.setenv("MERID_SETTLEMENT_BYPASS_IN_FLIGHT", "1")
    assert _is_settlement_guard_override(ExitReason.SETTLEMENT_GUARD) is True
    assert _is_settlement_guard_override(ExitReason.LOSS_CAP) is False
    monkeypatch.delenv("MERID_SETTLEMENT_BYPASS_IN_FLIGHT", raising=False)
    assert _is_settlement_guard_override(ExitReason.SETTLEMENT_GUARD) is False


@pytest.mark.asyncio
async def test_emit_exit_intent_forces_reconcile_on_submission_unknown(monitor, monkeypatch):
    """An empty lookup cannot authorize another exit, even for a forced exit."""
    # The 2026-10-14 profit_only_v1 breakeven floor suppresses below-entry
    # sells (exit 30c < entry 50c) before intent emission — orthogonal to the
    # stale-lock reconcile path under test.
    monkeypatch.setenv("MERID_PROFIT_ONLY_EXITS", "0")
    position = _make_position()
    monitor.add_position(position)

    # Simulate an earlier take-profit attempt that timed out into SUBMISSION_UNKNOWN.
    client_order_id = "merid_2aebae634057406b9f12"
    monitor._position_to_client_order[position.position_id] = client_order_id
    monitor._exit_intent_in_flight[position.position_id] = {
        "state": "SUBMISSION_UNKNOWN",
        "timestamp": 0.0,
        "client_order_id": client_order_id,
        "reason": ExitReason.TAKE_PROFIT.value,
        "last_reconcile_at": 0.0,
        "reconcile_count": 0,
    }

    callback_called = []

    def callback(pos, reason, price, contracts=None):
        callback_called.append((pos.position_id, reason, price, contracts))

    monitor._exit_intent_callback = callback

    # Mock the Kalshi client: order not found, no open orders, position still live.
    fake_client = MagicMock()
    fake_client.get_order_by_client_id_result = AsyncMock(
        return_value=OperationResult.ok(data=None)
    )
    fake_client.get_open_orders = AsyncMock(return_value=[])
    fake_client.get_positions = AsyncMock(
        return_value=[
            MagicMock(market_id=position.market_id, size=Decimal("1"))
        ]
    )

    with patch(
        "merid.event_venues.kalshi.client.get_kalshi_client",
        return_value=fake_client,
    ):
        await monitor._emit_exit_intent(
            position,
            ExitReason.SETTLEMENT_GUARD,
            30,
            snapshot=None,
        )

    assert not callback_called
    assert monitor._is_exit_intent_in_flight(position.position_id) is True
    flight = monitor._exit_intent_in_flight[position.position_id]
    assert flight["reason"] == ExitReason.TAKE_PROFIT.value
    assert flight["state"] == "SUBMISSION_UNKNOWN"


@pytest.mark.asyncio
async def test_reconcile_exit_intent_force_cancels_stale_open_order(monitor, monkeypatch):
    """A forced reconcile must cancel an existing open order at a stale price."""
    position = _make_position()
    monitor.add_position(position)

    client_order_id = "merid_test_stale_open"
    monkeypatch.setattr(monitor, "_transition_exit_attempt", Mock(return_value="attempt-1"))
    monkeypatch.setattr(monitor, "_update_order_attempt_status", Mock(return_value=True))
    monitor._position_to_client_order[position.position_id] = client_order_id
    monitor._exit_intent_in_flight[position.position_id] = {
        "state": "SUBMISSION_UNKNOWN", "timestamp": 0.0,
        "client_order_id": client_order_id, "reason": ExitReason.TAKE_PROFIT.value,
    }

    # Exchange reports an open order at 80c while the new settlement-guard exit is 30c.
    stale_order = MagicMock()
    stale_order.order_id = "ord_stale_123"
    stale_order.status = "open"
    stale_order.price = Decimal("0.80")
    stale_order.filled_size = Decimal("0")
    stale_order.market_id = position.market_id
    stale_order.raw_data = {"client_order_id": client_order_id, "fill_count_fp": "0.00"}

    fake_client = MagicMock()
    fake_client.get_order_by_client_id_result = AsyncMock(
        return_value=OperationResult.ok(data=stale_order)
    )
    fake_client.cancel_order_result = AsyncMock(
        return_value=OperationResult.ok(data=True)
    )

    with patch(
        "merid.event_venues.kalshi.client.get_kalshi_client",
        return_value=fake_client,
    ):
        await monitor._reconcile_exit_intent(
            position.position_id,
            client_order_id,
            force=True,
            new_price_cents=30,
        )

    # A cancel acknowledgement alone does not prove no fill raced the cancel.
    fake_client.cancel_order_result.assert_awaited_once()
    assert monitor._is_exit_intent_in_flight(position.position_id) is True
    stale_order.status = "canceled"
    with patch(
        "merid.event_venues.kalshi.client.get_kalshi_client",
        return_value=fake_client,
    ):
        await monitor._reconcile_exit_intent(position.position_id, client_order_id)
    assert monitor._is_exit_intent_in_flight(position.position_id) is False
    assert position.exit_triggered is False


def _isolated_attempt_store(tmp_path, monkeypatch):
    from merid.event_venues.kalshi import order_attempt_store as attempts

    monkeypatch.setattr(attempts, "DEFAULT_DB_PATH", str(tmp_path / "attempts.db"))
    monkeypatch.setattr(attempts.OrderAttemptStore, "_instances", {})
    return attempts.OrderAttemptStore()


@pytest.mark.asyncio
async def test_reconcile_releases_never_dispatched_attempt(monitor, tmp_path, monkeypatch):
    """An aged INTENT_PERSISTED attempt with an unclaimed canonical record
    provably never reached the wire; reconcile must terminalize and release it
    so a pre-dispatch crash cannot wedge the position's exits forever."""
    import sqlite3
    from merid.event_venues.kalshi.order_attempt_store import ExitOrderAttemptState

    store = _isolated_attempt_store(tmp_path, monkeypatch)
    position = _make_position()
    monitor.add_position(position)
    coid = "exit_co_never_sent"

    rec = store.create_exit_attempt(
        exit_intent_id="ei-1", position_key=position.position_id,
        ticker=position.market_id, reason="take_profit",
        client_order_id=coid, requested_quantity=100,
    )
    # Age the attempt past the 300s mid-dispatch bound.
    conn = store._get_conn()
    conn.execute(
        "UPDATE exit_order_attempts SET created_at = ? WHERE attempt_id = ?",
        (time.time() - 400, rec.attempt_id),
    )
    conn.commit()

    monitor._position_to_client_order[position.position_id] = coid
    monitor._exit_intent_in_flight[position.position_id] = {
        "state": "SUBMISSION_UNKNOWN", "timestamp": 0.0,
        "client_order_id": coid, "reason": ExitReason.TAKE_PROFIT.value,
    }
    position.exit_triggered = True
    position.exit_reason = "take_profit"
    position.exit_price_cents = 80

    fake_client = MagicMock()
    fake_client.get_order_by_client_id_result = AsyncMock(
        return_value=OperationResult.ok(data=None)
    )
    with patch(
        "merid.event_venues.kalshi.client.get_kalshi_client",
        return_value=fake_client,
    ):
        await monitor._reconcile_exit_intent(position.position_id, coid)

    updated = store.get_exit_attempt(rec.attempt_id)
    assert updated.state == ExitOrderAttemptState.TERMINAL_UNFILLED.value
    assert monitor._is_exit_intent_in_flight(position.position_id) is False
    assert position.exit_triggered is False
    # The release is a local proof — no exchange call was needed or made.
    fake_client.get_order_by_client_id_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_keeps_young_or_claimed_attempt(monitor, tmp_path, monkeypatch):
    """A recently created INTENT_PERSISTED attempt could still be mid-dispatch;
    reconcile must retain it rather than assert never-sent."""
    from merid.event_venues.kalshi.order_attempt_store import ExitOrderAttemptState

    store = _isolated_attempt_store(tmp_path, monkeypatch)
    position = _make_position()
    monitor.add_position(position)
    coid = "exit_co_maybe_flying"

    rec = store.create_exit_attempt(
        exit_intent_id="ei-2", position_key=position.position_id,
        ticker=position.market_id, reason="take_profit",
        client_order_id=coid, requested_quantity=100,
    )
    monitor._position_to_client_order[position.position_id] = coid
    monitor._exit_intent_in_flight[position.position_id] = {
        "state": "SUBMISSION_UNKNOWN", "timestamp": 0.0,
        "client_order_id": coid, "reason": ExitReason.TAKE_PROFIT.value,
    }

    fake_client = MagicMock()
    fake_client.get_order_by_client_id_result = AsyncMock(
        return_value=OperationResult.ok(data=None)
    )
    with patch(
        "merid.event_venues.kalshi.client.get_kalshi_client",
        return_value=fake_client,
    ):
        await monitor._reconcile_exit_intent(position.position_id, coid)

    assert store.get_exit_attempt(rec.attempt_id).state == (
        ExitOrderAttemptState.RESOLVING_ON_EXCHANGE.value
    )
    assert monitor._is_exit_intent_in_flight(position.position_id) is True


@pytest.mark.asyncio
async def test_reconcile_exit_intent_keeps_live_same_price_order(monitor):
    """A forced reconcile must keep an existing open order at the same exit price."""
    position = _make_position()
    monitor.add_position(position)

    client_order_id = "merid_test_same_price"
    monitor._position_to_client_order[position.position_id] = client_order_id
    monitor._exit_intent_in_flight[position.position_id] = {
        "state": "SUBMISSION_UNKNOWN",
        "timestamp": 0.0,
        "client_order_id": client_order_id,
        "reason": ExitReason.TAKE_PROFIT.value,
        "last_reconcile_at": 0.0,
        "reconcile_count": 0,
    }

    live_order = MagicMock()
    live_order.order_id = "ord_live_456"
    live_order.status = "resting"
    live_order.price = Decimal("0.30")
    live_order.market_id = position.market_id
    live_order.raw_data = {"client_order_id": client_order_id}

    fake_client = MagicMock()
    fake_client.get_order_by_client_id_result = AsyncMock(
        return_value=OperationResult.ok(data=live_order)
    )
    fake_client.cancel_order_result = AsyncMock(
        return_value=OperationResult.ok(data=True)
    )

    with patch(
        "merid.event_venues.kalshi.client.get_kalshi_client",
        return_value=fake_client,
    ):
        await monitor._reconcile_exit_intent(
            position.position_id,
            client_order_id,
            force=True,
            new_price_cents=30,
        )

    # Same price means no cancel; the in-flight lock should remain live.
    fake_client.cancel_order_result.assert_not_awaited()
    assert monitor._is_exit_intent_in_flight(position.position_id) is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", ["empty", "client_mismatch", "market_mismatch", "missing_fills", "partial", "executed"]
)
async def test_inconclusive_order_evidence_preserves_exit_lock(monitor, monkeypatch, case):
    position = _make_position()
    monitor.add_position(position)
    coid = "exit_inconclusive"
    monitor._position_to_client_order[position.position_id] = coid
    monitor._exit_intent_in_flight[position.position_id] = {
        "state": "SUBMISSION_UNKNOWN", "timestamp": time.time(), "client_order_id": coid,
    }
    raw = {"client_order_id": coid, "fill_count_fp": "0.00"}
    market = position.market_id
    status = "canceled"
    if case == "client_mismatch":
        raw["client_order_id"] = "other"
    elif case == "market_mismatch":
        market = "OTHER-MARKET"
    elif case == "missing_fills":
        del raw["fill_count_fp"]
    elif case == "partial":
        raw["fill_count_fp"] = "0.50"
    elif case == "executed":
        status = "executed"
        raw["fill_count_fp"] = "1.00"
    order = None if case == "empty" else PlacedOrder(
        order_id="order-1", market_id=market, side="sell", size=Decimal("1"),
        price=Decimal("0.50"), status=status, raw_data=raw,
    )
    client = MagicMock()
    client.get_order_by_client_id_result = AsyncMock(return_value=OperationResult.ok(data=order))
    client.cancel_order_result = AsyncMock()
    monkeypatch.setattr("merid.event_venues.kalshi.client.get_kalshi_client", lambda: client)
    monkeypatch.setattr(monitor, "_transition_exit_attempt", Mock())
    update_status = Mock()
    monkeypatch.setattr(monitor, "_update_order_attempt_status", update_status)

    await monitor._reconcile_exit_intent(position.position_id, coid, force=True, new_price_cents=30)
    assert monitor._exit_intent_in_flight[position.position_id]["state"] == "SUBMISSION_UNKNOWN"
    update_status.assert_not_called()
    client.cancel_order_result.assert_not_awaited()


@pytest.mark.parametrize(
    "reason", ["position_closed", "retry_unknown_submission", "expired_no_client_order_id", "partially_filled"]
)
def test_unproven_reason_cannot_terminalize_exit(monitor, monkeypatch, reason):
    pid = "position-unresolved"
    monitor._exit_intent_in_flight[pid] = {"state": "SUBMISSION_UNKNOWN", "client_order_id": "exit-1"}
    transition = Mock()
    monkeypatch.setattr(monitor, "_transition_exit_attempt", transition)
    assert monitor._mark_exit_intent_reconciled(pid, reason) is False
    assert monitor._exit_intent_in_flight[pid]["state"] == "SUBMISSION_UNKNOWN"
    transition.assert_not_called()


def test_failed_durable_transition_preserves_lock(monitor, monkeypatch):
    pid = "position-unresolved"
    monitor._exit_intent_in_flight[pid] = {"state": "SUBMISSION_UNKNOWN", "client_order_id": "exit-1"}
    monkeypatch.setattr(monitor, "_transition_exit_attempt", Mock(return_value=None))
    assert monitor._mark_exit_intent_reconciled(pid, "order_canceled") is False
    assert monitor._exit_intent_in_flight[pid]["state"] == "SUBMISSION_UNKNOWN"


@pytest.mark.parametrize(
    "flight,mapped,cleared",
    [
        ({"state": "EXECUTION_PENDING"}, None, True),
        ({"state": "EXECUTION_PENDING", "client_order_id": "exit-1"}, None, False),
        ({"state": "EXECUTION_PENDING", "attempt_id": "attempt-1"}, None, False),
        ({"state": "SUBMISSION_UNKNOWN"}, None, False),
        ({"state": "EXECUTION_PENDING"}, "exit-1", False),
    ],
)
def test_pre_dispatch_clear_retains_identified_or_unknown_intents(monitor, flight, mapped, cleared):
    pid = "position-pre-dispatch"
    monitor._exit_intent_in_flight[pid] = flight
    if mapped:
        monitor._position_to_client_order[pid] = mapped
    assert monitor._clear_exit_intent_if_unsubmitted(pid) is cleared
    assert (pid not in monitor._exit_intent_in_flight) is cleared


@pytest.mark.asyncio
async def test_failed_generic_order_update_preserves_exit_lock(monitor, monkeypatch):
    position = _make_position()
    monitor.add_position(position)
    coid = "exit_failed_update"
    monitor._exit_intent_in_flight[position.position_id] = {
        "state": "SUBMISSION_UNKNOWN", "timestamp": time.time(), "client_order_id": coid,
    }
    order = PlacedOrder(
        order_id="order-1", market_id=position.market_id, side="sell",
        size=Decimal("1"), price=Decimal("0.50"), status="canceled",
        raw_data={"client_order_id": coid, "fill_count_fp": "0.00"},
    )
    client = MagicMock()
    client.get_order_by_client_id_result = AsyncMock(return_value=OperationResult.ok(data=order))
    monkeypatch.setattr("merid.event_venues.kalshi.client.get_kalshi_client", lambda: client)
    transition = Mock(return_value="attempt-1")
    monkeypatch.setattr(monitor, "_transition_exit_attempt", transition)
    monkeypatch.setattr(monitor, "_update_order_attempt_status", Mock(return_value=False))
    await monitor._reconcile_exit_intent(position.position_id, coid)
    assert monitor._exit_intent_in_flight[position.position_id]["state"] == "SUBMISSION_UNKNOWN"
    assert all(call.args[1] != "CANCELED" for call in transition.call_args_list)


@pytest.mark.asyncio
async def test_bypass_flag_does_not_skip_unknown_exit_lock(monitor):
    position = _make_position()
    monitor.add_position(position)
    monitor._exit_intent_in_flight[position.position_id] = {
        "state": "SUBMISSION_UNKNOWN", "timestamp": time.time(), "client_order_id": "exit-1",
    }
    monitor._exit_intent_callback = Mock()
    await monitor._emit_exit_intent(
        position, ExitReason.TAKE_PROFIT, 80, bypass_in_flight_check=True,
    )
    monitor._exit_intent_callback.assert_not_called()
    assert monitor._exit_intent_in_flight[position.position_id]["state"] == "SUBMISSION_UNKNOWN"


@pytest.mark.asyncio
async def test_reconcile_exit_intent_periodic_retry_counts(monitor):
    """_is_exit_intent_in_flight must re-attempt reconciliation up to a bounded count."""
    position = _make_position()
    monitor.add_position(position)

    client_order_id = "merid_test_retry"
    monitor._position_to_client_order[position.position_id] = client_order_id
    monitor._exit_intent_in_flight[position.position_id] = {
        "state": "SUBMISSION_UNKNOWN",
        "timestamp": 0.0,
        "client_order_id": client_order_id,
        "reason": ExitReason.TAKE_PROFIT.value,
        "last_reconcile_at": 0.0,
        "reconcile_count": 0,
    }

    fake_client = MagicMock()
    fake_client.get_order_by_client_id_result = AsyncMock(
        return_value=OperationResult.ok(data=None)
    )
    fake_client.get_open_orders = AsyncMock(return_value=[])
    fake_client.get_positions = AsyncMock(
        return_value=[MagicMock(market_id=position.market_id, size=Decimal("1"))]
    )

    with patch(
        "merid.event_venues.kalshi.client.get_kalshi_client",
        return_value=fake_client,
    ):
        # First call should trigger a new reconcile task.
        result = monitor._is_exit_intent_in_flight(position.position_id)
        assert result is True
        flight = monitor._exit_intent_in_flight[position.position_id]
        assert flight["reconcile_count"] == 1

        # Run the reconcile task to completion.
        await asyncio.sleep(0)


def test_startup_cleanup_preserves_expired_unknown_intent(monitor):
    """Expiry does not establish the outcome of a submitted order."""
    position = _make_position()
    monitor.add_position(position)

    client_order_id = "merid_test_startup_cleanup"
    monitor._position_to_client_order[position.position_id] = client_order_id
    monitor._exit_intent_in_flight[position.position_id] = {
        "state": "SUBMISSION_UNKNOWN",
        "timestamp": 0.0,
        "client_order_id": client_order_id,
        "reason": ExitReason.TAKE_PROFIT.value,
        "last_reconcile_at": 0.0,
        "reconcile_count": 0,
    }
    monitor._recent_exit_submissions[client_order_id] = 0.0

    # Force the position's market to be treated as expired after it was added.
    monitor._is_expired_market = lambda market_id: True

    fake_store = MagicMock()
    fake_record = MagicMock(
        order_attempt_id="oa_test_startup",
        status="SUBMISSION_UNKNOWN",
    )
    fake_store.get_by_client_order_id = MagicMock(return_value=fake_record)
    fake_store.update_status = MagicMock(return_value=True)

    with patch(
        "merid.event_venues.kalshi.order_attempt_store.OrderAttemptStore",
        return_value=fake_store,
    ):
        monitor._cleanup_stale_exit_in_flight_on_startup()

    assert position.position_id in monitor._exit_intent_in_flight
    assert position.position_id in monitor._position_to_client_order
    assert position.position_id in monitor._open_positions
    assert client_order_id in monitor._recent_exit_submissions
    fake_store.update_status.assert_not_called()  # cleanup does not touch store directly
