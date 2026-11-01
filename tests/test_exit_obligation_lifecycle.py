"""Durable exit-obligation lifecycle tests (2026-10-08 repair).

Live evidence (data/kalshi_order_attempts.db): 391 attempts wedged at
INTENT_PERSISTED — 388 legacy JSON-migrated records plus genuine
never-dispatched stalls — because nothing could transition an unsubmitted
obligation to a terminal state.  191 ``duplicate:concurrent_in_flight``
results were also mislabeled SUBMISSION_UNKNOWN, regressing healthy attempts.

These tests pin conservative timeout handling and the durable FSM. A legacy
or stale INTENT_PERSISTED record is not proof that dispatch never occurred.
"""

import json
import time
from types import SimpleNamespace

import pytest

import merid.event_venues.kalshi.order_attempt_store as attempt_store_module
from merid.event_venues.kalshi.order_attempt_store import (
    ExitOrderAttemptConflict,
    ExitOrderAttemptState,
    OrderAttemptStore,
)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(
        attempt_store_module, "DEFAULT_DB_PATH", str(tmp_path / "attempts.db")
    )
    monkeypatch.setattr(OrderAttemptStore, "_instances", {})
    return OrderAttemptStore()


@pytest.fixture()
def monitor(tmp_path, monkeypatch, store):
    """PositionMonitor backed by the isolated attempt store + persistence path."""
    monkeypatch.setenv(
        "MERID_EXIT_INTENT_PERSISTENCE_PATH", str(tmp_path / "exit_intents.json")
    )
    from merid.position_management.position_monitor import PositionMonitor

    return PositionMonitor()


def _attempt(store, position_key="pos-1", age_s=0.0, payload=None, coid=None):
    rec = store.create_exit_attempt(
        exit_intent_id=f"intent_{position_key}_{time.time_ns()}",
        position_key=position_key,
        ticker="KXBTC15M-TEST",
        reason="take_profit",
        client_order_id=coid or f"coid_{position_key}_{time.time_ns()}",
        requested_quantity=100,
        requested_limit_cents=55,
        payload=payload,
    )
    if age_s:
        conn = store._get_conn()
        with conn:
            conn.execute(
                "UPDATE exit_order_attempts SET created_at=? WHERE attempt_id=?",
                (time.time() - age_s, rec.attempt_id),
            )
        rec = store.get_exit_attempt(rec.attempt_id)
    return rec


class TestFsmEdge:
    def test_intent_persisted_terminal_unfilled_is_valid(self, store):
        rec = _attempt(store)
        updated = store.transition_exit_attempt(
            rec.attempt_id,
            ExitOrderAttemptState.TERMINAL_UNFILLED.value,
            actor="test",
            reason="unsubmitted_age_limit:worker_not_dispatched",
        )
        assert updated is not None
        assert updated.state == ExitOrderAttemptState.TERMINAL_UNFILLED.value

    @pytest.mark.parametrize("new_state", [
        ExitOrderAttemptState.SUBMISSION_UNKNOWN,
        ExitOrderAttemptState.RESOLVING_ON_EXCHANGE,
    ])
    def test_persisted_may_require_reconciliation(self, store, new_state):
        rec = _attempt(store)
        updated = store.transition_exit_attempt(
            rec.attempt_id, new_state.value, actor="test", reason="uncertain_dispatch"
        )
        assert updated is not None and updated.state == new_state.value

    def test_intent_persisted_rejected_exchange_still_invalid(self, store):
        """REJECTED_EXCHANGE remains invalid from INTENT_PERSISTED — the old
        exception handler relied on it and silently left stalls."""
        rec = _attempt(store)
        assert (
            store.transition_exit_attempt(
                rec.attempt_id,
                ExitOrderAttemptState.REJECTED_EXCHANGE.value,
                actor="test",
                reason="exception",
            )
            is None
        )


class TestSingleObligation:
    def test_second_attempt_conflicts_while_active(self, store):
        _attempt(store, position_key="pos-dup")
        with pytest.raises(ExitOrderAttemptConflict):
            _attempt(store, position_key="pos-dup")

    def test_terminal_obligation_allows_fresh_attempt(self, store):
        rec = _attempt(store, position_key="pos-dup")
        store.transition_exit_attempt(
            rec.attempt_id,
            ExitOrderAttemptState.TERMINAL_UNFILLED.value,
            actor="test",
            reason="unsubmitted_age_limit:worker_not_dispatched",
        )
        fresh = _attempt(store, position_key="pos-dup")
        assert fresh.attempt_id != rec.attempt_id


class TestStaleObligationSweep:
    def test_migrated_legacy_is_reconciled_not_terminalized(self, monitor, store, monkeypatch):
        rec = _attempt(
            store,
            position_key="pos-gone",
            age_s=600.0,
            payload={"migrated_from_json": True, "legacy_state": "EXECUTION_PENDING"},
        )
        scheduled = []
        monkeypatch.setattr(monitor, "_schedule_exit_reconcile", lambda pid, coid: scheduled.append((pid, coid)))
        assert monitor._sweep_stale_exit_obligations() == 1
        assert (
            store.get_exit_attempt(rec.attempt_id).state
            == ExitOrderAttemptState.INTENT_PERSISTED.value
        )
        assert scheduled == [(rec.position_key, rec.client_order_id)]

    def test_open_position_stall_schedules_reconciliation(self, monitor, store, monkeypatch):
        from merid.position_management.position import Position, PositionSide

        monitor._open_positions["pos-open"] = Position(
            position_id="pos-open",
            market_id="KXBTC15M-TEST",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=50,
        )
        rec = _attempt(store, position_key="pos-open", age_s=600.0)
        scheduled = []
        monkeypatch.setattr(monitor, "_schedule_exit_reconcile", lambda pid, coid: scheduled.append((pid, coid)))
        assert monitor._sweep_stale_exit_obligations() == 1
        assert store.get_exit_attempt(rec.attempt_id).state == ExitOrderAttemptState.INTENT_PERSISTED.value
        assert scheduled == [(rec.position_key, rec.client_order_id)]

    def test_fresh_obligation_untouched(self, monitor, store):
        rec = _attempt(store, position_key="pos-fresh", age_s=5.0)
        assert monitor._sweep_stale_exit_obligations() == 0
        assert (
            store.get_exit_attempt(rec.attempt_id).state
            == ExitOrderAttemptState.INTENT_PERSISTED.value
        )

    def test_sweep_preserves_in_memory_lock(self, monitor, store, monkeypatch):
        rec = _attempt(store, position_key="pos-locked", age_s=600.0)
        monitor._exit_intent_in_flight["pos-locked"] = {
            "state": "EXECUTION_PENDING",
            "timestamp": time.time() - 600,
            "client_order_id": rec.client_order_id,
        }
        monitor._position_to_client_order["pos-locked"] = rec.client_order_id
        monkeypatch.setattr(monitor, "_schedule_exit_reconcile", lambda pid, coid: None)
        assert monitor._sweep_stale_exit_obligations() == 1
        assert "pos-locked" in monitor._exit_intent_in_flight
        assert "pos-locked" in monitor._position_to_client_order
        assert monitor._is_exit_intent_in_flight("pos-locked") is True


class TestTimeoutClassification:
    def test_persisted_timeout_is_unknown(self, monitor, store):
        """An absent exit lifecycle transition does not prove no order was sent."""
        rec = _attempt(store, position_key="pos-nd")
        monitor._exit_intent_in_flight["pos-nd"] = {
            "state": "EXECUTION_PENDING",
            "timestamp": time.time() - 999,
            "client_order_id": rec.client_order_id,
        }
        assert monitor._is_exit_intent_in_flight("pos-nd") is True
        assert (
            store.get_exit_attempt(rec.attempt_id).state
            == ExitOrderAttemptState.SUBMISSION_UNKNOWN.value
        )
        assert monitor._exit_intent_in_flight["pos-nd"]["state"] == "SUBMISSION_UNKNOWN"

    def test_dispatched_timeout_becomes_submission_unknown(self, monitor, store):
        """Durable SUBMITTING means the router call ran — the ack is genuinely
        lost, so SUBMISSION_UNKNOWN + reconcile is correct."""
        rec = _attempt(store, position_key="pos-disp")
        store.transition_exit_attempt(
            rec.attempt_id,
            ExitOrderAttemptState.SUBMITTING.value,
            actor="test",
            reason="dispatch",
        )
        monitor._exit_intent_in_flight["pos-disp"] = {
            "state": "EXECUTION_PENDING",
            "timestamp": time.time() - 999,
            "client_order_id": rec.client_order_id,
        }
        assert monitor._is_exit_intent_in_flight("pos-disp") is True
        assert monitor._exit_intent_in_flight["pos-disp"]["state"] == "SUBMISSION_UNKNOWN"
        # Durable record advanced to SUBMISSION_UNKNOWN as well.
        assert (
            store.get_exit_attempt(rec.attempt_id).state
            == ExitOrderAttemptState.SUBMISSION_UNKNOWN.value
        )

    def test_recent_submission_keeps_lock(self, monitor, store):
        rec = _attempt(store, position_key="pos-recent")
        monitor._exit_intent_in_flight["pos-recent"] = {
            "state": "EXECUTION_PENDING",
            "timestamp": time.time() - 999,
            "client_order_id": rec.client_order_id,
        }
        monitor._recent_exit_submissions[rec.client_order_id] = time.time()
        assert monitor._is_exit_intent_in_flight("pos-recent") is True
        assert monitor._exit_intent_in_flight["pos-recent"]["state"] == "EXECUTION_PENDING"


class TestWorkingOrderSurvival:
    def test_working_attempt_blocks_new_obligation(self, monitor, store):
        """A RESTING exit order survives re-evaluation: the single-obligation
        constraint rejects a second attempt while the first works."""
        rec = _attempt(store, position_key="pos-work")
        for state in (
            ExitOrderAttemptState.SUBMITTING,
            ExitOrderAttemptState.ACKNOWLEDGED,
            ExitOrderAttemptState.RESTING,
        ):
            assert store.transition_exit_attempt(
                rec.attempt_id, state.value, actor="test", reason="drive"
            )
        with pytest.raises(ExitOrderAttemptConflict):
            _attempt(store, position_key="pos-work")

    def test_submitted_flight_blocks_redispatch(self, monitor, store):
        rec = _attempt(store, position_key="pos-sub")
        monitor._exit_intent_in_flight["pos-sub"] = {
            "state": "SUBMITTED",
            "timestamp": time.time(),
            "client_order_id": rec.client_order_id,
        }
        assert monitor._is_exit_intent_in_flight("pos-sub") is True
