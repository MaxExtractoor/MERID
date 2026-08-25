"""Test fills-ledger BROKEN status blocks execution gate (CRIT-3 fix)."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import os


def _make_ledger(status: str):
    ledger = MagicMock()
    ledger.get_reconciliation_status.return_value = {
        "status": status,
        "last_run": "2026-04-09T00:00:00",
        "divergences": [],
    }
    return ledger


def _run_gate(ledger_mock, *, live: bool):
    """Run check_execution_gate with minimal mocking — only fills_ledger and mode vary."""
    with patch("merid.event_venues.kalshi.fills_ledger.get_fills_ledger", return_value=ledger_mock):
        with patch("merid.risk.kill_switches.risk_controller") as mock_rc:
            mock_rc.can_trade.return_value = True
            mock_rc.get_status.return_value = {"can_trade": True, "kill_reason": None}
            mock_rc._global_kill = False
            mock_rc._kill_details = None
            mock_rc._kill_reason = None
            with patch("merid.reconciliation.has_critical_discrepancies", return_value=False):
                with patch(
                    "core.execution_gate.check_price_feed_staleness",
                    return_value={"safe_to_trade": True, "stale_symbols": [], "critical_count": 0},
                ):
                    # Patch _is_kalshi_demo_mode directly so we control demo vs live
                    with patch(
                        "core.execution_gate._is_kalshi_demo_mode",
                        return_value=(not live),
                    ):
                        with patch(
                            "core.dependency_health.check_all_dependencies",
                            return_value={
                                "dependencies": [],
                                "any_critical_down": False,
                                "degraded_count": 0,
                                "down_count": 0,
                                "total": 0,
                                "healthy_count": 0,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            },
                        ):
                            from core.execution_gate import check_execution_gate
                            return check_execution_gate()


def test_fills_ledger_broken_blocks_in_live_mode():
    """BROKEN fills reconciliation must produce a critical reason and BLOCKED gate in live mode."""
    status = _run_gate(_make_ledger("broken"), live=True)
    sources = [r.source for r in status.reasons]
    assert "fills_ledger_reconciliation" in sources, f"Reason not in {sources}"
    fl = next(r for r in status.reasons if r.source == "fills_ledger_reconciliation")
    assert fl.severity == "critical"
    assert status.gate_state == "blocked"


def test_fills_ledger_broken_warning_only_in_demo():
    """BROKEN fills reconciliation must only be a warning in demo mode."""
    status = _run_gate(_make_ledger("broken"), live=False)
    fl = next((r for r in status.reasons if r.source == "fills_ledger_reconciliation"), None)
    assert fl is not None, "Expected fills_ledger_reconciliation reason in demo"
    assert fl.severity == "warning"


def test_fills_ledger_degraded_is_warning_in_live():
    """DEGRADED fills reconciliation must be a warning (not critical) in live mode."""
    status = _run_gate(_make_ledger("degraded"), live=True)
    fl = next((r for r in status.reasons if r.source == "fills_ledger_reconciliation"), None)
    assert fl is not None, "Expected fills_ledger_reconciliation reason"
    assert fl.severity == "warning"
    assert status.gate_state in ("limited", "clear")


def test_fills_ledger_ok_produces_no_reason():
    """OK reconciliation status must produce no fills_ledger_reconciliation reason."""
    status = _run_gate(_make_ledger("ok"), live=True)
    fl = next((r for r in status.reasons if r.source == "fills_ledger_reconciliation"), None)
    assert fl is None, f"Unexpected reason when status=ok: {fl}"
