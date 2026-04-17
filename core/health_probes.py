"""
Advanced Health Probes for MERID Services
Implements readiness, liveness, and dependency-specific health checks.
"""
from __future__ import annotations

import asyncio
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.health_probes")


class ProbeType(Enum):
    """Types of health probes."""
    READINESS = "readiness"  # Service ready to accept traffic
    LIVENESS = "liveness"    # Service alive and responsive
    STARTUP = "startup"      # Service startup complete
    DEPENDENCY = "dependency"  # External dependency health


class ProbeStatus(Enum):
    """Health probe status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ProbeResult:
    """Result of a health probe check."""
    probe_name: str
    probe_type: ProbeType
    status: ProbeStatus
    message: str
    timestamp: float
    latency_ms: float
    metadata: Dict[str, Any]


class HealthProbe(ABC):
    """Base class for health probes."""
    
    def __init__(
        self,
        name: str,
        probe_type: ProbeType,
        timeout_seconds: float = 5.0,
        interval_seconds: float = 10.0
    ):
        self.name = name
        self.probe_type = probe_type
        self.timeout_seconds = timeout_seconds
        self.interval_seconds = interval_seconds
        self._last_result: Optional[ProbeResult] = None
        self._consecutive_failures = 0
        self._consecutive_successes = 0
    
    @abstractmethod
    async def check(self) -> ProbeResult:
        """Execute the health check."""
        pass
    
    async def execute(self) -> ProbeResult:
        """Execute probe with timeout and error handling."""
        start_time = time.time()
        
        try:
            result = await asyncio.wait_for(
                self.check(),
                timeout=self.timeout_seconds
            )
            
            # Track consecutive results
            if result.status == ProbeStatus.HEALTHY:
                self._consecutive_successes += 1
                self._consecutive_failures = 0
            else:
                self._consecutive_failures += 1
                self._consecutive_successes = 0
            
            self._last_result = result
            return result
            
        except asyncio.TimeoutError:
            latency_ms = (time.time() - start_time) * 1000
            self._consecutive_failures += 1
            self._consecutive_successes = 0
            
            result = ProbeResult(
                probe_name=self.name,
                probe_type=self.probe_type,
                status=ProbeStatus.UNHEALTHY,
                message=f"Probe timed out after {self.timeout_seconds}s",
                timestamp=time.time(),
                latency_ms=latency_ms,
                metadata={"timeout": True}
            )
            self._last_result = result
            return result
            
        except Exception as exc:
            latency_ms = (time.time() - start_time) * 1000
            self._consecutive_failures += 1
            self._consecutive_successes = 0
            
            logger.error(f"Health probe {self.name} failed: {exc}")
            
            result = ProbeResult(
                probe_name=self.name,
                probe_type=self.probe_type,
                status=ProbeStatus.UNHEALTHY,
                message=f"Probe failed: {str(exc)}",
                timestamp=time.time(),
                latency_ms=latency_ms,
                metadata={"error": str(exc)}
            )
            self._last_result = result
            return result
    
    @property
    def last_result(self) -> Optional[ProbeResult]:
        """Get the last probe result."""
        return self._last_result
    
    @property
    def consecutive_failures(self) -> int:
        """Get consecutive failure count."""
        return self._consecutive_failures
    
    @property
    def consecutive_successes(self) -> int:
        """Get consecutive success count."""
        return self._consecutive_successes


class ReadinessProbe(HealthProbe):
    """Readiness probe - checks if service is ready to accept traffic."""
    
    def __init__(
        self,
        name: str,
        check_func: Callable[[], bool],
        timeout_seconds: float = 5.0,
        interval_seconds: float = 10.0
    ):
        super().__init__(name, ProbeType.READINESS, timeout_seconds, interval_seconds)
        self.check_func = check_func
    
    async def check(self) -> ProbeResult:
        """Execute readiness check."""
        start_time = time.time()
        
        try:
            is_ready = self.check_func()
            latency_ms = (time.time() - start_time) * 1000
            
            return ProbeResult(
                probe_name=self.name,
                probe_type=self.probe_type,
                status=ProbeStatus.HEALTHY if is_ready else ProbeStatus.UNHEALTHY,
                message="Service ready" if is_ready else "Service not ready",
                timestamp=time.time(),
                latency_ms=latency_ms,
                metadata={"ready": is_ready}
            )
        except Exception as exc:
            latency_ms = (time.time() - start_time) * 1000
            return ProbeResult(
                probe_name=self.name,
                probe_type=self.probe_type,
                status=ProbeStatus.UNHEALTHY,
                message=f"Readiness check failed: {exc}",
                timestamp=time.time(),
                latency_ms=latency_ms,
                metadata={"error": str(exc)}
            )


class LivenessProbe(HealthProbe):
    """Liveness probe - checks if service is alive and responsive."""
    
    def __init__(
        self,
        name: str,
        check_func: Callable[[], bool],
        timeout_seconds: float = 5.0,
        interval_seconds: float = 30.0
    ):
        super().__init__(name, ProbeType.LIVENESS, timeout_seconds, interval_seconds)
        self.check_func = check_func
    
    async def check(self) -> ProbeResult:
        """Execute liveness check."""
        start_time = time.time()
        
        try:
            is_alive = self.check_func()
            latency_ms = (time.time() - start_time) * 1000
            
            return ProbeResult(
                probe_name=self.name,
                probe_type=self.probe_type,
                status=ProbeStatus.HEALTHY if is_alive else ProbeStatus.UNHEALTHY,
                message="Service alive" if is_alive else "Service not responding",
                timestamp=time.time(),
                latency_ms=latency_ms,
                metadata={"alive": is_alive}
            )
        except Exception as exc:
            latency_ms = (time.time() - start_time) * 1000
            return ProbeResult(
                probe_name=self.name,
                probe_type=self.probe_type,
                status=ProbeStatus.UNHEALTHY,
                message=f"Liveness check failed: {exc}",
                timestamp=time.time(),
                latency_ms=latency_ms,
                metadata={"error": str(exc)}
            )


class DependencyProbe(HealthProbe):
    """Dependency probe - checks health of external dependencies."""
    
    def __init__(
        self,
        name: str,
        dependency_name: str,
        check_func: Callable[[], Dict[str, Any]],
        timeout_seconds: float = 10.0,
        interval_seconds: float = 30.0
    ):
        super().__init__(name, ProbeType.DEPENDENCY, timeout_seconds, interval_seconds)
        self.dependency_name = dependency_name
        self.check_func = check_func
    
    async def check(self) -> ProbeResult:
        """Execute dependency check."""
        start_time = time.time()
        
        try:
            result = self.check_func()
            latency_ms = (time.time() - start_time) * 1000
            
            is_healthy = result.get("healthy", False)
            
            return ProbeResult(
                probe_name=self.name,
                probe_type=self.probe_type,
                status=ProbeStatus.HEALTHY if is_healthy else ProbeStatus.UNHEALTHY,
                message=result.get("message", "Dependency check complete"),
                timestamp=time.time(),
                latency_ms=latency_ms,
                metadata={
                    "dependency": self.dependency_name,
                    **result
                }
            )
        except Exception as exc:
            latency_ms = (time.time() - start_time) * 1000
            return ProbeResult(
                probe_name=self.name,
                probe_type=self.probe_type,
                status=ProbeStatus.UNHEALTHY,
                message=f"Dependency check failed: {exc}",
                timestamp=time.time(),
                latency_ms=latency_ms,
                metadata={
                    "dependency": self.dependency_name,
                    "error": str(exc)
                }
            )


class ProbeRegistry:
    """Registry for managing health probes."""
    
    def __init__(self):
        self._probes: Dict[str, HealthProbe] = {}
        self._running = False
        self._tasks: List[asyncio.Task] = []
    
    def register(self, probe: HealthProbe) -> None:
        """Register a health probe."""
        if probe.name in self._probes:
            logger.warning(f"Probe {probe.name} already registered, replacing")
        
        self._probes[probe.name] = probe
        logger.info(f"Registered {probe.probe_type.value} probe: {probe.name}")
    
    def unregister(self, probe_name: str) -> None:
        """Unregister a health probe."""
        if probe_name in self._probes:
            del self._probes[probe_name]
            logger.info(f"Unregistered probe: {probe_name}")
    
    def get_probe(self, probe_name: str) -> Optional[HealthProbe]:
        """Get a probe by name."""
        return self._probes.get(probe_name)
    
    def get_probes_by_type(self, probe_type: ProbeType) -> List[HealthProbe]:
        """Get all probes of a specific type."""
        return [p for p in self._probes.values() if p.probe_type == probe_type]
    
    async def check_probe(self, probe_name: str) -> Optional[ProbeResult]:
        """Execute a specific probe."""
        probe = self._probes.get(probe_name)
        if not probe:
            return None
        
        return await probe.execute()
    
    async def check_all(self) -> Dict[str, ProbeResult]:
        """Execute all probes."""
        results = {}
        
        for name, probe in self._probes.items():
            result = await probe.execute()
            results[name] = result
        
        return results
    
    async def check_by_type(self, probe_type: ProbeType) -> Dict[str, ProbeResult]:
        """Execute all probes of a specific type."""
        results = {}
        
        for name, probe in self._probes.items():
            if probe.probe_type == probe_type:
                result = await probe.execute()
                results[name] = result
        
        return results
    
    async def _probe_loop(self, probe: HealthProbe) -> None:
        """Background loop for periodic probe execution."""
        while self._running:
            try:
                await probe.execute()
                await asyncio.sleep(probe.interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Error in probe loop for {probe.name}: {exc}")
                await asyncio.sleep(probe.interval_seconds)
    
    def start_monitoring(self) -> None:
        """Start background monitoring of all probes."""
        if self._running:
            logger.warning("Probe monitoring already running")
            return
        
        self._running = True
        
        for probe in self._probes.values():
            task = asyncio.create_task(self._probe_loop(probe))
            self._tasks.append(task)
        
        logger.info(f"Started monitoring {len(self._probes)} probes")
    
    async def stop_monitoring(self) -> None:
        """Stop background monitoring."""
        self._running = False
        
        for task in self._tasks:
            task.cancel()
        
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        
        logger.info("Stopped probe monitoring")
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of all probe statuses."""
        summary = {
            "total_probes": len(self._probes),
            "by_type": {},
            "by_status": {},
            "probes": {}
        }
        
        for name, probe in self._probes.items():
            result = probe.last_result
            
            if result:
                probe_type = result.probe_type.value
                status = result.status.value
                
                summary["by_type"][probe_type] = summary["by_type"].get(probe_type, 0) + 1
                summary["by_status"][status] = summary["by_status"].get(status, 0) + 1
                
                summary["probes"][name] = {
                    "type": probe_type,
                    "status": status,
                    "message": result.message,
                    "timestamp": result.timestamp,
                    "latency_ms": result.latency_ms,
                    "consecutive_failures": probe.consecutive_failures,
                    "consecutive_successes": probe.consecutive_successes
                }
        
        return summary


# Global probe registry
_probe_registry: Optional[ProbeRegistry] = None
_probe_registry_lock = threading.Lock()


def get_probe_registry() -> ProbeRegistry:
    """Get the global probe registry."""
    global _probe_registry
    if _probe_registry is None:
        with _probe_registry_lock:
            if _probe_registry is None:
                _probe_registry = ProbeRegistry()
    return _probe_registry


def register_readiness_probe(
    name: str,
    check_func: Callable[[], bool],
    timeout_seconds: float = 5.0,
    interval_seconds: float = 10.0
) -> None:
    """Register a readiness probe."""
    probe = ReadinessProbe(name, check_func, timeout_seconds, interval_seconds)
    get_probe_registry().register(probe)


def register_liveness_probe(
    name: str,
    check_func: Callable[[], bool],
    timeout_seconds: float = 5.0,
    interval_seconds: float = 30.0
) -> None:
    """Register a liveness probe."""
    probe = LivenessProbe(name, check_func, timeout_seconds, interval_seconds)
    get_probe_registry().register(probe)


def register_dependency_probe(
    name: str,
    dependency_name: str,
    check_func: Callable[[], Dict[str, Any]],
    timeout_seconds: float = 10.0,
    interval_seconds: float = 30.0
) -> None:
    """Register a dependency probe."""
    probe = DependencyProbe(name, dependency_name, check_func, timeout_seconds, interval_seconds)
    get_probe_registry().register(probe)
