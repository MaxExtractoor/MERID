"""Tests for Kalshi Consensus Bridge — agent → consensus integration.

Test Cases:
1. StrategySignal → Energy packet conversion
2. Order intent → Vote response conversion
3. Vote decision logic (edge + confidence thresholds)
4. Batch conversions
5. Asset and timeframe extraction
"""

import pytest
from unittest.mock import MagicMock

from merid.prediction.consensus_bridge import (
    KalshiConsensusAdapter,
    get_kalshi_consensus_adapter,
    reset_kalshi_consensus_adapter,
)
from merid.prediction.strategy import StrategySignal, SignalAction
from merid.event_venues.base import EventMarket, EventOutcome
from decimal import Decimal


@pytest.fixture
def adapter():
    """Create a fresh KalshiConsensusAdapter for testing."""
    reset_kalshi_consensus_adapter()
    return KalshiConsensusAdapter()


@pytest.fixture
def mock_market():
    """Create a mock EventMarket for testing."""
    return EventMarket(
        market_id="BTC-24FEB-50K-YES",
        venue="kalshi",
        question="Will BTC reach $50k by Feb 24?",
        description="Test market",
        outcomes=[
            EventOutcome("yes", "Yes", Decimal("0.55")),
            EventOutcome("no", "No", Decimal("0.45")),
        ],
        category="crypto",
        active=True,
    )


@pytest.fixture
def mock_signal():
    """Create a mock StrategySignal for testing."""
    signal = MagicMock(spec=StrategySignal)
    signal.action = SignalAction.BUY_YES
    signal.contracts = 10
    signal.limit_price_cents = 55.0
    signal.confidence = 0.7
    signal.reasoning = "Strong bullish edge detected"
    
    # Mock edge
    edge = MagicMock()
    edge.net_edge = 0.05  # 5% edge
    signal.edge = edge
    
    return signal


# ── Test: Signal → Energy Packet ──────────────────────────────────────────

def test_signal_to_energy_basic(adapter, mock_signal, mock_market):
    """Test basic signal to energy packet conversion."""
    energy = adapter.signal_to_energy(mock_signal, mock_market, agent_id="test_agent")
    
    assert "energy_id" in energy
    assert energy["source"] == "kalshi"
    assert energy["domain"] == "prediction"
    assert energy["venue"] == "kalshi"
    assert energy["agent_id"] == "test_agent"
    assert "payload" in energy
    assert "metadata" in energy


def test_signal_to_energy_metadata(adapter, mock_signal, mock_market):
    """Test energy packet metadata includes signal details."""
    energy = adapter.signal_to_energy(mock_signal, mock_market)
    
    metadata = energy["metadata"]
    assert metadata["market_id"] == "BTC-24FEB-50K-YES"
    assert metadata["asset"] == "BTC"
    assert metadata["action"] == "buy_yes"  # SignalAction.BUY_YES.value is lowercase
    assert metadata["direction"] == "yes"  # BUY_YES = yes
    assert metadata["contracts"] == 10
    assert metadata["limit_price_cents"] == 55.0
    assert metadata["edge_pct"] == 5.0  # 0.05 * 100
    assert metadata["confidence"] == 0.7


def test_signal_to_energy_payload_readable(adapter, mock_signal, mock_market):
    """Test energy packet payload is human-readable."""
    energy = adapter.signal_to_energy(mock_signal, mock_market)
    
    payload = energy["payload"]
    assert "BUY YES" in payload
    assert "10 contracts" in payload
    assert "BTC-24FEB-50K-YES" in payload
    assert "55" in payload  # Price
    assert "Edge: 5.0%" in payload
    assert "Confidence: 0.7" in payload


def test_signal_to_energy_different_actions(adapter, mock_market):
    """Test energy conversion for different signal actions."""
    actions = [
        (SignalAction.BUY_YES, "yes", "yes"),
        (SignalAction.SELL_YES, "no", "yes"),
        (SignalAction.BUY_NO, "no", "no"),
        (SignalAction.SELL_NO, "yes", "no"),
        (SignalAction.HOLD, "neutral", "no"),
    ]
    
    for action, expected_direction, expected_side in actions:
        signal = MagicMock(spec=StrategySignal)
        signal.action = action
        signal.contracts = 5
        signal.limit_price_cents = 50.0
        signal.confidence = 0.5
        signal.reasoning = "Test"
        signal.edge = MagicMock(net_edge=0.03)
        
        energy = adapter.signal_to_energy(signal, mock_market)
        
        assert energy["metadata"]["action"] == action.value
        assert energy["metadata"]["direction"] == expected_direction


# ── Test: Order Intent → Vote ─────────────────────────────────────────────

def test_order_intent_to_vote_accept(adapter):
    """Test order intent with strong signal → accept vote."""
    intent = {
        "action": "BUY_YES",
        "contracts": 10,
        "market_id": "BTC-TEST",
        "limit_price_cents": 55,
    }
    
    vote = adapter.order_intent_to_vote(intent, edge=0.10, confidence=0.7)
    
    assert vote["vote"] == "accept"
    assert vote["confidence"] == 0.7
    assert "reasoning" in vote
    assert "simulation" in vote
    assert vote["metadata"]["edge_pct"] == 10.0


def test_order_intent_to_vote_reject(adapter):
    """Test order intent with weak signal → reject vote."""
    intent = {
        "action": "BUY_YES",
        "contracts": 10,
        "market_id": "BTC-TEST",
    }
    
    # Edge between abstain and accept thresholds → reject
    vote = adapter.order_intent_to_vote(intent, edge=0.05, confidence=0.5)
    
    assert vote["vote"] == "reject"
    assert "does not meet minimum thresholds" in vote["reasoning"].lower()


def test_order_intent_to_vote_abstain(adapter):
    """Test order intent with very weak signal → abstain vote."""
    intent = {
        "action": "BUY_YES",
        "contracts": 10,
        "market_id": "BTC-TEST",
    }
    
    # Edge < 1% or confidence < 0.3
    vote = adapter.order_intent_to_vote(intent, edge=0.005, confidence=0.2)
    
    assert vote["vote"] == "abstain"
    assert "insufficient" in vote["reasoning"].lower()


def test_order_intent_to_vote_no_action(adapter):
    """Test NO_ACTION or HOLD signals → abstain vote."""
    for action in ["NO_ACTION", "HOLD"]:
        intent = {
            "action": action,
            "contracts": 0,
            "market_id": "BTC-TEST",
        }
        
        vote = adapter.order_intent_to_vote(intent, edge=0.10, confidence=0.9)
        
        assert vote["vote"] == "abstain"


def test_order_intent_to_vote_custom_reasoning(adapter):
    """Test custom reasoning is preserved."""
    intent = {"action": "BUY_YES", "contracts": 10, "market_id": "TEST"}
    custom_reasoning = "Custom agent logic applied here"
    
    vote = adapter.order_intent_to_vote(
        intent, edge=0.05, confidence=0.7, reasoning=custom_reasoning
    )
    
    assert vote["reasoning"] == custom_reasoning


# ── Test: Vote Decision Logic ─────────────────────────────────────────────

def test_compute_vote_decision_accept_thresholds(adapter):
    """Test vote decision with various threshold combinations."""
    intent = {"action": "BUY_YES", "market_id": "TEST"}
    
    # Edge >= accept_edge_pct (8% from StrategyConfig), confidence >= 0.60 → accept
    decision = adapter._compute_vote_decision(0.10, 0.7, intent)
    assert decision == "accept"
    
    decision = adapter._compute_vote_decision(0.12, 0.8, intent)
    assert decision == "accept"


def test_compute_vote_decision_abstain_thresholds(adapter):
    """Test vote decision abstain thresholds."""
    intent = {"action": "BUY_YES", "market_id": "TEST"}
    
    # Edge < 1% → abstain
    decision = adapter._compute_vote_decision(0.005, 0.8, intent)
    assert decision == "abstain"
    
    # Confidence < 0.3 → abstain
    decision = adapter._compute_vote_decision(0.05, 0.2, intent)
    assert decision == "abstain"


def test_compute_vote_decision_reject_middle(adapter):
    """Test vote decision in the middle range → reject."""
    intent = {"action": "BUY_YES", "market_id": "TEST"}
    
    # Edge between abstain (4%) and accept (8%) thresholds, decent confidence → reject
    decision = adapter._compute_vote_decision(0.05, 0.5, intent)
    assert decision == "reject"


# ── Test: Utility Functions ───────────────────────────────────────────────

def test_action_to_string(adapter):
    """Test action enum to string conversion."""
    assert adapter._action_to_string(SignalAction.BUY_YES) == "BUY YES"
    assert adapter._action_to_string(SignalAction.SELL_NO) == "SELL NO"
    assert adapter._action_to_string(SignalAction.HOLD) == "HOLD"


def test_action_to_direction(adapter):
    """Test action to directional intent conversion (yes/no/neutral vocabulary)."""
    assert adapter._action_to_direction(SignalAction.BUY_YES) == "yes"
    assert adapter._action_to_direction(SignalAction.SELL_NO) == "yes"
    assert adapter._action_to_direction(SignalAction.BUY_NO) == "no"
    assert adapter._action_to_direction(SignalAction.SELL_YES) == "no"
    assert adapter._action_to_direction(SignalAction.HOLD) == "neutral"


def test_extract_asset(adapter):
    """Test asset extraction from tickers."""
    assert adapter._extract_asset("BTC-24FEB-50K") == "BTC"
    assert adapter._extract_asset("ETH-WEEKLY-HIGH") == "ETH"
    assert adapter._extract_asset("SOL-DAILY") == "SOL"
    assert adapter._extract_asset("UNKNOWN-MARKET") == "UNKNOWN"


def test_extract_timeframe(adapter):
    """Test timeframe extraction from tickers."""
    assert adapter._extract_timeframe("BTC-24H-HIGH") == "24h"
    assert adapter._extract_timeframe("ETH-WEEKLY-LOW") == "weekly"
    assert adapter._extract_timeframe("SOL-HOURLY") == "1h"
    assert adapter._extract_timeframe("BTC-TEST") == "unknown"


# ── Test: Batch Conversions ───────────────────────────────────────────────

def test_signals_to_energy_batch(adapter, mock_signal, mock_market):
    """Test batch signal to energy conversion."""
    signals = [
        (mock_signal, mock_market, "agent1"),
        (mock_signal, mock_market, "agent2"),
        (mock_signal, mock_market, "agent3"),
    ]
    
    energies = adapter.signals_to_energy_batch(signals)
    
    assert len(energies) == 3
    assert all(e["source"] == "kalshi" for e in energies)
    assert energies[0]["agent_id"] == "agent1"
    assert energies[1]["agent_id"] == "agent2"
    assert energies[2]["agent_id"] == "agent3"


def test_intents_to_votes_batch(adapter):
    """Test batch order intent to vote conversion."""
    intents = [
        ({"action": "BUY_YES", "market_id": "M1"}, 0.10, 0.7),
        ({"action": "BUY_YES", "market_id": "M2"}, 0.05, 0.5),
        ({"action": "HOLD", "market_id": "M3"}, 0.10, 0.9),
    ]
    
    votes = adapter.intents_to_votes_batch(intents)
    
    assert len(votes) == 3
    assert votes[0]["vote"] == "accept"  # Strong signal (10% edge > 8% threshold)
    assert votes[1]["vote"] == "reject"  # Mid signal (5% edge between abstain and accept)
    assert votes[2]["vote"] == "abstain"  # HOLD action


# ── Test: Singleton ────────────────────────────────────────────────────────

def test_singleton_accessor():
    """Test singleton accessor returns same instance."""
    reset_kalshi_consensus_adapter()
    
    adapter1 = get_kalshi_consensus_adapter()
    adapter2 = get_kalshi_consensus_adapter()
    
    assert adapter1 is adapter2


# ── Test: Edge Cases ───────────────────────────────────────────────────────

def test_signal_to_energy_no_edge(adapter, mock_market):
    """Test signal conversion when edge is None."""
    signal = MagicMock(spec=StrategySignal)
    signal.action = SignalAction.BUY_YES
    signal.contracts = 10
    signal.limit_price_cents = 50.0
    signal.confidence = 0.5
    signal.reasoning = "Test"
    signal.edge = None  # No edge
    
    energy = adapter.signal_to_energy(signal, mock_market)
    
    assert energy["metadata"]["edge_pct"] == 0
    assert "payload" in energy


def test_simulation_generation(adapter):
    """Test simulation text generation for different decisions."""
    intent = {
        "action": "BUY_YES",
        "contracts": 10,
        "limit_price_cents": 50,
        "market_id": "TEST",
    }

    # Accept decision
    sim_accept = adapter._generate_simulation(intent, 0.05, "accept")
    assert "profit" in sim_accept.lower()
    assert "10 contracts" in sim_accept

    # Reject decision
    sim_reject = adapter._generate_simulation(intent, 0.01, "reject")
    assert "not meet" in sim_reject.lower()

    # Abstain decision
    sim_abstain = adapter._generate_simulation(intent, 0.00, "abstain")
    assert "insufficient" in sim_abstain.lower() or "waiting" in sim_abstain.lower()


# ── Task 1: _action_to_direction vocabulary ─────────────────────────────

def test_action_to_direction_buy_yes_returns_yes(adapter):
    from merid.prediction.strategy import SignalAction
    assert adapter._action_to_direction(SignalAction.BUY_YES) == "yes"

def test_action_to_direction_buy_no_returns_no(adapter):
    from merid.prediction.strategy import SignalAction
    assert adapter._action_to_direction(SignalAction.BUY_NO) == "no"

def test_action_to_direction_hold_returns_neutral(adapter):
    from merid.prediction.strategy import SignalAction
    assert adapter._action_to_direction(SignalAction.HOLD) == "neutral"

def test_action_to_direction_unknown_returns_neutral(adapter):
    assert adapter._action_to_direction(None) == "neutral"

def test_action_to_direction_sell_yes_returns_no(adapter):
    from merid.prediction.strategy import SignalAction
    assert adapter._action_to_direction(SignalAction.SELL_YES) == "no"

def test_action_to_direction_sell_no_returns_yes(adapter):
    from merid.prediction.strategy import SignalAction
    assert adapter._action_to_direction(SignalAction.SELL_NO) == "yes"

def test_action_to_direction_quote_returns_neutral(adapter):
    from merid.prediction.strategy import SignalAction
    assert adapter._action_to_direction(SignalAction.QUOTE) == "neutral"


# ── Task 2: signal_to_proposal ──────────────────────────────────────────

from merid.swarm.consensus_aggregator import AgentProposal


@pytest.fixture
def mock_live_markets():
    m = MagicMock()
    m.market_id = "KXBTC15M-71000"
    m.yes_price = 49
    m.no_price = 51
    m.spread_bps = 20
    m.open_interest = 1200
    m.distance_pct = 0.36
    m.target_price = 71000.0
    return [m]


def _make_signal(action=SignalAction.BUY_YES, contracts=10, confidence=0.7, edge_pct=0.08, limit_price_cents=49):
    """Helper: build a StrategySignal with extra attrs for signal_to_proposal tests."""
    from merid.prediction.strategy import StrategySignal, SignalAction as SA
    sig = StrategySignal(
        market_id="KXBTC15M-71000",
        action=action,
        side="yes",
        contracts=contracts,
        limit_price_cents=limit_price_cents,
    )
    sig.confidence = confidence
    sig.edge_pct = edge_pct
    return sig


def test_signal_to_proposal_returns_agent_proposal(adapter, mock_live_markets):
    """signal_to_proposal() returns a valid AgentProposal."""
    signal = _make_signal()
    proposal = adapter.signal_to_proposal(
        signal=signal,
        agent_id="kalshi-btc_15m",
        asset="BTC",
        timeframe="15m",
        archetype="directional",
        live_markets=mock_live_markets,
    )
    assert isinstance(proposal, AgentProposal)


def test_signal_to_proposal_direction_matches_action(adapter, mock_live_markets):
    """BUY_YES signal -> direction 'yes'."""
    signal = _make_signal()
    proposal = adapter.signal_to_proposal(
        signal=signal,
        agent_id="kalshi-btc_15m",
        asset="BTC",
        timeframe="15m",
        archetype="directional",
        live_markets=mock_live_markets,
    )
    assert proposal.direction == "yes"
    assert proposal.asset == "BTC"
    assert proposal.timeframe == "15m"
    assert proposal.agent_id == "kalshi-btc_15m"
    assert proposal.agent_archetype == "directional"


def test_signal_to_proposal_populates_market_data(adapter, mock_live_markets):
    """market_data field is populated from live_markets[0]."""
    signal = _make_signal()
    proposal = adapter.signal_to_proposal(
        signal=signal,
        agent_id="kalshi-btc_15m",
        asset="BTC",
        timeframe="15m",
        archetype="directional",
        live_markets=mock_live_markets,
    )
    assert proposal.market_data is not None
    assert proposal.market_data["top_market_id"] == "KXBTC15M-71000"
    assert proposal.market_data["spread_bps"] == 20


def test_signal_to_proposal_empty_live_markets_still_works(adapter):
    """Empty live_markets list -> market_data is None, proposal still valid."""
    signal = _make_signal(confidence=0.6, edge_pct=0.05, limit_price_cents=50)
    proposal = adapter.signal_to_proposal(
        signal=signal,
        agent_id="kalshi-btc_15m",
        asset="BTC",
        timeframe="15m",
        archetype="directional",
        live_markets=[],
    )
    assert proposal.direction == "yes"
    assert proposal.market_data is None


def test_signal_to_proposal_probability_in_range(adapter, mock_live_markets):
    """Probability is clamped to [0.05, 0.95]."""
    signal = _make_signal(confidence=1.0, edge_pct=9.99)
    proposal = adapter.signal_to_proposal(
        signal=signal,
        agent_id="test",
        asset="BTC",
        timeframe="15m",
        archetype="directional",
        live_markets=mock_live_markets,
    )
    assert 0.05 <= proposal.probability <= 0.95
