"""Tests for Wire 3 — consensus execution gate in KalshiTradingAgent."""
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def agent_config():
    from merid.prediction.agent_grid_config import (
        AgentConfig, MarketFilterConfig, AgentRiskLimits, EntryWindowConfig,
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


def test_apply_size_band_small_reduces_contracts(agent):
    result = agent._apply_size_band(base_contracts=100, band="small")
    assert result == 25

def test_apply_size_band_large_increases_contracts(agent):
    result = agent._apply_size_band(base_contracts=100, band="large")
    assert result == 150

def test_apply_size_band_base_unchanged(agent):
    result = agent._apply_size_band(base_contracts=100, band="base")
    assert result == 100

def test_apply_size_band_unknown_defaults_to_small(agent):
    result = agent._apply_size_band(base_contracts=100, band="unknown_band")
    assert result == 25

def test_apply_solo_trade_cap_reduces_contracts(agent):
    signal = MagicMock()
    signal.contracts = 200
    agent._apply_solo_trade_cap(signal)
    assert signal.contracts <= 50  # small band from 200 = 50

def test_consensus_gate_returns_none_when_forming(agent):
    from merid.swarm.consensus_aggregator import ConsensusStatus
    mock_consensus = MagicMock()
    mock_consensus.status = ConsensusStatus.FORMING

    with patch("merid.prediction.trading_agent.get_consensus_aggregator") as mock_agg_fn, \
         patch("merid.prediction.crypto_edge_production.get_crypto_edge_runtime") as mock_rt_fn:
        mock_agg = MagicMock()
        mock_agg.get_consensus.return_value = mock_consensus
        mock_agg_fn.return_value = mock_agg
        # Mock runtime to return 'full' mode (not 'bypass' or 'soft')
        mock_rt = MagicMock()
        mock_rt.mm_consensus_mode = "full"
        mock_rt_fn.return_value = mock_rt

        result = agent._check_consensus_gate(signal=MagicMock(), order_contracts=50)

    assert result is None

def test_consensus_gate_blocks_high_confidence_opposition(agent):
    from merid.swarm.consensus_aggregator import ConsensusStatus
    from merid.prediction.strategy import SignalAction

    mock_consensus = MagicMock()
    mock_consensus.status = ConsensusStatus.READY
    mock_consensus.consensus_direction = "no"
    mock_consensus.consensus_confidence = 0.85
    mock_consensus.size_band = "base"

    signal = MagicMock()
    signal.action = SignalAction.BUY_YES

    with patch("merid.prediction.trading_agent.get_consensus_aggregator") as mock_agg_fn:
        mock_agg = MagicMock()
        mock_agg.get_consensus.return_value = mock_consensus
        mock_agg_fn.return_value = mock_agg

        result = agent._check_consensus_gate(signal=signal, order_contracts=50)

    assert result is None

def test_consensus_gate_applies_size_band_when_ready_and_agrees(agent):
    from merid.swarm.consensus_aggregator import ConsensusStatus
    from merid.prediction.strategy import SignalAction

    mock_consensus = MagicMock()
    mock_consensus.status = ConsensusStatus.READY
    mock_consensus.consensus_direction = "yes"
    mock_consensus.consensus_confidence = 0.75
    mock_consensus.size_band = "large"

    signal = MagicMock()
    signal.action = SignalAction.BUY_YES

    with patch("merid.prediction.trading_agent.get_consensus_aggregator") as mock_agg_fn:
        mock_agg = MagicMock()
        mock_agg.get_consensus.return_value = mock_consensus
        mock_agg_fn.return_value = mock_agg

        result = agent._check_consensus_gate(signal=signal, order_contracts=100)

    assert result == 150


def test_consensus_gate_stale_applies_solo_cap_and_returns_capped(agent):
    from merid.swarm.consensus_aggregator import ConsensusStatus

    mock_consensus = MagicMock()
    mock_consensus.status = ConsensusStatus.STALE

    signal = MagicMock()
    signal.contracts = 200

    with patch("merid.prediction.trading_agent.get_consensus_aggregator") as mock_agg_fn:
        mock_agg = MagicMock()
        mock_agg.get_consensus.return_value = mock_consensus
        mock_agg_fn.return_value = mock_agg

        result = agent._check_consensus_gate(signal=signal, order_contracts=200)

    assert result == 50  # small band: 200 * 0.25 = 50
    assert signal.contracts == 50


def test_consensus_gate_none_consensus_applies_solo_cap_and_returns_capped(agent):
    signal = MagicMock()
    signal.contracts = 200

    with patch("merid.prediction.trading_agent.get_consensus_aggregator") as mock_agg_fn:
        mock_agg = MagicMock()
        mock_agg.get_consensus.return_value = None
        mock_agg_fn.return_value = mock_agg

        result = agent._check_consensus_gate(signal=signal, order_contracts=200)

    assert result == 50  # small band: 200 * 0.25 = 50
    assert signal.contracts == 50


def test_consensus_gate_conflicted_applies_solo_cap_and_returns_capped(agent):
    from merid.swarm.consensus_aggregator import ConsensusStatus

    mock_consensus = MagicMock()
    mock_consensus.status = ConsensusStatus.CONFLICTED

    signal = MagicMock()
    signal.contracts = 200

    with patch("merid.prediction.trading_agent.get_consensus_aggregator") as mock_agg_fn:
        mock_agg = MagicMock()
        mock_agg.get_consensus.return_value = mock_consensus
        mock_agg_fn.return_value = mock_agg

        result = agent._check_consensus_gate(signal=signal, order_contracts=200)

    assert result == 50  # small band: 200 * 0.25 = 50
    assert signal.contracts == 50


def test_consensus_gate_sell_yes_not_blocked_by_yes_consensus(agent):
    """SELL_YES is closing a YES position; it should align with 'yes' consensus, not be blocked."""
    from merid.swarm.consensus_aggregator import ConsensusStatus
    from merid.prediction.strategy import SignalAction

    mock_consensus = MagicMock()
    mock_consensus.status = ConsensusStatus.READY
    mock_consensus.consensus_direction = "yes"
    mock_consensus.consensus_confidence = 0.90  # high confidence YES consensus
    mock_consensus.size_band = "base"

    signal = MagicMock()
    signal.action = SignalAction.SELL_YES  # closing a YES position

    with patch("merid.prediction.trading_agent.get_consensus_aggregator") as mock_agg_fn:
        mock_agg = MagicMock()
        mock_agg.get_consensus.return_value = mock_consensus
        mock_agg_fn.return_value = mock_agg

        result = agent._check_consensus_gate(signal=signal, order_contracts=100)

    # Should NOT be blocked — SELL_YES maps to "yes", which matches consensus
    assert result is not None
    assert result == 100  # base band
