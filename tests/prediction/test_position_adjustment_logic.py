from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from merid.event_venues.base import EventOutcome
from merid.prediction.agent_grid_config import (
    AgentConfig,
    AgentRiskLimits,
    EntryWindowConfig,
    MarketFilterConfig,
)
from merid.prediction.model import ContractState, ImpliedProbability, MarketSnapshot
from merid.prediction.strategy import StrategySignal, SignalAction
from merid.prediction.trading_agent import (
    KalshiTradingAgent,
    OpenPosition,
    PositionMemory,
)
from merid.prediction.model import EdgeEstimate


def _agent(name: str = "TEST") -> KalshiTradingAgent:
    cfg = AgentConfig(
        name=name,
        assets=["BTC"],
        timeframes=["15m"],
        market_filter=MarketFilterConfig(),
        risk_limits=AgentRiskLimits(
            max_yes_position=10,
            max_no_position=10,
            max_orders_per_window=10,
            max_notional_usd=Decimal("500"),
        ),
        entry_window=EntryWindowConfig(minutes_before_expiry=10, cutoff_minutes_before_expiry=1),
    )
    return KalshiTradingAgent(cfg)


def _snapshot(time_minutes: int = 10, strike: float | None = None) -> MarketSnapshot:
    implied = ImpliedProbability(
        yes_prob=Decimal("0.55"),
        no_prob=Decimal("0.45"),
        yes_bid=Decimal("54"),
        yes_ask=Decimal("55"),
        no_bid=Decimal("45"),
        no_ask=Decimal("46"),
        spread_cents=Decimal("1"),
    )
    return MarketSnapshot(
        market_id="KXBTC15M-TEST-00",
        event_id="KXBTC15M-TEST",
        title="BTC 15m up?",
        state=ContractState.TRADING,
        implied=implied,
        volume=Decimal("1000"),
        open_interest=Decimal("100"),
        time_to_expiry_hours=Decimal(str(time_minutes / 60)),
        close_time=datetime.now(timezone.utc) + timedelta(minutes=time_minutes),
        category="crypto",
        timeframe="15m",
        strike_price=strike,
    )


def _edge(net_edge: str = "0.06", model_prob: str = "0.61", market_prob: str = "0.55") -> EdgeEstimate:
    return EdgeEstimate(
        market_id="KXBTC15M-TEST-00",
        side="yes",
        action="buy",
        market_prob=Decimal(market_prob),
        model_prob=Decimal(model_prob),
        raw_edge=Decimal(net_edge),
        fee_drag=Decimal("0"),
        slippage_est=Decimal("0"),
        net_edge=Decimal(net_edge),
        edge_type="speculative",
        confidence=Decimal("1.0"),
    )


def test_buy_more_when_edge_improves(monkeypatch):
    agent = _agent()
    pos = OpenPosition(ticker="KXBTC15M-TEST-00", side="yes", contracts=1, avg_entry_cents=50, asset="BTC", timeframe="15m")
    snap = _snapshot()
    improved_edge = _edge(net_edge="0.08", model_prob="0.65", market_prob="0.55")
    monkeypatch.setattr(agent._model, "compute_edge", lambda **kwargs: improved_edge)
    agent._position_memory[pos.ticker] = PositionMemory(edge=Decimal("0.02"), model_prob=Decimal("0.52"), kelly_fraction=0.1, target_contracts=1)

    decision = agent._decide_position_adjustment(pos, snap)

    assert decision.action == "buy_more"
    assert decision.delta_contracts > 0
    assert decision.target_contracts > pos.contracts


def test_sell_when_edge_flips_negative(monkeypatch):
    agent = _agent()
    pos = OpenPosition(ticker="KXBTC15M-TEST-00", side="yes", contracts=4, avg_entry_cents=50, asset="BTC", timeframe="15m")
    snap = _snapshot()
    negative_edge = _edge(net_edge="-0.02", model_prob="0.48", market_prob="0.55")
    monkeypatch.setattr(agent._model, "compute_edge", lambda **kwargs: negative_edge)
    agent._position_memory[pos.ticker] = PositionMemory(edge=Decimal("0.05"), model_prob=Decimal("0.6"), kelly_fraction=0.2, target_contracts=4)

    decision = agent._decide_position_adjustment(pos, snap)

    assert decision.action == "sell"
    assert decision.delta_contracts == pos.contracts
    assert decision.target_contracts == 0


def test_entry_window_respects_timefloor_and_edge():
    agent = _agent()
    good_edge = _edge(net_edge="0.03")
    short_time_snapshot = _snapshot(time_minutes=1)
    long_time_snapshot = _snapshot(time_minutes=8)
    signal = StrategySignal(
        market_id=short_time_snapshot.market_id,
        action=SignalAction.BUY_YES,
        side="yes",
        contracts=1,
        edge=good_edge,
        phase=None,
        reason="",
    )

    assert agent._entry_rule_allows(signal, long_time_snapshot) is True
    assert agent._entry_rule_allows(signal, short_time_snapshot) is False


def test_catastrophic_yes_block(monkeypatch):
    agent = _agent()
    snap = _snapshot(time_minutes=10, strike=59100.0)
    # Force spot well above strike to trigger catastrophic filter
    monkeypatch.setattr(agent, "_get_spot_price", lambda asset: 69480.0)
    edge_est = _edge(net_edge="0.05", model_prob="0.70")
    signal = StrategySignal(
        market_id=snap.market_id,
        action=SignalAction.BUY_YES,
        side="yes",
        contracts=1,
        edge=edge_est,
        phase=None,
        reason="",
    )

    assert agent._is_catastrophic_yes(signal, snap) is True

    pos = OpenPosition(ticker="KXBTC15M-TEST-00", side="yes", contracts=2, avg_entry_cents=40, asset="BTC", timeframe="15m")
    monkeypatch.setattr(agent._model, "compute_edge", lambda **kwargs: edge_est)
    decision = agent._decide_position_adjustment(pos, snap)
    assert decision.action == "sell"
    assert decision.target_contracts == 0
