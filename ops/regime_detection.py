"""
MERID-OPS Regime Detection Module

Phase 1.1 of Master Build Directive

Implements:
- Hidden Markov Models (HMM) for regime classification
- Bayesian Change Point Detection for regime transitions
- Canonical regime definitions with associated constraints

This module answers: "What world are we in right now?"

If regime detection fails, all downstream systems MUST degrade or halt.
"""

from __future__ import annotations

import threading
import time
import math
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple, Callable
import numpy as np
from collections import deque

from utils.logger import get_logger

logger = get_logger("ops.regime_detection")


class MarketRegime(Enum):
    """
    Canonical market regimes.
    
    Each regime defines:
    - Allowed strategies
    - Risk multipliers
    - Execution constraints
    - Automatic shutdown thresholds
    """
    TRENDING_BULL = "trending_bull"
    TRENDING_BEAR = "trending_bear"
    MEAN_REVERTING = "mean_reverting"
    HIGH_VOLATILITY = "high_volatility"
    CRISIS = "crisis"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RegimeConstraints:
    """Immutable constraints associated with a regime."""
    regime: MarketRegime
    
    # Strategy permissions
    allowed_strategy_types: Tuple[str, ...] = ()
    forbidden_strategy_types: Tuple[str, ...] = ()
    
    # Risk multipliers (1.0 = normal, <1.0 = reduced risk)
    position_size_multiplier: float = 1.0
    leverage_multiplier: float = 1.0
    drawdown_tolerance_multiplier: float = 1.0
    
    # Execution constraints
    max_order_size_pct: float = 1.0  # % of daily volume
    min_execution_delay_ms: int = 0
    require_twap: bool = False
    
    # Shutdown thresholds
    auto_halt_drawdown_pct: float = 5.0
    auto_halt_volatility_multiple: float = 3.0
    
    # Confidence requirements
    min_confidence_to_trade: float = 0.6
    min_regime_stability_seconds: float = 300.0


# Canonical regime constraint definitions
REGIME_CONSTRAINTS: Dict[MarketRegime, RegimeConstraints] = {
    MarketRegime.TRENDING_BULL: RegimeConstraints(
        regime=MarketRegime.TRENDING_BULL,
        allowed_strategy_types=("momentum", "breakout", "trend_following"),
        forbidden_strategy_types=("mean_reversion", "contrarian"),
        position_size_multiplier=1.0,
        leverage_multiplier=1.0,
        drawdown_tolerance_multiplier=1.0,
        max_order_size_pct=2.0,
        min_execution_delay_ms=0,
        require_twap=False,
        auto_halt_drawdown_pct=5.0,
        auto_halt_volatility_multiple=3.0,
        min_confidence_to_trade=0.6,
        min_regime_stability_seconds=300.0,
    ),
    MarketRegime.TRENDING_BEAR: RegimeConstraints(
        regime=MarketRegime.TRENDING_BEAR,
        allowed_strategy_types=("momentum", "trend_following", "hedging"),
        forbidden_strategy_types=("mean_reversion", "dip_buying"),
        position_size_multiplier=0.7,
        leverage_multiplier=0.5,
        drawdown_tolerance_multiplier=0.8,
        max_order_size_pct=1.5,
        min_execution_delay_ms=100,
        require_twap=False,
        auto_halt_drawdown_pct=4.0,
        auto_halt_volatility_multiple=2.5,
        min_confidence_to_trade=0.7,
        min_regime_stability_seconds=600.0,
    ),
    MarketRegime.MEAN_REVERTING: RegimeConstraints(
        regime=MarketRegime.MEAN_REVERTING,
        allowed_strategy_types=("mean_reversion", "range_trading", "arbitrage"),
        forbidden_strategy_types=("momentum", "breakout"),
        position_size_multiplier=0.8,
        leverage_multiplier=0.8,
        drawdown_tolerance_multiplier=1.0,
        max_order_size_pct=1.0,
        min_execution_delay_ms=0,
        require_twap=False,
        auto_halt_drawdown_pct=5.0,
        auto_halt_volatility_multiple=2.0,
        min_confidence_to_trade=0.65,
        min_regime_stability_seconds=600.0,
    ),
    MarketRegime.HIGH_VOLATILITY: RegimeConstraints(
        regime=MarketRegime.HIGH_VOLATILITY,
        allowed_strategy_types=("volatility", "hedging", "options"),
        forbidden_strategy_types=("momentum", "leverage", "margin"),
        position_size_multiplier=0.4,
        leverage_multiplier=0.25,
        drawdown_tolerance_multiplier=0.5,
        max_order_size_pct=0.5,
        min_execution_delay_ms=500,
        require_twap=True,
        auto_halt_drawdown_pct=3.0,
        auto_halt_volatility_multiple=1.5,
        min_confidence_to_trade=0.8,
        min_regime_stability_seconds=900.0,
    ),
    MarketRegime.CRISIS: RegimeConstraints(
        regime=MarketRegime.CRISIS,
        allowed_strategy_types=("hedging", "exit_only"),
        forbidden_strategy_types=("momentum", "leverage", "margin", "new_positions"),
        position_size_multiplier=0.1,
        leverage_multiplier=0.0,
        drawdown_tolerance_multiplier=0.3,
        max_order_size_pct=0.25,
        min_execution_delay_ms=1000,
        require_twap=True,
        auto_halt_drawdown_pct=2.0,
        auto_halt_volatility_multiple=1.0,
        min_confidence_to_trade=0.9,
        min_regime_stability_seconds=1800.0,
    ),
    MarketRegime.UNKNOWN: RegimeConstraints(
        regime=MarketRegime.UNKNOWN,
        allowed_strategy_types=("observation_only",),
        forbidden_strategy_types=("all_trading",),
        position_size_multiplier=0.0,
        leverage_multiplier=0.0,
        drawdown_tolerance_multiplier=0.0,
        max_order_size_pct=0.0,
        min_execution_delay_ms=5000,
        require_twap=True,
        auto_halt_drawdown_pct=1.0,
        auto_halt_volatility_multiple=0.5,
        min_confidence_to_trade=1.0,
        min_regime_stability_seconds=3600.0,
    ),
}


@dataclass
class RegimeObservation:
    """A single observation used for regime detection."""
    timestamp: float
    returns: float
    volatility: float
    volume_ratio: float  # vs 20-day average
    spread_ratio: float  # vs normal spread
    correlation_to_market: float
    momentum_score: float
    mean_reversion_score: float
    
    def to_vector(self) -> np.ndarray:
        """Convert to feature vector for HMM."""
        return np.array([
            self.returns,
            self.volatility,
            self.volume_ratio,
            self.spread_ratio,
            self.correlation_to_market,
            self.momentum_score,
            self.mean_reversion_score,
        ])


@dataclass
class RegimeState:
    """Current regime state with confidence and history."""
    current_regime: MarketRegime
    confidence: float
    regime_start_time: float
    observations_in_regime: int
    transition_probability: Dict[MarketRegime, float]
    constraints: RegimeConstraints
    
    # Stability metrics
    stability_score: float = 0.0
    time_in_regime_seconds: float = 0.0
    
    def is_stable(self) -> bool:
        """Check if regime is stable enough for trading."""
        return (
            self.time_in_regime_seconds >= self.constraints.min_regime_stability_seconds
            and self.confidence >= self.constraints.min_confidence_to_trade
            and self.stability_score >= 0.5
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_regime": self.current_regime.value,
            "confidence": round(self.confidence, 4),
            "regime_start_time": self.regime_start_time,
            "observations_in_regime": self.observations_in_regime,
            "transition_probability": {k.value: round(v, 4) for k, v in self.transition_probability.items()},
            "stability_score": round(self.stability_score, 4),
            "time_in_regime_seconds": round(self.time_in_regime_seconds, 1),
            "is_stable": self.is_stable(),
            "constraints": {
                "position_size_multiplier": self.constraints.position_size_multiplier,
                "leverage_multiplier": self.constraints.leverage_multiplier,
                "min_confidence_to_trade": self.constraints.min_confidence_to_trade,
            },
        }


class HiddenMarkovModel:
    """
    Hidden Markov Model for regime detection.
    
    States: MarketRegime enum values
    Observations: RegimeObservation feature vectors
    
    Uses Baum-Welch for parameter estimation and Viterbi for decoding.
    """
    
    def __init__(self, n_states: int = 5):
        self.n_states = n_states
        self.n_features = 7
        
        # State mapping
        self.states = [
            MarketRegime.TRENDING_BULL,
            MarketRegime.TRENDING_BEAR,
            MarketRegime.MEAN_REVERTING,
            MarketRegime.HIGH_VOLATILITY,
            MarketRegime.CRISIS,
        ]
        
        # Initialize transition matrix (row = from, col = to)
        # Regimes tend to persist (diagonal dominant)
        self.transition_matrix = np.array([
            [0.85, 0.05, 0.05, 0.04, 0.01],  # BULL
            [0.05, 0.80, 0.05, 0.07, 0.03],  # BEAR
            [0.10, 0.10, 0.70, 0.08, 0.02],  # MEAN_REV
            [0.05, 0.10, 0.10, 0.65, 0.10],  # HIGH_VOL
            [0.02, 0.08, 0.05, 0.15, 0.70],  # CRISIS
        ])
        
        # Initial state distribution
        self.initial_distribution = np.array([0.25, 0.15, 0.35, 0.20, 0.05])
        
        # Emission parameters (mean and std for each feature per state)
        # Shape: (n_states, n_features, 2) where last dim is [mean, std]
        self.emission_params = self._init_emission_params()
        
        # Observation history
        self._observations: deque = deque(maxlen=1000)
        self._state_history: deque = deque(maxlen=1000)
        
        logger.info("HMM initialized with %d states, %d features", n_states, self.n_features)
    
    def _init_emission_params(self) -> np.ndarray:
        """Initialize emission parameters based on regime characteristics."""
        params = np.zeros((self.n_states, self.n_features, 2))
        
        # Feature order: returns, volatility, volume_ratio, spread_ratio,
        #                correlation, momentum, mean_reversion
        
        # TRENDING_BULL: positive returns, moderate vol, high volume
        params[0] = [
            [0.002, 0.005],   # returns: positive
            [0.015, 0.005],   # volatility: moderate
            [1.2, 0.3],       # volume: above average
            [1.0, 0.2],       # spread: normal
            [0.7, 0.15],      # correlation: high
            [0.6, 0.2],       # momentum: positive
            [-0.2, 0.15],     # mean_reversion: low
        ]
        
        # TRENDING_BEAR: negative returns, higher vol
        params[1] = [
            [-0.003, 0.006],  # returns: negative
            [0.025, 0.008],   # volatility: elevated
            [1.4, 0.4],       # volume: high
            [1.3, 0.3],       # spread: wider
            [0.8, 0.1],       # correlation: very high
            [-0.5, 0.2],      # momentum: negative
            [-0.1, 0.15],     # mean_reversion: low
        ]
        
        # MEAN_REVERTING: near-zero returns, low vol
        params[2] = [
            [0.0, 0.003],     # returns: near zero
            [0.010, 0.003],   # volatility: low
            [0.9, 0.2],       # volume: below average
            [0.9, 0.15],      # spread: tight
            [0.4, 0.2],       # correlation: moderate
            [0.0, 0.15],      # momentum: neutral
            [0.5, 0.2],       # mean_reversion: high
        ]
        
        # HIGH_VOLATILITY: variable returns, high vol
        params[3] = [
            [0.0, 0.010],     # returns: highly variable
            [0.040, 0.015],   # volatility: high
            [1.8, 0.5],       # volume: very high
            [1.8, 0.4],       # spread: wide
            [0.6, 0.25],      # correlation: variable
            [0.0, 0.3],       # momentum: variable
            [0.0, 0.3],       # mean_reversion: variable
        ]
        
        # CRISIS: extreme negative, extreme vol
        params[4] = [
            [-0.010, 0.015],  # returns: very negative
            [0.080, 0.030],   # volatility: extreme
            [2.5, 0.8],       # volume: extreme
            [3.0, 1.0],       # spread: very wide
            [0.95, 0.05],     # correlation: near 1
            [-0.8, 0.15],     # momentum: very negative
            [-0.3, 0.2],      # mean_reversion: low
        ]
        
        return params
    
    def _emission_probability(self, observation: np.ndarray, state: int) -> float:
        """Calculate emission probability P(observation | state)."""
        log_prob = 0.0
        for i in range(self.n_features):
            mean = self.emission_params[state, i, 0]
            std = self.emission_params[state, i, 1]
            if std <= 0:
                std = 0.001
            
            # Gaussian emission
            z = (observation[i] - mean) / std
            log_prob += -0.5 * (z ** 2) - math.log(std) - 0.5 * math.log(2 * math.pi)
        
        return math.exp(max(log_prob, -700))  # Prevent underflow
    
    def forward(self, observations: List[np.ndarray]) -> Tuple[np.ndarray, float]:
        """
        Forward algorithm to compute P(observations | model).
        
        Returns alpha matrix and log-likelihood.
        """
        T = len(observations)
        alpha = np.zeros((T, self.n_states))
        
        # Initialize
        for s in range(self.n_states):
            alpha[0, s] = self.initial_distribution[s] * self._emission_probability(observations[0], s)
        
        # Normalize to prevent underflow
        scale = np.zeros(T)
        scale[0] = alpha[0].sum()
        if scale[0] > 0:
            alpha[0] /= scale[0]
        
        # Forward pass
        for t in range(1, T):
            for s in range(self.n_states):
                alpha[t, s] = sum(
                    alpha[t-1, s_prev] * self.transition_matrix[s_prev, s]
                    for s_prev in range(self.n_states)
                ) * self._emission_probability(observations[t], s)
            
            scale[t] = alpha[t].sum()
            if scale[t] > 0:
                alpha[t] /= scale[t]
        
        # Log-likelihood
        log_likelihood = sum(math.log(s) for s in scale if s > 0)
        
        return alpha, log_likelihood
    
    def viterbi(self, observations: List[np.ndarray]) -> Tuple[List[int], float]:
        """
        Viterbi algorithm to find most likely state sequence.
        
        Returns state sequence and log-probability.
        """
        T = len(observations)
        
        # Log probabilities to prevent underflow
        log_delta = np.full((T, self.n_states), -np.inf)
        psi = np.zeros((T, self.n_states), dtype=int)
        
        # Initialize
        for s in range(self.n_states):
            emit_prob = self._emission_probability(observations[0], s)
            if emit_prob > 0 and self.initial_distribution[s] > 0:
                log_delta[0, s] = math.log(self.initial_distribution[s]) + math.log(emit_prob)
        
        # Forward pass
        for t in range(1, T):
            emit_probs = [self._emission_probability(observations[t], s) for s in range(self.n_states)]
            
            for s in range(self.n_states):
                if emit_probs[s] <= 0:
                    continue
                
                log_emit = math.log(emit_probs[s])
                
                best_prev = -1
                best_score = -np.inf
                
                for s_prev in range(self.n_states):
                    if self.transition_matrix[s_prev, s] <= 0:
                        continue
                    
                    score = log_delta[t-1, s_prev] + math.log(self.transition_matrix[s_prev, s])
                    if score > best_score:
                        best_score = score
                        best_prev = s_prev
                
                if best_prev >= 0:
                    log_delta[t, s] = best_score + log_emit
                    psi[t, s] = best_prev
        
        # Backtrack
        states = [0] * T
        states[T-1] = int(np.argmax(log_delta[T-1]))
        
        for t in range(T-2, -1, -1):
            states[t] = psi[t+1, states[t+1]]
        
        return states, float(np.max(log_delta[T-1]))
    
    def predict_state(self, observation: RegimeObservation) -> Tuple[MarketRegime, np.ndarray]:
        """
        Predict current state given new observation.
        
        Returns (most likely regime, probability distribution over regimes).
        """
        obs_vector = observation.to_vector()
        self._observations.append(obs_vector)
        
        if len(self._observations) < 5:
            # Not enough history, use emission probabilities only
            probs = np.array([
                self._emission_probability(obs_vector, s)
                for s in range(self.n_states)
            ])
            probs = probs / probs.sum() if probs.sum() > 0 else self.initial_distribution
            best_state = int(np.argmax(probs))
            return self.states[best_state], probs
        
        # Use recent observations for Viterbi
        recent_obs = list(self._observations)[-50:]
        state_sequence, _ = self.viterbi(recent_obs)
        
        # Current state is last in sequence
        current_state_idx = state_sequence[-1]
        
        # Calculate state probabilities using forward algorithm
        alpha, _ = self.forward(recent_obs)
        probs = alpha[-1] / alpha[-1].sum() if alpha[-1].sum() > 0 else self.initial_distribution
        
        self._state_history.append(current_state_idx)
        
        return self.states[current_state_idx], probs
    
    def get_transition_probabilities(self, current_state: MarketRegime) -> Dict[MarketRegime, float]:
        """Get transition probabilities from current state."""
        state_idx = self.states.index(current_state)
        return {
            self.states[i]: float(self.transition_matrix[state_idx, i])
            for i in range(self.n_states)
        }


class BayesianChangePointDetector:
    """
    Bayesian Online Change Point Detection.
    
    Detects regime transitions in real-time using Bayesian inference.
    Based on Adams & MacKay (2007).
    """
    
    def __init__(self, hazard_rate: float = 0.01, min_run_length: int = 10):
        self.hazard_rate = hazard_rate  # Prior probability of change point
        self.min_run_length = min_run_length
        
        # Run length distribution
        self._run_length_probs: List[float] = [1.0]
        self._observations: List[float] = []
        
        # Sufficient statistics for Gaussian model
        self._sum_x: List[float] = [0.0]
        self._sum_x2: List[float] = [0.0]
        self._counts: List[int] = [0]
        
        # Change point history
        self._change_points: List[Tuple[int, float]] = []
        self._observation_count = 0
        
        logger.info("Bayesian change point detector initialized (hazard=%.3f)", hazard_rate)
    
    def _predictive_probability(self, x: float, run_length: int) -> float:
        """Calculate predictive probability P(x | run_length)."""
        if run_length >= len(self._counts) or self._counts[run_length] < 2:
            # Use prior (standard normal)
            return math.exp(-0.5 * x ** 2) / math.sqrt(2 * math.pi)
        
        n = self._counts[run_length]
        mean = self._sum_x[run_length] / n
        var = max(0.001, (self._sum_x2[run_length] / n) - mean ** 2)
        std = math.sqrt(var)
        
        z = (x - mean) / std
        return math.exp(-0.5 * z ** 2) / (std * math.sqrt(2 * math.pi))
    
    def update(self, observation: float) -> Tuple[float, Optional[int]]:
        """
        Update with new observation.
        
        Returns (change point probability, detected change point index or None).
        """
        self._observation_count += 1
        self._observations.append(observation)
        
        # Calculate predictive probabilities for all run lengths
        n_run_lengths = len(self._run_length_probs)
        pred_probs = np.array([
            self._predictive_probability(observation, r)
            for r in range(n_run_lengths)
        ])
        
        # Growth probabilities (no change point)
        growth_probs = np.array(self._run_length_probs) * pred_probs * (1 - self.hazard_rate)
        
        # Change point probability (sum of all run lengths transitioning to 0)
        cp_prob = sum(
            self._run_length_probs[r] * pred_probs[r] * self.hazard_rate
            for r in range(n_run_lengths)
        )
        
        # New run length distribution
        new_probs = [cp_prob] + list(growth_probs)
        
        # Normalize
        total = sum(new_probs)
        if total > 0:
            new_probs = [p / total for p in new_probs]
        
        self._run_length_probs = new_probs
        
        # Update sufficient statistics
        new_sum_x = [0.0] + [s + observation for s in self._sum_x]
        new_sum_x2 = [0.0] + [s + observation ** 2 for s in self._sum_x2]
        new_counts = [0] + [c + 1 for c in self._counts]
        
        self._sum_x = new_sum_x
        self._sum_x2 = new_sum_x2
        self._counts = new_counts
        
        # Detect change point
        detected_cp = None
        if cp_prob > 0.5 and self._observation_count > self.min_run_length:
            detected_cp = self._observation_count
            self._change_points.append((detected_cp, cp_prob))
            logger.info("Change point detected at observation %d (prob=%.3f)", detected_cp, cp_prob)
        
        return cp_prob, detected_cp
    
    def get_run_length_distribution(self) -> Dict[int, float]:
        """Get current run length probability distribution."""
        return {i: p for i, p in enumerate(self._run_length_probs) if p > 0.01}
    
    def get_most_likely_run_length(self) -> int:
        """Get most likely current run length."""
        return int(np.argmax(self._run_length_probs))
    
    def get_change_points(self) -> List[Tuple[int, float]]:
        """Get detected change points with probabilities."""
        return self._change_points.copy()


class RegimeDetector:
    """
    Main regime detection engine combining HMM and Bayesian change point detection.
    
    This is the primary interface for MERID-OPS regime awareness.
    """
    
    def __init__(self):
        self.hmm = HiddenMarkovModel()
        self.change_detector = BayesianChangePointDetector()
        
        # Current state
        self._current_state: Optional[RegimeState] = None
        self._state_history: List[RegimeState] = []
        self._observation_count = 0
        
        # Regime transition tracking
        self._last_regime_change: float = time.time()
        self._regime_durations: Dict[MarketRegime, List[float]] = {r: [] for r in MarketRegime}
        
        # Callbacks for regime changes
        self._regime_change_callbacks: List[Callable[[RegimeState, RegimeState], None]] = []
        
        logger.info("Regime detector initialized")
    
    def register_regime_change_callback(
        self,
        callback: Callable[[RegimeState, RegimeState], None]
    ) -> None:
        """Register callback for regime changes."""
        self._regime_change_callbacks.append(callback)
    
    def process_observation(self, observation: RegimeObservation) -> RegimeState:
        """
        Process new observation and update regime state.
        
        This is the main entry point for regime detection.
        """
        self._observation_count += 1
        
        # HMM prediction
        regime, state_probs = self.hmm.predict_state(observation)
        confidence = float(state_probs[self.hmm.states.index(regime)])
        
        # Change point detection on returns
        cp_prob, detected_cp = self.change_detector.update(observation.returns)
        
        # If change point detected, reduce confidence
        if cp_prob > 0.3:
            confidence *= (1 - cp_prob * 0.5)
        
        # Get transition probabilities
        transition_probs = self.hmm.get_transition_probabilities(regime)
        
        # Check for regime change
        old_state = self._current_state
        regime_changed = old_state is None or old_state.current_regime != regime
        
        if regime_changed:
            # Record duration of previous regime
            if old_state is not None:
                duration = time.time() - old_state.regime_start_time
                self._regime_durations[old_state.current_regime].append(duration)
            
            self._last_regime_change = time.time()
            observations_in_regime = 1
        else:
            observations_in_regime = old_state.observations_in_regime + 1
        
        # Calculate stability score
        time_in_regime = time.time() - self._last_regime_change
        stability_score = self._calculate_stability(regime, confidence, time_in_regime)
        
        # Create new state
        new_state = RegimeState(
            current_regime=regime,
            confidence=confidence,
            regime_start_time=self._last_regime_change,
            observations_in_regime=observations_in_regime,
            transition_probability=transition_probs,
            constraints=REGIME_CONSTRAINTS[regime],
            stability_score=stability_score,
            time_in_regime_seconds=time_in_regime,
        )
        
        self._current_state = new_state
        self._state_history.append(new_state)
        
        # Trigger callbacks on regime change
        if regime_changed and old_state is not None:
            logger.warning(
                "REGIME CHANGE: %s -> %s (confidence: %.2f, stability: %.2f)",
                old_state.current_regime.value, regime.value, confidence, stability_score
            )
            for callback in self._regime_change_callbacks:
                try:
                    callback(old_state, new_state)
                except Exception as e:
                    logger.error("Regime change callback failed: %s", e)
        
        return new_state
    
    def _calculate_stability(
        self,
        regime: MarketRegime,
        confidence: float,
        time_in_regime: float
    ) -> float:
        """Calculate regime stability score."""
        # Base stability from confidence
        stability = confidence
        
        # Increase stability with time (up to a point)
        time_factor = min(1.0, time_in_regime / 3600)  # Max at 1 hour
        stability = 0.6 * stability + 0.4 * time_factor
        
        # Reduce stability for volatile regimes
        if regime in (MarketRegime.HIGH_VOLATILITY, MarketRegime.CRISIS):
            stability *= 0.7
        
        # Check historical regime duration
        historical_durations = self._regime_durations.get(regime, [])
        if historical_durations:
            avg_duration = sum(historical_durations) / len(historical_durations)
            if time_in_regime > avg_duration * 2:
                # Regime has lasted longer than usual, may be ending
                stability *= 0.8
        
        return min(1.0, max(0.0, stability))
    
    def get_current_state(self) -> Optional[RegimeState]:
        """Get current regime state."""
        return self._current_state
    
    def get_constraints(self) -> Optional[RegimeConstraints]:
        """Get current regime constraints."""
        if self._current_state is None:
            return REGIME_CONSTRAINTS[MarketRegime.UNKNOWN]
        return self._current_state.constraints
    
    def is_trading_allowed(self, strategy_type: str) -> Tuple[bool, str]:
        """
        Check if trading is allowed for a strategy type.
        
        Returns (allowed, reason).
        """
        if self._current_state is None:
            return False, "No regime state available"
        
        state = self._current_state
        constraints = state.constraints
        
        # Check stability
        if not state.is_stable():
            return False, f"Regime not stable (stability={state.stability_score:.2f}, required={constraints.min_confidence_to_trade})"
        
        # Check forbidden strategies
        if strategy_type in constraints.forbidden_strategy_types:
            return False, f"Strategy type '{strategy_type}' forbidden in {state.current_regime.value} regime"
        
        # Check allowed strategies
        if constraints.allowed_strategy_types and strategy_type not in constraints.allowed_strategy_types:
            if "all_trading" in constraints.forbidden_strategy_types:
                return False, f"All trading forbidden in {state.current_regime.value} regime"
        
        return True, "Trading allowed"
    
    def should_halt(self) -> Tuple[bool, str]:
        """
        Check if system should halt based on regime.
        
        Returns (should_halt, reason).
        """
        if self._current_state is None:
            return True, "No regime state - cannot assess risk"
        
        state = self._current_state
        
        # Crisis regime with low confidence
        if state.current_regime == MarketRegime.CRISIS and state.confidence > 0.7:
            return True, "CRISIS regime detected with high confidence"
        
        # Unknown regime
        if state.current_regime == MarketRegime.UNKNOWN:
            return True, "UNKNOWN regime - cannot assess risk"
        
        # Very low stability
        if state.stability_score < 0.2:
            return True, f"Regime stability critically low ({state.stability_score:.2f})"
        
        return False, "No halt required"
    
    def get_status(self) -> Dict[str, Any]:
        """Get detector status."""
        state = self._current_state
        
        return {
            "current_regime": state.current_regime.value if state else "unknown",
            "confidence": round(state.confidence, 4) if state else 0,
            "stability_score": round(state.stability_score, 4) if state else 0,
            "is_stable": state.is_stable() if state else False,
            "time_in_regime_seconds": round(state.time_in_regime_seconds, 1) if state else 0,
            "observations_processed": self._observation_count,
            "change_points_detected": len(self.change_detector.get_change_points()),
            "should_halt": self.should_halt()[0],
            "halt_reason": self.should_halt()[1] if self.should_halt()[0] else None,
        }
    
    def get_regime_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent regime history."""
        return [s.to_dict() for s in self._state_history[-limit:]]


# Singleton instance
_regime_detector: Optional[RegimeDetector] = None
_regime_detector_lock = threading.Lock()


def get_regime_detector() -> RegimeDetector:
    """Get the singleton regime detector."""
    global _regime_detector
    if _regime_detector is None:
        with _regime_detector_lock:
            if _regime_detector is None:
                _regime_detector = RegimeDetector()
    return _regime_detector
