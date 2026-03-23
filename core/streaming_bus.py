"""
Production Event Bus - Typed pub/sub for continuous data streaming.

This is the backbone of MERID's streaming architecture.
All data flows through this bus to agent subscribers.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
from utils.logger import get_logger

logger = get_logger("core.streaming_bus")


class EventChannel(str, Enum):
    """Event channels for different data types."""
    MARKET_DATA = "market_data"
    NEWS = "news"
    SOCIAL = "social"
    ONCHAIN = "onchain"
    AGENT_OUTPUT = "agent_output"
    CONSENSUS = "consensus"
    EXECUTION = "execution"
    SIMULATION = "simulation"
    SYSTEM = "system"
    AUDIT = "audit"


@dataclass
class StreamEvent:
    """Typed event structure."""
    channel: EventChannel
    event_type: str
    data: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    source: str = "unknown"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "channel": self.channel.value,
            "event_type": self.event_type,
            "data": self.data,
            "timestamp": self.timestamp,
            "source": self.source
        }


class StreamingBus:
    """
    Production-grade event bus with typed channels.
    
    Features:
    - Multiple channels for different data types
    - Subscriber filtering by channel
    - Backpressure handling (drop old events if queue full)
    - Subscriber health monitoring
    - Event metrics
    """
    
    def __init__(self, max_queue_size: int = 500):
        self.max_queue_size = max_queue_size
        
        # Channel-specific subscribers
        self._subscribers: Dict[EventChannel, Set[asyncio.Queue]] = {
            channel: set() for channel in EventChannel
        }
        
        # Global subscribers (receive all events)
        self._global_subscribers: Set[asyncio.Queue] = set()
        
        self._lock = asyncio.Lock()
        
        # Metrics
        self._event_counts: Dict[EventChannel, int] = {
            channel: 0 for channel in EventChannel
        }
        self._dropped_events: int = 0
        self._dropped_by_channel: Dict[EventChannel, int] = {
            channel: 0 for channel in EventChannel
        }
        
    async def subscribe(
        self, 
        channels: Optional[List[EventChannel]] = None,
        global_sub: bool = False
    ) -> asyncio.Queue:
        """
        Subscribe to event channels.
        
        Args:
            channels: List of channels to subscribe to (None = all channels)
            global_sub: If True, receive all events regardless of channel
            
        Returns:
            Queue that will receive events
        """
        queue = asyncio.Queue(maxsize=self.max_queue_size)
        
        async with self._lock:
            if global_sub or channels is None:
                self._global_subscribers.add(queue)
                logger.info("New global subscriber added")
            else:
                for channel in channels:
                    self._subscribers[channel].add(queue)
                logger.info(f"New subscriber added to channels: {[c.value for c in channels]}")
        
        return queue
    
    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Remove subscriber from all channels."""
        async with self._lock:
            self._global_subscribers.discard(queue)
            for channel_subs in self._subscribers.values():
                channel_subs.discard(queue)
        logger.debug("Subscriber removed")
    
    async def publish(self, event: StreamEvent) -> int:
        """
        Publish event to subscribers.
        
        Returns:
            Number of subscribers that received the event
        """
        delivered = 0
        stale_queues: Set[asyncio.Queue] = set()
        
        async with self._lock:
            # Update metrics
            self._event_counts[event.channel] += 1
            
            # Get all relevant subscribers
            channel_subs = self._subscribers.get(event.channel, set())
            all_subs = channel_subs | self._global_subscribers
            
            # Deliver to subscribers
            for queue in all_subs:
                try:
                    if queue.full():
                        # Backpressure: drop oldest event
                        try:
                            queue.get_nowait()
                            self._dropped_events += 1
                            self._dropped_by_channel[event.channel] += 1
                        except asyncio.QueueEmpty:
                            pass
                    
                    queue.put_nowait(event)
                    delivered += 1
                    
                except (asyncio.QueueFull, asyncio.QueueEmpty, RuntimeError) as exc:
                    logger.warning(f"Failed to deliver event: {exc}")
                    stale_queues.add(queue)
            
            # Clean up stale subscribers
            for queue in stale_queues:
                self._global_subscribers.discard(queue)
                for channel_subs in self._subscribers.values():
                    channel_subs.discard(queue)
        
        return delivered
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get bus metrics."""
        total_subscribers = len(self._global_subscribers)
        for subs in self._subscribers.values():
            total_subscribers += len(subs)
        
        return {
            "total_subscribers": total_subscribers,
            "global_subscribers": len(self._global_subscribers),
            "channel_subscribers": {
                channel.value: len(subs) 
                for channel, subs in self._subscribers.items()
            },
            "event_counts": {
                channel.value: count 
                for channel, count in self._event_counts.items()
            },
            "dropped_events": self._dropped_events,
            "dropped_events_by_channel": {
                channel.value: count
                for channel, count in self._dropped_by_channel.items()
            },
        }
    
    def get_subscriber_count(self, channel: Optional[EventChannel] = None) -> int:
        """Get subscriber count for a channel or total."""
        if channel is None:
            total = len(self._global_subscribers)
            for subs in self._subscribers.values():
                total += len(subs)
            return total
        return len(self._subscribers.get(channel, set()))


# Global streaming bus instance
streaming_bus = StreamingBus()

# Subscriber ID to queue mapping for named subscribers
_subscriber_queues: Dict[str, asyncio.Queue] = {}
_subscriber_channels: Dict[str, List[EventChannel]] = {}


def get_event_bus() -> StreamingBus:
    """Get the global streaming bus instance."""
    return streaming_bus


async def subscribe_by_id(
    subscriber_id: str,
    channels: List[EventChannel],
    queue_size: int = 100
) -> None:
    """Subscribe with a named ID for later retrieval."""
    global _subscriber_queues, _subscriber_channels
    
    await streaming_bus.subscribe_named(subscriber_id, channels, queue_size)


async def unsubscribe_by_id(subscriber_id: str) -> None:
    """Unsubscribe a named subscriber."""
    global _subscriber_queues, _subscriber_channels
    
    if subscriber_id not in _subscriber_queues:
        return
    
    await streaming_bus.unsubscribe_named(subscriber_id)


async def get_event_by_id(subscriber_id: str) -> Optional[StreamEvent]:
    """Get next event for a named subscriber."""
    if subscriber_id not in _subscriber_queues:
        return None
    
    queue = _subscriber_queues[subscriber_id]
    try:
        return await queue.get()
    except (asyncio.CancelledError, asyncio.QueueEmpty):
        return None


# Instance-level named subscriber helpers
async def _subscribe_named(self, subscriber_id: str, channels: List[EventChannel], queue_size: int = 100) -> None:
    queue = asyncio.Queue(maxsize=queue_size)
    _subscriber_queues[subscriber_id] = queue
    _subscriber_channels[subscriber_id] = channels
    async with self._lock:
        for channel in channels:
            self._subscribers[channel].add(queue)
    logger.info(f"New subscriber added to channels: {[c.value for c in channels]}")


async def _unsubscribe_named(self, subscriber_id: str) -> None:
    if subscriber_id not in _subscriber_queues:
        return
    queue = _subscriber_queues[subscriber_id]
    channels = _subscriber_channels.get(subscriber_id, [])
    async with self._lock:
        for channel in channels:
            self._subscribers[channel].discard(queue)
    _subscriber_queues.pop(subscriber_id, None)
    _subscriber_channels.pop(subscriber_id, None)


async def _get_event_named(self, subscriber_id: str) -> Optional[StreamEvent]:
    if subscriber_id not in _subscriber_queues:
        return None
    queue = _subscriber_queues[subscriber_id]
    try:
        return await queue.get()
    except (asyncio.CancelledError, asyncio.QueueEmpty):
        return None


StreamingBus.subscribe_named = _subscribe_named
StreamingBus.unsubscribe_named = _unsubscribe_named
StreamingBus.get_event_named = _get_event_named


async def publish_market_data(
    symbol: str,
    price: float,
    volume: float,
    source: str,
    **extra_data
) -> None:
    """Convenience function to publish market data."""
    event = StreamEvent(
        channel=EventChannel.MARKET_DATA,
        event_type="ticker",
        data={
            "symbol": symbol,
            "price": price,
            "volume": volume,
            **extra_data
        },
        source=source
    )
    await streaming_bus.publish(event)


async def publish_news(
    title: str,
    content: str,
    source: str,
    sentiment: Optional[float] = None,
    **extra_data
) -> None:
    """Convenience function to publish news."""
    event = StreamEvent(
        channel=EventChannel.NEWS,
        event_type="article",
        data={
            "title": title,
            "content": content,
            "sentiment": sentiment,
            **extra_data
        },
        source=source
    )
    await streaming_bus.publish(event)


async def publish_agent_output(
    agent_id: str,
    output_type: str,
    data: Dict[str, Any]
) -> None:
    """Convenience function to publish agent outputs."""
    event = StreamEvent(
        channel=EventChannel.AGENT_OUTPUT,
        event_type=output_type,
        data=data,
        source=agent_id
    )
    await streaming_bus.publish(event)


async def publish_consensus(
    decision: str,
    confidence: float,
    votes: List[Dict[str, Any]]
) -> None:
    """Convenience function to publish consensus decisions."""
    event = StreamEvent(
        channel=EventChannel.CONSENSUS,
        event_type="decision",
        data={
            "decision": decision,
            "confidence": confidence,
            "votes": votes
        },
        source="consensus_engine"
    )
    await streaming_bus.publish(event)
