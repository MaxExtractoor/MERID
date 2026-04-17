"""PM live readiness env gating."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from merid.pm_live_readiness import compute_pm_live_readiness, is_env_prod_live_pm


@pytest.fixture
def prod_live_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MERID_PM_PROFILE", "production")
    monkeypatch.setenv("MERID_PM_TRADING_MODE", "live")
    monkeypatch.setenv("MERID_PM_LIVE_ENABLED", "true")
    monkeypatch.setenv("MERID_ALLOW_LIVE_TRADES", "true")
    monkeypatch.setenv("MERID_KALSHI_WS_CLIENT", "ws")
    monkeypatch.setenv("MERID_ENABLE_KALSHI_CT", "false")
    monkeypatch.delenv("MERID_VALIDATION_MODE", raising=False)
    monkeypatch.delenv("KALSHI_TRADER_SMOKE_TEST", raising=False)
    monkeypatch.setenv("KALSHI_CONFIRM_LIVE", "1")
    monkeypatch.setenv("KALSHI_ENV", "live")


def test_is_env_prod_live_pm_true(prod_live_env: None) -> None:
    assert is_env_prod_live_pm() is True


def test_is_env_prod_live_pm_false_when_paper(prod_live_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MERID_PM_TRADING_MODE", "paper")
    assert is_env_prod_live_pm() is False


@patch("merid.prediction.venue_gate.VenueGate")
@patch("merid.prediction.agent_grid.get_agent_grid")
@patch("core.execution_gate.check_execution_gate")
@patch("merid.risk.kill_switches.risk_controller")
def test_compute_pm_live_readiness_structure(
    mock_rc: MagicMock,
    mock_gate: MagicMock,
    mock_grid: MagicMock,
    mock_vg_cls: MagicMock,
    prod_live_env: None,
) -> None:
    mock_rc.can_trade.return_value = True
    mock_rc.get_kill_reason.return_value = None
    st = MagicMock()
    st.blocked = False
    st.safe_to_trade = True
    st.gate_state = "clear"
    st.reasons = []
    mock_gate.return_value = st
    mock_grid.return_value.startup_health.return_value = {
        "started": True,
        "phase": "running",
        "last_error": None,
        "deferred_start_skipped_reason": None,
    }
    vg_inst = MagicMock()
    vg_inst.is_live = True
    vg_inst.live_enabled = True
    vg_inst.mode = MagicMock(value="live")
    mock_vg_cls.return_value = vg_inst
    payload = compute_pm_live_readiness()
    assert "ready_for_live_pm_trading" in payload
    assert "checks" in payload
    assert set(payload["checks"].keys()) >= {
        "env_prod_live",
        "agent_grid_started",
        "kill_switch_can_trade",
        "execution_gate_clear",
        "venue_gate_live",
    }
    assert payload["checks"]["env_prod_live"] is True
    assert payload["ready_for_live_pm_trading"] is True
