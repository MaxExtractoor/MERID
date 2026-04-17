"""Centralized Error Budget System for MERID.

Provides explicit error classification (P0-P3) and budget tracking to ensure:
- Only truly critical conditions can halt or hard-degrade trading
- Advisory and "noisy" issues never consume the error budget
- Halt behavior is centralized, explicit, and observable
- The main async loop never dies on uncaught exceptions

Usage:
    from merid.core.error_budget import ErrorBudget, Severity, ErrorEvent
    
    # Record an error
    budget = ErrorBudget.get_instance()
    state = budget.record(ErrorEvent(
        severity=Severity.P0,
        code="KALSHI_AUTH_FAIL",
        message="Authentication failed",
        context={"venue": "kalshi"}
    ))
    
    # Check current state
    if budget.current_state() == ErrorBudgetState.EXHAUSTED:
        # Halt trading
        pass

Error Budget Semantics:
    - P0 (Critical): Can halt trading. Counts fully toward budget (weight=1.0)
    - P1 (Serious): Can degrade trading. Counts partially toward budget (weight=0.5)
    - P2 (Warning): Never consumes budget. Logged for observability only
    - P3 (Info/Noise): Never consumes budget. Expected retries, minor issues

State Transitions:
    HEALTHY → DEGRADED: When P0/P1 count exceeds warning threshold (default 70%)
    DEGRADED → EXHAUSTED: When P0/P1 count exceeds threshold (default 100%)
    EXHAUSTED → HEALTHY: Only via explicit operator reset()

[AGENT_AUDIT: Section 7.4 - Error Budget PROTECT phase]
"""

from __future__ import annotations

import os
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Set, Tuple

from utils.logger import get_logger

logger = get_logger("merid.core.error_budget")


class Severity(Enum):
    """Error severity tiers per error-budget specification.
    
    P0/P1 consume the error budget and can trigger halt/degrade.
    P2/P3 are advisory only and never consume the budget.
    """
    P0 = "p0_critical"      # Critical: data corruption, invariant violations, auth failures
    P1 = "p1_serious"       # Serious: recoverable issues, rate limits, venue errors  
    P2 = "p2_warning"       # Warning: operational concerns, non-critical degradations
    P3 = "p3_info"          # Info: expected retries, minor validation issues, noise


class ErrorBudgetState(Enum):
    """Error budget lifecycle states."""
    HEALTHY = "healthy"         # Normal trading - budget well within limits
    DEGRADED = "degraded"       # Reduced trading - approaching budget limit
    EXHAUSTED = "exhausted"     # Trading halted - budget exceeded


@dataclass(frozen=True)
class ErrorEvent:
    """Immutable error event record."""
    severity: Severity
    code: str                   # Short machine-parseable code (e.g., "KALSHI_AUTH_FAIL")
    message: str                # Human-readable description
    context: Dict[str, Any] = field(default_factory=dict)  # metadata: agent, venue, etc.
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def __post_init__(self):
        # Normalize code to uppercase with underscores
        object.__setattr__(
            self, 
            'code', 
            self.code.upper().replace("-", "_").replace(" ", "_")
        )


@dataclass
class BudgetConfig:
    """Configuration for error budget thresholds."""
    max_p0_events: int = 10              # P0 events to trigger EXHAUSTED
    max_p1_events: int = 20              # P1 events (weighted) to trigger EXHAUSTED
    warning_threshold_pct: float = 0.70  # % of threshold to enter DEGRADED
    window_seconds: float = 3600.0     # Rolling window for budget (default 1 hour)
    dedup_window_seconds: float = 300.0  # Deduplication window (default 5 min)
    
    @classmethod
    def from_env(cls) -> "BudgetConfig":
        """Load configuration from environment variables."""
        return cls(
            max_p0_events=int(os.getenv("MERID_ERROR_BUDGET_P0_MAX", "10")),
            max_p1_events=int(os.getenv("MERID_ERROR_BUDGET_P1_MAX", "20")),
            warning_threshold_pct=float(os.getenv("MERID_ERROR_BUDGET_WARN_PCT", "0.70")),
            window_seconds=float(os.getenv("MERID_ERROR_BUDGET_WINDOW_SECS", "3600")),
            dedup_window_seconds=float(os.getenv("MERID_ERROR_DEDUP_WINDOW_SECS", "300")),
        )


class ErrorBudget:
    """Centralized error budget tracker.
    
    Thread-safe singleton that tracks P0/P1 errors against configured thresholds.
    P2/P3 errors are logged but never consume the budget.
    
    State Machine:
        HEALTHY: Budget usage < warning_threshold_pct
        DEGRADED: warning_threshold_pct <= usage < 100%
        EXHAUSTED: usage >= 100% (trading must halt)
    """
    
    _instance: Optional["ErrorBudget"] = None
    _lock: threading.Lock = threading.Lock()
    
    # Severity weights for budget consumption
    _SEVERITY_WEIGHTS: Dict[Severity, float] = {
        Severity.P0: 1.0,   # Critical errors count fully
        Severity.P1: 0.5,   # Serious errors count half
        Severity.P2: 0.0,   # Warnings don't count
        Severity.P3: 0.0,   # Info doesn't count
    }
    
    # P0/P1 codes that can trigger budget (explicit whitelist approach)
    _BUDGET_CONSUMING_SEVERITIES: Set[Severity] = {Severity.P0, Severity.P1}
    
    def __new__(cls, *args, **kwargs):
        """Singleton pattern - only one ErrorBudget instance exists."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    @classmethod
    def get_instance(cls) -> "ErrorBudget":
        """Get the singleton ErrorBudget instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset_singleton(cls) -> None:
        """Reset the singleton instance. FOR TESTING ONLY.
        
        This clears the singleton so a fresh instance will be created
        on the next get_instance() call. Use in test setup/teardown.
        """
        with cls._lock:
            if cls._instance is not None:
                # Mark as not initialized so __init__ can run again
                cls._instance._initialized = False
            cls._instance = None
    
    def __init__(self, config: Optional[BudgetConfig] = None):
        """Initialize the error budget tracker.
        
        Idempotent - safe to call multiple times. Only first call configures.
        """
        if getattr(self, '_initialized', False):
            return
        
        self._config = config or BudgetConfig.from_env()
        self._state = ErrorBudgetState.HEALTHY
        
        # Budget tracking (P0/P1 only)
        self._p0_count = 0
        self._p1_weighted = 0.0
        self._window_start = time.time()
        
        # Deduplication: (code, context_key) -> last_counted_timestamp
        self._dedup_cache: Dict[Tuple[str, str], float] = {}
        
        # Event history for observability (circular buffer)
        self._recent_events: List[ErrorEvent] = []
        self._max_event_history = 100
        
        # Per-code counters for diagnostics
        self._code_counts: Dict[str, int] = {}
        
        # Callbacks for state transitions
        self._transition_callbacks: List[Callable[[ErrorBudgetState, ErrorBudgetState, ErrorEvent], None]] = []
        
        # Thread safety
        self._instance_lock = threading.Lock()
        
        # Startup grace period
        self._startup_time = time.time()
        self._startup_grace_seconds = float(os.getenv("MERID_ERROR_BUDGET_STARTUP_GRACE_SECS", "300"))
        
        self._initialized = True
        logger.info(
            "[error_budget] Initialized: P0_max=%d, P1_max=%.1f, warn_pct=%.0f%%, window=%.0fs",
            self._config.max_p0_events,
            self._config.max_p1_events,
            self._config.warning_threshold_pct * 100,
            self._config.window_seconds,
        )
    
    def record(self, event: ErrorEvent) -> ErrorBudgetState:
        """Record an error event and return the current budget state.
        
        This is the primary API for the error budget system. All error
        reporting should flow through this method.
        
        Args:
            event: The error event to record
            
        Returns:
            Current ErrorBudgetState after processing the event
        """
        with self._instance_lock:
            # Reset window if expired
            self._maybe_reset_window_locked()
            
            # Check deduplication
            is_duplicate = self._is_duplicate_locked(event)
            
            # Always track for observability
            self._track_event_locked(event)
            
            # Only P0/P1 consume budget
            consumes_budget = event.severity in self._BUDGET_CONSUMING_SEVERITIES
            
            if consumes_budget and not is_duplicate:
                weight = self._SEVERITY_WEIGHTS[event.severity]
                
                if event.severity == Severity.P0:
                    self._p0_count += 1
                    logger.error(
                        "[error_budget] P0 event: %s | %s | p0_count=%d/%d",
                        event.code, event.message, self._p0_count, self._config.max_p0_events
                    )
                elif event.severity == Severity.P1:
                    self._p1_weighted += weight
                    logger.warning(
                        "[error_budget] P1 event: %s | %s | p1_weighted=%.1f/%.1f",
                        event.code, event.message, self._p1_weighted, self._config.max_p1_events
                    )
                
                # Update code-specific counter
                self._code_counts[event.code] = self._code_counts.get(event.code, 0) + 1
            elif consumes_budget and is_duplicate:
                # Duplicate P0/P1 - don't increment counters but still check state
                logger.warning(
                    "[error_budget] %s event (dup): %s | %s | budget_exempt",
                    event.severity.value.upper(),
                    event.code,
                    event.message,
                )
            else:
                # P2/P3 - log but don't count
                level = "warning" if event.severity == Severity.P2 else "info"
                log_fn = logger.warning if level == "warning" else logger.info
                log_fn(
                    "[error_budget] %s event: %s | %s | budget_exempt",
                    event.severity.value.upper(),
                    event.code,
                    event.message,
                )
            
            # Check for state transition regardless of dedup (for P0/P1)
            if consumes_budget:
                old_state = self._state
                self._update_state_locked()
                
                if old_state != self._state:
                    self._on_state_transition_locked(old_state, self._state, event)
                
                return self._state
            
            return self._state
    
    def current_state(self) -> ErrorBudgetState:
        """Get the current error budget state."""
        with self._instance_lock:
            self._maybe_reset_window_locked()
            return self._state
    
    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive budget status for dashboards/operator visibility.
        
        Returns:
            Dict with current state, counts, thresholds, and recent events.
        """
        with self._instance_lock:
            self._maybe_reset_window_locked()
            
            # Calculate percentages
            p0_pct = (self._p0_count / self._config.max_p0_events * 100) if self._config.max_p0_events > 0 else 0
            p1_pct = (self._p1_weighted / self._config.max_p1_events * 100) if self._config.max_p1_events > 0 else 0
            total_usage_pct = max(p0_pct, p1_pct)
            
            return {
                "state": self._state.value,
                "budget_consuming_counts": {
                    "p0_count": self._p0_count,
                    "p0_max": self._config.max_p0_events,
                    "p0_pct": round(p0_pct, 1),
                    "p1_weighted": round(self._p1_weighted, 2),
                    "p1_max": self._config.max_p1_events,
                    "p1_pct": round(p1_pct, 1),
                    "total_usage_pct": round(total_usage_pct, 1),
                },
                "window": {
                    "start": self._window_start,
                    "elapsed_seconds": round(time.time() - self._window_start, 0),
                    "total_seconds": self._config.window_seconds,
                    "remaining_seconds": round(max(0, self._config.window_seconds - (time.time() - self._window_start)), 0),
                },
                "dedup": {
                    "tracked_keys": len(self._dedup_cache),
                },
                "top_codes": dict(sorted(self._code_counts.items(), key=lambda x: x[1], reverse=True)[:5]),
                "recent_events": [
                    {
                        "severity": e.severity.value,
                        "code": e.code,
                        "message": e.message,
                        "timestamp": e.timestamp.isoformat(),
                    }
                    for e in self._recent_events[-10:]
                ],
                "in_startup_grace": self._in_startup_grace_locked(),
                "grace_remaining_seconds": max(0, self._startup_grace_seconds - (time.time() - self._startup_time)) if self._in_startup_grace_locked() else 0,
            }
    
    def reset(self, operator: str = "system", reason: str = "operator_reset") -> None:
        """Reset the error budget counters (requires explicit operator acknowledgment).
        
        This clears the budget counters and returns to HEALTHY state.
        Should only be called after investigating and resolving the root cause.
        
        Args:
            operator: Who is performing the reset
            reason: Why the reset is being performed
        """
        with self._instance_lock:
            old_state = self._state
            
            self._p0_count = 0
            self._p1_weighted = 0.0
            self._window_start = time.time()
            self._dedup_cache.clear()
            self._state = ErrorBudgetState.HEALTHY
            
            logger.critical(
                "[error_budget] RESET by %s: reason=%s | old_state=%s | counters cleared",
                operator, reason, old_state.value
            )
            
            # Emit structured log
            logger.info(
                "[error_budget] STATE_TRANSITION: %s -> %s | trigger=reset | operator=%s",
                old_state.value, self._state.value, operator
            )
    
    def can_halt_trading(self) -> bool:
        """Check if budget exhaustion should halt trading.
        
        PRODUCTION FIX: Error budget can NEVER halt trading. This method
        always returns False. Only risk/drawdown violations and manual
        kills can halt trading.
        
        The error budget system is now observability-only - it tracks
        P0/P1 errors for metrics and dashboards but never blocks trading.
        
        Returns False always (error counts never halt trading).
        """
        # CRITICAL: Error budget is observability-only
        # Only risk/drawdown/manual kills can halt trading
        return False
    
    def on_state_transition(
        self,
        callback: Callable[[ErrorBudgetState, ErrorBudgetState, ErrorEvent], None]
    ) -> None:
        """Register a callback for state transitions.
        
        Callback receives: (old_state, new_state, triggering_event)
        """
        self._transition_callbacks.append(callback)
    
    def _maybe_reset_window_locked(self) -> None:
        """Reset budget window if expired. Caller must hold lock."""
        elapsed = time.time() - self._window_start
        if elapsed > self._config.window_seconds:
            logger.info(
                "[error_budget] Window reset: elapsed=%.0fs > window=%.0fs | counters cleared",
                elapsed, self._config.window_seconds
            )
            self._p0_count = 0
            self._p1_weighted = 0.0
            self._window_start = time.time()
            self._dedup_cache.clear()
            
            # If we were EXHAUSTED, return to HEALTHY (automatic recovery)
            if self._state == ErrorBudgetState.EXHAUSTED:
                old_state = self._state
                self._state = ErrorBudgetState.HEALTHY
                logger.critical(
                    "[error_budget] Automatic recovery: window expired, returning to HEALTHY"
                )
                logger.info(
                    "[error_budget] STATE_TRANSITION: %s -> %s | trigger=window_reset",
                    old_state.value, self._state.value
                )
    
    def _is_duplicate_locked(self, event: ErrorEvent) -> bool:
        """Check if this event is a duplicate within the dedup window.
        
        Deduplication key is (code, context_key) where context_key is
        derived from the context dict (venue, agent, etc.).
        """
        # Build context key from relevant fields
        context_key = self._build_context_key(event.context)
        key = (event.code, context_key)
        
        now = time.time()
        last_seen = self._dedup_cache.get(key, 0)
        
        if now - last_seen < self._config.dedup_window_seconds:
            # Update timestamp to extend window (sliding window)
            self._dedup_cache[key] = now
            return True
        
        self._dedup_cache[key] = now
        return False
    
    def _build_context_key(self, context: Dict[str, Any]) -> str:
        """Build a stable key from context dict for deduplication."""
        # Use venue + agent if available, else hash of context
        venue = context.get("venue", "")
        agent = context.get("agent", "")
        if venue or agent:
            return f"{venue}:{agent}"
        return str(hash(tuple(sorted(context.items()))))
    
    def _track_event_locked(self, event: ErrorEvent) -> None:
        """Track event in history buffer. Caller must hold lock."""
        self._recent_events.append(event)
        if len(self._recent_events) > self._max_event_history:
            self._recent_events.pop(0)
    
    def _update_state_locked(self) -> None:
        """Update budget state based on current counters. Caller must hold lock."""
        # Calculate total budget usage
        p0_usage = self._p0_count / self._config.max_p0_events if self._config.max_p0_events > 0 else 0
        p1_usage = self._p1_weighted / self._config.max_p1_events if self._config.max_p1_events > 0 else 0
        total_usage = max(p0_usage, p1_usage)
        
        # Determine new state
        if total_usage >= 1.0:
            new_state = ErrorBudgetState.EXHAUSTED
        elif total_usage >= self._config.warning_threshold_pct:
            new_state = ErrorBudgetState.DEGRADED
        else:
            new_state = ErrorBudgetState.HEALTHY
        
        self._state = new_state
    
    def _on_state_transition_locked(
        self,
        old_state: ErrorBudgetState,
        new_state: ErrorBudgetState,
        event: ErrorEvent
    ) -> None:
        """Handle state transition. Caller must hold lock."""
        logger.critical(
            "[error_budget] STATE_TRANSITION: %s -> %s | code=%s | severity=%s",
            old_state.value, new_state.value, event.code, event.severity.value
        )
        
        # Notify callbacks
        for callback in self._transition_callbacks:
            try:
                callback(old_state, new_state, event)
            except Exception as e:
                logger.error("[error_budget] Transition callback error: %s", e)
    
    def _in_startup_grace_locked(self) -> bool:
        """Check if we're still in startup grace period."""
        if self._startup_grace_seconds <= 0:
            return False
        return (time.time() - self._startup_time) < self._startup_grace_seconds


# ── Convenience API for common use cases ─────────────────────────────────


def record_p0(
    code: str,
    message: str,
    **context
) -> ErrorBudgetState:
    """Record a P0 (Critical) error. Convenience wrapper."""
    budget = ErrorBudget.get_instance()
    return budget.record(ErrorEvent(
        severity=Severity.P0,
        code=code,
        message=message,
        context=context
    ))


def record_p1(
    code: str,
    message: str,
    **context
) -> ErrorBudgetState:
    """Record a P1 (Serious) error. Convenience wrapper."""
    budget = ErrorBudget.get_instance()
    return budget.record(ErrorEvent(
        severity=Severity.P1,
        code=code,
        message=message,
        context=context
    ))


def record_p2(
    code: str,
    message: str,
    **context
) -> ErrorBudgetState:
    """Record a P2 (Warning) error. Convenience wrapper."""
    budget = ErrorBudget.get_instance()
    return budget.record(ErrorEvent(
        severity=Severity.P2,
        code=code,
        message=message,
        context=context
    ))


def record_p3(
    code: str,
    message: str,
    **context
) -> ErrorBudgetState:
    """Record a P3 (Info/Noise) error. Convenience wrapper."""
    budget = ErrorBudget.get_instance()
    return budget.record(ErrorEvent(
        severity=Severity.P3,
        code=code,
        message=message,
        context=context
    ))


def get_budget_status() -> Dict[str, Any]:
    """Get current budget status. Convenience wrapper."""
    return ErrorBudget.get_instance().get_status()


def is_budget_exhausted() -> bool:
    """Check if budget is exhausted (and startup grace has passed)."""
    budget = ErrorBudget.get_instance()
    return budget.can_halt_trading()


def reset_budget(operator: str = "system", reason: str = "") -> None:
    """Reset the error budget. Convenience wrapper."""
    ErrorBudget.get_instance().reset(operator, reason)


# ── Integration with existing error classification ─────────────────────


def migrate_legacy_classification(
    error_code: str,
    legacy_severity: str
) -> Tuple[Severity, str]:
    """Map legacy error classification to new P0-P3 severity.
    
    Returns: (new_severity, normalized_code)
    """
    severity_map = {
        "critical": Severity.P0,
        "high": Severity.P1,
        "medium": Severity.P2,
        "low": Severity.P3,
    }
    
    # Map legacy severity
    severity = severity_map.get(legacy_severity.lower(), Severity.P2)
    
    # Normalize code
    normalized = error_code.upper().replace("-", "_").replace(" ", "_")
    
    return severity, normalized


# ── Async exception handler integration ────────────────────────────────


def setup_async_exception_handler() -> None:
    """Install a global exception handler that routes errors to the budget.
    
    This ensures uncaught exceptions in async tasks are classified and
    routed through the error budget rather than killing the event loop.
    """
    import asyncio
    
    def _exception_handler(loop: asyncio.AbstractEventLoop, context: dict) -> None:
        """Handle uncaught exceptions in async tasks."""
        exception = context.get("exception")
        task = context.get("task")
        
        # Classify the exception
        if exception is None:
            severity = Severity.P2
            code = "ASYNC_EXCEPTION_UNKNOWN"
            message = str(context.get("message", "Unknown async error"))
        elif isinstance(exception, ConnectionError):
            severity = Severity.P1
            code = "ASYNC_CONNECTION_ERROR"
            message = f"Connection error in task {task}: {exception}"
        elif isinstance(exception, TimeoutError):
            severity = Severity.P1
            code = "ASYNC_TIMEOUT_ERROR"
            message = f"Timeout in task {task}: {exception}"
        elif isinstance(exception, (ValueError, TypeError)):
            severity = Severity.P2
            code = "ASYNC_VALIDATION_ERROR"
            message = f"Validation error in task {task}: {exception}"
        else:
            # Unknown/unexpected errors are P0 (critical)
            severity = Severity.P0
            code = "ASYNC_UNEXPECTED_ERROR"
            message = f"Unexpected error in task {task}: {type(exception).__name__}: {exception}"
        
        # Record to budget
        budget = ErrorBudget.get_instance()
        state = budget.record(ErrorEvent(
            severity=severity,
            code=code,
            message=message,
            context={
                "task": str(task) if task else None,
                "exception_type": type(exception).__name__ if exception else None,
            }
        ))
        
        # Log with appropriate level
        if severity == Severity.P0:
            logger.critical("[async_exception] %s: %s | budget_state=%s", code, message, state.value)
        elif severity == Severity.P1:
            logger.error("[async_exception] %s: %s | budget_state=%s", code, message, state.value)
        else:
            logger.warning("[async_exception] %s: %s", code, message)
        
        # If budget is exhausted, emit critical alert but don't crash
        if state == ErrorBudgetState.EXHAUSTED:
            logger.critical(
                "[error_budget] EXHAUSTED due to async exception | code=%s | "
                "Trading should halt but event loop continues",
                code
            )
    
    # Install handler
    asyncio.get_event_loop().set_exception_handler(_exception_handler)
    logger.info("[error_budget] Async exception handler installed")


# Global instance accessor
error_budget = ErrorBudget.get_instance()
