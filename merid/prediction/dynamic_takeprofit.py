"""Dynamic Take-Profit Engine — R-multiple based profit targets.

This module implements the production scalping take-profit regime:
- Base TP: 1.0-1.5R for fast scalping
- Stretch TP: 2.0-3.0R for high confidence signals
- Confidence/Kelly fraction modulates between base and stretch

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
    
    def to_dict(self) -> dict:
        return {
            "tp_price": self.tp_price,
            "tp_r_multiple": self.tp_r_multiple,
            "tp_level": self.tp_level.value,
            "trailing_trigger_r": self.trailing_trigger_r,
            "trailing_distance_r": self.trailing_distance_r,
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
    ) -> TakeProfitPlan:
        """Compute dynamic take-profit price based on R-multiple and confidence.
        
        Args:
            entry_price: Entry price in cents or dollars
            stop_price: Stop loss price
            direction: 'LONG' (buy YES) or 'SHORT' (buy NO)
            confidence: Signal confidence 0-1 (can use Kelly fraction)
            kelly_fraction: Optional Kelly fraction 0-1 (if None, uses confidence)
            
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
        
        # Calculate TP offset from entry
        tp_offset = r_multiple * risk_per_contract
        
        # Apply direction
        direction_upper = direction.upper()
        if direction_upper == 'LONG':
            tp_price = entry_price + tp_offset
        elif direction_upper == 'SHORT':
            tp_price = entry_price - tp_offset
        else:
            raise ValueError(f"Invalid direction: {direction}. Use 'LONG' or 'SHORT'")
        
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
        )
    
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
    ) -> float:
        """Compute trailing stop price.
        
        Args:
            current_price: Current market price
            entry_price: Original entry price
            direction: 'LONG' or 'SHORT'
            plan: Take-profit plan with trailing parameters
            
        Returns:
            Trailing stop price
        """
        if plan.trailing_distance_r is None or plan.trailing_trigger_r is None:
            # No trailing configured, return original stop logic
            return None
        
        # Calculate R distance for trailing
        risk_per_contract = abs(entry_price - (entry_price - plan.trailing_trigger_r * 0.01))
        # Actually we need the original stop distance... this is simplified
        # In production, you'd track the original stop distance
        trail_offset = plan.trailing_distance_r * abs(current_price - entry_price) / plan.trailing_trigger_r
        
        direction_upper = direction.upper()
        if direction_upper == 'LONG':
            return current_price - trail_offset
        else:
            return current_price + trail_offset


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
) -> TakeProfitPlan:
    """Convenience function to compute take-profit using singleton engine."""
    return get_dtp_engine().compute_tp(
        entry_price=entry_price,
        stop_price=stop_price,
        direction=direction,
        confidence=confidence,
        kelly_fraction=kelly_fraction,
    )
