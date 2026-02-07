"""
BaseStream - Canonical stream interface per MASTER_SPEC v1.0

This module defines the foundational interface for ALL data streams in MERID.
Every stream MUST inherit from BaseStream and emit EventEnvelope objects only.

Key guarantees:
- Backpressure handling with configurable buffer limits
- Health reporting with heartbeat monitoring
- Deterministic emit semantics (no silent drops)
- Explicit failure modes with typed exceptions
- Never talks directly to agents
- Never mutates external state directly

Reference: MASTER_SPEC.md Section 3 (Layer 1: Data Ingestion)
"""

from __future__ import annotations

import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    AsyncIterator,
    Callable,
    Deque,
    Dict,
    List,
    Optional,
    Set,
)

from core.events import EventEnvelope, EventType, EventPriority
from utils.logger import get_logger


class StreamState(Enum):
    """Stream lifecycle states."""
    
    INITIALIZING = "initializing"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    STREAMING = "streaming"
    PAUSED = "paused"
    RECONNECTING = "reconnecting"
    BACKPRESSURE = "backpressure"
    ERROR = "error"
    STOPPED = "stopped"


class BackpressurePolicy(Enum):
    """Policy for handling backpressure when buffer is full."""
    
    DROP_OLDEST = "drop_oldest"
    DROP_NEWEST = "drop_newest"
    BLOCK = "block"
    RAISE = "raise"


class StreamError(Exception):
    """Base exception for stream errors."""
    
    def __init__(self, stream_id: str, message: str) -> None:
        self.stream_id = stream_id
        self.message = message
        super().__init__(f"[{stream_id}] {message}")


class ConnectionError(StreamError):
    """Raised when stream cannot connect to data source."""
    pass


class BackpressureError(StreamError):
    """Raised when backpressure policy is RAISE and buffer is full."""
    pass


class EmitError(StreamError):
    """Raised when event emission fails."""
    pass


@dataclass
class StreamConfig:
    """Configuration for stream behavior."""
    
    buffer_size: int = 1000
    backpressure_policy: BackpressurePolicy = BackpressurePolicy.DROP_OLDEST
    
    reconnect_attempts: int = 5
    reconnect_delay_seconds: float = 1.0
    reconnect_backoff_multiplier: float = 2.0
    reconnect_max_delay_seconds: float = 60.0
    
    heartbeat_interval_seconds: float = 10.0
    health_check_interval_seconds: float = 30.0
    
    batch_size: int = 100
    batch_timeout_seconds: float = 1.0
    
    dedup_window_seconds: float = 5.0
    dedup_enabled: bool = True


@dataclass
class StreamHealth:
    """Stream health status for monitoring."""
    
    stream_id: str
    stream_type: str
    state: StreamState
    
    last_heartbeat: float
    last_event_at: Optional[float]
    uptime_seconds: float
    
    events_emitted: int
    events_dropped: int
    events_deduplicated: int
    errors_count: int
    
    buffer_size: int
    buffer_used: int
    buffer_utilization: float
    
    reconnect_count: int
    last_error: Optional[str]
    
    def is_healthy(self, max_heartbeat_age_seconds: float = 60.0) -> bool:
        """Check if stream is considered healthy."""
        if self.state in (StreamState.ERROR, StreamState.STOPPED):
            return False
        heartbeat_age = time.time() - self.last_heartbeat
        if heartbeat_age > max_heartbeat_age_seconds:
            return False
        return True
    
    def to_dict(self) -> Dict[str, object]:
        """Serialize to dictionary."""
        return {
            "stream_id": self.stream_id,
            "stream_type": self.stream_type,
            "state": self.state.value,
            "last_heartbeat": self.last_heartbeat,
            "last_event_at": self.last_event_at,
            "uptime_seconds": self.uptime_seconds,
            "events_emitted": self.events_emitted,
            "events_dropped": self.events_dropped,
            "events_deduplicated": self.events_deduplicated,
            "errors_count": self.errors_count,
            "buffer_size": self.buffer_size,
            "buffer_used": self.buffer_used,
            "buffer_utilization": self.buffer_utilization,
            "reconnect_count": self.reconnect_count,
            "last_error": self.last_error,
            "is_healthy": self.is_healthy(),
        }


class BaseStream(ABC):
    """
    Abstract base class for all MERID data streams.
    
    All streams MUST:
    - Emit EventEnvelope objects only
    - Handle backpressure explicitly
    - Report health status
    - Support graceful shutdown
    - Never talk directly to agents
    - Never mutate external state
    
    Subclasses MUST implement:
    - stream_type property
    - _connect() method
    - _disconnect() method
    - _fetch_data() method
    - _transform_to_events() method
    """
    
    def __init__(
        self,
        stream_id: str,
        config: Optional[StreamConfig] = None,
    ) -> None:
        """
        Initialize stream.
        
        Args:
            stream_id: Unique identifier for this stream instance
            config: Optional configuration override
        """
        if not stream_id:
            raise ValueError("stream_id cannot be empty")
        
        self._stream_id = stream_id
        self._config = config or StreamConfig()
        self._state = StreamState.INITIALIZING
        self._start_time: Optional[float] = None
        self._last_heartbeat = time.time()
        self._last_event_at: Optional[float] = None
        
        self._events_emitted = 0
        self._events_dropped = 0
        self._events_deduplicated = 0
        self._errors_count = 0
        self._reconnect_count = 0
        self._last_error: Optional[str] = None
        
        self._buffer: Deque[EventEnvelope] = deque(maxlen=self._config.buffer_size)
        self._dedup_cache: Dict[str, float] = {}
        
        self._subscribers: List[Callable[[EventEnvelope], None]] = []
        self._async_subscribers: List[Callable[[EventEnvelope], asyncio.Future[None]]] = []
        
        self._running = False
        self._stream_task: Optional[asyncio.Task[None]] = None
        self._heartbeat_task: Optional[asyncio.Task[None]] = None
        
        self._logger = get_logger(f"streams.{stream_id}")
    
    @property
    def stream_id(self) -> str:
        """Unique identifier for this stream."""
        return self._stream_id
    
    @property
    @abstractmethod
    def stream_type(self) -> str:
        """Type identifier for this stream (e.g., 'market', 'news')."""
        raise NotImplementedError
    
    @property
    def state(self) -> StreamState:
        """Current stream state."""
        return self._state
    
    @property
    def is_running(self) -> bool:
        """Check if stream is currently running."""
        return self._running and self._state in (
            StreamState.CONNECTED,
            StreamState.STREAMING,
            StreamState.RECONNECTING,
            StreamState.BACKPRESSURE,
        )
    
    def get_health(self) -> StreamHealth:
        """Get current health status."""
        buffer_used = len(self._buffer)
        buffer_utilization = (
            buffer_used / self._config.buffer_size
            if self._config.buffer_size > 0 else 0.0
        )
        
        uptime = (
            time.time() - self._start_time
            if self._start_time else 0.0
        )
        
        return StreamHealth(
            stream_id=self._stream_id,
            stream_type=self.stream_type,
            state=self._state,
            last_heartbeat=self._last_heartbeat,
            last_event_at=self._last_event_at,
            uptime_seconds=uptime,
            events_emitted=self._events_emitted,
            events_dropped=self._events_dropped,
            events_deduplicated=self._events_deduplicated,
            errors_count=self._errors_count,
            buffer_size=self._config.buffer_size,
            buffer_used=buffer_used,
            buffer_utilization=buffer_utilization,
            reconnect_count=self._reconnect_count,
            last_error=self._last_error,
        )
    
    def subscribe(self, callback: Callable[[EventEnvelope], None]) -> None:
        """
        Subscribe to events from this stream.
        
        Args:
            callback: Synchronous callback function
        """
        if callback not in self._subscribers:
            self._subscribers.append(callback)
            self._logger.debug("Added subscriber: %s", callback.__name__)
    
    def subscribe_async(
        self,
        callback: Callable[[EventEnvelope], asyncio.Future[None]],
    ) -> None:
        """
        Subscribe to events with async callback.
        
        Args:
            callback: Async callback function
        """
        if callback not in self._async_subscribers:
            self._async_subscribers.append(callback)
            self._logger.debug("Added async subscriber: %s", callback.__name__)
    
    def unsubscribe(self, callback: Callable[[EventEnvelope], None]) -> None:
        """Remove a subscriber."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)
    
    async def start(self) -> None:
        """
        Start the stream.
        
        Connects to data source and begins streaming events.
        """
        if self._running:
            self._logger.warning("Stream already running")
            return
        
        self._running = True
        self._start_time = time.time()
        self._state = StreamState.CONNECTING
        
        try:
            await self._connect()
            self._state = StreamState.CONNECTED
            self._logger.info("Stream connected: %s", self._stream_id)
        except Exception as e:
            self._state = StreamState.ERROR
            self._last_error = str(e)
            self._errors_count += 1
            self._logger.error("Connection failed: %s", e)
            raise ConnectionError(self._stream_id, str(e)) from e
        
        self._stream_task = asyncio.create_task(self._stream_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        
        self._state = StreamState.STREAMING
        self._logger.info("Stream started: %s", self._stream_id)
    
    async def stop(self) -> None:
        """
        Stop the stream gracefully.
        
        Disconnects from data source and cleans up resources.
        """
        if not self._running:
            return
        
        self._running = False
        self._state = StreamState.STOPPED
        
        if self._stream_task:
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass
        
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        try:
            await self._disconnect()
        except Exception as e:
            self._logger.error("Disconnect error: %s", e)
        
        self._logger.info("Stream stopped: %s", self._stream_id)
    
    async def pause(self) -> None:
        """Pause event emission (data still buffered)."""
        if self._state == StreamState.STREAMING:
            self._state = StreamState.PAUSED
            self._logger.info("Stream paused: %s", self._stream_id)
    
    async def resume(self) -> None:
        """Resume event emission."""
        if self._state == StreamState.PAUSED:
            self._state = StreamState.STREAMING
            self._logger.info("Stream resumed: %s", self._stream_id)
    
    async def emit(self, event: EventEnvelope) -> bool:
        """
        Emit an event to all subscribers.
        
        Handles backpressure according to configured policy.
        
        Args:
            event: Event to emit
            
        Returns:
            True if event was emitted, False if dropped
            
        Raises:
            BackpressureError: If policy is RAISE and buffer is full
        """
        if not event.validate():
            self._logger.warning("Invalid event rejected: %s", event.event_id)
            return False
        
        if self._config.dedup_enabled:
            event_hash = event.compute_hash()
            now = time.time()
            
            if event_hash in self._dedup_cache:
                cache_time = self._dedup_cache[event_hash]
                if now - cache_time < self._config.dedup_window_seconds:
                    self._events_deduplicated += 1
                    self._logger.debug("Duplicate event filtered: %s", event.event_id)
                    return False
            
            self._dedup_cache[event_hash] = now
            self._cleanup_dedup_cache()
        
        if len(self._buffer) >= self._config.buffer_size:
            self._state = StreamState.BACKPRESSURE
            
            if self._config.backpressure_policy == BackpressurePolicy.DROP_OLDEST:
                dropped = self._buffer.popleft()
                self._events_dropped += 1
                self._logger.warning(
                    "Backpressure: dropped oldest event %s", dropped.event_id
                )
            elif self._config.backpressure_policy == BackpressurePolicy.DROP_NEWEST:
                self._events_dropped += 1
                self._logger.warning(
                    "Backpressure: dropped newest event %s", event.event_id
                )
                return False
            elif self._config.backpressure_policy == BackpressurePolicy.BLOCK:
                while len(self._buffer) >= self._config.buffer_size:
                    await asyncio.sleep(0.01)
            elif self._config.backpressure_policy == BackpressurePolicy.RAISE:
                raise BackpressureError(
                    self._stream_id,
                    f"Buffer full ({len(self._buffer)}/{self._config.buffer_size})"
                )
        
        self._buffer.append(event)
        self._last_event_at = time.time()
        
        await self._notify_subscribers(event)
        
        self._events_emitted += 1
        
        if self._state == StreamState.BACKPRESSURE:
            if len(self._buffer) < self._config.buffer_size * 0.8:
                self._state = StreamState.STREAMING
        
        return True
    
    async def _notify_subscribers(self, event: EventEnvelope) -> None:
        """Notify all subscribers of new event."""
        for callback in self._subscribers:
            try:
                callback(event)
            except Exception as e:
                self._logger.error("Subscriber error: %s", e)
        
        for async_callback in self._async_subscribers:
            try:
                await async_callback(event)
            except Exception as e:
                self._logger.error("Async subscriber error: %s", e)
    
    async def _stream_loop(self) -> None:
        """Main streaming loop."""
        reconnect_delay = self._config.reconnect_delay_seconds
        
        while self._running:
            try:
                if self._state == StreamState.PAUSED:
                    await asyncio.sleep(0.1)
                    continue
                
                data = await self._fetch_data()
                
                if data is not None:
                    events = self._transform_to_events(data)
                    for event in events:
                        await self.emit(event)
                
                reconnect_delay = self._config.reconnect_delay_seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._errors_count += 1
                self._last_error = str(e)
                self._logger.error("Stream error: %s", e)
                
                if self._running:
                    self._state = StreamState.RECONNECTING
                    self._reconnect_count += 1
                    
                    self._logger.info(
                        "Reconnecting in %.1f seconds (attempt %d/%d)",
                        reconnect_delay,
                        self._reconnect_count,
                        self._config.reconnect_attempts,
                    )
                    
                    await asyncio.sleep(reconnect_delay)
                    
                    reconnect_delay = min(
                        reconnect_delay * self._config.reconnect_backoff_multiplier,
                        self._config.reconnect_max_delay_seconds,
                    )
                    
                    if self._reconnect_count >= self._config.reconnect_attempts:
                        self._state = StreamState.ERROR
                        self._logger.error(
                            "Max reconnect attempts reached, stopping stream"
                        )
                        break
                    
                    try:
                        await self._connect()
                        self._state = StreamState.STREAMING
                        self._logger.info("Reconnected successfully")
                    except Exception as reconnect_error:
                        self._logger.error("Reconnect failed: %s", reconnect_error)
    
    async def _heartbeat_loop(self) -> None:
        """Heartbeat loop for health monitoring."""
        while self._running:
            try:
                self._last_heartbeat = time.time()
                await asyncio.sleep(self._config.heartbeat_interval_seconds)
            except asyncio.CancelledError:
                break
    
    def _cleanup_dedup_cache(self) -> None:
        """Remove expired entries from dedup cache."""
        now = time.time()
        cutoff = now - self._config.dedup_window_seconds
        expired = [k for k, v in self._dedup_cache.items() if v < cutoff]
        for key in expired:
            del self._dedup_cache[key]
    
    @abstractmethod
    async def _connect(self) -> None:
        """
        Connect to data source.
        
        Must be implemented by subclasses.
        Should establish connection and validate it's working.
        
        Raises:
            ConnectionError: If connection fails
        """
        raise NotImplementedError
    
    @abstractmethod
    async def _disconnect(self) -> None:
        """
        Disconnect from data source.
        
        Must be implemented by subclasses.
        Should clean up all connection resources.
        """
        raise NotImplementedError
    
    @abstractmethod
    async def _fetch_data(self) -> Optional[object]:
        """
        Fetch next batch of data from source.
        
        Must be implemented by subclasses.
        Should return raw data or None if no data available.
        
        Returns:
            Raw data from source, or None
        """
        raise NotImplementedError
    
    @abstractmethod
    def _transform_to_events(self, data: object) -> List[EventEnvelope]:
        """
        Transform raw data to EventEnvelope objects.
        
        Must be implemented by subclasses.
        Should convert source-specific data to canonical events.
        
        Args:
            data: Raw data from _fetch_data()
            
        Returns:
            List of EventEnvelope objects
        """
        raise NotImplementedError
    
    async def __aenter__(self) -> BaseStream:
        """Async context manager entry."""
        await self.start()
        return self
    
    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[object],
    ) -> None:
        """Async context manager exit."""
        await self.stop()
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self._stream_id} state={self._state.value}>"


class StreamRegistry:
    """
    Registry for managing multiple streams.
    
    Provides centralized health monitoring and lifecycle management.
    """
    
    def __init__(self) -> None:
        self._streams: Dict[str, BaseStream] = {}
        self._logger = get_logger("streams.registry")
    
    def register(self, stream: BaseStream) -> None:
        """Register a stream."""
        if stream.stream_id in self._streams:
            raise ValueError(f"Stream {stream.stream_id} already registered")
        self._streams[stream.stream_id] = stream
        self._logger.info("Registered stream: %s", stream.stream_id)
    
    def unregister(self, stream_id: str) -> Optional[BaseStream]:
        """Unregister a stream."""
        stream = self._streams.pop(stream_id, None)
        if stream:
            self._logger.info("Unregistered stream: %s", stream_id)
        return stream
    
    def get(self, stream_id: str) -> Optional[BaseStream]:
        """Get a stream by ID."""
        return self._streams.get(stream_id)
    
    def get_all(self) -> List[BaseStream]:
        """Get all registered streams."""
        return list(self._streams.values())
    
    def get_health_report(self) -> Dict[str, StreamHealth]:
        """Get health report for all streams."""
        return {
            stream_id: stream.get_health()
            for stream_id, stream in self._streams.items()
        }
    
    async def start_all(self) -> None:
        """Start all registered streams."""
        for stream in self._streams.values():
            try:
                await stream.start()
            except Exception as e:
                self._logger.error("Failed to start %s: %s", stream.stream_id, e)
    
    async def stop_all(self) -> None:
        """Stop all registered streams."""
        for stream in self._streams.values():
            try:
                await stream.stop()
            except Exception as e:
                self._logger.error("Failed to stop %s: %s", stream.stream_id, e)


_stream_registry: Optional[StreamRegistry] = None


def get_stream_registry() -> StreamRegistry:
    """Get or create global stream registry singleton."""
    global _stream_registry
    if _stream_registry is None:
        _stream_registry = StreamRegistry()
    return _stream_registry
