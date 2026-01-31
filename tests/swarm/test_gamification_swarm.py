"""Tests for swarm.gamification_swarm."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from swarm.gamification_swarm import GamificationEvent, GamificationSwarm


class DummyTelemetry:
    def __init__(self) -> None:
        self.entries = []

    def log_structured(self, **kwargs) -> None:  # pragma: no cover - passthrough container
        self.entries.append(kwargs)


@pytest.fixture()
def gamification(monkeypatch):
    dummy = DummyTelemetry()
    monkeypatch.setattr("swarm.gamification_swarm.get_telemetry_manager", lambda: dummy)
    swarm = GamificationSwarm()
    return swarm, dummy


@pytest.mark.parametrize(
    ("contributor", "event", "expected_xp"),
    [
        ("alice", GamificationEvent(event_type="coverage_increase", payload={"delta": 5}), 5.0),
        (
            "agent-1",
            GamificationEvent(
                event_type="flaky_fix",
                payload={"test": "tests.test_alpha"},
            ),
            8.0,
        ),
    ],
)
def test_record_event_updates_xp_and_telemetry(contributor, event, expected_xp, gamification):
    swarm, telemetry = gamification

    swarm.record_event(contributor, event)
    snapshot = swarm._ledger.snapshot()

    assert snapshot["xp"][contributor] == pytest.approx(expected_xp)

    latest = telemetry.entries[-1]
    assert latest["event_type"] == "score_update"
    assert latest["fields"]["score_delta"] == expected_xp
    assert latest["fields"]["contributor"] == contributor


def test_issue_and_complete_quest_updates_ledger(gamification, monkeypatch):
    swarm, telemetry = gamification
    monkeypatch.setattr("uuid.uuid4", lambda: SimpleNamespace(hex="abcd1234"))

    quest_id = swarm.issue_quest("bob", theme="infra", objective="Fix alerts", reward=20.0)
    assert quest_id == "quest_abcd1234"

    snapshot = swarm._ledger.snapshot()
    assert quest_id in snapshot["quests"]["bob"]

    swarm.complete_quest("bob", quest_id)
    final_snapshot = swarm._ledger.snapshot()

    assert quest_id not in final_snapshot["quests"].get("bob", {})
    assert final_snapshot["xp"]["bob"] == pytest.approx(10.0)

    events = [entry["event_type"] for entry in telemetry.entries]
    assert events.count("quest_issued") == 1
    assert events.count("quest_completed") == 1
    assert events[-1] == "quest_completed"


def test_generate_weekly_report_emits_telemetry(gamification):
    swarm, telemetry = gamification
    report = swarm.generate_weekly_report()

    assert report == swarm._ledger.snapshot()
    assert telemetry.entries[-1]["event_type"] == "weekly_report"
