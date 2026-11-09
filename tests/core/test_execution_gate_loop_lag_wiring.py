"""Regression: execution gate must not couple to loop-lag diagnostics (gate ≠ lag monitor)."""

from __future__ import annotations

import ast
import inspect

import pytest

pytestmark = [
    pytest.mark.kalshi_live_ready,
    pytest.mark.p0_live_blocker,
]


def test_execution_gate_does_not_import_loop_lag_monitor():
    import core.execution_gate as mod

    src = inspect.getsource(mod.check_execution_gate)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
            assert not names & {"lag_health", "get_loop_lag_monitor", "get_loop_lag_thresholds_ms"}
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "BlockReason":
                sources = [kw.value for kw in node.keywords if kw.arg == "source"]
                assert all(
                    isinstance(source, ast.Constant)
                    and source.value not in {"loop_lag", "event_loop_lag"}
                    for source in sources
                )
    assert "get_loop_lag_thresholds_ms" not in src
    assert "merid.infra.loop_lag_monitor" not in src
