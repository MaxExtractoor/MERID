"""Tests for core.optimization_engine high-risk behaviors."""

from __future__ import annotations

from typing import List

import pytest

import core.optimization_engine as optimization_module


class _SocialEngineStub:
    def __init__(self, exposures: List[dict]):
        self._status = {
            "kill_switch_active": False,
            "social_drawdown": 0.05,
            "total_social_exposure": 15_000,
        }
        self._exposures = exposures

    def get_social_risk_status(self):
        return self._status

    def get_top_asset_exposure(self, limit: int = 5):
        return self._exposures[:limit]


@pytest.fixture
def feasible_social_engine(monkeypatch):
    exposures = [
        {"asset": "BTC", "weight": 0.4},
        {"asset": "ETH", "weight": 0.35},
        {"asset": "SOL", "weight": 0.25},
    ]
    stub = _SocialEngineStub(exposures)
    monkeypatch.setattr(
        optimization_module,
        "get_social_aware_quant_engine",
        lambda: stub,
    )
    return stub


@pytest.mark.asyncio
async def test_strategies_produce_feasible_portfolios(feasible_social_engine):
    engine = optimization_module.OptimizationEngine()

    risk_report = await engine._enhance_risk_management()

    weights = [asset["weight"] for asset in risk_report["enhancements"]]
    assert sum(weights) == pytest.approx(1.0)
    assert all(weight <= 0.5 for weight in weights)
    assert risk_report["status"] == "completed"


def test_constraint_violations_raise_descriptive_errors():
    enhancer = optimization_module.RiskManagementEnhancer()
    metrics = {
        "position_size": 0.3,
        "drawdown": 0.25,
        "volatility": 0.5,
        "correlation": 0.9,
    }

    report = enhancer.analyze_risk_exposure("core_trading", metrics)

    assert report["overall_status"] == "CRITICAL"
    assert any(v["severity"] in {"HIGH", "CRITICAL"} for v in report["violations"])
    assert all("metric" in v for v in report["violations"])


@pytest.mark.asyncio
async def test_fallback_when_external_providers_unavailable(monkeypatch):
    class EmptySocialEngine:
        def get_social_risk_status(self):
            return {"social_drawdown": 0.0, "kill_switch_active": False}

        def get_top_asset_exposure(self, limit: int = 5):
            return []

    monkeypatch.setattr(
        optimization_module,
        "get_social_aware_quant_engine",
        lambda: EmptySocialEngine(),
    )

    engine = optimization_module.OptimizationEngine()

    risk_report = await engine._enhance_risk_management()

    assert risk_report["risk_controls_added"] == 0
    assert risk_report["enhancements"] == []
    assert risk_report["status"] == "completed"
