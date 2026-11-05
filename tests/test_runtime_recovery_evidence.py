"""Regression tests: feed/book recovery must use verified evidence and
preserve the original halt reason when evidence is incomplete.

Pre-2026-11-05, feed recovery called ``complete_preflight(auto_enable=True)``
from RECOVERY_RUNNING — designed to refuse — which landed the machine in
LIVE_ENTRIES_HALTED with RECOVERY_VERIFICATION_REQUIRED, overwriting the
recoverable reason codes so no retry path could ever match again.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from merid.observability.live_runtime_state import (
    LiveRuntimeState,
    runtime_recovery_evidence_missing,
)


@pytest.fixture
def state(tmp_path: Path) -> LiveRuntimeState:
    path = tmp_path / "live_runtime_state.json"
    return LiveRuntimeState(persistence_path=path)


def _full_evidence(**overrides):
    ev = {
        "resolved_failure": True,
        "fresh_reconciliation": True,
        "reconciliation_snapshot_id": "recon_test",
        "fill_watermark": "2026-11-05T15:00:00+00:00",
        "no_critical_discrepancy": True,
        "exits_available": True,
        "router_available": True,
        "production_live": True,
    }
    ev.update(overrides)
    return ev


def _halted(state: LiveRuntimeState) -> None:
    # Drive to a real halt: ENABLED -> HALTED.
    state.transition("PREFLIGHT_RUNNING", "test_boot", ["TEST"])
    state.complete_preflight(auto_enable=True, preflight_context={})
    assert state.state == "LIVE_ENTRIES_ENABLED"
    state.halt_entries("ws_io_thread_exited", ["WS_DATA_PLANE_DEAD", "STALE_MARKET_DATA"])
    assert state.state == "LIVE_ENTRIES_HALTED"


def test_recovery_refusal_then_bounceback_preserves_codes(state: LiveRuntimeState):
    _halted(state)
    orig_codes = list(state._reason_codes)
    orig_reason = state._reason
    state.transition("RECOVERY_RUNNING", "ws_data_plane_recovered", ["WS_RECOVERED"])
    # Refused: watermark missing.
    ok = state.complete_runtime_recovery(
        "ws_data_plane_recovered",
        _full_evidence(fill_watermark=None),
    )
    assert not ok
    assert state.state == "RECOVERY_RUNNING"
    # RECOVERY_RUNNING -> HALTED must be legal so callers can restore the
    # original recoverable reason codes.
    state.transition("LIVE_ENTRIES_HALTED", orig_reason, orig_codes)
    assert state.state == "LIVE_ENTRIES_HALTED"
    assert set(state._reason_codes) == {"WS_DATA_PLANE_DEAD", "STALE_MARKET_DATA"}


def test_recovery_with_complete_evidence_enables(state: LiveRuntimeState):
    _halted(state)
    state.transition("RECOVERY_RUNNING", "ws_data_plane_recovered", ["WS_RECOVERED"])
    ok = state.complete_runtime_recovery(
        "ws_data_plane_recovered", _full_evidence()
    )
    assert ok
    assert state.state == "LIVE_ENTRIES_ENABLED"
    assert state.can_submit_live_entry()


def test_evidence_missing_mirrors_recovery_gate(state: LiveRuntimeState):
    _halted(state)
    ev = _full_evidence(fill_watermark=None, router_available=False)
    missing = runtime_recovery_evidence_missing(ev)
    assert "router_available" in missing
    assert "fill_watermark_missing" in missing
    assert "resolved_failure" not in missing
    # The prescreen must agree with the gate itself.
    state.transition("RECOVERY_RUNNING", "test", ["TEST"])
    assert not state.complete_runtime_recovery("test", ev)


def test_preflight_still_refuses_auto_enable_from_recovery(state: LiveRuntimeState):
    """The designed refusal stays: feed-only preflight cannot self-enable."""
    _halted(state)
    state.transition("RECOVERY_RUNNING", "test", ["TEST"])
    state.complete_preflight(auto_enable=True, preflight_context={})
    assert state.state == "LIVE_ENTRIES_HALTED"
    assert "RECOVERY_VERIFICATION_REQUIRED" in state._reason_codes
