"""CycleDrawdownManager — 15-minute rolling drawdown cycle with automatic reset.

This module implements a separate "cycle drawdown" layer that sits under the existing
dynamic daily loss / portfolio drawdown logic, throttling behavior without hard-stopping
the whole venue.

State Model:
- cycle_id: monotonically increasing integer
- cycle_start_ts: UTC timestamp when cycle started
- cycle_end_ts: cycle_start_ts + 15 minutes
- cycle_start_equity_usd: equity at start
- cycle_peak_equity_usd: max equity seen in this cycle
- cycle_floor_equity_usd: cycle_peak_equity_usd * (1 - cycle_drawdown_pct)
- cycle_status: ACTIVE | RESTRICTED | RESET_PENDING

Usage::

    from merid.event_venues.kalshi.cycle_drawdown import get_cycle_drawdown_manager
    
    cdm = get_cycle_drawdown_manager()
    
    # On each risk tick, update cycle state with current equity
    cdm.update_cycle_state(equity_usd=150.0)
    
    # Check if new risk can be opened
    if cdm.can_open_new_risk(trade_notional=10.0):
        # proceed with trade
        
    # Get risk multiplier for sizing
    risk_mult = cdm.get_cycle_risk_multiplier()
    contracts = int(base_contracts * risk_mult)
    
    # Record realized PnL for profit-lock tracking
    cdm.record_realized_pnl(5.0)
"""

from __future__ import annotations

import os
import threading
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.cycle_drawdown")


class CycleStatus(Enum):
    """Cycle drawdown status states."""
    ACTIVE = "active"           # Normal trading
    RESTRICTED = "restricted"    # No new net-long risk, only reductions/hedging
    RESET_PENDING = "reset_pending"  # Flush/cleanup before new cycle


@dataclass
class CycleDrawdownConfig:
    """Configuration for cycle drawdown manager.
    
    ALIGNED: Uses UnifiedDrawdownConfig as single source of truth for thresholds.
    Unified thresholds: warning=3%, hedge_active=5%, scalp_halt=10%, full_halt=15%
    
    Cycle drawdown maps to hedge_active_pct (5%) as the RESTRICTED threshold.
    """
    
    # Cycle timing
    cycle_duration_seconds: int = 900  # 15 minutes
    
    # Drawdown thresholds — now sourced from UnifiedDrawdownConfig
    # These are set dynamically based on unified config in __post_init__
    cycle_drawdown_pct_small: float = 0.07   # small bankroll (< $70)
    cycle_drawdown_pct_medium: float = 0.05  # medium bankroll ($70-$100)
    cycle_drawdown_pct_large: float = 0.03   # large bankroll (>$100)
    
    # Absolute halt threshold from unified config (full_halt_pct = 15%)
    absolute_halt_pct: float = 0.15  # Will be overridden by unified.full_halt_pct
    
    # Minimum notional to consider for profit reset (ignore dust)
    cycle_min_notional_to_reset_usd: float = 0.50  # 50 cents
    
    # Bankroll regime thresholds in cents used to choose the cycle drawdown pct.
    small_bankroll_threshold_cents: int = 7000      # $70
    medium_bankroll_threshold_cents: int = 10000    # $100
    
    # De-risk curve parameters
    derisk_start_pct: float = 0.25  # Start de-risking at 25% of max DD
    derisk_end_pct: float = 1.0     # Full de-risk at max DD
    derisk_max_mult: float = 1.0    # Max risk multiplier
    derisk_min_mult: float = 0.3   # Min risk multiplier at derisk_end_pct
    derisk_restricted_mult: float = 0.1  # Multiplier when RESTRICTED
    
    # Profit-lock parameters
    profit_lock_threshold_pct: float = 0.005  # Lock profits after 0.5% gain
    profit_lock_fraction: float = 0.60  # Don't give back more than 60% of realized PnL
    
    # Epsilon for floating point comparisons
    epsilon: float = 0.0001
    
    def __post_init__(self):
        """Load thresholds from UnifiedDrawdownConfig for consistency."""
        try:
            from merid.risk.drawdown_config import get_drawdown_config
            unified = get_drawdown_config()
            
            # Cycle drawdown uses hedge_active_pct (5%) as RESTRICTED threshold
            # This is when hedging should activate within a cycle
            _aligned_pct = unified.hedge_active_pct  # 5%
            self.cycle_drawdown_pct_small = _aligned_pct
            self.cycle_drawdown_pct_medium = _aligned_pct
            self.cycle_drawdown_pct_large = _aligned_pct
            
            # Absolute halt uses full_halt_pct (15%)
            self.absolute_halt_pct = unified.full_halt_pct  # 15%
            
            logger.debug(
                "[cycle-drawdown] Aligned with unified config: "
                "cycle_dd=%.1f%%, absolute_halt=%.1f%%",
                _aligned_pct * 100, unified.full_halt_pct * 100
            )
        except Exception as exc:
            logger.warning(
                "[cycle-drawdown] Could not load unified config: %s. "
                "Using defaults (cycle=5%%, halt=15%%).", exc
            )


@dataclass
class CycleState:
    """Mutable runtime cycle state."""
    
    cycle_id: int = 0
    cycle_start_ts: float = 0.0  # Unix timestamp
    cycle_end_ts: float = 0.0
    
    cycle_start_equity_usd: float = 0.0
    cycle_peak_equity_usd: float = 0.0
    cycle_floor_equity_usd: float = 0.0
    
    cycle_status: CycleStatus = CycleStatus.ACTIVE
    
    # Profit-lock tracking
    cycle_realized_pnl_usd: float = 0.0
    cycle_profit_lock_floor_equity: float = 0.0
    
    # Metrics tracking
    last_update_ts: float = 0.0
    breach_count_this_cycle: int = 0
    
    # History for sparklines (last 60 cycles)
    cycle_history: List[Dict[str, Any]] = field(default_factory=lambda: [])


class CycleDrawdownManager:
    """Manages 15-minute rolling drawdown cycles with automatic reset.
    
    Responsibilities:
    1. Track cycle state (id, timestamps, equity levels)
    2. Detect drawdown breaches and transition to RESTRICTED
    3. Auto-reset on timer expiry or profit achievement
    4. Provide risk multiplier for sizing decisions
    5. Implement profit-lock to prevent giving back gains
    """
    
    _MAX_HISTORY = 60
    
    def __init__(self, config: Optional[CycleDrawdownConfig] = None):
        self._config = config or CycleDrawdownConfig()
        self._state = CycleState()
        self._lock = threading.RLock()
        self._alert_last_fired: Dict[str, float] = {}  # reason -> monotonic timestamp
        
        # Initialize first cycle
        self._initialize_cycle(0.0)
        
    def _initialize_cycle(self, equity_usd: float, reason: str = "init") -> None:
        """Initialize a new cycle with current equity."""
        cfg = self._config
        now = datetime.now(timezone.utc).timestamp()
        
        with self._lock:
            old_cycle_id = self._state.cycle_id
            
            self._state.cycle_id += 1
            self._state.cycle_start_ts = now
            self._state.cycle_end_ts = now + cfg.cycle_duration_seconds
            self._state.cycle_start_equity_usd = equity_usd
            self._state.cycle_peak_equity_usd = equity_usd
            
            # Compute floor based on current bankroll regime
            dd_pct = self._get_cycle_drawdown_pct(equity_usd)
            self._state.cycle_floor_equity_usd = equity_usd * (1.0 - dd_pct)
            
            self._state.cycle_status = CycleStatus.ACTIVE
            self._state.cycle_realized_pnl_usd = 0.0
            self._state.cycle_profit_lock_floor_equity = 0.0
            self._state.breach_count_this_cycle = 0
            self._state.last_update_ts = now
            
            logger.info(
                "[CYCLE-DRAWDOWN] cycle_reset id=%d reason=%s "
                "start_equity=%.2f floor=%.2f dd_pct=%.1f%% "
                "start_ts=%s end_ts=%s",
                self._state.cycle_id,
                reason,
                self._state.cycle_start_equity_usd,
                self._state.cycle_floor_equity_usd,
                dd_pct * 100,
                datetime.fromtimestamp(self._state.cycle_start_ts, tz=timezone.utc).isoformat(),
                datetime.fromtimestamp(self._state.cycle_end_ts, tz=timezone.utc).isoformat(),
            )
    
    def _get_cycle_drawdown_pct(self, equity_usd: float) -> float:
        """Get the appropriate cycle drawdown percentage based on equity level.
        
        Tighter thresholds for larger balances:
        - Small (<$70 equivalent): 7%
        - Medium ($70-$100): 5%
        - Large (>$100): 3%
        """
        cfg = self._config
        
        # Handle non-positive equity gracefully
        if equity_usd <= 0:
            return cfg.cycle_drawdown_pct_small
        
        # Convert equity to cents for threshold comparison
        equity_cents = int(equity_usd * 100)
        
        if equity_cents < cfg.small_bankroll_threshold_cents:
            return cfg.cycle_drawdown_pct_small
        elif equity_cents < cfg.medium_bankroll_threshold_cents:
            return cfg.cycle_drawdown_pct_medium
        else:
            return cfg.cycle_drawdown_pct_large
    
    def update_cycle_state(self, equity_usd: float) -> CycleStatus:
        """Update cycle state on each risk tick.
        
        Args:
            equity_usd: Current portfolio equity in USD
            
        Returns:
            Current cycle status after update
        """
        cfg = self._config
        now = datetime.now(timezone.utc).timestamp()
        
        with self._lock:
            state = self._state
            
            # 1. Check for cycle expiry
            if now >= state.cycle_end_ts:
                self._initialize_cycle(equity_usd, "time_expiry")
                return self._state.cycle_status
            
            # Handle RESET_PENDING
            if state.cycle_status == CycleStatus.RESET_PENDING:
                self._initialize_cycle(equity_usd, "reset_pending_handled")
                return self._state.cycle_status
            
            # 2. Update peak equity if we've made new highs
            # Only update peak for positive equity values
            if equity_usd > 0 and equity_usd > state.cycle_peak_equity_usd + cfg.epsilon:
                state.cycle_peak_equity_usd = equity_usd
                # Recalculate floor with new peak
                dd_pct = self._get_cycle_drawdown_pct(equity_usd)
                state.cycle_floor_equity_usd = equity_usd * (1.0 - dd_pct)
                logger.debug(
                    "[CYCLE-DRAWDOWN] new_peak id=%d peak=%.2f floor=%.2f",
                    state.cycle_id, state.cycle_peak_equity_usd, state.cycle_floor_equity_usd
                )
            
            # 3. Check for drawdown breach (only for positive equity)
            if equity_usd > 0 and equity_usd <= state.cycle_floor_equity_usd:
                if state.cycle_status != CycleStatus.RESTRICTED:
                    state.cycle_status = CycleStatus.RESTRICTED
                    state.breach_count_this_cycle += 1
                    
                    dd_pct = (state.cycle_peak_equity_usd - equity_usd) / state.cycle_peak_equity_usd
                    
                    logger.warning(
                        "[CYCLE-DRAWDOWN] breach_detected id=%d status=RESTRICTED "
                        "equity=%.2f floor=%.2f dd_pct=%.2f%% breach_count=%d",
                        state.cycle_id,
                        equity_usd,
                        state.cycle_floor_equity_usd,
                        dd_pct * 100,
                        state.breach_count_this_cycle
                    )
                    
                    # Emit metric
                    self._emit_breach_metric(state.cycle_id, equity_usd, state.cycle_floor_equity_usd, dd_pct)
            
            # 4. Check for profit-based reset
            cycle_profit = equity_usd - state.cycle_start_equity_usd
            half_drawdown_pct = self._get_cycle_drawdown_pct(equity_usd) / 2.0
            recovery_threshold = state.cycle_peak_equity_usd * (1.0 - half_drawdown_pct)
            
            if (cycle_profit >= cfg.cycle_min_notional_to_reset_usd and 
                equity_usd >= recovery_threshold and
                state.cycle_status == CycleStatus.ACTIVE):
                
                logger.info(
                    "[CYCLE-DRAWDOWN] profit_reset_triggered id=%d "
                    "profit=%.2f threshold=%.2f",
                    state.cycle_id, cycle_profit, recovery_threshold
                )
                state.cycle_status = CycleStatus.RESET_PENDING
                # Return immediately so caller can see RESET_PENDING state
                state.last_update_ts = now
                self._record_history(equity_usd)
                return state.cycle_status
            
            # 5. Check profit-lock floor
            if state.cycle_profit_lock_floor_equity > 0 and equity_usd <= state.cycle_profit_lock_floor_equity:
                if state.cycle_status != CycleStatus.RESTRICTED:
                    state.cycle_status = CycleStatus.RESTRICTED
                    logger.warning(
                        "[CYCLE-DRAWDOWN] profit_lock_triggered id=%d "
                        "equity=%.2f lock_floor=%.2f realized_pnl=%.2f",
                        state.cycle_id,
                        equity_usd,
                        state.cycle_profit_lock_floor_equity,
                        state.cycle_realized_pnl_usd
                    )
            
            # Update history
            state.last_update_ts = now
            self._record_history(equity_usd)
            
            return state.cycle_status
    
    def _record_history(self, equity_usd: float) -> None:
        """Record equity point for sparkline history."""
        state = self._state
        
        history_entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "cycle_id": state.cycle_id,
            "equity": round(equity_usd, 2),
            "peak": round(state.cycle_peak_equity_usd, 2),
            "floor": round(state.cycle_floor_equity_usd, 2),
            "status": state.cycle_status.value,
            "realized_pnl": round(state.cycle_realized_pnl_usd, 2),
        }
        
        state.cycle_history.append(history_entry)
        if len(state.cycle_history) > self._MAX_HISTORY:
            state.cycle_history = state.cycle_history[-self._MAX_HISTORY:]
    
    def _emit_breach_metric(self, cycle_id: int, equity: float, floor: float, dd_pct: float) -> None:
        """Emit metric/log for drawdown breach."""
        try:
            # This can be wired to Prometheus or other metrics systems
            logger.info(
                "[METRIC] cycle_drawdown_breach cycle_id=%d equity=%.2f floor=%.2f dd_pct=%.2f%%",
                cycle_id, equity, floor, dd_pct * 100
            )
        except Exception as e:
            logger.debug(f"Metric logging failed: {e}")
    
    def get_cycle_risk_multiplier(self, equity_usd: Optional[float] = None) -> float:
        """Compute risk multiplier based on current drawdown within cycle.
        
        Uses a smooth de-risking curve:
        - If dd <= 25% of max: multiplier = 1.0
        - If dd between 25% and 100% of max: linear decay from 1.0 to 0.3
        - If dd > max or status is RESTRICTED: multiplier = 0.1
        
        Args:
            equity_usd: Current equity (uses last update if None)
            
        Returns:
            Risk multiplier (0.0 to 1.0)
        """
        cfg = self._config
        
        with self._lock:
            state = self._state
            
            # If restricted, use minimum multiplier
            if state.cycle_status == CycleStatus.RESTRICTED:
                return cfg.derisk_restricted_mult
            
            # If reset pending, allow cleanup but not new risk
            if state.cycle_status == CycleStatus.RESET_PENDING:
                return cfg.derisk_restricted_mult
            
            if equity_usd is None:
                # Use last recorded equity from history
                if state.cycle_history:
                    equity_usd = state.cycle_history[-1].get("equity", state.cycle_start_equity_usd)
                else:
                    equity_usd = state.cycle_start_equity_usd
            
            # Handle non-positive equity - return minimum multiplier for safety
            if equity_usd <= 0:
                return cfg.derisk_restricted_mult
            
            peak = state.cycle_peak_equity_usd
            if peak <= 0:
                return cfg.derisk_max_mult
            
            # Compute drawdown within cycle (ensure non-negative)
            dd = max(0.0, (peak - equity_usd) / peak)
            max_dd = self._get_cycle_drawdown_pct(equity_usd)
            
            # Normalized drawdown (0 to 1 relative to max)
            if max_dd <= 0:
                return cfg.derisk_max_mult
            
            normalized_dd = min(1.0, dd / max_dd)
            
            # Apply de-risk curve
            if normalized_dd <= cfg.derisk_start_pct:
                return cfg.derisk_max_mult
            elif normalized_dd >= cfg.derisk_end_pct:
                return cfg.derisk_min_mult
            else:
                # Linear interpolation
                t = (normalized_dd - cfg.derisk_start_pct) / (cfg.derisk_end_pct - cfg.derisk_start_pct)
                return cfg.derisk_max_mult - t * (cfg.derisk_max_mult - cfg.derisk_min_mult)
    
    def can_open_new_risk(self, trade_notional: float = 0.0) -> bool:
        """Check if new risk-on positions can be opened.
        
        Returns False if:
        - Daily loss limit breached (checked externally)
        - Portfolio drawdown halt active (checked externally)
        - Cycle status is RESTRICTED or RESET_PENDING
        
        Args:
            trade_notional: Notional value of proposed trade (for logging)
            
        Returns:
            True if new risk can be opened
        """
        with self._lock:
            state = self._state
            
            if state.cycle_status in (CycleStatus.RESTRICTED, CycleStatus.RESET_PENDING):
                logger.info(
                    "[CYCLE-DRAWDOWN] risk_denied id=%d status=%s notional=%.2f",
                    state.cycle_id, state.cycle_status.value, trade_notional
                )
                return False
            
            return True
    
    def record_realized_pnl(self, pnl_usd: float) -> None:
        """Record realized PnL and update profit-lock floor.
        
        When cycle_realized_pnl exceeds threshold, raise a profit-lock floor
        that prevents giving back more than X% of realized PnL within the cycle.
        
        Args:
            pnl_usd: Realized profit (positive) or loss (negative) in USD
        """
        cfg = self._config
        
        with self._lock:
            state = self._state
            
            state.cycle_realized_pnl_usd += pnl_usd
            
            # Only lock profits on positive realized PnL above threshold
            if state.cycle_realized_pnl_usd > cfg.cycle_min_notional_to_reset_usd:
                # Calculate profit-lock floor: start + (realized_pnl * lock_fraction)
                # This ensures we don't give back more than (1 - lock_fraction) of profits
                lock_floor = (
                    state.cycle_start_equity_usd + 
                    cfg.profit_lock_fraction * state.cycle_realized_pnl_usd
                )
                
                # Only raise floor, never lower it
                if lock_floor > state.cycle_profit_lock_floor_equity:
                    old_floor = state.cycle_profit_lock_floor_equity
                    state.cycle_profit_lock_floor_equity = lock_floor
                    
                    logger.info(
                        "[CYCLE-DRAWDOWN] profit_lock_raised id=%d "
                        "realized_pnl=%.2f lock_floor=%.2f (was %.2f)",
                        state.cycle_id,
                        state.cycle_realized_pnl_usd,
                        lock_floor,
                        old_floor if old_floor > 0 else 0
                    )
    
    def force_reset(self, reason: str = "manual") -> None:
        """Force immediate cycle reset.
        
        Args:
            reason: Reason for forced reset
        """
        with self._lock:
            current_equity = self._state.cycle_start_equity_usd
            if self._state.cycle_history:
                current_equity = self._state.cycle_history[-1].get("equity", current_equity)
            
            self._initialize_cycle(current_equity, f"force_reset:{reason}")
    
    def get_cycle_metrics(self) -> Dict[str, Any]:
        """Get current cycle metrics for dashboard/telemetry.
        
        Returns:
            Dict with cycle state and metrics
        """
        with self._lock:
            state = self._state
            cfg = self._config
            
            now = datetime.now(timezone.utc).timestamp()
            
            # Calculate current drawdown
            equity = state.cycle_start_equity_usd
            if state.cycle_history:
                equity = state.cycle_history[-1].get("equity", equity)
            
            peak = state.cycle_peak_equity_usd
            dd_pct = 0.0
            if peak > 0:
                dd_pct = (peak - equity) / peak
            
            max_dd_pct = self._get_cycle_drawdown_pct(equity)
            
            return {
                "cycle_id": state.cycle_id,
                "status": state.cycle_status.value,
                "start_ts": datetime.fromtimestamp(state.cycle_start_ts, tz=timezone.utc).isoformat(),
                "end_ts": datetime.fromtimestamp(state.cycle_end_ts, tz=timezone.utc).isoformat(),
                "seconds_remaining": max(0, int(state.cycle_end_ts - now)),
                "start_equity_usd": round(state.cycle_start_equity_usd, 2),
                "peak_equity_usd": round(state.cycle_peak_equity_usd, 2),
                "current_equity_usd": round(equity, 2),
                "floor_equity_usd": round(state.cycle_floor_equity_usd, 2),
                "profit_lock_floor": round(state.cycle_profit_lock_floor_equity, 2),
                "cycle_drawdown_pct": round(dd_pct * 100, 2),
                "max_drawdown_pct": round(max_dd_pct * 100, 2),
                "cycle_profit_usd": round(equity - state.cycle_start_equity_usd, 2),
                "cycle_realized_pnl_usd": round(state.cycle_realized_pnl_usd, 2),
                "risk_multiplier": round(self.get_cycle_risk_multiplier(equity), 3),
                "can_open_new_risk": self.can_open_new_risk(),
                "breach_count_this_cycle": state.breach_count_this_cycle,
                "cycle_history": list(state.cycle_history),
            }
    
    def configure(self, **kwargs) -> None:
        """Update configuration parameters.
        
        Args:
            **kwargs: Configuration parameters to update
        """
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self._config, key):
                    setattr(self._config, key, value)
                    logger.info("[CYCLE-DRAWDOWN] config_updated %s=%s", key, value)
    
    @property
    def current_cycle_id(self) -> int:
        """Current cycle ID."""
        with self._lock:
            return self._state.cycle_id
    
    @property
    def current_status(self) -> CycleStatus:
        """Current cycle status."""
        with self._lock:
            return self._state.cycle_status


# ═══════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════

_instance: Optional[CycleDrawdownManager] = None
_instance_lock = threading.Lock()


def get_cycle_drawdown_manager() -> CycleDrawdownManager:
    """Get the singleton CycleDrawdownManager instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = CycleDrawdownManager()
    return _instance


def reset_cycle_drawdown_manager() -> None:
    """Reset the singleton (for testing or config changes)."""
    global _instance
    with _instance_lock:
        if _instance is not None:
            _instance.force_reset("singleton_reset")
        _instance = None
