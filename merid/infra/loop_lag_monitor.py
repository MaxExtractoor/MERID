"""Loop Lag Monitor — Tracks event loop latency and provides health status.

This module provides:
- Real-time loop latency sampling using asyncio event loop probes
- Rolling window statistics (p50, p95, p99)
- Health status evaluation with warn/degrade/halt thresholds
- Integration with ExecutionGate for automatic throttling

Usage:
    monitor = LoopLagMonitor()
    monitor.start()
    
    # In main loop
    lag_ms = monitor.sample()
    status = monitor.get_health_status()  # 'OK', 'WARN', 'DEGRADE', 'HALT'
"""

from __future__ import annotations

import asyncio
import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Deque, Optional, Dict, Any
from collections import deque

from utils.logger import get_logger

logger = get_logger("merid.infra.loop_lag_monitor")


@dataclass
class LagSample:
    """Single loop latency sample."""
    timestamp: float
    lag_ms: float


@dataclass
class LagStatistics:
    """Rolling window statistics."""
    samples: int = 0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    max_ms: float = 0.0
    mean_ms: float = 0.0


class LoopLagMonitor:
    """Monitors event loop latency and provides health status.
    
    The monitor works by scheduling a probe callback on the event loop
    and measuring the delay between expected and actual execution time.
    
    OLD-HARDWARE FIX (2026-04-28): Raised thresholds for weak hardware + spotty internet.
    Thresholds:
        - WARN: lag > LAG_WARN_MS (default 1500ms, was 100ms)
        - DEGRADE: lag > LAG_DEGRADE_MS (default 3000ms, was 250ms)
        - HALT: lag > LAG_HALT_MS (default 8000ms, was 500ms)
    
    All thresholds are configurable via settings and environment variables.
    """
    
    # OLD-HARDWARE FIX: Significantly raised defaults for weak hardware
    DEFAULT_WARN_MS = 1500.0  # was 100ms
    DEFAULT_DEGRADE_MS = 3000.0  # was 250ms
    DEFAULT_HALT_MS = 8000.0  # was 500ms
    DEFAULT_SAMPLE_INTERVAL = 1.0  # seconds between samples
    DEFAULT_WINDOW_SIZE = 60  # Keep last 60 samples (~1 minute at 1s interval)
    
    def __init__(
        self,
        warn_ms: float = DEFAULT_WARN_MS,
        degrade_ms: float = DEFAULT_DEGRADE_MS,
        halt_ms: float = DEFAULT_HALT_MS,
        sample_interval: float = DEFAULT_SAMPLE_INTERVAL,
        window_size: int = DEFAULT_WINDOW_SIZE,
    ):
        self._warn_ms = warn_ms
        self._degrade_ms = degrade_ms
        self._halt_ms = halt_ms
        self._sample_interval = sample_interval
        self._window_size = window_size
        
        # Rolling window of samples
        self._samples: Deque[LagSample] = deque(maxlen=window_size)
        self._lock = threading.Lock()
        
        # Sampling state
        self._running = False
        self._probe_handle: Optional[asyncio.Handle] = None
        self._last_probe_time: Optional[float] = None
        self._sample_task: Optional[asyncio.Task] = None
        
        # Statistics cache (computed on demand)
        self._stats_cache: Optional[LagStatistics] = None
        self._stats_last_computed = 0.0
        self._stats_ttl = 1.0  # Recompute stats at most once per second
        
        # Current health status
        self._current_status = "OK"
        self._current_lag_ms = 0.0
    
    # ── Lifecycle ─────────────────────────────────────────────────────
    
    async def start(self) -> None:
        """Start the lag monitoring loop."""
        if self._running:
            return
        
        self._running = True
        self._sample_task = asyncio.create_task(
            self._sampling_loop(),
            name="loop-lag-monitor"
        )
        logger.info(
            "LoopLagMonitor started (warn=%.0fms, degrade=%.0fms, halt=%.0fms)",
            self._warn_ms,
            self._degrade_ms,
            self._halt_ms,
        )
    
    async def stop(self) -> None:
        """Stop the lag monitoring loop."""
        self._running = False
        if self._sample_task and not self._sample_task.done():
            self._sample_task.cancel()
            try:
                await self._sample_task
            except asyncio.CancelledError:
                pass
        logger.info("LoopLagMonitor stopped")
    
    # ── Sampling ───────────────────────────────────────────────────────
    
    async def _sampling_loop(self) -> None:
        """Main sampling loop that measures event loop latency."""
        while self._running:
            try:
                lag_ms = await self._measure_once()
                
                with self._lock:
                    self._samples.append(LagSample(
                        timestamp=time.time(),
                        lag_ms=lag_ms,
                    ))
                    self._current_lag_ms = lag_ms
                    self._current_status = self._evaluate_status(lag_ms)
                
                # Log at appropriate level based on status
                if self._current_status == "HALT":
                    logger.critical(
                        "Loop lag HALT: %.1fms exceeded threshold %.0fms",
                        lag_ms,
                        self._halt_ms,
                    )
                elif self._current_status == "DEGRADE":
                    logger.error(
                        "Loop lag DEGRADE: %.1fms exceeded threshold %.0fms",
                        lag_ms,
                        self._degrade_ms,
                    )
                elif self._current_status == "WARN":
                    logger.warning(
                        "Loop lag WARN: %.1fms exceeded threshold %.0fms",
                        lag_ms,
                        self._warn_ms,
                    )
                
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug(f"Loop lag sampling error: {exc}")
            
            try:
                await asyncio.wait_for(
                    self._wait_for_next_sample(),
                    timeout=self._sample_interval
                )
            except asyncio.TimeoutError:
                pass  # Normal - just continue to next sample
    
    async def _measure_once(self) -> float:
        """Measure event loop latency once.
        
        Schedules a callback on the event loop and measures how long
        it takes to execute (indicates loop congestion).
        """
        start_time = time.monotonic()
        future: asyncio.Future[float] = asyncio.get_event_loop().create_future()
        
        def probe():
            # This callback executes on the event loop
            # The delay between schedule and execution is the lag
            scheduled_time = start_time
            executed_time = time.monotonic()
            lag_ms = (executed_time - scheduled_time) * 1000
            if not future.done():
                future.set_result(lag_ms)
        
        # Schedule the probe
        loop = asyncio.get_event_loop()
        loop.call_soon(probe)
        
        # Wait for probe to execute with timeout
        try:
            lag_ms = await asyncio.wait_for(future, timeout=5.0)
            return lag_ms
        except asyncio.TimeoutError:
            # Probe didn't execute within 5s - severe loop blockage
            return 5000.0  # Report as 5 seconds
    
    async def _wait_for_next_sample(self) -> None:
        """Wait for next sample interval."""
        await asyncio.sleep(self._sample_interval)
    
    # ── Status Evaluation ────────────────────────────────────────────
    
    def _evaluate_status(self, lag_ms: float) -> str:
        """Evaluate health status from lag measurement.
        
        Returns:
            'OK', 'WARN', 'DEGRADE', or 'HALT'
        """
        if lag_ms >= self._halt_ms:
            return "HALT"
        if lag_ms >= self._degrade_ms:
            return "DEGRADE"
        if lag_ms >= self._warn_ms:
            return "WARN"
        return "OK"
    
    # ── Public API ───────────────────────────────────────────────────
    
    def get_recent_ms(self) -> float:
        """Get most recent lag measurement in milliseconds."""
        with self._lock:
            return self._current_lag_ms
    
    def get_health_status(self) -> str:
        """Get current health status ('OK', 'WARN', 'DEGRADE', 'HALT')."""
        with self._lock:
            return self._current_status
    
    def get_statistics(self) -> LagStatistics:
        """Get rolling window statistics."""
        with self._lock:
            now = time.time()
            if self._stats_cache and (now - self._stats_last_computed) < self._stats_ttl:
                return self._stats_cache
            
            if not self._samples:
                return LagStatistics()
            
            lags = [s.lag_ms for s in self._samples]
            lags_sorted = sorted(lags)
            n = len(lags_sorted)
            
            stats = LagStatistics(
                samples=n,
                p50_ms=lags_sorted[int(n * 0.5)] if n > 1 else lags_sorted[0] if n else 0,
                p95_ms=lags_sorted[int(n * 0.95)] if n > 1 else lags_sorted[0] if n else 0,
                p99_ms=lags_sorted[int(n * 0.99)] if n > 1 else lags_sorted[0] if n else 0,
                max_ms=max(lags) if lags else 0,
                mean_ms=statistics.mean(lags) if lags else 0,
            )
            
            self._stats_cache = stats
            self._stats_last_computed = now
            return stats
    
    def health_check(self) -> Dict[str, Any]:
        """Full health check result for dashboards/monitoring."""
        stats = self.get_statistics()
        status = self.get_health_status()
        
        return {
            "healthy": status in ("OK", "WARN"),
            "status": status,
            "current_lag_ms": self.get_recent_ms(),
            "thresholds": {
                "warn_ms": self._warn_ms,
                "degrade_ms": self._degrade_ms,
                "halt_ms": self._halt_ms,
            },
            "statistics": {
                "samples": stats.samples,
                "p50_ms": round(stats.p50_ms, 2),
                "p95_ms": round(stats.p95_ms, 2),
                "p99_ms": round(stats.p99_ms, 2),
                "max_ms": round(stats.max_ms, 2),
                "mean_ms": round(stats.mean_ms, 2),
            },
            "running": self._running,
        }
    
    def should_degrade(self) -> bool:
        """Returns True if current status warrants degradation."""
        return self.get_health_status() in ("DEGRADE", "HALT")
    
    def should_halt(self) -> bool:
        """Returns True if current status warrants halt."""
        return self.get_health_status() == "HALT"


# ── Global Instance ────────────────────────────────────────────────────

_loop_lag_monitor: Optional[LoopLagMonitor] = None
_monitor_lock = threading.Lock()


def get_loop_lag_monitor() -> LoopLagMonitor:
    """Get or create global LoopLagMonitor instance."""
    global _loop_lag_monitor
    
    if _loop_lag_monitor is not None:
        return _loop_lag_monitor
    
    with _monitor_lock:
        if _loop_lag_monitor is not None:
            return _loop_lag_monitor
        
        # Try to load thresholds from settings
        try:
            from merid.settings import settings
            warn_ms = getattr(settings, "MERID_LOOP_LAG_WARN_MS", LoopLagMonitor.DEFAULT_WARN_MS)
            degrade_ms = getattr(settings, "MERID_LOOP_LAG_DEGRADE_MS", LoopLagMonitor.DEFAULT_DEGRADE_MS)
            halt_ms = getattr(settings, "MERID_LOOP_LAG_HALT_MS", LoopLagMonitor.DEFAULT_HALT_MS)
        except Exception:
            warn_ms = LoopLagMonitor.DEFAULT_WARN_MS
            degrade_ms = LoopLagMonitor.DEFAULT_DEGRADE_MS
            halt_ms = LoopLagMonitor.DEFAULT_HALT_MS
        
        _loop_lag_monitor = LoopLagMonitor(
            warn_ms=warn_ms,
            degrade_ms=degrade_ms,
            halt_ms=halt_ms,
        )
        return _loop_lag_monitor


def reset_loop_lag_monitor() -> None:
    """Reset the global monitor (for testing)."""
    global _loop_lag_monitor
    with _monitor_lock:
        _loop_lag_monitor = None
