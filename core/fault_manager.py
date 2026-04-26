"""Fault Manager - centralized health tracking and shutdown decisions.

Implements graceful degradation patterns where venue-specific failures
degrade that venue rather than triggering global process shutdown.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Dict, List, Optional, Any

from utils.logger import get_logger

logger = get_logger("core.fault_manager")


class HealthState(IntEnum):
    """Health states for venues and core system."""
    OK = 0
    DEGRADED = 1
    OFFLINE = 2
    CRITICAL = 3


class CircuitState(IntEnum):
    """Circuit breaker states."""
    CLOSED = 0      # Normal operation
    HALF_OPEN = 1   # Testing if recovered
    OPEN = 2        # Failing, not attempting


@dataclass
class VenueHealth:
    """Health record for a single venue."""
    state: HealthState = HealthState.OK
    circuit_state: CircuitState = CircuitState.CLOSED
    last_failure: Optional[float] = None
    failure_count: int = 0
    recovery_attempts: int = 0
    last_recovery_attempt: Optional[float] = None
    reasons: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass  
class CoreHealth:
    """Health record for core system."""
    state: HealthState = HealthState.OK
    last_critical_event: Optional[float] = None
    critical_event_count: int = 0
    venues_offline: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)


class FaultManager:
    """Centralized fault management for graceful degradation.
    
    Design: venue-specific failures degrade that venue, not the whole process.
    Global shutdown only occurs for multi-signal, system-wide critical failures.
    """
    
    def __init__(self):
        self._venue_health: Dict[str, VenueHealth] = {}
        self._core = CoreHealth()
        self._last_shutdown_check: float = 0.0
        
        # Configuration from environment
        self._allow_degraded_kalshi = os.getenv("MERID_ALLOW_DEGRADED_KALSHI", "1") == "1"
        self._fatal_shutdown_after_n = int(os.getenv("MERID_FATAL_SHUTDOWN_AFTER_N_FAILS", "0"))
        self._shutdown_on_asgi_fatal = os.getenv("MERID_SHUTDOWN_ON_ASGI_FATAL", "0") == "1"
        
        # Circuit breaker settings for Kalshi
        self._cb_failure_threshold = int(os.getenv("MERID_KALSHI_CB_FAILURE_THRESHOLD", "5"))
        self._cb_recovery_timeout = float(os.getenv("MERID_KALSHI_CB_RECOVERY_TIMEOUT_SEC", "30.0"))
        self._cb_max_half_open_trials = int(os.getenv("MERID_KALSHI_CB_MAX_HALF_OPEN_TRIALS", "3"))
        
        logger.info(
            "[FAULT-MANAGER] Initialized: allow_degraded_kalshi=%s, shutdown_on_fatal=%s, "
            "cb_threshold=%d, cb_recovery=%.1fs",
            self._allow_degraded_kalshi,
            self._shutdown_on_asgi_fatal,
            self._cb_failure_threshold,
            self._cb_recovery_timeout,
        )
    
    def _get_venue(self, venue: str) -> VenueHealth:
        """Get or create venue health record."""
        if venue not in self._venue_health:
            self._venue_health[venue] = VenueHealth()
        return self._venue_health[venue]
    
    def mark_venue_degraded(self, venue: str, reason: str, metrics: Optional[Dict] = None) -> None:
        """Mark a venue as degraded but still attempting recovery."""
        v = self._get_venue(venue)
        old_state = v.state
        v.state = HealthState.DEGRADED
        v.last_failure = time.monotonic()
        v.failure_count += 1
        v.reasons.append(f"{time.monotonic():.0f}: {reason}")
        if metrics:
            v.metrics.update(metrics)
        
        # Keep only last 10 reasons
        v.reasons = v.reasons[-10:]
        
        logger.warning(
            "[VENUE-DEGRADED] venue=%s reason=%s failures=%d",
            venue, reason, v.failure_count,
            extra={"metrics": metrics} if metrics else {}
        )
        
        # Update core health - degraded venues don't immediately affect core
        self._update_core_health()
    
    def mark_venue_offline(self, venue: str, reason: str, circuit_open: bool = False) -> None:
        """Mark a venue as offline (circuit open or persistent failure)."""
        v = self._get_venue(venue)
        v.state = HealthState.OFFLINE
        if circuit_open:
            v.circuit_state = CircuitState.OPEN
        v.last_failure = time.monotonic()
        v.reasons.append(f"{time.monotonic():.0f}: {reason}")
        v.reasons = v.reasons[-10:]
        
        logger.error(
            "[VENUE-OFFLINE] venue=%s reason=%s circuit=%s",
            venue, reason, "open" if circuit_open else "closed"
        )
        
        self._update_core_health()
    
    def mark_venue_recovered(self, venue: str, reason: str = "recovered") -> None:
        """Mark a venue as recovered and operational."""
        v = self._get_venue(venue)
        old_state = v.state
        v.state = HealthState.OK
        v.circuit_state = CircuitState.CLOSED
        v.failure_count = 0
        v.recovery_attempts = 0
        v.reasons.append(f"{time.monotonic():.0f}: {reason}")
        v.reasons = v.reasons[-10:]
        
        logger.info(
            "[VENUE-RECOVERED] venue=%s previous_state=%s",
            venue, old_state.name
        )
        
        self._update_core_health()
    
    def mark_recovery_attempt(self, venue: str, attempt_number: int, half_open: bool = False) -> None:
        """Log a recovery attempt for a venue."""
        v = self._get_venue(venue)
        v.recovery_attempts = attempt_number
        v.last_recovery_attempt = time.monotonic()
        if half_open:
            v.circuit_state = CircuitState.HALF_OPEN
        
        logger.info(
            "[VENUE-RECOVERY-ATTEMPT] venue=%s attempt=%d half_open=%s",
            venue, attempt_number, half_open
        )
    
    def mark_core_degraded(self, reason: str) -> None:
        """Mark core system as degraded but operational."""
        self._core.state = HealthState.DEGRADED
        self._core.reasons.append(f"{time.monotonic():.0f}: {reason}")
        self._core.reasons = self._core.reasons[-10:]
        
        logger.warning("[CORE-DEGRADED] reason=%s", reason)
    
    def mark_core_critical(self, reason: str) -> None:
        """Mark core system as critical - may trigger shutdown."""
        self._core.state = HealthState.CRITICAL
        self._core.last_critical_event = time.monotonic()
        self._core.critical_event_count += 1
        self._core.reasons.append(f"{time.monotonic():.0f}: {reason}")
        self._core.reasons = self._core.reasons[-10:]
        
        logger.critical(
            "[CORE-CRITICAL] reason=%s critical_count=%d",
            reason, self._core.critical_event_count
        )
    
    def _update_core_health(self) -> None:
        """Update core health based on venue states."""
        offline_venues = [
            v for v, h in self._venue_health.items()
            if h.state in (HealthState.OFFLINE, HealthState.CRITICAL)
        ]
        self._core.venues_offline = offline_venues
        
        # Core is DEGRADED if any venue is offline
        if offline_venues and self._core.state == HealthState.OK:
            self._core.state = HealthState.DEGRADED
            logger.warning(
                "[CORE-DEGRADED] due to offline venues: %s",
                offline_venues
            )
        
        # Core returns to OK if all venues recovered
        if not offline_venues and self._core.state == HealthState.DEGRADED:
            self._core.state = HealthState.OK
            logger.info("[CORE-RECOVERED] all venues operational")
    
    def should_initiate_shutdown(self, lag_ms: float = 0.0, lag_p95: float = 0.0) -> bool:
        """Determine if global shutdown should be initiated.
        
        INFINITE ERROR BUDGET: Always returns False for 24/7 operation.
        System will log conditions but never shutdown regardless of lag,
        critical events, or venue failures.
        """
        # Multi-signal shutdown conditions (for logging only)
        conditions_met = []
        
        # Condition 1: Critical event occurred
        if self._core.critical_event_count > 0:
            conditions_met.append("critical_event")
        
        # Condition 2: Extreme lag
        if lag_ms > 5000 or lag_p95 > 5000:
            conditions_met.append("extreme_lag")
        
        # Condition 3: Multiple venues offline
        if len(self._core.venues_offline) >= 2:
            conditions_met.append("multiple_venues_offline")
        
        # Condition 4: Core is CRITICAL (not just DEGRADED)
        if self._core.state == HealthState.CRITICAL:
            conditions_met.append("core_critical")
        
        # INFINITE ERROR BUDGET: Never shutdown, just log the conditions
        if conditions_met:
            logger.critical(
                "[SHUTDOWN-DECISION] INFINITE ERROR BUDGET: conditions=%s venues=%s lag_ms=%.1f — "
                "STAYING UP (no shutdown)",
                conditions_met, self._core.venues_offline, lag_ms
            )
        
        # Always return False - system runs 24/7 regardless of conditions
        return False
    
    def get_venue_circuit_state(self, venue: str) -> CircuitState:
        """Get circuit breaker state for a venue."""
        return self._get_venue(venue).circuit_state
    
    def can_attempt_reconnect(self, venue: str) -> bool:
        """Check if venue can attempt reconnection based on circuit state."""
        v = self._get_venue(venue)
        
        if v.circuit_state == CircuitState.CLOSED:
            return True
        
        if v.circuit_state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if v.last_failure is not None:
                elapsed = time.monotonic() - v.last_failure
                if elapsed >= self._cb_recovery_timeout:
                    # Transition to half-open
                    v.circuit_state = CircuitState.HALF_OPEN
                    v.recovery_attempts = 0
                    logger.info(
                        "[CIRCUIT-STATE] venue=%s OPEN -> HALF_OPEN (recovery timeout elapsed)",
                        venue
                    )
                    return True
            return False
        
        if v.circuit_state == CircuitState.HALF_OPEN:
            # Allow limited attempts in half-open
            if v.recovery_attempts < self._cb_max_half_open_trials:
                return True
            # Too many half-open failures - go back to open
            v.circuit_state = CircuitState.OPEN
            v.last_failure = time.monotonic()
            logger.warning(
                "[CIRCUIT-STATE] venue=%s HALF_OPEN -> OPEN (max trials exceeded)",
                venue
            )
            return False
        
        return True
    
    def record_circuit_success(self, venue: str) -> None:
        """Record successful operation, reset circuit breaker."""
        v = self._get_venue(venue)
        if v.circuit_state != CircuitState.CLOSED:
            v.circuit_state = CircuitState.CLOSED
            v.failure_count = 0
            v.recovery_attempts = 0
            logger.info("[CIRCUIT-STATE] venue=%s -> CLOSED (success)", venue)
    
    def record_circuit_failure(self, venue: str) -> None:
        """Record failure, potentially open circuit."""
        v = self._get_venue(venue)
        v.failure_count += 1
        
        if v.circuit_state == CircuitState.HALF_OPEN:
            # Fail in half-open -> go back to open
            v.circuit_state = CircuitState.OPEN
            v.last_failure = time.monotonic()
            logger.warning(
                "[CIRCUIT-STATE] venue=%s HALF_OPEN -> OPEN (failure)", venue
            )
        elif v.failure_count >= self._cb_failure_threshold:
            # Exceeded threshold -> open circuit
            v.circuit_state = CircuitState.OPEN
            v.last_failure = time.monotonic()
            logger.error(
                "[CIRCUIT-STATE] venue=%s -> OPEN (threshold=%d exceeded)",
                venue, self._cb_failure_threshold
            )
            # Mark venue offline
            self.mark_venue_offline(venue, "circuit_threshold_exceeded", circuit_open=True)
    
    def get_health_summary(self) -> Dict[str, Any]:
        """Get full health summary for logging/metrics."""
        return {
            "core": {
                "state": self._core.state.name,
                "critical_count": self._core.critical_event_count,
                "venues_offline": self._core.venues_offline,
                "reasons": self._core.reasons[-5:],
            },
            "venues": {
                v: {
                    "state": h.state.name,
                    "circuit": h.circuit_state.name,
                    "failures": h.failure_count,
                    "recoveries": h.recovery_attempts,
                }
                for v, h in self._venue_health.items()
            },
            "config": {
                "allow_degraded_kalshi": self._allow_degraded_kalshi,
                "shutdown_on_fatal": self._shutdown_on_asgi_fatal,
                "cb_threshold": self._cb_failure_threshold,
                "cb_recovery_timeout": self._cb_recovery_timeout,
            }
        }


# Global singleton instance
_fault_manager: Optional[FaultManager] = None


def get_fault_manager() -> FaultManager:
    """Get the global fault manager instance."""
    global _fault_manager
    if _fault_manager is None:
        _fault_manager = FaultManager()
    return _fault_manager


def reset_fault_manager() -> None:
    """Reset the global fault manager (for testing)."""
    global _fault_manager
    _fault_manager = None
