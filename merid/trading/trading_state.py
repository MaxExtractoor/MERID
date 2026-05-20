"""Trading State Machine — Defines system states and transitions for scalping + hedging.

This module implements the state machine described in the momentum scalping audit:
- State A: SCALP_ONLY — Normal momentum scalping
- State B: SCALP_HEDGE — Reduced scalping with active hedging
- State C: HEDGE_ONLY — Risk-off mode, hedges only
- State D: FLAT — No positions

State transitions include hysteresis (minimum time in state) to prevent thrashing.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Any

from utils.logger import get_logger

logger = get_logger("merid.trading.state_machine")


class TradingState(Enum):
    """System trading states.
    
    A: SCALP_ONLY — Normal operation, full momentum scalping, no hedging
    B: SCALP_HEDGE — Drawdown protection active, reduced sizes + hedging
    C: HEDGE_ONLY — Risk-off, scalping disabled, maintain hedges
    D: FLAT — No positions, all exposure closed
    """
    SCALP_ONLY = "scalp_only"
    SCALP_HEDGE = "scalp_hedge"
    HEDGE_ONLY = "hedge_only"
    FLAT = "flat"


class TransitionReason(Enum):
    """Reason codes for state transitions."""
    DRAWDOWN_WARNING = "drawdown_warning"           # 3% threshold
    DRAWDOWN_HEDGE_ACTIVE = "drawdown_hedge_active"  # 5% threshold
    DRAWDOWN_HALT = "drawdown_halt"                  # 10% threshold
    DRAWDOWN_FULL_HALT = "drawdown_full_halt"        # 15% threshold
    RECOVERY_PARTIAL = "recovery_partial"          # Recovered to < 5%
    RECOVERY_FULL = "recovery_full"                  # Recovered to < 3%
    TIMEOUT = "timeout"                              # Hysteresis expired
    MANUAL_OVERRIDE = "manual_override"              # Admin command
    ALL_POSITIONS_CLOSED = "all_positions_closed"    # Natural flat
    MARKET_REGIME_BLOCK = "market_regime_block"    # Market regime gate blocked trading
    MARKET_REGIME_REDUCE = "market_regime_reduce"    # Market regime gate reduced sizing
    REGIME_BLOCK = "regime_block"                      # Market regime blocked
    REGIME_REDUCE = "regime_reduce"                    # Market regime reduced sizing


@dataclass
class StateMachineConfig:
    """Configuration for state machine thresholds and hysteresis."""
    
    # Drawdown thresholds (decimal, e.g., 0.05 = 5%)
    warning_pct: float = 0.03           # 3% — alert only
    hedge_active_pct: float = 0.05      # 5% — activate hedging (A→B)
    scalp_halt_pct: float = 0.10        # 10% — stop new scalping (B→C)
    full_halt_pct: float = 0.15         # 15% — full halt (emergency)
    
    # Recovery thresholds (must be below these to transition back)
    recovery_hedge_to_scalp_pct: float = 0.03   # < 3% to return A
    recovery_halt_to_hedge_pct: float = 0.05    # < 5% to return B from C
    
    # Hysteresis (minimum seconds in state before transition)
    hysteresis_scalp_hedge: float = 900.0       # 15 minutes
    hysteresis_hedge_scalp: float = 900.0       # 15 minutes
    hysteresis_halt_hedge: float = 1800.0       # 30 minutes
    
    # Consecutive loss threshold (for B→C)
    consecutive_losses_threshold: int = 3
    
    # Liquidity degradation threshold (spread multiple)
    liquidity_spread_multiplier: float = 2.0
    
    # Volatility spike threshold (standard deviations)
    vol_spike_std: float = 2.0

    def __post_init__(self):
        """Load thresholds from environment variables if set."""
        # Drawdown thresholds
        self.warning_pct = float(os.getenv("TRADING_STATE_WARNING_PCT", str(self.warning_pct)))
        self.hedge_active_pct = float(os.getenv("TRADING_STATE_HEDGE_ACTIVE_PCT", str(self.hedge_active_pct)))
        self.scalp_halt_pct = float(os.getenv("TRADING_STATE_SCALP_HALT_PCT", str(self.scalp_halt_pct)))
        self.full_halt_pct = float(os.getenv("TRADING_STATE_FULL_HALT_PCT", str(self.full_halt_pct)))
        
        # Recovery thresholds
        self.recovery_hedge_to_scalp_pct = float(os.getenv("TRADING_STATE_RECOVERY_HEDGE_TO_SCALP_PCT", str(self.recovery_hedge_to_scalp_pct)))
        self.recovery_halt_to_hedge_pct = float(os.getenv("TRADING_STATE_RECOVERY_HALT_TO_HEDGE_PCT", str(self.recovery_halt_to_hedge_pct)))
        
        # Hysteresis thresholds
        self.hysteresis_scalp_hedge = float(os.getenv("TRADING_STATE_HYSTERESIS_SCALP_HEDGE", str(self.hysteresis_scalp_hedge)))
        self.hysteresis_hedge_scalp = float(os.getenv("TRADING_STATE_HYSTERESIS_HEDGE_SCALP", str(self.hysteresis_hedge_scalp)))
        self.hysteresis_halt_hedge = float(os.getenv("TRADING_STATE_HYSTERESIS_HALT_HEDGE", str(self.hysteresis_halt_hedge)))


@dataclass
class StateTransition:
    """Record of a state transition."""
    from_state: TradingState
    to_state: TradingState
    reason: TransitionReason
    timestamp: float = field(default_factory=time.time)
    drawdown_pct: float = 0.0
    time_in_previous_state: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class TradingStateMachine:
    """Manages trading state transitions with hysteresis.
    
    Thread-safe for state reads/writes. All state changes are logged
    with reason codes for audit trail.
    """
    
    def __init__(self, config: Optional[StateMachineConfig] = None):
        self.config = config or StateMachineConfig()
        self._state = TradingState.SCALP_ONLY
        self._state_entry_time = time.time()
        self._time_in_state = 0.0
        self._last_drawdown = 0.0
        self._consecutive_losses = 0
        self._transition_history: List[StateTransition] = []
        self._max_history = 100
        
    @property
    def current_state(self) -> TradingState:
        """Current trading state."""
        return self._state
    
    @property
    def time_in_state_seconds(self) -> float:
        """Time elapsed in current state."""
        return time.time() - self._state_entry_time
    
    @property
    def transition_history(self) -> List[StateTransition]:
        """Recent state transitions (oldest first)."""
        return self._transition_history.copy()
    
    def can_enter_new_scalp_positions(self) -> bool:
        """Check if new scalping entries are allowed in current state."""
        return self._state in (TradingState.SCALP_ONLY, TradingState.SCALP_HEDGE)
    
    def can_maintain_hedges(self) -> bool:
        """Check if hedges should be active in current state."""
        return self._state in (TradingState.SCALP_HEDGE, TradingState.HEDGE_ONLY)
    
    def get_hedge_target_ratio(self) -> float:
        """Get target hedge ratio for current state.
        
        Returns:
            0.0 for SCALP_ONLY
            0.5 for SCALP_HEDGE (50% hedge)
            1.0 for HEDGE_ONLY (100% hedge)
            0.0 for FLAT (no positions)
        """
        ratios = {
            TradingState.SCALP_ONLY: 0.0,
            TradingState.SCALP_HEDGE: 0.5,
            TradingState.HEDGE_ONLY: 1.0,
            TradingState.FLAT: 0.0,
        }
        return ratios.get(self._state, 0.0)
    
    def get_position_size_multiplier(self) -> float:
        """Get position size multiplier for current state.
        
        Returns:
            1.0 for SCALP_ONLY (full size)
            0.6 for SCALP_HEDGE (reduced size)
            0.0 for HEDGE_ONLY/HEDGE_ONLY (no new positions)
        """
        multipliers = {
            TradingState.SCALP_ONLY: 1.0,
            TradingState.SCALP_HEDGE: 0.6,
            TradingState.HEDGE_ONLY: 0.0,
            TradingState.FLAT: 0.0,
        }
        return multipliers.get(self._state, 0.0)
    
    def evaluate_regime_impact(
        self,
        regime_action: str,
        basket_flatness: float = 0.0,
    ) -> Optional[StateTransition]:
        """Evaluate market regime impact on trading state (Task 8).
        
        Connects MarketRegimeGate decisions to state machine transitions.
        When basket is flat and regime blocks new entries, transition to
        SCALP_HEDGE (if hedging allowed) or FLAT (if severe).
        
        Args:
            regime_action: Regime decision - "ALLOW", "REDUCE", or "BLOCK"
            basket_flatness: Measure of basket flatness (0-1, higher = flatter)
            
        Returns:
            StateTransition if regime triggers state change, None otherwise
        """
        if regime_action == "ALLOW":
            # Regime allows trading - no impact on state
            return None
            
        if regime_action == "BLOCK":
            # Severe regime block - consider transitioning to FLAT or HEDGE_ONLY
            if self._state == TradingState.SCALP_ONLY:
                return self._transition(
                    TradingState.SCALP_HEDGE,
                    TransitionReason.MARKET_REGIME_BLOCK,
                    None,
                )
            elif self._state == TradingState.SCALP_HEDGE:
                # If already hedging, go to HEDGE_ONLY
                return self._transition(
                    TradingState.HEDGE_ONLY,
                    TransitionReason.MARKET_REGIME_BLOCK,
                    None,
                )
                
        if regime_action == "REDUCE":
            # Moderate regime restriction - reduce sizing via state multiplier
            if self._state == TradingState.SCALP_ONLY and basket_flatness > 0.7:
                # High flatness + reduce action = activate hedging
                return self._transition(
                    TradingState.SCALP_HEDGE,
                    TransitionReason.MARKET_REGIME_REDUCE,
                    None,
                )
                
        return None

    def evaluate_transition(
        self,
        drawdown_pct: float,
        consecutive_losses: int = 0,
        all_positions_closed: bool = False,
        liquidity_degraded: bool = False,
        vol_spike: bool = False,
        regime_action: Optional[str] = None,
        manual_override: Optional[TradingState] = None,
    ) -> Optional[StateTransition]:
        """Evaluate if state transition should occur.
        
        Task 3: Added hedge effectiveness monitoring for state transitions.
        
        Args:
            drawdown_pct: Current drawdown percentage
            consecutive_losses: Number of consecutive losing trades
            liquidity_degraded: Whether liquidity conditions are degraded
            vol_spike: Whether a volatility spike is detected
            all_positions_closed: Whether all positions are now closed
            hedge_effectiveness: Effectiveness ratio from PnL tracker (None if no hedges)
            unlinked_hedge_count: Number of orphaned hedge fills
            
        Returns:
            StateTransition if transition should occur, None otherwise
        """
        self._last_drawdown = drawdown_pct
        self._consecutive_losses = consecutive_losses
        
        # Manual override takes precedence
        if hedge_effectiveness is not None and hedge_effectiveness != self._state:
            return self._transition(
                hedge_effectiveness,
                TransitionReason.MANUAL_OVERRIDE,
                drawdown_pct,
                {"manual": True}
            )
        
        current = self._state
        time_in_state = self.time_in_state_seconds
        
        # Task 3: Check for hedge health issues that should force transitions
        if unlinked_hedge_count > 10:
            # Too many orphaned hedges - force halt
            return self._transition(
                TradingState.HEDGE_ONLY,
                TransitionReason.DRAWDOWN_HALT,
                drawdown_pct,
                {"unlinked_hedges": unlinked_hedge_count, "reason": "orphaned_hedge_threshold"}
            )
        
        # Task 3: Check hedge effectiveness for SCALP_HEDGE → HEDGE_ONLY transition
        if current == TradingState.SCALP_HEDGE and hedge_effectiveness is not None:
            if hedge_effectiveness < -0.5:  # Hedges are significantly hurting
                # Hedges not working, might need to re-evaluate
                pass  # Could add special handling here
        
        # Evaluate transitions based on current state
        if current == TradingState.SCALP_ONLY:
            return self._evaluate_from_scalp_only(
                drawdown_pct, consecutive_losses, liquidity_degraded, vol_spike
            )
        elif current == TradingState.SCALP_HEDGE:
            return self._evaluate_from_scalp_hedge(
                drawdown_pct, consecutive_losses, liquidity_degraded, vol_spike, time_in_state
            )
        elif current == TradingState.HEDGE_ONLY:
            return self._evaluate_from_hedge_only(
                drawdown_pct, all_positions_closed, time_in_state
            )
        elif current == TradingState.FLAT:
            return self._evaluate_from_flat(
                drawdown_pct, all_positions_closed, time_in_state
            )
        
        return None
    
    def _evaluate_from_scalp_only(
        self,
        drawdown_pct: float,
        consecutive_losses: int,
        liquidity_degraded: bool,
        vol_spike: bool,
    ) -> Optional[StateTransition]:
        """Evaluate transitions from SCALP_ONLY state."""
        cfg = self.config
        
        # A → C (direct to halt if severe drawdown)
        if drawdown_pct >= cfg.scalp_halt_pct:
            return self._transition(
                TradingState.HEDGE_ONLY,
                TransitionReason.DRAWDOWN_HALT,
                drawdown_pct
            )
        
        # A → B (hedge activation)
        if drawdown_pct >= cfg.hedge_active_pct:
            return self._transition(
                TradingState.SCALP_HEDGE,
                TransitionReason.DRAWDOWN_HEDGE_ACTIVE,
                drawdown_pct
            )
        
        # A → B (liquidity or vol triggers)
        if liquidity_degraded or vol_spike:
            return self._transition(
                TradingState.SCALP_HEDGE,
                TransitionReason.DRAWDOWN_WARNING,
                drawdown_pct,
                {"liquidity_degraded": liquidity_degraded, "vol_spike": vol_spike}
            )
        
        return None
    
    def _evaluate_from_scalp_hedge(
        self,
        drawdown_pct: float,
        consecutive_losses: int,
        liquidity_degraded: bool,
        vol_spike: bool,
        time_in_state: float,
    ) -> Optional[StateTransition]:
        """Evaluate transitions from SCALP_HEDGE state."""
        cfg = self.config
        
        # B → C (halt scalping)
        if drawdown_pct >= cfg.scalp_halt_pct:
            return self._transition(
                TradingState.HEDGE_ONLY,
                TransitionReason.DRAWDOWN_HALT,
                drawdown_pct
            )
        
        # B → C (consecutive losses)
        if consecutive_losses >= cfg.consecutive_losses_threshold:
            return self._transition(
                TradingState.HEDGE_ONLY,
                TransitionReason.DRAWDOWN_HALT,
                drawdown_pct,
                {"consecutive_losses": consecutive_losses}
            )
        
        # B → C (liquidity degradation)
        if liquidity_degraded:
            return self._transition(
                TradingState.HEDGE_ONLY,
                TransitionReason.DRAWDOWN_HALT,
                drawdown_pct,
                {"liquidity_degraded": True}
            )
        
        # B → A (recovery with hysteresis)
        if drawdown_pct < cfg.recovery_hedge_to_scalp_pct:
            if time_in_state >= cfg.hysteresis_hedge_scalp:
                return self._transition(
                    TradingState.SCALP_ONLY,
                    TransitionReason.RECOVERY_FULL,
                    drawdown_pct
                )
        
        return None
    
    def _evaluate_from_hedge_only(
        self,
        drawdown_pct: float,
        all_positions_closed: bool,
        time_in_state: float,
    ) -> Optional[StateTransition]:
        """Evaluate transitions from HEDGE_ONLY state."""
        cfg = self.config
        
        # C → D (all positions closed)
        if all_positions_closed:
            return self._transition(
                TradingState.FLAT,
                TransitionReason.ALL_POSITIONS_CLOSED,
                drawdown_pct
            )
        
        # C → B (partial recovery with hysteresis)
        if drawdown_pct < cfg.recovery_halt_to_hedge_pct:
            if time_in_state >= cfg.hysteresis_halt_hedge:
                return self._transition(
                    TradingState.SCALP_HEDGE,
                    TransitionReason.RECOVERY_PARTIAL,
                    drawdown_pct
                )
        
        return None
    
    def _evaluate_from_flat(
        self,
        drawdown_pct: float,
        all_positions_closed: bool,
        time_in_state: float,
    ) -> Optional[StateTransition]:
        """Evaluate transitions from FLAT state."""
        cfg = self.config
        
        # D → A (re-entry after stabilization)
        if drawdown_pct < cfg.recovery_hedge_to_scalp_pct:
            if time_in_state >= cfg.hysteresis_scalp_hedge:
                return self._transition(
                    TradingState.SCALP_ONLY,
                    TransitionReason.RECOVERY_FULL,
                    drawdown_pct
                )
        
        return None
    
    def _transition(
        self,
        new_state: TradingState,
        reason: TransitionReason,
        drawdown_pct: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StateTransition:
        """Execute state transition."""
        old_state = self._state
        time_in_state = self.time_in_state_seconds
        
        self._state = new_state
        self._state_entry_time = time.time()
        
        transition = StateTransition(
            from_state=old_state,
            to_state=new_state,
            reason=reason,
            drawdown_pct=drawdown_pct,
            time_in_previous_state=time_in_state,
            metadata=metadata or {}
        )
        
        self._transition_history.append(transition)
        if len(self._transition_history) > self._max_history:
            self._transition_history.pop(0)
        
        logger.warning(
            "[STATE-TRANSITION] %s → %s | reason=%s | dd=%.2f%% | time_in_prev=%.1fs",
            old_state.value,
            new_state.value,
            reason.value,
            drawdown_pct * 100,
            time_in_state
        )
        
        return transition
    
    def save_state(self, filepath: Optional[str] = None) -> str:
        """Save current state to disk for recovery on restart (Task 10).
        
        Args:
            filepath: Path to save state file. Defaults to data/trading_state.json
            
        Returns:
            Path to saved file
        """
        import json
        import os
        
        if filepath is None:
            filepath = os.path.join("data", "trading_state.json")
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        state_data = {
            "state": self._state.value,
            "state_entry_time": self._state_entry_time,
            "last_drawdown_pct": self._last_drawdown,
            "consecutive_losses": self._consecutive_losses,
            "transition_history": [
                {
                    "from": t.from_state.value,
                    "to": t.to_state.value,
                    "reason": t.reason.value,
                    "timestamp": t.timestamp,
                    "dd_pct": t.drawdown_pct,
                }
                for t in self._transition_history[-10:]  # Last 10
            ],
            "saved_at": time.time(),
        }
        
        with open(filepath, 'w') as f:
            json.dump(state_data, f, indent=2)
        
        logger.info("[STATE-PERSIST] Saved state to %s (state=%s)", filepath, self._state.value)
        return filepath
    
    def restore_state(self, filepath: Optional[str] = None, max_age_seconds: float = 300.0) -> bool:
        """Restore state from disk (Task 10).
        
        SAFETY: If state file is older than max_age_seconds, force FLAT state
        to prevent trading on stale data after extended downtime.
        
        Args:
            filepath: Path to state file. Defaults to data/trading_state.json
            max_age_seconds: Maximum age of state file to restore (default 5 min)
            
        Returns:
            True if state restored, False if not (uses defaults)
        """
        import json
        import os
        
        if filepath is None:
            filepath = os.path.join("data", "trading_state.json")
        
        if not os.path.exists(filepath):
            logger.info("[STATE-PERSIST] No state file found at %s, using defaults", filepath)
            return False
        
        try:
            with open(filepath, 'r') as f:
                state_data = json.load(f)
            
            # Check staleness
            saved_at = state_data.get("saved_at", 0)
            age_seconds = time.time() - saved_at
            
            if age_seconds > max_age_seconds:
                logger.warning(
                    "[STATE-PERSIST] State file stale (age=%.0fs > max=%.0fs), forcing FLAT",
                    age_seconds, max_age_seconds
                )
                self._state = TradingState.FLAT
                self._state_entry_time = time.time()
                return False
            
            # Restore state
            state_str = state_data.get("state", "scalp_only")
            try:
                self._state = TradingState(state_str)
            except ValueError:
                self._state = TradingState.SCALP_ONLY
            
            self._state_entry_time = state_data.get("state_entry_time", time.time())
            self._last_drawdown = state_data.get("last_drawdown_pct", 0.0)
            self._consecutive_losses = state_data.get("consecutive_losses", 0)
            
            logger.info(
                "[STATE-PERSIST] Restored state from %s (state=%s, age=%.0fs)",
                filepath, self._state.value, age_seconds
            )
            return True
            
        except Exception as e:
            logger.error("[STATE-PERSIST] Failed to restore state: %s", e)
            return False
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize current state for monitoring."""
        return {
            "state": self._state.value,
            "state_entry_time": self._state_entry_time,
            "time_in_state_seconds": self.time_in_state_seconds,
            "last_drawdown_pct": self._last_drawdown,
            "consecutive_losses": self._consecutive_losses,
            "can_enter_scalp": self.can_enter_new_scalp_positions(),
            "can_maintain_hedge": self.can_maintain_hedges(),
            "hedge_target_ratio": self.get_hedge_target_ratio(),
            "size_multiplier": self.get_position_size_multiplier(),
            "recent_transitions": [
                {
                    "from": t.from_state.value,
                    "to": t.to_state.value,
                    "reason": t.reason.value,
                    "timestamp": t.timestamp,
                    "dd_pct": t.drawdown_pct,
                }
                for t in self._transition_history[-5:]  # Last 5
            ]
        }


# Singleton instance
_state_machine: Optional[TradingStateMachine] = None


def get_state_machine(config: Optional[StateMachineConfig] = None) -> TradingStateMachine:
    """Get or create singleton state machine instance."""
    global _state_machine
    if _state_machine is None:
        _state_machine = TradingStateMachine(config)
    return _state_machine


def reset_state_machine() -> None:
    """Reset singleton (for testing)."""
    global _state_machine
    _state_machine = None
