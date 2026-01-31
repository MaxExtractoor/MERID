"""Tests for swarm.spawner population control."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from swarm import spawner as spawner_mod


@dataclass
class DummyAgent:
    agent_id: str
    model_name: str = "gpt"
    trust: float = 1.0
    tool_budget: int = 2


class DummyLedger:
    def __init__(self) -> None:
        self.leaderboard_rows = []
        self.parent_row = None

    def leaderboard(self, limit: int = 20):  # noqa: D401
        return list(self.leaderboard_rows[:limit])

    def best_parent(self, min_score: float, min_votes: int):
        return self.parent_row


def _make_spawner(active_ids, *, ledger=None, **kwargs):
    ledger = ledger or DummyLedger()
    spawn = spawner_mod.SwarmSpawner(ledger, **kwargs)
    spawn.bootstrap([DummyAgent(agent_id=i) for i in active_ids])
    return spawn, ledger


def test_bootstrap_populates_lineage_and_counters():
    spawn, _ = _make_spawner(["agent#a", "agent#b"])

    active = spawn.get_active_agents()
    assert {agent.agent_id for agent in active} == {"agent#a", "agent#b"}

    lineage = spawn.lineage()
    assert len(lineage) == 2
    assert all(record.generation == 0 for record in lineage)
    assert spawn.get_replication_count() == 0
    assert spawn.get_termination_count() == 0


def test_refresh_retire_underperformers_and_spawn_child(monkeypatch):
    spawn, ledger = _make_spawner(["parent#001", "keep#001"], max_population=3)
    ledger.leaderboard_rows = [
        {"agent_id": "parent#001", "votes": 10, "score": 0.9},
        {"agent_id": "keep#001", "votes": 10, "score": 0.8},
    ]
    ledger.parent_row = {"agent_id": "parent#001", "score": 0.9, "votes": 10}

    child = DummyAgent(agent_id="child#tmp")

    def fake_spawn(parent):
        return DummyAgent(agent_id=f"{parent.agent_id}#child")

    monkeypatch.setattr(spawner_mod.SwarmSpawner, "_spawn_child", lambda self, parent: fake_spawn(parent))

    new_population = spawn.refresh_population()

    assert any(agent.agent_id.endswith("#child") for agent in new_population)
    assert len(new_population) == 3


def test_refresh_retains_bootstrap_generation_without_votes():
    spawn, ledger = _make_spawner(["bootstrap#001", "bootstrap#002"], min_votes_to_spawn=5)
    ledger.leaderboard_rows = [
        {"agent_id": "bootstrap#001", "votes": 2, "score": 0.1},
        {"agent_id": "bootstrap#002", "votes": 2, "score": 0.1},
    ]

    refreshed = spawn.refresh_population()
    assert {agent.agent_id for agent in refreshed} == {"bootstrap#001", "bootstrap#002"}


def test_lineage_updates_for_spawned_children(monkeypatch):
    spawn, ledger = _make_spawner(["parent#base"], max_population=2)
    ledger.leaderboard_rows = [{"agent_id": "parent#base", "votes": 10, "score": 0.95}]
    ledger.parent_row = {"agent_id": "parent#base", "score": 0.95, "votes": 10}

    def make_child(parent):
        child = DummyAgent(agent_id=f"{parent.agent_id}#child")
        spawn._lineage[child.agent_id] = spawner_mod.LineageRecord(
            agent_id=child.agent_id,
            parent_id=parent.agent_id,
            generation=1,
            created_at="now",
        )
        return child

    monkeypatch.setattr(spawner_mod.SwarmSpawner, "_spawn_child", lambda self, parent: make_child(parent))

    spawn.refresh_population()

    lineage = {record.agent_id: record for record in spawn.lineage()}
    assert "parent#base#child" in lineage
    assert lineage["parent#base#child"].parent_id == "parent#base"
    assert lineage["parent#base#child"].generation == 1


def test_spawn_child_inherits_state_and_mutates_budget(monkeypatch):
    spawn, _ = _make_spawner(["parent#001"], max_population=1)
    parent = spawn.get_active_agents()[0]
    parent.trust = 0.42
    parent.tool_budget = 3

    monkeypatch.setattr(spawner_mod, "current_time", lambda: {"utc_iso": "2026-01-18T00:00:00Z"})
    monkeypatch.setattr(spawner_mod.random, "choice", lambda seq: 1)

    child = spawn._spawn_child(parent)

    assert child.agent_id.startswith("parent#")
    assert child.trust == pytest.approx(0.42)
    assert child.tool_budget == 3

    lineage = {record.agent_id: record for record in spawn.lineage()}
    assert lineage[child.agent_id].parent_id == parent.agent_id
    assert lineage[child.agent_id].generation == 1


def test_refresh_retires_underperforming_descendants(monkeypatch):
    spawn, ledger = _make_spawner(["root#001", "root#002"], min_votes_to_spawn=2)
    child = DummyAgent(agent_id="root#001#child")
    spawn._active_agents.append(child)
    spawn._lineage[child.agent_id] = spawner_mod.LineageRecord(
        agent_id=child.agent_id,
        parent_id="root#001",
        generation=1,
        created_at="2026-01-18T00:00:00Z",
    )

    ledger.leaderboard_rows = [
        {"agent_id": child.agent_id, "votes": 5, "score": 0.1},
        {"agent_id": "root#002", "votes": 5, "score": 0.9},
    ]

    refreshed = spawn.refresh_population()
    assert child.agent_id not in {agent.agent_id for agent in refreshed}
    assert "root#002" in {agent.agent_id for agent in refreshed}
