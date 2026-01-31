"""High-risk tests for core.social_strategy_router."""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Dict, List

import pytest

import core.social_strategy_router as router_module
from core.social_strategy_router import evaluate_social_trade, release_social_position
from core.strategy_versioning import StrategyVersion, VersionStatus


class FakeRegistry:
    def __init__(self, strategy: StrategyVersion) -> None:
        self._strategy = strategy

    def get_active_version(self, strategy_id: str) -> StrategyVersion:
        return self._strategy

    def get_version(self, strategy_id: str, version: str) -> StrategyVersion:
        return self._strategy


class FakeSocialEngine:
    def __init__(self, default_size: float = 5_000.0) -> None:
        self._exposure: Dict[str, float] = {}
        self._default_size = default_size
        self.last_request = None

    def evaluate_trade_request(self, asset, portfolio_value, sentiment_score, market_metrics=None):
        self.last_request = {
            "asset": asset,
            "portfolio_value": portfolio_value,
            "sentiment_score": sentiment_score,
        }
        return {
            "allowed": True,
            "size_usd": self._default_size,
            "reason": None,
            "constraints": {
                "asset_exposure": self._exposure.get(asset, 0.0),
            },
            "confirmation": {"confirmation_score": 0.95},
        }

    def register_position_allocation(self, asset: str, size_usd: float) -> None:
        self._exposure[asset] = self._exposure.get(asset, 0.0) + size_usd

    def release_position_allocation(self, asset: str, size_usd: float) -> None:
        self._exposure[asset] = max(0.0, self._exposure.get(asset, 0.0) - size_usd)

    def exposure_for(self, asset: str) -> float:
        return self._exposure.get(asset, 0.0)

    def reset_state(self) -> None:
        self._exposure.clear()


class FakeRiskControls:
    def __init__(self) -> None:
        self.block_reason: str | None = None
        self.override_active = False
        self.audit_log: List[str] = []
        self.recorded_trades: List[Dict[str, float]] = []

    def validate_social_constraints(self, strategy: StrategyVersion, sizing_result: Dict[str, float]):
        if self.override_active:
            self.audit_log.append(f"override_granted:{strategy.strategy_id}")
            return True, []
        if self.block_reason:
            return False, [self.block_reason]
        return True, []

    def register_social_trade(self, agent_id: str, strategy_id: str, asset: str, size_usd: float, metadata: Dict[str, float]):
        self.recorded_trades.append({"agent_id": agent_id, "asset": asset, "size_usd": size_usd})

    def apply_override(self, note: str) -> None:
        self.override_active = True
        self.block_reason = None
        self.audit_log.append(f"governance_override:{note}")


@pytest.fixture
def strategy() -> StrategyVersion:
    return SimpleNamespace(
        strategy_id="social_router_test",
        version="1.0.0",
        status=VersionStatus.PRODUCTION,
        is_social_strategy=True,
        social_assets=["BTC", "SOL"],
    )


@pytest.fixture
def stubs(monkeypatch, strategy):
    social_engine = FakeSocialEngine()
    risk_controls = FakeRiskControls()
    registry = FakeRegistry(strategy)

    monkeypatch.setattr(
        router_module,
        "get_social_aware_quant_engine",
        lambda: social_engine,
    )
    monkeypatch.setattr(
        router_module,
        "get_multi_agent_risk_controls",
        lambda: risk_controls,
    )
    monkeypatch.setattr(
        router_module,
        "get_version_registry",
        lambda: registry,
    )

    return social_engine, risk_controls


def test_risk_validation_blocks_over_exposed_trade(stubs):
    social_engine, risk_controls = stubs
    risk_controls.block_reason = "overexposure: BTC > cap"

    result = evaluate_social_trade(
        strategy_id="social_router_test",
        asset="BTC",
        portfolio_value=100_000.0,
        sentiment_score=0.8,
    )

    assert result["allowed"] is False
    assert any("overexposure" in reason for reason in result["reasons"])
    assert social_engine.exposure_for("BTC") == 0.0
    assert risk_controls.recorded_trades == []


def test_release_path_updates_exposure(stubs):
    social_engine, risk_controls = stubs

    first = evaluate_social_trade(
        strategy_id="social_router_test",
        asset="SOL",
        portfolio_value=200_000.0,
        sentiment_score=0.9,
    )

    assert first["allowed"] is True
    assert social_engine.exposure_for("SOL") == pytest.approx(5_000.0)

    release_social_position("SOL", 2_000.0)

    assert social_engine.exposure_for("SOL") == pytest.approx(3_000.0)
    assert risk_controls.recorded_trades[0]["asset"] == "SOL"


def test_governance_override_allows_blocked_trade(stubs):
    social_engine, risk_controls = stubs
    risk_controls.block_reason = "cap exceeded"

    initial = evaluate_social_trade(
        strategy_id="social_router_test",
        asset="BTC",
        portfolio_value=150_000.0,
        sentiment_score=0.75,
    )

    assert initial["allowed"] is False

    risk_controls.apply_override("override_ticket_42")

    approved = evaluate_social_trade(
        strategy_id="social_router_test",
        asset="BTC",
        portfolio_value=150_000.0,
        sentiment_score=0.75,
    )

    assert approved["allowed"] is True
    assert social_engine.exposure_for("BTC") == pytest.approx(5_000.0)
    assert any("governance_override" in entry for entry in risk_controls.audit_log)
    assert any("override_granted" in entry for entry in risk_controls.audit_log)
