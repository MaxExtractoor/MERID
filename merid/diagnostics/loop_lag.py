"""Event-loop lag monitor for async health diagnostics.

Provides non-intrusive event-loop lag measurement to identify
asyncio starvation caused by blocking operations.

Thresholds (milliseconds, overridable via env):

- ``KALSHI_LOOP_LAG_HEALTHY_MS`` (default 50): below = healthy.
- ``KALSHI_LOOP_LAG_DEGRADE_MS`` (default 500): at/above = LIMITED-style
  degradation (warnings; CT blocks new entries when gate is LIMITED).
- ``KALSHI_LOOP_LAG_HALT_MS`` (default 2000): at/above = halt-eligible band;
  ``core.execution_gate`` only trips kill / full block after **consecutive**
  samples in this band (see ``KALSHI_LOOP_LAG_HALT_CONSECUTIVE`` there).
- ``KALSHI_LOOP_LAG_P95_MIN_SAMPLES`` (default 10, read in ``execution_gate``):
  once lag stats report at least this many samples, LIMITED/degrade uses
  rolling ``p95_ms`` instead of a single ``current_ms`` tick.
"""

from __future__ import annotations

import asyncio
import os
import time
import threading
import traceback
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Set, Callable
from collections import defaultdict

from utils.logger import get_logger

logger = get_logger("merid.diagnostics.loop_lag")


def get_loop_lag_thresholds_ms() -> Dict[str, float]:
    """Read lag bands from environment (shared with execution_gate)."""
    return {
        "healthy_ms": float(os.getenv("KALSHI_LOOP_LAG_HEALTHY_MS", "50")),
        "degrade_ms": float(os.getenv("KALSHI_LOOP_LAG_DEGRADE_MS", "500")),
        "halt_ms": float(os.getenv("KALSHI_LOOP_LAG_HALT_MS", "2000")),
    }


@dataclass
class LoopLagSample:
    """Single event-loop lag sample."""
    timestamp: float
    lag_ms: float
    cpu_percent: Optional[float] = None


@dataclass
class LoopLagStats:
    """Aggregated event-loop lag statistics."""
    samples: List[LoopLagSample] = field(default_factory=list)
    max_samples: int = 60
    
    def add(self, sample: LoopLagSample) -> None:
        self.samples.append(sample)
        if len(self.samples) > self.max_samples:
            self.samples = self.samples[-self.max_samples:]
    
    @property
    def current_ms(self) -> float:
        return self.samples[-1].lag_ms if self.samples else 0.0
    
    @property
    def p50_ms(self) -> float:
        if not self.samples:
            return 0.0
        sorted_samples = sorted(s.lag_ms for s in self.samples)
        idx = len(sorted_samples) // 2
        return sorted_samples[idx]
    
    @property
    def p95_ms(self) -> float:
        if not self.samples:
            return 0.0
        sorted_samples = sorted(s.lag_ms for s in self.samples)
        idx = int(len(sorted_samples) * 0.95)
        return sorted_samples[min(idx, len(sorted_samples) - 1)]
    
    @property
    def p99_ms(self) -> float:
        if not self.samples:
            return 0.0
        sorted_samples = sorted(s.lag_ms for s in self.samples)
        idx = int(len(sorted_samples) * 0.99)
        return sorted_samples[min(idx, len(sorted_samples) - 1)]
    
    @property
    def max_ms(self) -> float:
        return max((s.lag_ms for s in self.samples), default=0.0)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_ms": round(self.current_ms, 2),
            "p50_ms": round(self.p50_ms, 2),
            "p95_ms": round(self.p95_ms, 2),
            "p99_ms": round(self.p99_ms, 2),
            "max_ms": round(self.max_ms, 2),
            "sample_count": len(self.samples),
        }


class LoopLagMonitor:
    """Monitor event-loop lag via periodic timer checks.

    EVENT-LOOP-FIX: Implements progressive load shedding based on lag thresholds:
    - elevated (50ms): Log warning, notify health endpoint
    - degraded (500ms): Trigger scope reduction callbacks (shed non-critical work)
    - halt (2000ms): Consider shutdown after consecutive samples, if shedding fails

    Usage:
        monitor = LoopLagMonitor()
        monitor.start()  # Begins monitoring
        ...
        stats = monitor.get_stats()  # Get current stats
        monitor.stop()
    """

    _instance: Optional[LoopLagMonitor] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, interval_ms: float = 1000.0):
        if self._initialized:
            return

        self._initialized = True
        self._interval_ms = interval_ms
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._stats = LoopLagStats()
        self._expected_time: Optional[float] = None
        self._shutdown_event: Optional[asyncio.Event] = None

        # Profiling data for high-lag periods
        self._profiling_enabled = True
        self._high_lag_profiles: List[Dict[str, Any]] = []
        self._max_profiles = 10

        # EVENT-LOOP-FIX: Action callbacks for progressive load shedding
        self._on_elevated_callbacks: List[Callable[[float], None]] = []
        self._on_degraded_callbacks: List[Callable[[float], None]] = []
        self._on_halt_callbacks: List[Callable[[float, int], Optional[bool]]] = []

        # Consecutive halt-band tracking for shutdown decision
        self._halt_consecutive_count: int = 0
        self._halt_max_consecutive: int = int(os.getenv("KALSHI_LOOP_LAG_HALT_CONSECUTIVE", "3"))
        self._last_action_ts: float = 0.0
        self._action_cooldown_s: float = 5.0  # Min time between actions

        # Load shedding state
        self._scope_reduced: bool = False
        self._scope_reduced_at: Optional[float] = None
        
    def _capture_task_snapshot(self) -> List[Dict[str, Any]]:
        """Capture snapshot of currently running asyncio tasks."""
        try:
            loop = asyncio.get_running_loop()
            tasks = []
            for task in asyncio.all_tasks(loop):
                if not task.done():
                    task_info = {
                        "name": task.get_name() if hasattr(task, "get_name") else str(task),
                        "coro": str(task.get_coro())[:200] if hasattr(task, "get_coro") else "unknown",
                        "stack": [],
                    }
                    tasks.append(task_info)
            return tasks
        except Exception as e:
            return [{"error": str(e)}]
    
    def _record_high_lag_profile(self, lag_ms: float, tasks: List[Dict[str, Any]]) -> None:
        """Record profiling data for high-lag period."""
        import traceback
        profile = {
            "timestamp": time.time(),
            "lag_ms": lag_ms,
            "active_tasks": len(tasks),
            "tasks": tasks[:20],  # Limit to first 20 tasks
            "stack_sample": traceback.format_stack()[-5:-1],  # Sample of call stack
        }
        self._high_lag_profiles.append(profile)
        if len(self._high_lag_profiles) > self._max_profiles:
            self._high_lag_profiles.pop(0)
    
    def get_high_lag_profiles(self) -> List[Dict[str, Any]]:
        """Get recorded high-lag profiling data."""
        return self._high_lag_profiles.copy()

    def start(self) -> None:
        """Start the lag monitor."""
        if self._running:
            return
        
        self._running = True
        self._shutdown_event = asyncio.Event()
        
        try:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._monitor_loop())
            logger.info(f"LoopLagMonitor started (interval={self._interval_ms}ms)")
        except RuntimeError:
            logger.warning("LoopLagMonitor: no running event loop, deferring start")
    
    def stop(self) -> None:
        """Stop the lag monitor."""
        if not self._running:
            return
        
        self._running = False
        if self._shutdown_event:
            self._shutdown_event.set()
        
        if self._task and not self._task.done():
            self._task.cancel()
    
    def on_elevated(self, callback: Callable[[float], None]) -> None:
        """Register callback for elevated lag events.

        Callback receives the lag_ms value.
        """
        self._on_elevated_callbacks.append(callback)

    def on_degraded(self, callback: Callable[[float], None]) -> None:
        """Register callback for degraded lag events (scope reduction).

        Callback receives the lag_ms value. Should trigger load shedding.
        """
        self._on_degraded_callbacks.append(callback)

    def on_halt(self, callback: Callable[[float, int], Optional[bool]]) -> None:
        """Register callback for halt-band lag events.

        Callback receives (lag_ms, consecutive_count) and should return:
        - True if shutdown should proceed
        - False if load shedding was successful (stay alive)
        - None for default behavior (shutdown after threshold)
        """
        self._on_halt_callbacks.append(callback)

    def _check_rate_limit(self) -> bool:
        """Check if action can be taken (rate limiting)."""
        now = time.time()
        if now - self._last_action_ts < self._action_cooldown_s:
            return False
        self._last_action_ts = now
        return True

    def _trigger_elevated(self, lag_ms: float) -> None:
        """Trigger elevated lag callbacks."""
        for cb in self._on_elevated_callbacks:
            try:
                cb(lag_ms)
            except Exception as e:
                logger.debug(f"Elevated callback error: {e}")

    def _trigger_degraded(self, lag_ms: float) -> None:
        """Trigger degraded lag callbacks (scope reduction)."""
        if not self._scope_reduced and self._check_rate_limit():
            self._scope_reduced = True
            self._scope_reduced_at = time.time()
            logger.warning(
                "[LOOP-LAG] ENTERING DEGRADED MODE — lag %.1fms, reducing scope",
                lag_ms
            )

        for cb in self._on_degraded_callbacks:
            try:
                cb(lag_ms)
            except Exception as e:
                logger.debug(f"Degraded callback error: {e}")

    def _trigger_halt(self, lag_ms: float) -> None:
        """Trigger halt-band callbacks (consider shutdown).

        Returns True if shutdown should proceed, False otherwise.
        """
        self._halt_consecutive_count += 1

        # Always call callbacks to allow custom handling
        should_shutdown: Optional[bool] = None
        for cb in self._on_halt_callbacks:
            try:
                result = cb(lag_ms, self._halt_consecutive_count)
                if result is not None:
                    should_shutdown = result
            except Exception as e:
                logger.debug(f"Halt callback error: {e}")

        # If callbacks explicitly said don't shutdown, respect that
        if should_shutdown is False:
            logger.warning(
                "[LOOP-LAG] HALT BAND (%.1fms, count=%d) — callbacks suppressed shutdown",
                lag_ms, self._halt_consecutive_count
            )
            return

        # Default: shutdown after consecutive threshold
        if self._halt_consecutive_count >= self._halt_max_consecutive:
            logger.critical(
                "[LOOP-LAG] HALT BAND SHUTDOWN TRIGGERED — lag %.1fms for %d consecutive samples "
                "(max=%d). Initiating controlled shutdown.",
                lag_ms, self._halt_consecutive_count, self._halt_max_consecutive
            )
            try:
                from web.asgi_guard import initiate_shutdown, ShutdownReason
                initiate_shutdown(
                    reason=ShutdownReason.LOOP_LAG_HALT,
                    sub_reason=f"lag_{lag_ms:.0f}ms_consecutive_{self._halt_consecutive_count}",
                    initiator_module="merid.diagnostics.loop_lag",
                    metrics={
                        "lag_ms": lag_ms,
                        "consecutive_count": self._halt_consecutive_count,
                        "scope_reduced": self._scope_reduced,
                    }
                )
            except Exception as e:
                logger.critical(f"Failed to initiate shutdown: {e}")
        else:
            logger.warning(
                "[LOOP-LAG] HALT BAND (%.1fms, count=%d/%d) — approaching shutdown threshold",
                lag_ms, self._halt_consecutive_count, self._halt_max_consecutive
            )

    def _reset_state_on_recovery(self, lag_ms: float) -> None:
        """Reset state when lag recovers to healthy levels."""
        if self._halt_consecutive_count > 0:
            logger.info(
                "[LOOP-LAG] Lag recovered to %.1fms, resetting halt counter (was %d)",
                lag_ms, self._halt_consecutive_count
            )
            self._halt_consecutive_count = 0

        if self._scope_reduced and self._scope_reduced_at:
            # Only restore after sustained recovery
            recovery_duration = time.time() - self._scope_reduced_at
            if recovery_duration > 30.0:  # 30s of recovery before restoring scope
                logger.info(
                    "[LOOP-LAG] Scope restoration after %.1fs recovery",
                    recovery_duration
                )
                self._scope_reduced = False
                self._scope_reduced_at = None

    async def _monitor_loop(self) -> None:
        """Main monitoring loop with progressive load shedding.

        EVENT-LOOP-FIX: Implements concrete actions at each threshold:
        - elevated (50ms): Log warning, notify health endpoint
        - degraded (500ms): Trigger scope reduction callbacks
        - halt (2000ms): Consider shutdown after consecutive samples
        """
        while self._running:
            t0 = time.monotonic()
            self._expected_time = t0 + (self._interval_ms / 1000.0)

            # Try to sleep exactly interval_ms
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self._interval_ms / 1000.0
                )
                break  # Shutdown requested
            except asyncio.TimeoutError:
                pass

            # Measure how late we are
            t1 = time.monotonic()
            lag_ms = max(0.0, (t1 - self._expected_time) * 1000.0)

            self._stats.add(LoopLagSample(timestamp=t1, lag_ms=lag_ms))

            th = get_loop_lag_thresholds_ms()
            h_ok = th["healthy_ms"]
            d_ms = th["degrade_ms"]
            halt_ms = th["halt_ms"]

            # Capture profiling data for high lag
            if lag_ms >= d_ms and self._profiling_enabled:
                tasks = self._capture_task_snapshot()
                self._record_high_lag_profile(lag_ms, tasks)

            # EVENT-LOOP-FIX: Progressive action based on lag band
            if lag_ms >= halt_ms:
                self._trigger_halt(lag_ms)
            elif lag_ms >= d_ms:
                self._trigger_degraded(lag_ms)
                self._reset_state_on_recovery(lag_ms)
            elif lag_ms >= h_ok:
                self._trigger_elevated(lag_ms)
                self._reset_state_on_recovery(lag_ms)
            else:
                # Healthy - reset any elevated state
                self._reset_state_on_recovery(lag_ms)
    
    def get_stats(self) -> LoopLagStats:
        """Get current lag statistics."""
        return self._stats
    
    def get_health(self) -> Dict[str, Any]:
        """Get health status for monitoring endpoints.

        EVENT-LOOP-FIX: Includes load-shedding state for external health checks.
        """
        stats = self._stats
        th = get_loop_lag_thresholds_ms()
        h_ms = th["healthy_ms"]
        d_ms = th["degrade_ms"]
        halt_ms = th["halt_ms"]
        lag_ms = stats.current_ms
        # Mutually exclusive bands for gate mapping
        healthy = lag_ms < h_ms
        elevated = (not healthy) and lag_ms < d_ms
        degraded = d_ms <= lag_ms < halt_ms
        critical = lag_ms >= halt_ms
        health = {
            "running": self._running,
            "interval_ms": self._interval_ms,
            "stats": stats.to_dict(),
            "thresholds_ms": {k: round(v, 1) for k, v in th.items()},
            "healthy": healthy,
            "elevated": elevated,
            "degraded": degraded,
            "critical": critical,
            "high_lag_profiles": len(self._high_lag_profiles),
            # EVENT-LOOP-FIX: Load shedding state
            "scope_reduced": self._scope_reduced,
            "scope_reduced_at": self._scope_reduced_at,
            "halt_consecutive_count": self._halt_consecutive_count,
            "halt_max_consecutive": self._halt_max_consecutive,
        }
        return health


def get_loop_lag_monitor() -> LoopLagMonitor:
    """Get the singleton LoopLagMonitor instance."""
    return LoopLagMonitor()


# Convenience function for quick lag check
async def measure_loop_lag() -> float:
    """Measure current event-loop lag (one-shot).
    
    Returns:
        Lag in milliseconds
    """
    t0 = time.monotonic()
    await asyncio.sleep(0)  # Yield control
    t1 = time.monotonic()
    return max(0.0, (t1 - t0) * 1000.0)


# EVENT-LOOP-FIX: Utility functions for lag-aware operation guards
def get_current_lag_ms() -> float:
    """Get current event-loop lag without blocking.
    
    Returns:
        Current lag in milliseconds, or 0.0 if monitor unavailable.
    """
    try:
        monitor = get_loop_lag_monitor()
        health = monitor.get_health()
        return health.get("current_ms", 0.0)
    except Exception:
        return 0.0


def is_lag_elevated(threshold_ms: float = 500.0) -> bool:
    """Check if event-loop lag is elevated.
    
    Args:
        threshold_ms: Lag threshold in milliseconds (default: 500ms)
        
    Returns:
        True if lag exceeds threshold, False otherwise.
    """
    return get_current_lag_ms() > threshold_ms


def is_lag_degraded(threshold_ms: float = 1000.0) -> bool:
    """Check if event-loop lag is in degraded state.
    
    Args:
        threshold_ms: Lag threshold in milliseconds (default: 1000ms)
        
    Returns:
        True if lag exceeds threshold, False otherwise.
    """
    return get_current_lag_ms() > threshold_ms


def is_lag_halt_band(threshold_ms: float = 2000.0) -> bool:
    """Check if event-loop lag is in halt band (critical).
    
    Args:
        threshold_ms: Lag threshold in milliseconds (default: 2000ms)
        
    Returns:
        True if lag exceeds threshold, False otherwise.
    """
    return get_current_lag_ms() > threshold_ms


async def with_timeout_guard(coro, timeout_ms: float, operation_name: str = "operation"):
    """Execute coroutine with timeout to prevent event-loop starvation.
    
    EVENT-LOOP-FIX: Wraps slow operations to prevent them from blocking
    the event loop beyond their budget.
    
    Args:
        coro: Coroutine to execute
        timeout_ms: Timeout in milliseconds
        operation_name: Name for logging
        
    Returns:
        Result of coroutine
        
    Raises:
        asyncio.TimeoutError: If operation exceeds timeout
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout_ms / 1000.0)
    except asyncio.TimeoutError:
        logger.warning(
            f"[EVENT-LOOP-FIX] Operation '{operation_name}' timed out after {timeout_ms}ms "
            f"— prevented event-loop starvation"
        )
        raise
