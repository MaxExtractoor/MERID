"""
Hardening - Adversarial hardening components per MASTER_SPEC v1.0

This module exports the hardening layer components:
- Watchdog: Self-healing automation monitoring
- CircuitBreaker: Fault tolerance and cascade prevention
- Lockdown: Emergency halt and governance override

Reference: MASTER_SPEC.md Section 8 (Adversarial Hardening)
"""

from hardening.watchdog import watchdog
from hardening.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerRegistry,
    CircuitState,
    CircuitOpenError,
    CircuitStats,
    get_circuit_registry,
    get_circuit,
)
from hardening.lockdown import (
    LockdownManager,
    LockdownLevel,
    LockdownReason,
    get_lockdown_manager,
    enable_lockdown,
    disable_lockdown,
    is_lockdown_active,
    check_operation_allowed,
)

__all__ = [
    "watchdog",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerRegistry",
    "CircuitState",
    "CircuitOpenError",
    "CircuitStats",
    "get_circuit_registry",
    "get_circuit",
    "LockdownManager",
    "LockdownLevel",
    "LockdownReason",
    "get_lockdown_manager",
    "enable_lockdown",
    "disable_lockdown",
    "is_lockdown_active",
    "check_operation_allowed",
]
