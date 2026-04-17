"""Regression: execution gate must not couple to loop-lag diagnostics (gate ≠ lag monitor)."""

from __future__ import annotations

import inspect

import pytest

pytestmark = [
    pytest.mark.kalshi_live_ready,
    pytest.mark.p0_live_blocker,
]


def test_execution_gate_does_not_import_loop_lag_monitor():
    import core.execution_gate as mod

    src = inspect.getsource(mod.check_execution_gate)
    assert "from merid.diagnostics.loop_lag import" not in src
    assert "get_loop_lag_monitor" not in src
    assert "get_loop_lag_thresholds_ms" not in src
    assert "merid.infra.loop_lag_monitor" not in src
