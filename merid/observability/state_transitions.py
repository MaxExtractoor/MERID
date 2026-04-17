"""
State Transition Logger

Logs and alerts on critical state transitions:
- Reconciliation status changes (ok → degraded → broken)
- Kill switch activations/deactivations
- Trading mode changes (live ↔ paper ↔ halted)

These transitions are logged with full context for incident reconstruction.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Callable, Any

logger = logging.getLogger("merid.state_transitions")


class TransitionType(str, Enum):
    RECONCILIATION = "reconciliation"
    KILL_SWITCH = "kill_switch"
    TRADING_MODE = "trading_mode"
    DATA_SOURCE = "data_source"


class TransitionSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class StateTransition:
    """Record of a state transition."""
    transition_type: TransitionType
    severity: TransitionSeverity
    timestamp: str
    previous_state: str
    new_state: str
    context: Dict[str, Any]
    triggered_by: Optional[str] = None
    affected_orders: Optional[List[str]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    def to_log_line(self) -> str:
        """Format as structured log line for ingestion."""
        return json.dumps({
            "event": "state_transition",
            "type": self.transition_type,
            "severity": self.severity,
            "timestamp": self.timestamp,
            "transition": f"{self.previous_state} -> {self.new_state}",
            **self.context,
        })


class StateTransitionLogger:
    """
    Monitors and logs state transitions.
    
    Usage:
        transition_logger = StateTransitionLogger()
        
        # In reconciliation check
        if new_status != old_status:
            transition_logger.log_reconciliation_change(old_status, new_status, context)
    """
    
    def __init__(self):
        self._last_states: Dict[str, str] = {}
        self._handlers: List[Callable[[StateTransition], None]] = []
        self._transition_history: List[StateTransition] = []
        self._max_history = 1000
        
    def add_handler(self, handler: Callable[[StateTransition], None]) -> None:
        """Add a handler for transitions (e.g., alert, webhook, log)."""
        self._handlers.append(handler)
        
    def _emit(self, transition: StateTransition) -> None:
        """Emit transition to all handlers."""
        # Always log
        logger.warning(transition.to_log_line())
        
        # Store in history
        self._transition_history.append(transition)
        if len(self._transition_history) > self._max_history:
            self._transition_history.pop(0)
        
        # Call handlers
        for handler in self._handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    asyncio.create_task(handler(transition))
                else:
                    handler(transition)
            except Exception as exc:
                logger.error(f"Transition handler failed: {exc}")
    
    def log_reconciliation_change(
        self,
        previous_status: str,
        new_status: str,
        context: Dict[str, Any],
        affected_orders: Optional[List[str]] = None,
    ) -> None:
        """Log a reconciliation status change."""
        if previous_status == new_status:
            return
        
        severity = TransitionSeverity.INFO
        if new_status == "broken":
            severity = TransitionSeverity.CRITICAL
        elif new_status == "degraded":
            severity = TransitionSeverity.WARNING
        elif previous_status == "broken" and new_status == "ok":
            severity = TransitionSeverity.INFO  # Recovery
        
        transition = StateTransition(
            transition_type=TransitionType.RECONCILIATION,
            severity=severity,
            timestamp=datetime.now(timezone.utc).isoformat(),
            previous_state=previous_status,
            new_state=new_status,
            context=context,
            affected_orders=affected_orders,
        )
        
        self._emit(transition)
        
    def log_kill_switch_change(
        self,
        was_active: bool,
        is_active: bool,
        triggered_by: str,
        reason: str,
        affected_positions: Optional[List[str]] = None,
    ) -> None:
        """Log a kill switch activation/deactivation."""
        if was_active == is_active:
            return
        
        transition = StateTransition(
            transition_type=TransitionType.KILL_SWITCH,
            severity=TransitionSeverity.CRITICAL if is_active else TransitionSeverity.INFO,
            timestamp=datetime.now(timezone.utc).isoformat(),
            previous_state="active" if was_active else "inactive",
            new_state="active" if is_active else "inactive",
            context={"reason": reason, "triggered_by": triggered_by},
            triggered_by=triggered_by,
            affected_orders=affected_positions,
        )
        
        self._emit(transition)
        
    def log_trading_mode_change(
        self,
        previous_mode: str,
        new_mode: str,
        triggered_by: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log a trading mode change (live/paper/sim/halted)."""
        if previous_mode == new_mode:
            return
        
        severity = TransitionSeverity.INFO
        if new_mode == "halted":
            severity = TransitionSeverity.CRITICAL
        elif new_mode == "live" and previous_mode != "live":
            severity = TransitionSeverity.WARNING  # Entering live
        
        transition = StateTransition(
            transition_type=TransitionType.TRADING_MODE,
            severity=severity,
            timestamp=datetime.now(timezone.utc).isoformat(),
            previous_state=previous_mode,
            new_state=new_mode,
            context=context or {},
            triggered_by=triggered_by,
        )
        
        self._emit(transition)
        
    def get_recent_transitions(
        self,
        transition_type: Optional[TransitionType] = None,
        since_minutes: int = 60,
    ) -> List[StateTransition]:
        """Get recent transitions for incident analysis."""
        cutoff = datetime.now(timezone.utc).timestamp() - (since_minutes * 60)
        
        filtered = []
        for t in reversed(self._transition_history):
            ts = datetime.fromisoformat(t.timestamp.replace("Z", "+00:00")).timestamp()
            if ts < cutoff:
                break
            if transition_type is None or t.transition_type == transition_type:
                filtered.append(t)
        
        return list(reversed(filtered))
    
    def export_incident_timeline(
        self,
        start_time: str,
        end_time: str,
    ) -> List[Dict[str, Any]]:
        """Export all transitions in a time range for incident replay."""
        start_ts = datetime.fromisoformat(start_time.replace("Z", "+00:00")).timestamp()
        end_ts = datetime.fromisoformat(end_time.replace("Z", "+00:00")).timestamp()
        
        return [
            t.to_dict() for t in self._transition_history
            if start_ts <= datetime.fromisoformat(t.timestamp.replace("Z", "+00:00")).timestamp() <= end_ts
        ]


# Global singleton
_transition_logger: Optional[StateTransitionLogger] = None


def get_state_transition_logger() -> StateTransitionLogger:
    """Get or create the global state transition logger."""
    global _transition_logger
    if _transition_logger is None:
        _transition_logger = StateTransitionLogger()
    return _transition_logger


# Pre-built handlers

async def telegram_transition_alert(transition: StateTransition) -> None:
    """Send critical transitions to Telegram."""
    if transition.severity != TransitionSeverity.CRITICAL:
        return
    
    try:
        from merid.alerts.webhook_client import tg_send
        
        emoji = {
            TransitionType.RECONCILIATION: "🔄",
            TransitionType.KILL_SWITCH: "🛑",
            TransitionType.TRADING_MODE: "⚠️",
        }.get(transition.transition_type, "⚡")
        
        message = (
            f"<b>{emoji} CRITICAL STATE TRANSITION</b>\n\n"
            f"<b>Type:</b> {transition.transition_type.value.upper()}\n"
            f"<b>Transition:</b> {transition.previous_state} → {transition.new_state}\n"
            f"<b>Time:</b> {transition.timestamp[:19]}\n"
        )
        
        if transition.triggered_by:
            message += f"<b>Triggered by:</b> {transition.triggered_by}\n"
        
        if transition.affected_orders:
            message += f"<b>Affected:</b> {len(transition.affected_orders)} orders/positions\n"
        
        if transition.context:
            message += f"\n<b>Context:</b>\n"
            for key, value in list(transition.context.items())[:5]:
                message += f"  • {key}: {value}\n"
        
        await tg_send(message, parse_mode="HTML")
    except Exception as exc:
        logger.error(f"Failed to send transition alert: {exc}")


def webhook_transition_handler(transition: StateTransition) -> None:
    """Send transitions to webhook for external monitoring."""
    try:
        import os
        import requests
        
        webhook_url = os.getenv("STATE_TRANSITION_WEBHOOK_URL")
        if not webhook_url:
            return
        
        payload = {
            "event": "state_transition",
            "transition_type": transition.transition_type.value,
            "severity": transition.severity.value,
            "timestamp": transition.timestamp,
            "previous_state": transition.previous_state,
            "new_state": transition.new_state,
            "context": transition.context,
        }
        
        requests.post(webhook_url, json=payload, timeout=5)
    except Exception as exc:
        logger.debug(f"Webhook transition handler failed: {exc}")


# Integration helpers

def wire_standard_transition_handlers() -> None:
    """Wire up standard transition handlers."""
    stl = get_state_transition_logger()
    
    # Wire Telegram for critical transitions
    try:
        import os
        if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
            stl.add_handler(telegram_transition_alert)
            logger.info("Wired transition alerts to Telegram")
    except Exception:
        pass
    
    # Wire webhook if configured
    if os.getenv("STATE_TRANSITION_WEBHOOK_URL"):
        stl.add_handler(webhook_transition_handler)
        logger.info("Wired transition alerts to webhook")
