"""
Debate Risk Configuration - Shared constants for UI and backend alignment
Ensures consistent debate risk adjustment behavior across frontend and backend.
"""

from dataclasses import dataclass
from typing import Final

@dataclass
class DebateRiskConfig:
    """Configuration for debate risk adjustments - shared between UI and backend"""
    
    # Critical alert reductions
    CRITICAL_REDUCTION_PER_ALERT: Final[float] = 0.20  # 20% reduction per critical alert
    MAX_CRITICAL_ALERTS: Final[int] = 5                # Cap critical alerts for safety
    MIN_CRITICAL_MULTIPLIER: Final[float] = 0.10       # Minimum 10% of original size
    
    # Warning alert reductions  
    WARNING_REDUCTION_PER_ALERT: Final[float] = 0.10   # 10% reduction per warning alert
    MAX_WARNING_ALERTS: Final[int] = 3                # Cap warning alerts for safety
    MIN_WARNING_MULTIPLIER: Final[float] = 0.50        # Minimum 50% of original size
    
    # Unknown/missing context
    UNKNOWN_MULTIPLIER: Final[float] = 0.80            # Conservative reduction for unknown status
    
    # Cache and performance
    CACHE_TIMEOUT_SECONDS: Final[int] = 300           # 5 minutes cache timeout
    
    # Safety thresholds
    MIN_POSITION_SIZE: Final[int] = 1                 # Minimum 1 contract
    MAX_POSITION_REDUCTION: Final[float] = 0.90       # Maximum 90% reduction

# Global instance for consistent access
DEBATE_RISK_CONFIG = DebateRiskConfig()

# Export constants for easy import
CRITICAL_REDUCTION_PER_ALERT = DEBATE_RISK_CONFIG.CRITICAL_REDUCTION_PER_ALERT
WARNING_REDUCTION_PER_ALERT = DEBATE_RISK_CONFIG.WARNING_REDUCTION_PER_ALERT
MIN_CRITICAL_MULTIPLIER = DEBATE_RISK_CONFIG.MIN_CRITICAL_MULTIPLIER
MIN_WARNING_MULTIPLIER = DEBATE_RISK_CONFIG.MIN_WARNING_MULTIPLIER
UNKNOWN_MULTIPLIER = DEBATE_RISK_CONFIG.UNKNOWN_MULTIPLIER
