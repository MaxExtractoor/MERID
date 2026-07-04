"""
Exit policy model and resolver for swing trading.

Defines exit conditions and policy evaluation logic.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, List
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
    CANDLE_REVERSAL = "candle_reversal"  # Research: Exit on candle pattern reversal
    LOSS_CAP = "loss_cap"  # 2026 FIX: Exit at 80% loss (PolyTrack research)


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
    
    def evaluate_loss_cap(self) -> bool:
        """
        Evaluate loss cap exit condition (2026 best practice).
        
        Based on PolyTrack research: "If a trade goes against you and reaches 80% loss
        (e.g., you bought YES at 50¢, it's now 10¢), consider exiting. The math says
        you're unlikely to recover."
        
        Exit if:
        - Unrealized PnL is >= 80% loss (current price <= 20% of entry price)
        
        Returns:
            True if loss cap should trigger exit
        """
        if self.unrealized_pnl_cents >= 0:
            # Not a losing position
            return False
        
        # Calculate loss percentage
        # For binary options: max loss = entry price * size (contracts * entry_price_cents)
        # Loss percentage = abs(unrealized_pnl) / max_loss
        try:
            entry_price_cents = self.position.avg_entry_price_cents
            if entry_price_cents <= 0:
                return False
            
            max_loss_cents = entry_price_cents * self.position.size  # Total max loss for position
            loss_pct = abs(self.unrealized_pnl_cents) / max_loss_cents
            
            # 2026 FIX: Exit at 80% loss (loss_pct >= 0.80)
            if loss_pct >= 0.80:
                return True
            
        except Exception as e:
            # If calculation fails, don't exit based on loss cap
            pass
        
        return False
    
    def evaluate_candle_reversal(self, candles: Optional[List] = None) -> bool:
        """
        Evaluate candle pattern reversal exit condition.
        
        Research: Candle patterns provide early signals of trend reversals,
        allowing proactive exit before price-based triggers fire.
        
        Exit if:
        - Candle reversal pattern detected AND
        - Pattern is opposite to position direction
        
        Args:
            candles: Recent candle data (OHLC)
            
        Returns:
            True if candle reversal should trigger exit
        """
        if candles is None or len(candles) < 2:
            return False
        
        try:
            from merid.position_management.candle_patterns import (
                get_candle_pattern_detector,
                Candle
            )
            
            # Convert candles to Candle objects
            candle_objects = []
            for c in candles:
                candle_objects.append(Candle(
                    open=c.get('open', 0),
                    high=c.get('high', 0),
                    low=c.get('low', 0),
                    close=c.get('close', 0),
                    timestamp=c.get('timestamp', 0)
                ))
            
            detector = get_candle_pattern_detector()
            position_side = "yes" if self.position.side.value == "yes" else "no"
            
            should_exit, pattern = detector.should_exit_on_reversal(
                position_side,
                candle_objects
            )
            
            return should_exit
        except Exception as e:
            # If candle detection fails, don't exit based on it
            return False
    
    def evaluate_adaptive_timing(self) -> bool:
        """
        Evaluate adaptive exit timing based on historical performance.
        
        Research: ML-based optimal expiry selection maximizes risk-adjusted returns
        by dynamically selecting the best contract expiry based on market conditions.
        
        Exit if:
        - Current hold duration exceeds optimal hold time based on historical data
        
        Returns:
            True if adaptive timing should trigger exit
        """
        try:
            from merid.position_management.adaptive_exit_timing import get_adaptive_exit_timing
            
            adaptive_timing = get_adaptive_exit_timing()
            position_side = "yes" if self.position.side.value == "yes" else "no"
            
            should_exit = adaptive_timing.should_exit_early(
                market_id=self.position.market_id,
                side=position_side,
                hold_duration_seconds=self.time_since_entry_seconds,
                current_r_multiple=self.r_multiple
            )
            
            return should_exit
        except Exception as e:
            # If adaptive timing fails, don't exit based on it
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
    
    def evaluate(self, current_edge_pct: Optional[float] = None, candles: Optional[List] = None) -> None:
        """
        Evaluate all exit policies and set action/reason.
        
        Priority order:
        1. RISK (highest priority - kill switch)
        2. LOSS_CAP (2026 FIX: exit at 80% loss to prevent catastrophic losses)
        3. CANDLE_REVERSAL (momentum reversal)
        4. ADAPTIVE_TIMING (historical performance-based)
        5. TIME_STOP
        6. EDGE_DECAY
        
        Args:
            current_edge_pct: Current edge percentage (optional, for edge decay check)
            candles: Recent candle data (optional, for candle reversal check)
        """
        # Check risk layer first (highest priority)
        if self.evaluate_risk():
            self.action = ExitAction.EXIT_MARKET
            self.reason = ExitReason.RISK
            return
        
        # 2026 FIX: Check loss cap (exit at 80% loss - PolyTrack research)
        if self.evaluate_loss_cap():
            self.action = ExitAction.EXIT_MARKET
            self.reason = ExitReason.LOSS_CAP
            return
        
        # Check candle reversal (momentum reversal signal)
        if self.evaluate_candle_reversal(candles):
            self.action = ExitAction.EXIT_MARKET
            self.reason = ExitReason.CANDLE_REVERSAL
            return
        
        # Check adaptive timing (historical performance-based)
        if self.evaluate_adaptive_timing():
            self.action = ExitAction.EXIT_MARKET
            self.reason = ExitReason.TIME_STOP  # Reuse TIME_STOP for adaptive timing
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
