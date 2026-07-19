"""
Exit policy model and resolver for swing trading.

Defines exit conditions and policy evaluation logic.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict
from merid.position_management.position import Position


class ExitAction(str, Enum):
    """Exit action types."""
    HOLD = "hold"
    EXIT_MARKET = "exit_market"


class ExitReason(str, Enum):
    """
    Exit reason types for both policy-layer and position-level exits.
    
    This enum contains ALL exit reasons used across the system:
    - Policy-layer exits: Evaluated by ExitPolicy.evaluate()
    - Position-level exits: Handled in position_monitor._check_position()
    
    EXIT POLICY PRECEDENCE (evaluated in this order by ExitPolicy.evaluate()):
    1. RISK - Global risk layer kill switch (highest priority)
    2. STALE_DATA - Exit when market data becomes stale (P0 safety fix)
    3. CANDLE_REVERSAL - Momentum reversal signal
    4. ADAPTIVE_TIMING - Historical performance-based optimal exit timing
    5. TIME_STOP - Volatility-adjusted time-based exit
    6. EDGE_DECAY - Exit when computed edge drops below threshold
    
    POSITION-LEVEL EXITS (handled in position_monitor before policy evaluation):
    - AUTO_EXIT_99C - 99c YES / 99c NO (cash out at near-settlement, highest priority after RISK)
    - EXTREME_PROFIT - 99c YES / 1c NO (extreme profit take, deprecated - use AUTO_EXIT_99C)
    - DYNAMIC_TAKE_PROFIT - Laddered exits
    - RATCHET_TRIM - Partial close at >80c
    - RATCHET_FLOOR - Profit protection
    - STOP_LOSS - Stop loss trigger
    - TAKE_PROFIT - Take profit trigger
    
    NOTE: SCALE_OUT and MANUAL are supported but not evaluated by default policy logic.
    """
    RISK = "risk"
    STALE_DATA = "stale_data"
    CANDLE_REVERSAL = "candle_reversal"
    ADAPTIVE_TIMING = "adaptive_timing"
    TIME_STOP = "time_stop"
    EDGE_DECAY = "edge_decay"
    SCALE_OUT = "scale_out"
    MANUAL = "manual"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    AUTO_EXIT_99C = "auto_exit_99c"  # Cash out at 99c (near-settlement)
    EXTREME_PROFIT = "extreme_profit"  # Deprecated - use AUTO_EXIT_99C
    DYNAMIC_TAKE_PROFIT = "dynamic_take_profit"
    RATCHET_TRIM = "ratchet_trim"
    RATCHET_FLOOR = "ratchet_floor"
    TRAIL = "trail"


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
    volatility_hold_multipliers: Dict[str, float] = field(default_factory=lambda: {
        "LOW": 1.0,
        "NORMAL": 0.75,
        "HIGH": 0.5,
        "EXTREME": 0.33,
    })
    
    # Outputs (deprecated - use evaluate() which returns ExitDecision)
    action: ExitAction = ExitAction.HOLD
    reason: Optional[ExitReason] = None
    
    
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
        - r_multiple < 0.5 (position not making meaningful progress)
        
        This preserves the "don't exit winners too early" principle while making
        the threshold explicit and unambiguous.
        
        Returns:
            True if time stop should trigger
        """
        effective_max_hold = self.get_effective_max_hold()
        
        if self.time_since_entry_seconds < effective_max_hold:
            return False
        
        # Exit if position is not making meaningful progress (< 0.5R)
        return self.r_multiple < 0.5
    
    
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
    
    def evaluate_stale_data(self, md_age_ms: int, max_age_ms: float) -> bool:
        """
        Evaluate stale data exit condition (P0 safety fix).
        
        CRITICAL FIX (2026-07-11): Auto-exit positions when market data becomes stale.
        This prevents holding exposure on untrustworthy data.
        
        Exit if:
        - MD age exceeds maximum allowed age for current time-to-expiry
        
        Args:
            md_age_ms: Current market data age in milliseconds
            max_age_ms: Maximum allowed age in milliseconds (from timing-aware SLA)
        
        Returns:
            True if stale data should trigger exit
        """
        if md_age_ms < 0:
            # No data - consider as stale
            return True
        
        if md_age_ms > max_age_ms:
            # Data is stale - force exit
            return True
        
        return False
    
    def evaluate(self, current_edge_pct: Optional[float] = None, candles: Optional[List] = None, md_age_ms: Optional[int] = None, max_age_ms: Optional[float] = None) -> Optional['ExitDecision']:
        """
        Evaluate all exit policies and return ExitDecision.
        
        This method handles ONLY policy-layer exits. Position-level exits
        (EXTREME_PROFIT, RATCHET_FLOOR, DYNAMIC_TAKE_PROFIT, etc.) are handled
        in position_monitor._check_position() before calling this class.
        
        EXIT POLICY PRECEDENCE (evaluated in this order):
        1. RISK - Global risk layer kill switch (highest priority)
        2. STALE_DATA - Exit when market data becomes stale (P0 safety fix)
        3. CANDLE_REVERSAL - Momentum reversal signal
        4. ADAPTIVE_TIMING - Historical performance-based optimal exit timing
        5. TIME_STOP - Volatility-adjusted time-based exit
        6. EDGE_DECAY - Exit when computed edge drops below threshold
        
        Args:
            current_edge_pct: Current edge percentage (optional, for edge decay check)
            candles: Recent candle data (optional, for candle reversal check)
            md_age_ms: Current market data age in milliseconds (optional, for stale data check)
            max_age_ms: Maximum allowed age in milliseconds (optional, for stale data check)
            
        Returns:
            ExitDecision if exit should occur, None if hold
        """
        # Lazy import to avoid circular dependency
        from merid.position_management.exit_decision import ExitDecision, ExitSourceLayer, get_priority_for_reason
        
        # Check risk layer first (highest priority)
        if self.evaluate_risk():
            self.action = ExitAction.EXIT_MARKET
            self.reason = ExitReason.RISK
            return ExitDecision(
                reason=ExitReason.RISK,
                priority=get_priority_for_reason(ExitReason.RISK),
                source_layer=ExitSourceLayer.POLICY_LAYER,
                exit_price_cents=self.current_price_cents,
                metadata={"kill_switch": self.risk_kill_switch}
            )
        
        # Check stale data (P0 safety fix - exit when MD becomes stale)
        if md_age_ms is not None and max_age_ms is not None:
            if self.evaluate_stale_data(md_age_ms, max_age_ms):
                self.action = ExitAction.EXIT_MARKET
                self.reason = ExitReason.STALE_DATA
                return ExitDecision(
                    reason=ExitReason.STALE_DATA,
                    priority=get_priority_for_reason(ExitReason.STALE_DATA),
                    source_layer=ExitSourceLayer.POLICY_LAYER,
                    exit_price_cents=self.current_price_cents,
                    metadata={
                        "md_age_ms": md_age_ms,
                        "max_age_ms": max_age_ms,
                        "time_to_expiry_seconds": self.time_to_expiry_seconds
                    }
                )
        
        # Check candle reversal (momentum reversal signal)
        if self.evaluate_candle_reversal(candles):
            self.action = ExitAction.EXIT_MARKET
            self.reason = ExitReason.CANDLE_REVERSAL
            return ExitDecision(
                reason=ExitReason.CANDLE_REVERSAL,
                priority=get_priority_for_reason(ExitReason.CANDLE_REVERSAL),
                source_layer=ExitSourceLayer.POLICY_LAYER,
                exit_price_cents=self.current_price_cents,
                metadata={"candles_count": len(candles) if candles else 0}
            )
        
        # Check adaptive timing (historical performance-based)
        if self.evaluate_adaptive_timing():
            self.action = ExitAction.EXIT_MARKET
            self.reason = ExitReason.ADAPTIVE_TIMING
            return ExitDecision(
                reason=ExitReason.ADAPTIVE_TIMING,
                priority=get_priority_for_reason(ExitReason.ADAPTIVE_TIMING),
                source_layer=ExitSourceLayer.POLICY_LAYER,
                exit_price_cents=self.current_price_cents,
                metadata={"time_since_entry_seconds": self.time_since_entry_seconds}
            )
        
        # Check time stop
        if self.evaluate_time_stop():
            self.action = ExitAction.EXIT_MARKET
            self.reason = ExitReason.TIME_STOP
            return ExitDecision(
                reason=ExitReason.TIME_STOP,
                priority=get_priority_for_reason(ExitReason.TIME_STOP),
                source_layer=ExitSourceLayer.POLICY_LAYER,
                exit_price_cents=self.current_price_cents,
                metadata={
                    "time_since_entry_seconds": self.time_since_entry_seconds,
                    "effective_max_hold": self.get_effective_max_hold(),
                    "r_multiple": self.r_multiple,
                    "volatility_regime": self.volatility_regime
                }
            )
        
        # Check edge decay (if edge provided)
        if current_edge_pct is not None and self.evaluate_edge_decay(current_edge_pct):
            self.action = ExitAction.EXIT_MARKET
            self.reason = ExitReason.EDGE_DECAY
            return ExitDecision(
                reason=ExitReason.EDGE_DECAY,
                priority=get_priority_for_reason(ExitReason.EDGE_DECAY),
                source_layer=ExitSourceLayer.POLICY_LAYER,
                exit_price_cents=self.current_price_cents,
                metadata={
                    "current_edge_pct": current_edge_pct,
                    "min_edge_threshold": self.min_edge_threshold
                }
            )
        
        # No exit condition met
        self.action = ExitAction.HOLD
        self.reason = None
        return None
        return None
