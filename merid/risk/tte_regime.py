"""
TTE-Specific Behavior Near Expiry

Defines special trading behavior for contracts near expiry (<5 minutes).
Near-expiry contracts have different risk characteristics:
- Higher time decay (theta)
- Lower liquidity
- Higher volatility
- Different optimal sizing strategies
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from utils.logger import get_logger

logger = get_logger("merid.risk.tte_regime")


class TTERegime(Enum):
    """Time-to-expiry regime classification."""
    NORMAL = "normal"  # > 10 minutes to expiry
    APPROACHING = "approaching"  # 5-10 minutes to expiry
    CRITICAL = "critical"  # < 5 minutes to expiry
    TERMINAL = "terminal"  # < 2 minutes to expiry


@dataclass
class TTERegimeConfig:
    """Configuration for TTE-specific behavior."""
    # Time thresholds (minutes)
    approaching_threshold: float = 10.0  # Below this = approaching regime
    critical_threshold: float = 5.0  # Below this = critical regime
    terminal_threshold: float = 2.0  # Below this = terminal regime
    
    # Position sizing multipliers
    normal_size_multiplier: float = 1.0
    approaching_size_multiplier: float = 0.75
    critical_size_multiplier: float = 0.5
    terminal_size_multiplier: float = 0.25
    
    # Edge threshold adjustments
    normal_edge_multiplier: float = 1.0
    approaching_edge_multiplier: float = 1.2  # Require higher edge
    critical_edge_multiplier: float = 1.5  # Require much higher edge
    terminal_edge_multiplier: float = 2.0  # Require very high edge
    
    # Spread tolerance (aligned with 2026 industry standards for 15m binary options)
    # Updated 2026-07-01: Reduced from 40-10c to 10-5c to align with industry research
    # Industry standard: 5-10c maximum spread for 15m binary options
    # NOTE: These TTE-specific thresholds are intentionally tighter than dynamic threshold manager
    # because markets close to expiry have less time to recover from wide spreads and higher illiquidity risk
    normal_max_spread_cents: int = 10
    approaching_max_spread_cents: int = 8
    critical_max_spread_cents: int = 6
    terminal_max_spread_cents: int = 5
    
    # Minimum depth requirements (aligned with profile guardrails to avoid conflicts)
    # Profile: Tier1 (BTC/ETH) = 10, Tier2 (SOL/XRP/DOGE) = 5
    # TTE regime now uses profile depth instead of scaling requirements
    normal_min_depth: int = 5  # Aligned with profile min_depth_contracts
    approaching_min_depth: int = 5  # No longer scales - use profile tier-based depth
    critical_min_depth: int = 5  # No longer scales - use profile tier-based depth
    terminal_min_depth: int = 5  # No longer scales - use profile tier-based depth


class TTERegimeClassifier:
    """Classifier for TTE regimes."""
    
    def __init__(self, config: Optional[TTERegimeConfig] = None):
        self.config = config or TTERegimeConfig()
    
    def classify(self, tte_seconds: float) -> TTERegime:
        """Classify TTE into regime based on seconds to expiry.
        
        Args:
            tte_seconds: Time to expiry in seconds
        
        Returns:
            TTERegime classification
        """
        tte_minutes = tte_seconds / 60.0
        
        if tte_minutes < self.config.terminal_threshold:
            return TTERegime.TERMINAL
        elif tte_minutes < self.config.critical_threshold:
            return TTERegime.CRITICAL
        elif tte_minutes < self.config.approaching_threshold:
            return TTERegime.APPROACHING
        else:
            return TTERegime.NORMAL
    
    def get_size_multiplier(self, tte_seconds: float) -> float:
        """Get position size multiplier based on TTE regime.
        
        Args:
            tte_seconds: Time to expiry in seconds
        
        Returns:
            Size multiplier (0.0 to 1.0)
        """
        regime = self.classify(tte_seconds)
        
        if regime == TTERegime.NORMAL:
            return self.config.normal_size_multiplier
        elif regime == TTERegime.APPROACHING:
            return self.config.approaching_size_multiplier
        elif regime == TTERegime.CRITICAL:
            return self.config.critical_size_multiplier
        else:  # TERMINAL
            return self.config.terminal_size_multiplier
    
    def get_edge_multiplier(self, tte_seconds: float) -> float:
        """Get required edge multiplier based on TTE regime.
        
        Args:
            tte_seconds: Time to expiry in seconds
        
        Returns:
            Edge multiplier (>= 1.0, higher = more edge required)
        """
        regime = self.classify(tte_seconds)
        
        if regime == TTERegime.NORMAL:
            return self.config.normal_edge_multiplier
        elif regime == TTERegime.APPROACHING:
            return self.config.approaching_edge_multiplier
        elif regime == TTERegime.CRITICAL:
            return self.config.critical_edge_multiplier
        else:  # TERMINAL
            return self.config.terminal_edge_multiplier
    
    def get_max_spread(self, tte_seconds: float) -> int:
        """Get maximum allowed spread based on TTE regime.
        
        Args:
            tte_seconds: Time to expiry in seconds
        
        Returns:
            Maximum spread in cents
        """
        regime = self.classify(tte_seconds)
        
        if regime == TTERegime.NORMAL:
            return self.config.normal_max_spread_cents
        elif regime == TTERegime.APPROACHING:
            return self.config.approaching_max_spread_cents
        elif regime == TTERegime.CRITICAL:
            return self.config.critical_max_spread_cents
        else:  # TERMINAL
            return self.config.terminal_max_spread_cents
    
    def get_min_depth(self, tte_seconds: float) -> int:
        """Get minimum required depth based on TTE regime.
        
        Args:
            tte_seconds: Time to expiry in seconds
        
        Returns:
            Minimum depth in contracts
        """
        regime = self.classify(tte_seconds)
        
        if regime == TTERegime.NORMAL:
            return self.config.normal_min_depth
        elif regime == TTERegime.APPROACHING:
            return self.config.approaching_min_depth
        elif regime == TTERegime.CRITICAL:
            return self.config.critical_min_depth
        else:  # TERMINAL
            return self.config.terminal_min_depth
    
    def should_allow_entry(self, tte_seconds: float) -> bool:
        """Check if entry is allowed based on TTE regime.
        
        Args:
            tte_seconds: Time to expiry in seconds
        
        Returns:
            True if entry allowed, False otherwise
        """
        regime = self.classify(tte_seconds)
        
        # Allow entry in all regimes except terminal (too risky)
        return regime != TTERegime.TERMINAL


def get_tte_classifier(config: Optional[TTERegimeConfig] = None) -> TTERegimeClassifier:
    """Get the TTE regime classifier singleton."""
    global _classifier
    if _classifier is None:
        _classifier = TTERegimeClassifier(config)
    return _classifier


_classifier: Optional[TTERegimeClassifier] = None
