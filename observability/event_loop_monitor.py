"""Event loop lag monitoring for asyncio applications.

Measures event loop responsiveness by scheduling callbacks and measuring
the delay between when they were scheduled and when they actually execute.

This is critical for detecting event loop starvation, tight loops without
yields, and blocking operations on the main event loop.

⚠️  ADVISORY-ONLY POLICY
==========================
Event loop lag is a **diagnostic signal only**.  It MUST NOT:
- Flip any global ``trading_enabled`` / ``execution_gate`` flag.
- Activate any kill switch (global or per-domain).
- Set ``/api/health`` top-level status to "degraded".
- Appear in ``/api/v1/system/execution-gate`` reasons.

The ``_degraded`` flag and ``is_degraded()`` method on ``EventLoopMonitor``
are purely advisory and exist for operator dashboards and profiling.

Enforcement
-----------
``MERID_LOOP_LAG_KILL_SWITCH_ENABLED`` (default: ``false``)
    Guard for any hypothetical future kill-switch code path.  The default
    is ``false`` (non-blocking).  Set to ``true`` only in isolated test
    environments where you explicitly want lag to block execution.

Slow-action profiling (e.g. ``arb_scan`` 2-7 s spikes) is captured as
``HighLagProfile`` entries for post-hoc analysis but does NOT affect
the trading pipeline.  See ``get_profiles()`` and the
``/health/event_loop/profiles`` endpoint.

References:
- https://til.simonwillison.net/python/yielding-in-asyncio
- https://oneuptime.com/blog/post/2026-02-06-monitor-asyncio-event-loop-performance-opentelemetry/view
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("observability.event_loop_monitor")

# ── Config ────────────────────────────────────────────────────────────────────
# MERID_LOOP_LAG_KILL_SWITCH_ENABLED: if true, a hypothetical kill-switch path
# would be activated on halt-band lag.  Default is false (non-blocking, advisory).
# Production MUST keep this false.
_LAG_KILL_SWITCH_ENABLED: bool = os.environ.get(
    "MERID_LOOP_LAG_KILL_SWITCH_ENABLED", "false"
).lower() in ("1", "true", "yes")

# Advisory metric counter — incremented when lag exceeds a "halt-band" threshold.
# Read by dashboards only; MUST NOT be used to gate execution.
_metric_halt_band_total: int = 0   # samples that exceeded halt-band threshold (advisory)


@dataclass
class LagSample:
    """A single event loop lag measurement."""
    measured_at: datetime
    lag_ms: float
    expected_ms: float = 100.0  # Target callback interval


@dataclass
class HighLagProfile:
    """Captured profile during a high-lag event.

    Records stack traces and task information to identify
    which coroutines are blocking the event loop.
    """
    captured_at: datetime
    lag_ms: float
    active_task_count: int
    top_tasks: List[Dict[str, Any]]  # Top N tasks with name, coro, stack
    full_stack_trace: str  # Complete stack dump for analysis

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "captured_at": self.captured_at.isoformat(),
            "lag_ms": round(self.lag_ms, 2),
            "active_task_count": self.active_task_count,
            "top_tasks": self.top_tasks,
            "full_stack_trace": self.full_stack_trace,
        }


@dataclass
class LagStats:
    """Statistical summary of event loop lag over a time window."""
    window_seconds: int
    sample_count: int
    min_ms: float
    max_ms: float
    mean_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    samples_above_warn: int  # samples > 200ms
    samples_above_crit: int  # samples > 500ms


class EventLoopMonitor:
    """Continuously monitors event loop lag and exposes metrics.

    All lag state is **advisory only**.  High lag NEVER blocks trading or
    activates any kill switch.  Use the ``is_degraded()`` / ``_degraded``
    flag only for dashboards and alerting — never for execution gating.

    Usage:
        monitor = EventLoopMonitor()
        await monitor.start()

        # Later, get stats
        stats = monitor.get_stats()
        print(f"P95 lag: {stats.p95_ms}ms")

        # Cleanup
        await monitor.stop()
    """

    def __init__(
        self,
        sample_interval_ms: float = 100.0,
        max_samples: int = 6000,  # 10 minutes at 100ms interval
        warn_threshold_ms: float = 200.0,
        crit_threshold_ms: float = 500.0,
        profile_threshold_ms: float = 500.0,  # Capture profile when lag exceeds this
        max_profiles: int = 10,  # Keep last N high-lag profiles
    ):
        self.sample_interval_ms = sample_interval_ms
        self.max_samples = max_samples
        self.warn_threshold_ms = warn_threshold_ms
        self.crit_threshold_ms = crit_threshold_ms
        self.profile_threshold_ms = profile_threshold_ms
        self.max_profiles = max_profiles

        self._samples: Deque[LagSample] = deque(maxlen=max_samples)
        self._profiles: Deque[HighLagProfile] = deque(maxlen=max_profiles)
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_callback_time: float = 0.0
        self._degraded = False
        self._degraded_since: Optional[datetime] = None

    async def start(self) -> None:
        """Start monitoring event loop lag."""
        if self._running:
            logger.warning("EventLoopMonitor already running")
            return

        self._running = True
        self._last_callback_time = time.monotonic()
        self._task = asyncio.create_task(
            self._monitor_loop(),
            name="event-loop-monitor"
        )
        logger.info(
            f"EventLoopMonitor started: interval={self.sample_interval_ms}ms, "
            f"warn={self.warn_threshold_ms}ms, crit={self.crit_threshold_ms}ms"
        )

    async def stop(self) -> None:
        """Stop monitoring."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("EventLoopMonitor stopped")

    def _capture_high_lag_profile(self, lag_ms: float) -> None:
        """Capture a profile of running tasks during high lag event.

        This is called synchronously when lag exceeds the profile threshold.
        It captures stack traces of all running tasks to identify blocking code.
        """
        try:
            loop = asyncio.get_event_loop()
            all_tasks = asyncio.all_tasks(loop)

            # Build list of task info
            top_tasks = []
            for task in all_tasks:
                if task.done():
                    continue

                # Extract coroutine name and frame info
                coro = task.get_coro()
                coro_name = getattr(coro, '__name__', str(coro))
                coro_qualname = getattr(coro, '__qualname__', coro_name)

                # Get the coroutine's current frame for stack trace
                frame = getattr(coro, 'cr_frame', None) or getattr(coro, 'gi_frame', None)

                task_info = {
                    "name": task.get_name(),
                    "coro": coro_qualname,
                    "done": task.done(),
                    "cancelled": task.cancelled(),
                }

                # Capture stack trace if frame available
                if frame:
                    stack_lines = traceback.format_stack(frame)
                    # Get just the last few frames (most recent calls)
                    task_info["stack"] = "".join(stack_lines[-5:])
                    task_info["file"] = frame.f_code.co_filename
                    task_info["line"] = frame.f_lineno
                    task_info["function"] = frame.f_code.co_name
                else:
                    task_info["stack"] = "N/A"

                top_tasks.append(task_info)

            # Capture full stack dump for deep analysis
            full_stack = "=== Full Event Loop Stack Dump ===\n"
            full_stack += f"Active tasks: {len(all_tasks)}\n"
            full_stack += f"Lag: {lag_ms:.1f}ms\n\n"

            for idx, task_info in enumerate(top_tasks[:20], 1):  # Top 20 tasks
                full_stack += f"\n--- Task {idx}: {task_info['name']} ---\n"
                full_stack += f"Coroutine: {task_info['coro']}\n"
                if "file" in task_info:
                    full_stack += f"Location: {task_info['file']}:{task_info['line']} in {task_info['function']}\n"
                full_stack += f"{task_info.get('stack', 'N/A')}\n"

            # Create profile
            profile = HighLagProfile(
                captured_at=datetime.now(timezone.utc),
                lag_ms=lag_ms,
                active_task_count=len(all_tasks),
                top_tasks=top_tasks[:10],  # Keep top 10 for API response
                full_stack_trace=full_stack,
            )

            self._profiles.append(profile)

            # Log a summary
            logger.warning(
                f"High-lag profile captured: {lag_ms:.1f}ms, "
                f"{len(all_tasks)} active tasks. "
                f"Top offenders: {', '.join(t['coro'] for t in top_tasks[:3])}"
            )

        except Exception as exc:
            logger.error(f"Failed to capture high-lag profile: {exc}")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop.

        All state mutations here are advisory.  No kill switch is activated
        regardless of lag magnitude.  ``_degraded`` is a dashboard flag only.
        """
        global _metric_halt_band_total

        # Halt-band threshold: "extreme" lag used solely for the advisory counter.
        # Does NOT trigger any kill switch.
        _HALT_BAND_MS = float(os.environ.get("MERID_LOOP_LAG_HALT_BAND_MS", "2000"))

        while self._running:
            try:
                # Schedule a callback to measure lag
                scheduled_time = time.monotonic()
                await asyncio.sleep(self.sample_interval_ms / 1000.0)
                callback_time = time.monotonic()

                # Calculate actual lag (difference between expected and actual sleep time)
                expected_sleep_s = self.sample_interval_ms / 1000.0
                actual_sleep_s = callback_time - scheduled_time
                lag_s = max(0.0, actual_sleep_s - expected_sleep_s)
                lag_ms = lag_s * 1000.0

                # Record sample
                sample = LagSample(
                    measured_at=datetime.now(timezone.utc),
                    lag_ms=lag_ms,
                    expected_ms=self.sample_interval_ms,
                )
                self._samples.append(sample)

                # ── Halt-band advisory counter (NO kill switch) ────────────
                # When lag exceeds the halt-band threshold, we:
                #   1. Increment the advisory metric counter.
                #   2. Log at WARNING with context.
                # We do NOT flip any execution gate or kill switch.
                # _LAG_KILL_SWITCH_ENABLED guard is provided for isolated tests only.
                if lag_ms >= _HALT_BAND_MS:
                    _metric_halt_band_total += 1
                    logger.warning(
                        "event_loop_lag_halt_band: lag=%.0fms "
                        "halt_band_ms=%.0f event_loop_lag_halt_band_total=%d "
                        "[ADVISORY — no kill switch triggered]",
                        lag_ms,
                        _HALT_BAND_MS,
                        _metric_halt_band_total,
                    )
                    # ── Kill-switch guard (disabled by default) ──
                    if _LAG_KILL_SWITCH_ENABLED:
                        logger.error(
                            "MERID_LOOP_LAG_KILL_SWITCH_ENABLED=true — "
                            "halt-band kill-switch path enabled (non-prod only). "
                            "lag=%.0fms", lag_ms,
                        )
                        # NOTE: Even with the flag set we do NOT actually activate
                        # a kill switch here; this block exists only to document
                        # where such code would go and to emit a clear error so the
                        # flag mis-configuration is immediately visible in logs.

                # ── Standard threshold checks (advisory only) ─────────────
                if lag_ms >= self.crit_threshold_ms:
                    # Capture profile for high lag events
                    if lag_ms >= self.profile_threshold_ms:
                        self._capture_high_lag_profile(lag_ms)

                    if not self._degraded:
                        self._degraded = True
                        self._degraded_since = sample.measured_at
                        logger.warning(
                            "Event loop DEGRADED [advisory]: lag=%.1fms "
                            "(crit threshold=%.0fms) — no trading halt triggered",
                            lag_ms, self.crit_threshold_ms,
                        )
                    else:
                        logger.warning(
                            "Event loop lag spike [advisory]: %.1fms", lag_ms
                        )
                elif lag_ms >= self.warn_threshold_ms:
                    logger.debug("Event loop lag warning: %.1fms", lag_ms)
                else:
                    # Reset degraded state if lag drops below crit
                    if self._degraded:
                        logger.info(
                            "Event loop recovered: lag=%.1fms "
                            "(was degraded for %.1fs)",
                            lag_ms,
                            (sample.measured_at - self._degraded_since).total_seconds(),
                        )
                        self._degraded = False
                        self._degraded_since = None

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Error in event loop monitor: {exc}")
                await asyncio.sleep(1.0)  # Backoff on error

    def get_stats(self, window_seconds: int = 300) -> LagStats:
        """Get lag statistics for the last N seconds."""
        if not self._samples:
            return LagStats(
                window_seconds=window_seconds,
                sample_count=0,
                min_ms=0.0,
                max_ms=0.0,
                mean_ms=0.0,
                p50_ms=0.0,
                p95_ms=0.0,
                p99_ms=0.0,
                samples_above_warn=0,
                samples_above_crit=0,
            )

        # Filter to window
        cutoff = datetime.now(timezone.utc).timestamp() - window_seconds
        recent_samples = [
            s for s in self._samples
            if s.measured_at.timestamp() >= cutoff
        ]

        if not recent_samples:
            return LagStats(
                window_seconds=window_seconds,
                sample_count=0,
                min_ms=0.0,
                max_ms=0.0,
                mean_ms=0.0,
                p50_ms=0.0,
                p95_ms=0.0,
                p99_ms=0.0,
                samples_above_warn=0,
                samples_above_crit=0,
            )

        # Calculate stats
        lags = sorted([s.lag_ms for s in recent_samples])
        count = len(lags)

        return LagStats(
            window_seconds=window_seconds,
            sample_count=count,
            min_ms=min(lags),
            max_ms=max(lags),
            mean_ms=sum(lags) / count,
            p50_ms=lags[int(count * 0.50)] if count > 0 else 0.0,
            p95_ms=lags[int(count * 0.95)] if count > 20 else lags[-1] if lags else 0.0,
            p99_ms=lags[int(count * 0.99)] if count > 100 else lags[-1] if lags else 0.0,
            samples_above_warn=sum(1 for lag in lags if lag >= self.warn_threshold_ms),
            samples_above_crit=sum(1 for lag in lags if lag >= self.crit_threshold_ms),
        )

    def is_degraded(self) -> bool:
        """Return True when event loop is currently experiencing sustained high lag.

        ⚠️ ADVISORY ONLY — this flag must never be used to block execution or
        activate a kill switch.  It exists solely for operator dashboards and
        alerting.  See module docstring for the advisory-only policy.
        """
        return self._degraded

    def halt_band_count(self) -> int:
        """Return total number of samples that exceeded the halt-band threshold.

        This is the ``event_loop_lag_halt_band_total`` advisory metric.
        It is a cumulative counter since process start and MUST NOT be used
        to gate execution decisions.
        """
        return _metric_halt_band_total

    def get_profiles(self, max_count: Optional[int] = None) -> List[HighLagProfile]:
        """Get captured high-lag profiles.

        Args:
            max_count: Maximum number of profiles to return (most recent first).
                      If None, returns all stored profiles.

        Returns:
            List of HighLagProfile objects, most recent first.
        """
        profiles_list = list(self._profiles)
        profiles_list.reverse()  # Most recent first
        if max_count is not None:
            profiles_list = profiles_list[:max_count]
        return profiles_list

    def clear_profiles(self) -> int:
        """Clear all captured profiles.

        Returns:
            Number of profiles that were cleared.
        """
        count = len(self._profiles)
        self._profiles.clear()
        logger.info(f"Cleared {count} high-lag profiles")
        return count

    def get_current_status(self) -> Dict[str, object]:
        """Get current monitor status.

        All fields are advisory.  ``degraded`` and ``advisory_degraded`` MUST
        NOT be used to block execution.  See module-level docstring.
        """
        stats_5m = self.get_stats(window_seconds=300)
        stats_1m = self.get_stats(window_seconds=60)

        return {
            "running": self._running,
            # advisory_degraded replaces the old "degraded" key.
            # Both are kept for backward compatibility but MUST NOT gate execution.
            "degraded": self._degraded,           # legacy — advisory only
            "advisory_degraded": self._degraded,  # explicit advisory label
            "blocks_trading": False,              # always False — loop lag never blocks
            "degraded_since": self._degraded_since.isoformat() if self._degraded_since else None,
            "sample_interval_ms": self.sample_interval_ms,
            "warn_threshold_ms": self.warn_threshold_ms,
            "crit_threshold_ms": self.crit_threshold_ms,
            "profile_threshold_ms": self.profile_threshold_ms,
            "total_samples": len(self._samples),
            "total_profiles": len(self._profiles),
            "max_profiles": self.max_profiles,
            # Advisory metric counter for dashboards / Prometheus
            "event_loop_lag_halt_band_total": _metric_halt_band_total,
            "kill_switch_enabled": _LAG_KILL_SWITCH_ENABLED,
            "stats_1m": {
                "sample_count": stats_1m.sample_count,
                "mean_ms": round(stats_1m.mean_ms, 2),
                "p50_ms": round(stats_1m.p50_ms, 2),
                "p95_ms": round(stats_1m.p95_ms, 2),
                "p99_ms": round(stats_1m.p99_ms, 2),
                "max_ms": round(stats_1m.max_ms, 2),
                "samples_above_warn": stats_1m.samples_above_warn,
                "samples_above_crit": stats_1m.samples_above_crit,
            },
            "stats_5m": {
                "sample_count": stats_5m.sample_count,
                "mean_ms": round(stats_5m.mean_ms, 2),
                "p50_ms": round(stats_5m.p50_ms, 2),
                "p95_ms": round(stats_5m.p95_ms, 2),
                "p99_ms": round(stats_5m.p99_ms, 2),
                "max_ms": round(stats_5m.max_ms, 2),
                "samples_above_warn": stats_5m.samples_above_warn,
                "samples_above_crit": stats_5m.samples_above_crit,
            },
        }


# Global singleton
_event_loop_monitor: Optional[EventLoopMonitor] = None


def get_event_loop_monitor() -> EventLoopMonitor:
    """Get global EventLoopMonitor instance."""
    global _event_loop_monitor
    if _event_loop_monitor is None:
        _event_loop_monitor = EventLoopMonitor()
    return _event_loop_monitor
