"""pm_bankroll_snapshot — AgentGrid overlay when CT loop is idle."""

from __future__ import annotations

from unittest.mock import MagicMock


def test_overlay_leaves_ct_running_unchanged(monkeypatch):
    from merid.prediction.pm_bankroll_snapshot import build_agent_grid_bankroll_overlay

    _tc = MagicMock(
        initial_bankroll_cents=1000,
        kelly_fraction=0.25,
        max_risk_per_trade_pct=0.02,
        drawdown_halt_pct=0.2,
        drawdown_reduce_pct=0.1,
    )
    monkeypatch.setattr(
        "merid.trading.kalshi_continuous_trader.TraderConfig.from_env",
        lambda: _tc,
    )
    base = {"running": True, "cycle": 5, "pm_signal_source": "x"}
    out = build_agent_grid_bankroll_overlay(base)
    assert out["running"] is True
    assert out.get("pm_signal_source") == "continuous_trader"


def test_overlay_ag_grid_sets_running_and_merges_cycles(monkeypatch):
    from merid.prediction import pm_bankroll_snapshot as pbs

    _tc = MagicMock(
        initial_bankroll_cents=1000,
        kelly_fraction=0.25,
        max_risk_per_trade_pct=0.02,
        drawdown_halt_pct=0.2,
        drawdown_reduce_pct=0.1,
    )
    monkeypatch.setattr(
        "merid.trading.kalshi_continuous_trader.TraderConfig.from_env",
        lambda: _tc,
    )

    class St:
        def __init__(self, cyc: int, ord_: int) -> None:
            self.cycles_run = cyc
            self.orders_placed = ord_

    class Ag:
        def __init__(self) -> None:
            self.state = St(4, 2)

    class Grid:
        is_running = True
        agents = [Ag(), Ag()]

    monkeypatch.setattr(
        "merid.prediction.agent_grid.get_agent_grid",
        lambda: Grid(),
    )
    monkeypatch.setattr(
        "core.execution_gate.check_execution_gate",
        lambda: MagicMock(to_dict=lambda: {"gate_state": "ok", "blocked": False, "safe_to_trade": True, "reasons": []}),
    )
    _st = MagicMock(
        current_equity_usd=100.0,
        peak_equity_usd=100.0,
        daily_pnl_usd=1.25,
        daily_fees_usd=0.05,
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk",
        lambda: MagicMock(state=_st),
    )

    out = pbs.build_agent_grid_bankroll_overlay(
        {"running": False, "cycle": 0, "orders_placed": 0, "portfolio_cents": 0, "config": {}}
    )
    assert out["running"] is True
    assert out["pm_signal_source"] == "agent_grid"
    assert out["pm_ct_loop_idle"] is True
    assert out["agent_grid_cycles_total"] == 8
    assert out["cycle"] >= 4
    assert out["orders_placed"] >= 4
    assert out.get("pm_bankroll_source") == "kalshi_risk_manager"
    assert out["config"]["initial_bankroll_cents"] == 10000
    assert out["config"].get("pm_reference_bankroll") == "kalshi_risk_manager"
    assert out["total_pnl_cents"] == 125
    assert out["total_fees_cents"] == 5
