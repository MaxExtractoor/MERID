"""
Regression tests for 2026-08-27 forced exit / stale in-flight reconciliation.

Covers the two critical patches:
1. _reconcile_exit_intent can be called with force=True to clear a stale
   SUBMISSION_UNKNOWN lock when the prior order is not live.
2. _emit_exit_intent is async and will force-reconcile an in-flight lock for
   safety exits (settlement guard, loss cap, etc.) before allowing a new exit.
"""

import asyncio
import os
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merid.position_management.position import Position, PositionSide
from merid.position_management.position_monitor import PositionMonitor
from merid.position_management.exit_policy import ExitReason
from merid.resilience.result import OperationResult


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
async def test_emit_exit_intent_forces_reconcile_on_submission_unknown(monitor):
    """A SETTLEMENT_GUARD intent must clear a stale SUBMISSION_UNKNOWN lock and re-emit."""
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

    assert len(callback_called) == 1
    assert callback_called[0][2] == 30
    assert callback_called[0][1] == ExitReason.SETTLEMENT_GUARD
    # A new in-flight record should be present for the forced exit.
    assert monitor._is_exit_intent_in_flight(position.position_id) is True
    flight = monitor._exit_intent_in_flight[position.position_id]
    assert flight["reason"] == ExitReason.SETTLEMENT_GUARD.value
    assert flight["state"] == "EXECUTION_PENDING"


@pytest.mark.asyncio
async def test_reconcile_exit_intent_force_cancels_stale_open_order(monitor):
    """A forced reconcile must cancel an existing open order at a stale price."""
    position = _make_position()
    monitor.add_position(position)

    client_order_id = "merid_test_stale_open"
    monitor._position_to_client_order[position.position_id] = client_order_id

    # Exchange reports an open order at 80c while the new settlement-guard exit is 30c.
    stale_order = MagicMock()
    stale_order.order_id = "ord_stale_123"
    stale_order.status = "open"
    stale_order.price = Decimal("0.80")

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

    # The stale open order should have been cancelled and the lock released.
    fake_client.cancel_order_result.assert_awaited_once()
    assert monitor._is_exit_intent_in_flight(position.position_id) is False
    assert position.exit_triggered is False


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


def test_cancel_durable_order_attempt_terminalizes_store(monitor):
    """_cancel_durable_order_attempt must mark a stale SUBMISSION_UNKNOWN record CANCELLED."""
    fake_store = MagicMock()
    fake_record = MagicMock(
        order_attempt_id="oa_test_cancel",
        status="SUBMISSION_UNKNOWN",
    )
    fake_store.get_by_client_order_id = MagicMock(return_value=fake_record)
    fake_store.update_status = MagicMock(return_value=True)

    with patch(
        "merid.event_venues.kalshi.order_attempt_store.OrderAttemptStore",
        return_value=fake_store,
    ):
        monitor._cancel_durable_order_attempt(
            "merid_test_cancel",
            "test_cancel_reason",
        )

    fake_store.update_status.assert_called_once()
    call_args = fake_store.update_status.call_args[0]
    assert call_args[0] == "oa_test_cancel"
    assert call_args[1] == "CANCELLED"


def test_startup_cleanup_clears_expired_position_in_flight(monitor):
    """_cleanup_stale_exit_in_flight_on_startup must remove expired positions and their locks."""
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

    assert position.position_id not in monitor._exit_intent_in_flight
    assert position.position_id not in monitor._position_to_client_order
    assert position.position_id not in monitor._open_positions
    assert client_order_id not in monitor._recent_exit_submissions
    fake_store.update_status.assert_not_called()  # cleanup does not touch store directly
