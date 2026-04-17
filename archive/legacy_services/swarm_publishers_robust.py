"""
Enhanced Swarm Publishers with Robustness Features

Critical fixes for swarm publishing components to address:
- Error handling and retry logic
- Circuit breaking for WebSocket connections
- Graceful shutdown handling
- Resource management
- Health checks and monitoring
- Rate limiting and backpressure
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, timezone

from observability.event_stream import get_event_stream, EventRecord
from observability.swarm_telemetry import get_swarm_telemetry
from agents.watchdog_agents import get_watchdog_coordinator
from utils.logger import get_logger
from merid.pipeline.robustness import (
    retry_async, circuit_breaker, rate_limit, ThreadSafeState,
    ResourceManager, HealthChecker, PipelineMetrics, GracefulShutdown,
    ErrorRecovery, get_health_checker, get_metrics, get_shutdown_handler
)

logger = get_logger("web.swarm_publishers_robust")


# ── Enhanced Event Publisher with Robustness ─────────────────────────────────

@dataclass
class PublisherConfig:
    """Configuration for swarm event publisher."""
    max_queue_size: int = 1000
    batch_size: int = 10
    batch_timeout: float = 1.0
    max_retries: int = 3
    retry_delay: float = 1.0
    health_check_interval: float = 30.0
    backpressure_threshold: float = 0.8


class SwarmEventPublisherRobust:
    """
    Enhanced swarm event publisher with comprehensive robustness features.
    
    Key improvements:
    - Error handling with retry logic and circuit breaking
    - Backpressure handling and queue management
    - Graceful shutdown handling
    - Health checks and metrics
    - Resource management
    - Rate limiting
    """

    def __init__(self, config: Optional[PublisherConfig] = None):
        self.config = config or PublisherConfig()
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self._resource_manager = ResourceManager()
        self._shutdown_handler = get_shutdown_handler()
        self._metrics = get_metrics()
        self._health_checker = get_health_checker()
        
        # Thread-safe state management
        self._state = ThreadSafeState()
        self._state.set("event_queue", asyncio.Queue(maxsize=self.config.max_queue_size))
        self._state.set("websocket_connected", False)
        self._state.set("last_broadcast_time", 0.0)
        self._state.set("broadcast_count", 0)
        self._state.set("error_count", 0)
        self._state.set("active_consumers", set())

        # Event stream and telemetry
        self.event_stream = get_event_stream()
        self.telemetry = get_swarm_telemetry()
        
        # Register health checks
        self._health_checker.register_check("publisher_status", self._health_check_status)
        self._health_checker.register_check("websocket_health", self._health_check_websocket)
        self._health_checker.register_check("queue_health", self._health_check_queue)
        self._health_checker.register_check("event_stream_health", self._health_check_event_stream)

        # Register shutdown handler
        self._shutdown_handler.register_handler(self._cleanup_resources)

    async def start(self) -> None:
        """Start the enhanced publisher with error handling."""
        if self._running:
            logger.warning("SwarmEventPublisherRobust already running")
            return
        
        try:
            self._running = True
            logger.info("SwarmEventPublisherRobust starting with enhanced robustness")
            
            # Start event subscriber with retry logic
            event_task = asyncio.create_task(
                self._event_subscriber_robust(),
                name="swarm-event-subscriber"
            )
            self._tasks.append(event_task)
            self._resource_manager.register(event_task, lambda t: t.cancel())
            
            # Start telemetry publisher with retry logic
            telemetry_task = asyncio.create_task(
                self._telemetry_publisher_robust(),
                name="swarm-telemetry-publisher"
            )
            self._tasks.append(telemetry_task)
            self._resource_manager.register(telemetry_task, lambda t: t.cancel())
            
            # Start batch processor
            batch_task = asyncio.create_task(
                self._batch_processor_robust(),
                name="swarm-batch-processor"
            )
            self._tasks.append(batch_task)
            self._resource_manager.register(batch_task, lambda t: t.cancel())
            
            # Start health check monitor
            health_task = asyncio.create_task(
                self._health_check_monitor(),
                name="swarm-health-monitor"
            )
            self._tasks.append(health_task)
            self._resource_manager.register(health_task, lambda t: t.cancel())
            
            logger.info(f"SwarmEventPublisherRobust started with {len(self._tasks)} tasks")
            
        except Exception as exc:
            logger.error(f"Failed to start SwarmEventPublisherRobust: {exc}")
            await self.stop()
            raise

    async def stop(self) -> None:
        """Stop the publisher gracefully."""
        if not self._running:
            return
        
        logger.info("Stopping SwarmEventPublisherRobust...")
        self._running = False
        
        # Cancel all tasks
        for task in self._tasks:
            task.cancel()
        
        # Wait for tasks to complete with timeout
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._tasks, return_exceptions=True),
                timeout=30.0
            )
        except asyncio.TimeoutError:
            logger.warning("Some tasks didn't complete within timeout")
        
        self._tasks.clear()
        
        # Cleanup resources
        await self._resource_manager.cleanup_all()
        
        logger.info("SwarmEventPublisherRobust stopped")

    # ── Enhanced Event Subscriber with Robustness ─────────────────────────────

    @retry_async(max_attempts=3, base_delay=1.0)
    @rate_limit(calls_per_second=100.0)  # Max 100 events per second
    async def _event_subscriber_robust(self) -> None:
        """Enhanced event subscriber with comprehensive error handling."""
        queue = self._state.get("event_queue")
        
        try:
            # Subscribe to event stream
            queue = await self.event_stream.subscribe()
            self._resource_manager.register(queue, lambda q: self.event_stream.unsubscribe(q))
            
            logger.info("Event subscriber started successfully")
            
            while self._running and not self._shutdown_handler.is_shutting_down():
                try:
                    # Get event with timeout and backpressure handling
                    event = await asyncio.wait_for(
                        queue.get(),
                        timeout=1.0
                    )
                    
                    # Check queue size for backpressure
                    if queue.qsize() > self.config.max_queue_size * self.config.backpressure_threshold:
                        logger.warning(f"Event queue backpressure: {queue.qsize()}/{self.config.max_queue_size}")
                        self._metrics.increment_counter("backpressure_events")
                    
                    # Filter and enqueue event
                    if self._should_publish_event(event):
                        await self._enqueue_event_with_backpressure(event)
                    
                    self._metrics.increment_counter("events_received")
                    
                except asyncio.TimeoutError:
                    # Expected timeout for shutdown check
                    continue
                except Exception as exc:
                    self._state.get("error_count", 0)
                    self._metrics.increment_counter("subscriber_errors")
                    logger.error(f"Event subscriber error: {exc}")
                    await asyncio.sleep(1.0)  # Brief pause before retry
        
        except Exception as exc:
            logger.error(f"Event subscriber failed: {exc}")
            raise
        finally:
            try:
                await self.event_stream.unsubscribe(queue)
            except Exception as exc:
                logger.debug(f"Error unsubscribing from event stream: {exc}")

    def _should_publish_event(self, event: EventRecord) -> bool:
        """Determine if event should be published."""
        return event.event_type in [
            "strategy_opinion",
            "consensus_decision",
            "trade_intent",
            "order_event",
            "agent_heartbeat",
            "watchdog_alert",
            "swarm_telemetry"
        ]

    async def _enqueue_event_with_backpressure(self, event: EventRecord) -> None:
        """Enqueue event with backpressure handling."""
        queue = self._state.get("event_queue")
        
        try:
            # Try to enqueue without blocking
            queue.put_nowait(event)
        except asyncio.QueueFull:
            # Queue is full, apply backpressure
            logger.warning(f"Event queue full, dropping event: {event.event_type}")
            self._metrics.increment_counter("dropped_events")
            
            # Try to make space by removing old events
            try:
                queue.get_nowait()  # Remove oldest event
                queue.put_nowait(event)  # Add new event
                self._metrics.increment_counter("backpressure_drops")
            except asyncio.QueueEmpty:
                pass

    # ── Enhanced Telemetry Publisher with Robustness ─────────────────────────

    @circuit_breaker(failure_threshold=3, recovery_timeout=30.0)
    @retry_async(max_attempts=3, base_delay=2.0)
    async def _telemetry_publisher_robust(self) -> None:
        """Enhanced telemetry publisher with circuit breaking."""
        logger.info("Telemetry publisher started")
        
        while self._running and not self._shutdown_handler.is_shutting_down():
            try:
                # Get telemetry stats with timeout
                stats = await ErrorRecovery.with_timeout(
                    self.telemetry.get_stats_dict,
                    timeout=5.0,
                    fallback_value={}
                )
                
                # Broadcast telemetry with error handling
                await ErrorRecovery.safe_execute(
                    self._broadcast_to_websocket_robust,
                    "swarm_telemetry",
                    stats,
                    log_error=True
                )
                
                self._metrics.increment_counter("telemetry_broadcasts")
                
                # Wait with shutdown check
                await asyncio.wait_for(
                    asyncio.sleep(5.0),
                    timeout=5.0
                )
                
            except asyncio.TimeoutError:
                continue  # Expected timeout for shutdown check
            except Exception as exc:
                self._state.get("error_count", 0)
                self._metrics.increment_counter("telemetry_errors")
                logger.error(f"Telemetry publisher error: {exc}")
                await asyncio.sleep(5.0)

    # ── Batch Processor for Efficient Broadcasting ─────────────────────────────

    async def _batch_processor_robust(self) -> None:
        """Process events in batches for efficient broadcasting."""
        queue = self._state.get("event_queue")
        batch = []
        
        while self._running and not self._shutdown_handler.is_shutting_down():
            try:
                # Collect batch
                try:
                    event = await asyncio.wait_for(
                        queue.get(),
                        timeout=self.config.batch_timeout
                    )
                    batch.append(event)
                except asyncio.TimeoutError:
                    # Timeout, process current batch
                    pass
                
                # Process batch if ready
                if (len(batch) >= self.config.batch_size or 
                    (batch and asyncio.get_event_loop().time() - self._state.get("last_broadcast_time", 0.0) > self.config.batch_timeout)):
                    
                    await self._process_event_batch(batch)
                    batch.clear()
                
            except Exception as exc:
                self._state.get("error_count", 0)
                self._metrics.increment_counter("batch_processor_errors")
                logger.error(f"Batch processor error: {exc}")
                batch.clear()  # Clear batch on error
                await asyncio.sleep(1.0)

    async def _process_event_batch(self, batch: List[EventRecord]) -> None:
        """Process a batch of events."""
        for event in batch:
            await ErrorRecovery.safe_execute(
                self._broadcast_to_websocket_robust,
                event.event_type,
                event.payload,
                log_error=False
            )
        
        self._state.set("last_broadcast_time", asyncio.get_event_loop().time())
        self._state.get("broadcast_count", 0)
        self._metrics.increment_counter("events_broadcast", len(batch))

    # ── Enhanced WebSocket Broadcasting with Robustness ───────────────────────

    @circuit_breaker(failure_threshold=5, recovery_timeout=60.0)
    @retry_async(max_attempts=3, base_delay=1.0)
    async def _broadcast_to_websocket_robust(
        self,
        event_type: str,
        payload: Dict[str, Any]
    ) -> None:
        """Enhanced WebSocket broadcasting with circuit breaking."""
        try:
            # Import here to avoid circular dependency
            from web.api.ws_events import broadcast_event
            
            # Validate inputs
            if not event_type or not isinstance(event_type, str):
                raise ValueError(f"Invalid event_type: {event_type}")
            
            if not payload or not isinstance(payload, dict):
                raise ValueError(f"Invalid payload: {payload}")
            
            # Broadcast with timeout
            await ErrorRecovery.with_timeout(
                broadcast_event,
                timeout=5.0,
                event_type=event_type,
                payload=payload,
                fallback_value=None
            )
            
            self._state.set("websocket_connected", True)
            self._metrics.increment_counter("websocket_broadcasts")
            
        except ImportError:
            # WebSocket module not available
            logger.debug("WebSocket module not available")
            self._state.set("websocket_connected", False)
        except Exception as exc:
            self._state.set("websocket_connected", False)
            self._metrics.increment_counter("websocket_errors")
            logger.debug(f"WebSocket broadcast error: {exc}")
            raise

    # ── Health Check Monitor ─────────────────────────────────────────────────────

    async def _health_check_monitor(self) -> None:
        """Monitor health checks and alert on issues."""
        while self._running and not self._shutdown_handler.is_shutting_down():
            try:
                # Run all health checks
                health_results = await self._health_checker.run_all_checks()
                
                # Check for unhealthy components
                unhealthy = [
                    name for name, status in health_results.items()
                    if not status.healthy
                ]
                
                if unhealthy:
                    logger.warning(f"Unhealthy components detected: {unhealthy}")
                    self._metrics.increment_counter("health_check_failures")
                
                # Update health status
                self._state.set("health_status", health_results)
                
                # Wait before next check
                await asyncio.wait_for(
                    asyncio.sleep(self.config.health_check_interval),
                    timeout=self.config.health_check_interval
                )
                
            except asyncio.TimeoutError:
                continue  # Expected timeout for shutdown check
            except Exception as exc:
                logger.error(f"Health check monitor error: {exc}")
                await asyncio.sleep(self.config.health_check_interval)

    # ── Health Check Implementations ─────────────────────────────────────────────

    async def _health_check_status(self) -> Dict[str, Any]:
        """Check publisher status health."""
        return {
            "running": self._running,
            "tasks_running": len([t for t in self._tasks if not t.done()]),
            "websocket_connected": self._state.get("websocket_connected", False),
            "broadcast_count": self._state.get("broadcast_count", 0),
            "error_count": self._state.get("error_count", 0),
            "uptime": time.time() - (self._state.get("start_time", time.time()))
        }

    async def _health_check_websocket(self) -> Dict[str, Any]:
        """Check WebSocket connection health."""
        try:
            # Try a test broadcast
            await self._broadcast_to_websocket_robust("health_check", {"test": True})
            return {
                "healthy": True,
                "last_broadcast": self._state.get("last_broadcast_time", 0.0)
            }
        except Exception as exc:
            return {
                "healthy": False,
                "error": str(exc),
                "last_broadcast": self._state.get("last_broadcast_time", 0.0)
            }

    async def _health_check_queue(self) -> Dict[str, Any]:
        """Check event queue health."""
        queue = self._state.get("event_queue")
        return {
            "healthy": queue.qsize() < self.config.max_queue_size * 0.9,
            "queue_size": queue.qsize(),
            "max_size": self.config.max_queue_size,
            "utilization": queue.qsize() / self.config.max_queue_size
        }

    async def _health_check_event_stream(self) -> Dict[str, Any]:
        """Check event stream health."""
        try:
            # Try to get stream status
            stats = self.event_stream.get_stats()
            return {
                "healthy": True,
                "subscribers": stats.get("subscribers", 0),
                "events_processed": stats.get("events_processed", 0)
            }
        except Exception as exc:
            return {
                "healthy": False,
                "error": str(exc)
            }

    # ── Resource Cleanup ─────────────────────────────────────────────────────

    async def _cleanup_resources(self) -> None:
        """Clean up publisher resources."""
        logger.info("Cleaning up swarm publisher resources...")
        
        # Cancel all tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()
        
        # Clear state
        self._state.clear()
        
        logger.info("Swarm publisher resources cleaned up")

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive publisher stats."""
        queue = self._state.get("event_queue")
        
        return {
            "running": self._running,
            "config": {
                "max_queue_size": self.config.max_queue_size,
                "batch_size": self.config.batch_size,
                "batch_timeout": self.config.batch_timeout,
                "max_retries": self.config.max_retries
            },
            "queue": {
                "size": queue.qsize() if queue else 0,
                "max_size": self.config.max_queue_size,
                "utilization": (queue.qsize() / self.config.max_queue_size) if queue else 0
            },
            "websocket": {
                "connected": self._state.get("websocket_connected", False),
                "last_broadcast": self._state.get("last_broadcast_time", 0.0),
                "broadcast_count": self._state.get("broadcast_count", 0)
            },
            "errors": self._state.get("error_count", 0),
            "metrics": self._metrics.get_summary(),
            "health": self._health_checker.get_summary()
        }


# ── Singleton and Factory Functions ─────────────────────────────────────────────

_swarm_publisher_robust: Optional[SwarmEventPublisherRobust] = None
_swarm_publisher_lock = threading.Lock()


def get_swarm_publisher_robust(config: Optional[PublisherConfig] = None) -> SwarmEventPublisherRobust:
    """Get or create the robust swarm publisher singleton."""
    global _swarm_publisher_robust
    if _swarm_publisher_robust is None:
        with _swarm_publisher_lock:
            if _swarm_publisher_robust is None:
                _swarm_publisher_robust = SwarmEventPublisherRobust(config)
    return _swarm_publisher_robust


async def start_swarm_publishers_robust(config: Optional[PublisherConfig] = None) -> None:
    """Start all robust swarm event publishers."""
    publisher = get_swarm_publisher_robust(config)
    await publisher.start()
    logger.info("Robust swarm publishers started")


async def stop_swarm_publishers_robust() -> None:
    """Stop all robust swarm event publishers."""
    publisher = get_swarm_publisher_robust()
    await publisher.stop()
    logger.info("Robust swarm publishers stopped")


# ── Backward Compatibility ─────────────────────────────────────────────────────

# Legacy aliases for backward compatibility
SwarmEventPublisher = SwarmEventPublisherRobust
get_swarm_publisher = get_swarm_publisher_robust
start_swarm_publishers = start_swarm_publishers_robust
stop_swarm_publishers = stop_swarm_publishers_robust
