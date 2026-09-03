"""Exit-order attempt lifecycle: durable store, restart rehydration, and FSM.

These tests prove that the PositionMonitor and loop do not lose an in-flight
exit when data/exit_intents.json is edited, and that every logical exit has
exactly one durable client_order_id.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

import pytest

from merid.position_management.position import Position, PositionSide
from merid.position_management.position_monitor import PositionMonitor
from merid.event_venues.kalshi import order_attempt_store as _order_attempt_store
from merid.event_venues.kalshi.order_attempt_store import (
    ExitOrderAttemptState,
    ExitOrderAttemptConflict,
    OrderAttemptRecord,
    OrderAttemptStore,
)


@pytest.fixture
def temp_db_path():
    """Provide an isolated order-attempt SQLite database for each test."""
    _dir = Path(tempfile.mkdtemp())
    db_path = _dir / "kalshi_order_attempts.db"
    old_env = os.environ.get("MERID_KALSHI_ORDER_ATTEMPT_DB")
    old_default = _order_attempt_store.DEFAULT_DB_PATH
    os.environ["MERID_KALSHI_ORDER_ATTEMPT_DB"] = str(db_path)
    _order_attempt_store.DEFAULT_DB_PATH = str(db_path)
    # Force a fresh singleton for the temp path.
    OrderAttemptStore._instances.clear()
    yield str(db_path)
    if old_env is None:
        os.environ.pop("MERID_KALSHI_ORDER_ATTEMPT_DB", None)
    else:
        os.environ["MERID_KALSHI_ORDER_ATTEMPT_DB"] = old_env
    _order_attempt_store.DEFAULT_DB_PATH = old_default
    shutil.rmtree(_dir, ignore_errors=True)
    OrderAttemptStore._instances.clear()


@pytest.fixture
def exit_json_path():
    """Provide an isolated exit_intents.json file."""
    _dir = Path(tempfile.mkdtemp())
    path = _dir / "exit_intents.json"
    old_env = os.environ.get("MERID_EXIT_INTENT_PATH")
    # PositionMonitor hard-codes the path relative to project root; we patch it
    # via monkeypatch in tests that need a custom one.
    yield path
    shutil.rmtree(_dir, ignore_errors=True)


def _make_position(position_id: str = "pos-1", market_id: str = "KXBTC15M-TEST") -> Position:
    return Position(
        market_id=market_id,
        series_ticker="KXBTC15M",
        side=PositionSide.YES,
        size=1,
        avg_entry_price_cents=50,
        entry_fill_price_cents=50,
        risk_params_state="original_persisted",
        risk_params_schema_version=2,
        client_order_id="entry-1",
        entry_fill_id="fill-1",
    )


def test_store_prevents_two_active_attempts_for_same_position(temp_db_path):
    """A position cannot own two simultaneous active exit attempts."""
    store = OrderAttemptStore()
    store.create_exit_attempt(
        exit_intent_id="intent-1",
        position_key="pos-1",
        ticker="KXBTC15M-TEST",
        reason="take_profit",
        client_order_id="exit-coid-1",
        requested_quantity=100,
        requested_limit_cents=60,
    )
    with pytest.raises(ExitOrderAttemptConflict):
        store.create_exit_attempt(
            exit_intent_id="intent-2",
            position_key="pos-1",
            ticker="KXBTC15M-TEST",
            reason="stop_loss",
            client_order_id="exit-coid-2",
            requested_quantity=100,
            requested_limit_cents=40,
        )


def test_store_optimistic_concurrency_rejects_stale_transition(temp_db_path):
    """A transition with a stale expected_state_version is rejected."""
    store = OrderAttemptStore()
    record = store.create_exit_attempt(
        exit_intent_id="intent-1",
        position_key="pos-1",
        ticker="KXBTC15M-TEST",
        reason="take_profit",
        client_order_id="exit-coid-1",
        requested_quantity=100,
        requested_limit_cents=60,
    )
    first_version = record.state_version
    store.transition_exit_attempt(
        record.attempt_id,
        ExitOrderAttemptState.SUBMITTING.value,
        actor="test",
        reason="first",
    )
    stale = store.transition_exit_attempt(
        record.attempt_id,
        ExitOrderAttemptState.ACKNOWLEDGED.value,
        actor="test",
        reason="stale",
        expected_state_version=first_version,
    )
    assert stale is None


def test_monitor_rehydrates_nonterminal_exit_attempt_from_store(temp_db_path, monkeypatch):
    """A PositionMonitor created after a store record exists loads it."""
    store = OrderAttemptStore()
    record = store.create_exit_attempt(
        exit_intent_id="intent-1",
        position_key="pos-1",
        ticker="KXBTC15M-TEST",
        reason="take_profit",
        client_order_id="exit-coid-1",
        requested_quantity=100,
        requested_limit_cents=60,
    )
    store.transition_exit_attempt(
        record.attempt_id,
        ExitOrderAttemptState.SUBMITTING.value,
        actor="test",
        reason="route_start",
    )
    store.transition_exit_attempt(
        record.attempt_id,
        ExitOrderAttemptState.SUBMISSION_UNKNOWN.value,
        actor="test",
        reason="timeout",
    )

    # Use a fresh isolated exit_intents.json.
    _dir = Path(tempfile.mkdtemp())
    exit_path = _dir / "exit_intents.json"
    exit_path.write_text("{}")
    monkeypatch.setenv("MERID_EXIT_INTENT_PERSISTENCE_PATH", str(exit_path))

    monitor = PositionMonitor()
    assert monitor._is_exit_intent_in_flight("pos-1") is True
    assert monitor._exit_intent_in_flight["pos-1"]["client_order_id"] == "exit-coid-1"
    assert monitor._exit_intent_in_flight["pos-1"]["attempt_id"] == record.attempt_id
    assert monitor._exit_intent_in_flight["pos-1"]["state"] == ExitOrderAttemptState.SUBMISSION_UNKNOWN.value


def test_monitor_transitions_store_through_lifecycle(temp_db_path, monkeypatch):
    """_mark_exit_intent_* promote the durable FSM state."""
    store = OrderAttemptStore()
    record = store.create_exit_attempt(
        exit_intent_id="intent-1",
        position_key="pos-1",
        ticker="KXBTC15M-TEST",
        reason="take_profit",
        client_order_id="exit-coid-1",
        requested_quantity=100,
        requested_limit_cents=60,
    )

    _dir = Path(tempfile.mkdtemp())
    exit_path = _dir / "exit_intents.json"
    exit_path.write_text("{}")
    monkeypatch.setenv("MERID_EXIT_INTENT_PERSISTENCE_PATH", str(exit_path))

    monitor = PositionMonitor()
    pos = _make_position("pos-1")
    monitor.add_position(pos)

    monitor._mark_exit_intent_in_flight("pos-1", client_order_id="exit-coid-1", reason="take_profit")
    assert store.get_exit_attempt(record.attempt_id).state == ExitOrderAttemptState.SUBMITTING.value

    monitor._mark_exit_intent_submitted(
        "pos-1", client_order_id="exit-coid-1", exchange_order_id="order-123"
    )
    updated = store.get_exit_attempt(record.attempt_id)
    assert updated.state == ExitOrderAttemptState.ACKNOWLEDGED.value
    assert updated.exchange_order_id == "order-123"

    # SUBMISSION_UNKNOWN is only valid from SUBMITTING, so test it on a fresh
    # record that has not reached ACKNOWLEDGED.
    record2 = store.create_exit_attempt(
        exit_intent_id="intent-2",
        position_key="pos-2",
        ticker="KXBTC15M-TEST",
        reason="stop_loss",
        client_order_id="exit-coid-2",
        requested_quantity=100,
        requested_limit_cents=60,
    )
    store.transition_exit_attempt(
        record2.attempt_id,
        ExitOrderAttemptState.SUBMITTING.value,
        actor="test",
        reason="route_start",
    )
    pos2 = _make_position("pos-2", market_id="KXBTC15M-TEST2")
    monitor.add_position(pos2)
    monitor._mark_exit_intent_in_flight("pos-2", client_order_id="exit-coid-2", reason="stop_loss")
    monitor._mark_exit_intent_submission_unknown("pos-2", "route_timeout")
    assert store.get_exit_attempt(record2.attempt_id).state == ExitOrderAttemptState.SUBMISSION_UNKNOWN.value


def test_editing_exit_intents_json_does_not_erase_store_state(temp_db_path, monkeypatch):
    """Manual clearing of data/exit_intents.json does not remove durable state."""
    store = OrderAttemptStore()
    record = store.create_exit_attempt(
        exit_intent_id="intent-1",
        position_key="pos-1",
        ticker="KXBTC15M-TEST",
        reason="take_profit",
        client_order_id="exit-coid-1",
        requested_quantity=100,
        requested_limit_cents=60,
    )
    store.transition_exit_attempt(
        record.attempt_id,
        ExitOrderAttemptState.SUBMITTING.value,
        actor="test",
        reason="submit",
    )

    _dir = Path(tempfile.mkdtemp())
    exit_path = _dir / "exit_intents.json"
    # Simulate a manual clear: the JSON is empty but the store still has the attempt.
    exit_path.write_text("{}")
    monkeypatch.setenv("MERID_EXIT_INTENT_PERSISTENCE_PATH", str(exit_path))

    monitor = PositionMonitor()
    assert monitor._is_exit_intent_in_flight("pos-1") is True
    assert monitor._exit_intent_in_flight["pos-1"]["attempt_id"] == record.attempt_id


def _persist_legacy_order_attempt(client_order_id: str, position_id: str, status: str, store: OrderAttemptStore) -> OrderAttemptRecord:
    payload = {
        "type": "exit_order_attempt",
        "position_id": position_id,
        "market_id": "KXBTC15M-LEGACY",
        "exit_reason": "take_profit",
        "count": 1,
        "price_cents": 60,
    }
    legacy = OrderAttemptRecord(
        order_attempt_id=f"legacy_oa_{uuid.uuid4().hex}",
        client_order_id=client_order_id,
        decision_id=None,
        replaces_order_attempt_id=None,
        intent_id=f"legacy-intent-{position_id}",
        client_tag=client_order_id,
        run_id=None,
        process_id=None,
        fingerprint="legacy-fp",
        status=status,
        created_at=time.time(),
        updated_at=time.time(),
        payload_json=json.dumps(payload, default=str, sort_keys=True),
    )
    store.persist_attempt(legacy)
    return legacy


@pytest.mark.parametrize("legacy_status,expected_state", [
    ("SUBMISSION_UNKNOWN", ExitOrderAttemptState.SUBMISSION_UNKNOWN.value),
    ("ACKNOWLEDGED", ExitOrderAttemptState.ACKNOWLEDGED.value),
    ("SUBMITTING", ExitOrderAttemptState.SUBMITTING.value),
])
def test_monitor_migrates_legacy_order_attempts(temp_db_path, monkeypatch, legacy_status, expected_state):
    """Legacy order_attempts SUBMISSION_UNKNOWN/ACKNOWLEDGED/SUBMITTING records seed new lifecycle records."""
    store = OrderAttemptStore()
    _persist_legacy_order_attempt("legacy-exit-coid-1", "legacy-pos-1", legacy_status, store)

    _dir = Path(tempfile.mkdtemp())
    exit_path = _dir / "exit_intents.json"
    exit_path.write_text("{}")
    monkeypatch.setenv("MERID_EXIT_INTENT_PERSISTENCE_PATH", str(exit_path))

    monitor = PositionMonitor()
    assert monitor._is_exit_intent_in_flight("legacy-pos-1") is True
    assert monitor._exit_intent_in_flight["legacy-pos-1"]["client_order_id"] == "legacy-exit-coid-1"

    migrated = store.get_exit_attempt_by_client_order_id("legacy-exit-coid-1")
    assert migrated is not None
    assert migrated.state == expected_state
