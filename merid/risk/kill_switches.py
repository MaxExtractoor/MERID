"""MERID Risk Kill Switches.

Hard safety controls that halt trading when triggered.

Kill Switches:
1. Global Kill Switch - Immediately halts all trading
2. Daily Loss Kill - Halts when daily P&L limit breached

Usage:
    from merid.risk.kill_switches import risk_controller
    
    # Check before any trade
    if not risk_controller.can_trade():
        return  # Trading halted
    
    # Record P&L after trades
    risk_controller.record_pnl(-50.0)
    
    # Emergency stop
    risk_controller.emergency_stop("Manual operator intervention")
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.risk.kill_switches")


class KillSwitchState(str, Enum):
    """Kill switch states."""
    ACTIVE = "active"        # Trading allowed
    TRIGGERED = "triggered"  # Trading halted


class KillSwitchReason(str, Enum):
    """Reasons for kill switch activation."""
    MANUAL = "manual"                    # Operator triggered
    DAILY_LOSS = "daily_loss"            # Daily loss limit hit
    POSITION_LIMIT = "position_limit"    # Position limit exceeded
    ERROR_THRESHOLD = "error_threshold"  # Too many errors
    CIRCUIT_BREAKER = "circuit_breaker"  # All venues circuit-broken


@dataclass
class KillSwitchEvent:
    """Record of a kill switch state change."""
    timestamp: datetime
    old_state: KillSwitchState
    new_state: KillSwitchState
    reason: KillSwitchReason
    details: Optional[str] = None


@dataclass 
class RiskController:
    """
    Central risk controller with kill switches.
    
    Thread-safe singleton that integrates with:
    - Settings (config validation)
    - Circuit breakers (venue health)
    - Trading engine (P&L tracking)
    """
    
    daily_loss_limit: float = 500.0
    max_position_value: float = 10000.0
    error_threshold: int = 10
    
    def __post_init__(self):
        self._global_kill: bool = False
        self._kill_reason: Optional[KillSwitchReason] = None
        self._kill_details: Optional[str] = None
        self._kill_timestamp: Optional[datetime] = None
        
        self._daily_pnl: float = 0.0
        self._daily_pnl_reset_date: str = self._today()
        self._total_position_value: float = 0.0
        
        self._error_count: int = 0
        self._error_window_start: float = time.time()
        
        self._events: List[KillSwitchEvent] = []
        self._callbacks: List[Callable[[KillSwitchEvent], None]] = []
        
        # Load from settings if available
        self._load_from_settings()
    
    def _load_from_settings(self):
        """Load limits from settings module if not explicitly set."""
        # Only load from settings if using defaults
        if self.daily_loss_limit == 500.0 and self.max_position_value == 10000.0:
            try:
                from merid.settings import settings
                self.daily_loss_limit = settings.MERID_MAX_DAILY_LOSS_USD
                self.max_position_value = settings.MERID_MAX_POSITION_SIZE_USD * 10
            except (ImportError, AttributeError):
                pass
    
    @staticmethod
    def _today() -> str:
        """Get today's date string (UTC)."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    @staticmethod
    def _now() -> datetime:
        """Get current UTC timestamp."""
        return datetime.now(timezone.utc)
    
    # -------------------------------------------------------------------------
    # Core API
    # -------------------------------------------------------------------------
    
    def can_trade(self) -> bool:
        """
        Check if trading is allowed.
        
        Call this before every trade attempt.
        Returns False if any kill switch is triggered.
        """
        # Reset daily P&L if new day
        today = self._today()
        if self._daily_pnl_reset_date != today:
            logger.info(f"[risk] New trading day, resetting daily P&L from {self._daily_pnl}")
            self._daily_pnl = 0.0
            self._daily_pnl_reset_date = today
        
        return not self._global_kill
    
    def get_state(self) -> KillSwitchState:
        """Get current kill switch state."""
        return KillSwitchState.TRIGGERED if self._global_kill else KillSwitchState.ACTIVE
    
    def state(self) -> str:
        """Get current state as string."""
        return self.get_state().value
    
    def get_kill_reason(self) -> Optional[str]:
        """Get the reason for kill switch activation, if any."""
        if self._kill_reason:
            return f"{self._kill_reason.value}: {self._kill_details}" if self._kill_details else self._kill_reason.value
        return None
    
    def get_status(self) -> dict:
        """
        Get full risk controller status.
        
        Useful for dashboards and monitoring.
        """
        return {
            "state": self.get_state().value,
            "can_trade": self.can_trade(),
            "kill_reason": self._kill_reason.value if self._kill_reason else None,
            "kill_details": self._kill_details,
            "kill_timestamp": self._kill_timestamp.isoformat() if self._kill_timestamp else None,
            "daily_pnl": self._daily_pnl,
            "daily_loss_limit": self.daily_loss_limit,
            "daily_pnl_pct": (abs(self._daily_pnl) / self.daily_loss_limit * 100) if self.daily_loss_limit > 0 else 0,
            "position_value": self._total_position_value,
            "max_position_value": self.max_position_value,
            "error_count": self._error_count,
            "error_threshold": self.error_threshold,
            "events_count": len(self._events),
        }
    
    # -------------------------------------------------------------------------
    # Kill Switch Triggers
    # -------------------------------------------------------------------------
    
    def emergency_stop(self, reason: str = "Manual stop") -> None:
        """
        Trigger global kill switch immediately.
        
        Use for manual intervention or automated safety triggers.
        """
        if self._global_kill:
            logger.warning(f"[risk] Kill switch already triggered, ignoring: {reason}")
            return
        
        self._trigger_kill(KillSwitchReason.MANUAL, reason)
        logger.critical(f"[risk] EMERGENCY STOP: {reason}")
    
    def _trigger_kill(self, reason: KillSwitchReason, details: str) -> None:
        """Internal method to trigger kill switch."""
        old_state = self.get_state()
        
        self._global_kill = True
        self._kill_reason = reason
        self._kill_details = details
        self._kill_timestamp = self._now()
        
        event = KillSwitchEvent(
            timestamp=self._kill_timestamp,
            old_state=old_state,
            new_state=KillSwitchState.TRIGGERED,
            reason=reason,
            details=details,
        )
        self._events.append(event)

        # Record session event
        try:
            from core.session_log import record_event
            record_event(
                category="kill_switch",
                severity="critical",
                title="Kill switch TRIGGERED",
                detail=details,
                hint="Reset via Mode & Safety panel after investigating the trigger cause.",
                metadata={"reason": reason.value if hasattr(reason, 'value') else str(reason)},
            )
        except Exception:
            pass
        
        # Notify callbacks
        for callback in self._callbacks:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"[risk] Callback error: {e}")
    
    def reset(self, operator: str = "system") -> bool:
        """
        Reset kill switch to allow trading.
        
        Requires explicit operator acknowledgment.
        Returns True if reset successful.
        """
        if not self._global_kill:
            logger.info("[risk] Kill switch not triggered, nothing to reset")
            return True
        
        old_reason = self._kill_reason
        old_details = self._kill_details
        
        self._global_kill = False
        self._kill_reason = None
        self._kill_details = None
        self._kill_timestamp = None
        
        # Don't reset daily P&L - that persists
        self._error_count = 0
        
        event = KillSwitchEvent(
            timestamp=self._now(),
            old_state=KillSwitchState.TRIGGERED,
            new_state=KillSwitchState.ACTIVE,
            reason=KillSwitchReason.MANUAL,
            details=f"Reset by {operator} (was: {old_reason} - {old_details})",
        )
        self._events.append(event)

        # Record session event
        try:
            from core.session_log import record_event
            record_event(
                category="kill_switch",
                severity="info",
                title="Kill switch RESET",
                detail=f"Reset by {operator} (was: {old_reason} - {old_details})",
                hint="Monitor for recurrence. If the trigger was automatic, check risk thresholds.",
                metadata={"operator": operator},
            )
        except Exception:
            pass
        
        logger.warning(f"[risk] Kill switch RESET by {operator}")
        return True
    
    # -------------------------------------------------------------------------
    # P&L Tracking
    # -------------------------------------------------------------------------
    
    def record_pnl(self, pnl: float) -> bool:
        """
        Record P&L from a trade.
        
        Automatically triggers daily loss kill if limit exceeded.
        Returns True if trading can continue, False if killed.
        """
        self._daily_pnl += pnl
        
        # Check daily loss limit (negative P&L)
        if self._daily_pnl < 0 and abs(self._daily_pnl) >= self.daily_loss_limit:
            self._trigger_kill(
                KillSwitchReason.DAILY_LOSS,
                f"Daily loss ${abs(self._daily_pnl):.2f} exceeds limit ${self.daily_loss_limit:.2f}"
            )
            logger.critical(
                f"[risk] DAILY LOSS KILL: ${abs(self._daily_pnl):.2f} >= ${self.daily_loss_limit:.2f}"
            )
            return False
        
        return True
    
    def update_position_value(self, total_value: float) -> bool:
        """
        Update total position value.
        
        Triggers kill if position limit exceeded.
        Returns True if trading can continue.
        """
        self._total_position_value = total_value
        
        if total_value > self.max_position_value:
            self._trigger_kill(
                KillSwitchReason.POSITION_LIMIT,
                f"Position value ${total_value:.2f} exceeds limit ${self.max_position_value:.2f}"
            )
            logger.critical(
                f"[risk] POSITION LIMIT KILL: ${total_value:.2f} > ${self.max_position_value:.2f}"
            )
            return False
        
        return True
    
    # -------------------------------------------------------------------------
    # Error Tracking
    # -------------------------------------------------------------------------
    
    def record_error(self) -> bool:
        """
        Record an error occurrence.
        
        Triggers kill if error threshold exceeded within 1 hour.
        Returns True if trading can continue.
        """
        now = time.time()
        
        # Reset counter if outside 1-hour window
        if now - self._error_window_start > 3600:
            self._error_count = 0
            self._error_window_start = now
        
        self._error_count += 1
        
        if self._error_count >= self.error_threshold:
            self._trigger_kill(
                KillSwitchReason.ERROR_THRESHOLD,
                f"{self._error_count} errors in last hour exceeds threshold {self.error_threshold}"
            )
            logger.critical(
                f"[risk] ERROR THRESHOLD KILL: {self._error_count} errors in 1 hour"
            )
            return False
        
        return True
    
    # -------------------------------------------------------------------------
    # Callbacks
    # -------------------------------------------------------------------------
    
    def reset_daily_counters(self) -> None:
        """Zero transient PnL / error counters for a fresh start.

        Kill-switch state (_global_kill, _kill_reason, etc.) is
        deliberately **preserved** so a reset cannot silently
        re-enable trading.
        """
        self._daily_pnl = 0.0
        self._daily_pnl_reset_date = self._today()
        self._total_position_value = 0.0
        self._error_count = 0
        self._error_window_start = time.time()
        self._events.clear()
        logger.info("[risk] Daily counters reset (kill-switch state preserved)")

    def on_kill(self, callback: Callable[[KillSwitchEvent], None]) -> None:
        """Register callback for kill switch events."""
        self._callbacks.append(callback)
    
    def get_events(self, limit: int = 10) -> List[KillSwitchEvent]:
        """Get recent kill switch events."""
        return self._events[-limit:]


# Global singleton instance
risk_controller = RiskController()


def can_trade() -> bool:
    """Convenience function to check if trading is allowed."""
    return risk_controller.can_trade()


def emergency_stop(reason: str = "Manual stop") -> None:
    """Convenience function for emergency stop."""
    risk_controller.emergency_stop(reason)


def get_risk_status() -> dict:
    """Convenience function to get risk status."""
    return risk_controller.get_status()
