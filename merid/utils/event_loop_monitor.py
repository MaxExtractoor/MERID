"""Asyncio event loop lag and stall monitor.

Monitors the responsiveness of the main asyncio event loop by measuring the delay
between scheduled sleep wakeups. If the event loop is blocked by synchronous code,
heavy I/O, or thread contention, the delay exceeds the expected interval and is logged.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("merid.event_loop_monitor")


class EventLoopLagMonitor:
    """Monitors asyncio event-loop scheduling latency and exposes lag metrics."""

    def __init__(
        self,
        check_interval_s: float = 1.0,
        stall_threshold_s: float = 2.0,
    ) -> None:
        self._check_interval = float(
            os.getenv("MERID_LOOP_LAG_CHECK_INTERVAL_S", str(check_interval_s))
        )
        self._stall_threshold = float(
            os.getenv("MERID_LOOP_LAG_STALL_THRESHOLD_S", str(stall_threshold_s))
        )
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._current_lag_s: float = 0.0
        self._max_lag_s: float = 0.0
        self._stall_count: int = 0
        self._last_stall_ts: Optional[float] = None
        self._last_stall_duration_s: float = 0.0

    async def _monitor_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while self._running:
            t0 = loop.time()
            try:
                await asyncio.sleep(self._check_interval)
            except asyncio.CancelledError:
                break
            t1 = loop.time()
            elapsed = t1 - t0
            lag = max(0.0, elapsed - self._check_interval)
            self._current_lag_s = lag
            if lag > self._max_lag_s:
                self._max_lag_s = lag
            if lag >= self._stall_threshold:
                self._stall_count += 1
                self._last_stall_ts = time.time()
                self._last_stall_duration_s = lag
                logger.warning(
                    "[EVENT-LOOP-STALL] Asyncio event loop starved for %.3fs "
                    "(lag=%.3fs threshold=%.1fs total_stalls=%d)",
                    elapsed,
                    lag,
                    self._stall_threshold,
                    self._stall_count,
                )

    def start(self) -> "EventLoopLagMonitor":
        if not self._running:
            self._running = True
            try:
                self._task = asyncio.create_task(
                    self._monitor_loop(), name="event-loop-lag-monitor"
                )
            except RuntimeError:
                logger.debug("[EVENT-LOOP-MONITOR] No running event loop to attach to")
        return self

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    @property
    def current_lag_s(self) -> float:
        return self._current_lag_s

    @property
    def max_lag_s(self) -> float:
        return self._max_lag_s

    @property
    def stall_count(self) -> int:
        return self._stall_count

    def get_stats(self) -> Dict[str, Any]:
        return {
            "current_lag_ms": round(self._current_lag_s * 1000, 2),
            "max_lag_ms": round(self._max_lag_s * 1000, 2),
            "stall_count": self._stall_count,
            "last_stall_ts": self._last_stall_ts,
            "last_stall_duration_s": round(self._last_stall_duration_s, 3),
            "healthy": self._current_lag_s < self._stall_threshold,
        }
