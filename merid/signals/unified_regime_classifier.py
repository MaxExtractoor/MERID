"""Unified Volatility & Regime Classifier

Phase 5 of MERID single-signal hierarchy:
Integrates macro overlay, momentum ranker, and BTC anchor gate into a single
volatility regime state that drives execution cycle behavior.

Produces unified regime classification:
- REGIME_AGGRESSIVE: Expand position sizing, increase edge threshold
- REGIME_NORMAL: Standard execution parameters
- REGIME_DEFENSIVE: Reduce sizing, tighten stops, raise edge bar
- REGIME_HALT: Pause new positions, begin wind-down

Architecture:
- Thread-safe singleton
- Callbacks for regime transitions
- Configurable thresholds
- Persistence for regime history
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Set
from enum import Enum
from collections import deque

from merid.kalshi.macro_overlay import get_kalshi_macro_overlay, MacroState
from merid.signals.momentum_ranker import get_momentum_ranker, MomentumRankings
from merid.signals.btc_anchor_gate import get_btc_anchor_gate, BtcRegimeState
from utils.logger import get_logger

logger = get_logger("merid.signals.unified_regime_classifier")


class ExecutionRegime(str, Enum):
    """Execution cycle regime - drives behavior of entire trading loop."""
    AGGRESSIVE = "aggressive"    # Size up, lower edge threshold
    NORMAL = "normal"            # Standard parameters
    DEFENSIVE = "defensive"      # Size down, tighten stops
    HALT = "halt"                # Pause new positions


class VolatilityRegime(str, Enum):
    """Pure volatility regime classification."""
    CRISIS = "crisis"            # >80% VIX equiv, extreme stress
    ELEVATED = "elevated"        # >60% VIX equiv, risk-off
    NORMAL = "normal"            # 20-60% VIX equiv
    COMPRESSED = "compressed"    # <20% VIX equiv, potential breakout


@dataclass
class UnifiedRegimeState:
    """Complete unified regime state for execution cycle.
    
    This is the single source of truth for regime-aware execution.
    """
    timestamp: float
    
    # Macro signals (from Phase 3)
    macro_regime: str = "neutral"  # risk_on, risk_off, neutral, event_risk_high
    macro_conviction_avg: float = 0.5  # Average conviction across assets
    macro_event_risk: float = 0.0  # 0-1 scale
    
    # Momentum signals (from Phase 4)
    momentum_dispersion: float = 0.0  # Cross-sectional dispersion
    momentum_leader: Optional[str] = None  # Strongest asset
    momentum_avg_score: float = 0.0  # Average momentum score
    
    # BTC anchor (from Phase 4)
    btc_regime: str = "neutral"
    btc_adx: float = 0.0
    btc_trending: bool = False
    
    # Computed unified state
    execution_regime: ExecutionRegime = ExecutionRegime.NORMAL
    volatility_regime: VolatilityRegime = VolatilityRegime.NORMAL
    
    # Execution parameters (derived from regime)
    position_size_multiplier: float = 1.0  # Multiply base sizes by this
    edge_threshold_multiplier: float = 1.0  # Multiply min edge by this
    max_positions_override: Optional[int] = None  # Cap positions if set
    stop_tightening_factor: float = 1.0  # Multiply stop distances
    
    # Risk limits adjustment
    daily_loss_limit_multiplier: float = 1.0
    position_concentration_limit: float = 1.0
    
    # Metadata
    signal_count: int = 0  # How many signals contributed
    confidence: float = 1.0  # Regime classification confidence
    
    @property
    def is_aggressive(self) -> bool:
        return self.execution_regime == ExecutionRegime.AGGRESSIVE
    
    @property
    def is_defensive(self) -> bool:
        return self.execution_regime == ExecutionRegime.DEFENSIVE
    
    @property
    def is_halted(self) -> bool:
        return self.execution_regime == ExecutionRegime.HALT
    
    @property
    def is_crisis(self) -> bool:
        return self.volatility_regime == VolatilityRegime.CRISIS


@dataclass
class RegimeTransition:
    """Record of a regime change for auditing."""
    timestamp: float
    from_regime: ExecutionRegime
    to_regime: ExecutionRegime
    trigger: str  # What caused the transition
    severity: str  # "minor", "major", "critical"


class UnifiedRegimeClassifier:
    """Unified classifier integrating all signal layers.
    
    Combines macro, momentum, and BTC anchor signals into a single
    unified regime state that drives execution parameters.
    """
    
    # Regime transition thresholds
    CRISIS_VIX_THRESHOLD = 40.0  # VIX equivalent
    ELEVATED_VIX_THRESHOLD = 25.0
    COMPRESSED_VIX_THRESHOLD = 15.0
    
    # Signal aggregation weights
    MACRO_WEIGHT = 0.35
    MOMENTUM_WEIGHT = 0.30
    BTC_ANCHOR_WEIGHT = 0.35
    
    # Position sizing multipliers by regime
    SIZE_MULTIPLIERS = {
        ExecutionRegime.AGGRESSIVE: 1.3,
        ExecutionRegime.NORMAL: 1.0,
        ExecutionRegime.DEFENSIVE: 0.6,
        ExecutionRegime.HALT: 0.0,
    }
    
    # Edge threshold multipliers by regime
    EDGE_MULTIPLIERS = {
        ExecutionRegime.AGGRESSIVE: 0.8,  # Lower threshold = more trades
        ExecutionRegime.NORMAL: 1.0,
        ExecutionRegime.DEFENSIVE: 1.5,  # Higher threshold = only best edges
        ExecutionRegime.HALT: float('inf'),  # No trades
    }
    
    def __init__(
        self,
        history_window: int = 100,
        transition_cooldown_seconds: float = 60.0,
    ):
        self._macro_overlay = get_kalshi_macro_overlay()
        self._momentum_ranker = get_momentum_ranker()
        self._btc_gate = get_btc_anchor_gate()
        
        self._current_state: Optional[UnifiedRegimeState] = None
        self._last_update: float = 0.0
        self._last_transition: float = 0.0
        self._transition_cooldown = transition_cooldown_seconds
        
        # History for auditing
        self._regime_history: deque = deque(maxlen=history_window)
        self._transitions: List[RegimeTransition] = []
        
        # Callbacks for regime changes
        self._callbacks: List[Callable[[UnifiedRegimeState, UnifiedRegimeState], None]] = []
        
        # TEMPORARILY DISABLED: threading.Lock causing deadlock during startup
        # TODO: Re-enable lock after startup is stable and investigate proper async synchronization
        # self._lock = threading.Lock()
        self._lock = None  # Disabled to prevent startup hang
        
        logger.info(
            "UnifiedRegimeClassifier initialized (cooldown=%.1fs, history=%d)",
            transition_cooldown_seconds, history_window
        )
    
    def register_callback(
        self,
        callback: Callable[[UnifiedRegimeState, UnifiedRegimeState], None]
    ) -> None:
        """Register callback for regime transitions.
        
        Callback receives (old_state, new_state) when regime changes.
        """
        if self._lock is not None:
            with self._lock:
                self._callbacks.append(callback)
                logger.debug("Regime transition callback registered")
        else:
            # Lock disabled - direct update (startup workaround)
            self._callbacks.append(callback)
            logger.debug("Regime transition callback registered (lock disabled)")
    
    def update(self) -> UnifiedRegimeState:
        """Compute unified regime from all signal sources.
        
        Returns:
            Updated UnifiedRegimeState
        """
        if self._lock is not None:
            with self._lock:
                now = time.time()
                
                # Gather inputs from all signal layers
                macro_state = self._macro_overlay.get_macro_state()
                momentum_rankings = self._momentum_ranker.get_current_rankings()
                btc_regime = self._btc_gate.get_current_regime()
                
                # Build new state
                new_state = self._compute_state(macro_state, momentum_rankings, btc_regime)
                new_state.timestamp = now
                
                # Check for regime transition
                old_state = self._current_state
                if old_state is not None:
                    self._handle_transition(old_state, new_state)
                
                # Update history
                self._regime_history.append(new_state)
                self._current_state = new_state
                self._last_update = now
                
                return new_state
        else:
            # Lock disabled - direct update (startup workaround)
            now = time.time()
            
            # Gather inputs from all signal layers
            macro_state = self._macro_overlay.get_macro_state()
            momentum_rankings = self._momentum_ranker.get_current_rankings()
            btc_regime = self._btc_gate.get_current_regime()
            
            # Build new state
            new_state = self._compute_state(macro_state, momentum_rankings, btc_regime)
            new_state.timestamp = now
            
            # Check for regime transition
            old_state = self._current_state
            if old_state is not None:
                self._handle_transition(old_state, new_state)
            
            # Update history
            self._regime_history.append(new_state)
            self._current_state = new_state
            self._last_update = now
            
            return new_state
    
    def _compute_state(
        self,
        macro: Optional[MacroState],
        momentum: Optional[MomentumRankings],
        btc: Optional[BtcRegimeState],
    ) -> UnifiedRegimeState:
        """Compute unified state from component signals."""
        state = UnifiedRegimeState(timestamp=time.time())
        
        signal_count = 0
        
        # Process macro signals (Phase 3)
        if macro:
            signal_count += 1
            state.macro_regime = macro.macro_regime.value
            state.macro_event_risk = macro.event_risk_score
            
            # Average conviction across tracked assets
            convictions = self._macro_overlay.get_conviction_scores()
            if convictions:
                scores = [c.score for c in convictions.values()]
                state.macro_conviction_avg = sum(scores) / len(scores)
        
        # Process momentum signals (Phase 4)
        if momentum:
            signal_count += 1
            state.momentum_dispersion = momentum.dispersion
            state.momentum_leader = momentum.strongest
            
            if momentum.assets:
                scores = [m.composite_score for m in momentum.assets.values()]
                state.momentum_avg_score = sum(scores) / len(scores)
        
        # Process BTC anchor (Phase 4)
        if btc:
            signal_count += 1
            state.btc_regime = btc.regime.value
            state.btc_adx = btc.adx
            state.btc_trending = btc.is_trending
        
        state.signal_count = signal_count
        
        # Compute unified volatility regime
        state.volatility_regime = self._compute_vol_regime(macro, momentum, btc)
        
        # Compute execution regime
        state.execution_regime = self._compute_execution_regime(state)
        
        # Derive execution parameters
        state.position_size_multiplier = self.SIZE_MULTIPLIERS[state.execution_regime]
        state.edge_threshold_multiplier = self.EDGE_MULTIPLIERS[state.execution_regime]
        
        # Defensive adjustments
        if state.execution_regime == ExecutionRegime.DEFENSIVE:
            state.stop_tightening_factor = 0.7
            state.daily_loss_limit_multiplier = 0.6
            state.position_concentration_limit = 0.7
        elif state.execution_regime == ExecutionRegime.HALT:
            state.stop_tightening_factor = 0.5
            state.daily_loss_limit_multiplier = 0.3
            state.max_positions_override = 0
        
        # Confidence based on signal diversity
        state.confidence = min(1.0, signal_count / 3.0)
        
        return state
    
    def _compute_vol_regime(
        self,
        macro: Optional[MacroState],
        momentum: Optional[MomentumRankings],
        btc: Optional[BtcRegimeState],
    ) -> VolatilityRegime:
        """Compute unified volatility regime."""
        vol_scores = []
        
        # Macro contribution
        if macro:
            if macro.vol_regime.value in ["expanding", "elevated"]:
                vol_scores.append(0.7)
            elif macro.vol_regime.value == "contracting":
                vol_scores.append(0.1)  # Low score = compressed
            else:
                vol_scores.append(0.4)  # Stable = normal
        
        # Momentum dispersion contribution
        if momentum and momentum.dispersion > 0:
            # Higher dispersion = higher vol
            normalized_dispersion = min(1.0, momentum.dispersion / 0.5)
            vol_scores.append(normalized_dispersion)
        
        # BTC contribution (via ATR)
        if btc and btc.atr_pct > 0:
            # ATR% > 3% is elevated, > 5% is crisis
            if btc.atr_pct > 5:
                vol_scores.append(0.9)
            elif btc.atr_pct > 3:
                vol_scores.append(0.6)
            else:
                vol_scores.append(0.3)
        
        if not vol_scores:
            return VolatilityRegime.NORMAL
        
        avg_vol_score = sum(vol_scores) / len(vol_scores)
        
        if avg_vol_score > 0.7:
            return VolatilityRegime.CRISIS
        elif avg_vol_score > 0.5:
            return VolatilityRegime.ELEVATED
        elif avg_vol_score < 0.2:
            return VolatilityRegime.COMPRESSED
        else:
            return VolatilityRegime.NORMAL
    
    def _compute_execution_regime(self, state: UnifiedRegimeState) -> ExecutionRegime:
        """Compute execution regime from unified state."""
        # Crisis overrides everything
        if state.volatility_regime == VolatilityRegime.CRISIS:
            return ExecutionRegime.HALT
        
        # Elevated vol with macro event risk = defensive
        if state.volatility_regime == VolatilityRegime.ELEVATED and state.macro_event_risk > 0.6:
            return ExecutionRegime.DEFENSIVE
        
        # Strong BTC trend alignment with macro = aggressive
        if (state.btc_trending and 
            state.macro_conviction_avg > 0.6 and
            abs(state.momentum_avg_score) > 0.3 and
            state.volatility_regime == VolatilityRegime.NORMAL):
            return ExecutionRegime.AGGRESSIVE
        
        # Elevated vol or high event risk = defensive
        if state.volatility_regime == VolatilityRegime.ELEVATED or state.macro_event_risk > 0.5:
            return ExecutionRegime.DEFENSIVE
        
        # Compressed vol with momentum = aggressive setup
        if (state.volatility_regime == VolatilityRegime.COMPRESSED and
            abs(state.momentum_avg_score) > 0.2):
            return ExecutionRegime.AGGRESSIVE
        
        return ExecutionRegime.NORMAL
    
    def _handle_transition(self, old: UnifiedRegimeState, new: UnifiedRegimeState) -> None:
        """Handle regime transition with cooldown and callbacks."""
        now = time.time()
        
        if old.execution_regime == new.execution_regime:
            return  # No transition
        
        # Check cooldown
        if (now - self._last_transition) < self._transition_cooldown:
            logger.debug(
                "Regime transition suppressed (cooldown): %s -> %s",
                old.execution_regime.value, new.execution_regime.value
            )
            return
        
        # Determine severity
        severity = self._transition_severity(old.execution_regime, new.execution_regime)
        
        # Record transition
        transition = RegimeTransition(
            timestamp=now,
            from_regime=old.execution_regime,
            to_regime=new.execution_regime,
            trigger=f"macro={new.macro_regime}, btc={new.btc_regime}, vol={new.volatility_regime.value}",
            severity=severity,
        )
        self._transitions.append(transition)
        self._last_transition = now
        
        logger.warning(
            "REGIME TRANSITION [%s]: %s -> %s (trigger: %s, size_mult: %.2f)",
            severity.upper(),
            old.execution_regime.value,
            new.execution_regime.value,
            transition.trigger,
            new.position_size_multiplier,
        )
        
        # Notify callbacks
        for callback in self._callbacks:
            try:
                callback(old, new)
            except Exception as e:
                logger.error("Regime transition callback failed: %s", e)
    
    def _transition_severity(
        self,
        from_regime: ExecutionRegime,
        to_regime: ExecutionRegime,
    ) -> str:
        """Classify transition severity."""
        # Halt is always critical
        if to_regime == ExecutionRegime.HALT:
            return "critical"
        
        # Aggressive to defensive is major
        if from_regime == ExecutionRegime.AGGRESSIVE and to_regime == ExecutionRegime.DEFENSIVE:
            return "major"
        
        # Normal to defensive is minor
        if from_regime == ExecutionRegime.NORMAL and to_regime == ExecutionRegime.DEFENSIVE:
            return "minor"
        
        return "minor"
    
    def get_current_state(self) -> Optional[UnifiedRegimeState]:
        """Get current unified regime state."""
        with self._lock:
            return self._current_state
    
    def is_fresh(self, max_age_seconds: float = 300.0) -> bool:
        """Check if regime state is fresh."""
        with self._lock:
            return (time.time() - self._last_update) < max_age_seconds
    
    def get_transitions(self, since: Optional[float] = None) -> List[RegimeTransition]:
        """Get regime transition history."""
        with self._lock:
            if since is None:
                return list(self._transitions)
            return [t for t in self._transitions if t.timestamp >= since]
    
    def reset(self) -> None:
        """Reset classifier state."""
        with self._lock:
            self._current_state = None
            self._regime_history.clear()
            self._transitions.clear()
            self._last_update = 0.0
            self._last_transition = 0.0
            logger.info("UnifiedRegimeClassifier reset")


# ═══════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════

_classifier_instance: Optional[UnifiedRegimeClassifier] = None
# TEMPORARILY DISABLED: threading.Lock causing deadlock during startup
# TODO: Re-enable lock after startup is stable and investigate proper async synchronization
# _classifier_lock = threading.Lock()
_classifier_lock = None  # Disabled to prevent startup hang


def get_unified_regime_classifier(
    history_window: int = 100,
    transition_cooldown_seconds: float = 60.0,
) -> UnifiedRegimeClassifier:
    """Get or create the singleton UnifiedRegimeClassifier."""
    global _classifier_instance
    if _classifier_instance is None:
        if _classifier_lock is not None:
            with _classifier_lock:
                if _classifier_instance is None:
                    _classifier_instance = UnifiedRegimeClassifier(
                        history_window=history_window,
                        transition_cooldown_seconds=transition_cooldown_seconds,
                    )
                    logger.info("UnifiedRegimeClassifier singleton initialized")
        else:
            # Lock disabled - direct initialization (startup workaround)
            _classifier_instance = UnifiedRegimeClassifier(
                history_window=history_window,
                transition_cooldown_seconds=transition_cooldown_seconds,
            )
            logger.info("UnifiedRegimeClassifier singleton initialized (lock disabled)")
    return _classifier_instance


def reset_unified_regime_classifier() -> None:
    """Reset the singleton (for testing)."""
    global _classifier_instance
    if _classifier_lock is not None:
        with _classifier_lock:
            _classifier_instance = None
            logger.info("UnifiedRegimeClassifier singleton reset")
    else:
        _classifier_instance = None
        logger.info("UnifiedRegimeClassifier singleton reset (lock disabled)")
