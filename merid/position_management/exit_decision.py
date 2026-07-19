"""
Exit decision DTO and precedence constants.

Provides a unified exit decision structure with single source of truth for precedence.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional
from merid.position_management.exit_policy import ExitReason


class ExitSourceLayer(str, Enum):
    """Source layer for exit decisions."""
    POSITION_LEVEL = "position_level"  # Price-structure exits (extreme profit, ratchets, TP/SL)
    POLICY_LAYER = "policy_layer"  # Abstract signals (risk, stale data, timing, edge)


class ExitPriority(int, Enum):
    """
    Exit precedence priority (higher number = higher priority).
    
    This is the SINGLE SOURCE OF TRUTH for exit precedence across the entire system.
    Both position-level and policy-layer exits must use these priorities.
    
    EXIT PRECEDENCE ORDER (highest to lowest priority):
    1. RISK (kill switch) - 100
    2. AUTO_EXIT_99C (99c YES / 99c NO - cash out at near-settlement) - 95
    3. EXTREME_PROFIT (99c YES / 1c NO - deprecated, use AUTO_EXIT_99C) - 90
    4. STALE_DATA (market data staleness) - 85
    5. DYNAMIC_TAKE_PROFIT (laddered exits) - 80
    6. RATCHET_TRIM (partial close at >80c) - 75
    7. RATCHET_FLOOR (profit protection) - 70
    8. STOP_LOSS - 60
    9. TAKE_PROFIT - 55
    10. CANDLE_REVERSAL (momentum reversal) - 50
    11. ADAPTIVE_TIMING (historical performance) - 45
    12. TIME_STOP (volatility-adjusted time-based) - 40
    13. EDGE_DECAY (edge threshold) - 35
    14. SCALE_OUT (partial exit at 1.5-2R) - 30
    15. TRAIL (trailing stop) - 25
    16. MANUAL - 20
    """
    AUTO_EXIT_99C = 95
    RISK = 100
    EXTREME_PROFIT = 90
    STALE_DATA = 85
    DYNAMIC_TAKE_PROFIT = 80
    RATCHET_TRIM = 75
    RATCHET_FLOOR = 70
    STOP_LOSS = 60
    TAKE_PROFIT = 55
    CANDLE_REVERSAL = 50
    ADAPTIVE_TIMING = 45
    TIME_STOP = 40
    EDGE_DECAY = 35
    SCALE_OUT = 30
    TRAIL = 25
    MANUAL = 20


@dataclass
class ExitDecision:
    """
    Exit decision DTO with reason, priority, and source layer.
    
    Both position_monitor and ExitPolicy emit ExitDecision objects.
    A centralized resolver merges multiple decisions based on priority.
    """
    reason: ExitReason
    priority: ExitPriority
    source_layer: ExitSourceLayer
    exit_price_cents: int
    contracts_to_close: Optional[int] = None  # None = full position
    metadata: Optional[dict] = None  # Additional context (MD age, SLA, etc.)
    
    def __post_init__(self):
        """Initialize metadata dict if not provided."""
        if self.metadata is None:
            self.metadata = {}
    
    def is_full_exit(self) -> bool:
        """Check if this is a full position exit."""
        return self.contracts_to_close is None
    
    def is_partial_exit(self) -> bool:
        """Check if this is a partial position exit."""
        return self.contracts_to_close is not None
    
    def should_override(self, other: 'ExitDecision') -> bool:
        """
        Check if this decision should override another based on priority.
        
        Args:
            other: Another ExitDecision to compare against
            
        Returns:
            True if this decision has higher priority
        """
        return self.priority.value > other.priority.value


def get_priority_for_reason(reason: ExitReason) -> ExitPriority:
    """
    Get priority for a given exit reason.
    
    This maps ExitReason enum values to ExitPriority constants.
    Includes all exits that exist in the ExitReason enum.
    
    Args:
        reason: Exit reason
        
    Returns:
        Exit priority value
    """
    # Map all exits that exist in ExitReason enum
    priority_map = {
        ExitReason.RISK: ExitPriority.RISK,
        ExitReason.AUTO_EXIT_99C: ExitPriority.AUTO_EXIT_99C,
        ExitReason.EXTREME_PROFIT: ExitPriority.EXTREME_PROFIT,
        ExitReason.STALE_DATA: ExitPriority.STALE_DATA,
        ExitReason.CANDLE_REVERSAL: ExitPriority.CANDLE_REVERSAL,
        ExitReason.ADAPTIVE_TIMING: ExitPriority.ADAPTIVE_TIMING,
        ExitReason.TIME_STOP: ExitPriority.TIME_STOP,
        ExitReason.EDGE_DECAY: ExitPriority.EDGE_DECAY,
        ExitReason.SCALE_OUT: ExitPriority.SCALE_OUT,
        ExitReason.MANUAL: ExitPriority.MANUAL,
        ExitReason.STOP_LOSS: ExitPriority.STOP_LOSS,
        ExitReason.TAKE_PROFIT: ExitPriority.TAKE_PROFIT,
        ExitReason.DYNAMIC_TAKE_PROFIT: ExitPriority.DYNAMIC_TAKE_PROFIT,
        ExitReason.RATCHET_TRIM: ExitPriority.RATCHET_TRIM,
        ExitReason.RATCHET_FLOOR: ExitPriority.RATCHET_FLOOR,
        ExitReason.TRAIL: ExitPriority.TRAIL,
    }
    
    return priority_map.get(reason, ExitPriority.MANUAL)
