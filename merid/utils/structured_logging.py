"""
Structured Logging Module for MERID

Provides consistent, machine-readable log output for all critical events.
"""

import logging
import json
from datetime import datetime
from typing import Dict, Any, Optional


class StructuredLogger:
    """
    Structured logger for MERID trading system.
    
    All critical events (guard trips, mode transitions, kill switches)
    are logged as JSON for easy parsing and alerting.
    """
    
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
    
    def _log_event(self, level: int, event_type: str, **kwargs):
        """Internal method to log structured event."""
        event = {
            "event_type": event_type,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            **kwargs
        }
        
        self.logger.log(level, json.dumps(event))
    
    def log_guard_trip(self, guard_type: str, mode: str, endpoint: str,
                       details: Optional[Dict[str, Any]] = None,
                       source_ip: Optional[str] = None):
        """
        Log a guard trip event.
        
        Args:
            guard_type: Type of guard (e.g., "PASS8_FIX_GUARD")
            mode: Current trading mode (sim/paper/live)
            endpoint: API endpoint that was blocked
            details: Additional context (ticker, quantity, etc.)
            source_ip: Source IP of the request
        """
        self._log_event(
            logging.ERROR,
            "GUARD_TRIP",
            guard=guard_type,
            mode=mode,
            endpoint=endpoint,
            details=details or {},
            source=source_ip
        )
    
    def log_mode_transition(self, from_mode: str, to_mode: str, 
                           triggered_by: str,
                           confirm_token: Optional[str] = None):
        """
        Log a mode transition event.
        
        CRITICAL level because this affects risk posture.
        
        Args:
            from_mode: Previous mode
            to_mode: New mode
            triggered_by: User/system that triggered change
            confirm_token: Confirmation token for destructive changes
        """
        self._log_event(
            logging.CRITICAL,
            "MODE_TRANSITION",
            from_mode=from_mode,
            to_mode=to_mode,
            triggered_by=triggered_by,
            confirm_token_used=confirm_token is not None
        )
    
    def log_kill_switch(self, reason: str, severity: str, source: str,
                       details: Optional[Dict[str, Any]] = None):
        """
        Log a kill switch activation.
        
        CRITICAL level - requires immediate operator attention.
        
        Args:
            reason: Why the kill switch was triggered
            severity: Severity level (critical, high, medium)
            source: Component that triggered the kill switch
            details: Additional context
        """
        self._log_event(
            logging.CRITICAL,
            "KILL_SWITCH",
            reason=reason,
            severity=severity,
            source=source,
            details=details or {}
        )
    
    def log_risk_violation(self, violation_type: str, 
                          current_value: Any, max_allowed: Any,
                          config_source: str):
        """
        Log a risk configuration violation.
        
        Args:
            violation_type: Type of violation (global_cap, fixed_usd, etc.)
            current_value: The violating value
            max_allowed: The maximum allowed value
            config_source: Where the config came from
        """
        self._log_event(
            logging.CRITICAL,
            "RISK_VIOLATION",
            violation_type=violation_type,
            current_value=current_value,
            max_allowed=max_allowed,
            config_source=config_source
        )
    
    def log_order_rejected(self, reason: str, order_details: Dict[str, Any],
                          risk_context: Optional[Dict[str, Any]] = None):
        """
        Log an order rejection by risk system.
        
        Args:
            reason: Why the order was rejected
            order_details: Ticker, side, quantity, price, etc.
            risk_context: Current risk state (bankroll, exposure, etc.)
        """
        self._log_event(
            logging.WARNING,
            "ORDER_REJECTED",
            reason=reason,
            order=order_details,
            risk_context=risk_context or {}
        )
    
    def log_startup_enforcement(self, success: bool, 
                               violations: Optional[list] = None):
        """
        Log startup risk enforcement result.
        
        Args:
            success: Whether enforcement passed
            violations: List of violations if failed
        """
        level = logging.INFO if success else logging.CRITICAL
        self._log_event(
            level,
            "STARTUP_ENFORCEMENT",
            success=success,
            violations=violations or []
        )
    
    def log_executor_failure(self, error: str, fallback_attempted: bool,
                            kill_switch_triggered: bool):
        """
        Log an executor failure event.
        
        Args:
            error: The error that occurred
            fallback_attempted: Whether REST fallback was attempted
            kill_switch_triggered: Whether kill switch was activated
        """
        self._log_event(
            logging.ERROR,
            "EXECUTOR_FAILURE",
            error=error,
            fallback_attempted=fallback_attempted,
            kill_switch_triggered=kill_switch_triggered
        )


# Convenience function for getting logger instance
def get_structured_logger(name: str) -> StructuredLogger:
    """Get a structured logger instance."""
    return StructuredLogger(name)
