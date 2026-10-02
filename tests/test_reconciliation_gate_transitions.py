"""Minimal reconciliation → execution_gate transition tests.

Isolates Kalshi venue reconciliation (§2b in ``check_execution_gate``) by mocking
other gate inputs so we can assert state changes when reconciliation results change.

See: ``MERID_KALSHI_CT_AUDIT.md`` §5, prompt follow-up for gate transition coverage.

**Note:** Patching ``trading.reconciliation`` by import path triggers ``trading``'s
lazy loader and a circular import in this repo. We stub ``sys.modules['trading.reconciliation']``
instead so ``check_execution_gate``'s in-function import resolves to a lightweight fake.
"""

from __future__ import annotations

import sys
import types
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

# Submodules are lazy — import them so patch("merid.<pkg>.<mod>....") resolves.
import merid.diagnostics.loop_lag  # noqa: F401

from core.execution_gate import GateState, check_execution_gate


class _MockRisk:
    _global_kill = False
    _kill_details = None
    _kill_reason = None


def _install_legacy_reconciliation_stub() -> Optional[types.ModuleType]:
    """Return previous module (if any) for restoration."""
    stub = types.ModuleType("trading.reconciliation")

    def _no_crit() -> bool:
        return False

    stub.has_critical_discrepancies = _no_crit
    stub.get_last_report = lambda: None
    stub._has_ever_completed = True

    old = sys.modules.get("trading.reconciliation")
    sys.modules["trading.reconciliation"] = stub
    return old


@pytest.fixture
def isolated_gate_env():
    """Patches kill switch, feeds, pnl, deps, news, loop lag; stubs legacy paper recon.

    Kalshi venue reconciliation (``merid.reconciliation.*``) is NOT patched here —
    tests pass explicit patch values for those.
    """
    old_tr = _install_legacy_reconciliation_stub()
    mock_monitor = MagicMock()
    mock_monitor.get_health.return_value = {
        "stats": {"current_ms": 5.0, "p95_ms": 8.0},
        "healthy": True,
        "elevated": False,
        "degraded": False,
        "critical": False,
    }

    try:
        with patch("core.execution_gate._is_kalshi_demo_mode", return_value=False), patch(
            "merid.risk.kill_switches.risk_controller",
            _MockRisk(),
        ), patch(
            "core.execution_gate.check_price_feed_staleness",
            return_value={
                "safe_to_trade": True,
                "stale_symbols": [],
                "critical_count": 0,
            },
        ), patch(
            "core.execution_gate.check_pnl_consistency",
            return_value={"consistent": True, "max_divergence_usd": 0.0, "threshold_usd": 5.0},
        ), patch(
            "core.dependency_health.check_all_dependencies",
            return_value={
                "any_critical_down": False,
                "degraded_count": 0,
                "dependencies": [],
                "down_count": 0,
                "total": 0,
            },
        ), patch(
            "merid.diagnostics.loop_lag.get_loop_lag_monitor",
            return_value=mock_monitor,
        ), patch(
            "merid.diagnostics.loop_lag.get_loop_lag_thresholds_ms",
            return_value={"degrade_ms": 500.0, "halt_ms": 2000.0},
        ):
            yield
    finally:
        if old_tr is not None:
            sys.modules["trading.reconciliation"] = old_tr
        else:
            sys.modules.pop("trading.reconciliation", None)







def test_genuine_mismatch_blocks_in_live_mode(isolated_gate_env):
    """Critical qty mismatch → blocked (critical severity) when not demo."""

    class _D:
        severity = "critical"
        merid_qty = 0.0
        venue_qty = 3.0
        message = ""

    d = _D()

    from core import execution_gate as eg

    eg.reset_lag_halt_counter()

    with patch(
        "merid.reconciliation.has_critical_discrepancies",
        return_value=True,
    ), patch(
        "merid.reconciliation.get_last_discrepancies",
        return_value=[d],
    ):
        s = check_execution_gate()

    assert s.blocked is True
    assert s.gate_state == GateState.BLOCKED.value
    assert s.safe_to_trade is False
    crit = [r for r in s.reasons if r.source == "reconciliation" and r.severity == "critical"]
    assert crit, "expected critical Kalshi reconciliation reason"
    assert "discrepancies" in crit[0].message.lower() or "mismatch" in crit[0].details.lower()