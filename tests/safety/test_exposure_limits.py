"""Safety-critical tests for exposure and position guardrails."""

from __future__ import annotations

import pytest

from core.automated_risk_controls import PortfolioRiskManager


pytestmark = pytest.mark.safety_critical


def _make_manager(portfolio_value: float = 100_000.0) -> PortfolioRiskManager:
    manager = PortfolioRiskManager(
        max_portfolio_risk=0.15,
        max_position_size=0.10,
        max_leverage=2.0,
        max_correlation=0.7,
    )
    manager.portfolio_value = portfolio_value
    return manager


@pytest.mark.asyncio
async def test_position_size_limit_blocks_large_trade() -> None:
    manager = _make_manager()
    result = await manager.check_position_allowed(
        symbol="BTC",
        position_size=1.0,
        price=15_000.0,
    )

    assert result["allowed"] is False
    assert any(v["type"] == "position_size" for v in result["violations"])


@pytest.mark.asyncio
async def test_leverage_limit_blocks_when_total_exposure_exceeds_cap() -> None:
    manager = _make_manager()
    manager.total_exposure = 150_000.0  # already near limit

    result = await manager.check_position_allowed(
        symbol="ETH",
        position_size=1.0,
        price=60_000.0,
    )

    assert result["allowed"] is False
    assert any(v["type"] == "leverage" for v in result["violations"])
