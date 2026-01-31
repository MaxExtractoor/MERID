from __future__ import annotations

import json
from datetime import datetime

import pytest

from swarm import performance


@pytest.fixture(autouse=True)
def _cleanup_logs(tmp_path, monkeypatch):
    # Prevent the module-level ledger from writing to the repo logs directory during tests.
    monkeypatch.setattr(performance, "LOG_PATH", tmp_path / "swarm_performance.json", raising=False)
    yield


def test_coerce_dt_parses_z_suffix_and_handles_invalid():
    dt = performance._coerce_dt("2025-01-02T03:04:05Z")
    assert dt == datetime(2025, 1, 2, 3, 4, 5)

    before = datetime.utcnow()
    fallback = performance._coerce_dt("not-a-date")
    assert isinstance(fallback, datetime)
    assert 0 <= (fallback - before).total_seconds() < 5


def test_agent_performance_metrics_and_serialization():
    record = performance.AgentPerformance(agent_id="agent-1")
    record.total_votes = 5
    record.correct_votes = 3
    record.incorrect_votes = 2
    record.streak = 2
    record.decay_weight = 0.9
    record.accuracy_window.extend([1, 0, 1, 1])

    assert record.base_accuracy() == pytest.approx(0.6)
    assert record.rolling_accuracy() == pytest.approx(0.75)
    assert record.score() > 0.6

    payload = record.to_dict()
    restored = performance.AgentPerformance.from_dict(payload)
    assert restored.agent_id == "agent-1"
    assert restored.total_votes == 5
    assert list(restored.accuracy_window) == [1, 0, 1, 1]


def test_record_cycle_applies_decay_and_persists(tmp_path):
    log_file = tmp_path / "ledger.json"
    ledger = performance.SwarmPerformanceLedger(
        log_path=log_file,
        decay_window_hours=6,
        decay_rate=0.5,
        now_provider=lambda: {"utc_iso": "2024-01-02T12:00:00Z"},
    )

    entry = performance.AgentPerformance(agent_id="agent-decay")
    entry.last_active = "2024-01-01T00:00:00Z"
    entry.decay_weight = 1.0
    ledger._agents[entry.agent_id] = entry

    ledger.record_cycle([
        {"agent_id": "agent-decay", "vote": "accept"},
        {"agent_id": "agent-new", "vote": "reject"},
    ], approved=True)

    assert entry.decay_weight < 1.0
    assert log_file.exists()

    with log_file.open() as handle:
        payload = json.load(handle)
        assert "agent-new" in payload


def test_leaderboard_and_best_parent_from_loaded_state(tmp_path):
    log_file = tmp_path / "ledger.json"
    log_file.write_text(
        json.dumps(
            {
                "agent-alpha": {
                    "agent_id": "agent-alpha",
                    "accuracy_window": [1, 1, 0, 1],
                    "total_votes": 10,
                    "correct_votes": 8,
                    "incorrect_votes": 2,
                    "last_active": "2025-01-01T00:00:00Z",
                    "streak": 3,
                    "decay_weight": 0.95,
                }
            }
        )
    )

    ledger = performance.SwarmPerformanceLedger(log_path=log_file)

    leaderboard = ledger.leaderboard(limit=5)
    assert leaderboard[0]["agent_id"] == "agent-alpha"

    best = ledger.best_parent(min_score=0.1, min_votes=1)
    assert best is not None
    assert best["agent_id"] == "agent-alpha"
