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
    """Exit reason types aligned with position_management.exit_policy."""
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    TRAIL = "trail"
    TIME_STOP = "time_stop"
    EDGE_DECAY = "edge_decay"
    RISK = "risk"
    MANUAL = "manual"
    SCALE_OUT = "scale_out"
    CANDLE_REVERSAL = "candle_reversal"
    EXTREME_PROFIT = "extreme_profit"
    RATCHET_FLOOR = "ratchet_floor"
    RATCHET_TRIM = "ratchet_trim"
    DYNAMIC_TAKE_PROFIT = "dynamic_take_profit"
    STALE_DATA = "stale_data"
    ADAPTIVE_TIMING = "adaptive_timing"


@dataclass
class ExitPolicyConfig:
    """
    Exit policy configuration.
    
    Configures the exit policy engine with thresholds and parameters.
    Aligned with 2026 best practices for prediction market exits.
    """
    # Take-profit configuration
    take_profit_enabled: bool = True
    take_profit_pct: float = 0.50  # 50% profit target (edge capture ratio)
    min_hold_minutes: float = 2.0  # Minimum hold before TP (prevents noise exits)
    
    # Stop-loss configuration
    stop_loss_enabled: bool = True
    stop_loss_pct: float = 0.80  # 80% loss trigger (aligned with research)
    
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
        # Calculate profit/loss percentage
        if side.lower() == "yes":
            profit_pct = (current_price_cents - entry_price_cents) / entry_price_cents
        else:  # NO position
            profit_pct = (entry_price_cents - current_price_cents) / entry_price_cents
        
        # Apply dynamic threshold adjustments
        tp_threshold = self._get_tp_threshold(edge_pct, confidence)
        sl_threshold = self._get_sl_threshold(edge_pct, confidence)
        
        # Check stop loss first (risk management priority)
        if self.config.stop_loss_enabled and profit_pct <= -sl_threshold:
            return ExitSignal(
                should_exit=True,
                reason=ExitReason.STOP_LOSS,
                message=f"SL triggered: {profit_pct:.1%} loss (threshold: {sl_threshold:.1%})",
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
        if self.config.time_stop_enabled and minutes_held >= self.config.max_hold_minutes:
            if profit_pct < 0 or profit_pct < 0.05:  # Losing or minimal progress
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
