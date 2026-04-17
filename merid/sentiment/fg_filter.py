"""
Fear & Greed Filter and Probability Adjustment for Kalshi Trades

Implements FG-based trade filtering and contrarian probability adjustments
as described in sentiment trading research.
"""

from utils.logger import get_logger
from typing import Tuple, Dict, Any
from dataclasses import dataclass
import threading

logger = get_logger(__name__)


@dataclass
class FGFilterResult:
    """Result of Fear/Greed filter check."""
    allowed: bool
    reason: str
    adjustment: float  # Probability adjustment
    contrarian_signal: bool


class KalshiFGFilter:
    """
    Fear & Greed Index filter and probability adjuster for Kalshi trades.
    
    Uses FG as a regime identifier and filter rather than standalone signal.
    Best used to limit certain trade types to appropriate periods.
    
    Usage:
        fg_filter = KalshiFGFilter()
        
        # Check if trade allowed
        result = fg_filter.filter_trade(fg_index=75, side="yes")
        if not result.allowed:
            return  # Skip trade
        
        # Adjust probability
        prob = fg_filter.adjust_prob(base_prob=0.55, fg_index=75, side="yes")
    """
    
    def __init__(
        self,
        extreme_greed: int = 80,
        extreme_fear: int = 20,
        contrarian_bias: float = 0.01,
    ):
        self.extreme_greed = extreme_greed
        self.extreme_fear = extreme_fear
        self.contrarian_bias = contrarian_bias
    
    def filter_trade(
        self,
        fg_index: int,
        side: str,
        strategy_type: str = "directional",
    ) -> FGFilterResult:
        """
        Check if trade is allowed given FG and side.
        
        Logic:
        - YES (bullish): Allow in fear/neutral, restrict in extreme greed
        - NO (bearish): Allow in greed/neutral, restrict in extreme fear
        - Contrarian strategies: Reverse logic
        
        Args:
            fg_index: Fear/greed index 0-100
            side: 'yes' or 'no'
            strategy_type: 'directional' or 'contrarian'
        
        Returns:
            FGFilterResult
        """
        is_extreme_greed = fg_index >= self.extreme_greed
        is_extreme_fear = fg_index <= self.extreme_fear
        
        if strategy_type == "directional":
            # Directional: Follow the bias, but avoid extremes
            if side == "yes":
                # Bullish: more willing when fearful, cautious when greedy
                if is_extreme_greed:
                    return FGFilterResult(
                        allowed=False,
                        reason=f"Extreme greed ({fg_index}) - avoid bullish",
                        adjustment=0.0,
                        contrarian_signal=True,
                    )
                return FGFilterResult(
                    allowed=True,
                    reason=f"Bullish allowed at FG={fg_index}",
                    adjustment=0.0,
                    contrarian_signal=False,
                )
            
            else:  # side == "no"
                # Bearish: more willing when greedy, cautious when fearful
                if is_extreme_fear:
                    return FGFilterResult(
                        allowed=False,
                        reason=f"Extreme fear ({fg_index}) - avoid bearish",
                        adjustment=0.0,
                        contrarian_signal=True,
                    )
                return FGFilterResult(
                    allowed=True,
                    reason=f"Bearish allowed at FG={fg_index}",
                    adjustment=0.0,
                    contrarian_signal=False,
                )
        
        else:  # contrarian strategy
            # Contrarian: Go against the crowd
            if side == "yes" and is_extreme_fear:
                return FGFilterResult(
                    allowed=True,
                    reason=f"Contrarian bullish in fear ({fg_index})",
                    adjustment=self.contrarian_bias,
                    contrarian_signal=True,
                )
            
            if side == "no" and is_extreme_greed:
                return FGFilterResult(
                    allowed=True,
                    reason=f"Contrarian bearish in greed ({fg_index})",
                    adjustment=-self.contrarian_bias,
                    contrarian_signal=True,
                )
            
            return FGFilterResult(
                allowed=False,
                reason=f"No contrarian signal at FG={fg_index}",
                adjustment=0.0,
                contrarian_signal=False,
            )
    
    def adjust_prob(
        self,
        base_prob: float,
        fg_index: int,
        side: str,
    ) -> Tuple[float, str]:
        """
        Apply small contrarian bias to probability.
        
        When greed is high, nudge bullish prob down (crowd overoptimistic).
        When fear is high, nudge bullish prob up (crowd overpessimistic).
        
        Args:
            base_prob: Base probability 0-1
            fg_index: Fear/greed index
            side: 'yes' or 'no'
        
        Returns:
            (adjusted_prob, reasoning) tuple
        """
        bias = 0.0
        reason = "No FG adjustment"
        
        if fg_index >= self.extreme_greed:
            if side == "yes":
                bias = -self.contrarian_bias
                reason = f"Contrarian: reduce bullish prob in greed ({fg_index})"
            else:
                # Bearish in greed - crowd is wrong
                bias = self.contrarian_bias
                reason = f"Confirming: increase bearish prob in greed ({fg_index})"
        
        elif fg_index <= self.extreme_fear:
            if side == "yes":
                # Bullish in fear - contrarian opportunity
                bias = self.contrarian_bias
                reason = f"Contrarian: increase bullish prob in fear ({fg_index})"
            else:
                bias = -self.contrarian_bias
                reason = f"Confirming: reduce bearish prob in fear ({fg_index})"
        
        adjusted = max(0.01, min(0.99, base_prob + bias))
        
        return adjusted, reason
    
    def get_regime(self, fg_index: int) -> str:
        """Get FG regime classification."""
        if fg_index >= self.extreme_greed:
            return "extreme_greed"
        elif fg_index >= 60:
            return "greed"
        elif fg_index >= 40:
            return "neutral"
        elif fg_index >= self.extreme_fear:
            return "fear"
        else:
            return "extreme_fear"
    
    def get_position_scale(self, fg_index: int) -> float:
        """
        Get position size scaling factor based on FG.
        
        Returns 1.0 for neutral, 0.6 for extremes.
        """
        if fg_index >= self.extreme_greed or fg_index <= self.extreme_fear:
            return 0.6
        elif fg_index >= 70 or fg_index <= 30:
            return 0.8
        else:
            return 1.0


# Singleton accessor
_fg_filter: KalshiFGFilter = None
_fg_filter_lock = threading.Lock()

def get_fg_filter() -> KalshiFGFilter:
    """Get the singleton KalshiFGFilter instance."""
    global _fg_filter
    if _fg_filter is None:
        with _fg_filter_lock:
            if _fg_filter is None:
                _fg_filter = KalshiFGFilter()
    return _fg_filter


# ── Convenience functions ──────────────────────────────────────────

def fg_filter_trade(fg_index: int, side: str, strategy_type: str = "directional") -> bool:
    """
    Quick one-liner to check if trade is allowed.
    
    Returns:
        True if allowed
    """
    fg_filter = get_fg_filter()
    result = fg_filter.filter_trade(fg_index, side, strategy_type)
    return result.allowed


def fg_adjust_prob(base_prob: float, fg_index: int, side: str) -> Tuple[float, str]:
    """
    Quick probability adjustment.
    
    Returns:
        (adjusted_prob, reasoning)
    """
    fg_filter = get_fg_filter()
    return fg_filter.adjust_prob(base_prob, fg_index, side)
