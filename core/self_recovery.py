"""
Self-Recovery System for MERID Services
Automatic failure detection and recovery mechanisms.
"""
from __future__ import annotations

import asyncio
import multiprocessing
import signal
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from core.health_probes import ProbeStatus, get_probe_registry
from utils.logger import get_logger

logger = get_logger("core.self_recovery")


class RecoveryAction(Enum):
    """Types of recovery actions."""
    RESTART = "restart"
    DRAIN_TRAFFIC = "drain_traffic"
    FAILOVER = "failover"
    EVICT_NODE = "evict_node"
    CIRCUIT_BREAK = "circuit_break"
    SCALE_UP = "scale_up"
    SCALE_DOWN = "scale_down"


class ServiceState(Enum):
    """Service state."""
    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    DRAINING = "draining"
    STOPPED = "stopped"


@dataclass
class RecoveryPolicy:
    """Policy for automatic recovery."""
    service_name: str
    failure_threshold: int = 3
    success_threshold: int = 2
    restart_delay_seconds: float = 5.0
    max_restarts_per_hour: int = 5
    drain_timeout_seconds: float = 30.0
    enable_auto_restart: bool = True
    enable_auto_failover: bool = False
    enable_auto_eviction: bool = False


@dataclass
class RecoveryEvent:
    """Recovery event record."""
    timestamp: float
    service_name: str
    action: RecoveryAction
    reason: str
    success: bool
    metadata: Dict[str, Any]


class ServiceRecoveryManager:
    """Manages automatic recovery for a service."""
    
    def __init__(self, policy: RecoveryPolicy):
        self.policy = policy
        self.state = ServiceState.STARTING
        self._restart_count = 0
        self._restart_timestamps: List[float] = []
        self._recovery_events: List[RecoveryEvent] = []
        self._process: Optional[multiprocessing.Process] = None
        self._draining = False
    
    def record_health_check(self, is_healthy: bool) -> Optional[RecoveryAction]:
        """Record health check result and determine if recovery action needed."""
        probe_registry = get_probe_registry()
        
        # Get all probes for this service
        all_results = []
        for probe in probe_registry._probes.values():
            if probe.last_result:
                all_results.append(probe.last_result)
        
        if not all_results:
            return None
        
        # Count failures
        unhealthy_count = sum(1 for r in all_results if r.status == ProbeStatus.UNHEALTHY)
        total_count = len(all_results)
        
        # Determine state
        if unhealthy_count == 0:
            self.state = ServiceState.HEALTHY
        elif unhealthy_count < total_count / 2:
            self.state = ServiceState.DEGRADED
        else:
            self.state = ServiceState.UNHEALTHY
        
        # Check if recovery needed
        if self.state == ServiceState.UNHEALTHY:
            if self.policy.enable_auto_restart:
                if self._can_restart():
                    return RecoveryAction.RESTART
                else:
                    logger.error(f"Service {self.policy.service_name} exceeded restart limit")
                    if self.policy.enable_auto_eviction:
                        return RecoveryAction.EVICT_NODE
        
        return None
    
    def _can_restart(self) -> bool:
        """Check if service can be restarted based on policy."""
        now = time.time()
        
        # Remove old restart timestamps (older than 1 hour)
        self._restart_timestamps = [
            ts for ts in self._restart_timestamps
            if now - ts < 3600
        ]
        
        return len(self._restart_timestamps) < self.policy.max_restarts_per_hour
    
    async def execute_recovery(self, action: RecoveryAction, reason: str) -> bool:
        """Execute a recovery action."""
        logger.info(f"Executing recovery action {action.value} for {self.policy.service_name}: {reason}")
        
        start_time = time.time()
        success = False
        metadata = {}
        
        try:
            if action == RecoveryAction.RESTART:
                success = await self._restart_service()
                metadata["restart_count"] = self._restart_count
            
            elif action == RecoveryAction.DRAIN_TRAFFIC:
                success = await self._drain_traffic()
                metadata["drain_timeout"] = self.policy.drain_timeout_seconds
            
            elif action == RecoveryAction.FAILOVER:
                success = await self._failover()
            
            elif action == RecoveryAction.EVICT_NODE:
                success = await self._evict_node()
            
            elif action == RecoveryAction.CIRCUIT_BREAK:
                success = await self._circuit_break()
            
            # Record event
            event = RecoveryEvent(
                timestamp=time.time(),
                service_name=self.policy.service_name,
                action=action,
                reason=reason,
                success=success,
                metadata=metadata
            )
            self._recovery_events.append(event)
            
            return success
            
        except Exception as exc:
            logger.error(f"Recovery action {action.value} failed: {exc}")
            
            event = RecoveryEvent(
                timestamp=time.time(),
                service_name=self.policy.service_name,
                action=action,
                reason=reason,
                success=False,
                metadata={"error": str(exc)}
            )
            self._recovery_events.append(event)
            
            return False
    
    async def _restart_service(self) -> bool:
        """Restart the service."""
        try:
            # Drain traffic first
            await self._drain_traffic()
            
            # Wait for drain
            await asyncio.sleep(self.policy.restart_delay_seconds)
            
            # Record restart
            self._restart_count += 1
            self._restart_timestamps.append(time.time())
            
            # In a real implementation, this would restart the actual service process
            # For now, we just log it
            logger.info(f"Service {self.policy.service_name} restarted (count: {self._restart_count})")
            
            self.state = ServiceState.STARTING
            
            return True
            
        except Exception as exc:
            logger.error(f"Failed to restart service: {exc}")
            return False
    
    async def _drain_traffic(self) -> bool:
        """Drain traffic from the service."""
        try:
            self._draining = True
            self.state = ServiceState.DRAINING
            
            logger.info(f"Draining traffic from {self.policy.service_name}")
            
            # Wait for drain timeout
            await asyncio.sleep(self.policy.drain_timeout_seconds)
            
            self._draining = False
            
            return True
            
        except Exception as exc:
            logger.error(f"Failed to drain traffic: {exc}")
            self._draining = False
            return False
    
    async def _failover(self) -> bool:
        """Failover to backup instance."""
        try:
            logger.info(f"Failing over {self.policy.service_name} to backup")
            
            # In a real implementation, this would switch to a backup instance
            # For now, we just log it
            
            return True
            
        except Exception as exc:
            logger.error(f"Failed to failover: {exc}")
            return False
    
    async def _evict_node(self) -> bool:
        """Evict the node from the cluster."""
        try:
            logger.warning(f"Evicting node for {self.policy.service_name}")
            
            # In a real implementation, this would remove the node from load balancer
            # For now, we just log it
            
            self.state = ServiceState.STOPPED
            
            return True
            
        except Exception as exc:
            logger.error(f"Failed to evict node: {exc}")
            return False
    
    async def _circuit_break(self) -> bool:
        """Open circuit breaker for the service."""
        try:
            logger.warning(f"Opening circuit breaker for {self.policy.service_name}")
            
            # In a real implementation, this would open a circuit breaker
            # For now, we just log it
            
            return True
            
        except Exception as exc:
            logger.error(f"Failed to circuit break: {exc}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get recovery statistics."""
        return {
            "service_name": self.policy.service_name,
            "state": self.state.value,
            "restart_count": self._restart_count,
            "recent_restarts": len(self._restart_timestamps),
            "draining": self._draining,
            "recovery_events": len(self._recovery_events),
            "last_recovery": self._recovery_events[-1].__dict__ if self._recovery_events else None
        }


class RecoveryOrchestrator:
    """Orchestrates recovery across all services."""
    
    def __init__(self):
        self._managers: Dict[str, ServiceRecoveryManager] = {}
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
    
    def register_service(self, policy: RecoveryPolicy) -> None:
        """Register a service for recovery management."""
        manager = ServiceRecoveryManager(policy)
        self._managers[policy.service_name] = manager
        logger.info(f"Registered service for recovery: {policy.service_name}")
    
    def unregister_service(self, service_name: str) -> None:
        """Unregister a service."""
        if service_name in self._managers:
            del self._managers[service_name]
            logger.info(f"Unregistered service: {service_name}")
    
    async def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        while self._running:
            try:
                probe_registry = get_probe_registry()
                
                # Check all services
                for service_name, manager in self._managers.items():
                    # Get health status
                    summary = probe_registry.get_summary()
                    
                    # Determine if recovery needed
                    action = manager.record_health_check(
                        summary.get("by_status", {}).get("healthy", 0) > 0
                    )
                    
                    if action:
                        await manager.execute_recovery(
                            action,
                            f"Automatic recovery triggered by health check"
                        )
                
                await asyncio.sleep(10)  # Check every 10 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Error in recovery monitor loop: {exc}")
                await asyncio.sleep(10)
    
    def start_monitoring(self) -> None:
        """Start background monitoring."""
        if self._running:
            logger.warning("Recovery monitoring already running")
            return
        
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        
        logger.info(f"Started recovery monitoring for {len(self._managers)} services")
    
    async def stop_monitoring(self) -> None:
        """Stop background monitoring."""
        self._running = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Stopped recovery monitoring")
    
    def get_all_stats(self) -> Dict[str, Any]:
        """Get statistics for all services."""
        return {
            service_name: manager.get_stats()
            for service_name, manager in self._managers.items()
        }


# Global recovery orchestrator
_recovery_orchestrator: Optional[RecoveryOrchestrator] = None
_recovery_orchestrator_lock = threading.Lock()


def get_recovery_orchestrator() -> RecoveryOrchestrator:
    """Get the global recovery orchestrator."""
    global _recovery_orchestrator
    if _recovery_orchestrator is None:
        with _recovery_orchestrator_lock:
            if _recovery_orchestrator is None:
                _recovery_orchestrator = RecoveryOrchestrator()
    return _recovery_orchestrator
