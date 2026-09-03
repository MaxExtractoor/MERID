import os
import shutil
import tempfile
from pathlib import Path

import pytest

from merid.event_venues.kalshi import order_attempt_store as _order_attempt_store
from merid.event_venues.kalshi.incidents.replayer import (
    ExitOrderIncidentReplay,
    KalshiIncidentReplayer,
    load_scenario,
)
from merid.event_venues.kalshi.order_attempt_store import (
    ExitOrderAttemptConflict,
    ExitOrderAttemptState,
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
def exit_json_path(monkeypatch):
    """Provide an isolated exit_intents.json file."""
    _dir = Path(tempfile.mkdtemp())
    path = _dir / "exit_intents.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("MERID_EXIT_INTENT_PERSISTENCE_PATH", str(path))
    yield path
    shutil.rmtree(_dir, ignore_errors=True)


def test_replay_synthetic_fomc():
    scenario_path = Path("tests/fixtures/kalshi-incidents/2026-02-14-fomc.json")
    scenario = load_scenario(scenario_path)

    replayer = KalshiIncidentReplayer(scenario)
    replayer.replay_metrics()
    replayer.replay_cb_events()
    report = replayer.generate_report()

    assert report["scenario_id"] == "2026-02-14-fomc"
    assert report["observed_cb_events"] == report["expected_cb_events"] == 1
    assert report["latency_samples"] == 4


@pytest.mark.asyncio
async def test_replay_exit_submission_unknown_lifecycle(temp_db_path, exit_json_path, monkeypatch):
    """End-to-end replay: process restart with a SUBMISSION_UNKNOWN exit reconciles to terminal."""
    # Treat all markets as tradeable so the fixture position is not rejected
    # for being a test ticker or for any date skew.
    monkeypatch.setattr(
        "merid.position_management.position_monitor._is_expired_ticker",
        lambda _: False,
    )

    scenario_path = Path("tests/fixtures/kalshi-incidents/2026-09-03-exit-submission-unknown.json")
    scenario = load_scenario(scenario_path)

    replay = ExitOrderIncidentReplay(scenario)

    # 1. Seed the durable store in the post-restart SUBMISSION_UNKNOWN state.
    record = replay.seed_exit_attempt()
    assert record.state == ExitOrderAttemptState.SUBMISSION_UNKNOWN.value
    assert record.client_order_id == "exit_ac7038bd3fc2a8f4fdbe"

    # 2. Only one active exit attempt may exist for a position at any time.
    with pytest.raises(ExitOrderAttemptConflict):
        replay.store.create_exit_attempt(
            exit_intent_id="intent-duplicate",
            position_key=record.position_key,
            ticker=record.ticker,
            reason="take_profit",
            client_order_id="exit-duplicate",
            requested_quantity=record.requested_quantity,
        )

    # 3. Build a PositionMonitor and prove it rehydrates the nonterminal attempt.
    position = replay.build_position()
    monitor = replay.monitor
    assert record.position_key in monitor._exit_intent_in_flight
    flight = monitor._exit_intent_in_flight[record.position_key]
    assert flight["client_order_id"] == record.client_order_id
    assert flight["attempt_id"] == record.attempt_id
    assert flight["state"] == ExitOrderAttemptState.SUBMISSION_UNKNOWN.value

    # 4. First exchange lookup: order is still resting. Durable state should move
    #    to RESOLVING_ON_EXCHANGE while the monitor keeps the in-flight guard.
    resting_evidence = scenario.exchange_evidence[0]
    resolving = await replay.reconcile(resting_evidence)
    assert resolving.state == ExitOrderAttemptState.RESOLVING_ON_EXCHANGE.value
    assert record.position_key in monitor._exit_intent_in_flight

    # 5. Second exchange lookup: order was canceled. The FSM should resolve
    #    SUBMISSION_UNKNOWN -> RESOLVING_ON_EXCHANGE -> CANCELED.
    canceled_evidence = scenario.exchange_evidence[1]
    terminal = await replay.reconcile(canceled_evidence)
    assert terminal.state == ExitOrderAttemptState.CANCELED.value
    assert monitor._is_exit_intent_in_flight(record.position_key) is False

    # 6. After terminalization, only one active attempt exists at a time.
    active = replay.store.get_active_exit_attempt_for_position(record.position_key)
    assert active is None

    new_record = replay.store.create_exit_attempt(
        exit_intent_id="intent-retry",
        position_key=record.position_key,
        ticker=record.ticker,
        reason="take_profit",
        client_order_id="exit-retry",
        requested_quantity=record.requested_quantity,
    )
    assert new_record.state == ExitOrderAttemptState.INTENT_PERSISTED.value
    assert replay.store.get_active_exit_attempt_for_position(record.position_key).client_order_id == "exit-retry"

    with pytest.raises(ExitOrderAttemptConflict):
        replay.store.create_exit_attempt(
            exit_intent_id="intent-duplicate-2",
            position_key=record.position_key,
            ticker=record.ticker,
            reason="take_profit",
            client_order_id="exit-duplicate-2",
            requested_quantity=record.requested_quantity,
        )
