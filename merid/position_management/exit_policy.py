"""
Exit policy model and resolver for swing trading.

Defines exit conditions and policy evaluation logic.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional
from merid.position_management.position import Position


class ExitAction(str, Enum):
    """Exit action types."""
    HOLD = "hold"
    EXIT_MARKET = "exit_market"


class ExitReason(str, Enum):
    """Exit reason types."""
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    TRAIL = "trail"
    TIME_STOP = "time_stop"
    EDGE_DECAY = "edge_decay"
    RISK = "risk"
    MANUAL = "manual"
    SCALE_OUT = "scale_out"  # Research: Partial exit at 1.5-2R (Pay Yourself strategy)


@dataclass
class ExitPolicy:
    """
    Exit policy evaluation inputs and outputs.
    
    Evaluates whether a position should be held or exited based on:
    - Current PnL and R-multiple
    - Time since entry and time to expiry
    - Volatility regime
    - Risk layer signals
    """
    # Inputs
    position: Position
    current_price_cents: int
    unrealized_pnl_cents: int
    r_multiple: float
    time_since_entry_seconds: float
    time_to_expiry_seconds: float
    volatility_regime: Optional[str] = None  # e.g., "LOW", "NORMAL", "HIGH", "EXTREME"
    
    # Policy parameters (configurable)
    max_hold_seconds: float = 900.0  # Default 15 minutes
    min_edge_threshold: float = 0.0  # Minimum edge to hold position
    risk_kill_switch: bool = False  # Global risk layer kill switch
    
    # Volatility-based hold time adjustment
    # HIGH vol: shorter holds (300-600s), NORMAL: 600-900s, LOW: 900-1200s
    volatility_hold_multipliers: dict = None  # Will be set in __post_init__
    
    # Outputs
    action: ExitAction = ExitAction.HOLD
    reason: Optional[ExitReason] = None
    
    def __post_init__(self):
        """Initialize volatility hold multipliers if not set."""
        if self.volatility_hold_multipliers is None:
            self.volatility_hold_multipliers = {
                "LOW": 1.0,      # 100% of base max_hold (900s)
                "NORMAL": 0.75,  # 75% of base max_hold (675s)
                "HIGH": 0.5,     # 50% of base max_hold (450s)
                "EXTREME": 0.33, # 33% of base max_hold (300s)
            }
    
    def get_effective_max_hold(self) -> float:
        """
        Get effective max hold time adjusted for volatility regime.
        
        Returns:
            Effective max hold time in seconds
        """
        if self.volatility_regime and self.volatility_regime in self.volatility_hold_multipliers:
            multiplier = self.volatility_hold_multipliers[self.volatility_regime]
            return self.max_hold_seconds * multiplier
        return self.max_hold_seconds
    
    def evaluate_time_stop(self) -> bool:
        """
        Evaluate time-based exit condition with volatility adjustment.
        
        Exit if:
        - time_since_entry >= effective_max_hold (volatility-adjusted) AND
        - r_multiple < 0 (losing position) OR
        - r_multiple between 0 and +0.5R (no progress)
        
        Returns:
            True if time stop should trigger
        """
        effective_max_hold = self.get_effective_max_hold()
        
        if self.time_since_entry_seconds < effective_max_hold:
            return False
        
        # Time stop only triggers if position is not making progress
        if self.r_multiple < 0:
            # Losing position - exit to avoid late noise
            return True
        elif 0 <= self.r_multiple < 0.5:
            # No meaningful progress - exit to avoid late noise
            return True
        
        return False
    
    def evaluate_edge_decay(self, current_edge_pct: float) -> bool:
        """
        Evaluate edge decay exit condition.
        
        Exit if computed net edge since entry drops below threshold.
        
        Args:
            current_edge_pct: Current edge percentage
            
        Returns:
            True if edge decay should trigger exit
        """
        if current_edge_pct < self.min_edge_threshold:
            return True
        return False
    
    def evaluate_risk(self) -> bool:
        """
        Evaluate risk layer exit condition.
        
        Exit if global risk layer signals kill switch.
        
        Returns:
            True if risk layer should trigger exit
        """
        return self.risk_kill_switch
    
    def evaluate(self, current_edge_pct: Optional[float] = None) -> None:
        """
        Evaluate all exit policies and set action/reason.
        
        Priority order:
        1. RISK (highest priority - kill switch)
        2. TIME_STOP
        3. EDGE_DECAY
        
        Args:
            current_edge_pct: Current edge percentage (optional, for edge decay check)
        """
        # Check risk layer first (highest priority)
        if self.evaluate_risk():
            self.action = ExitAction.EXIT_MARKET
            self.reason = ExitReason.RISK
            return
        
        # Check time stop
        if self.evaluate_time_stop():
            self.action = ExitAction.EXIT_MARKET
            self.reason = ExitReason.TIME_STOP
            return
        
        # Check edge decay (if edge provided)
        if current_edge_pct is not None and self.evaluate_edge_decay(current_edge_pct):
            self.action = ExitAction.EXIT_MARKET
            self.reason = ExitReason.EDGE_DECAY
            return
        
        # No exit condition met
        self.action = ExitAction.HOLD
        self.reason = None
