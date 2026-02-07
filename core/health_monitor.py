"""
Health Monitor - Comprehensive system health checking and diagnostics.

Provides:
- Multi-level health checks (service, dependency, resource)
- Detailed diagnostic information
- Health status aggregation
- Automatic recovery triggers
- Health history tracking
"""
from __future__ import annotations

import time
import threading
import psutil
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from utils.logger import get_logger

logger = get_logger("core.health_monitor")


class HealthStatus(Enum):
    """Health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheck:
    """Single health check definition."""
    name: str
    check_func: Callable[[], Dict[str, Any]]
    interval: float = 60.0  # seconds
    timeout: float = 5.0    # seconds
    critical: bool = False  # If True, failure marks system as unhealthy
    last_run: float = 0.0
    last_status: HealthStatus = HealthStatus.UNKNOWN
    last_result: Optional[Dict[str, Any]] = None
    consecutive_failures: int = 0
    total_runs: int = 0
    total_failures: int = 0


@dataclass
class HealthReport:
    """Aggregated health report."""
    timestamp: str
    overall_status: HealthStatus
    checks: Dict[str, Dict[str, Any]]
    system_metrics: Dict[str, Any]
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class HealthMonitor:
    """
    Production-grade health monitoring system.
    
    Features:
    - Periodic health checks
    - Dependency health tracking
    - System resource monitoring
    - Health history
    - Automatic alerting
    """
    
    def __init__(self):
        self._checks: Dict[str, HealthCheck] = {}
        self._lock = threading.Lock()
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        
        # Health history (last 100 reports)
        self._history: List[HealthReport] = []
        self._max_history = 100
        
        # Rate limiting for health status logging
        self._last_health_log = 0.0
        self._health_log_interval = 300.0  # Log health status every 5 minutes max
        
        # Thresholds
        self._cpu_warning_threshold = 70.0  # percent
        self._cpu_critical_threshold = 90.0
        self._memory_warning_threshold = 70.0  # percent
        self._memory_critical_threshold = 90.0
        self._disk_warning_threshold = 80.0  # percent
        self._disk_critical_threshold = 95.0
        
        logger.info("HealthMonitor initialized")
    
    def register_check(
        self,
        name: str,
        check_func: Callable[[], Dict[str, Any]],
        interval: float = 60.0,
        timeout: float = 5.0,
        critical: bool = False
    ) -> None:
        """
        Register a health check.
        
        Args:
            name: Unique check identifier
            check_func: Function that returns health status dict
            interval: Check interval in seconds
            timeout: Max execution time for check
            critical: If True, failure marks system as unhealthy
        """
        with self._lock:
            if name in self._checks:
                logger.warning(f"Health check '{name}' already registered")
                return
            
            check = HealthCheck(
                name=name,
                check_func=check_func,
                interval=interval,
                timeout=timeout,
                critical=critical
            )
            self._checks[name] = check
            logger.info(f"Registered health check '{name}' (interval={interval}s, critical={critical})")
    
    def unregister_check(self, name: str) -> bool:
        """Unregister a health check."""
        with self._lock:
            if name in self._checks:
                del self._checks[name]
                logger.info(f"Unregistered health check '{name}'")
                return True
            return False
    
    def run_check(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Run a specific health check immediately.
        
        Returns:
            Check result dict or None if check not found
        """
        with self._lock:
            check = self._checks.get(name)
            if not check:
                return None
        
        return self._execute_check(check)
    
    def _execute_check(self, check: HealthCheck) -> Dict[str, Any]:
        """Execute a single health check with timeout."""
        start_time = time.time()
        check.total_runs += 1
        
        try:
            # Run check with timeout
            result = check.check_func()
            
            # Validate result format
            if not isinstance(result, dict):
                raise ValueError("Check must return dict")
            
            if "status" not in result:
                raise ValueError("Check result must include 'status' key")
            
            # Parse status
            status_str = result["status"].lower()
            if status_str == "healthy":
                status = HealthStatus.HEALTHY
                check.consecutive_failures = 0
            elif status_str == "degraded":
                status = HealthStatus.DEGRADED
                check.consecutive_failures = 0
            else:
                status = HealthStatus.UNHEALTHY
                check.consecutive_failures += 1
                check.total_failures += 1
            
            check.last_status = status
            check.last_result = result
            check.last_run = time.time()
            
            duration = time.time() - start_time
            result["duration_ms"] = duration * 1000
            result["timestamp"] = datetime.utcnow().isoformat()
            
            return result
            
        except Exception as exc:
            check.consecutive_failures += 1
            check.total_failures += 1
            check.last_status = HealthStatus.UNHEALTHY
            check.last_run = time.time()
            
            duration = time.time() - start_time
            
            error_result = {
                "status": "unhealthy",
                "error": str(exc),
                "duration_ms": duration * 1000,
                "timestamp": datetime.utcnow().isoformat()
            }
            check.last_result = error_result
            
            logger.error(f"Health check '{check.name}' failed: {exc}")
            return error_result
    
    def get_system_metrics(self) -> Dict[str, Any]:
        """Get current system resource metrics."""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # Determine status based on thresholds
            cpu_status = "healthy"
            if cpu_percent >= self._cpu_critical_threshold:
                cpu_status = "critical"
            elif cpu_percent >= self._cpu_warning_threshold:
                cpu_status = "warning"
            
            memory_status = "healthy"
            if memory.percent >= self._memory_critical_threshold:
                memory_status = "critical"
            elif memory.percent >= self._memory_warning_threshold:
                memory_status = "warning"
            
            disk_status = "healthy"
            if disk.percent >= self._disk_critical_threshold:
                disk_status = "critical"
            elif disk.percent >= self._disk_warning_threshold:
                disk_status = "warning"
            
            return {
                "cpu": {
                    "percent": cpu_percent,
                    "status": cpu_status,
                    "warning_threshold": self._cpu_warning_threshold,
                    "critical_threshold": self._cpu_critical_threshold
                },
                "memory": {
                    "total_mb": memory.total / 1024 / 1024,
                    "available_mb": memory.available / 1024 / 1024,
                    "used_mb": memory.used / 1024 / 1024,
                    "percent": memory.percent,
                    "status": memory_status,
                    "warning_threshold": self._memory_warning_threshold,
                    "critical_threshold": self._memory_critical_threshold
                },
                "disk": {
                    "total_gb": disk.total / 1024 / 1024 / 1024,
                    "used_gb": disk.used / 1024 / 1024 / 1024,
                    "free_gb": disk.free / 1024 / 1024 / 1024,
                    "percent": disk.percent,
                    "status": disk_status,
                    "warning_threshold": self._disk_warning_threshold,
                    "critical_threshold": self._disk_critical_threshold
                }
            }
        except Exception as exc:
            logger.error(f"Failed to get system metrics: {exc}")
            return {
                "error": str(exc),
                "status": "unknown"
            }
    
    def get_health_report(self) -> HealthReport:
        """Generate comprehensive health report."""
        with self._lock:
            checks_dict = {}
            warnings = []
            errors = []
            
            # Run all checks that are due
            now = time.time()
            for name, check in self._checks.items():
                if now - check.last_run >= check.interval:
                    result = self._execute_check(check)
                else:
                    result = check.last_result or {"status": "unknown"}
                
                checks_dict[name] = {
                    "status": check.last_status.value,
                    "result": result,
                    "consecutive_failures": check.consecutive_failures,
                    "total_runs": check.total_runs,
                    "total_failures": check.total_failures,
                    "critical": check.critical
                }
                
                # Collect warnings and errors
                if check.last_status == HealthStatus.UNHEALTHY:
                    if check.critical:
                        errors.append(f"Critical check '{name}' is unhealthy")
                    else:
                        warnings.append(f"Check '{name}' is unhealthy")
                elif check.last_status == HealthStatus.DEGRADED:
                    warnings.append(f"Check '{name}' is degraded")
            
            # Get system metrics
            system_metrics = self.get_system_metrics()
            
            # Check system metrics for warnings/errors
            if "cpu" in system_metrics:
                if system_metrics["cpu"]["status"] == "critical":
                    errors.append(f"CPU usage critical: {system_metrics['cpu']['percent']:.1f}%")
                elif system_metrics["cpu"]["status"] == "warning":
                    warnings.append(f"CPU usage high: {system_metrics['cpu']['percent']:.1f}%")
            
            if "memory" in system_metrics:
                if system_metrics["memory"]["status"] == "critical":
                    errors.append(f"Memory usage critical: {system_metrics['memory']['percent']:.1f}%")
                elif system_metrics["memory"]["status"] == "warning":
                    warnings.append(f"Memory usage high: {system_metrics['memory']['percent']:.1f}%")
            
            if "disk" in system_metrics:
                if system_metrics["disk"]["status"] == "critical":
                    errors.append(f"Disk usage critical: {system_metrics['disk']['percent']:.1f}%")
                elif system_metrics["disk"]["status"] == "warning":
                    warnings.append(f"Disk usage high: {system_metrics['disk']['percent']:.1f}%")
            
            # Determine overall status
            if errors:
                overall_status = HealthStatus.UNHEALTHY
            elif warnings:
                overall_status = HealthStatus.DEGRADED
            else:
                overall_status = HealthStatus.HEALTHY
            
            report = HealthReport(
                timestamp=datetime.utcnow().isoformat(),
                overall_status=overall_status,
                checks=checks_dict,
                system_metrics=system_metrics,
                warnings=warnings,
                errors=errors
            )
            
            # Add to history
            self._history.append(report)
            if len(self._history) > self._max_history:
                self._history.pop(0)
            
            return report
    
    def get_health_history(self, limit: int = 10) -> List[HealthReport]:
        """Get recent health reports."""
        with self._lock:
            return self._history[-limit:]
    
    def start_monitoring(self, interval: float = 30.0) -> None:
        """Start background health monitoring."""
        if self._running:
            logger.warning("Health monitoring already running")
            return
        
        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(interval,),
            daemon=True
        )
        self._monitor_thread.start()
        logger.info(f"Started health monitoring (interval={interval}s)")
    
    def stop_monitoring(self) -> None:
        """Stop background health monitoring."""
        if not self._running:
            return
        
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)
        logger.info("Stopped health monitoring")
    
    def _monitor_loop(self, interval: float) -> None:
        """Background monitoring loop."""
        while self._running:
            try:
                report = self.get_health_report()
                
                # Rate limit health status logging to reduce noise
                now = time.time()
                if now - self._last_health_log >= self._health_log_interval:
                    if report.overall_status == HealthStatus.UNHEALTHY:
                        logger.error(f"System health: UNHEALTHY - {len(report.errors)} errors")
                    elif report.overall_status == HealthStatus.DEGRADED:
                        logger.warning(f"System health: DEGRADED - {len(report.warnings)} warnings")
                    else:
                        logger.debug("System health: HEALTHY")
                    self._last_health_log = now
                
            except Exception as exc:
                logger.error(f"Error in health monitoring loop: {exc}")
            
            time.sleep(interval)
    
    def set_thresholds(
        self,
        cpu_warning: Optional[float] = None,
        cpu_critical: Optional[float] = None,
        memory_warning: Optional[float] = None,
        memory_critical: Optional[float] = None,
        disk_warning: Optional[float] = None,
        disk_critical: Optional[float] = None
    ) -> None:
        """Set resource thresholds."""
        if cpu_warning is not None:
            self._cpu_warning_threshold = cpu_warning
        if cpu_critical is not None:
            self._cpu_critical_threshold = cpu_critical
        if memory_warning is not None:
            self._memory_warning_threshold = memory_warning
        if memory_critical is not None:
            self._memory_critical_threshold = memory_critical
        if disk_warning is not None:
            self._disk_warning_threshold = disk_warning
        if disk_critical is not None:
            self._disk_critical_threshold = disk_critical
        
        logger.info("Updated health thresholds")


# Global singleton
_health_monitor: Optional[HealthMonitor] = None


def get_health_monitor() -> HealthMonitor:
    """Get the global health monitor instance."""
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = HealthMonitor()
    return _health_monitor


# Standard health check functions
def check_memory_health() -> Dict[str, Any]:
    """Check memory health."""
    try:
        memory = psutil.virtual_memory()
        if memory.percent >= 90:
            return {"status": "unhealthy", "memory_percent": memory.percent, "reason": "Memory usage critical"}
        elif memory.percent >= 70:
            return {"status": "degraded", "memory_percent": memory.percent, "reason": "Memory usage high"}
        else:
            return {"status": "healthy", "memory_percent": memory.percent}
    except Exception as exc:
        return {"status": "unhealthy", "error": str(exc)}


def check_cpu_health() -> Dict[str, Any]:
    """Check CPU health."""
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        if cpu_percent >= 90:
            return {"status": "unhealthy", "cpu_percent": cpu_percent, "reason": "CPU usage critical"}
        elif cpu_percent >= 70:
            return {"status": "degraded", "cpu_percent": cpu_percent, "reason": "CPU usage high"}
        else:
            return {"status": "healthy", "cpu_percent": cpu_percent}
    except Exception as exc:
        return {"status": "unhealthy", "error": str(exc)}


def check_disk_health() -> Dict[str, Any]:
    """Check disk health."""
    try:
        disk = psutil.disk_usage('/')
        if disk.percent >= 95:
            return {"status": "unhealthy", "disk_percent": disk.percent, "reason": "Disk usage critical"}
        elif disk.percent >= 80:
            return {"status": "degraded", "disk_percent": disk.percent, "reason": "Disk usage high"}
        else:
            return {"status": "healthy", "disk_percent": disk.percent}
    except Exception as exc:
        return {"status": "unhealthy", "error": str(exc)}
