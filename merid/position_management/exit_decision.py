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
    9. LOSS_CUT_40PCT (-40% loss cut when thesis changes) - 58
    10. TAKE_PROFIT - 55
    11. CANDLE_REVERSAL (momentum reversal) - 50
    12. ADAPTIVE_TIMING (historical performance) - 45
    13. TIME_STOP (volatility-adjusted time-based) - 40
    14. TRAIL (trailing stop) - 36
    15. EDGE_DECAY (edge threshold) - 35
    16. OPPORTUNITY_COST (better opportunity exists) - 33
    17. SCALE_OUT (partial exit at 1.5-2R) - 30
    18. MANUAL - 20
    19. MODEL_INVALIDATION_LOSS_EXIT (thesis collapse at a loss) - 57
    20. SETTLEMENT_GUARD (forced T-30s exit) - 94
    21. MARKET_EXPIRED (settlement reconciliation) - 93
    22. LOSS_CAP (break-even loss cap) - 56
    """
    AUTO_EXIT_99C = 95
    RISK = 100
    EXTREME_PROFIT = 90
    STALE_DATA = 85
    MODEL_INVALIDATION_LOSS_EXIT = 57
    SETTLEMENT_GUARD = 94
    MARKET_EXPIRED = 93
    LOSS_CAP = 56
    DYNAMIC_TAKE_PROFIT = 80
    RATCHET_TRIM = 75
    RATCHET_FLOOR = 70
    STOP_LOSS = 60
    LOSS_CUT_40PCT = 58  # 2026-08-01: -40% loss cut when thesis changes
    TAKE_PROFIT = 55
    CANDLE_REVERSAL = 50
    ADAPTIVE_TIMING = 45
    TIME_STOP = 40
    TRAIL = 36
    CURRENT_EDGE_REVERSAL = 37  # 2026-08-28: mark-to-model edge realization
    EDGE_DECAY = 35
    OPPORTUNITY_COST = 33  # 2026-08-01: Exit when better opportunity exists
    SCALE_OUT = 30
    CONTINUATION_STOP = 25  # 2026-08-25: 5m underlying continuation stop
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
    Map ExitReason to ExitPriority.
    
    Args:
        reason: Exit reason
        
    Returns:
        Exit priority value
    """
    priority_map = {
        ExitReason.RISK: ExitPriority.RISK,
        ExitReason.AUTO_EXIT_99C: ExitPriority.AUTO_EXIT_99C,
        ExitReason.EXTREME_PROFIT: ExitPriority.EXTREME_PROFIT,
        ExitReason.STALE_DATA: ExitPriority.STALE_DATA,
        ExitReason.DYNAMIC_TAKE_PROFIT: ExitPriority.DYNAMIC_TAKE_PROFIT,
        ExitReason.RATCHET_TRIM: ExitPriority.RATCHET_TRIM,
        ExitReason.RATCHET_FLOOR: ExitPriority.RATCHET_FLOOR,
        ExitReason.STOP_LOSS: ExitPriority.STOP_LOSS,
        ExitReason.LOSS_CUT_40PCT: ExitPriority.LOSS_CUT_40PCT,
        ExitReason.TAKE_PROFIT: ExitPriority.TAKE_PROFIT,
        ExitReason.CANDLE_REVERSAL: ExitPriority.CANDLE_REVERSAL,
        ExitReason.ADAPTIVE_TIMING: ExitPriority.ADAPTIVE_TIMING,
        ExitReason.TIME_STOP: ExitPriority.TIME_STOP,
        ExitReason.CURRENT_EDGE_REVERSAL: ExitPriority.CURRENT_EDGE_REVERSAL,
        ExitReason.EDGE_DECAY: ExitPriority.EDGE_DECAY,
        ExitReason.OPPORTUNITY_COST: ExitPriority.OPPORTUNITY_COST,
        ExitReason.SCALE_OUT: ExitPriority.SCALE_OUT,
        ExitReason.TRAIL: ExitPriority.TRAIL,
        ExitReason.CONTINUATION_STOP: ExitPriority.CONTINUATION_STOP,
        ExitReason.MANUAL: ExitPriority.MANUAL,
        ExitReason.MODEL_INVALIDATION_LOSS_EXIT: ExitPriority.MODEL_INVALIDATION_LOSS_EXIT,
        ExitReason.SETTLEMENT_GUARD: ExitPriority.SETTLEMENT_GUARD,
        ExitReason.MARKET_EXPIRED: ExitPriority.MARKET_EXPIRED,
        ExitReason.LOSS_CAP: ExitPriority.LOSS_CAP,
    }
    
    return priority_map.get(reason, ExitPriority.MANUAL)
