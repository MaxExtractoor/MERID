"""Dynamic Take-Profit Engine — R-multiple based profit targets.

This module implements the production scalping take-profit regime:
- Base TP: 1.0-1.5R for fast scalping
- Stretch TP: 2.0-3.0R for high confidence signals
- Confidence/Kelly fraction modulates between base and stretch

TP STRATEGY PRECEDENCE:
For 15m Kalshi crypto agents, the take-profit strategy is determined by:
1. Agent config take_profit.enabled (kalshi_agent_grid.yaml) - master switch
2. Time-based R-multiple (agent config take_profit.time_based_r_multiple) - overrides based on time to expiry
3. DynamicTakeProfitEngine.compute_tp() - computes TP price based on confidence/Kelly
4. Trailing stop (agent config take_profit.trailing_enabled) - activates after TP trigger

Precedence order: Time-based R-multiple > DynamicTakeProfitEngine > Static TP from config

Usage::
    from merid.prediction.dynamic_takeprofit import DynamicTakeProfitEngine, TakeProfitLevel
    
    engine = DynamicTakeProfitEngine()
    tp_price = engine.compute_tp(
        entry_price=0.55,
        stop_price=0.50,
        direction='LONG',
        confidence=0.75,
        kelly_fraction=0.65
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from utils.logger import get_logger

logger = get_logger("merid.prediction.dynamic_takeprofit")


class TakeProfitLevel(Enum):
    """Profit target aggressiveness levels."""
    BASE = "base"           # 1.0-1.5R fast scalping
    STRETCH = "stretch"     # 2.0-3.0R high confidence
    AGGRESSIVE = "aggressive"  # 2.5-3.5R exceptional signals


@dataclass(frozen=True)
class TakeProfitPlan:
    """Computed take-profit plan for a trade."""
    tp_price: float
    tp_r_multiple: float
    tp_level: TakeProfitLevel
    trailing_trigger_r: Optional[float] = None  # When to start trailing (e.g., 1.0R)
    trailing_distance_r: Optional[float] = None  # Trailing stop distance in R
    # Ratchet profit floor parameters (research-backed profit locking)
    ratchet_enabled: bool = False  # Whether ratchet is enabled for this position
    ratchet_activation_threshold_cents: int = 85  # Price threshold to activate ratchet
    ratchet_floor_offset_cents: int = 5  # Floor offset below activation
    ratchet_force_exit_on_breach: bool = True  # Mandatory exit on floor breach
    ratchet_min_hold_after_activation_sec: int = 30  # Minimum hold after activation
    
    def to_dict(self) -> dict:
        return {
            "tp_price": self.tp_price,
            "tp_r_multiple": self.tp_r_multiple,
            "tp_level": self.tp_level.value,
            "trailing_trigger_r": self.trailing_trigger_r,
            "trailing_distance_r": self.trailing_distance_r,
            "ratchet_enabled": self.ratchet_enabled,
            "ratchet_activation_threshold_cents": self.ratchet_activation_threshold_cents,
            "ratchet_floor_offset_cents": self.ratchet_floor_offset_cents,
            "ratchet_force_exit_on_breach": self.ratchet_force_exit_on_breach,
            "ratchet_min_hold_after_activation_sec": self.ratchet_min_hold_after_activation_sec,
        }


class DynamicTakeProfitEngine:
    """Dynamic take-profit engine based on R-multiples and confidence.
    
    PRODUCTION RISK REGIME (per user spec):
    - Confidence / Kelly ≤ 0.3 → 1.0R hard TP (fast exit)
    - 0.3 < Confidence ≤ 0.6 → 1.5R base TP, trailing once 1R hit
    - > 0.6 → 2.0-3.0R stretch TP, aggressive trailing
    
    R-multiple is computed as: (TP - Entry) / (Entry - Stop)
    """
    
    # TP levels mapped to confidence thresholds
    CONFIDENCE_LOW = 0.3
    CONFIDENCE_MID = 0.6
    CONFIDENCE_HIGH = 0.8
    
    # R-multiple targets
    R_BASE_LOW = 1.0      # ≤ 0.3 confidence
    R_BASE_MID = 1.5      # 0.3-0.6 confidence
    R_STRETCH_MIN = 2.0   # > 0.6 confidence (base)
    R_STRETCH_MAX = 3.0   # > 0.9 confidence (max)
    
    # Trailing parameters
    TRAIL_TRIGGER_BASE = 1.0   # Start trailing at 1R profit
    TRAIL_DISTANCE_BASE = 0.5  # Trail 0.5R behind price
    TRAIL_TRIGGER_STRETCH = 1.5  # Start trailing later for stretch targets
    TRAIL_DISTANCE_STRETCH = 0.75  # Wider trail for stretch
    
    def __init__(self):
        pass
    
    def compute_tp(
        self,
        entry_price: float,
        stop_price: float,
        direction: str,
        confidence: float,
        kelly_fraction: Optional[float] = None,
        use_60_70_rule: bool = True,  # Enable 60-70% profit capture rule
        time_to_expiry_seconds: Optional[float] = None,  # For TTE compression
        ratchet_enabled: bool = True,  # Enable ratchet profit floor
        ratchet_activation_threshold_cents: int = 85,
        ratchet_floor_offset_cents: int = 5,
        ratchet_force_exit_on_breach: bool = True,
        ratchet_min_hold_after_activation_sec: int = 30,
    ) -> TakeProfitPlan:
        """Compute dynamic take-profit price based on R-multiple and confidence.
        
        Args:
            entry_price: Entry price in cents or dollars
            stop_price: Stop loss price
            direction: 'LONG' (buy YES) or 'SHORT' (buy NO)
            confidence: Signal confidence 0-1 (can use Kelly fraction)
            kelly_fraction: Optional Kelly fraction 0-1 (if None, uses confidence)
            use_60_70_rule: Apply 60-70% profit capture rule (research-backed)
            time_to_expiry_seconds: Time to expiry in seconds (for TTE compression)
            
        Returns:
            TakeProfitPlan with computed TP price and parameters
        """
        # Use confidence as fallback if Kelly not provided
        effective_confidence = kelly_fraction if kelly_fraction is not None else confidence
        effective_confidence = max(0.0, min(effective_confidence, 1.0))
        
        # Calculate risk per contract (R)
        risk_per_contract = abs(entry_price - stop_price)
        if risk_per_contract <= 0:
            # Fallback: use 0.5% of entry price as minimum risk
            risk_per_contract = entry_price * 0.005
            logger.warning(
                "[DTP] Zero risk distance, using fallback 0.5%%: entry=%.3f, stop=%.3f",
                entry_price, stop_price
            )
        
        # Map confidence to R-multiple and TP level
        r_multiple, tp_level, trail_trigger, trail_distance = self._map_confidence_to_r(
            effective_confidence
        )
        
        # Apply time-to-expiry compression for trailing parameters
        # Research: Compress AT and TD as resolution approaches (Prevayo)
        if time_to_expiry_seconds is not None and trail_trigger is not None:
            trail_trigger, trail_distance = self._apply_tte_compression(
                trail_trigger=trail_trigger,
                trail_distance=trail_distance,
                time_to_expiry_seconds=time_to_expiry_seconds
            )

        # Calculate TP offset from entry
        tp_offset = r_multiple * risk_per_contract
        
        # Apply direction
        direction_upper = direction.upper()
        if direction_upper == 'LONG':
            tp_price_r_based = entry_price + tp_offset
        elif direction_upper == 'SHORT':
            tp_price_r_based = entry_price - tp_offset
        else:
            raise ValueError(f"Invalid direction: {direction}. Use 'LONG' or 'SHORT'")
        
        # Apply 60-70% profit capture rule (research-backed)
        # This prevents holding for last 20-30% of gain which takes disproportionately longer
        if use_60_70_rule:
            tp_price = self._apply_60_70_rule(
                entry_price=entry_price,
                tp_price_r_based=tp_price_r_based,
                direction=direction_upper
            )
            logger.info(
                "[DTP-60-70-RULE] entry=%.3f r_based_tp=%.3f adjusted_tp=%.3f (capturing 60-70%% of max gain)",
                entry_price, tp_price_r_based, tp_price
            )
        else:
            tp_price = tp_price_r_based

        logger.info(
            "[CONF-TP-SL] confidence=%.2f r_multiple=%.2f tp_level=%s trail_trigger=%.2f trail_distance=%.2f",
            effective_confidence, r_multiple, tp_level.value, trail_trigger or 0, trail_distance or 0
        )
        
        logger.debug(
            "[DTP] %s: entry=%.3f, stop=%.3f, conf=%.2f, R=%.2f, tp=%.3f (%s)",
            direction, entry_price, stop_price, effective_confidence,
            r_multiple, tp_price, tp_level.value
        )
        
        return TakeProfitPlan(
            tp_price=tp_price,
            tp_r_multiple=r_multiple,
            tp_level=tp_level,
            trailing_trigger_r=trail_trigger,
            trailing_distance_r=trail_distance,
            ratchet_enabled=ratchet_enabled,
            ratchet_activation_threshold_cents=ratchet_activation_threshold_cents,
            ratchet_floor_offset_cents=ratchet_floor_offset_cents,
            ratchet_force_exit_on_breach=ratchet_force_exit_on_breach,
            ratchet_min_hold_after_activation_sec=ratchet_min_hold_after_activation_sec,
        )
    
    def _apply_60_70_rule(
        self,
        entry_price: float,
        tp_price_r_based: float,
        direction: str,
    ) -> float:
        """
        Apply 60-70% profit capture rule based on Polymarket research.
        
        Research shows:
        - 80% of gain comes in first 60% of holding period
        - Last 20-30% takes disproportionately longer (time decay)
        - Opportunity cost of waiting for final cents
        - Tail risk from unexpected events near resolution
        
        Args:
            entry_price: Entry price
            tp_price_r_based: TP price calculated from R-multiple
            direction: 'LONG' or 'SHORT'
            
        Returns:
            Adjusted TP price capturing 60-70% of theoretical max gain
        """
        direction_upper = direction.upper()
        
        if direction_upper == 'LONG':
            # For YES: max theoretical gain is 1.00 - entry_price
            max_gain = 1.00 - entry_price
            r_based_gain = tp_price_r_based - entry_price
            
            # Calculate what percentage of max gain the R-based TP represents
            gain_pct = r_based_gain / max_gain if max_gain > 0 else 0
            
            # Cap at 70% of max gain (research-backed optimal)
            if gain_pct > 0.70:
                adjusted_gain = max_gain * 0.70
                tp_price = entry_price + adjusted_gain
            elif gain_pct < 0.60:
                # Ensure minimum 60% capture if R-based is too conservative
                adjusted_gain = max_gain * 0.60
                tp_price = entry_price + adjusted_gain
            else:
                # R-based is already in 60-70% range, use it
                tp_price = tp_price_r_based
        
        else:  # SHORT
            # For NO: max theoretical gain is entry_price - 0.00
            max_gain = entry_price - 0.00
            r_based_gain = entry_price - tp_price_r_based
            
            # Calculate what percentage of max gain the R-based TP represents
            gain_pct = r_based_gain / max_gain if max_gain > 0 else 0
            
            # Cap at 70% of max gain
            if gain_pct > 0.70:
                adjusted_gain = max_gain * 0.70
                tp_price = entry_price - adjusted_gain
            elif gain_pct < 0.60:
                # Ensure minimum 60% capture
                adjusted_gain = max_gain * 0.60
                tp_price = entry_price - adjusted_gain
            else:
                # R-based is already in 60-70% range, use it
                tp_price = tp_price_r_based
        
        return tp_price
    
    def _apply_tte_compression(
        self,
        trail_trigger: float,
        trail_distance: float,
        time_to_expiry_seconds: float,
    ) -> tuple[float, float]:
        """
        Apply time-to-expiry compression to trailing parameters.
        
        Research (Prevayo): Compress activation threshold (AT) and trail distance (TD)
        as resolution approaches. This tighter control near expiry prevents
        slippage and captures profits faster in volatile final minutes.
        
        Compression schedule for 15m contracts (900s total):
        - > 600s (10m): No compression (normal parameters)
        - 300-600s (5-10m): 20% compression
        - 120-300s (2-5m): 40% compression
        - < 120s (2m): 60% compression (very tight)
        
        Args:
            trail_trigger: Original trail trigger R-multiple
            trail_distance: Original trail distance R-multiple
            time_to_expiry_seconds: Time to expiry in seconds
            
        Returns:
            Tuple of (compressed_trail_trigger, compressed_trail_distance)
        """
        if time_to_expiry_seconds >= 600:
            # No compression - more than 10 minutes remaining
            compression_factor = 1.0
        elif time_to_expiry_seconds >= 300:
            # 20% compression - 5-10 minutes remaining
            compression_factor = 0.8
        elif time_to_expiry_seconds >= 120:
            # 40% compression - 2-5 minutes remaining
            compression_factor = 0.6
        else:
            # 60% compression - less than 2 minutes remaining
            compression_factor = 0.4
        
        compressed_trigger = trail_trigger * compression_factor
        compressed_distance = trail_distance * compression_factor
        
        logger.debug(
            "[DTP-TTE-COMPRESSION] tte=%.1fs compression=%.0f%% trigger=%.2f->%.2f distance=%.2f->%.2f",
            time_to_expiry_seconds, (1 - compression_factor) * 100,
            trail_trigger, compressed_trigger, trail_distance, compressed_distance
        )
        
        return compressed_trigger, compressed_distance
    
    def _map_confidence_to_r(
        self, confidence: float
    ) -> tuple[float, TakeProfitLevel, float, float]:
        """Map confidence level to R-multiple and trailing parameters.
        
        Returns:
            Tuple of (r_multiple, tp_level, trail_trigger_r, trail_distance_r)
        """
        if confidence <= self.CONFIDENCE_LOW:
            # Low confidence: 1.0R hard TP, no trailing
            return (
                self.R_BASE_LOW,
                TakeProfitLevel.BASE,
                None,  # No trailing for fast exit
                None
            )
        
        elif confidence <= self.CONFIDENCE_MID:
            # Medium confidence: 1.5R base TP, trailing once 1R hit
            return (
                self.R_BASE_MID,
                TakeProfitLevel.BASE,
                self.TRAIL_TRIGGER_BASE,
                self.TRAIL_DISTANCE_BASE
            )
        
        elif confidence <= self.CONFIDENCE_HIGH:
            # High confidence: 2.0-2.5R stretch (linear interpolation)
            # Map 0.6-0.8 confidence to 2.0-2.5R
            pct_through_range = (confidence - self.CONFIDENCE_MID) / (
                self.CONFIDENCE_HIGH - self.CONFIDENCE_MID
            )
            r_multiple = self.R_STRETCH_MIN + pct_through_range * 0.5
            
            return (
                r_multiple,
                TakeProfitLevel.STRETCH,
                self.TRAIL_TRIGGER_STRETCH,
                self.TRAIL_DISTANCE_STRETCH
            )
        
        else:
            # Very high confidence (> 0.8): 2.5-3.0R aggressive stretch
            # Map 0.8-1.0 confidence to 2.5-3.0R
            pct_through_range = (confidence - self.CONFIDENCE_HIGH) / (
                1.0 - self.CONFIDENCE_HIGH
            )
            r_multiple = 2.5 + pct_through_range * 0.5
            r_multiple = min(r_multiple, self.R_STRETCH_MAX)
            
            return (
                r_multiple,
                TakeProfitLevel.AGGRESSIVE,
                self.TRAIL_TRIGGER_STRETCH,
                self.TRAIL_DISTANCE_STRETCH
            )
    
    def should_move_to_trailing(
        self, 
        current_pnl_r: float, 
        plan: TakeProfitPlan
    ) -> bool:
        """Check if position should switch to trailing stop.
        
        Args:
            current_pnl_r: Current profit in R-multiples (e.g., 1.2 = +1.2R)
            plan: The take-profit plan for this position
            
        Returns:
            True if trailing should be activated
        """
        if plan.trailing_trigger_r is None:
            return False
        return current_pnl_r >= plan.trailing_trigger_r
    
    def compute_trailing_stop(
        self,
        current_price: float,
        entry_price: float,
        direction: str,
        plan: TakeProfitPlan,
        stop_price: Optional[float] = None,
    ) -> float:
        """Compute trailing stop price.
        
        Args:
            current_price: Current market price
            entry_price: Original entry price
            direction: 'LONG' or 'SHORT'
            plan: Take-profit plan with trailing parameters
            stop_price: Original stop loss price (required for R calculation)
            
        Returns:
            Trailing stop price
        """
        if plan.trailing_distance_r is None or plan.trailing_trigger_r is None:
            # No trailing configured, return original stop logic
            return None
        
        # Calculate original risk per contract (R)
        if stop_price is not None:
            risk_per_contract = abs(entry_price - stop_price)
        else:
            # Fallback: estimate from trailing trigger R
            risk_per_contract = abs(current_price - entry_price) / max(plan.trailing_trigger_r, 0.01)
        
        if risk_per_contract <= 0:
            risk_per_contract = entry_price * 0.005  # 0.5% fallback
        
        # Calculate trail offset based on trailing distance R
        trail_offset = plan.trailing_distance_r * risk_per_contract
        
        direction_upper = direction.upper()
        if direction_upper == 'LONG':
            return current_price - trail_offset
        else:
            return current_price + trail_offset
    
    def should_activate_ratchet(
        self,
        current_price_cents: int,
        direction: str,
        plan: TakeProfitPlan,
    ) -> bool:
        """Check if ratchet should be activated based on current price.
        
        Args:
            current_price_cents: Current market price in cents
            direction: 'LONG' or 'SHORT'
            plan: Take-profit plan with ratchet parameters
            
        Returns:
            True if ratchet should be activated
        """
        if not plan.ratchet_enabled:
            return False
        
        threshold = plan.ratchet_activation_threshold_cents
        direction_upper = direction.upper()
        
        if direction_upper == 'LONG':
            # For YES: activate when price >= threshold
            return current_price_cents >= threshold
        else:  # SHORT
            # For NO: activate when price <= threshold (lower is better)
            return current_price_cents <= threshold
    
    def compute_ratchet_floor(
        self,
        activation_price_cents: int,
        plan: TakeProfitPlan,
        direction: str = "LONG",
    ) -> int:
        """Compute the ratchet floor price based on activation price.
        
        Args:
            activation_price_cents: Price at which ratchet activated
            plan: Take-profit plan with ratchet parameters
            direction: "LONG" for YES, "SHORT" for NO
            
        Returns:
            Floor price in cents (never changes once set)
        """
        offset = plan.ratchet_floor_offset_cents
        
        if direction.upper() == 'LONG':
            # For YES: floor is below activation (exit if price drops)
            floor = activation_price_cents - offset
        else:  # SHORT
            # For NO: floor is above activation (exit if price rises)
            floor = activation_price_cents + offset
            
        return max(1, min(99, floor))  # Clamp to valid Kalshi range [1, 99]
    
    def should_exit_on_ratchet_floor(
        self,
        current_price_cents: int,
        floor_price_cents: int,
        direction: str,
        activation_timestamp: Optional[float] = None,
        min_hold_seconds: int = 30,
    ) -> bool:
        """Check if position should exit due to ratchet floor breach.
        
        Args:
            current_price_cents: Current market price in cents
            floor_price_cents: Ratchet floor price in cents
            direction: 'LONG' or 'SHORT'
            activation_timestamp: Unix timestamp when ratchet activated (optional)
            min_hold_seconds: Minimum seconds to hold after activation
            
        Returns:
            True if should exit due to floor breach
        """
        import time
        
        # Check minimum hold time to prevent noise-triggered exits
        if activation_timestamp is not None:
            elapsed = time.time() - activation_timestamp
            if elapsed < min_hold_seconds:
                return False
        
        direction_upper = direction.upper()
        
        if direction_upper == 'LONG':
            # For YES: exit if price drops to or below floor
            return current_price_cents <= floor_price_cents
        else:  # SHORT
            # For NO: exit if price rises to or above floor
            return current_price_cents >= floor_price_cents


# Singleton instance for convenience
_dtp_engine: Optional[DynamicTakeProfitEngine] = None


def get_dtp_engine() -> DynamicTakeProfitEngine:
    """Get singleton dynamic take-profit engine."""
    global _dtp_engine
    if _dtp_engine is None:
        _dtp_engine = DynamicTakeProfitEngine()
    return _dtp_engine


def compute_dynamic_tp(
    entry_price: float,
    stop_price: float,
    direction: str,
    confidence: float,
    kelly_fraction: Optional[float] = None,
    use_60_70_rule: bool = True,
    time_to_expiry_seconds: Optional[float] = None,
) -> TakeProfitPlan:
    """Convenience function to compute take-profit using singleton engine."""
    return get_dtp_engine().compute_tp(
        entry_price=entry_price,
        stop_price=stop_price,
        direction=direction,
        confidence=confidence,
        kelly_fraction=kelly_fraction,
        use_60_70_rule=use_60_70_rule,
        time_to_expiry_seconds=time_to_expiry_seconds,
    )
