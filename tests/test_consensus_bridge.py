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
    assert metadata["direction"] == "long"  # BUY_YES = long
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
        (SignalAction.BUY_YES, "long", "yes"),
        (SignalAction.SELL_YES, "short", "yes"),
        (SignalAction.BUY_NO, "short", "no"),
        (SignalAction.SELL_NO, "long", "no"),
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
    
    vote = adapter.order_intent_to_vote(intent, edge=0.05, confidence=0.7)
    
    assert vote["vote"] == "accept"
    assert vote["confidence"] == 0.7
    assert "reasoning" in vote
    assert "simulation" in vote
    assert vote["metadata"]["edge_pct"] == 5.0


def test_order_intent_to_vote_reject(adapter):
    """Test order intent with weak signal → reject vote."""
    intent = {
        "action": "BUY_YES",
        "contracts": 10,
        "market_id": "BTC-TEST",
    }
    
    # Edge < 3% but confidence >= 0.5
    vote = adapter.order_intent_to_vote(intent, edge=0.02, confidence=0.5)
    
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
    
    # Edge >= 3%, confidence >= 0.5 → accept
    decision = adapter._compute_vote_decision(0.03, 0.5, intent)
    assert decision == "accept"
    
    decision = adapter._compute_vote_decision(0.05, 0.7, intent)
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
    
    # Edge 2%, confidence 0.4 → reject (not strong enough)
    decision = adapter._compute_vote_decision(0.02, 0.4, intent)
    assert decision == "reject"


# ── Test: Utility Functions ───────────────────────────────────────────────

def test_action_to_string(adapter):
    """Test action enum to string conversion."""
    assert adapter._action_to_string(SignalAction.BUY_YES) == "BUY YES"
    assert adapter._action_to_string(SignalAction.SELL_NO) == "SELL NO"
    assert adapter._action_to_string(SignalAction.HOLD) == "HOLD"


def test_action_to_direction(adapter):
    """Test action to directional intent conversion."""
    assert adapter._action_to_direction(SignalAction.BUY_YES) == "long"
    assert adapter._action_to_direction(SignalAction.SELL_NO) == "long"
    assert adapter._action_to_direction(SignalAction.BUY_NO) == "short"
    assert adapter._action_to_direction(SignalAction.SELL_YES) == "short"
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
        ({"action": "BUY_YES", "market_id": "M1"}, 0.05, 0.7),
        ({"action": "BUY_YES", "market_id": "M2"}, 0.02, 0.4),
        ({"action": "HOLD", "market_id": "M3"}, 0.10, 0.9),
    ]
    
    votes = adapter.intents_to_votes_batch(intents)
    
    assert len(votes) == 3
    assert votes[0]["vote"] == "accept"  # Strong signal
    assert votes[1]["vote"] == "reject"  # Weak signal
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
