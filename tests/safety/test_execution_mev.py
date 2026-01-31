"""Safety-critical tests for MEV defense helpers and flows."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from trading.execution import (
    ExecutionConfig,
    ExecutionEngine,
    ExecutionMode,
    OrderRejectedError,
    OrderSide,
    OrderType,
    _is_abort_action,
    _is_high_threat,
)
from trading.execution.defense import DefenseAction, DefenseRecommendation, ThreatLevel


pytestmark = pytest.mark.safety_critical


@dataclass
class _StubFrontRunningDetector:
    def register_pending_order(self, **_: object) -> None:  # pragma: no cover - no-op side effect
        return None


class _StubMEVDefender:
    def __init__(self, recommendation: DefenseRecommendation) -> None:
        self._recommendation = recommendation
        self.front_running_detector = _StubFrontRunningDetector()

    def get_defense_recommendation(self, **_: object) -> DefenseRecommendation:
        return self._recommendation


def _make_engine_with_stub(recommendation: DefenseRecommendation | None) -> ExecutionEngine:
    engine = ExecutionEngine(config=ExecutionConfig(mode=ExecutionMode.PAPER))
    # Disable optional integrations for hermetic tests
    engine._reality_auditor = None
    engine._validator = None
    engine._mev_defender = _StubMEVDefender(recommendation) if recommendation else None
    return engine


def test_is_abort_action_and_high_threat_classifiers() -> None:
    assert _is_abort_action(DefenseAction.ABORT) is True
    assert _is_abort_action(DefenseAction.PROCEED) is False
    assert _is_high_threat(ThreatLevel.HIGH) is True
    assert _is_high_threat(ThreatLevel.CRITICAL) is True
    assert _is_high_threat(ThreatLevel.MEDIUM) is False


@pytest.mark.asyncio
async def test_mev_enabled_aborts_on_high_threat() -> None:
    recommendation = DefenseRecommendation(
        action=DefenseAction.ABORT,
        reason="critical threat",
        threat_level=ThreatLevel.CRITICAL,
        estimated_mev_risk=10_000.0,
    )
    engine = _make_engine_with_stub(recommendation)
    engine._price_cache["BTC"] = 20_000.0

    with pytest.raises(OrderRejectedError) as exc:
        await engine.submit_order(
            symbol="BTC",
            side=OrderSide.BUY,
            quantity=1.0,
            order_type=OrderType.MARKET,
        )

    assert "MEV defense aborted" in str(exc.value)


@pytest.mark.asyncio
async def test_mev_enabled_allows_non_threat_order() -> None:
    recommendation = DefenseRecommendation(
        action=DefenseAction.PROCEED,
        reason=" benign",
        threat_level=ThreatLevel.LOW,
        estimated_mev_risk=0.0,
    )
    engine = _make_engine_with_stub(recommendation)
    engine._price_cache["ETH"] = 3_000.0

    order = await engine.submit_order(
        symbol="ETH",
        side=OrderSide.SELL,
        quantity=0.5,
        order_type=OrderType.MARKET,
    )

    assert order.metadata["mev_recommendation"]["action"] == DefenseAction.PROCEED.value


@pytest.mark.asyncio
async def test_mev_disabled_skips_defense_flow() -> None:
    engine = _make_engine_with_stub(recommendation=None)
    engine._price_cache["SOL"] = 150.0

    order = await engine.submit_order(
        symbol="SOL",
        side=OrderSide.BUY,
        quantity=2.0,
        order_type=OrderType.MARKET,
    )

    assert "mev_recommendation" not in order.metadata
