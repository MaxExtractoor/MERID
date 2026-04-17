"""Integration bridge between ErrorBudget and existing risk systems.

This module provides seamless integration between:
1. The new ErrorBudget system (P0-P3 severity, centralized tracking)
2. The existing RiskController (kill switches, error thresholds)
3. The existing ErrorClassification system (legacy severity mapping)

Usage:
    # In existing code using RiskController:
    from merid.core.error_budget_integration import record_to_error_budget
    
    # Record an error with legacy classification
    record_to_error_budget(
        error_code="KALSHI_AUTH_FAIL",
        severity="critical",  # Maps to P0
        context={"venue": "kalshi"}
    )

[AGENT_AUDIT: Section 7.4 - Error Budget INTEGRATE phase]
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable, Dict, Optional, TypeVar

from merid.core.error_budget import (
    ErrorBudget,
    ErrorBudgetState,
    ErrorEvent,
    Severity,
    record_p0,
    record_p1,
    record_p2,
    record_p3,
    get_budget_status,
)
from merid.risk.error_classification import (
    ErrorSeverity as LegacySeverity,
    ErrorClass,
    classify_error,
    should_count_error,
)
from merid.risk.kill_switches import RiskController, KillSwitchReason

logger = logging.getLogger("merid.core.error_budget_integration")

# ── Severity Mapping ───────────────────────────────────────────────────

_LEGACY_TO_NEW_SEVERITY: Dict[str, Severity] = {
    LegacySeverity.CRITICAL.value: Severity.P0,   # Critical = P0
    LegacySeverity.HIGH.value: Severity.P1,       # High = P1
    LegacySeverity.MEDIUM.value: Severity.P2,     # Medium = P2
    LegacySeverity.LOW.value: Severity.P3,        # Low = P3
}

_NEW_TO_LEGACY_SEVERITY: Dict[Severity, str] = {
    Severity.P0: LegacySeverity.CRITICAL.value,
    Severity.P1: LegacySeverity.HIGH.value,
    Severity.P2: LegacySeverity.MEDIUM.value,
    Severity.P3: LegacySeverity.LOW.value,
}

# ── Integration Functions ─────────────────────────────────────────────


def map_legacy_severity(legacy_severity: str) -> Severity:
    """Map legacy ErrorSeverity to new P0-P3 Severity."""
    return _LEGACY_TO_NEW_SEVERITY.get(legacy_severity.lower(), Severity.P2)


def record_to_error_budget(
    error_code: str,
    severity: str,  # "critical", "high", "medium", "low" or "p0", "p1", "p2", "p3"
    message: str,
    context: Optional[Dict[str, Any]] = None,
    check_budget_state: bool = True,
) -> ErrorBudgetState:
    """Record an error to the error budget using legacy severity strings.
    
    This is the primary integration point for existing code that uses
    legacy severity levels. It maps them to P0-P3 and records the event.
    
    Args:
        error_code: Machine-parseable error code (e.g., "KALSHI_AUTH_FAIL")
        severity: Legacy severity string ("critical"/"high"/"medium"/"low")
                  or new P-level ("p0"/"p1"/"p2"/"p3")
        message: Human-readable error message
        context: Optional metadata (venue, agent, etc.)
        check_budget_state: If True, return budget state; if False, return immediately
        
    Returns:
        Current ErrorBudgetState
    """
    # Normalize severity string
    severity_lower = severity.lower()
    
    # Map to new severity
    if severity_lower in ("p0", "p0_critical"):
        new_severity = Severity.P0
    elif severity_lower in ("p1", "p1_serious"):
        new_severity = Severity.P1
    elif severity_lower in ("p2", "p2_warning"):
        new_severity = Severity.P2
    elif severity_lower in ("p3", "p3_info"):
        new_severity = Severity.P3
    else:
        # Try legacy mapping
        new_severity = _LEGACY_TO_NEW_SEVERITY.get(severity_lower, Severity.P2)
    
    # Record to budget using appropriate convenience function
    if new_severity == Severity.P0:
        return record_p0(error_code, message, **(context or {}))
    elif new_severity == Severity.P1:
        return record_p1(error_code, message, **(context or {}))
    elif new_severity == Severity.P2:
        return record_p2(error_code, message, **(context or {}))
    else:  # P3
        return record_p3(error_code, message, **(context or {}))


def record_classified_error(
    error_code: str,
    context: Optional[str] = None,
    details: Optional[str] = None,
    is_transient: bool = False,
) -> Dict[str, Any]:
    """Record an error using the existing classification system.
    
    This bridges the existing `classify_error()` and `should_count_error()`
    functions to the new error budget system.
    
    Args:
        error_code: Error code to classify
        context: Optional context string for classification
        details: Human-readable details
        is_transient: Whether this is a transient/expected error
        
    Returns:
        Dict with budget_state, classification, and should_count
    """
    # Use existing classification
    classification = classify_error(error_code, context, is_transient)
    should_count, _ = should_count_error(error_code, context)
    
    # Map to new severity
    new_severity = map_legacy_severity(classification.severity.value)
    
    # Build context dict
    ctx = {}
    if context:
        ctx["context"] = context
    ctx["is_transient"] = classification.is_transient
    ctx["counts_toward_budget"] = classification.counts_toward_budget
    ctx["should_count"] = should_count
    
    # Record to budget
    budget = ErrorBudget.get_instance()
    state = budget.record(ErrorEvent(
        severity=new_severity,
        code=classification.error_class.value,
        message=details or classification.description,
        context=ctx
    ))
    
    return {
        "budget_state": state.value,
        "classification": classification,
        "should_count": should_count,
        "new_severity": new_severity.value,
    }


# ── RiskController Integration ───────────────────────────────────────


def setup_error_budget_kill_switch_bridge(risk_controller: RiskController) -> None:
    """Connect ErrorBudget state changes to RiskController kill switch.
    
    When the error budget becomes EXHAUSTED, this triggers the kill switch
    via the RiskController. This ensures the two systems work together.
    
    Args:
        risk_controller: The RiskController instance to wire up
    """
    budget = ErrorBudget.get_instance()
    
    def _on_budget_exhausted(
        old_state: ErrorBudgetState,
        new_state: ErrorBudgetState,
        event: ErrorEvent
    ) -> None:
        """Callback triggered when budget state changes."""
        if new_state == ErrorBudgetState.EXHAUSTED:
            logger.critical(
                "[error_budget_bridge] Budget EXHAUSTED - triggering kill switch | "
                "code=%s | severity=%s",
                event.code, event.severity.value
            )
            
            # Trigger kill switch via RiskController
            # Use record_error_classified for proper integration
            try:
                risk_controller.record_error_classified(
                    error_code="ERROR_BUDGET_EXHAUSTED",
                    context="error_budget_bridge",
                    details=f"Error budget exhausted due to {event.code} ({event.severity.value})"
                )
            except Exception as e:
                logger.error("[error_budget_bridge] Failed to trigger kill switch: %s", e)
                # Fallback: try legacy method
                try:
                    risk_controller.record_error(error_hint="ERROR_BUDGET_EXHAUSTED")
                except Exception as e2:
                    logger.critical(
                        "[error_budget_bridge] CRITICAL: Failed to trigger kill switch: %s",
                        e2
                    )
    
    # Register the callback
    budget.on_state_transition(_on_budget_exhausted)
    logger.info("[error_budget_bridge] Kill switch bridge established")


def sync_error_budget_to_kill_switch(risk_controller: RiskController) -> bool:
    """Sync current error budget state to kill switch.
    
    Returns True if kill switch should be engaged.
    """
    budget = ErrorBudget.get_instance()
    
    # Check if budget can halt trading
    if budget.can_halt_trading():
        # Budget is exhausted and not in grace period
        status = budget.get_status()
        logger.critical(
            "[error_budget_bridge] Budget EXHAUSTED detected - kill switch should engage | "
            "p0_count=%d, p1_weighted=%.1f",
            status["budget_consuming_counts"]["p0_count"],
            status["budget_consuming_counts"]["p1_weighted"]
        )
        return True
    
    return False


# ── Decorators for Error Budget Integration ────────────────────────────

F = TypeVar("F", bound=Callable[..., Any])


def with_error_budget_tracking(
    error_code: str,
    severity: Severity = Severity.P1,
    context: Optional[Dict[str, Any]] = None
) -> Callable[[F], F]:
    """Decorator to track function errors in the error budget.
    
    Usage:
        @with_error_budget_tracking("KALSHI_API_ERROR", Severity.P1)
        def call_kalshi_api():
            ...
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # Record to error budget
                budget = ErrorBudget.get_instance()
                budget.record(ErrorEvent(
                    severity=severity,
                    code=error_code,
                    message=f"{func.__name__} failed: {e}",
                    context={
                        "function": func.__name__,
                        "exception": type(e).__name__,
                        **(context or {})
                    }
                ))
                # Re-raise so caller can handle
                raise
        return wrapper
    return decorator


def with_p0_protection(error_code: str, context: Optional[Dict[str, Any]] = None) -> Callable[[F], F]:
    """Decorator for P0-critical operations that must halt on failure.
    
    Any exception will be recorded as P0 and may trigger kill switch.
    """
    return with_error_budget_tracking(error_code, Severity.P0, context)


def with_p1_warning(error_code: str, context: Optional[Dict[str, Any]] = None) -> Callable[[F], F]:
    """Decorator for P1-serious operations that should degrade on failure.
    """
    return with_error_budget_tracking(error_code, Severity.P1, context)


# ── Async Exception Handler Integration ────────────────────────────────


def install_async_exception_handler() -> None:
    """Install the error budget async exception handler.
    
    This sets up a handler for uncaught exceptions in async tasks that
    routes them to the error budget instead of crashing the event loop.
    """
    from merid.core.error_budget import setup_async_exception_handler
    setup_async_exception_handler()
    logger.info("[error_budget_bridge] Async exception handler installed")


# ── Health Check Integration ─────────────────────────────────────────


def get_combined_health_status(risk_controller: Optional[RiskController] = None) -> Dict[str, Any]:
    """Get combined health status from error budget and kill switch.
    
    Returns a unified view of system health including:
    - Error budget state (HEALTHY/DEGRADED/EXHAUSTED)
    - Kill switch status (engaged/disengaged)
    - Overall safe_to_trade status
    """
    budget = ErrorBudget.get_instance()
    budget_status = budget.get_status()
    
    result = {
        "error_budget": budget_status,
        "kill_switch": None,
        "safe_to_trade": True,
        "should_halt": False,
    }
    
    # Check kill switch if controller provided
    if risk_controller is not None:
        try:
            can_trade = risk_controller.can_trade()
            result["kill_switch"] = {
                "engaged": not can_trade,
                "can_trade": can_trade,
            }
            result["safe_to_trade"] = result["safe_to_trade"] and can_trade
        except Exception as e:
            logger.warning("[error_budget_bridge] Failed to check kill switch: %s", e)
    
    # Check if budget should halt trading
    if budget.can_halt_trading():
        result["should_halt"] = True
        result["safe_to_trade"] = False
    
    return result


# ── Convenience Imports ───────────────────────────────────────────────

__all__ = [
    # Core functions
    "map_legacy_severity",
    "record_to_error_budget",
    "record_classified_error",
    
    # RiskController integration
    "setup_error_budget_kill_switch_bridge",
    "sync_error_budget_to_kill_switch",
    
    # Decorators
    "with_error_budget_tracking",
    "with_p0_protection",
    "with_p1_warning",
    
    # Health checks
    "get_combined_health_status",
    "install_async_exception_handler",
    
    # Re-export for convenience
    "ErrorBudget",
    "ErrorBudgetState",
    "ErrorEvent",
    "Severity",
    "record_p0",
    "record_p1",
    "record_p2",
    "record_p3",
    "get_budget_status",
]
