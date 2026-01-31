"""Tests for predictive health monitor and performance ledger modules."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import pytest

from swarm import predictive_health_monitor
from swarm.performance import SwarmPerformanceLedger
from swarm.predictive_health_monitor import PredictiveHealthMonitor


class _SequencedDatetime(datetime):
    """datetime replacement that yields predetermined utcnow values."""

    _iterator: Iterable[datetime] | None = None

    @classmethod
    def configure(cls, timeline: Iterable[datetime]) -> None:
        cls._iterator = iter(timeline)

    @classmethod
    def utcnow(cls) -> datetime:  # type: ignore[override]
        if cls._iterator is None:
            return datetime.utcnow()
        try:
            return next(cls._iterator)
        except StopIteration:  # pragma: no cover - defensive guard
            return datetime.utcnow()


def test_predictive_health_forecast_detects_breach(monkeypatch):
    base = datetime(2025, 1, 1, 12, 0)
    timeline = [base + timedelta(minutes=5 * i) for i in range(7)]
    _SequencedDatetime.configure(timeline)
    monkeypatch.setattr(predictive_health_monitor, "datetime", _SequencedDatetime)

    monitor = PredictiveHealthMonitor(horizon_minutes=60)
    for value in [50, 52, 55, 58, 61, 64]:
        monitor.record_metric("latency", value)

    forecast = monitor.forecast("latency", threshold=70.0)

    assert forecast is not None
    assert forecast.forecast_value > 64
    assert forecast.breach_time is not None
    assert forecast.breach_time > base
    assert 0.0 <= forecast.confidence <= 1.0


def test_predictive_health_requires_history():
    monitor = PredictiveHealthMonitor()
    for value in [100.0, 102.0, 105.0]:
        monitor.record_metric("error_rate", value)

    assert monitor.forecast("error_rate", threshold=120.0) is None


@pytest.fixture()
def ledger_env(tmp_path, monkeypatch):
    log_path = tmp_path / "swarm_perf.json"
    monkeypatch.setattr("swarm.performance.LOG_PATH", log_path)
    monkeypatch.setattr(predictive_health_monitor, "datetime", datetime)

    timestamps = iter([
        "2025-01-01T00:00:00Z",
        "2025-01-01T12:00:00Z",
        "2025-01-02T00:00:00Z",
    ])

    def fake_current_time() -> dict[str, str]:
        return {"utc_iso": next(timestamps)}

    monkeypatch.setattr("swarm.performance.current_time", fake_current_time)
    return log_path


def test_swarm_performance_records_and_persists(ledger_env):
    ledger = SwarmPerformanceLedger()
    votes = [
        {"agent_id": "alpha", "vote": "accept"},
        {"agent_id": "beta", "vote": "reject"},
        {"agent_id": "beta", "vote": "accept"},
    ]

    ledger.record_cycle(votes, approved=True)

    alpha = ledger._agents["alpha"]
    beta = ledger._agents["beta"]
    assert alpha.correct_votes == 1
    assert alpha.streak == 1
    assert beta.correct_votes == 1
    assert beta.incorrect_votes == 1

    stored = json.loads(Path(ledger_env).read_text())
    assert "alpha" in stored and "beta" in stored


def test_swarm_performance_decay_and_best_parent(ledger_env):
    ledger = SwarmPerformanceLedger(decay_window_hours=6, decay_rate=0.5, min_decay_weight=0.1)
    votes = [{"agent_id": "alpha", "vote": "accept"}]

    ledger.record_cycle(votes, approved=True)
    ledger.record_cycle(votes, approved=True)

    entry = ledger._agents["alpha"]
    assert entry.decay_weight == pytest.approx(0.25)
    assert entry.correct_votes == 2

    leaderboard = ledger.leaderboard(limit=1)
    assert leaderboard[0]["agent_id"] == "alpha"
    parent = ledger.best_parent(min_score=0.1, min_votes=1)
    assert parent["agent_id"] == "alpha"


def test_swarm_performance_loads_from_disk(ledger_env):
    first = SwarmPerformanceLedger()
    first.record_cycle([{"agent_id": "alpha", "vote": "accept"}], approved=True)

    reloaded = SwarmPerformanceLedger()
    assert "alpha" in reloaded._agents
    assert reloaded.best_parent(min_score=0.1, min_votes=1)["agent_id"] == "alpha"
