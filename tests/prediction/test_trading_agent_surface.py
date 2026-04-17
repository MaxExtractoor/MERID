"""Unit tests for KalshiTradingAgent Wire 1 — surface update handling."""
from decimal import Decimal

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def agent_config():
    from merid.prediction.agent_grid_config import (
        AgentConfig, MarketFilterConfig, AgentRiskLimits, EntryWindowConfig
    )
    return AgentConfig(
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


@pytest.fixture
def agent(agent_config):
    with patch("merid.prediction.trading_agent.get_prediction_risk"), \
         patch("merid.prediction.trading_agent.get_session_guard"), \
         patch("merid.prediction.trading_agent.get_venue_gate"):
        from merid.prediction.trading_agent import KalshiTradingAgent
        return KalshiTradingAgent(agent_config)


def test_agent_has_live_markets_init_empty(agent):
    """_live_markets is initialised as empty list."""
    assert hasattr(agent, "_live_markets")
    assert agent._live_markets == []


def test_on_surface_update_stores_near_spot_markets(agent):
    """on_surface_update() populates _live_markets from snapshot entry."""
    mock_entry = MagicMock()
    mock_market_a = MagicMock()
    mock_market_a.market_id = "KXBTC15M-71000"
    mock_market_b = MagicMock()
    mock_market_b.market_id = "KXBTC15M-71500"

    mock_snapshot = MagicMock()
    mock_snapshot.get_entry.return_value = mock_entry

    with patch(
        "config.crypto_spot_kalshi_config.select_markets_near_spot",
        return_value=[mock_market_a, mock_market_b],
    ):
        agent.on_surface_update(mock_snapshot)

    assert len(agent._live_markets) == 2
    assert agent._live_markets[0].market_id == "KXBTC15M-71000"


def test_on_surface_update_no_entry_leaves_markets_unchanged(agent):
    """on_surface_update() with no entry for this asset/tf is a no-op."""
    agent._live_markets = [MagicMock()]  # pre-existing data

    mock_snapshot = MagicMock()
    mock_snapshot.get_entry.return_value = None  # entry not found

    agent.on_surface_update(mock_snapshot)

    assert len(agent._live_markets) == 1  # unchanged


def test_on_surface_update_uses_correct_asset_and_timeframe(agent):
    """get_entry() is called with agent's asset and timeframe."""
    mock_snapshot = MagicMock()
    mock_snapshot.get_entry.return_value = None

    agent.on_surface_update(mock_snapshot)

    mock_snapshot.get_entry.assert_called_once_with("BTC", "15m")


# ── Task 4: proposal submission ─────────────────────────────────────────

def test_agent_has_submit_consensus_proposal_method(agent):
    """_submit_consensus_proposal() exists on KalshiTradingAgent."""
    assert hasattr(agent, "_submit_consensus_proposal")
    assert callable(agent._submit_consensus_proposal)


def test_submit_consensus_proposal_calls_submit_proposal(agent):
    """_submit_consensus_proposal() calls get_consensus_aggregator().submit_proposal()."""
    from unittest.mock import MagicMock, patch

    submitted = []
    mock_signal = MagicMock()

    with patch("merid.prediction.trading_agent.get_kalshi_consensus_adapter") as mock_adapter_fn, \
         patch("merid.prediction.trading_agent.get_consensus_aggregator") as mock_agg_fn:

        mock_adapter = MagicMock()
        mock_proposal = MagicMock()
        mock_adapter.signal_to_proposal.return_value = mock_proposal
        mock_adapter_fn.return_value = mock_adapter

        mock_agg = MagicMock()
        mock_agg.submit_proposal.side_effect = lambda p: submitted.append(p)
        mock_agg_fn.return_value = mock_agg

        agent._submit_consensus_proposal(mock_signal)

    assert len(submitted) == 1
    mock_adapter.signal_to_proposal.assert_called_once()


def test_submit_consensus_proposal_does_not_raise_on_error(agent):
    """_submit_consensus_proposal() swallows errors — never blocks trading."""
    from unittest.mock import patch

    with patch("merid.prediction.trading_agent.get_kalshi_consensus_adapter",
               side_effect=Exception("adapter unavailable")):
        # Should not raise
        agent._submit_consensus_proposal(MagicMock())


@pytest.fixture
def mm_agent_config():
    """Multi-asset MM style: no static ``assets`` list — asset comes from each market ticker."""
    from merid.prediction.agent_grid_config import (
        AgentConfig, MarketFilterConfig, AgentRiskLimits, EntryWindowConfig
    )
    return AgentConfig(
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


@pytest.fixture
def mm_agent(mm_agent_config):
    with patch("merid.prediction.trading_agent.get_prediction_risk"), \
         patch("merid.prediction.trading_agent.get_session_guard"), \
         patch("merid.prediction.trading_agent.get_venue_gate"):
        from merid.prediction.trading_agent import KalshiTradingAgent
        return KalshiTradingAgent(mm_agent_config)


def test_resolve_consensus_asset_infers_btc_from_kxbtc15m_ticker(mm_agent):
    """Empty ``assets`` + KXBTC15M market ticker → BTC for Wire-2 proposals (no Invalid asset: '')."""
    sig = MagicMock()
    sig.market_id = "KXBTC15M-26APR071915-15"
    a, tf = mm_agent._resolve_consensus_asset_timeframe(sig)
    assert a == "BTC"
    assert tf == "15m"


def test_submit_consensus_mm_agent_infers_asset_calls_submit(mm_agent):
    """CRYPTO_15M_MM style agent submits proposal with inferred asset."""
    submitted = []
    mock_signal = MagicMock()
    mock_signal.market_id = "KXETH15M-26APR071915-15"

    with patch("merid.prediction.trading_agent.get_kalshi_consensus_adapter") as mock_adapter_fn, \
         patch("merid.prediction.trading_agent.get_consensus_aggregator") as mock_agg_fn:

        mock_adapter = MagicMock()
        mock_proposal = MagicMock()
        mock_adapter.signal_to_proposal.return_value = mock_proposal
        mock_adapter_fn.return_value = mock_adapter

        mock_agg = MagicMock()
        mock_agg.submit_proposal.side_effect = lambda p: submitted.append(p)
        mock_agg_fn.return_value = mock_agg

        mm_agent._submit_consensus_proposal(mock_signal)

    assert len(submitted) == 1
    call_kw = mock_adapter.signal_to_proposal.call_args[1]
    assert call_kw["asset"] == "ETH"


def test_submit_to_consensus_mm_infers_asset_for_swarm_proposal(mm_agent):
    """``_submit_to_consensus`` must infer asset from ticker when ``assets: []`` (CRYPTO_15M_MM)."""
    from merid.event_venues.base import EventMarket
    from merid.prediction.strategy import SignalAction, StrategySignal

    market = EventMarket(
        market_id="KXBTC15M-26APR072015-15",
        venue="kalshi",
        question="q",
        description="d",
        outcomes=[],
        category="crypto",
    )
    edge = MagicMock()
    edge.net_edge = Decimal("0.01")
    edge.yes_prob = 0.5
    edge.confidence = Decimal("0.5")
    signal = StrategySignal(
        market_id="KXBTC15M-26APR072015-15",
        action=SignalAction.BUY_YES,
        side="yes",
        contracts=5,
        edge=edge,
    )
    snapshot = MagicMock()
    snapshot.implied = MagicMock()
    snapshot.implied.yes_prob = 0.5

    submitted = []
    with patch.object(mm_agent, "_build_kalshi_market_context", return_value={}), \
         patch.object(mm_agent, "_submit_taco_opinion"), \
         patch(
             "merid.prediction.agent_performance_tracker.get_agent_performance_tracker",
         ) as mock_tr, \
         patch(
             "merid.prediction.opinion_strategy.KalshiLiveMarketStrategy",
         ) as mock_kls, \
         patch("merid.swarm.consensus_aggregator.get_consensus_aggregator") as mock_agg_fn:

        mock_tr.return_value.get_agent_metrics.return_value = None
        mock_kls.return_value.estimate.return_value = None
        mock_agg = MagicMock()
        mock_agg.submit_proposal.side_effect = lambda p: submitted.append(p)
        mock_agg_fn.return_value = mock_agg

        mm_agent._submit_to_consensus(market, signal, snapshot, None)

    assert len(submitted) == 1
    assert submitted[0].asset == "BTC"
    assert submitted[0].timeframe == "15m"
