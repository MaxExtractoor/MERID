"""Tests for Unified Volatility & Regime Classifier.

Validates:
- Integration of macro, momentum, and BTC signals
- Volatility regime classification
- Execution regime determination
- Transition detection and callbacks
- Execution parameter derivation
"""

import time
import pytest
from typing import List

from merid.signals.unified_regime_classifier import (
    UnifiedRegimeClassifier,
    UnifiedRegimeState,
    ExecutionRegime,
    VolatilityRegime,
    RegimeTransition,
    get_unified_regime_classifier,
    reset_unified_regime_classifier,
)
from merid.kalshi.macro_models import MacroState, MacroRegime, VolatilityRegime as MacroVolRegime
from merid.signals.momentum_ranker import MomentumRankings, AssetMomentum
from merid.signals.btc_anchor_gate import BtcRegimeState, BtcRegime


class TestUnifiedRegimeState:
    """Test UnifiedRegimeState dataclass."""

    def test_is_aggressive(self):
        """Test aggressive regime detection."""
        state = UnifiedRegimeState(
            timestamp=time.time(),
            execution_regime=ExecutionRegime.AGGRESSIVE,
            position_size_multiplier=1.3,
        )
        assert state.is_aggressive
        assert not state.is_defensive
        assert not state.is_halted

    def test_is_defensive(self):
        """Test defensive regime detection."""
        state = UnifiedRegimeState(
            timestamp=time.time(),
            execution_regime=ExecutionRegime.DEFENSIVE,
            position_size_multiplier=0.6,
        )
        assert state.is_defensive
        assert not state.is_aggressive
        assert not state.is_halted

    def test_is_halted(self):
        """Test halt regime detection."""
        state = UnifiedRegimeState(
            timestamp=time.time(),
            execution_regime=ExecutionRegime.HALT,
            position_size_multiplier=0.0,
        )
        assert state.is_halted
        assert not state.is_aggressive
        assert not state.is_defensive

    def test_is_crisis(self):
        """Test crisis volatility detection."""
        state = UnifiedRegimeState(
            timestamp=time.time(),
            volatility_regime=VolatilityRegime.CRISIS,
        )
        assert state.is_crisis


class TestUnifiedRegimeClassifier:
    """Test unified classifier core functionality."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before each test."""
        reset_unified_regime_classifier()
        yield
        reset_unified_regime_classifier()

    def test_singleton_pattern(self):
        """Test singleton returns same instance."""
        c1 = get_unified_regime_classifier()
        c2 = get_unified_regime_classifier()
        assert c1 is c2

    def test_initial_state_none(self):
        """Test initial state is None."""
        classifier = UnifiedRegimeClassifier()
        assert classifier.get_current_state() is None

    def test_update_returns_state(self):
        """Test update returns valid state."""
        classifier = UnifiedRegimeClassifier()
        state = classifier.update()

        assert state is not None
        assert isinstance(state.execution_regime, ExecutionRegime)
        assert isinstance(state.volatility_regime, VolatilityRegime)
        assert state.timestamp > 0

    def test_compute_vol_regime_crisis(self):
        """Test crisis volatility detection."""
        classifier = UnifiedRegimeClassifier()

        # Create macro state with elevated vol
        macro = MacroState(
            timestamp=time.time(),
            macro_regime=MacroRegime.RISK_OFF,
            vol_regime=MacroVolRegime.ELEVATED,
        )

        vol_regime = classifier._compute_vol_regime(macro, None, None)
        assert vol_regime in [VolatilityRegime.ELEVATED, VolatilityRegime.CRISIS]

    def test_compute_vol_regime_compressed(self):
        """Test compressed volatility detection."""
        classifier = UnifiedRegimeClassifier()

        macro = MacroState(
            timestamp=time.time(),
            macro_regime=MacroRegime.NEUTRAL,
            vol_regime=MacroVolRegime.CONTRACTING,
        )

        vol_regime = classifier._compute_vol_regime(macro, None, None)
        assert vol_regime == VolatilityRegime.COMPRESSED

    def test_compute_execution_regime_crisis(self):
        """Test crisis -> halt execution regime."""
        classifier = UnifiedRegimeClassifier()

        state = UnifiedRegimeState(
            timestamp=time.time(),
            volatility_regime=VolatilityRegime.CRISIS,
        )

        regime = classifier._compute_execution_regime(state)
        assert regime == ExecutionRegime.HALT

    def test_compute_execution_regime_aggressive(self):
        """Test aggressive execution regime conditions."""
        classifier = UnifiedRegimeClassifier()

        state = UnifiedRegimeState(
            timestamp=time.time(),
            btc_trending=True,
            macro_conviction_avg=0.7,
            momentum_avg_score=0.4,
            volatility_regime=VolatilityRegime.NORMAL,
        )

        regime = classifier._compute_execution_regime(state)
        assert regime == ExecutionRegime.AGGRESSIVE

    def test_compute_execution_regime_defensive(self):
        """Test defensive execution regime conditions."""
        classifier = UnifiedRegimeClassifier()

        state = UnifiedRegimeState(
            timestamp=time.time(),
            volatility_regime=VolatilityRegime.ELEVATED,
            macro_event_risk=0.7,
        )

        regime = classifier._compute_execution_regime(state)
        assert regime == ExecutionRegime.DEFENSIVE

    def test_execution_parameters_aggressive(self):
        """Test aggressive execution parameters."""
        classifier = UnifiedRegimeClassifier()

        state = UnifiedRegimeState(
            timestamp=time.time(),
            execution_regime=ExecutionRegime.AGGRESSIVE,
        )

        # Update with computed parameters
        state.position_size_multiplier = classifier.SIZE_MULTIPLIERS[ExecutionRegime.AGGRESSIVE]
        state.edge_threshold_multiplier = classifier.EDGE_MULTIPLIERS[ExecutionRegime.AGGRESSIVE]

        assert state.position_size_multiplier > 1.0
        assert state.edge_threshold_multiplier < 1.0  # Lower threshold

    def test_execution_parameters_defensive(self):
        """Test defensive execution parameters."""
        classifier = UnifiedRegimeClassifier()

        state = UnifiedRegimeState(
            timestamp=time.time(),
            execution_regime=ExecutionRegime.DEFENSIVE,
        )

        state.position_size_multiplier = classifier.SIZE_MULTIPLIERS[ExecutionRegime.DEFENSIVE]
        state.stop_tightening_factor = 0.7
        state.daily_loss_limit_multiplier = 0.6

        assert state.position_size_multiplier < 1.0
        assert state.stop_tightening_factor < 1.0
        assert state.daily_loss_limit_multiplier < 1.0

    def test_execution_parameters_halt(self):
        """Test halt execution parameters."""
        classifier = UnifiedRegimeClassifier()

        state = UnifiedRegimeState(
            timestamp=time.time(),
            execution_regime=ExecutionRegime.HALT,
        )

        state.position_size_multiplier = classifier.SIZE_MULTIPLIERS[ExecutionRegime.HALT]
        state.max_positions_override = 0

        assert state.position_size_multiplier == 0.0
        assert state.max_positions_override == 0

    def test_transition_detection(self):
        """Test regime transition detection."""
        classifier = UnifiedRegimeClassifier()

        old = UnifiedRegimeState(
            timestamp=time.time(),
            execution_regime=ExecutionRegime.NORMAL,
        )
        new = UnifiedRegimeState(
            timestamp=time.time(),
            execution_regime=ExecutionRegime.DEFENSIVE,
        )

        classifier._handle_transition(old, new)

        transitions = classifier.get_transitions()
        assert len(transitions) == 1
        assert transitions[0].from_regime == ExecutionRegime.NORMAL
        assert transitions[0].to_regime == ExecutionRegime.DEFENSIVE

    def test_transition_cooldown(self):
        """Test transition cooldown prevents rapid flipping."""
        classifier = UnifiedRegimeClassifier()
        classifier._transition_cooldown = 300.0  # 5 min cooldown

        old = UnifiedRegimeState(
            timestamp=time.time(),
            execution_regime=ExecutionRegime.NORMAL,
        )
        new = UnifiedRegimeState(
            timestamp=time.time(),
            execution_regime=ExecutionRegime.DEFENSIVE,
        )

        # First transition should record
        classifier._handle_transition(old, new)
        assert len(classifier._transitions) == 1

        # Immediate second transition should be suppressed
        classifier._handle_transition(new, old)
        assert len(classifier._transitions) == 1  # No new transition

    def test_transition_severity_classification(self):
        """Test transition severity classification."""
        classifier = UnifiedRegimeClassifier()

        # Aggressive -> Defensive = major
        severity = classifier._transition_severity(
            ExecutionRegime.AGGRESSIVE, ExecutionRegime.DEFENSIVE
        )
        assert severity == "major"

        # Normal -> Defensive = minor
        severity = classifier._transition_severity(
            ExecutionRegime.NORMAL, ExecutionRegime.DEFENSIVE
        )
        assert severity == "minor"

        # Anything -> Halt = critical
        severity = classifier._transition_severity(
            ExecutionRegime.AGGRESSIVE, ExecutionRegime.HALT
        )
        assert severity == "critical"

    def test_callback_registration(self):
        """Test callback registration and invocation."""
        classifier = UnifiedRegimeClassifier()
        callback_calls = []

        def callback(old: UnifiedRegimeState, new: UnifiedRegimeState):
            callback_calls.append((old.execution_regime, new.execution_regime))

        classifier.register_callback(callback)

        old = UnifiedRegimeState(
            timestamp=time.time(),
            execution_regime=ExecutionRegime.NORMAL,
        )
        new = UnifiedRegimeState(
            timestamp=time.time(),
            execution_regime=ExecutionRegime.DEFENSIVE,
        )

        # Override cooldown for test
        classifier._last_transition = 0
        classifier._handle_transition(old, new)

        assert len(callback_calls) == 1
        assert callback_calls[0] == (ExecutionRegime.NORMAL, ExecutionRegime.DEFENSIVE)

    def test_freshness_check(self):
        """Test freshness detection."""
        classifier = UnifiedRegimeClassifier()

        # Initially not fresh
        assert not classifier.is_fresh()

        # After update
        classifier.update()
        assert classifier.is_fresh(max_age_seconds=300)

    def test_get_transitions_filtered(self):
        """Test filtered transition retrieval."""
        classifier = UnifiedRegimeClassifier()

        # Add transitions at different times
        now = time.time()
        classifier._transitions = [
            RegimeTransition(now - 100, ExecutionRegime.NORMAL, ExecutionRegime.DEFENSIVE, "test", "minor"),
            RegimeTransition(now - 50, ExecutionRegime.DEFENSIVE, ExecutionRegime.NORMAL, "test", "minor"),
            RegimeTransition(now - 10, ExecutionRegime.NORMAL, ExecutionRegime.AGGRESSIVE, "test", "minor"),
        ]

        # Get all since 60 seconds ago
        recent = classifier.get_transitions(since=now - 60)
        assert len(recent) == 2

    def test_reset_clears_state(self):
        """Test reset clears all state."""
        classifier = UnifiedRegimeClassifier()

        classifier.update()
        classifier.reset()

        assert classifier.get_current_state() is None
        assert len(classifier._transitions) == 0
        assert len(classifier._regime_history) == 0

    def test_confidence_calculation(self):
        """Test confidence based on signal count."""
        classifier = UnifiedRegimeClassifier()

        # Simulate update with partial signals
        state = classifier._compute_state(None, None, None)
        assert state.signal_count == 0
        assert state.confidence == 0.0

        macro = MacroState(timestamp=time.time(), macro_regime=MacroRegime.NEUTRAL)
        state = classifier._compute_state(macro, None, None)
        assert state.signal_count == 1
        assert state.confidence == pytest.approx(0.33, abs=0.01)

    def test_full_integration_compute_state(self):
        """Test state computation with all signal sources."""
        classifier = UnifiedRegimeClassifier()

        # Create realistic signal states
        macro = MacroState(
            timestamp=time.time(),
            macro_regime=MacroRegime.RISK_ON,
            vol_regime=MacroVolRegime.CONTRACTING,
            event_risk_score=0.2,
        )

        momentum = MomentumRankings(
            timestamp=time.time(),
            assets={
                "BTC": AssetMomentum("BTC", time.time(), composite_score=0.3),
                "ETH": AssetMomentum("ETH", time.time(), composite_score=0.2),
            },
            ranked_assets=["BTC", "ETH"],
            dispersion=0.05,
        )

        btc = BtcRegimeState(
            regime=BtcRegime.STRONG_BULL,
            timestamp=time.time(),
            adx=30.0,
            slope_15m=0.001,
            atr_pct=2.0,
        )

        state = classifier._compute_state(macro, momentum, btc)

        assert state.signal_count == 3
        assert state.macro_regime == "risk_on"
        assert state.btc_regime == "strong_bull"
        assert state.momentum_leader == "BTC"
        assert state.confidence == 1.0
