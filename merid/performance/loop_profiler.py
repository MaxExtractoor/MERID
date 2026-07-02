"""
15m Loop Performance Profiler and Optimizer

Phase 4.2: Profile agent processing and market scanning

This module provides comprehensive performance monitoring and optimization
for the Kalshi 15m trading loop, including:
- Cycle timing analysis
- Agent processing bottlenecks
- Market scanning performance
- Memory usage tracking
- Event loop health monitoring
"""

from __future__ import annotations

import asyncio
import time
import threading
import psutil
import gc
from collections import deque, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Callable
from contextlib import asynccontextmanager
import statistics

from utils.logger import get_logger

logger = get_logger("merid.performance.loop_profiler")


@dataclass
class CycleMetrics:
    """Metrics for a single cycle execution."""
    cycle_id: int
    start_time: float
    end_time: float
    duration_ms: float
    agent_processing_ms: float
    market_scanning_ms: float
    order_submission_ms: float
    risk_check_ms: float
    memory_usage_mb: float
    cpu_percent: float
    error_count: int
    warnings: List[str] = field(default_factory=list)


@dataclass
class PerformanceSummary:
    """Aggregated performance summary."""
    total_cycles: int
    avg_cycle_duration_ms: float
    p95_cycle_duration_ms: float
    p99_cycle_duration_ms: float
    max_cycle_duration_ms: float
    min_cycle_duration_ms: float
    avg_memory_usage_mb: float
    max_memory_usage_mb: float
    avg_cpu_percent: float
    max_cpu_percent: float
    error_rate: float
    bottleneck_phase: str
    recommendations: List[str] = field(default_factory=list)


class LoopProfiler:
    """
    Comprehensive performance profiler for the 15m trading loop.
    
    Features:
    - Real-time cycle timing
    - Phase-level breakdown
    - Memory and CPU monitoring
    - Bottleneck detection
    - Performance recommendations
    """
    
    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self._cycle_history: deque = deque(maxlen=max_history)
        self._phase_timers: Dict[str, float] = {}
        self._start_time: Optional[float] = None
        self._current_cycle: Optional[int] = None
        self._enabled = True
        self._process = psutil.Process()
        
        # Performance thresholds
        self.CYCLE_DURATION_WARNING_MS = 1000.0  # 1 second
        self.CYCLE_DURATION_CRITICAL_MS = 2000.0  # 2 seconds
        self.MEMORY_WARNING_MB = 500.0  # 500MB
        self.CPU_WARNING_PERCENT = 80.0  # 80%
        
        # Phase tracking
        self._phases = [
            "agent_processing",
            "market_scanning", 
            "order_submission",
            "risk_check",
            "cleanup"
        ]
        
        logger.info("[LOOP-PROFILER] Initialized with max_history=%d", max_history)
    
    def enable(self) -> None:
        """Enable profiling."""
        self._enabled = True
        logger.info("[LOOP-PROFILER] Enabled")
    
    def disable(self) -> None:
        """Disable profiling."""
        self._enabled = False
        logger.info("[LOOP-PROFILER] Disabled")
    
    @asynccontextmanager
    async def profile_cycle(self, cycle_id: int):
        """Context manager for profiling a complete cycle."""
        if not self._enabled:
            yield
            return
        
        self._current_cycle = cycle_id
        self._start_time = time.time()
        
        # Record initial system metrics
        initial_memory = self._get_memory_usage()
        initial_cpu = self._get_cpu_usage()
        
        try:
            logger.debug("[LOOP-PROFILER] Starting cycle %d profiling", cycle_id)
            yield
        finally:
            end_time = time.time()
            duration_ms = (end_time - self._start_time) * 1000
            
            # Record final system metrics
            final_memory = self._get_memory_usage()
            final_cpu = self._get_cpu_usage()
            
            # Create cycle metrics
            metrics = CycleMetrics(
                cycle_id=cycle_id,
                start_time=self._start_time,
                end_time=end_time,
                duration_ms=duration_ms,
                agent_processing_ms=self._phase_timers.get("agent_processing", 0.0) * 1000,
                market_scanning_ms=self._phase_timers.get("market_scanning", 0.0) * 1000,
                order_submission_ms=self._phase_timers.get("order_submission", 0.0) * 1000,
                risk_check_ms=self._phase_timers.get("risk_check", 0.0) * 1000,
                memory_usage_mb=final_memory,
                cpu_percent=final_cpu,
                error_count=0,  # To be updated by error handlers
                warnings=self._generate_warnings(duration_ms, final_memory, final_cpu)
            )
            
            self._cycle_history.append(metrics)
            self._phase_timers.clear()
            self._current_cycle = None
            
            # Log performance metrics
            self._log_cycle_metrics(metrics)
            
            # Check for performance issues
            self._check_performance_issues(metrics)
    
    @asynccontextmanager
    async def profile_phase(self, phase_name: str):
        """Context manager for profiling a specific phase."""
        if not self._enabled or not self._current_cycle:
            yield
            return
        
        start_time = time.time()
        try:
            logger.debug("[LOOP-PROFILER] Starting phase: %s", phase_name)
            yield
        finally:
            end_time = time.time()
            duration = end_time - start_time
            self._phase_timers[phase_name] = self._phase_timers.get(phase_name, 0.0) + duration
            logger.debug("[LOOP-PROFILER] Completed phase: %s in %.3fs", phase_name, duration)
    
    def _get_memory_usage(self) -> float:
        """Get current memory usage in MB."""
        try:
            return self._process.memory_info().rss / 1024 / 1024
        except Exception:
            return 0.0
    
    def _get_cpu_usage(self) -> float:
        """Get current CPU usage percentage."""
        try:
            return self._process.cpu_percent()
        except Exception:
            return 0.0
    
    def _generate_warnings(self, duration_ms: float, memory_mb: float, cpu_percent: float) -> List[str]:
        """Generate performance warnings."""
        warnings = []
        
        if duration_ms > self.CYCLE_DURATION_CRITICAL_MS:
            warnings.append(f"CRITICAL: Cycle duration {duration_ms:.1f}ms exceeds threshold {self.CYCLE_DURATION_CRITICAL_MS}ms")
        elif duration_ms > self.CYCLE_DURATION_WARNING_MS:
            warnings.append(f"WARNING: Cycle duration {duration_ms:.1f}ms exceeds threshold {self.CYCLE_DURATION_WARNING_MS}ms")
        
        if memory_mb > self.MEMORY_WARNING_MB:
            warnings.append(f"WARNING: Memory usage {memory_mb:.1f}MB exceeds threshold {self.MEMORY_WARNING_MB}MB")
        
        if cpu_percent > self.CPU_WARNING_PERCENT:
            warnings.append(f"WARNING: CPU usage {cpu_percent:.1f}% exceeds threshold {self.CPU_WARNING_PERCENT}%")
        
        return warnings
    
    def _log_cycle_metrics(self, metrics: CycleMetrics) -> None:
        """Log cycle metrics."""
        logger.info(
            "[LOOP-PROFILER] Cycle %d: duration=%.1fms "
            "agent=%.1fms market=%.1fms order=%.1fms risk=%.1fms "
            "memory=%.1fMB cpu=%.1f%% warnings=%d",
            metrics.cycle_id,
            metrics.duration_ms,
            metrics.agent_processing_ms,
            metrics.market_scanning_ms,
            metrics.order_submission_ms,
            metrics.risk_check_ms,
            metrics.memory_usage_mb,
            metrics.cpu_percent,
            len(metrics.warnings)
        )
        
        # Log warnings if any
        for warning in metrics.warnings:
            logger.warning("[LOOP-PROFILER] %s", warning)
    
    def _check_performance_issues(self, metrics: CycleMetrics) -> None:
        """Check for performance issues and trigger optimizations."""
        if metrics.duration_ms > self.CYCLE_DURATION_CRITICAL_MS:
            logger.error("[LOOP-PROFILER] CRITICAL: Cycle %d took %.1fms - investigating bottleneck", 
                        metrics.cycle_id, metrics.duration_ms)
            self._analyze_bottlenecks(metrics)
    
    def _analyze_bottlenecks(self, metrics: CycleMetrics) -> None:
        """Analyze performance bottlenecks."""
        phase_times = [
            ("agent_processing", metrics.agent_processing_ms),
            ("market_scanning", metrics.market_scanning_ms),
            ("order_submission", metrics.order_submission_ms),
            ("risk_check", metrics.risk_check_ms),
        ]
        
        # Find slowest phase
        slowest_phase, slowest_time = max(phase_times, key=lambda x: x[1])
        
        logger.error("[LOOP-PROFILER] Bottleneck analysis:")
        logger.error("  Total duration: %.1fms", metrics.duration_ms)
        for phase, time_ms in phase_times:
            percentage = (time_ms / metrics.duration_ms) * 100 if metrics.duration_ms > 0 else 0
            logger.error("  %s: %.1fms (%.1f%%)", phase, time_ms, percentage)
        
        logger.error("  Slowest phase: %s (%.1fms)", slowest_phase, slowest_time)
        
        # Generate recommendations
        recommendations = self._generate_recommendations(metrics, phase_times)
        for rec in recommendations:
            logger.error("[LOOP-PROFILER] Recommendation: %s", rec)
    
    def _generate_recommendations(self, metrics: CycleMetrics, phase_times: List[tuple]) -> List[str]:
        """Generate performance optimization recommendations."""
        recommendations = []
        
        # Analyze phase-specific bottlenecks
        for phase, time_ms in phase_times:
            if phase == "agent_processing" and time_ms > 500:
                recommendations.append("Consider optimizing agent signal generation logic")
                recommendations.append("Implement agent result caching")
            
            elif phase == "market_scanning" and time_ms > 300:
                recommendations.append("Optimize market catalog queries")
                recommendations.append("Implement market data caching")
            
            elif phase == "order_submission" and time_ms > 200:
                recommendations.append("Check order router performance")
                recommendations.append("Optimize risk validation")
            
            elif phase == "risk_check" and time_ms > 100:
                recommendations.append("Cache risk envelope computations")
                recommendations.append("Optimize risk rule evaluation")
        
        # General recommendations
        if metrics.memory_usage_mb > self.MEMORY_WARNING_MB:
            recommendations.append("Implement memory cleanup and garbage collection")
            recommendations.append("Check for memory leaks in agent processing")
        
        if metrics.cpu_percent > self.CPU_WARNING_PERCENT:
            recommendations.append("Consider parallelizing independent operations")
            recommendations.append("Optimize CPU-intensive computations")
        
        return recommendations
    
    def get_performance_summary(self) -> PerformanceSummary:
        """Get aggregated performance summary."""
        if not self._cycle_history:
            return PerformanceSummary(
                total_cycles=0,
                avg_cycle_duration_ms=0.0,
                p95_cycle_duration_ms=0.0,
                p99_cycle_duration_ms=0.0,
                max_cycle_duration_ms=0.0,
                min_cycle_duration_ms=0.0,
                avg_memory_usage_mb=0.0,
                max_memory_usage_mb=0.0,
                avg_cpu_percent=0.0,
                max_cpu_percent=0.0,
                error_rate=0.0,
                bottleneck_phase="unknown",
                recommendations=["No data available"]
            )
        
        # Extract metrics
        durations = [m.duration_ms for m in self._cycle_history]
        memory_usage = [m.memory_usage_mb for m in self._cycle_history]
        cpu_usage = [m.cpu_percent for m in self._cycle_history]
        error_count = sum(m.error_count for m in self._cycle_history)
        
        # Calculate statistics
        avg_duration = statistics.mean(durations)
        p95_duration = statistics.quantiles(durations, n=20)[18] if len(durations) >= 20 else max(durations)
        p99_duration = statistics.quantiles(durations, n=100)[98] if len(durations) >= 100 else max(durations)
        
        # Find bottleneck phase
        phase_totals = defaultdict(float)
        for metrics in self._cycle_history:
            phase_totals["agent_processing"] += metrics.agent_processing_ms
            phase_totals["market_scanning"] += metrics.market_scanning_ms
            phase_totals["order_submission"] += metrics.order_submission_ms
            phase_totals["risk_check"] += metrics.risk_check_ms
        
        bottleneck_phase = max(phase_totals.items(), key=lambda x: x[1])[0]
        
        # Generate recommendations
        latest_metrics = self._cycle_history[-1]
        phase_times = [
            ("agent_processing", latest_metrics.agent_processing_ms),
            ("market_scanning", latest_metrics.market_scanning_ms),
            ("order_submission", latest_metrics.order_submission_ms),
            ("risk_check", latest_metrics.risk_check_ms),
        ]
        recommendations = self._generate_recommendations(latest_metrics, phase_times)
        
        return PerformanceSummary(
            total_cycles=len(self._cycle_history),
            avg_cycle_duration_ms=avg_duration,
            p95_cycle_duration_ms=p95_duration,
            p99_cycle_duration_ms=p99_duration,
            max_cycle_duration_ms=max(durations),
            min_cycle_duration_ms=min(durations),
            avg_memory_usage_mb=statistics.mean(memory_usage),
            max_memory_usage_mb=max(memory_usage),
            avg_cpu_percent=statistics.mean(cpu_usage),
            max_cpu_percent=max(cpu_usage),
            error_rate=error_count / len(self._cycle_history),
            bottleneck_phase=bottleneck_phase,
            recommendations=recommendations
        )
    
    def get_recent_cycles(self, count: int = 10) -> List[CycleMetrics]:
        """Get metrics for recent cycles."""
        return list(self._cycle_history)[-count:]
    
    def reset_history(self) -> None:
        """Reset performance history."""
        self._cycle_history.clear()
        self._phase_timers.clear()
        logger.info("[LOOP-PROFILER] Performance history reset")
    
    def export_metrics(self) -> Dict[str, Any]:
        """Export metrics for external monitoring."""
        summary = self.get_performance_summary()
        recent_cycles = self.get_recent_cycles(5)
        
        return {
            "summary": {
                "total_cycles": summary.total_cycles,
                "avg_duration_ms": summary.avg_cycle_duration_ms,
                "p95_duration_ms": summary.p95_cycle_duration_ms,
                "p99_duration_ms": summary.p99_cycle_duration_ms,
                "max_duration_ms": summary.max_cycle_duration_ms,
                "avg_memory_mb": summary.avg_memory_usage_mb,
                "max_memory_mb": summary.max_memory_usage_mb,
                "avg_cpu_percent": summary.avg_cpu_percent,
                "max_cpu_percent": summary.max_cpu_percent,
                "error_rate": summary.error_rate,
                "bottleneck_phase": summary.bottleneck_phase,
                "recommendations": summary.recommendations
            },
            "recent_cycles": [
                {
                    "cycle_id": m.cycle_id,
                    "duration_ms": m.duration_ms,
                    "agent_processing_ms": m.agent_processing_ms,
                    "market_scanning_ms": m.market_scanning_ms,
                    "order_submission_ms": m.order_submission_ms,
                    "risk_check_ms": m.risk_check_ms,
                    "memory_mb": m.memory_usage_mb,
                    "cpu_percent": m.cpu_percent,
                    "warnings": m.warnings
                }
                for m in recent_cycles
            ],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


# Global profiler instance
_profiler_instance: Optional[LoopProfiler] = None
_profiler_lock = threading.Lock()


def get_loop_profiler() -> LoopProfiler:
    """Get the global loop profiler instance."""
    global _profiler_instance
    
    if _profiler_instance is None:
        with _profiler_lock:
            if _profiler_instance is None:
                _profiler_instance = LoopProfiler()
    
    return _profiler_instance


def reset_loop_profiler() -> None:
    """Reset the global loop profiler instance."""
    global _profiler_instance
    
    with _profiler_lock:
        _profiler_instance = None
    
    logger.info("[LOOP-PROFILER] Global profiler instance reset")
