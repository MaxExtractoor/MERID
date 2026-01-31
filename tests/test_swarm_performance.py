"""Tests for swarm.performance performance ledger."""

from __future__ import annotations

import json

import pytest

from swarm import performance


def _install_log_path(monkeypatch, tmp_path):
    log_path = tmp_path / "swarm_ledger.json"
    monkeypatch.setattr(performance, "LOG_PATH", log_path)
    return log_path


def test_record_cycle_updates_leaderboard_and_persists(monkeypatch, tmp_path):
    log_path = _install_log_path(monkeypatch, tmp_path)

    timestamps = iter(
        [f"2026-01-01T0{i}:00:00Z" for i in range(5)]
    )
    monkeypatch.setattr(performance, "current_time", lambda: {"utc_iso": next(timestamps)})

    ledger = performance.SwarmPerformanceLedger(decay_window_hours=6)

    votes = [
        {"agent_id": "agent_alpha", "vote": "accept"},
        {"agent_id": "agent_beta", "vote": "reject"},
    ]

    for _ in range(5):
        ledger.record_cycle(votes, approved=True)

    alpha = ledger._agents["agent_alpha"]
    beta = ledger._agents["agent_beta"]

    assert alpha.correct_votes == 5
    assert beta.incorrect_votes == 5

    board = ledger.leaderboard(limit=2)
    assert board[0]["agent_id"] == "agent_alpha"
    assert board[0]["score"] > board[1]["score"]

    parent = ledger.best_parent(min_score=0.5, min_votes=5)
    assert parent is not None
    assert parent["agent_id"] == "agent_alpha"

    persisted = json.loads(log_path.read_text(encoding="utf-8"))
    assert "agent_alpha" in persisted and persisted["agent_alpha"]["correct_votes"] == 5


def test_decay_weight_respects_window_and_min(monkeypatch, tmp_path):
    _install_log_path(monkeypatch, tmp_path)

    ledger = performance.SwarmPerformanceLedger(
        decay_window_hours=1,
        decay_rate=0.5,
        min_decay_weight=0.25,
    )

    entry = performance.AgentPerformance(agent_id="agent_delta")
    entry.last_active = "2026-01-01T00:00:00Z"
    entry.decay_weight = 1.0

    ledger._apply_decay(entry, "2026-01-01T00:30:00Z")
    assert entry.decay_weight == pytest.approx(1.0)

    ledger._apply_decay(entry, "2026-01-01T03:00:00Z")
    assert entry.decay_weight == pytest.approx(0.25)  # clamped to min weight
