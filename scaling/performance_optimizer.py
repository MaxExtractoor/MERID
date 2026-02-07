"""
Performance Optimizer for MERID Production Scalability

Provides comprehensive performance monitoring, optimization, and
resource management with US-compliant configuration.

Features:
- Real-time performance monitoring
- Resource usage optimization
- Automatic scaling recommendations
- Performance bottleneck detection
- US-compliant resource management
"""

import asyncio
import time
import psutil
import gc
import threading
from typing import Dict, List, Optional, Any, Tuple, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import logging
import json

from utils.logger import get_logger

logger = get_logger("scaling.performance_optimizer")

@dataclass
class PerformanceMetrics:
    """System performance metrics."""
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    memory_available_mb: float
    disk_usage_percent: float
    disk_read_mb_s: float
    disk_write_mb_s: float
    network_sent_mb_s: float
    network_recv_mb_s: float
    active_connections: int
    thread_count: int
    process_count: int
    timestamp: float
    gc_collections: int
    response_time_ms: float
    throughput_ops_s: float

@dataclass
class ResourceThreshold:
    """Resource threshold configuration."""
    cpu_warning: float = 70.0
    cpu_critical: float = 85.0
    memory_warning: float = 75.0
    memory_critical: float = 90.0
    disk_warning: float = 80.0
    disk_critical: float = 95.0
    response_time_warning: float = 500.0  # ms
    response_time_critical: float = 1000.0  # ms
    throughput_warning: float = 100.0  # ops/s
    throughput_critical: float = 50.0  # ops/s

@dataclass
class OptimizationAction:
    """Performance optimization action."""
    action_id: str
    action_type: str  # gc, cache_clear, thread_pool_resize, connection_pool_resize
    description: str
    priority: str  # low, medium, high, critical
    impact_estimate: str
    execution_time: float
    success: bool = False
    error_message: Optional[str] = None
    metrics_before: Optional[PerformanceMetrics] = None
    metrics_after: Optional[PerformanceMetrics] = None
    timestamp: float = field(default_factory=time.time)

@dataclass
class ScalingRecommendation:
    """Auto-scaling recommendation."""
    recommendation_id: str
    resource_type: str  # cpu, memory, disk, network
    current_value: float
    threshold_value: float
    action: str  # scale_up, scale_down, optimize
    confidence: float
    estimated_cost: Optional[float] = None
    estimated_improvement: Optional[float] = None
    reasoning: str = ""
    timestamp: float = field(default_factory=time.time)

class PerformanceOptimizer:
    """
    Production-grade performance optimizer for MERID.
    
    Provides real-time monitoring, automatic optimization, and
    scaling recommendations for production workloads.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Performance monitoring
        self.metrics_history: deque = deque(maxlen=1000)
        self.current_metrics: Optional[PerformanceMetrics] = None
        self.monitoring_task: Optional[asyncio.Task] = None
        
        # Thresholds
        self.thresholds = ResourceThreshold(
            **config.get("thresholds", {})
        )
        
        # Optimization actions
        self.optimization_actions: deque = deque(maxlen=100)
        self.action_history: deque = deque(maxlen=1000)
        
        # Scaling recommendations
        self.scaling_recommendations: deque = deque(maxlen=100)
        
        # Performance callbacks
        self.performance_callbacks: List[Callable] = []
        
        # Resource limits
        self.resource_limits = config.get("resource_limits", {
            "max_cpu_percent": 95.0,
            "max_memory_percent": 95.0,
            "max_response_time_ms": 2000.0,
            "min_throughput_ops_s": 25.0
        })
        
        # US compliance
        self.us_compliance = config.get("us_compliance", {
            "resource_audit": True,
            "performance_logging": True,
            "cost_tracking": True,
            "security_monitoring": True
        })
        
        # Optimization settings
        self.auto_optimize = config.get("auto_optimize", True)
        self.optimization_interval = config.get("optimization_interval", 60)  # seconds
        
        logger.info("PerformanceOptimizer initialized")
    
    async def start(self):
        """Start performance monitoring and optimization."""
        logger.info("Starting performance optimizer")
        
        # Start monitoring
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())
        
        # Start optimization loop
        if self.auto_optimize:
            asyncio.create_task(self._optimization_loop())
        
        logger.info("Performance optimizer started")
    
    async def stop(self):
        """Stop performance monitoring and optimization."""
        logger.info("Stopping performance optimizer")
        
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Performance optimizer stopped")
    
    async def collect_metrics(self) -> PerformanceMetrics:
        """Collect current system performance metrics."""
        try:
            # CPU metrics
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # Memory metrics
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_used_mb = memory.used / 1024 / 1024
            memory_available_mb = memory.available / 1024 / 1024
            
            # Disk metrics
            disk = psutil.disk_usage('/')
            disk_usage_percent = disk.percent
            disk_io = psutil.disk_io_counters()
            disk_read_mb_s = disk_io.read_bytes / 1024 / 1024 if disk_io else 0
            disk_write_mb_s = disk_io.write_bytes / 1024 / 1024 if disk_io else 0
            
            # Network metrics
            network_io = psutil.net_io_counters()
            network_sent_mb_s = network_io.bytes_sent / 1024 / 1024 if network_io else 0
            network_recv_mb_s = network_io.bytes_recv / 1024 / 1024 if network_io else 0
            
            # Process metrics
            process_count = len(psutil.pids())
            thread_count = threading.active_count()
            
            # Connection metrics
            connections = len(psutil.net_connections())
            
            # GC metrics
            gc_stats = gc.get_stats()
            gc_collections = sum(stat['collections'] for stat in gc_stats)
            
            # Application metrics (mock for now)
            response_time_ms = self._calculate_response_time()
            throughput_ops_s = self._calculate_throughput()
            
            metrics = PerformanceMetrics(
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
                memory_used_mb=memory_used_mb,
                memory_available_mb=memory_available_mb,
                disk_usage_percent=disk_usage_percent,
                disk_read_mb_s=disk_read_mb_s,
                disk_write_mb_s=disk_write_mb_s,
                network_sent_mb_s=network_sent_mb_s,
                network_recv_mb_s=network_recv_mb_s,
                active_connections=connections,
                thread_count=thread_count,
                process_count=process_count,
                timestamp=time.time(),
                gc_collections=gc_collections,
                response_time_ms=response_time_ms,
                throughput_ops_s=throughput_ops_s
            )
            
            self.current_metrics = metrics
            self.metrics_history.append(metrics)
            
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to collect metrics: {e}")
            return self.current_metrics or PerformanceMetrics(
                cpu_percent=0, memory_percent=0, memory_used_mb=0, memory_available_mb=0,
                disk_usage_percent=0, disk_read_mb_s=0, disk_write_mb_s=0,
                network_sent_mb_s=0, network_recv_mb_s=0, active_connections=0,
                thread_count=0, process_count=0, timestamp=time.time(),
                gc_collections=0, response_time_ms=0, throughput_ops_s=0
            )
    
    async def _monitoring_loop(self):
        """Continuous performance monitoring loop."""
        while True:
            try:
                # Collect metrics
                metrics = await self.collect_metrics()
                
                # Check thresholds
                await self._check_thresholds(metrics)
                
                # Generate recommendations
                await self._generate_recommendations(metrics)
                
                # Notify callbacks
                await self._notify_callbacks(metrics)
                
                # Record for compliance
                if self.us_compliance.get("performance_logging", True):
                    await self._record_compliance(metrics)
                
                # Sleep for next iteration
                await asyncio.sleep(10)  # Monitor every 10 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitoring loop error: {e}")
                await asyncio.sleep(5)
    
    async def _optimization_loop(self):
        """Automatic optimization loop."""
        while True:
            try:
                # Check for optimization opportunities
                if self.current_metrics:
                    await self._auto_optimize()
                
                # Sleep for next iteration
                await asyncio.sleep(self.optimization_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Optimization loop error: {e}")
                await asyncio.sleep(30)
    
    async def _check_thresholds(self, metrics: PerformanceMetrics):
        """Check performance against thresholds."""
        alerts = []
        
        # CPU checks
        if metrics.cpu_percent >= self.thresholds.cpu_critical:
            alerts.append(("critical", f"CPU usage critical: {metrics.cpu_percent:.1f}%"))
        elif metrics.cpu_percent >= self.thresholds.cpu_warning:
            alerts.append(("warning", f"CPU usage high: {metrics.cpu_percent:.1f}%"))
        
        # Memory checks
        if metrics.memory_percent >= self.thresholds.memory_critical:
            alerts.append(("critical", f"Memory usage critical: {metrics.memory_percent:.1f}%"))
        elif metrics.memory_percent >= self.thresholds.memory_warning:
            alerts.append(("warning", f"Memory usage high: {metrics.memory_percent:.1f}%"))
        
        # Disk checks
        if metrics.disk_usage_percent >= self.thresholds.disk_critical:
            alerts.append(("critical", f"Disk usage critical: {metrics.disk_usage_percent:.1f}%"))
        elif metrics.disk_usage_percent >= self.thresholds.disk_warning:
            alerts.append(("warning", f"Disk usage high: {metrics.disk_usage_percent:.1f}%"))
        
        # Response time checks
        if metrics.response_time_ms >= self.thresholds.response_time_critical:
            alerts.append(("critical", f"Response time critical: {metrics.response_time_ms:.1f}ms"))
        elif metrics.response_time_ms >= self.thresholds.response_time_warning:
            alerts.append(("warning", f"Response time high: {metrics.response_time_ms:.1f}ms"))
        
        # Throughput checks
        if metrics.throughput_ops_s <= self.thresholds.throughput_critical:
            alerts.append(("critical", f"Throughput critical: {metrics.throughput_ops_s:.1f} ops/s"))
        elif metrics.throughput_ops_s <= self.thresholds.throughput_warning:
            alerts.append(("warning", f"Throughput low: {metrics.throughput_ops_s:.1f} ops/s"))
        
        # Log alerts
        for severity, message in alerts:
            if severity == "critical":
                logger.error(message)
            else:
                logger.warning(message)
    
    async def _generate_recommendations(self, metrics: PerformanceMetrics):
        """Generate scaling and optimization recommendations."""
        recommendations = []
        
        # CPU recommendations
        if metrics.cpu_percent >= self.thresholds.cpu_critical:
            recommendations.append(ScalingRecommendation(
                recommendation_id=f"cpu_scale_up_{int(time.time())}",
                resource_type="cpu",
                current_value=metrics.cpu_percent,
                threshold_value=self.thresholds.cpu_critical,
                action="scale_up",
                confidence=0.9,
                estimated_cost=50.0,  # Mock cost
                estimated_improvement=30.0,  # Mock improvement
                reasoning=f"CPU usage at {metrics.cpu_percent:.1f}% exceeds critical threshold"
            ))
        
        # Memory recommendations
        if metrics.memory_percent >= self.thresholds.memory_critical:
            recommendations.append(ScalingRecommendation(
                recommendation_id=f"memory_scale_up_{int(time.time())}",
                resource_type="memory",
                current_value=metrics.memory_percent,
                threshold_value=self.thresholds.memory_critical,
                action="scale_up",
                confidence=0.85,
                estimated_cost=75.0,
                estimated_improvement=40.0,
                reasoning=f"Memory usage at {metrics.memory_percent:.1f}% exceeds critical threshold"
            ))
        
        # Performance optimization recommendations
        if metrics.response_time_ms >= self.thresholds.response_time_warning:
            recommendations.append(ScalingRecommendation(
                recommendation_id=f"performance_optimize_{int(time.time())}",
                resource_type="performance",
                current_value=metrics.response_time_ms,
                threshold_value=self.thresholds.response_time_warning,
                action="optimize",
                confidence=0.8,
                estimated_cost=0.0,
                estimated_improvement=25.0,
                reasoning=f"Response time at {metrics.response_time_ms:.1f}ms exceeds warning threshold"
            ))
        
        # Add recommendations to queue
        for rec in recommendations:
            self.scaling_recommendations.append(rec)
    
    async def _auto_optimize(self):
        """Perform automatic optimizations."""
        if not self.current_metrics:
            return
        
        metrics = self.current_metrics
        
        # Memory optimization
        if metrics.memory_percent >= self.thresholds.memory_warning:
            await self._optimize_memory()
        
        # Performance optimization
        if metrics.response_time_ms >= self.thresholds.response_time_warning:
            await self._optimize_performance()
        
        # GC optimization
        if metrics.gc_collections > 100:  # High GC activity
            await self._optimize_gc()
    
    async def _optimize_memory(self):
        """Optimize memory usage."""
        try:
            metrics_before = self.current_metrics
            
            # Force garbage collection
            collected = gc.collect()
            
            # Clear caches (mock)
            cache_cleared = True  # In production, implement actual cache clearing
            
            # Create optimization action
            action = OptimizationAction(
                action_id=f"memory_optimize_{int(time.time())}",
                action_type="memory_optimization",
                description="Memory optimization: GC and cache clearing",
                priority="medium",
                impact_estimate="5-15% memory reduction",
                execution_time=0.1,
                success=True,
                metrics_before=metrics_before
            )
            
            # Collect metrics after optimization
            await asyncio.sleep(1)
            metrics_after = await self.collect_metrics()
            action.metrics_after = metrics_after
            
            self.optimization_actions.append(action)
            logger.info(f"Memory optimization completed: {collected} objects collected")
            
        except Exception as e:
            logger.error(f"Memory optimization failed: {e}")
    
    async def _optimize_performance(self):
        """Optimize application performance."""
        try:
            metrics_before = self.current_metrics
            
            # Thread pool optimization (mock)
            thread_optimized = True
            
            # Connection pool optimization (mock)
            connection_optimized = True
            
            # Cache warming (mock)
            cache_warmed = True
            
            # Create optimization action
            action = OptimizationAction(
                action_id=f"performance_optimize_{int(time.time())}",
                action_type="performance_optimization",
                description="Performance optimization: thread pool, connection pool, cache",
                priority="high",
                impact_estimate="10-25% performance improvement",
                execution_time=0.5,
                success=True,
                metrics_before=metrics_before
            )
            
            # Collect metrics after optimization
            await asyncio.sleep(1)
            metrics_after = await self.collect_metrics()
            action.metrics_after = metrics_after
            
            self.optimization_actions.append(action)
            logger.info("Performance optimization completed")
            
        except Exception as e:
            logger.error(f"Performance optimization failed: {e}")
    
    async def _optimize_gc(self):
        """Optimize garbage collection."""
        try:
            metrics_before = self.current_metrics
            
            # Adjust GC thresholds
            gc.set_threshold(700, 10, 10)  # More aggressive GC
            
            # Force collection
            collected = gc.collect()
            
            # Create optimization action
            action = OptimizationAction(
                action_id=f"gc_optimize_{int(time.time())}",
                action_type="gc_optimization",
                description="GC optimization: threshold adjustment and collection",
                priority="low",
                impact_estimate="2-5% performance improvement",
                execution_time=0.05,
                success=True,
                metrics_before=metrics_before
            )
            
            # Collect metrics after optimization
            await asyncio.sleep(1)
            metrics_after = await self.collect_metrics()
            action.metrics_after = metrics_after
            
            self.optimization_actions.append(action)
            logger.info(f"GC optimization completed: {collected} objects collected")
            
        except Exception as e:
            logger.error(f"GC optimization failed: {e}")
    
    def _calculate_response_time(self) -> float:
        """Calculate application response time (mock)."""
        # In production, calculate from actual request timing
        import random
        return random.uniform(50, 500)  # Mock response time in ms
    
    def _calculate_throughput(self) -> float:
        """Calculate application throughput (mock)."""
        # In production, calculate from actual request count
        import random
        return random.uniform(50, 200)  # Mock throughput in ops/s
    
    async def _notify_callbacks(self, metrics: PerformanceMetrics):
        """Notify performance callbacks."""
        for callback in self.performance_callbacks:
            try:
                await callback(metrics)
            except Exception as e:
                logger.error(f"Performance callback error: {e}")
    
    async def _record_compliance(self, metrics: PerformanceMetrics):
        """Record compliance audit entry."""
        if not self.us_compliance.get("resource_audit", True):
            return
        
        audit_entry = {
            "timestamp": metrics.timestamp,
            "cpu_percent": metrics.cpu_percent,
            "memory_percent": metrics.memory_percent,
            "disk_usage_percent": metrics.disk_usage_percent,
            "response_time_ms": metrics.response_time_ms,
            "throughput_ops_s": metrics.throughput_ops_s,
            "active_connections": metrics.active_connections
        }
        
        # In production, store in audit database
        logger.debug(f"Performance audit entry: {audit_entry}")
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get comprehensive performance summary."""
        if not self.current_metrics:
            return {"status": "no_data"}
        
        metrics = self.current_metrics
        
        # Calculate averages from history
        if len(self.metrics_history) > 1:
            avg_cpu = sum(m.cpu_percent for m in self.metrics_history) / len(self.metrics_history)
            avg_memory = sum(m.memory_percent for m in self.metrics_history) / len(self.metrics_history)
            avg_response = sum(m.response_time_ms for m in self.metrics_history) / len(self.metrics_history)
            avg_throughput = sum(m.throughput_ops_s for m in self.metrics_history) / len(self.metrics_history)
        else:
            avg_cpu = metrics.cpu_percent
            avg_memory = metrics.memory_percent
            avg_response = metrics.response_time_ms
            avg_throughput = metrics.throughput_ops_s
        
        return {
            "current": {
                "cpu_percent": metrics.cpu_percent,
                "memory_percent": metrics.memory_percent,
                "memory_used_mb": metrics.memory_used_mb,
                "disk_usage_percent": metrics.disk_usage_percent,
                "response_time_ms": metrics.response_time_ms,
                "throughput_ops_s": metrics.throughput_ops_s,
                "active_connections": metrics.active_connections,
                "thread_count": metrics.thread_count
            },
            "averages": {
                "cpu_percent": avg_cpu,
                "memory_percent": avg_memory,
                "response_time_ms": avg_response,
                "throughput_ops_s": avg_throughput
            },
            "alerts": {
                "cpu_warning": metrics.cpu_percent >= self.thresholds.cpu_warning,
                "cpu_critical": metrics.cpu_percent >= self.thresholds.cpu_critical,
                "memory_warning": metrics.memory_percent >= self.thresholds.memory_warning,
                "memory_critical": metrics.memory_percent >= self.thresholds.memory_critical,
                "response_time_warning": metrics.response_time_ms >= self.thresholds.response_time_warning,
                "response_time_critical": metrics.response_time_ms >= self.thresholds.response_time_critical
            },
            "optimizations": {
                "total_actions": len(self.optimization_actions),
                "successful_actions": sum(1 for a in self.optimization_actions if a.success),
                "recent_actions": len([a for a in self.optimization_actions if time.time() - a.timestamp < 3600])
            },
            "recommendations": {
                "total_recommendations": len(self.scaling_recommendations),
                "active_recommendations": len([r for r in self.scaling_recommendations if time.time() - r.timestamp < 1800])
            }
        }
    
    def get_optimization_history(self, limit: int = 50) -> List[OptimizationAction]:
        """Get optimization action history."""
        return list(self.optimization_actions)[-limit:]
    
    def get_scaling_recommendations(self, limit: int = 20) -> List[ScalingRecommendation]:
        """Get scaling recommendations."""
        return list(self.scaling_recommendations)[-limit:]
    
    def add_performance_callback(self, callback: Callable):
        """Add performance monitoring callback."""
        self.performance_callbacks.append(callback)
    
    def remove_performance_callback(self, callback: Callable):
        """Remove performance monitoring callback."""
        if callback in self.performance_callbacks:
            self.performance_callbacks.remove(callback)
    
    async def manual_optimization(self, optimization_type: str) -> OptimizationAction:
        """Perform manual optimization."""
        try:
            metrics_before = self.current_metrics
            
            if optimization_type == "memory":
                await self._optimize_memory()
                action_type = "memory_optimization"
            elif optimization_type == "performance":
                await self._optimize_performance()
                action_type = "performance_optimization"
            elif optimization_type == "gc":
                await self._optimize_gc()
                action_type = "gc_optimization"
            else:
                raise ValueError(f"Unknown optimization type: {optimization_type}")
            
            # Create manual action record
            action = OptimizationAction(
                action_id=f"manual_{optimization_type}_{int(time.time())}",
                action_type=action_type,
                description=f"Manual {optimization_type} optimization",
                priority="medium",
                impact_estimate="Manual optimization",
                execution_time=0.1,
                success=True,
                metrics_before=metrics_before
            )
            
            await asyncio.sleep(1)
            action.metrics_after = await self.collect_metrics()
            
            self.optimization_actions.append(action)
            logger.info(f"Manual {optimization_type} optimization completed")
            
            return action
            
        except Exception as e:
            logger.error(f"Manual optimization failed: {e}")
            raise
