"""
Central Runtime State Management for MERID

This module provides a unified runtime state machine that tracks:
- Runtime mode (BOOTING, LIVE_TRADING, OBSERVE_ONLY, DEGRADED, SHUTTING_DOWN, OFFLINE)
- Service readiness flags
- Execution permission
- Critical service health
- Startup/shutdown lifecycle

All health endpoints, execution guards, and lifecycle managers should
read from this single source of truth.
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Set
from utils.logger import get_logger

logger = get_logger(__name__)


class RuntimeMode(Enum):
    """Runtime operational modes"""
    BOOTING = "booting"  # Startup in progress, execution blocked
    LIVE_TRADING = "live_trading"  # All systems operational, execution allowed
    OBSERVE_ONLY = "observe_only"  # Data feeds OK but execution blocked (e.g., reconciliation failure)
    DEGRADED = "degraded"  # Partial service failure, limited execution
    SHUTTING_DOWN = "shutting_down"  # Shutdown initiated, execution blocked
    OFFLINE = "offline"  # System offline


@dataclass
class RuntimeState:
    """Current runtime state"""
    mode: RuntimeMode = RuntimeMode.BOOTING
    readiness_flags: Dict[str, bool] = field(default_factory=dict)
    critical_services: Dict[str, str] = field(default_factory=dict)  # service_name → status
    execution_allowed: bool = False
    startup_completed: bool = False
    startup_timestamp: Optional[float] = None
    degradation_reason: Optional[str] = None

    @property
    def uptime_seconds(self) -> float:
        if self.startup_timestamp is None:
            return 0.0
        return time.time() - self.startup_timestamp

    def is_execution_allowed(self) -> bool:
        """Check if trading execution is permitted"""
        return (
            self.execution_allowed
            and self.mode == RuntimeMode.LIVE_TRADING
            and self.startup_completed
        )

    def is_ready_for_traffic(self) -> bool:
        """Check if system can accept traffic (even if not executing)"""
        return (
            self.startup_completed
            and self.mode not in (RuntimeMode.OFFLINE, RuntimeMode.SHUTTING_DOWN)
        )

    def get_failed_services(self) -> Set[str]:
        """Return set of critical services that failed"""
        return {
            svc for svc, status in self.critical_services.items()
            if status in ("failed", "timeout", "unhealthy")
        }

    def to_dict(self) -> Dict:
        """Export state as dictionary"""
        return {
            "mode": self.mode.value,
            "execution_allowed": self.execution_allowed,
            "startup_completed": self.startup_completed,
            "uptime_seconds": self.uptime_seconds,
            "readiness_flags": self.readiness_flags,
            "critical_services": self.critical_services,
            "degradation_reason": self.degradation_reason,
            "is_execution_allowed": self.is_execution_allowed(),
            "is_ready_for_traffic": self.is_ready_for_traffic(),
            "failed_services": list(self.get_failed_services()),
        }


# Global runtime state singleton
_state: Optional[RuntimeState] = None


def get_runtime_state() -> RuntimeState:
    """Get the global runtime state singleton"""
    global _state
    if _state is None:
        _state = RuntimeState()
        logger.info("RuntimeState initialized in BOOTING mode")
    return _state


def set_runtime_mode(mode: RuntimeMode, reason: Optional[str] = None) -> None:
    """
    Transition to a new runtime mode

    Args:
        mode: Target runtime mode
        reason: Optional reason for transition (required for OBSERVE_ONLY/DEGRADED)
    """
    state = get_runtime_state()
    old_mode = state.mode

    # Log transition
    if mode != old_mode:
        logger.info(
            f"Runtime mode transition: {old_mode.value} → {mode.value}"
            + (f" (reason: {reason})" if reason else "")
        )

    # Update mode
    state.mode = mode

    # Update execution permission based on mode
    if mode in (RuntimeMode.OBSERVE_ONLY, RuntimeMode.DEGRADED):
        state.execution_allowed = False
        state.degradation_reason = reason
    elif mode == RuntimeMode.LIVE_TRADING:
        state.execution_allowed = state.startup_completed
        state.degradation_reason = None
    elif mode in (RuntimeMode.BOOTING, RuntimeMode.SHUTTING_DOWN, RuntimeMode.OFFLINE):
        state.execution_allowed = False
        if mode == RuntimeMode.BOOTING:
            state.degradation_reason = None


def mark_startup_complete() -> None:
    """Mark startup as completed"""
    state = get_runtime_state()
    state.startup_completed = True
    if state.startup_timestamp is None:
        state.startup_timestamp = time.time()
    logger.info(f"Startup marked complete (duration: {state.uptime_seconds:.2f}s)")

    # If no critical failures, transition to LIVE_TRADING
    if not state.get_failed_services() and state.mode == RuntimeMode.BOOTING:
        set_runtime_mode(RuntimeMode.LIVE_TRADING)


def set_readiness_flag(component: str, ready: bool) -> None:
    """
    Set a readiness flag for a component

    Args:
        component: Component name (e.g., "price_feed", "execution", "consensus")
        ready: Whether component is ready
    """
    state = get_runtime_state()
    old_value = state.readiness_flags.get(component)
    if old_value != ready:
        state.readiness_flags[component] = ready
        logger.info(f"Readiness: {component} → {ready}")


def set_service_status(service: str, status: str, critical: bool = False) -> None:
    """
    Update service status

    Args:
        service: Service name
        status: Status string ("running", "failed", "timeout", "unhealthy", etc.)
        critical: Whether this is a critical service (affects execution permission)
    """
    state = get_runtime_state()
    old_status = state.critical_services.get(service)

    if critical:
        state.critical_services[service] = status

        # If critical service failed, downgrade to OBSERVE_ONLY or DEGRADED
        if status in ("failed", "timeout", "unhealthy"):
            logger.error(f"Critical service {service} failed: {status}")
            if state.mode == RuntimeMode.LIVE_TRADING:
                set_runtime_mode(
                    RuntimeMode.OBSERVE_ONLY,
                    reason=f"critical_service_{service}_{status}"
                )

    if old_status != status:
        logger.info(f"Service status: {service} → {status} (critical={critical})")


def check_critical_dependencies(
    required_services: Set[str],
    required_flags: Set[str]
) -> tuple[bool, Set[str]]:
    """
    Check if all critical dependencies are ready

    Args:
        required_services: Set of required service names
        required_flags: Set of required readiness flag names

    Returns:
        Tuple of (all_ready: bool, missing: Set[str])
    """
    state = get_runtime_state()
    missing = set()

    # Check services
    for svc in required_services:
        status = state.critical_services.get(svc)
        if status not in ("running", "healthy"):
            missing.add(f"service:{svc}")

    # Check flags
    for flag in required_flags:
        if not state.readiness_flags.get(flag, False):
            missing.add(f"flag:{flag}")

    return (len(missing) == 0, missing)
