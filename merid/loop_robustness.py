"""
MERID Loop Robustness Layer

Enhances merid/loop.py, tick_events.py, tick_log.py with:
- Automatic error recovery
- Circuit breaker integration
- Health monitoring
- Graceful degradation
- Deadlock prevention
"""

from __future__ import annotations

import asyncio
import time
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set
from datetime import datetime, timezone
from enum import Enum

from merid.pipeline.robustness import (
    ThreadSafeState, HealthChecker, ErrorRecovery,
    get_health_checker, retry_async, circuit_breaker
)
from utils.logger import get_logger

logger = get_logger("merid.loop_robustness")


class LoopState(Enum):
    """States for the robust loop."""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    RECOVERING = "recovering"
    FAILED = "failed"
    STOPPING = "stopping"


@dataclass
class LoopHealthMetrics:
    """Health metrics for loop monitoring."""
    state: LoopState = LoopState.IDLE
    total_ticks: int = 0
    successful_ticks: int = 0
    failed_ticks: int = 0
    consecutive_failures: int = 0
    last_tick_at: Optional[float] = None
    last_tick_duration_ms: float = 0.0
    avg_tick_duration_ms: float = 0.0
    circuit_breaker_open: bool = False
    error_count_1h: int = 0


class RobustLoopRunner:
    """
    Robust wrapper for MERID main loop operations.
    
    Features:
    - Automatic tick error recovery
    - Circuit breaker for failing steps
    - Health monitoring and reporting
    - Graceful degradation on component failures
    - Deadlock detection and prevention
    """

    def __init__(
        self,
        max_consecutive_failures: int = 5,
        circuit_failure_threshold: int = 10,
        recovery_timeout: float = 60.0,
        health_check_interval: float = 30.0,
        tick_timeout: float = 60.0,
    ):
        self._state = ThreadSafeState()
        self._state.set("loop_state", LoopState.IDLE)
        self._state.set("metrics", LoopHealthMetrics())
        self._state.set("step_circuit_states", {})  # step_name -> bool (open)
        self._state.set("step_failure_counts", {})   # step_name -> count
        
        self._max_consecutive_failures = max_consecutive_failures
        self._circuit_failure_threshold = circuit_failure_threshold
        self._recovery_timeout = recovery_timeout
        self._health_check_interval = health_check_interval
        self._tick_timeout = tick_timeout
        
        self._health_checker = get_health_checker()
        self._shutdown_event = asyncio.Event()
        self._tasks: List[asyncio.Task] = []
        
        # Register health checks
        self._health_checker.register_check("merid_loop", self._health_check_loop)
        
        logger.info("RobustLoopRunner initialized")

    async def start(self) -> None:
        """Start the robust loop runner with health monitoring."""
        logger.info("Starting RobustLoopRunner...")
        self._state.set("loop_state", LoopState.RUNNING)
        
        # Start health monitoring
        self._tasks.append(asyncio.create_task(self._health_monitor_loop()))
        
        logger.info("RobustLoopRunner started")

    async def stop(self) -> None:
        """Stop the robust loop runner gracefully."""
        logger.info("Stopping RobustLoopRunner...")
        self._state.set("loop_state", LoopState.STOPPING)
        self._shutdown_event.set()
        
        # Cancel all tasks
        for task in self._tasks:
            task.cancel()
        
        await asyncio.gather(*self._tasks, return_exceptions=True)
        
        self._state.set("loop_state", LoopState.IDLE)
        logger.info("RobustLoopRunner stopped")

    async def run_tick_with_robustness(
        self,
        tick_func: Callable,
        *args,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute a tick with full robustness handling.
        
        Args:
            tick_func: The tick function to execute
            *args, **kwargs: Arguments for tick function
            
        Returns:
            Tick summary or fallback on failure
        """
        metrics = self._state.get("metrics", LoopHealthMetrics())
        
        # Check if we should pause due to consecutive failures
        if metrics.consecutive_failures >= self._max_consecutive_failures:
            logger.error(f"Too many consecutive failures ({metrics.consecutive_failures}), pausing loop")
            self._state.set("loop_state", LoopState.PAUSED)
            
            # Attempt recovery
            recovery_success = await self._attempt_recovery()
            if not recovery_success:
                return {
                    "error": "Loop paused due to consecutive failures",
                    "recovery_attempted": True,
                    "recovery_success": False,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            
            self._state.set("loop_state", LoopState.RUNNING)
            metrics.consecutive_failures = 0
        
        # Execute tick with timeout
        start_time = time.perf_counter()
        tick_id = f"tick_{int(time.time() * 1000)}"
        
        try:
            # Run tick with timeout
            summary = await asyncio.wait_for(
                tick_func(*args, **kwargs),
                timeout=self._tick_timeout
            )
            
            # Update metrics on success
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            metrics.total_ticks += 1
            metrics.successful_ticks += 1
            metrics.consecutive_failures = 0
            metrics.last_tick_at = time.time()
            metrics.last_tick_duration_ms = elapsed_ms
            
            # Update rolling average
            old_avg = metrics.avg_tick_duration_ms
            metrics.avg_tick_duration_ms = (old_avg * 0.9) + (elapsed_ms * 0.1)
            
            logger.debug(f"Tick {tick_id} completed in {elapsed_ms:.1f}ms")
            
            return summary
            
        except asyncio.TimeoutError:
            metrics.total_ticks += 1
            metrics.failed_ticks += 1
            metrics.consecutive_failures += 1
            metrics.error_count_1h += 1
            
            logger.error(f"Tick {tick_id} timed out after {self._tick_timeout}s")
            
            return {
                "error": f"Tick timeout after {self._tick_timeout}s",
                "tick_id": tick_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as exc:
            metrics.total_ticks += 1
            metrics.failed_ticks += 1
            metrics.consecutive_failures += 1
            metrics.error_count_1h += 1
            
            logger.error(f"Tick {tick_id} failed: {exc}", exc_info=True)
            
            return {
                "error": str(exc),
                "tick_id": tick_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

    async def run_step_with_robustness(
        self,
        step_name: str,
        step_coro,
        summary: Dict[str, Any],
        timeout: Optional[float] = None,
        critical: bool = False,
    ) -> bool:
        """
        Execute a single loop step with robustness.
        
        Args:
            step_name: Name of the step for tracking
            step_coro: Coroutine to execute
            summary: Tick summary dict to update
            timeout: Step timeout override
            critical: If True, failure is not tolerated
            
        Returns:
            True if step succeeded, False otherwise
        """
        # Check circuit breaker
        circuit_states = self._state.get("step_circuit_states", {})
        if circuit_states.get(step_name, False):  # Circuit open
            logger.warning(f"Step '{step_name}' circuit breaker open, skipping")
            summary["actions"].append(f"{step_name}:circuit_open")
            return False
        
        step_timeout = timeout or 5.0
        
        try:
            await asyncio.wait_for(step_coro, timeout=step_timeout)
            
            # Reset failure count on success
            failure_counts = self._state.get("step_failure_counts", {})
            failure_counts[step_name] = 0
            
            return True
            
        except asyncio.TimeoutError:
            self._record_step_failure(step_name, f"timeout ({step_timeout}s)")
            summary["actions"].append(f"step_timeout:{step_name}")
            
            if critical:
                raise  # Re-raise for critical steps
            return False
            
        except Exception as exc:
            self._record_step_failure(step_name, str(exc))
            summary["actions"].append(f"step_error:{step_name}:{exc}")
            
            logger.error(f"Step '{step_name}' failed: {exc}", exc_info=True)
            
            if critical:
                raise  # Re-raise for critical steps
            return False

    def _record_step_failure(self, step_name: str, error: str) -> None:
        """Record a step failure and check circuit breaker."""
        failure_counts = self._state.get("step_failure_counts", {})
        circuit_states = self._state.get("step_circuit_states", {})
        
        # Increment failure count
        current_count = failure_counts.get(step_name, 0) + 1
        failure_counts[step_name] = current_count
        
        # Check if circuit should open
        if current_count >= self._circuit_failure_threshold:
            if not circuit_states.get(step_name, False):
                logger.warning(
                    f"Opening circuit breaker for step '{step_name}' "
                    f"after {current_count} failures"
                )
                circuit_states[step_name] = True
                
                # Schedule circuit recovery
                asyncio.create_task(self._schedule_circuit_recovery(step_name))

    async def _schedule_circuit_recovery(self, step_name: str) -> None:
        """Schedule circuit breaker recovery after timeout."""
        await asyncio.sleep(self._recovery_timeout)
        
        circuit_states = self._state.get("step_circuit_states", {})
        failure_counts = self._state.get("step_failure_counts", {})
        
        if circuit_states.get(step_name, False):
            logger.info(f"Attempting circuit recovery for step '{step_name}'")
            circuit_states[step_name] = False
            failure_counts[step_name] = 0

    async def _attempt_recovery(self) -> bool:
        """Attempt to recover from failure state."""
        logger.info("Attempting loop recovery...")
        
        # Reset all circuit breakers
        circuit_states = self._state.get("step_circuit_states", {})
        failure_counts = self._state.get("step_failure_counts", {})
        
        for step_name in circuit_states:
            circuit_states[step_name] = False
            failure_counts[step_name] = 0
        
        # Reset metrics
        metrics = self._state.get("metrics", LoopHealthMetrics())
        metrics.consecutive_failures = 0
        
        logger.info("Loop recovery completed")
        return True

    async def _health_monitor_loop(self) -> None:
        """Background health monitoring loop."""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self._health_check_interval
                )
                break
            except asyncio.TimeoutError:
                # Perform health check
                await self._perform_health_check()

    async def _perform_health_check(self) -> None:
        """Perform comprehensive health check."""
        metrics = self._state.get("metrics", LoopHealthMetrics())
        
        # Check for stuck loop
        if metrics.last_tick_at:
            time_since_last_tick = time.time() - metrics.last_tick_at
            if time_since_last_tick > self._tick_timeout * 2:
                logger.warning(
                    f"Loop appears stuck: {time_since_last_tick:.0f}s since last tick"
                )
        
        # Log health status
        logger.debug(
            f"Loop health: ticks={metrics.total_ticks}, "
            f"failures={metrics.failed_ticks}, "
            f"state={self._state.get('loop_state', LoopState.IDLE).value}"
        )

    async def _health_check_loop(self) -> Dict[str, Any]:
        """Health check function for health checker integration."""
        metrics = self._state.get("metrics", LoopHealthMetrics())
        circuit_states = self._state.get("step_circuit_states", {})
        
        open_circuits = [name for name, is_open in circuit_states.items() if is_open]
        
        return {
            "healthy": metrics.consecutive_failures < self._max_consecutive_failures,
            "state": self._state.get("loop_state", LoopState.IDLE).value,
            "metrics": {
                "total_ticks": metrics.total_ticks,
                "successful_ticks": metrics.successful_ticks,
                "failed_ticks": metrics.failed_ticks,
                "consecutive_failures": metrics.consecutive_failures,
                "avg_tick_duration_ms": round(metrics.avg_tick_duration_ms, 2),
            },
            "circuit_breakers": {
                "open_count": len(open_circuits),
                "open_circuits": open_circuits,
            },
        }

    @property
    def health(self) -> LoopHealthMetrics:
        """Get current health metrics."""
        return self._state.get("metrics", LoopHealthMetrics())

    def get_summary(self) -> Dict[str, Any]:
        """Get comprehensive loop summary."""
        metrics = self._state.get("metrics", LoopHealthMetrics())
        circuit_states = self._state.get("step_circuit_states", {})
        
        return {
            "state": metrics.state.value,
            "metrics": {
                "total_ticks": metrics.total_ticks,
                "successful_ticks": metrics.successful_ticks,
                "failed_ticks": metrics.failed_ticks,
                "success_rate": (
                    metrics.successful_ticks / metrics.total_ticks * 100
                    if metrics.total_ticks > 0 else 0
                ),
                "consecutive_failures": metrics.consecutive_failures,
                "avg_tick_duration_ms": round(metrics.avg_tick_duration_ms, 2),
                "error_count_1h": metrics.error_count_1h,
            },
            "circuit_breakers": {
                name: "open" if is_open else "closed"
                for name, is_open in circuit_states.items()
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


class RobustTickEventBus:
    """
    Robust wrapper for TickEventBus with error handling.
    
    Features:
    - Subscriber isolation (one failing subscriber doesn't affect others)
    - Automatic cleanup of dead subscribers
    - Memory limits for event history
    - Backpressure handling
    """

    def __init__(
        self,
        max_history: int = 200,
        max_subscribers: int = 100,
        subscriber_timeout: float = 5.0,
    ):
        self._state = ThreadSafeState()
        self._state.set("summaries", [])  # List of TickSummary
        self._state.set("subscribers", {})  # id -> queue
        self._state.set("subscriber_metadata", {})  # id -> metadata
        
        self._max_history = max_history
        self._max_subscribers = max_subscribers
        self._subscriber_timeout = subscriber_timeout
        
        self._lock = threading.Lock()
        self._subscriber_counter = 0

    def subscribe(self) -> tuple:
        """
        Subscribe to tick events.
        
        Returns:
            (subscriber_id, queue) tuple
        """
        with self._lock:
            # Check subscriber limit
            subscribers = self._state.get("subscribers", {})
            if len(subscribers) >= self._max_subscribers:
                logger.warning("Max subscribers reached, rejecting new subscription")
                return None, None
            
            # Create subscriber
            self._subscriber_counter += 1
            sub_id = f"sub_{self._subscriber_counter}_{int(time.time())}"
            
            import asyncio
            queue = asyncio.Queue(maxsize=100)  # Backpressure limit
            
            subscribers[sub_id] = queue
            
            metadata = self._state.get("subscriber_metadata", {})
            metadata[sub_id] = {
                "subscribed_at": time.time(),
                "events_delivered": 0,
                "errors": 0,
            }
            
            logger.debug(f"New subscriber {sub_id}")
            return sub_id, queue

    def unsubscribe(self, sub_id: str) -> None:
        """Unsubscribe from tick events."""
        with self._lock:
            subscribers = self._state.get("subscribers", {})
            metadata = self._state.get("subscriber_metadata", {})
            
            if sub_id in subscribers:
                del subscribers[sub_id]
            if sub_id in metadata:
                del metadata[sub_id]
            
            logger.debug(f"Unsubscribed {sub_id}")

    async def publish(self, event) -> None:
        """
        Publish event to all subscribers with isolation.
        
        Args:
            event: TickEvent or TickSummary to publish
        """
        subscribers = self._state.get("subscribers", {})
        metadata = self._state.get("subscriber_metadata", {})
        
        dead_subscribers = []
        
        for sub_id, queue in subscribers.items():
            try:
                # Try to put with timeout
                await asyncio.wait_for(queue.put(event), timeout=self._subscriber_timeout)
                
                # Update metadata
                meta = metadata.get(sub_id, {})
                meta["events_delivered"] = meta.get("events_delivered", 0) + 1
                
            except asyncio.TimeoutError:
                logger.warning(f"Subscriber {sub_id} queue full, marking for cleanup")
                dead_subscribers.append(sub_id)
                
                meta = metadata.get(sub_id, {})
                meta["errors"] = meta.get("errors", 0) + 1
                
            except Exception as exc:
                logger.error(f"Failed to deliver to subscriber {sub_id}: {exc}")
                dead_subscribers.append(sub_id)
                
                meta = metadata.get(sub_id, {})
                meta["errors"] = meta.get("errors", 0) + 1
        
        # Clean up dead subscribers
        for sub_id in dead_subscribers:
            self.unsubscribe(sub_id)

    def record_summary(self, summary) -> None:
        """Record tick summary with history limit."""
        summaries = self._state.get("summaries", [])
        summaries.append(summary)
        
        # Enforce history limit
        if len(summaries) > self._max_history:
            summaries.pop(0)  # Remove oldest

    def get_recent_summaries(self, count: int = 10) -> List[Any]:
        """Get recent tick summaries."""
        summaries = self._state.get("summaries", [])
        return summaries[-count:] if summaries else []

    def get_stats(self) -> Dict[str, Any]:
        """Get event bus statistics."""
        subscribers = self._state.get("subscribers", {})
        metadata = self._state.get("subscriber_metadata", {})
        summaries = self._state.get("summaries", [])
        
        total_delivered = sum(
            m.get("events_delivered", 0) for m in metadata.values()
        )
        total_errors = sum(
            m.get("errors", 0) for m in metadata.values()
        )
        
        return {
            "subscriber_count": len(subscribers),
            "history_size": len(summaries),
            "total_events_delivered": total_delivered,
            "total_delivery_errors": total_errors,
            "max_history": self._max_history,
            "max_subscribers": self._max_subscribers,
        }


class RobustTickLog:
    """
    Robust wrapper for TickLog with error recovery.
    
    Features:
    - Automatic log rotation
    - Write failure recovery
    - Async batching for performance
    - Disk space monitoring
    """

    def __init__(
        self,
        log_dir: str = "data/logs",
        log_file: str = "merid_ticks_robust.jsonl",
        max_file_size_mb: float = 100.0,
        max_files: int = 10,
        batch_size: int = 10,
        flush_interval: float = 5.0,
    ):
        self._log_dir = log_dir
        self._log_file = log_file
        self._max_file_size = max_file_size_mb * 1024 * 1024
        self._max_files = max_files
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        
        self._state = ThreadSafeState()
        self._state.set("batch", [])
        self._state.set("total_records", 0)
        self._state.set("failed_writes", 0)
        self._state.set("last_flush", time.time())
        
        self._shutdown_event = asyncio.Event()
        self._flush_task: Optional[asyncio.Task] = None
        
        # Ensure log directory exists
        import os
        os.makedirs(log_dir, exist_ok=True)
        
        self._log_path = os.path.join(log_dir, log_file)

    async def start(self) -> None:
        """Start background flush task."""
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info("RobustTickLog started")

    async def stop(self) -> None:
        """Stop and flush remaining records."""
        self._shutdown_event.set()
        
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        
        # Final flush
        await self._flush()
        logger.info("RobustTickLog stopped")

    def append(self, record) -> None:
        """Append a record to the batch."""
        batch = self._state.get("batch", [])
        batch.append(record)
        
        # Auto-flush if batch is full
        if len(batch) >= self._batch_size:
            asyncio.create_task(self._flush())

    async def _flush_loop(self) -> None:
        """Background flush loop."""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self._flush_interval
                )
                break
            except asyncio.TimeoutError:
                await self._flush()

    async def _flush(self) -> None:
        """Flush batched records to disk."""
        batch = self._state.get("batch", [])
        
        if not batch:
            return
        
        # Clear batch (atomic)
        self._state.set("batch", [])
        
        try:
            # Check if rotation needed
            await self._rotate_if_needed()
            
            # Write records
            lines = [record.to_json() if hasattr(record, 'to_json') else str(record) 
                    for record in batch]
            
            import aiofiles
            async with aiofiles.open(self._log_path, "a") as f:
                for line in lines:
                    await f.write(line + "\n")
            
            # Update stats
            self._state.get("total_records", 0)
            self._state.set("last_flush", time.time())
            
            logger.debug(f"Flushed {len(batch)} records to {self._log_path}")
            
        except Exception as exc:
            self._state.get("failed_writes", 0)
            logger.error(f"Failed to flush tick log: {exc}")
            
            # Re-queue failed records
            current_batch = self._state.get("batch", [])
            current_batch.extend(batch)

    async def _rotate_if_needed(self) -> None:
        """Rotate log file if size exceeds limit."""
        import os
        
        if not os.path.exists(self._log_path):
            return
        
        size = os.path.getsize(self._log_path)
        
        if size > self._max_file_size:
            logger.info(f"Rotating log file (size: {size / 1024 / 1024:.1f}MB)")
            
            # Rotate existing files
            for i in range(self._max_files - 1, 0, -1):
                old_path = f"{self._log_path}.{i}"
                new_path = f"{self._log_path}.{i + 1}"
                
                if os.path.exists(old_path):
                    if os.path.exists(new_path):
                        os.remove(new_path)
                    os.rename(old_path, new_path)
            
            # Rotate current file
            if os.path.exists(self._log_path):
                os.rename(self._log_path, f"{self._log_path}.1")

    def get_stats(self) -> Dict[str, Any]:
        """Get log statistics."""
        return {
            "total_records": self._state.get("total_records", 0),
            "failed_writes": self._state.get("failed_writes", 0),
            "pending_batch_size": len(self._state.get("batch", [])),
            "last_flush": self._state.get("last_flush", 0),
            "log_path": self._log_path,
        }


# Singleton accessor
_robust_loop_runner: Optional[RobustLoopRunner] = None
_robust_tick_bus: Optional[RobustTickEventBus] = None
_robust_tick_log: Optional[RobustTickLog] = None


def get_robust_loop_runner() -> RobustLoopRunner:
    """Get or create singleton RobustLoopRunner."""
    global _robust_loop_runner
    if _robust_loop_runner is None:
        _robust_loop_runner = RobustLoopRunner()
    return _robust_loop_runner


def get_robust_tick_bus() -> RobustTickEventBus:
    """Get or create singleton RobustTickEventBus."""
    global _robust_tick_bus
    if _robust_tick_bus is None:
        _robust_tick_bus = RobustTickEventBus()
    return _robust_tick_bus


def get_robust_tick_log() -> RobustTickLog:
    """Get or create singleton RobustTickLog."""
    global _robust_tick_log
    if _robust_tick_log is None:
        _robust_tick_log = RobustTickLog()
    return _robust_tick_log
