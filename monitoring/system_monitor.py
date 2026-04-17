"""
System Monitor.

Monitors system resources and component health.

Version: 1.0.0
"""

from __future__ import annotations

import threading
import asyncio
import time
import platform
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from monitoring.metrics_collector import MetricsCollector, get_metrics_collector
from utils.logger import get_logger

logger = get_logger("monitoring.system")


@dataclass
class SystemStats:
    """System resource statistics."""
    timestamp: float = field(default_factory=time.time)
    
    # CPU
    cpu_percent: float = 0.0
    cpu_count: int = 0
    
    # Memory
    memory_total_mb: float = 0.0
    memory_used_mb: float = 0.0
    memory_percent: float = 0.0
    
    # Disk
    disk_total_gb: float = 0.0
    disk_used_gb: float = 0.0
    disk_percent: float = 0.0
    
    # Network
    network_bytes_sent: int = 0
    network_bytes_recv: int = 0
    
    # Process
    process_memory_mb: float = 0.0
    process_cpu_percent: float = 0.0
    process_threads: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "cpu": {
                "percent": self.cpu_percent,
                "count": self.cpu_count,
            },
            "memory": {
                "total_mb": self.memory_total_mb,
                "used_mb": self.memory_used_mb,
                "percent": self.memory_percent,
            },
            "disk": {
                "total_gb": self.disk_total_gb,
                "used_gb": self.disk_used_gb,
                "percent": self.disk_percent,
            },
            "network": {
                "bytes_sent": self.network_bytes_sent,
                "bytes_recv": self.network_bytes_recv,
            },
            "process": {
                "memory_mb": self.process_memory_mb,
                "cpu_percent": self.process_cpu_percent,
                "threads": self.process_threads,
            },
        }


@dataclass
class ComponentStatus:
    """Status of a system component."""
    name: str
    healthy: bool = True
    status: str = "running"
    last_check: float = field(default_factory=time.time)
    latency_ms: float = 0.0
    error_message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "healthy": self.healthy,
            "status": self.status,
            "last_check": self.last_check,
            "latency_ms": self.latency_ms,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }


class SystemMonitor:
    """
    Monitors system resources and components.
    
    Features:
    - CPU, memory, disk monitoring
    - Process-level metrics
    - Component health tracking
    - Historical data
    """
    
    def __init__(self):
        self.logger = get_logger("monitoring.system")
        self._metrics = get_metrics_collector()
        
        # Current stats
        self._current_stats: Optional[SystemStats] = None
        
        # Historical stats
        self._history: List[SystemStats] = []
        self._max_history: int = 1000
        
        # Component status
        self._components: Dict[str, ComponentStatus] = {}
        
        # Running state
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._interval_seconds: float = 10.0
    
    async def start(self) -> None:
        """Start system monitoring."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        self.logger.info("System monitor started")
    
    async def stop(self) -> None:
        """Stop system monitoring."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.logger.info("System monitor stopped")
    
    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                stats = self._collect_stats()
                self._current_stats = stats
                
                # Store history
                self._history.append(stats)
                if len(self._history) > self._max_history:
                    self._history = self._history[-self._max_history:]
                
                # Update metrics
                self._update_metrics(stats)
                
                await asyncio.sleep(self._interval_seconds)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Monitor error: {e}")
                await asyncio.sleep(30)
    
    def _collect_stats(self) -> SystemStats:
        """Collect system statistics."""
        stats = SystemStats()
        
        try:
            import psutil
            
            # CPU
            stats.cpu_percent = psutil.cpu_percent(interval=0.1)
            stats.cpu_count = psutil.cpu_count()
            
            # Memory
            mem = psutil.virtual_memory()
            stats.memory_total_mb = mem.total / (1024 * 1024)
            stats.memory_used_mb = mem.used / (1024 * 1024)
            stats.memory_percent = mem.percent
            
            # Disk
            disk = psutil.disk_usage("/")
            stats.disk_total_gb = disk.total / (1024 * 1024 * 1024)
            stats.disk_used_gb = disk.used / (1024 * 1024 * 1024)
            stats.disk_percent = disk.percent
            
            # Network
            net = psutil.net_io_counters()
            stats.network_bytes_sent = net.bytes_sent
            stats.network_bytes_recv = net.bytes_recv
            
            # Process
            process = psutil.Process()
            stats.process_memory_mb = process.memory_info().rss / (1024 * 1024)
            stats.process_cpu_percent = process.cpu_percent()
            stats.process_threads = process.num_threads()
            
        except ImportError:
            # psutil not available, use fallback
            stats.cpu_count = 1
            stats.memory_percent = 50.0
            stats.disk_percent = 50.0
        except Exception as e:
            self.logger.debug(f"Stats collection error: {e}")
        
        return stats
    
    def _update_metrics(self, stats: SystemStats) -> None:
        """Update metrics from stats."""
        self._metrics.gauge("cpu_usage", stats.cpu_percent)
        self._metrics.gauge("memory_usage", stats.memory_percent)
        self._metrics.gauge("disk_usage", stats.disk_percent)
        self._metrics.gauge("process_memory_mb", stats.process_memory_mb)
        self._metrics.gauge("process_threads", stats.process_threads)
    
    def register_component(self, name: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Register a component for monitoring."""
        self._components[name] = ComponentStatus(
            name=name,
            metadata=metadata or {},
        )
    
    def update_component(
        self,
        name: str,
        healthy: bool,
        status: str = "running",
        latency_ms: float = 0.0,
        error_message: str = "",
    ) -> None:
        """Update component status."""
        if name not in self._components:
            self.register_component(name)
        
        component = self._components[name]
        component.healthy = healthy
        component.status = status
        component.latency_ms = latency_ms
        component.error_message = error_message
        component.last_check = time.time()
    
    def get_current_stats(self) -> Optional[Dict[str, Any]]:
        """Get current system stats."""
        if self._current_stats:
            return self._current_stats.to_dict()
        return None
    
    def get_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get historical stats."""
        return [s.to_dict() for s in self._history[-limit:]]
    
    def get_components(self) -> Dict[str, Dict[str, Any]]:
        """Get all component statuses."""
        return {name: c.to_dict() for name, c in self._components.items()}
    
    def get_unhealthy_components(self) -> List[Dict[str, Any]]:
        """Get unhealthy components."""
        return [c.to_dict() for c in self._components.values() if not c.healthy]
    
    def get_system_info(self) -> Dict[str, Any]:
        """Get system information."""
        return {
            "platform": platform.system(),
            "platform_release": platform.release(),
            "platform_version": platform.version(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
            "hostname": platform.node(),
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get monitor status."""
        return {
            "running": self._running,
            "interval_seconds": self._interval_seconds,
            "history_count": len(self._history),
            "components_count": len(self._components),
            "unhealthy_count": len(self.get_unhealthy_components()),
            "current_stats": self.get_current_stats(),
            "system_info": self.get_system_info(),
            "components": self.get_components(),
        }


# Singleton
_system_monitor: Optional[SystemMonitor] = None
_system_monitor_lock = threading.Lock()


def get_system_monitor() -> SystemMonitor:
    """Get or create the System Monitor singleton."""
    global _system_monitor
    if _system_monitor is None:
        with _system_monitor_lock:
            if _system_monitor is None:
                _system_monitor = SystemMonitor()
    return _system_monitor
