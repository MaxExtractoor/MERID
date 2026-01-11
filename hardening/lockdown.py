"""
Lockdown - System-wide emergency halt per MASTER_SPEC v1.0

This module implements the lockdown capability for MERID:
- Immediate halt of all execution
- Governance override
- Human intervention point
- Audit trail for lockdown events

Reference: MASTER_SPEC.md Section 8.2 (Governance Safeguards)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional

from core.events import EventEnvelope, EventType, create_audit_event
from utils.logger import get_logger

logger = get_logger("hardening.lockdown")


class LockdownLevel(Enum):
    """Lockdown severity levels."""
    NONE = "none"
    PARTIAL = "partial"
    FULL = "full"
    EMERGENCY = "emergency"


class LockdownReason(Enum):
    """Reasons for lockdown."""
    MANUAL = "manual"
    RISK_THRESHOLD = "risk_threshold"
    CONSENSUS_FAILURE = "consensus_failure"
    ORACLE_FAILURE = "oracle_failure"
    SYSTEM_ERROR = "system_error"
    SECURITY_BREACH = "security_breach"
    MARKET_ANOMALY = "market_anomaly"
    SCHEDULED = "scheduled"


@dataclass
class LockdownEvent:
    """Record of a lockdown event."""
    event_id: str
    level: LockdownLevel
    reason: LockdownReason
    triggered_by: str
    message: str
    timestamp: float = field(default_factory=time.time)
    resolved_at: Optional[float] = None
    resolved_by: Optional[str] = None
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass
class LockdownConfig:
    """Configuration for lockdown behavior."""
    
    auto_lockdown_on_critical_error: bool = True
    
    max_consecutive_failures: int = 5
    
    require_human_unlock: bool = True
    
    auto_unlock_timeout_seconds: Optional[float] = None
    
    notify_on_lockdown: bool = True


class LockdownManager:
    """
    Manages system-wide lockdown state.
    
    Capabilities:
    - Trigger immediate lockdown at various levels
    - Block execution during lockdown
    - Require human intervention for unlock
    - Maintain audit trail of all lockdown events
    
    Lockdown Levels:
    - NONE: Normal operation
    - PARTIAL: Block new trades, allow monitoring
    - FULL: Block all automated actions
    - EMERGENCY: Halt everything, close positions
    """
    
    def __init__(self, config: Optional[LockdownConfig] = None) -> None:
        """
        Initialize lockdown manager.
        
        Args:
            config: Optional configuration override
        """
        self.config = config or LockdownConfig()
        
        self._current_level = LockdownLevel.NONE
        self._current_reason: Optional[LockdownReason] = None
        self._lockdown_time: Optional[float] = None
        self._locked_by: Optional[str] = None
        
        self._event_history: List[LockdownEvent] = []
        self._consecutive_failures = 0
        
        self._callbacks: List[Callable[[LockdownLevel, LockdownReason], None]] = []
        self._event_emitters: List[Callable[[EventEnvelope], None]] = []
        
        self._logger = get_logger("hardening.lockdown.manager")
    
    @property
    def is_locked(self) -> bool:
        """Check if system is in any lockdown state."""
        return self._current_level != LockdownLevel.NONE
    
    @property
    def level(self) -> LockdownLevel:
        """Current lockdown level."""
        return self._current_level
    
    @property
    def reason(self) -> Optional[LockdownReason]:
        """Reason for current lockdown."""
        return self._current_reason
    
    def can_execute(self) -> bool:
        """Check if execution is allowed."""
        return self._current_level in (LockdownLevel.NONE, LockdownLevel.PARTIAL)
    
    def can_trade(self) -> bool:
        """Check if trading is allowed."""
        return self._current_level == LockdownLevel.NONE
    
    def trigger_lockdown(
        self,
        level: LockdownLevel,
        reason: LockdownReason,
        triggered_by: str,
        message: str = "",
        metadata: Optional[Dict[str, object]] = None,
    ) -> LockdownEvent:
        """
        Trigger a lockdown.
        
        Args:
            level: Lockdown severity level
            reason: Reason for lockdown
            triggered_by: Entity triggering lockdown
            message: Human-readable message
            metadata: Additional context
            
        Returns:
            LockdownEvent record
        """
        if level == LockdownLevel.NONE:
            raise ValueError("Cannot trigger lockdown with level NONE")
        
        event = LockdownEvent(
            event_id=f"lockdown_{int(time.time())}",
            level=level,
            reason=reason,
            triggered_by=triggered_by,
            message=message,
            metadata=metadata or {},
        )
        
        self._current_level = level
        self._current_reason = reason
        self._lockdown_time = time.time()
        self._locked_by = triggered_by
        
        self._event_history.append(event)
        
        self._logger.warning(
            "LOCKDOWN TRIGGERED: level=%s, reason=%s, by=%s, message=%s",
            level.value, reason.value, triggered_by, message
        )
        
        self._notify_callbacks(level, reason)
        self._emit_audit_event("lockdown_triggered", {
            "level": level.value,
            "reason": reason.value,
            "triggered_by": triggered_by,
            "message": message,
        })
        
        return event
    
    def release_lockdown(
        self,
        released_by: str,
        message: str = "",
    ) -> bool:
        """
        Release lockdown and return to normal operation.
        
        Args:
            released_by: Entity releasing lockdown
            message: Release message
            
        Returns:
            True if lockdown was released
        """
        if not self.is_locked:
            return False
        
        if self.config.require_human_unlock:
            if not released_by.startswith("human:"):
                self._logger.warning(
                    "Lockdown release rejected: requires human unlock (attempted by %s)",
                    released_by
                )
                return False
        
        if self._event_history:
            last_event = self._event_history[-1]
            if not last_event.resolved_at:
                last_event.resolved_at = time.time()
                last_event.resolved_by = released_by
        
        old_level = self._current_level
        self._current_level = LockdownLevel.NONE
        self._current_reason = None
        self._lockdown_time = None
        self._locked_by = None
        self._consecutive_failures = 0
        
        self._logger.info(
            "LOCKDOWN RELEASED: was=%s, by=%s, message=%s",
            old_level.value, released_by, message
        )
        
        self._notify_callbacks(LockdownLevel.NONE, LockdownReason.MANUAL)
        self._emit_audit_event("lockdown_released", {
            "previous_level": old_level.value,
            "released_by": released_by,
            "message": message,
        })
        
        return True
    
    def record_failure(self, component: str, error: str) -> None:
        """
        Record a system failure.
        
        May trigger automatic lockdown if threshold exceeded.
        
        Args:
            component: Component that failed
            error: Error description
        """
        self._consecutive_failures += 1
        
        self._logger.warning(
            "System failure recorded: component=%s, error=%s, consecutive=%d",
            component, error, self._consecutive_failures
        )
        
        if self.config.auto_lockdown_on_critical_error:
            if self._consecutive_failures >= self.config.max_consecutive_failures:
                self.trigger_lockdown(
                    level=LockdownLevel.FULL,
                    reason=LockdownReason.SYSTEM_ERROR,
                    triggered_by="auto:failure_threshold",
                    message=f"Automatic lockdown after {self._consecutive_failures} consecutive failures. Last: {component}: {error}",
                )
    
    def record_success(self) -> None:
        """Record a successful operation (resets failure counter)."""
        self._consecutive_failures = 0
    
    def get_status(self) -> Dict[str, object]:
        """Get current lockdown status."""
        return {
            "is_locked": self.is_locked,
            "level": self._current_level.value,
            "reason": self._current_reason.value if self._current_reason else None,
            "locked_by": self._locked_by,
            "lockdown_time": self._lockdown_time,
            "duration_seconds": (
                time.time() - self._lockdown_time
                if self._lockdown_time else None
            ),
            "can_execute": self.can_execute(),
            "can_trade": self.can_trade(),
            "consecutive_failures": self._consecutive_failures,
            "event_count": len(self._event_history),
        }
    
    def get_event_history(self, limit: int = 50) -> List[LockdownEvent]:
        """Get recent lockdown events."""
        return self._event_history[-limit:]
    
    def register_callback(
        self,
        callback: Callable[[LockdownLevel, LockdownReason], None],
    ) -> None:
        """Register callback for lockdown state changes."""
        self._callbacks.append(callback)
    
    def register_event_emitter(
        self,
        emitter: Callable[[EventEnvelope], None],
    ) -> None:
        """Register event emitter for audit events."""
        self._event_emitters.append(emitter)
    
    def _notify_callbacks(
        self,
        level: LockdownLevel,
        reason: LockdownReason,
    ) -> None:
        """Notify all registered callbacks."""
        for callback in self._callbacks:
            try:
                callback(level, reason)
            except Exception as e:
                self._logger.error("Callback error: %s", e)
    
    def _emit_audit_event(
        self,
        action: str,
        details: Dict[str, object],
    ) -> None:
        """Emit audit event."""
        event = create_audit_event(
            action=action,
            actor="lockdown_manager",
            details=details,
            severity="critical" if "triggered" in action else "info",
        )
        
        for emitter in self._event_emitters:
            try:
                emitter(event)
            except Exception as e:
                self._logger.error("Event emitter error: %s", e)


_lockdown_manager: Optional[LockdownManager] = None


def get_lockdown_manager() -> LockdownManager:
    """Get or create global lockdown manager."""
    global _lockdown_manager
    if _lockdown_manager is None:
        _lockdown_manager = LockdownManager()
    return _lockdown_manager


def trigger_emergency_lockdown(
    reason: str,
    triggered_by: str = "system",
) -> LockdownEvent:
    """
    Trigger emergency lockdown.
    
    Convenience function for critical situations.
    """
    manager = get_lockdown_manager()
    return manager.trigger_lockdown(
        level=LockdownLevel.EMERGENCY,
        reason=LockdownReason.SECURITY_BREACH,
        triggered_by=triggered_by,
        message=reason,
    )


def is_system_locked() -> bool:
    """Check if system is currently locked."""
    return get_lockdown_manager().is_locked


def can_execute() -> bool:
    """Check if execution is currently allowed."""
    return get_lockdown_manager().can_execute()


def can_trade() -> bool:
    """Check if trading is currently allowed."""
    return get_lockdown_manager().can_trade()
