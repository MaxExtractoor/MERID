"""
Exit policy engine for unified edge-based exit decisions.

This module provides a unified exit policy engine that integrates with the
position management system to make consistent exit decisions across all assets
(BTC, ETH, SOL, XRP, DOGE) and both sides (YES/NO).

The exit policy engine evaluates:
- Take-profit triggers based on edge capture ratios
- Stop-loss triggers based on R-multiple thresholds
- Time-based exits for stale positions
- Edge decay detection
- Risk layer kill switches

This is the production exit policy implementation for the 15m Kalshi crypto
trading system. It aligns with best practices from 2026 prediction market
research.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class ExitReason(str, Enum):
    """
    Exit reason types - SINGLE SOURCE OF TRUTH for exit reasons across the system.
    
    CRITICAL FIX: 2026-07-15 - Synchronized with position_management.exit_policy.ExitReason
    All modules must use this enum to ensure consistency in logging, metrics, and callbacks.
    
    EXIT PRECEDENCE ORDER (highest to lowest priority):
    This is the ACTUAL check order in position_monitor._check_position():
    
    1. EXTREME_PROFIT - Exit at 99c YES / 1c NO (guaranteed win, highest priority)
    2. DYNAMIC_TAKE_PROFIT - Laddered exit based on entry price zones (user strategy)
    3. RATCHET_TRIM - Partial close to trim position when >1 contract and price >80c
    4. RATCHET_FLOOR - Exit when price drops below ratchet floor (80-85c profit protection)
    5. STOP_LOSS - Stop loss trigger
    6. TAKE_PROFIT - Take profit trigger
    7. TRAIL - Trailing stop trigger
    8. TIME_STOP - Time-based exit (emergency flatten, staged exits)
    9. EDGE_DECAY - Edge quality degradation
    10. CANDLE_REVERSAL - Momentum reversal signal
    11. ADAPTIVE_TIMING - Historical performance-based timing
    12. STALE_DATA - Market data staleness (P0 safety fix)
    13. RISK - Risk kill switch or exposure limit
    14. SCALE_OUT - Partial position close
    15. MANUAL - Manual exit
    16. LOSS_CAP - Loss cap trigger (break-even mechanism)
    
    NOTE: EXTREME_PROFIT and RATCHET_FLOOR are handled in position_monitor/resolver, not in ExitPolicy.evaluate().
    NOTE: LOSS_CAP is handled by position.py break-even mechanism, not in ExitPolicy.evaluate().
    """
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    TRAIL = "trail"
    TIME_STOP = "time_stop"
    EDGE_DECAY = "edge_decay"
    RISK = "risk"
    MANUAL = "manual"
    SCALE_OUT = "scale_out"
    CANDLE_REVERSAL = "candle_reversal"
    AUTO_EXIT_99C = "auto_exit_99c"  # Cash out at 99c (near-settlement)
    EXTREME_PROFIT = "extreme_profit"  # Deprecated - use AUTO_EXIT_99C
    RATCHET_FLOOR = "ratchet_floor"
    RATCHET_TRIM = "ratchet_trim"
    DYNAMIC_TAKE_PROFIT = "dynamic_take_profit"
    STALE_DATA = "stale_data"
    ADAPTIVE_TIMING = "adaptive_timing"
    LOSS_CAP = "loss_cap"
    LOSS_CUT_40PCT = "loss_cut_40pct"  # 2026-08-12: -40% loss cut when thesis changes
    OPPORTUNITY_COST = "opportunity_cost"  # 2026-08-12: better opportunity exists
    SETTLEMENT_GUARD = "settlement_guard"  # 2026-08-12: forced T-30s exit
    MODEL_INVALIDATION_LOSS_EXIT = "model_invalidation_loss_exit"  # 2026-08-12: edge collapse below entry with loss
    CURRENT_EDGE_REVERSAL = "current_edge_reversal"  # 2026-08-23: model has reversed to the opposite outcome
    CONTINUATION_STOP = "continuation_stop"  # 2026-08-25: 5m underlying continuation stop
    MARKET_EXPIRED = "market_expired"


@dataclass
class ExitPolicyConfig:
    """
    Exit policy configuration.
    
    Configures the exit policy engine with thresholds and parameters.
    Aligned with 2026 best practices for prediction market exits.
    """
    # Take-profit configuration
    take_profit_enabled: bool = True
    take_profit_pct: float = 0.80  # 80% profit target (edge capture ratio) - CRITICAL FIX 2026-07-16: Changed from 0.50 to achieve positive risk/reward
    min_hold_minutes: float = 5.0  # Minimum hold before TP (prevents noise exits) - CRITICAL FIX 2026-07-30: Increased from 2.0 to 5.0 for 15m markets
    
    # Stop-loss configuration
    stop_loss_enabled: bool = True
    stop_loss_pct: float = 0.40  # 40% loss trigger (aligned with research) - CRITICAL FIX 2026-07-16: Changed from 0.80 to achieve positive risk/reward
    
    # Dynamic thresholds
    edge_based_tp: bool = True  # Adjust TP based on edge quality
    edge_based_sl: bool = True  # Adjust SL based on edge quality
    confidence_scaling: bool = True  # Scale thresholds by confidence
    
    # Time-based exits
    max_hold_minutes: float = 15.0  # 15-minute max hold for 15m strips
    time_stop_enabled: bool = True
    
    # Edge decay
    min_edge_threshold: float = 0.02  # 2% minimum edge threshold


@dataclass
class ExitSignal:
    """
    Exit signal from the exit policy engine.
    
    Contains the decision and metadata for exit actions.
    """
    should_exit: bool
    reason: ExitReason
    message: str
    exit_price_cents: Optional[int] = None
    confidence: float = 0.0


class ExitPolicyEngine:
    """
    Exit policy engine for unified exit decisions.
    
    Evaluates exit conditions based on position state, market conditions,
    and edge quality. Works across all 5 crypto assets (BTC, ETH, SOL, XRP, DOGE)
    and both sides (YES/NO).
    """
    
    def __init__(self, config: Optional[ExitPolicyConfig] = None):
        """
        Initialize exit policy engine.
        
        Args:
            config: Exit policy configuration (uses defaults if None)
        """
        self.config = config or ExitPolicyConfig()
        logger.info("[EXIT-POLICY-ENGINE] Initialized with config: TP=%s%% SL=%s%% edge_based_tp=%s",
                    self.config.take_profit_pct * 100,
                    self.config.stop_loss_pct * 100,
                    self.config.edge_based_tp)
    
    def evaluate_exit(
        self,
        entry_price_cents: int,
        current_price_cents: int,
        edge_pct: float,
        confidence: float,
        minutes_held: float,
        side: str,
    ) -> ExitSignal:
        """
        Evaluate exit conditions for a position.
        
        Args:
            entry_price_cents: Entry price in cents
            current_price_cents: Current price in cents
            edge_pct: Edge percentage at entry
            confidence: Model confidence (0-1)
            minutes_held: Time since entry in minutes
            side: Position side ("yes" or "no")
        
        Returns:
            ExitSignal with exit decision
        """
        # CRITICAL FIX (2026-08-01): Validate entry_price_cents to prevent division by zero
        # Invalid entry prices should trigger immediate exit for safety
        if entry_price_cents is None or entry_price_cents <= 0:
            logger.error(
                "[EXIT-POLICY] Invalid entry_price_cents=%s for position - triggering emergency exit for safety",
                entry_price_cents
            )
            return ExitSignal(
                should_exit=True,
                reason=ExitReason.MANUAL,
                message=f"Invalid entry price: {entry_price_cents} - emergency exit for safety",
                exit_price_cents=current_price_cents,
                confidence=confidence,
            )
        
        # Calculate profit/loss percentage
        if side.lower() == "yes":
            profit_pct = (current_price_cents - entry_price_cents) / entry_price_cents
        else:  # NO position
            profit_pct = (entry_price_cents - current_price_cents) / entry_price_cents
        
        # Apply dynamic threshold adjustments
        tp_threshold = self._get_tp_threshold(edge_pct, confidence)
        sl_threshold = self._get_sl_threshold(edge_pct, confidence)
        
        # Check stop loss first (risk management priority)
        # CRITICAL (2026-08-10): Direct stop-loss exits are disabled.  Any SL
        # predicate that fires is suppressed; the live stop path is now a gated
        # StopCandidate event handled by the execution layer.
        if self.config.stop_loss_enabled and profit_pct <= -sl_threshold:
            logger.warning(
                "[EXIT-POLICY-ENGINE] SL predicate suppressed: %.1f%% loss (threshold %.1f%%) "
                "- StopCandidate path is disabled until replay tests pass",
                profit_pct * 100,
                sl_threshold * 100,
            )
            return ExitSignal(
                should_exit=False,
                reason=None,
                message=f"SL suppressed: {profit_pct:.1%} loss (threshold: {sl_threshold:.1%})",
                exit_price_cents=current_price_cents,
                confidence=confidence,
            )
        
        # Check take profit (with minimum hold time gate)
        if self.config.take_profit_enabled:
            if minutes_held >= self.config.min_hold_minutes:
                if profit_pct >= tp_threshold:
                    return ExitSignal(
                        should_exit=True,
                        reason=ExitReason.TAKE_PROFIT,
                        message=f"TP triggered: {profit_pct:.1%} profit (threshold: {tp_threshold:.1%})",
                        exit_price_cents=current_price_cents,
                        confidence=confidence,
                    )
            else:
                # Profitable but not held long enough
                if profit_pct >= tp_threshold:
                    return ExitSignal(
                        should_exit=False,
                        reason=ExitReason.MANUAL,
                        message=f"Holding: {profit_pct:.1%} profit but only {minutes_held:.1f}min held (min: {self.config.min_hold_minutes}min)",
                        exit_price_cents=current_price_cents,
                        confidence=confidence,
                    )
        
        # Check time stop
        # CRITICAL FIX: 2026-07-30 - Fixed logic bug: "profit_pct < 0 or profit_pct < 0.05" is redundant
        # Previous condition always triggered because profit_pct < 0 implies profit_pct < 0.05
        # New condition: exit only if losing (profit_pct < 0) OR minimal progress (0 <= profit_pct < 0.05)
        if self.config.time_stop_enabled and minutes_held >= self.config.max_hold_minutes:
            if profit_pct < 0 or (profit_pct >= 0 and profit_pct < 0.05):  # Losing or minimal progress
                return ExitSignal(
                    should_exit=True,
                    reason=ExitReason.TIME_STOP,
                    message=f"Time stop: {minutes_held:.1f}min held (max: {self.config.max_hold_minutes}min)",
                    exit_price_cents=current_price_cents,
                    confidence=confidence,
                )
        
        # No exit condition met
        return ExitSignal(
            should_exit=False,
            reason=ExitReason.MANUAL,
            message=f"Holding: {profit_pct:.1%} PnL, {minutes_held:.1f}min held",
            exit_price_cents=current_price_cents,
            confidence=confidence,
        )
    
    def _get_tp_threshold(self, edge_pct: float, confidence: float) -> float:
        """
        Get dynamic take-profit threshold.
        
        Args:
            edge_pct: Edge percentage at entry
            confidence: Model confidence
        
        Returns:
            TP threshold as percentage
        """
        threshold = self.config.take_profit_pct
        
        if self.config.edge_based_tp:
            # Higher edge = higher TP target (capture more of the edge)
            edge_multiplier = 1.0 + (edge_pct * 2.0)  # 2% edge -> 1.04x, 5% edge -> 1.10x
            threshold *= edge_multiplier
        
        if self.config.confidence_scaling:
            # Higher confidence = higher TP target
            conf_multiplier = 1.0 + (confidence * 0.2)  # 0.8 confidence -> 1.16x
            threshold *= conf_multiplier
        
        return threshold
    
    def _get_sl_threshold(self, edge_pct: float, confidence: float) -> float:
        """
        Get dynamic stop-loss threshold.
        
        Args:
            edge_pct: Edge percentage at entry
            confidence: Model confidence
        
        Returns:
            SL threshold as percentage (negative)
        """
        threshold = self.config.stop_loss_pct
        
        if self.config.edge_based_sl:
            # Higher edge = tighter SL (protect high-conviction trades)
            edge_multiplier = 1.0 - (edge_pct * 1.0)  # 2% edge -> 0.98x, 5% edge -> 0.95x
            threshold *= edge_multiplier
        
        if self.config.confidence_scaling:
            # Higher confidence = tighter SL
            conf_multiplier = 1.0 - (confidence * 0.1)  # 0.8 confidence -> 0.92x
            threshold *= conf_multiplier
        
        return threshold


# Global singleton instance
_exit_engine: Optional[ExitPolicyEngine] = None


def get_exit_policy_engine(config: Optional[ExitPolicyConfig] = None) -> ExitPolicyEngine:
    """
    Get global exit policy engine singleton.
    
    Args:
        config: Exit policy configuration (only used on first call)
    
    Returns:
        ExitPolicyEngine instance
    """
    global _exit_engine
    if _exit_engine is None:
        _exit_engine = ExitPolicyEngine(config)
        logger.info("[EXIT-POLICY-ENGINE] Created global singleton")
    return _exit_engine
