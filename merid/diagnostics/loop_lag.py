"""Event-loop lag monitor for async health diagnostics.

Provides non-intrusive event-loop lag measurement to identify
asyncio starvation caused by blocking operations.

Thresholds (milliseconds, overridable via env):

- ``KALSHI_LOOP_LAG_HEALTHY_MS`` (default 3000): below = healthy.
- ``KALSHI_LOOP_LAG_DEGRADE_MS`` (default 8000): at/above = LIMITED-style
  degradation (warnings; CT blocks new entries when gate is LIMITED).
- ``KALSHI_LOOP_LAG_HALT_MS`` (default 15000): at/above = halt-eligible band.

OLD-HARDWARE FIX (2026-04-29): ULTRA-relaxed thresholds for very old hardware:
- Warning: 3000ms (was 100ms) - very high tolerance for slow hardware
- Degrade: 8000ms (was 2500ms) - requires 15 consecutive breaches
- Halt: 15000ms (was 5000ms) - requires 20 consecutive breaches, never auto-shutdown

Recovery: Breach counters reset after 45s of sustained lag < warning threshold.
Shutdown: NEVER automatic - only manual kill-switch or fatal structural errors.
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
    """Read lag bands from environment (shared with execution_gate).
    
    OLD-HARDWARE FIX (2026-04-29): ULTRA-relaxed for very old hardware + spotty internet.
    - Warning: 3000ms (was 100ms) - extreme tolerance for slow hardware
    - Degrade: 8000ms (was 2500ms) - requires 15 consecutive breaches
    - Halt: 15000ms (was 5000ms) - never triggers automatic shutdown
    """
    return {
        "healthy_ms": float(os.getenv("KALSHI_LOOP_LAG_HEALTHY_MS", "3000")),  # OLD-HW: 3000ms tolerance
        "degrade_ms": float(os.getenv("KALSHI_LOOP_LAG_DEGRADE_MS", "8000")),  # OLD-HW: 8000ms tolerance
        "halt_ms": float(os.getenv("KALSHI_LOOP_LAG_HALT_MS", "15000")),  # OLD-HW: 15000ms tolerance
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

        # Consecutive breach tracking for degraded/halt mode decisions
        # OLD-HARDWARE FIX (2026-04-29): ULTRA-relaxed for very old hardware
        self._degraded_consecutive_count: int = 0
        self._degraded_max_consecutive: int = int(os.getenv("KALSHI_LOOP_LAG_DEGRADED_CONSECUTIVE", "15"))  # 15 breaches (was 5)
        self._halt_consecutive_count: int = 0
        self._halt_max_consecutive: int = int(os.getenv("KALSHI_LOOP_LAG_HALT_CONSECUTIVE", "20"))  # 20 breaches (was 10)
        self._last_action_ts: float = 0.0
        self._action_cooldown_s: float = 5.0  # Min time between actions

        # Recovery tracking
        self._recovery_window_s: float = float(os.getenv("KALSHI_LOOP_LAG_RECOVERY_WINDOW_S", "45.0"))  # Reset counters after 45s healthy
        self._last_healthy_ts: Optional[float] = None

        # Load shedding state
        self._scope_reduced: bool = False
        self._scope_reduced_at: Optional[float] = None
        self._degraded_mode_active: bool = False  # OLD-HW: Track degraded mode separately
        
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
        """Trigger degraded lag callbacks (scope reduction).
        
        OLD-HARDWARE FIX: Require consecutive breaches before entering degraded mode.
        Single spikes are logged as warnings but don't change operating mode.
        """
        self._degraded_consecutive_count += 1
        
        # Only enter degraded mode after consecutive breaches
        if self._degraded_consecutive_count >= self._degraded_max_consecutive:
            if not self._degraded_mode_active:
                self._degraded_mode_active = True
                logger.warning(
                    "[LOOP-LAG] ENTERING DEGRADED MODE — lag %.1fms after %d consecutive breaches, reducing scope",
                    lag_ms, self._degraded_consecutive_count
                )
            
            if not self._scope_reduced and self._check_rate_limit():
                self._scope_reduced = True
                self._scope_reduced_at = time.time()
        else:
            # STARTUP-FIX: Classify isolated spikes as INFO, not WARNING
            # Degraded mode requires 5 consecutive breaches - single spikes are expected
            # DISABLED: User requested removal of LOOP-LAG logging
            # logger.info(
            #     "[LOOP-LAG] Elevated lag %.1fms (breach %d/%d for degraded mode)",
            #     lag_ms, self._degraded_consecutive_count, self._degraded_max_consecutive
            # )
            pass  # No action for isolated spikes

        for cb in self._on_degraded_callbacks:
            try:
                cb(lag_ms)
            except Exception as e:
                logger.debug(f"Degraded callback error: {e}")

    def _trigger_halt(self, lag_ms: float) -> None:
        """Trigger halt-band callbacks.

        OLD-HARDWARE POLICY: Never shutdown automatically due to loop lag.
        Only manual kill-switch or fatal structural errors trigger shutdown.
        """
        self._halt_consecutive_count += 1

        # Always call callbacks to allow custom handling (e.g., metrics, alerts)
        for cb in self._on_halt_callbacks:
            try:
                # Callbacks can return False to suppress default logging
                cb(lag_ms, self._halt_consecutive_count)
            except Exception as e:
                logger.debug(f"Halt callback error: {e}")

        # OLD-HARDWARE: Log only - never trigger automatic shutdown
        if self._halt_consecutive_count >= self._halt_max_consecutive:
            logger.critical(
                "[LOOP-LAG] HALT BAND SUSTAINED — lag %.1fms for %d consecutive samples. "
                "CONTINUING OPERATION (no auto-shutdown policy). Consider manual review.",
                lag_ms, self._halt_consecutive_count
            )
            # Reset counter to prevent log spam, but stay in halt band
            self._halt_consecutive_count = self._halt_max_consecutive // 2
        else:
            # STARTUP-FIX: Classify isolated halt-band spikes as INFO
            # Sustained halt requires 10 consecutive breaches
            # DISABLED: User requested removal of LOOP-LAG logging
            # logger.info(
            #     "[LOOP-LAG] HALT BAND (%.1fms, count=%d/%d) — continuing operation",
            #     lag_ms, self._halt_consecutive_count, self._halt_max_consecutive
            # )
            pass  # Continue operation despite lag

    def _reset_state_on_recovery(self, lag_ms: float, healthy_threshold: float) -> None:
        """Reset state when lag recovers to healthy levels.
        
        OLD-HARDWARE FIX: Recovery requires sustained healthy period (45s default).
        This prevents oscillation between degraded and normal modes.
        """
        now = time.time()
        
        # Track when we first dropped below warning threshold
        if self._last_healthy_ts is None:
            self._last_healthy_ts = now
        
        # Check if we've been healthy long enough to reset
        healthy_duration = now - self._last_healthy_ts
        
        if healthy_duration >= self._recovery_window_s:
            # Reset all breach counters after sustained recovery
            if self._halt_consecutive_count > 0 or self._degraded_consecutive_count > 0:
                # DISABLED: User requested removal of LOOP-LAG logging
                # logger.info(
                #     "[LOOP-LAG] Lag recovered to %.1fms after %.0fs sustained healthy period. "
                #     "Resetting breach counters (halt was %d, degraded was %d)",
                #     lag_ms, healthy_duration, self._halt_consecutive_count, self._degraded_consecutive_count
                # )
                self._halt_consecutive_count = 0
                self._degraded_consecutive_count = 0
                self._degraded_mode_active = False
            
            # Restore scope after recovery
            if self._scope_reduced and self._scope_reduced_at:
                recovery_duration = now - self._scope_reduced_at
                # DISABLED: User requested removal of LOOP-LAG logging
                # logger.info(
                #     "[LOOP-LAG] Scope restoration after %.1fs recovery (%.0fs healthy)",
                #     recovery_duration, healthy_duration
                # )
                self._scope_reduced = False
                self._scope_reduced_at = None
        else:
            # Still in recovery window - don't reset yet
            if self._degraded_mode_active or self._halt_consecutive_count > 0:
                # DISABLED: User requested removal of LOOP-LAG logging
                # logger.debug(
                #     "[LOOP-LAG] Recovery in progress: %.0f/%.0fs healthy, lag=%.1fms",
                #     healthy_duration, self._recovery_window_s, lag_ms
                # )
                # No action needed - just checking state
                pass

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

            # OLD-HARDWARE-FIX: Progressive action based on lag band with recovery tracking
            if lag_ms >= halt_ms:
                self._trigger_halt(lag_ms)
                self._last_healthy_ts = None  # Reset recovery timer
            elif lag_ms >= d_ms:
                self._trigger_degraded(lag_ms)
                self._last_healthy_ts = None  # Reset recovery timer
            elif lag_ms >= h_ok:
                self._trigger_elevated(lag_ms)
                self._last_healthy_ts = None  # Reset recovery timer
            else:
                # Healthy - track recovery and reset elevated state after sustained period
                self._reset_state_on_recovery(lag_ms, h_ok)
    
    def get_stats(self) -> LoopLagStats:
        """Get current lag statistics."""
        return self._stats
    
    @property
    def is_degraded(self) -> bool:
        """Return True if monitor is in degraded mode (sustained high lag).

        Used by SessionGuard to block new order placement during loop lag.
        """
        return self._degraded_mode_active

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
            # OLD-HARDWARE-FIX: Extended load shedding state
            "scope_reduced": self._scope_reduced,
            "scope_reduced_at": self._scope_reduced_at,
            "degraded_mode_active": self._degraded_mode_active,
            "degraded_consecutive_count": self._degraded_consecutive_count,
            "degraded_max_consecutive": self._degraded_max_consecutive,
            "halt_consecutive_count": self._halt_consecutive_count,
            "halt_max_consecutive": self._halt_max_consecutive,
            "recovery_window_s": self._recovery_window_s,
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
