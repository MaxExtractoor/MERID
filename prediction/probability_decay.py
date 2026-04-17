"""
Implied Probability Decay Analyzer.

Analyzes how prediction market probabilities decay/converge
as events approach resolution. Identifies mispricing opportunities.

Version: 1.0.0
"""

from __future__ import annotations

import threading
import math
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

from utils.logger import get_logger

logger = get_logger("prediction.probability_decay")


class DecayPattern(Enum):
    """Types of probability decay patterns."""
    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    STEP = "step"
    OSCILLATING = "oscillating"
    STABLE = "stable"


@dataclass
class ProbabilitySnapshot:
    """A snapshot of market probability at a point in time."""
    timestamp: float
    yes_price: float
    no_price: float
    volume_24h: float
    liquidity: float
    time_to_resolution_hours: float
    
    @property
    def implied_probability(self) -> float:
        """Implied probability from yes price."""
        return self.yes_price
    
    @property
    def spread(self) -> float:
        """Bid-ask spread."""
        return abs(1 - self.yes_price - self.no_price)


@dataclass
class DecayCurve:
    """Modeled decay curve for a market."""
    market_id: str
    pattern: DecayPattern
    
    # Curve parameters
    initial_probability: float = 0.5
    final_probability: float = 0.5  # Expected at resolution
    decay_rate: float = 0.0  # Rate of change
    
    # Fit quality
    r_squared: float = 0.0
    samples: int = 0
    
    # Time parameters
    hours_to_resolution: float = 0.0
    
    def predict_probability(self, hours_remaining: float) -> float:
        """Predict probability at given time."""
        if self.pattern == DecayPattern.LINEAR:
            progress = 1 - (hours_remaining / max(self.hours_to_resolution, 1))
            return self.initial_probability + (self.final_probability - self.initial_probability) * progress
        
        elif self.pattern == DecayPattern.EXPONENTIAL:
            decay = math.exp(-self.decay_rate * (self.hours_to_resolution - hours_remaining))
            return self.final_probability + (self.initial_probability - self.final_probability) * decay
        
        elif self.pattern == DecayPattern.STEP:
            # Step function at certain thresholds
            if hours_remaining > 24:
                return self.initial_probability
            elif hours_remaining > 1:
                return (self.initial_probability + self.final_probability) / 2
            else:
                return self.final_probability
        
        return self.initial_probability
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_id": self.market_id,
            "pattern": self.pattern.value,
            "initial_probability": self.initial_probability,
            "final_probability": self.final_probability,
            "decay_rate": self.decay_rate,
            "r_squared": self.r_squared,
            "samples": self.samples,
            "hours_to_resolution": self.hours_to_resolution,
        }


@dataclass
class MispricingSignal:
    """Signal indicating potential mispricing."""
    market_id: str
    platform: str
    
    # Current state
    current_price: float
    predicted_price: float
    deviation_pct: float
    
    # Direction
    direction: str  # "overpriced" or "underpriced"
    
    # Confidence
    confidence: float
    signal_strength: float  # 0-1
    
    # Timing
    hours_to_resolution: float
    detected_at: float = field(default_factory=time.time)
    
    # Action
    suggested_action: str = ""  # "buy_yes", "buy_no", "wait"
    expected_edge_pct: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_id": self.market_id,
            "platform": self.platform,
            "current_price": self.current_price,
            "predicted_price": self.predicted_price,
            "deviation_pct": self.deviation_pct,
            "direction": self.direction,
            "confidence": self.confidence,
            "signal_strength": self.signal_strength,
            "hours_to_resolution": self.hours_to_resolution,
            "suggested_action": self.suggested_action,
            "expected_edge_pct": self.expected_edge_pct,
            "detected_at": self.detected_at,
        }


class ProbabilityDecayAnalyzer:
    """
    Analyzes probability decay patterns in prediction markets.
    
    Tracks how market prices evolve as events approach resolution
    and identifies deviations from expected decay patterns that
    may indicate mispricing opportunities.
    """
    
    def __init__(self):
        self.logger = get_logger("prediction.probability_decay")
        
        # Price history per market
        self._history: Dict[str, List[ProbabilitySnapshot]] = {}
        self._max_history: int = 1000
        
        # Fitted decay curves
        self._curves: Dict[str, DecayCurve] = {}
        
        # Active mispricing signals
        self._signals: List[MispricingSignal] = []
        self._max_signals: int = 100
        
        # Configuration
        self._min_deviation_pct: float = 5.0  # Minimum deviation to signal
        self._min_samples: int = 10  # Minimum samples to fit curve
    
    def record_snapshot(self, market_id: str, snapshot: ProbabilitySnapshot) -> None:
        """Record a probability snapshot for a market."""
        if market_id not in self._history:
            self._history[market_id] = []
        
        self._history[market_id].append(snapshot)
        
        # Trim old snapshots
        if len(self._history[market_id]) > self._max_history:
            self._history[market_id] = self._history[market_id][-self._max_history:]
        
        # Update curve if enough samples
        if len(self._history[market_id]) >= self._min_samples:
            self._fit_curve(market_id)
    
    def _fit_curve(self, market_id: str) -> None:
        """Fit a decay curve to market history."""
        snapshots = self._history.get(market_id, [])
        if len(snapshots) < self._min_samples:
            return
        
        # Extract data
        times = [s.time_to_resolution_hours for s in snapshots]
        probs = [s.implied_probability for s in snapshots]
        
        # Determine pattern
        pattern = self._detect_pattern(times, probs)
        
        # Fit parameters
        initial_prob = probs[0] if probs else 0.5
        final_prob = probs[-1] if probs else 0.5
        
        # Calculate decay rate for exponential
        if pattern == DecayPattern.EXPONENTIAL and len(times) > 1:
            time_diff = times[0] - times[-1]
            prob_diff = initial_prob - final_prob
            if time_diff > 0 and prob_diff != 0:
                decay_rate = -math.log(abs(prob_diff) + 0.01) / time_diff
            else:
                decay_rate = 0.1
        else:
            decay_rate = 0.0
        
        # Calculate R-squared (simplified)
        r_squared = self._calculate_r_squared(times, probs, pattern, initial_prob, final_prob, decay_rate)
        
        self._curves[market_id] = DecayCurve(
            market_id=market_id,
            pattern=pattern,
            initial_probability=initial_prob,
            final_probability=final_prob,
            decay_rate=decay_rate,
            r_squared=r_squared,
            samples=len(snapshots),
            hours_to_resolution=times[0] if times else 0,
        )
    
    def _detect_pattern(self, times: List[float], probs: List[float]) -> DecayPattern:
        """Detect the decay pattern from data."""
        if len(probs) < 3:
            return DecayPattern.STABLE
        
        # Calculate changes
        changes = [probs[i+1] - probs[i] for i in range(len(probs)-1)]
        
        # Check for stability
        if all(abs(c) < 0.02 for c in changes):
            return DecayPattern.STABLE
        
        # Check for step changes
        large_changes = sum(1 for c in changes if abs(c) > 0.1)
        if large_changes > 0 and large_changes < len(changes) * 0.2:
            return DecayPattern.STEP
        
        # Check for oscillation
        sign_changes = sum(1 for i in range(len(changes)-1) if changes[i] * changes[i+1] < 0)
        if sign_changes > len(changes) * 0.4:
            return DecayPattern.OSCILLATING
        
        # Check for exponential vs linear
        # Exponential has accelerating change near resolution
        if len(changes) > 5:
            early_avg = abs(sum(changes[:len(changes)//2]) / (len(changes)//2))
            late_avg = abs(sum(changes[len(changes)//2:]) / (len(changes) - len(changes)//2))
            if late_avg > early_avg * 1.5:
                return DecayPattern.EXPONENTIAL
        
        return DecayPattern.LINEAR
    
    def _calculate_r_squared(
        self,
        times: List[float],
        probs: List[float],
        pattern: DecayPattern,
        initial: float,
        final: float,
        decay_rate: float
    ) -> float:
        """Calculate R-squared for curve fit."""
        if not probs:
            return 0.0
        
        mean_prob = sum(probs) / len(probs)
        ss_tot = sum((p - mean_prob) ** 2 for p in probs)
        
        if ss_tot == 0:
            return 1.0
        
        # Create temporary curve for predictions
        temp_curve = DecayCurve(
            market_id="temp",
            pattern=pattern,
            initial_probability=initial,
            final_probability=final,
            decay_rate=decay_rate,
            hours_to_resolution=times[0] if times else 0,
        )
        
        predictions = [temp_curve.predict_probability(t) for t in times]
        ss_res = sum((probs[i] - predictions[i]) ** 2 for i in range(len(probs)))
        
        return 1 - (ss_res / ss_tot)
    
    def analyze_mispricing(
        self,
        market_id: str,
        platform: str,
        current_price: float,
        hours_to_resolution: float
    ) -> Optional[MispricingSignal]:
        """Analyze if current price is mispriced relative to decay curve."""
        curve = self._curves.get(market_id)
        if not curve:
            return None
        
        # Predict expected price
        predicted = curve.predict_probability(hours_to_resolution)
        
        # Calculate deviation
        deviation = current_price - predicted
        deviation_pct = abs(deviation / predicted) * 100 if predicted > 0 else 0
        
        # Check if significant
        if deviation_pct < self._min_deviation_pct:
            return None
        
        # Determine direction
        if deviation > 0:
            direction = "overpriced"
            suggested_action = "buy_no"
        else:
            direction = "underpriced"
            suggested_action = "buy_yes"
        
        # Calculate confidence based on curve fit and samples
        confidence = curve.r_squared * min(1.0, curve.samples / 50)
        
        # Signal strength based on deviation and time
        time_factor = min(1.0, 24 / max(hours_to_resolution, 1))  # Stronger near resolution
        signal_strength = min(1.0, (deviation_pct / 20) * time_factor)
        
        signal = MispricingSignal(
            market_id=market_id,
            platform=platform,
            current_price=current_price,
            predicted_price=predicted,
            deviation_pct=deviation_pct,
            direction=direction,
            confidence=confidence,
            signal_strength=signal_strength,
            hours_to_resolution=hours_to_resolution,
            suggested_action=suggested_action,
            expected_edge_pct=deviation_pct * confidence,
        )
        
        # Store signal
        self._signals.append(signal)
        if len(self._signals) > self._max_signals:
            self._signals = self._signals[-self._max_signals:]
        
        return signal
    
    def get_curve(self, market_id: str) -> Optional[DecayCurve]:
        """Get decay curve for a market."""
        return self._curves.get(market_id)
    
    def get_all_curves(self) -> Dict[str, DecayCurve]:
        """Get all decay curves."""
        return self._curves.copy()
    
    def get_signals(self, min_strength: float = 0.0) -> List[MispricingSignal]:
        """Get mispricing signals above threshold."""
        return [s for s in self._signals if s.signal_strength >= min_strength]
    
    def get_status(self) -> Dict[str, Any]:
        """Get analyzer status."""
        return {
            "markets_tracked": len(self._history),
            "curves_fitted": len(self._curves),
            "active_signals": len(self._signals),
            "curves": {k: v.to_dict() for k, v in self._curves.items()},
            "recent_signals": [s.to_dict() for s in self._signals[-10:]],
        }


# Singleton
_probability_decay_analyzer: Optional[ProbabilityDecayAnalyzer] = None
_probability_decay_analyzer_lock = threading.Lock()


def get_probability_decay_analyzer() -> ProbabilityDecayAnalyzer:
    """Get or create the Probability Decay Analyzer singleton."""
    global _probability_decay_analyzer
    if _probability_decay_analyzer is None:
        with _probability_decay_analyzer_lock:
            if _probability_decay_analyzer is None:
                _probability_decay_analyzer = ProbabilityDecayAnalyzer()
    return _probability_decay_analyzer
