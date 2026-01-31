"""Tests for swarm.agent_pattern_library."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from swarm.agent_pattern_library import AgentPatternLibrary


@pytest.fixture()
def library(monkeypatch):
    # Ensure deterministic UUIDs
    counter = {"value": 0}

    def fake_uuid4():
        counter["value"] += 1
        return SimpleNamespace(hex=f"pattern{counter['value']:02d}")

    monkeypatch.setattr("swarm.agent_pattern_library.uuid.uuid4", fake_uuid4)
    return AgentPatternLibrary()


def test_register_pattern_creates_entry(library):
    pattern = library.register_pattern(
        name="Latency Hunter",
        archetype="scout",
        description="Low-latency arbitrage",
        strengths=["speed"],
        weaknesses=["complexity"],
        telemetry_signatures={"latency_ms": 90},
        success_metrics={"sharpe_ratio": 1.8},
        tags=["latency"],
    )

    assert pattern.pattern_id == "pattern01"
    assert library.get_pattern(pattern.pattern_id) is pattern


def test_list_patterns_filters_and_orders(library):
    first = library.register_pattern(
        name="Pattern A",
        archetype="explorer",
        description="",
        strengths=[],
        weaknesses=[],
        tags=["latency"],
    )
    second = library.register_pattern(
        name="Pattern B",
        archetype="explorer",
        description="",
        strengths=[],
        weaknesses=[],
        tags=["latency", "risk"],
    )
    # Force timestamps so second appears first
    second.created_at = datetime.utcnow()
    first.created_at = second.created_at - timedelta(days=1)

    results = library.list_patterns(tag="latency", archetype="explorer")
    assert [p.pattern_id for p in results] == [second.pattern_id, first.pattern_id]


def test_suggest_patterns_applies_thresholds(library):
    p1 = library.register_pattern(
        name="Pattern Sharpe High",
        archetype="alpha",
        description="",
        strengths=[],
        weaknesses=[],
        success_metrics={"sharpe_ratio": 2.0},
        telemetry_signatures={"stability": 0.95},
        tags=["stability"],
    )
    p2 = library.register_pattern(
        name="Pattern Telemetry",
        archetype="alpha",
        description="",
        strengths=[],
        weaknesses=[],
        success_metrics={"sharpe_ratio": 1.2},
        telemetry_signatures={"stability": 0.5},
        tags=["stability"],
    )

    suggestions = library.suggest_patterns("stability", min_sharpe=1.5, telemetry_window=("stability", 0.9))
    assert [p.pattern_id for p in suggestions] == [p1.pattern_id]


def test_get_playbook_groups_archetypes(library):
    pattern = library.register_pattern(
        name="Pattern",
        archetype="support",
        description="",
        strengths=["clarity"],
        weaknesses=["speed"],
        success_metrics={"sharpe_ratio": 1.5},
        tags=["support"],
    )

    playbook = library.get_playbook()
    assert "support" in playbook
    record = playbook["support"][0]
    assert record["pattern_id"] == pattern.pattern_id
    assert record["strengths"] == ["clarity"]


def test_record_outcome_updates_metrics_and_notes(library):
    pattern = library.register_pattern(
        name="Pattern",
        archetype="support",
        description="",
        strengths=[],
        weaknesses=[],
        success_metrics={"sharpe_ratio": 1.0},
        tags=["support"],
    )

    library.record_outcome(pattern.pattern_id, {"sharpe_ratio": 0.2}, notes="Great run")

    updated = library.get_pattern(pattern.pattern_id)
    assert updated.success_metrics["sharpe_ratio"] == pytest.approx(1.2)
    assert "Great run" in updated.governance_notes


def test_record_outcome_missing_pattern_raises(library):
    with pytest.raises(KeyError):
        library.record_outcome("missing", {"metric": 1.0})
