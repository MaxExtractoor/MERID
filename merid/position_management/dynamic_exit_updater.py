"""
Dynamic Exit Policy Updater

Updates exit policy parameters based on runtime conditions including
time-based tightening, ATR-based scaling, and regime-based adaptation.
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any

from utils.logger import get_logger

from merid.position_management.unified_exit_policy_engine import ExitPolicyResolution

logger = get_logger(__name__)


class DynamicExitPolicyUpdater:
    """Updates exit policy parameters based on runtime conditions."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize dynamic exit policy updater.
        
        Args:
            config: Configuration for dynamic updates
        """
        self._config = config or {}
        self._time_decay_enabled = self._config.get("time_decay_enabled", True)
        self._atr_scaling_enabled = self._config.get("atr_scaling_enabled", False)
        self._regime_adaptation_enabled = self._config.get("regime_adaptation_enabled", True)
        
        # Time decay parameters
        self._time_decay_interval_seconds = self._config.get("time_decay_interval_seconds", 300)  # 5 minutes
        self._time_decay_sl_tightening_pct = self._config.get("time_decay_sl_tightening_pct", 0.10)  # 10%
        
        # ATR scaling parameters
        self._atr_stop_multiplier = self._config.get("atr_stop_multiplier", 1.0)
        self._atr_tp_multiplier = self._config.get("atr_tp_multiplier", 2.0)
        
        logger.info(
            "[DYNAMIC-EXIT-UPDATER] Initialized: time_decay=%s atr_scaling=%s regime_adaptation=%s",
            self._time_decay_enabled,
            self._atr_scaling_enabled,
            self._regime_adaptation_enabled
        )
    
    def update_policy(
        self,
        position: Any,
        current_policy: ExitPolicyResolution,
        current_price_cents: int,
        time_since_entry_seconds: float,
        current_atr_pct: Optional[float] = None,
        current_regime: Optional[str] = None
    ) -> ExitPolicyResolution:
        """
        Return updated exit policy with dynamic adjustments.
        
        Args:
            position: Position to update policy for
            current_policy: Current exit policy
            current_price_cents: Current market price in cents
            time_since_entry_seconds: Time since position entry in seconds
            current_atr_pct: Current ATR percentage (optional)
            current_regime: Current market regime (optional)
        
        Returns:
            Updated exit policy with dynamic adjustments
        """
        updated_policy = copy.deepcopy(current_policy)
        
        # Apply time-based tightening
        if self._time_decay_enabled:
            updated_policy = self._apply_time_decay(updated_policy, time_since_entry_seconds)
        
        # Apply ATR-based scaling
        if self._atr_scaling_enabled and current_atr_pct:
            updated_policy = self._apply_atr_scaling(updated_policy, current_atr_pct)
        
        # Apply regime-based adaptation
        if self._regime_adaptation_enabled and current_regime:
            updated_policy = self._apply_regime_adjustment(updated_policy, current_regime)
        
        return updated_policy
    
    def _apply_time_decay(
        self,
        policy: ExitPolicyResolution,
        time_since_entry_seconds: float
    ) -> ExitPolicyResolution:
        """
        Progressively tighten stops as position ages.
        
        From Nous Ergon: time-decay rules force system to prove thesis quickly.
        Tighten SL by 10% every 5 minutes.
        """
        # Calculate number of decay intervals
        decay_intervals = int(time_since_entry_seconds / self._time_decay_interval_seconds)
        
        if decay_intervals == 0:
            return policy
        
        # Calculate tightening factor
        tightening_factor = (1.0 - self._time_decay_sl_tightening_pct) ** decay_intervals
        
        # Tighten stop loss if using fixed cents
        if policy.sl_cents:
            original_sl = policy.sl_cents
            policy.sl_cents = int(original_sl * tightening_factor)
            logger.debug(
                "[DYNAMIC-EXIT-UPDATER] Time decay: SL tightened from %d to %d (%.2f%%)",
                original_sl,
                policy.sl_cents,
                (1.0 - tightening_factor) * 100
            )
        
        # Tighten trailing stop giveback
        if policy.trailing_giveback_cents:
            original_giveback = policy.trailing_giveback_cents
            policy.trailing_giveback_cents = int(original_giveback * tightening_factor)
            logger.debug(
                "[DYNAMIC-EXIT-UPDATER] Time decay: trailing giveback tightened from %d to %d (%.2f%%)",
                original_giveback,
                policy.trailing_giveback_cents,
                (1.0 - tightening_factor) * 100
            )
        
        return policy
    
    def _apply_atr_scaling(
        self,
        policy: ExitPolicyResolution,
        atr_pct: float
    ) -> ExitPolicyResolution:
        """
        Apply ATR-based volatility scaling.
        
        From research: 1.0× ATR stop, 2.0× ATR TP.
        """
        # Calculate ATR-based stop loss in cents
        if policy.sl_cents is None and policy.sl_r_multiple:
            # Convert R-multiple to cents using ATR
            atr_cents = int(atr_pct * 100)  # Convert to cents
            policy.sl_cents = int(atr_cents * self._atr_stop_multiplier)
            logger.debug(
                "[DYNAMIC-EXIT-UPDATER] ATR scaling: SL set to %d cents (%.2f× ATR)",
                policy.sl_cents,
                self._atr_stop_multiplier
            )
        
        # Calculate ATR-based take profit in cents
        if policy.tp_r_multiple:
            atr_cents = int(atr_pct * 100)  # Convert to cents
            atr_tp_cents = int(atr_cents * self._atr_tp_multiplier)
            
            # Use the larger of profile TP and ATR TP
            profile_tp_cents = int(policy.tp_r_multiple * 100)  # Rough estimate
            policy.tp_min_cents = max(policy.tp_min_cents, atr_tp_cents)
            
            logger.debug(
                "[DYNAMIC-EXIT-UPDATER] ATR scaling: TP min set to %d cents (%.2f× ATR)",
                policy.tp_min_cents,
                self._atr_tp_multiplier
            )
        
        return policy
    
    def _apply_regime_adjustment(
        self,
        policy: ExitPolicyResolution,
        regime: str
    ) -> ExitPolicyResolution:
        """
        Adjust based on market regime.
        
        Conservative: wider stops, tighter TP
        Aggressive: tighter stops, wider TP
        """
        if regime == policy.regime:
            # No regime change
            return policy
        
        # Apply regime adjustments
        if regime == "conservative":
            # Tighter TP, wider SL, longer hold
            policy.tp_r_multiple *= 0.75
            if policy.sl_cents:
                policy.sl_cents = int(policy.sl_cents * 1.2)
            policy.max_hold_seconds = int(policy.max_hold_seconds * 1.5)
            policy.regime = regime
            
            logger.debug("[DYNAMIC-EXIT-UPDATER] Regime adjustment: conservative")
            
        elif regime == "aggressive":
            # Wider TP, tighter SL, shorter hold
            policy.tp_r_multiple *= 1.2
            if policy.sl_cents:
                policy.sl_cents = int(policy.sl_cents * 0.8)
            policy.max_hold_seconds = int(policy.max_hold_seconds * 0.67)
            policy.regime = regime
            
            logger.debug("[DYNAMIC-EXIT-UPDATER] Regime adjustment: aggressive")
        
        else:
            # Normal regime
            policy.regime = regime
            logger.debug("[DYNAMIC-EXIT-UPDATER] Regime adjustment: normal")
        
        return policy
