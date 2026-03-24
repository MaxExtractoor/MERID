"""
System Health Monitoring for MERID.

Tracks health of all system components and provides status endpoints.
"""

from __future__ import annotations

import time
import asyncio
import psutil
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum

from utils.logger import get_logger

logger = get_logger("core.health")


class HealthStatus(Enum):
    """Health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealth:
    """Health status of a component."""
    name: str
    status: HealthStatus
    message: str = ""
    last_check: float = field(default_factory=time.time)
    metrics: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "last_check": self.last_check,
            "metrics": self.metrics,
        }


class HealthMonitor:
    """
    Monitors health of all MERID components.
    """
    
    def __init__(self):
        self._components: Dict[str, ComponentHealth] = {}
        self._start_time = time.time()
        self._running = False
        self._check_task: Optional[asyncio.Task] = None
        self.ready_event: asyncio.Event = asyncio.Event()
        
        logger.info("Health monitor initialized")
    
    async def start(self) -> None:
        """Start health monitoring."""
        if self._running:
            return
        
        self._running = True
        self._check_task = asyncio.create_task(self._monitor_loop())
        self.ready_event.set()
        logger.info("Health monitor started")
    
    async def stop(self) -> None:
        """Stop health monitoring."""
        self._running = False
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
        logger.info("Health monitor stopped")
    
    async def check_all(self) -> Dict[str, ComponentHealth]:
        """Check health of all components in parallel with timeout."""
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    self._check_event_bus(),
                    self._check_consensus_engine(),
                    self._check_execution_engine(),
                    self._check_agent_mesh(),
                    self._check_simulation_miner(),
                    self._check_audit_trail(),
                    self._check_system_resources(),
                    return_exceptions=True
                ),
                timeout=5.0
            )
        except asyncio.TimeoutError:
            logger.warning("Health check timed out")
        
        return self._components
    
    async def _check_event_bus(self) -> None:
        """Check event bus health."""
        try:
            from core.streaming_bus import streaming_bus
            
            metrics = streaming_bus.get_metrics()
            
            status = HealthStatus.HEALTHY
            message = "Event bus operational"
            
            if metrics.get("total_events", 0) == 0:
                status = HealthStatus.DEGRADED
                message = "No events processed yet"
            
            self._components["event_bus"] = ComponentHealth(
                name="Event Bus",
                status=status,
                message=message,
                metrics={
                    "total_events": metrics.get("total_events", 0),
                    "subscribers": metrics.get("total_subscribers", 0),
                },
            )
        except (ImportError, AttributeError, RuntimeError) as e:
            self._components["event_bus"] = ComponentHealth(
                name="Event Bus",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )
    
    async def _check_consensus_engine(self) -> None:
        """Check consensus engine health."""
        try:
            from core.consensus_engine import get_consensus_engine
            
            engine = get_consensus_engine()
            
            running = getattr(engine, 'running', False)
            status = HealthStatus.HEALTHY if running else HealthStatus.DEGRADED
            message = "Running" if running else "Not running"
            
            pending = getattr(engine, 'pending_votes', {})
            
            self._components["consensus"] = ComponentHealth(
                name="Consensus Engine",
                status=status,
                message=message,
                metrics={
                    "running": running,
                    "pending_votes": len(pending) if isinstance(pending, dict) else 0,
                },
            )
        except (ImportError, AttributeError, RuntimeError) as e:
            self._components["consensus"] = ComponentHealth(
                name="Consensus Engine",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )
    
    async def _check_execution_engine(self) -> None:
        """Check execution engine health."""
        try:
            from trading.execution import get_execution_engine
            
            engine = get_execution_engine()
            
            running = getattr(engine, 'running', True)  # Default to True if not found
            mode = getattr(engine.config, 'mode', None)
            mode_value = mode.value if mode else 'unknown'
            
            status = HealthStatus.HEALTHY if running else HealthStatus.DEGRADED
            message = f"Mode: {mode_value}"
            
            self._components["execution"] = ComponentHealth(
                name="Execution Engine",
                status=status,
                message=message,
                metrics={
                    "running": running,
                    "mode": mode_value,
                    "balance": getattr(engine, '_balance', 0),
                    "positions": len(getattr(engine, '_positions', {})),
                },
            )
        except (ImportError, AttributeError, RuntimeError) as e:
            self._components["execution"] = ComponentHealth(
                name="Execution Engine",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )
    
    async def _check_agent_mesh(self) -> None:
        """Check agent mesh health."""
        try:
            from agents.agent_mesh import agent_mesh
            
            running_agents = sum(1 for a in agent_mesh.agents if a.running)
            total_agents = len(agent_mesh.agents)
            
            if running_agents == total_agents and total_agents > 0:
                status = HealthStatus.HEALTHY
                message = f"All {total_agents} agents running"
            elif running_agents > 0:
                status = HealthStatus.DEGRADED
                message = f"{running_agents}/{total_agents} agents running"
            else:
                status = HealthStatus.UNHEALTHY
                message = "No agents running"
            
            self._components["agent_mesh"] = ComponentHealth(
                name="Agent Mesh",
                status=status,
                message=message,
                metrics={
                    "running": agent_mesh.running,
                    "total_agents": total_agents,
                    "running_agents": running_agents,
                },
            )
        except (ImportError, AttributeError, RuntimeError) as e:
            self._components["agent_mesh"] = ComponentHealth(
                name="Agent Mesh",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )
    
    async def _check_simulation_miner(self) -> None:
        """Check simulation miner health."""
        try:
            from simulation.continuous_miner import get_continuous_miner
            
            miner = get_continuous_miner()
            
            status = HealthStatus.HEALTHY if miner.running else HealthStatus.DEGRADED
            message = f"Block {miner.current_block}"
            
            self._components["simulation"] = ComponentHealth(
                name="Simulation Miner",
                status=status,
                message=message,
                metrics={
                    "running": miner.running,
                    "current_block": miner.current_block,
                },
            )
        except (ImportError, AttributeError, RuntimeError) as e:
            self._components["simulation"] = ComponentHealth(
                name="Simulation Miner",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )
    
    async def _check_audit_trail(self) -> None:
        """Check audit trail health."""
        try:
            from core.audit_trail import get_audit_trail
            
            audit = get_audit_trail()
            
            running = getattr(audit, 'running', True)
            sequence = getattr(audit, 'sequence', getattr(audit, '_sequence', 0))
            
            status = HealthStatus.HEALTHY if running else HealthStatus.DEGRADED
            message = f"{sequence} entries"
            
            self._components["audit"] = ComponentHealth(
                name="Audit Trail",
                status=status,
                message=message,
                metrics={
                    "running": running,
                    "entries": sequence,
                },
            )
        except (ImportError, AttributeError, RuntimeError) as e:
            self._components["audit"] = ComponentHealth(
                name="Audit Trail",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )
    
    async def _check_system_resources(self) -> None:
        """Check system resource usage."""
        try:
            cpu_percent = psutil.cpu_percent(interval=None)  # Non-blocking
            memory = psutil.virtual_memory()
            
            if cpu_percent > 90 or memory.percent > 90:
                status = HealthStatus.UNHEALTHY
                message = "High resource usage"
            elif cpu_percent > 70 or memory.percent > 70:
                status = HealthStatus.DEGRADED
                message = "Elevated resource usage"
            else:
                status = HealthStatus.HEALTHY
                message = "Resources normal"
            
            self._components["system"] = ComponentHealth(
                name="System Resources",
                status=status,
                message=message,
                metrics={
                    "cpu_percent": cpu_percent,
                    "memory_percent": memory.percent,
                    "memory_used_gb": memory.used / (1024**3),
                    "memory_total_gb": memory.total / (1024**3),
                },
            )
        except (IOError, OSError, RuntimeError) as e:
            self._components["system"] = ComponentHealth(
                name="System Resources",
                status=HealthStatus.UNKNOWN,
                message=str(e),
            )
    
    def get_overall_status(self) -> HealthStatus:
        """Get overall system health status."""
        if not self._components:
            return HealthStatus.UNKNOWN
        
        statuses = [c.status for c in self._components.values()]
        
        if HealthStatus.UNHEALTHY in statuses:
            return HealthStatus.UNHEALTHY
        elif HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED
        elif all(s == HealthStatus.HEALTHY for s in statuses):
            return HealthStatus.HEALTHY
        else:
            return HealthStatus.UNKNOWN
    
    def get_summary(self) -> Dict[str, Any]:
        """Get health summary."""
        return {
            "status": self.get_overall_status().value,
            "uptime_seconds": time.time() - self._start_time,
            "components": {
                name: comp.to_dict()
                for name, comp in self._components.items()
            },
            "healthy_count": sum(
                1 for c in self._components.values()
                if c.status == HealthStatus.HEALTHY
            ),
            "total_components": len(self._components),
        }
    
    async def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        while self._running:
            try:
                await self.check_all()
                await asyncio.sleep(30)  # Check every 30 seconds
            except asyncio.CancelledError:
                break
            except (RuntimeError, ConnectionError) as e:
                logger.error(f"Health monitor error: {e}")
                await asyncio.sleep(10)
            except Exception as e:
                logger.exception(f"Unexpected health monitor error: {e}")
                await asyncio.sleep(10)


# Singleton instance
_health_monitor: Optional[HealthMonitor] = None


def get_health_monitor() -> HealthMonitor:
    """Get or create health monitor singleton."""
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = HealthMonitor()
    return _health_monitor
