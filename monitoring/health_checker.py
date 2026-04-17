"""
Health Checker.

Performs health checks on system components and services.

Version: 1.0.0
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Dict, List, Optional, Any, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum

from utils.logger import get_logger

logger = get_logger("monitoring.health")


class HealthStatus(Enum):
    """Health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheck:
    """A health check definition."""
    name: str
    check_fn: Callable[[], Awaitable[bool]]
    
    # Configuration
    timeout_seconds: float = 5.0
    interval_seconds: float = 30.0
    failure_threshold: int = 3
    success_threshold: int = 1
    
    # State
    status: HealthStatus = HealthStatus.UNKNOWN
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_check: Optional[float] = None
    last_success: Optional[float] = None
    last_failure: Optional[float] = None
    last_error: str = ""
    latency_ms: float = 0.0
    
    # Statistics
    total_checks: int = 0
    total_failures: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "last_check": self.last_check,
            "last_success": self.last_success,
            "last_failure": self.last_failure,
            "last_error": self.last_error,
            "latency_ms": self.latency_ms,
            "total_checks": self.total_checks,
            "total_failures": self.total_failures,
            "failure_rate": self.total_failures / self.total_checks * 100 if self.total_checks > 0 else 0,
        }


@dataclass
class OverallHealth:
    """Overall system health."""
    status: HealthStatus = HealthStatus.UNKNOWN
    healthy_count: int = 0
    degraded_count: int = 0
    unhealthy_count: int = 0
    unknown_count: int = 0
    last_update: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "healthy_count": self.healthy_count,
            "degraded_count": self.degraded_count,
            "unhealthy_count": self.unhealthy_count,
            "unknown_count": self.unknown_count,
            "last_update": self.last_update,
        }


class HealthChecker:
    """
    Performs health checks on system components.
    
    Features:
    - Configurable health checks
    - Failure/success thresholds
    - Automatic status updates
    - Overall health aggregation
    """
    
    def __init__(self):
        self.logger = get_logger("monitoring.health")
        
        # Health checks
        self._checks: Dict[str, HealthCheck] = {}
        
        # Overall health
        self._overall: OverallHealth = OverallHealth()
        
        # Running state
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
        
        # Callbacks
        self._status_callbacks: List[Callable[[str, HealthStatus], None]] = []
        
        # Initialize default checks
        self._init_default_checks()
    
    def _init_default_checks(self) -> None:
        """Initialize default health checks."""
        # Database check (simulated)
        async def check_database() -> bool:
            # In production, actually check database connection
            return True
        
        # Event bus check
        async def check_event_bus() -> bool:
            try:
                from core.event_bus import get_event_bus
                bus = get_event_bus()
                return bus is not None
            except Exception:
                return False
        
        # Price feed check
        async def check_price_feed() -> bool:
            try:
                from data.price_feed import get_price_feed
                feed = get_price_feed()
                return feed is not None
            except Exception:
                return False
        
        # Agent swarm check
        async def check_agents() -> bool:
            try:
                from swarm.swarm_coordinator import get_swarm_coordinator
                coordinator = get_swarm_coordinator()
                return coordinator is not None
            except Exception:
                return False
        
        self.register_check("database", check_database)
        self.register_check("event_bus", check_event_bus)
        self.register_check("price_feed", check_price_feed)
        self.register_check("agent_swarm", check_agents)
    
    def register_check(
        self,
        name: str,
        check_fn: Callable[[], Awaitable[bool]],
        timeout_seconds: float = 5.0,
        interval_seconds: float = 30.0,
        failure_threshold: int = 3,
    ) -> None:
        """Register a health check."""
        self._checks[name] = HealthCheck(
            name=name,
            check_fn=check_fn,
            timeout_seconds=timeout_seconds,
            interval_seconds=interval_seconds,
            failure_threshold=failure_threshold,
        )
        self.logger.info(f"Registered health check: {name}")
    
    def unregister_check(self, name: str) -> bool:
        """Unregister a health check."""
        if name in self._checks:
            del self._checks[name]
            return True
        return False
    
    async def start(self) -> None:
        """Start health checking."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._check_loop())
        self.logger.info("Health checker started")
    
    async def stop(self) -> None:
        """Stop health checking."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.logger.info("Health checker stopped")
    
    async def _check_loop(self) -> None:
        """Main health check loop."""
        while self._running:
            try:
                # Run all checks
                for check in self._checks.values():
                    await self._run_check(check)
                
                # Update overall health
                self._update_overall_health()
                
                # Wait for next cycle
                await asyncio.sleep(10)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Health check loop error: {e}")
                await asyncio.sleep(30)
    
    async def _run_check(self, check: HealthCheck) -> None:
        """Run a single health check."""
        # Check if it's time to run
        if check.last_check and time.time() - check.last_check < check.interval_seconds:
            return
        
        start_time = time.time()
        check.last_check = start_time
        check.total_checks += 1
        
        try:
            # Run with timeout
            result = await asyncio.wait_for(
                check.check_fn(),
                timeout=check.timeout_seconds
            )
            
            check.latency_ms = (time.time() - start_time) * 1000
            
            if result:
                check.consecutive_successes += 1
                check.consecutive_failures = 0
                check.last_success = time.time()
                check.last_error = ""
                
                if check.consecutive_successes >= check.success_threshold:
                    old_status = check.status
                    check.status = HealthStatus.HEALTHY
                    
                    if old_status != HealthStatus.HEALTHY:
                        self._notify_status_change(check.name, check.status)
            else:
                self._record_failure(check, "Check returned false")
                
        except asyncio.TimeoutError:
            self._record_failure(check, "Check timed out")
        except Exception as e:
            self._record_failure(check, str(e))
    
    def _record_failure(self, check: HealthCheck, error: str) -> None:
        """Record a check failure."""
        check.consecutive_failures += 1
        check.consecutive_successes = 0
        check.last_failure = time.time()
        check.last_error = error
        check.total_failures += 1
        
        old_status = check.status
        
        if check.consecutive_failures >= check.failure_threshold:
            check.status = HealthStatus.UNHEALTHY
        elif check.consecutive_failures > 0:
            check.status = HealthStatus.DEGRADED
        
        if old_status != check.status:
            self._notify_status_change(check.name, check.status)
    
    def _update_overall_health(self) -> None:
        """Update overall health status."""
        healthy = sum(1 for c in self._checks.values() if c.status == HealthStatus.HEALTHY)
        degraded = sum(1 for c in self._checks.values() if c.status == HealthStatus.DEGRADED)
        unhealthy = sum(1 for c in self._checks.values() if c.status == HealthStatus.UNHEALTHY)
        unknown = sum(1 for c in self._checks.values() if c.status == HealthStatus.UNKNOWN)
        
        self._overall.healthy_count = healthy
        self._overall.degraded_count = degraded
        self._overall.unhealthy_count = unhealthy
        self._overall.unknown_count = unknown
        self._overall.last_update = time.time()
        
        # Determine overall status
        if unhealthy > 0:
            self._overall.status = HealthStatus.UNHEALTHY
        elif degraded > 0:
            self._overall.status = HealthStatus.DEGRADED
        elif unknown == len(self._checks):
            self._overall.status = HealthStatus.UNKNOWN
        else:
            self._overall.status = HealthStatus.HEALTHY
    
    def _notify_status_change(self, name: str, status: HealthStatus) -> None:
        """Notify callbacks of status change."""
        self.logger.warning(f"Health status changed: {name} -> {status.value}")
        
        for callback in self._status_callbacks:
            try:
                callback(name, status)
            except Exception as e:
                self.logger.error(f"Status callback error: {e}")
    
    def on_status_change(self, callback: Callable[[str, HealthStatus], None]) -> None:
        """Register callback for status changes."""
        self._status_callbacks.append(callback)
    
    async def run_check_now(self, name: str) -> Dict[str, Any]:
        """Run a specific check immediately."""
        check = self._checks.get(name)
        if not check:
            return {"error": "Check not found"}
        
        # Force run by resetting last_check
        check.last_check = None
        await self._run_check(check)
        
        return check.to_dict()
    
    def get_check(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a specific check status."""
        check = self._checks.get(name)
        if check:
            return check.to_dict()
        return None
    
    def get_all_checks(self) -> Dict[str, Dict[str, Any]]:
        """Get all check statuses."""
        return {name: c.to_dict() for name, c in self._checks.items()}
    
    def get_overall_health(self) -> Dict[str, Any]:
        """Get overall health status."""
        return self._overall.to_dict()
    
    def is_healthy(self) -> bool:
        """Check if system is healthy."""
        return self._overall.status == HealthStatus.HEALTHY
    
    def get_unhealthy_checks(self) -> List[Dict[str, Any]]:
        """Get unhealthy checks."""
        return [c.to_dict() for c in self._checks.values() if c.status == HealthStatus.UNHEALTHY]
    
    def get_status(self) -> Dict[str, Any]:
        """Get health checker status."""
        return {
            "running": self._running,
            "overall": self._overall.to_dict(),
            "checks": self.get_all_checks(),
            "unhealthy": self.get_unhealthy_checks(),
        }


# Singleton
_health_checker: Optional[HealthChecker] = None
_health_checker_lock = threading.Lock()


def get_health_checker() -> HealthChecker:
    """Get or create the Health Checker singleton."""
    global _health_checker
    if _health_checker is None:
        with _health_checker_lock:
            if _health_checker is None:
                _health_checker = HealthChecker()
    return _health_checker
