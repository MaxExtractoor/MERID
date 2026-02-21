"""
Markov Switching Regime Detector with Fear/Greed

2-state Markov regime (calm vs turbulent) driven partly by FG index.
Useful for dynamic risk adjustment based on market regime.
"""

import numpy as np
from typing import Tuple, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


class RegimeState(Enum):
    """Markov regime states."""
    CALM = 0        # Normal market conditions
    TURBULENT = 1   # High volatility/uncertainty


@dataclass
class RegimeInfo:
    """Current regime information."""
    state: RegimeState
    state_name: str
    transition_prob: float
    fg_index: int
    timestamp: datetime


class SimpleFGMarkov:
    """
    Simple 2-state Markov regime detector driven by Fear/Greed.
    
    States:
    - CALM (0): Normal market, allow normal sizing
    - TURBULENT (1): High uncertainty, reduce exposure
    
    FG influences transition probabilities:
    - Extreme FG increases likelihood of turbulent regime
    - Neutral FG favors calm regime
    
    Usage:
        markov = SimpleFGMarkov()
        
        # Update with current FG
        regime = markov.transition(fg_index=75)
        
        if regime == RegimeState.TURBULENT:
            # Reduce position sizes
            size *= 0.6
    """
    
    def __init__(
        self,
        base_transition: np.ndarray = None,
        fg_extreme_threshold: int = 20,
        fg_influence: float = 0.05,
    ):
        """
        Args:
            base_transition: Base 2x2 transition matrix [[P(calm->calm), P(calm->turb)],
                                                           [P(turb->calm), P(turb->turb)]]
            fg_extreme_threshold: FG deviation from 50 to count as extreme
            fg_influence: How much extreme FG shifts transition probs
        """
        if base_transition is None:
            # Default: 90% stay in same state, 10% switch
            self.P_base = np.array([[0.9, 0.1],
                                    [0.2, 0.8]], dtype=float)
        else:
            self.P_base = base_transition
        
        self.fg_extreme_threshold = fg_extreme_threshold
        self.fg_influence = fg_influence
        
        self.state = RegimeState.CALM
        self.P_current = self.P_base.copy()
        self._history: list = []
    
    def _is_fg_extreme(self, fg_index: int) -> bool:
        """Check if FG is in extreme zone."""
        return abs(fg_index - 50) >= self.fg_extreme_threshold
    
    def update_transition_matrix(self, fg_index: int) -> np.ndarray:
        """
        Update transition matrix based on FG.
        
        Extreme FG (high or low) increases probability of turbulent regime.
        """
        P = self.P_base.copy()
        
        if self._is_fg_extreme(fg_index):
            # FG extreme - more likely to enter/stay in turbulent
            P[0, 1] += self.fg_influence  # calm -> turbulent
            P[0, 0] -= self.fg_influence
            P[1, 1] += self.fg_influence  # turbulent -> turbulent
            P[1, 0] -= self.fg_influence
        
        # Normalize rows to sum to 1
        P = np.clip(P, 0.01, 0.99)
        P = P / P.sum(axis=1, keepdims=True)
        
        self.P_current = P
        return P
    
    def transition(self, fg_index: int) -> RegimeState:
        """
        Perform state transition based on FG.
        
        Args:
            fg_index: Current fear/greed index
        
        Returns:
            New regime state
        """
        # Update transition matrix
        self.update_transition_matrix(fg_index)
        
        # Get transition probabilities from current state
        current_idx = self.state.value
        probs = self.P_current[current_idx]
        
        # Sample next state
        # probs[0] = P(stay in current), probs[1] = P(switch)
        if self.state == RegimeState.CALM:
            # probs[0] = P(calm->calm), probs[1] = P(calm->turbulent)
            next_state = RegimeState.TURBULENT if np.random.rand() > probs[0] else RegimeState.CALM
        else:
            # probs[0] = P(turbulent->calm), probs[1] = P(turbulent->turbulent)
            next_state = RegimeState.CALM if np.random.rand() < probs[0] else RegimeState.TURBULENT
        
        self.state = next_state
        
        # Log transition
        info = RegimeInfo(
            state=next_state,
            state_name=next_state.name,
            transition_prob=probs[1] if next_state != self.state else probs[0],
            fg_index=fg_index,
            timestamp=datetime.now(timezone.utc),
        )
        self._history.append(info)
        
        if len(self._history) > 1000:
            self._history = self._history[-1000:]
        
        logger.info(f"Markov regime: {next_state.name} (FG={fg_index})")
        return next_state
    
    def get_current_regime(self) -> RegimeInfo:
        """Get current regime info."""
        return RegimeInfo(
            state=self.state,
            state_name=self.state.name,
            transition_prob=self.P_current[self.state.value, 1 - self.state.value],
            fg_index=0,  # Unknown unless updated
            timestamp=datetime.now(timezone.utc),
        )
    
    def get_risk_multiplier(self) -> float:
        """Get position size multiplier based on regime."""
        return 1.0 if self.state == RegimeState.CALM else 0.6
    
    def should_trade(self) -> Tuple[bool, str]:
        """Check if trading is allowed in current regime."""
        if self.state == RegimeState.TURBULENT:
            return False, f"Regime {self.state.name} - reduced trading"
        return True, f"Regime {self.state.name} - normal trading"
    
    def get_transition_stats(self) -> Dict[str, Any]:
        """Get statistics on regime transitions."""
        if not self._history:
            return {"error": "No history"}
        
        calm_count = sum(1 for h in self._history if h.state == RegimeState.CALM)
        turb_count = len(self._history) - calm_count
        
        return {
            "total_transitions": len(self._history),
            "calm_periods": calm_count,
            "turbulent_periods": turb_count,
            "calm_pct": calm_count / len(self._history),
            "current_regime": self.state.name,
            "current_duration": self._compute_current_duration(),
        }
    
    def _compute_current_duration(self) -> int:
        """Compute how long we've been in current regime."""
        if not self._history:
            return 0
        
        current_state = self.state
        duration = 0
        
        for info in reversed(self._history):
            if info.state == current_state:
                duration += 1
            else:
                break
        
        return duration


class MarkovSentimentRiskAdapter:
    """
    Adapter to use Markov regime with sentiment-based risk management.
    
    Combines Markov regime detector with sentiment state for unified risk signals.
    """
    
    def __init__(self, markov: Optional[SimpleFGMarkov] = None):
        self.markov = markov or SimpleFGMarkov()
    
    def update(
        self,
        fg_index: int,
        sentiment: float,
        confidence: float,
    ) -> Dict[str, Any]:
        """
        Update with current market conditions.
        
        Returns:
            Risk recommendation dict
        """
        # Update Markov regime
        regime = self.markov.transition(fg_index)
        
        # Compute combined risk score
        markov_mult = self.markov.get_risk_multiplier()
        
        # Sentiment extreme check
        extreme = (fg_index >= 80 and sentiment > 0) or (fg_index <= 20 and sentiment < 0)
        sent_mult = 0.6 if extreme else 1.0
        
        # Confidence scaling
        conf_mult = 0.5 + 0.5 * confidence
        
        # Combined multiplier
        total_mult = markov_mult * sent_mult * conf_mult
        
        return {
            "regime": regime.name,
            "markov_multiplier": markov_mult,
            "sentiment_multiplier": sent_mult,
            "confidence_multiplier": conf_mult,
            "total_multiplier": total_mult,
            "can_trade": regime == RegimeState.CALM and confidence > 0.3,
            "reason": self._generate_reason(regime, extreme, confidence),
        }
    
    def _generate_reason(
        self,
        regime: RegimeState,
        extreme: bool,
        confidence: float,
    ) -> str:
        """Generate human-readable reason."""
        parts = [f"Regime: {regime.name}"]
        
        if extreme:
            parts.append("Extreme sentiment")
        
        if confidence < 0.3:
            parts.append("Low confidence")
        
        return " | ".join(parts)


# ── Convenience functions ──────────────────────────────────────────

def quick_markov_regime(fg_index: int, prev_regime: Optional[int] = None) -> str:
    """
    Quick one-liner to get Markov regime.
    
    Returns:
        Regime name: 'CALM' or 'TURBULENT'
    """
    markov = SimpleFGMarkov()
    if prev_regime is not None:
        markov.state = RegimeState(prev_regime)
    
    regime = markov.transition(fg_index)
    return regime.name


def get_markov_risk_mult(fg_index: int) -> float:
    """Quick risk multiplier from Markov regime."""
    markov = SimpleFGMarkov()
    markov.transition(fg_index)
    return markov.get_risk_multiplier()
