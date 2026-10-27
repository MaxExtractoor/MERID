"""Tests for Q-Inline Policy Agent.

Validates:
- State aggregation from all signal sources
- Q-value computation with regime adjustments
- Action selection with confidence thresholds
- Position sizing with signal strength
- Urgency determination
- Halt regime handling
"""

import time
import pytest
from typing import Dict

from merid.policy.qinline_policy import (
    QInlinePolicy,
    QInlineDecision,
    QInlineState,
    QValue,
    TradeDecision,
    Urgency,
    get_qinline_policy,
    reset_qinline_policy,
)
from merid.signals.unified_regime_classifier import ExecutionRegime


class TestQValue:
    """Test QValue dataclass."""

    def test_qvalue_creation(self):
        """Test QValue creation."""
        qv = QValue(action="long", value=0.5, confidence=0.8, visits=10)
        assert qv.action == "long"
        assert qv.value == 0.5
        assert qv.confidence == 0.8
        assert qv.visits == 10


class TestQInlineDecision:
    """Test QInlineDecision dataclass."""

    def test_should_execute_long(self):
        """Test execute detection for long."""
        decision = QInlineDecision(
            ticker="KXBTC-15M-UP",
            asset="BTC",
            decision=TradeDecision.EXECUTE_LONG,
            urgency=Urgency.IMMEDIATE,
            target_contracts=10,
            confidence=0.7,
        )
        assert decision.should_execute
        assert decision.side == "long"

    def test_should_execute_short(self):
        """Test execute detection for short."""
        decision = QInlineDecision(
            ticker="KXBTC-15M-DOWN",
            asset="BTC",
            decision=TradeDecision.EXECUTE_SHORT,
            urgency=Urgency.IMMEDIATE,
            target_contracts=10,
            confidence=0.7,
        )
        assert decision.should_execute
        assert decision.side == "short"

    def test_should_not_execute_hold(self):
        """Test no execute for hold."""
        decision = QInlineDecision(
            ticker="KXBTC-15M-UP",
            asset="BTC",
            decision=TradeDecision.HOLD,
            urgency=Urgency.PASS,
            target_contracts=0,
            confidence=0.3,
        )
        assert not decision.should_execute
        assert decision.side is None

    def test_halt_decision_blocked(self):
        """Test halt decision blocks execution."""
        decision = QInlineDecision(
            ticker="KXBTC-15M-UP",
            asset="BTC",
            decision=TradeDecision.HALT,
            urgency=Urgency.PASS,
            target_contracts=0,
            confidence=1.0,
            regime_multiplier=0.0,
        )
        assert not decision.should_execute


class TestQInlineState:
    """Test QInlineState dataclass."""

    def test_composite_signal_calculation(self):
        """Test composite signal weighting."""
        state = QInlineState(
            ticker="KXBTC-15M-UP",
            asset="BTC",
            timestamp=time.time(),
            macro_score=0.5,  # Bullish macro
            momentum_score=0.3,  # Moderate momentum
            btc_anchor_score=0.4,  # Bullish BTC
        )
        
        # Expected: 0.35*0.5 + 0.30*0.3 + 0.35*0.4 = 0.175 + 0.09 + 0.14 = 0.405
        expected = 0.35 * 0.5 + 0.30 * 0.3 + 0.35 * 0.4
        assert abs(state.composite_signal - expected) < 0.001

    def test_composite_signal_negative(self):
        """Test composite signal with bearish inputs."""
        state = QInlineState(
            ticker="KXBTC-15M-DOWN",
            asset="BTC",
            timestamp=time.time(),
            macro_score=-0.5,
            momentum_score=-0.3,
            btc_anchor_score=-0.4,
        )
        
        assert state.composite_signal < 0


class TestQInlinePolicy:
    """Test Q-Inline Policy core functionality."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before each test."""
        reset_qinline_policy()
        yield
        reset_qinline_policy()

    def test_singleton_pattern(self):
        """Test singleton returns same instance."""
        p1 = get_qinline_policy()
        p2 = get_qinline_policy()
        assert p1 is p2

    def test_extract_asset(self):
        """Test asset extraction from ticker."""
        policy = QInlinePolicy()
        
        assert policy._extract_asset("KXBTC-15M-UP") == "BTC"
        assert policy._extract_asset("KXETH-15M-DOWN") == "ETH"
        assert policy._extract_asset("KXSOL-15M-UP") == "SOL"
        assert policy._extract_asset("KXXRP-15M-DOWN") == "XRP"
        assert policy._extract_asset("KXDOGE-15M-UP") == "DOGE"
        assert policy._extract_asset("UNKNOWN") is None

    def test_compute_q_values_bullish(self):
        """Test Q-value computation for bullish state."""
        policy = QInlinePolicy()
        
        state = QInlineState(
            ticker="KXBTC-15M-UP",
            asset="BTC",
            timestamp=time.time(),
            macro_score=0.6,
            momentum_score=0.5,
            btc_anchor_score=0.7,
            execution_regime=ExecutionRegime.NORMAL,
        )
        
        q_values = policy._compute_q_values(state)
        
        assert "long" in q_values
        assert "short" in q_values
        assert "hold" in q_values
        
        # Bullish state should favor long
        assert q_values["long"].value > q_values["short"].value

    def test_compute_q_values_bearish(self):
        """Test Q-value computation for bearish state."""
        policy = QInlinePolicy()
        
        state = QInlineState(
            ticker="KXBTC-15M-DOWN",
            asset="BTC",
            timestamp=time.time(),
            macro_score=-0.6,
            momentum_score=-0.5,
            btc_anchor_score=-0.7,
            execution_regime=ExecutionRegime.NORMAL,
        )
        
        q_values = policy._compute_q_values(state)
        
        # Bearish state should favor short
        assert q_values["short"].value > q_values["long"].value

    def test_compute_q_values_defensive_regime(self):
        """Test Q-values in defensive regime."""
        policy = QInlinePolicy()
        
        state = QInlineState(
            ticker="KXBTC-15M-UP",
            asset="BTC",
            timestamp=time.time(),
            macro_score=0.6,
            momentum_score=0.5,
            btc_anchor_score=0.7,
            execution_regime=ExecutionRegime.DEFENSIVE,
        )
        
        q_values = policy._compute_q_values(state)
        
        # In defensive, confidence should be reduced
        assert q_values["long"].confidence < 0.7  # Reduced from base
        assert q_values["hold"].confidence > 0.3  # Increased

    def test_select_action_strong_signal(self):
        """Test action selection with strong signal."""
        policy = QInlinePolicy()
        
        q_values = {
            "long": QValue("long", value=0.6, confidence=0.8),
            "short": QValue("short", value=-0.2, confidence=0.3),
            "hold": QValue("hold", value=0.0, confidence=0.2),
        }
        
        state = QInlineState(
            ticker="KXBTC-15M-UP",
            asset="BTC",
            timestamp=time.time(),
            execution_regime=ExecutionRegime.NORMAL,
        )
        
        action = policy._select_action(q_values, state)
        assert action == "long"

    def test_select_action_weak_signal(self):
        """Test action selection with weak signal defaults to hold."""
        policy = QInlinePolicy()
        
        q_values = {
            "long": QValue("long", value=0.1, confidence=0.2),  # Below threshold
            "short": QValue("short", value=-0.05, confidence=0.15),
            "hold": QValue("hold", value=0.0, confidence=0.8),
        }
        
        state = QInlineState(
            ticker="KXBTC-15M-UP",
            asset="BTC",
            timestamp=time.time(),
            execution_regime=ExecutionRegime.NORMAL,
        )
        
        action = policy._select_action(q_values, state)
        assert action == "hold"

    def test_select_action_halt_regime(self):
        """Test halt regime forces hold."""
        policy = QInlinePolicy()
        
        q_values = {
            "long": QValue("long", value=0.9, confidence=0.95),
            "short": QValue("short", value=-0.1, confidence=0.2),
            "hold": QValue("hold", value=0.0, confidence=0.5),
        }
        
        state = QInlineState(
            ticker="KXBTC-15M-UP",
            asset="BTC",
            timestamp=time.time(),
            execution_regime=ExecutionRegime.HALT,
        )
        
        action = policy._select_action(q_values, state)
        assert action == "hold"

    def test_compute_position_size(self):
        """Test position size computation."""
        policy = QInlinePolicy()
        
        state = QInlineState(
            ticker="KXBTC-15M-UP",
            asset="BTC",
            timestamp=time.time(),
            macro_score=0.8,
            momentum_score=0.7,
            btc_anchor_score=0.9,
            remaining_risk_budget_pct=1.0,
        )
        
        size = policy._compute_position_size(state, "long")
        
        # Should be proportional to signal strength
        assert size > policy.MIN_CONTRACTS_PER_TRADE
        assert size <= policy.MAX_CONTRACTS_PER_TRADE

    def test_compute_position_size_risk_budget(self):
        """Test position size scales with risk budget."""
        policy = QInlinePolicy()
        
        # Full risk budget
        state_full = QInlineState(
            ticker="KXBTC-15M-UP",
            asset="BTC",
            timestamp=time.time(),
            macro_score=0.8,
            remaining_risk_budget_pct=1.0,
        )
        size_full = policy._compute_position_size(state_full, "long")
        
        # Low risk budget
        state_low = QInlineState(
            ticker="KXBTC-15M-UP",
            asset="BTC",
            timestamp=time.time(),
            macro_score=0.8,
            remaining_risk_budget_pct=0.2,
        )
        size_low = policy._compute_position_size(state_low, "long")
        
        assert size_low < size_full

    def test_determine_urgency_immediate(self):
        """Test immediate urgency for strong signal."""
        policy = QInlinePolicy()
        
        state = QInlineState(
            ticker="KXBTC-15M-UP",
            asset="BTC",
            timestamp=time.time(),
            macro_score=0.9,
            momentum_score=0.8,
            btc_anchor_score=0.9,
        )
        # Composite should be > STRONG_SIGNAL_THRESHOLD (0.4)
        
        urgency = policy._determine_urgency(state, TradeDecision.EXECUTE_LONG)
        assert urgency == Urgency.IMMEDIATE

    def test_determine_urgency_pass(self):
        """Test pass urgency for hold decision."""
        policy = QInlinePolicy()
        
        state = QInlineState(
            ticker="KXBTC-15M-UP",
            asset="BTC",
            timestamp=time.time(),
        )
        
        urgency = policy._determine_urgency(state, TradeDecision.HOLD)
        assert urgency == Urgency.PASS

    def test_make_halt_decision(self):
        """Test halt decision creation."""
        policy = QInlinePolicy()
        
        state = QInlineState(
            ticker="KXBTC-15M-UP",
            asset="BTC",
            timestamp=time.time(),
            execution_regime=ExecutionRegime.HALT,
        )
        
        decision = policy._make_halt_decision("KXBTC-15M-UP", "BTC", state)
        
        assert decision.decision == TradeDecision.HALT
        assert decision.target_contracts == 0
        assert decision.regime_multiplier == 0.0
        assert not decision.should_execute

    def test_callback_registration(self):
        """Test callback registration."""
        policy = QInlinePolicy()
        callback_calls = []
        
        def callback(decision: QInlineDecision):
            callback_calls.append(decision.ticker)
        
        policy.register_callback(callback)
        
        # Manually trigger a decision to test callback
        state = QInlineState(
            ticker="KXBTC-15M-UP",
            asset="BTC",
            timestamp=time.time(),
            execution_regime=ExecutionRegime.NORMAL,
        )
        q_values = policy._compute_q_values(state)
        action = policy._select_action(q_values, state)
        decision = policy._build_decision("KXBTC-15M-UP", "BTC", state, action, q_values)
        
        # Notify callbacks manually (normally done in evaluate)
        for cb in policy._callbacks:
            cb(decision)
        
        assert len(callback_calls) == 1
        assert callback_calls[0] == "KXBTC-15M-UP"

    def test_get_decision_history(self):
        """Test decision history retrieval."""
        policy = QInlinePolicy()
        
        # Add some mock decisions to history
        now = time.time()
        policy._decision_history.append(QInlineDecision(
            ticker="KXBTC-15M-UP",
            asset="BTC",
            decision=TradeDecision.EXECUTE_LONG,
            urgency=Urgency.IMMEDIATE,
            target_contracts=10,
            confidence=0.7,
            timestamp=now - 100,
        ))
        policy._decision_history.append(QInlineDecision(
            ticker="KXETH-15M-UP",
            asset="ETH",
            decision=TradeDecision.HOLD,
            urgency=Urgency.PASS,
            target_contracts=0,
            confidence=0.3,
            timestamp=now - 50,
        ))
        
        # Get all history
        all_history = policy.get_decision_history()
        assert len(all_history) == 2
        
        # Filter by ticker
        btc_history = policy.get_decision_history(ticker="KXBTC-15M-UP")
        assert len(btc_history) == 1
        assert btc_history[0].ticker == "KXBTC-15M-UP"
        
        # Filter by time
        recent_history = policy.get_decision_history(since=now - 60)
        assert len(recent_history) == 1

    def test_reset_clears_state(self):
        """Test reset clears all state."""
        policy = QInlinePolicy()
        
        policy._decision_history.append(QInlineDecision(
            ticker="KXBTC-15M-UP",
            asset="BTC",
            decision=TradeDecision.EXECUTE_LONG,
            urgency=Urgency.IMMEDIATE,
            target_contracts=10,
            confidence=0.7,
        ))
        
        def dummy_callback(d): pass
        policy.register_callback(dummy_callback)
        
        policy.reset()
        
        assert len(policy._decision_history) == 0
        assert len(policy._callbacks) == 0

    def test_position_size_limits(self):
        """Test position size respects min/max limits."""
        policy = QInlinePolicy()
        
        # Very strong signal should hit max
        state_strong = QInlineState(
            ticker="KXBTC-15M-UP",
            asset="BTC",
            timestamp=time.time(),
            macro_score=1.0,
            momentum_score=1.0,
            btc_anchor_score=1.0,
            remaining_risk_budget_pct=1.0,
        )
        size_strong = policy._compute_position_size(state_strong, "long")
        assert size_strong <= policy.MAX_CONTRACTS_PER_TRADE
        
        # Very weak signal should hit min
        state_weak = QInlineState(
            ticker="KXBTC-15M-UP",
            asset="BTC",
            timestamp=time.time(),
            macro_score=0.1,
            momentum_score=0.1,
            btc_anchor_score=0.1,
            remaining_risk_budget_pct=1.0,
        )
        size_weak = policy._compute_position_size(state_weak, "long")
        assert size_weak >= policy.MIN_CONTRACTS_PER_TRADE

    def test_inventory_skew_affects_q_values(self):
        """Test inventory skew reduces attractiveness of adding to position."""
        policy = QInlinePolicy()
        
        # Long inventory should reduce long Q-value
        state_long_inv = QInlineState(
            ticker="KXBTC-15M-UP",
            asset="BTC",
            timestamp=time.time(),
            macro_score=0.5,
            inventory_skew=0.5,  # Already long
        )
        
        q_values = policy._compute_q_values(state_long_inv)
        
        # Long inventory should reduce long value
        assert q_values["long"].value < state_long_inv.macro_score * 0.35

    def test_risk_budget_affects_q_values(self):
        """Test low risk budget increases hold attractiveness."""
        policy = QInlinePolicy()
        
        state_low_budget = QInlineState(
            ticker="KXBTC-15M-UP",
            asset="BTC",
            timestamp=time.time(),
            macro_score=0.6,
            remaining_risk_budget_pct=0.1,  # Low budget
        )
        
        q_values = policy._compute_q_values(state_low_budget)
        
        # Low budget should reduce directional confidence
        assert q_values["long"].confidence < 0.6
        assert q_values["hold"].confidence > 0.4
