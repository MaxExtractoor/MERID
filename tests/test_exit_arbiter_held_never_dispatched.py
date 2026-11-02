"""A local arbiter hold must not leave a durable exit as submission unknown."""

from threading import RLock
from types import SimpleNamespace

import pytest

from merid.loop_15m import _terminalize_arbiter_held_exit
from merid.event_venues.kalshi.order_attempt_store import OrderAttemptStore
import merid.position_management.position_monitor as monitor_module
from merid.position_management.position_monitor import PositionMonitor


@pytest.fixture(autouse=True)
def _isolated_runtime_state(tmp_path, monkeypatch):
    from merid.observability import live_runtime_state

    monkeypatch.setattr(
        live_runtime_state, "_live_runtime_state",
        live_runtime_state.LiveRuntimeState(tmp_path / "runtime_state.json"),
    )


def _monitor(transition_ok=True):
    monitor = PositionMonitor.__new__(PositionMonitor)
    monitor._lock = RLock()
    monitor._exit_intent_in_flight = {
        "position": {
            "state": "EXECUTION_PENDING",
            "client_order_id": "exit-1",
            "attempt_id": "attempt-1",
        }
    }
    monitor._position_to_client_order = {"position": "exit-1"}
    monitor._recent_exit_submissions = {"exit-1": 1}
    monitor._open_positions = {}
    monitor._save_exit_intent_in_flight = lambda: None
    transitions = []

    def transition(coid, state, reason, **kwargs):
        transitions.append((coid, state, reason, kwargs))
        return transition_ok

    monitor._transition_exit_attempt = transition
    return monitor, transitions


def _prepared(status="held_unmarketable", approved=False, attempt=None):
    return SimpleNamespace(
        approved=approved,
        result=SimpleNamespace(status=status, attempt=attempt),
    )


def test_held_exit_terminalizes_and_clears_only_its_identity():
    monitor, transitions = _monitor()
    assert _terminalize_arbiter_held_exit(
        monitor, "position", "exit-1", _prepared()
    )
    assert transitions[0][:3] == ("exit-1", "TERMINAL_UNFILLED", "never_dispatched")
    assert transitions[0][3]["raw_payload"]["never_dispatched_evidence"] == (
        "arbiter_held_before_route"
    )
    assert not monitor._exit_intent_in_flight
    assert not monitor._position_to_client_order
    assert not monitor._recent_exit_submissions
    assert monitor._clear_exit_intent_if_unsubmitted("position")


@pytest.mark.parametrize(
    "prepared",
    [
        _prepared(status="in_flight"),
        _prepared(status="reconcile_required"),
        _prepared(status="rejected"),
        _prepared(approved=True),
        _prepared(attempt=object()),
    ],
)
def test_uncertain_or_other_outcomes_remain_in_flight(prepared):
    monitor, transitions = _monitor()
    assert not _terminalize_arbiter_held_exit(
        monitor, "position", "exit-1", prepared
    )
    assert not transitions
    assert monitor._position_to_client_order["position"] == "exit-1"
    assert monitor._exit_intent_in_flight["position"]["state"] == "EXECUTION_PENDING"


def test_failed_durable_transition_keeps_the_lock():
    monitor, transitions = _monitor(transition_ok=False)
    assert not _terminalize_arbiter_held_exit(
        monitor, "position", "exit-1", _prepared()
    )
    assert transitions
    assert monitor._position_to_client_order["position"] == "exit-1"
    assert monitor._exit_intent_in_flight["position"]["state"] == "EXECUTION_PENDING"


def test_other_client_order_is_not_cleared():
    monitor, transitions = _monitor()
    assert not _terminalize_arbiter_held_exit(
        monitor, "position", "exit-other", _prepared()
    )
    assert not transitions
    assert monitor._position_to_client_order["position"] == "exit-1"
    assert monitor._exit_intent_in_flight["position"]["state"] == "EXECUTION_PENDING"


def test_held_exit_terminalizes_real_durable_attempt(tmp_path, monkeypatch):
    store = OrderAttemptStore(str(tmp_path / "attempts.db"))
    attempt = store.create_exit_attempt(
        exit_intent_id="intent-1", position_key="position",
        ticker="KXETH15M-TEST", reason="trail", client_order_id="exit-1",
        requested_quantity=200,
    )
    assert store.transition_exit_attempt(
        attempt.attempt_id, "SUBMITTING", "test", "test"
    )
    monitor, _ = _monitor()
    monitor._transition_exit_attempt = PositionMonitor._transition_exit_attempt.__get__(monitor)
    monkeypatch.setattr(monitor_module, "OrderAttemptStore", lambda: store)

    assert _terminalize_arbiter_held_exit(
        monitor, "position", "exit-1", _prepared()
    )
    assert store.get_exit_attempt(attempt.attempt_id).state == "TERMINAL_UNFILLED"
