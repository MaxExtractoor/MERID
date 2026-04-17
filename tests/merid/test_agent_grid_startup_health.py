"""AgentGrid startup_health / deferred-skip helpers."""

from __future__ import annotations

from merid.prediction import agent_grid as ag_mod
from merid.prediction.agent_grid import (
    clear_agent_grid_deferred_skip,
    note_agent_grid_deferred_skipped,
)


def test_startup_health_not_started() -> None:
    clear_agent_grid_deferred_skip()
    # Fresh singleton from test isolation may still exist — health shape only
    g = ag_mod.get_agent_grid()
    h = g.startup_health()
    assert "phase" in h
    assert "started" in h
    assert h["agents_enabled"] >= 0


def test_deferred_skip_reason_surfaces_in_health() -> None:
    note_agent_grid_deferred_skipped("test_skip")
    g = ag_mod.get_agent_grid()
    assert g.startup_health()["deferred_start_skipped_reason"] == "test_skip"
    clear_agent_grid_deferred_skip()
    assert g.startup_health()["deferred_start_skipped_reason"] is None
