"""Event loop lag monitoring for asyncio applications.

Measures event loop responsiveness by scheduling callbacks and measuring
the delay between when they were scheduled and when they actually execute.

This is critical for detecting event loop starvation, tight loops without
yields, and blocking operations on the main event loop.

References:
- https://til.simonwillison.net/python/yielding-in-asyncio
- https://oneuptime.com/blog/post/2026-02-06-monitor-asyncio-event-loop-performance-opentelemetry/view
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("observability.event_loop_monitor")


@dataclass
class LagSample:
    """A single event loop lag measurement."""
    measured_at: datetime
    lag_ms: float
    expected_ms: float = 100.0  # Target callback interval


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
    ):
        self.sample_interval_ms = sample_interval_ms
        self.max_samples = max_samples
        self.warn_threshold_ms = warn_threshold_ms
        self.crit_threshold_ms = crit_threshold_ms

        self._samples: Deque[LagSample] = deque(maxlen=max_samples)
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

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
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

                # Check thresholds
                if lag_ms >= self.crit_threshold_ms:
                    if not self._degraded:
                        self._degraded = True
                        self._degraded_since = sample.measured_at
                        logger.warning(
                            f"Event loop DEGRADED: lag={lag_ms:.1f}ms "
                            f"(crit threshold={self.crit_threshold_ms}ms)"
                        )
                    else:
                        logger.warning(f"Event loop lag spike: {lag_ms:.1f}ms")
                elif lag_ms >= self.warn_threshold_ms:
                    logger.debug(f"Event loop lag warning: {lag_ms:.1f}ms")
                else:
                    # Reset degraded state if lag drops below crit
                    if self._degraded:
                        logger.info(
                            f"Event loop recovered: lag={lag_ms:.1f}ms "
                            f"(was degraded for {(sample.measured_at - self._degraded_since).total_seconds():.1f}s)"
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
        """Check if event loop is currently degraded."""
        return self._degraded

    def get_current_status(self) -> Dict[str, object]:
        """Get current monitor status."""
        stats_5m = self.get_stats(window_seconds=300)
        stats_1m = self.get_stats(window_seconds=60)

        return {
            "running": self._running,
            "degraded": self._degraded,
            "degraded_since": self._degraded_since.isoformat() if self._degraded_since else None,
            "sample_interval_ms": self.sample_interval_ms,
            "warn_threshold_ms": self.warn_threshold_ms,
            "crit_threshold_ms": self.crit_threshold_ms,
            "total_samples": len(self._samples),
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
