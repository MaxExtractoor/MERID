"""Tests for swarm.gamification_swarm scaffolding."""

from __future__ import annotations

import pytest

from swarm import gamification_swarm as gam_mod


class DummyTelemetry:
    def __init__(self) -> None:
        self.records = []

    def log_structured(self, **kwargs):  # pragma: no cover - simple stub
        self.records.append(kwargs)


@pytest.fixture
def gamification(monkeypatch):
    telemetry = DummyTelemetry()
    monkeypatch.setattr(gam_mod, "get_telemetry_manager", lambda: telemetry)
    swarm = gam_mod.GamificationSwarm()
    return swarm, telemetry


def test_record_event_awards_weighted_xp(gamification):
    swarm, telemetry = gamification

    swarm.record_event(
        contributor="agent-1",
        event=gam_mod.GamificationEvent(
            event_type="flaky_fix",
            payload={"test": "tests.test_alpha"},
        ),
    )

    snapshot = swarm._ledger.snapshot()
    assert snapshot["xp"]["agent-1"] == pytest.approx(8.0)

    assert telemetry.records
    latest = telemetry.records[-1]
    assert latest["event_type"] == "score_update"
    assert latest["fields"]["score_delta"] == 8.0
    assert latest["fields"]["contributor"] == "agent-1"


def test_issue_and_complete_quest_updates_ledger(gamification):
    swarm, telemetry = gamification

    quest_id = swarm.issue_quest(
        contributor="agent-42",
        theme="coverage",
        objective="Raise core coverage by 5%",
        reward=25.0,
    )

    snapshot = swarm._ledger.snapshot()
    assert quest_id in snapshot["quests"]["agent-42"]

    swarm.complete_quest("agent-42", quest_id)

    snapshot_after = swarm._ledger.snapshot()
    assert quest_id not in snapshot_after["quests"].get("agent-42", {})
    assert snapshot_after["xp"]["agent-42"] == pytest.approx(10.0)

    event_types = [record["event_type"] for record in telemetry.records]
    assert "quest_issued" in event_types
    assert "quest_completed" in event_types
