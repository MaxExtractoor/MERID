"""
Health Checker - Comprehensive health monitoring with threshold configuration and alerting.

Performs health checks on system components and services with:
- Configurable health thresholds
- Component-specific check intervals
- Automatic status transitions
- Health alerting integration
- Latency tracking and SLA monitoring

Version: 2.0.0
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Dict, List, Optional, Any, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum

from utils.logger import get_logger
from config.monitoring_config import get_monitoring_config, HealthCheckConfig

logger = get_logger("monitoring.health")


class HealthStatus(Enum):
    """Health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheck:
    """A health check definition with threshold configuration."""
    name: str
    check_fn: Callable[[], Awaitable[bool]]
    
    # Configuration
    timeout_seconds: float = 5.0
    interval_seconds: float = 30.0
    failure_threshold: int = 3
    success_threshold: int = 1
    latency_threshold_ms: Optional[float] = None  # SLA threshold for latency
    
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
    
    # Latency statistics for SLA monitoring
    latency_p50: float = 0.0
    latency_p95: float = 0.0
    latency_p99: float = 0.0
    latency_samples: List[float] = field(default_factory=list)
    max_latency_samples: int = 100
    
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
            "latency_p50": self.latency_p50,
            "latency_p95": self.latency_p95,
            "latency_p99": self.latency_p99,
            "latency_threshold_ms": self.latency_threshold_ms,
            "total_checks": self.total_checks,
            "total_failures": self.total_failures,
            "failure_rate": self.total_failures / self.total_checks * 100 if self.total_checks > 0 else 0,
        }
    
    def _update_latency_stats(self, latency_ms: float) -> None:
        """Update latency statistics with new sample."""
        self.latency_samples.append(latency_ms)
        
        # Keep only recent samples
        if len(self.latency_samples) > self.max_latency_samples:
            self.latency_samples.pop(0)
        
        # Calculate percentiles
        if self.latency_samples:
            sorted_samples = sorted(self.latency_samples)
            n = len(sorted_samples)
            self.latency_p50 = sorted_samples[int(n * 0.5)]
            self.latency_p95 = sorted_samples[int(n * 0.95)]
            self.latency_p99 = sorted_samples[int(n * 0.99)]


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
    Performs health checks on system components with threshold configuration and alerting.
    
    Features:
    - Configurable health checks with component-specific thresholds
    - Failure/success thresholds from configuration
    - Automatic status updates with SLA monitoring
    - Overall health aggregation
    - Health alerting integration
    - Latency threshold monitoring
    """
    
    def __init__(self, config: Optional[HealthCheckConfig] = None):
        self.logger = get_logger("monitoring.health")
        
        # Load configuration
        self._config = config or get_monitoring_config().health
        
        # Health checks
        self._checks: Dict[str, HealthCheck] = {}
        
        # Overall health
        self._overall: OverallHealth = OverallHealth()
        
        # Running state
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
        
        # Callbacks
        self._status_callbacks: List[Callable[[str, HealthStatus], None]] = []
        
        # Alert manager integration
        self._alert_manager = None
        
        # Initialize default checks
        self._init_default_checks()
    
    def set_alert_manager(self, alert_manager) -> None:
        """Set the alert manager for health status alerts."""
        self._alert_manager = alert_manager
        self.logger.info("Alert manager configured for health checker")
    
    def _init_default_checks(self) -> None:
        """Initialize default health checks for all critical components."""
        # Database check
        async def check_database() -> bool:
            try:
                from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
                ledger = get_fills_ledger()
                health = await ledger.health_check()
                return health.get("status") != "error"
            except Exception:
                return False
        
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
                from data.live_price_feed import get_live_price_feed
                feed = get_live_price_feed()
                return feed is not None
            except Exception:
                return False
        
        # Agent swarm check
        async def check_agents() -> bool:
            try:
                from merid.prediction.agent_grid_15m import get_agent_grid
                grid = get_agent_grid()
                return grid is not None and grid._startup_complete
            except Exception:
                return False
        
        # Kalshi client check
        async def check_kalshi_client() -> bool:
            try:
                from merid.event_venues.kalshi.client import get_kalshi_client
                client = get_kalshi_client()
                return client is not None and not client.is_circuit_open
            except Exception:
                return False
        
        # MeridLoop check
        async def check_merid_loop() -> bool:
            try:
                from merid.loop_15m import get_merid_loop_15m
                loop = get_merid_loop_15m()
                status = loop.status()
                return status.get("running", False)
            except Exception:
                return False
        
        # ExecutionGuard check
        async def check_execution_guard() -> bool:
            try:
                from merid.execution_guard import get_execution_guard
                guard = get_execution_guard()
                return not guard.kill_switch_active
            except Exception:
                return False
        
        self.register_check("database", check_database)
        self.register_check("event_bus", check_event_bus)
        self.register_check("price_feed", check_price_feed)
        self.register_check("agent_swarm", check_agents)
        self.register_check("kalshi_client", check_kalshi_client)
        self.register_check("merid_loop", check_merid_loop)
        self.register_check("execution_guard", check_execution_guard)
    
    def register_check(
        self,
        name: str,
        check_fn: Callable[[], Awaitable[bool]],
        timeout_seconds: Optional[float] = None,
        interval_seconds: Optional[float] = None,
        failure_threshold: Optional[int] = None,
        latency_threshold_ms: Optional[float] = None,
    ) -> None:
        """
        Register a health check with configuration-based defaults.
        
        Args:
            name: Unique name for the health check
            check_fn: Async function that returns True if healthy
            timeout_seconds: Override default timeout from config
            interval_seconds: Override default interval from config
            failure_threshold: Override default failure threshold from config
            latency_threshold_ms: Latency threshold for SLA monitoring
        """
        # Use component-specific config if available
        component_config = self._config.component_thresholds.get(name, {})
        
        # Apply defaults from config if not overridden
        timeout = timeout_seconds or component_config.get("timeout", self._config.default_timeout)
        interval = interval_seconds or component_config.get("interval", self._config.default_interval)
        threshold = failure_threshold or component_config.get("failure_threshold", self._config.default_failure_threshold)
        latency_thresh = latency_threshold_ms or component_config.get("latency_threshold_ms")
        
        self._checks[name] = HealthCheck(
            name=name,
            check_fn=check_fn,
            timeout_seconds=timeout,
            interval_seconds=interval,
            failure_threshold=threshold,
        )
        
        # Store latency threshold separately
        if latency_thresh:
            self._checks[name].latency_threshold_ms = latency_thresh
        
        self.logger.info(
            f"Registered health check: {name} (interval={interval}s, timeout={timeout}s, "
            f"failure_threshold={threshold}, latency_threshold={latency_thresh}ms)"
        )
    
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
        """Run a single health check with latency tracking and SLA monitoring."""
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
            check._update_latency_stats(check.latency_ms)
            
            # Check latency threshold (SLA monitoring)
            if check.latency_threshold_ms and check.latency_ms > check.latency_threshold_ms:
                self.logger.warning(
                    f"Health check {check.name} exceeded latency threshold: "
                    f"{check.latency_ms:.2f}ms > {check.latency_threshold_ms}ms"
                )
                # Don't fail the check, but log the SLA violation
            
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
        """Update overall health status with threshold-based degradation detection."""
        healthy = sum(1 for c in self._checks.values() if c.status == HealthStatus.HEALTHY)
        degraded = sum(1 for c in self._checks.values() if c.status == HealthStatus.DEGRADED)
        unhealthy = sum(1 for c in self._checks.values() if c.status == HealthStatus.UNHEALTHY)
        unknown = sum(1 for c in self._checks.values() if c.status == HealthStatus.UNKNOWN)
        
        self._overall.healthy_count = healthy
        self._overall.degraded_count = degraded
        self._overall.unhealthy_count = unhealthy
        self._overall.unknown_count = unknown
        self._overall.last_update = time.time()
        
        # Calculate overall failure rate
        total_checks = sum(c.total_checks for c in self._checks.values())
        total_failures = sum(c.total_failures for c in self._checks.values())
        overall_failure_rate = total_failures / total_checks if total_checks > 0 else 0
        
        # Determine overall status using configuration thresholds
        if unhealthy > 0:
            self._overall.status = HealthStatus.UNHEALTHY
        elif overall_failure_rate >= self._config.unhealthy_failure_rate:
            self._overall.status = HealthStatus.UNHEALTHY
        elif degraded > 0 or overall_failure_rate >= self._config.degraded_failure_rate:
            self._overall.status = HealthStatus.DEGRADED
        elif unknown == len(self._checks):
            self._overall.status = HealthStatus.UNKNOWN
        else:
            self._overall.status = HealthStatus.HEALTHY
    
    def _notify_status_change(self, name: str, status: HealthStatus) -> None:
        """Notify callbacks of status change and send health alerts."""
        self.logger.warning(f"Health status changed: {name} -> {status.value}")
        
        # Send alert if status is unhealthy or degraded
        if status in (HealthStatus.UNHEALTHY, HealthStatus.DEGRADED):
            self._send_health_alert(name, status)
        
        # Notify callbacks
        for callback in self._status_callbacks:
            try:
                callback(name, status)
            except Exception as e:
                self.logger.error(f"Status callback error: {e}")
    
    def _send_health_alert(self, name: str, status: HealthStatus) -> None:
        """Send health status alert via alert manager."""
        if not self._alert_manager:
            return
        
        try:
            # Import here to avoid circular dependency
            from agents.alert_manager import AlertSeverity
            
            severity = AlertSeverity.CRITICAL if status == HealthStatus.UNHEALTHY else AlertSeverity.HIGH
            
            # Get check details
            check = self._checks.get(name)
            if not check:
                return
            
            # Build alert message
            message = f"Health check '{name}' is {status.value}"
            if check.last_error:
                message += f": {check.last_error}"
            if check.latency_threshold_ms and check.latency_ms > check.latency_threshold_ms:
                message += f" (latency {check.latency_ms:.2f}ms exceeds threshold {check.latency_threshold_ms}ms)"
            
            # Send alert (non-blocking)
            asyncio.create_task(
                self._alert_manager.alert(
                    severity=severity,
                    title=f"Health Check {status.value.upper()}: {name}",
                    message=message,
                    source="health_checker",
                    metadata={
                        "check_name": name,
                        "status": status.value,
                        "consecutive_failures": check.consecutive_failures,
                        "latency_ms": check.latency_ms,
                        "failure_rate": check.total_failures / check.total_checks * 100 if check.total_checks > 0 else 0,
                    }
                )
            )
        except Exception as e:
            self.logger.error(f"Failed to send health alert: {e}")
    
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
        """Get a specific health check status."""
        check = self._checks.get(name)
        return check.to_dict() if check else None
    
    def get_all_checks(self) -> Dict[str, Dict[str, Any]]:
        """Get all health check statuses."""
        return {name: check.to_dict() for name, check in self._checks.items()}
    
    def get_overall_health(self) -> Dict[str, Any]:
        """Get overall system health."""
        return self._overall.to_dict()
    
    def get_status(self) -> Dict[str, Any]:
        """Get complete health checker status."""
        return {
            "overall": self.get_overall_health(),
            "checks": self.get_all_checks(),
            "running": self._running,
            "config": {
                "default_interval": self._config.default_interval,
                "default_timeout": self._config.default_timeout,
                "default_failure_threshold": self._config.default_failure_threshold,
                "degraded_failure_rate": self._config.degraded_failure_rate,
                "unhealthy_failure_rate": self._config.unhealthy_failure_rate,
            }
        }
    
    def is_healthy(self) -> bool:
        """Check if system is healthy."""
        return self._overall.status == HealthStatus.HEALTHY
    
    def get_unhealthy_checks(self) -> List[Dict[str, Any]]:
        """Get unhealthy checks."""
        return [c.to_dict() for c in self._checks.values() if c.status == HealthStatus.UNHEALTHY]


# Singleton
_health_checker: Optional[HealthChecker] = None
_health_checker_lock = threading.Lock()


def get_health_checker(config: Optional[HealthCheckConfig] = None) -> HealthChecker:
    """Get or create the Health Checker singleton with optional config."""
    global _health_checker
    if _health_checker is None:
        with _health_checker_lock:
            if _health_checker is None:
                _health_checker = HealthChecker(config)
    return _health_checker


def reload_health_checker() -> HealthChecker:
    """Reload the health checker with new configuration."""
    global _health_checker
    with _health_checker_lock:
        # Stop old instance if running
        if _health_checker and _health_checker._running:
            # This is a synchronous context, so we can't await stop
            # The caller should handle stopping before reloading
            pass
        
        # Create new instance with fresh config
        _health_checker = HealthChecker()
    return _health_checker
