"""AgentGrid PM path: cycle reaches order dispatch when strategy + risk allow (paper)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merid.prediction.agent_grid_config import (
    AgentConfig,
    AgentRiskLimits,
    EntryWindowConfig,
    MarketFilterConfig,
)
from merid.prediction.risk import PreTradeCheck, RiskAction
from merid.prediction.strategy import SignalAction, StrategySignal
from merid.prediction.trading_agent import KalshiTradingAgent, LifecycleState
from merid.swarm.consensus_aggregator import ConsensusStatus, ConsensusView
from merid.tick_events import TickContext


@pytest.mark.asyncio
async def test_cycle_dispatches_execute_when_consensus_ready_and_risk_allows():
    """Synthetic edge: strategy fires, consensus READY, risk OK → _execute_signal awaited."""
    cfg = AgentConfig(
        name="BTC_15M",
        category="crypto",
        assets=["BTC"],
        timeframes=["15m"],
        archetype="directional",
        market_filter=MarketFilterConfig(category="crypto", frequency="fifteen_min"),
        risk_limits=AgentRiskLimits(),
        entry_window=EntryWindowConfig(),
        enabled=True,
    )

    market = MagicMock()
    market.market_id = "KXBTC-15M-TEST"
    market.category = "crypto"
    market.volume = None

    snap = MagicMock()
    snap.resolved_asset = "BTC"
    snap.resolved_timeframe = "15m"
    snap.implied = MagicMock(
        yes_prob=0.45,
        no_prob=0.55,
        yes_bid=0.44,
        yes_ask=0.46,
    )
    snap.timestamp = time.time()
    snap.time_to_expiry_hours = Decimal("0.2")
    snap.depth_at_best = 10

    edge = MagicMock()
    edge.net_edge = Decimal("0.08")
    edge.confidence = Decimal("0.72")
    edge.yes_prob = Decimal("0.58")
    signal = StrategySignal(
        market_id=market.market_id,
        action=SignalAction.BUY_YES,
        side="yes",
        contracts=3,
        limit_price_cents=50,
        edge=edge,
        reason="synthetic_test",
    )

    mock_risk = MagicMock()
    mock_risk.check_order.return_value = PreTradeCheck(
        allowed=True,
        action=RiskAction.ALLOW,
        reason="ok",
        adjusted_size=3,
    )

    consensus = ConsensusView(
        asset="BTC",
        timeframe="15m",
        timestamp=datetime.now(timezone.utc),
        status=ConsensusStatus.READY,
        consensus_direction="yes",
        consensus_probability=0.6,
        consensus_confidence=0.7,
        total_agents=1,
        voting_agents=1,
        direction_breakdown={"yes": 1, "no": 0, "neutral": 0},
        size_band="base",
        size_rationale="test",
        confidence_factors=[],
        disagreement_flags=[],
        raw_proposals=[],
        usable=True,
    )

    tick_bus = MagicMock()
    tick_bus.emit = MagicMock()
    _tick = TickContext(
        agent_id=cfg.name,
        cycle_number=1,
        mode="paper",
    )

    with patch("merid.prediction.trading_agent.get_prediction_risk", return_value=mock_risk), \
         patch("merid.prediction.trading_agent.get_session_guard") as mock_sg, \
         patch("merid.prediction.trading_agent.get_venue_gate"), \
         patch("merid.prediction.trading_agent.get_tick_bus", return_value=tick_bus), \
         patch.object(KalshiTradingAgent, "_check_stop_losses", new_callable=AsyncMock), \
         patch.object(KalshiTradingAgent, "_resolve_markets", new_callable=AsyncMock), \
         patch.object(KalshiTradingAgent, "_filter_active_contracts_async", new_callable=AsyncMock) as mock_filt, \
         patch.object(KalshiTradingAgent, "_in_entry_window", return_value=True), \
         patch.object(KalshiTradingAgent, "_get_seconds_to_expiry", return_value=600.0), \
         patch.object(KalshiTradingAgent, "_build_snapshot", return_value=snap), \
         patch.object(KalshiTradingAgent, "_get_mood_context", return_value=None), \
         patch.object(KalshiTradingAgent, "_record_signal", new_callable=AsyncMock), \
         patch.object(KalshiTradingAgent, "_submit_to_consensus"), \
         patch.object(KalshiTradingAgent, "_submit_consensus_proposal"), \
         patch.object(KalshiTradingAgent, "_record_explainability_decision"), \
         patch.object(KalshiTradingAgent, "_get_consensus", return_value=consensus), \
         patch.object(KalshiTradingAgent, "_execute_signal", new_callable=AsyncMock) as mock_exec:

        mock_sg.return_value.is_trading_allowed.return_value = True
        mock_filt.return_value = [market]

        agent = KalshiTradingAgent(cfg)
        agent.state.lifecycle = LifecycleState.ACTIVE
        agent.state.started_at = datetime.now(timezone.utc)
        agent._resolved_markets = [market]

        with patch.object(agent, "_strategy") as mock_strategy:
            mock_strategy.evaluate.return_value = signal
            await agent._run_cycle_body(datetime.now(timezone.utc), _tick, tick_bus)

    mock_exec.assert_awaited_once()


@pytest.mark.asyncio
async def test_mm_quote_reaches_execute_with_neutral_swarm_consensus():
    """QUOTE is not directional; READY+neutral must not block MM (regression: signal_dir was \"no\")."""
    cfg = AgentConfig(
        name="CRYPTO_15M_MM",
        category="crypto",
        assets=[],
        timeframes=["15m"],
        archetype="market_maker",
        market_filter=MarketFilterConfig(category="crypto", frequency="fifteen_min"),
        risk_limits=AgentRiskLimits(),
        entry_window=EntryWindowConfig(),
        enabled=True,
    )

    market = MagicMock()
    market.market_id = "KXBTC15M-26APR072045-45"
    market.category = "crypto"
    market.volume = None

    snap = MagicMock()
    snap.resolved_asset = "BTC"
    snap.resolved_timeframe = "15m"
    snap.implied = MagicMock(
        yes_prob=Decimal("0.5"),
        no_prob=Decimal("0.5"),
        yes_bid=Decimal("0.48"),
        yes_ask=Decimal("0.52"),
    )
    snap.timestamp = time.time()
    snap.time_to_expiry_hours = Decimal("0.2")
    snap.depth_at_best = 10

    signal = StrategySignal(
        market_id=market.market_id,
        action=SignalAction.QUOTE,
        side="yes",
        contracts=5,
        bid_price_cents=48,
        ask_price_cents=52,
        reason="MM quoting",
    )

    mock_risk = MagicMock()
    mock_risk.check_order.return_value = PreTradeCheck(
        allowed=True,
        action=RiskAction.ALLOW,
        reason="ok",
        adjusted_size=5,
    )

    consensus = ConsensusView(
        asset="BTC",
        timeframe="15m",
        timestamp=datetime.now(timezone.utc),
        status=ConsensusStatus.READY,
        consensus_direction="neutral",
        consensus_probability=0.5,
        consensus_confidence=0.5,
        total_agents=2,
        voting_agents=2,
        direction_breakdown={"yes": 0, "no": 0, "neutral": 2},
        size_band="base",
        size_rationale="test",
        confidence_factors=[],
        disagreement_flags=[],
        raw_proposals=[],
        usable=True,
    )

    tick_bus = MagicMock()
    tick_bus.emit = MagicMock()
    _tick = TickContext(
        agent_id=cfg.name,
        cycle_number=1,
        mode="paper",
    )

    with patch("merid.prediction.trading_agent.get_prediction_risk", return_value=mock_risk), \
         patch("merid.prediction.trading_agent.get_session_guard") as mock_sg, \
         patch("merid.prediction.trading_agent.get_venue_gate"), \
         patch("merid.prediction.trading_agent.get_tick_bus", return_value=tick_bus), \
         patch.object(KalshiTradingAgent, "_check_stop_losses", new_callable=AsyncMock), \
         patch.object(KalshiTradingAgent, "_resolve_markets", new_callable=AsyncMock), \
         patch.object(KalshiTradingAgent, "_filter_active_contracts_async", new_callable=AsyncMock) as mock_filt, \
         patch.object(KalshiTradingAgent, "_in_entry_window", return_value=True), \
         patch.object(KalshiTradingAgent, "_get_seconds_to_expiry", return_value=600.0), \
         patch.object(KalshiTradingAgent, "_build_snapshot", return_value=snap), \
         patch.object(KalshiTradingAgent, "_get_mood_context", return_value=None), \
         patch.object(KalshiTradingAgent, "_record_signal", new_callable=AsyncMock), \
         patch.object(KalshiTradingAgent, "_submit_to_consensus"), \
         patch.object(KalshiTradingAgent, "_submit_consensus_proposal"), \
         patch.object(KalshiTradingAgent, "_record_explainability_decision"), \
         patch.object(KalshiTradingAgent, "_get_consensus", return_value=consensus), \
         patch.object(KalshiTradingAgent, "_execute_signal", new_callable=AsyncMock) as mock_exec:

        mock_sg.return_value.is_trading_allowed.return_value = True
        mock_filt.return_value = [market]

        agent = KalshiTradingAgent(cfg)
        agent.state.lifecycle = LifecycleState.ACTIVE
        agent.state.started_at = datetime.now(timezone.utc)
        agent._resolved_markets = [market]

        with patch.object(agent, "_strategy") as mock_strategy:
            mock_strategy.evaluate.return_value = signal
            await agent._run_cycle_body(datetime.now(timezone.utc), _tick, tick_bus)

    mock_exec.assert_awaited_once()
