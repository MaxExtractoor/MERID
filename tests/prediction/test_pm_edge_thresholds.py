"""PM strategy thresholds: edge gates, profile merge, execution-gate helper parity."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from merid.prediction.model import ContractState, EdgeEstimate, ImpliedProbability, MarketSnapshot
from merid.prediction.strategy import KalshiStrategy, SignalAction, StrategyConfig


def _base_snapshot(
    market_id: str = "KXBTC15M-26APR071200-00",
    *,
    net_edge: Decimal = Decimal("0.01"),
    hours_to_expiry: Decimal = Decimal("10"),
) -> MarketSnapshot:
    """Minimal fresh snapshot in MID phase (~10h left)."""
    now = datetime.now(timezone.utc)
    impl = ImpliedProbability(
        yes_prob=Decimal("0.5"),
        no_prob=Decimal("0.5"),
    )
    edge = EdgeEstimate(
        market_id=market_id,
        side="yes",
        action="buy",
        market_prob=Decimal("0.45"),
        model_prob=Decimal("0.55"),
        raw_edge=Decimal("0.10"),
        fee_drag=Decimal("0.01"),
        slippage_est=Decimal("0.01"),
        net_edge=net_edge,
        edge_type="speculative",
        confidence=Decimal("0.9"),
        timestamp=now,
    )
    return MarketSnapshot(
        market_id=market_id,
        event_id="E1",
        title="t",
        state=ContractState.TRADING,
        implied=impl,
        volume=Decimal("10000"),
        open_interest=Decimal("5000"),
        time_to_expiry_hours=hours_to_expiry,
        edges=[edge],
        timestamp=now,
    )


def test_directional_edge_below_mid_threshold_no_action_with_eval_context():
    cfg = StrategyConfig(
        min_edge_early=Decimal("0.01"),
        min_edge_mid=Decimal("0.50"),
        min_edge_late=Decimal("0.01"),
        min_edge_terminal=Decimal("0.01"),
        min_confidence=Decimal("0.1"),
    )
    strat = KalshiStrategy(config=cfg, agent_name="t")
    snap = _base_snapshot(net_edge=Decimal("0.05"))
    sig = strat.evaluate(snap, archetype="directional", correlation_id="c-test-1")
    assert sig.action == SignalAction.NO_ACTION
    assert "threshold" in (sig.reason or "").lower()
    assert sig.eval_context.get("block") == "edge_below_threshold"
    assert "min_edge_threshold" in sig.eval_context


def test_crypto_low_edge_profile_merges(monkeypatch):
    from merid.prediction import pm_profiles

    pm_profiles._profiles_cache = None
    monkeypatch.setenv("MERID_PM_PROFILE", "crypto_low_edge_dev")
    overrides = pm_profiles.get_pm_profile_strategy_overrides("crypto_low_edge_dev")
    assert overrides.get("min_edge_terminal") == 0.005
    sc = StrategyConfig()
    pm_profiles.merge_profile_into_strategy_config(sc, "crypto_low_edge_dev")
    assert sc.min_edge_terminal == Decimal("0.005")
    assert sc.max_contracts_per_order == 3


def test_live_execution_blocked_helper():
    from core.execution_gate import ExecutionGateStatus, GateState, live_execution_blocked

    clear = ExecutionGateStatus(blocked=False, safe_to_trade=True, gate_state=GateState.CLEAR.value)
    assert live_execution_blocked(clear) is False

    blocked = ExecutionGateStatus(blocked=True, safe_to_trade=False, gate_state=GateState.BLOCKED.value)
    assert live_execution_blocked(blocked) is True

    integrity_style = ExecutionGateStatus(blocked=False, safe_to_trade=False, gate_state=GateState.LIMITED.value)
    assert live_execution_blocked(integrity_style) is True


def test_normalize_crypto_timeframe_hourly_and_annual():
    from merid.prediction.crypto_edge_production import normalize_crypto_timeframe

    assert normalize_crypto_timeframe("HOURLY") == "1h"
    assert normalize_crypto_timeframe("annual") == "annual"
    assert normalize_crypto_timeframe("Y1") == "annual"


def test_crypto_threshold_matrix_includes_annual(monkeypatch):
    from merid.prediction.crypto_edge_production import get_crypto_thresholds

    monkeypatch.setenv("MERID_CRYPTO_EDGE_PRODUCTION_PROFILE", "modern")
    from merid.prediction.crypto_threshold_matrix import reload_matrix_document

    reload_matrix_document()
    ann = get_crypto_thresholds("BTC", "annual")
    mon = get_crypto_thresholds("BTC", "monthly")
    assert ann.timeframe == "annual"
    assert ann.directional_min_edge == mon.directional_min_edge
    assert ann.pm_risk_max_spread_cents == mon.pm_risk_max_spread_cents
