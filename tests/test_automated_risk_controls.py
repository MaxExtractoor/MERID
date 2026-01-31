"""Tests for `core.automated_risk_controls` high-risk behaviors."""

from __future__ import annotations

import pytest

from core.automated_risk_controls import PortfolioRiskManager, PositionRisk


pytestmark = pytest.mark.safety_critical


@pytest.fixture
def risk_manager(monkeypatch):
    """Create a risk manager with deterministic portfolio state and a stubbed social engine."""

    manager = PortfolioRiskManager(
        max_portfolio_risk=0.15,
        max_position_size=0.10,
        max_leverage=2.0,
        max_correlation=0.7,
    )
    manager.portfolio_value = 100_000
    manager.total_exposure = 90_000  # current leverage = 0.9x

    class DummySocialEngine:
        def __init__(self):
            self.constraints = {
                "kill_switch_active": False,
                "kill_switch_reason": None,
                "data_fresh": True,
            }

        def is_social_asset(self, symbol: str) -> bool:  # pragma: no cover - deterministic branch
            return symbol.startswith("SOCIAL")

        def get_position_constraints(self, symbol: str):
            return self.constraints

    dummy_engine = DummySocialEngine()
    monkeypatch.setattr(
        "core.automated_risk_controls.get_social_aware_quant_engine",
        lambda: dummy_engine,
    )

    return manager, dummy_engine


@pytest.mark.asyncio
async def test_leverage_cap_enforced(risk_manager):
    manager, _ = risk_manager

    # New order would push leverage beyond the configured 2.0x cap
    result = await manager.check_position_allowed(
        symbol="BTC",
        position_size=5.0,
        price=25_000.0,
    )

    assert result["allowed"] is False
    assert any(v["type"] == "leverage" for v in result["violations"])


@pytest.mark.asyncio
async def test_kill_switch_freezes_orders(risk_manager):
    manager, social_engine = risk_manager
    social_engine.constraints.update(
        {
            "kill_switch_active": True,
            "kill_switch_reason": "governance halt",
        }
    )

    result = await manager.check_position_allowed(
        symbol="SOCIAL_X",
        position_size=0.5,
        price=1.0,
        strategy_id="social-alpha",
    )

    assert result["allowed"] is False
    violation_types = [v["type"] for v in result["violations"]]
    assert "social_kill_switch" in violation_types
    assert any("governance halt" in v.get("reason", "") for v in result["violations"])


@pytest.mark.asyncio
async def test_exposure_resets_after_close():
    manager = PortfolioRiskManager(
        max_portfolio_risk=0.20,
        max_position_size=0.15,
        max_leverage=3.0,
    )
    manager.portfolio_value = 50_000

    position = PositionRisk(
        symbol="ETH",
        position_size=10,
        entry_price=2_000,
        current_price=2_100,
        unrealized_pnl=1_000,
        unrealized_pnl_pct=0.05,
    )

    manager.add_position(position)
    add_exposure = manager.total_exposure
    assert add_exposure > 0

    manager.remove_position("ETH")
    assert manager.total_exposure == 0
    assert manager.positions == {}


@pytest.mark.asyncio
async def test_leverage_ladder_triggers_risk_limit_breach(risk_manager):
    manager, _ = risk_manager
    manager.portfolio_value = 100_000

    # Seed an existing position that already places the book near the leverage cap
    high_leverage = PositionRisk(
        symbol="LADDER",
        position_size=21,  # 21 * 10k = 210k exposure => 2.1x leverage
        entry_price=10_000,
        current_price=10_000,
        unrealized_pnl=0.0,
        unrealized_pnl_pct=0.0,
    )
    manager.add_position(high_leverage)
    assert manager.current_leverage == pytest.approx(2.1)

    # Additional order would push leverage even higher and must be blocked
    result = await manager.check_position_allowed(
        symbol="BTC",
        position_size=1.0,
        price=5_000.0,
    )

    assert result["allowed"] is False
    assert any(v["type"] == "leverage" for v in result["violations"])

    # Risk report should record the breach and increment the leverage risk limit counters
    report = manager.get_portfolio_risk_report()
    leverage_limit = next(limit for limit in report["risk_limits"] if limit["limit_type"] == "leverage_limit")
    assert leverage_limit["breached"] is True
    assert leverage_limit["current_value"] == pytest.approx(manager.current_leverage)
    assert leverage_limit["breach_count"] >= 1
