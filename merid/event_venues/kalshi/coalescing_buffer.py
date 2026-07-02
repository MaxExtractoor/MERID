"""
Coalescing buffer for Kalshi WebSocket messages to reduce redundant work.

Phase 2: Implement coalescing buffer per market to reduce redundant work.
This buffers rapid updates for the same market and processes them in batches.
"""

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


@dataclass
class BufferedMessage:
    """A buffered message with metadata for coalescing."""
    data: Dict[str, Any]
    timestamp: float
    seq: Optional[int] = None
    market_id: str = ""
    
    def __post_init__(self):
        if not self.market_id:
            self.market_id = self.data.get("ticker") or self.data.get("market_ticker", "")


@dataclass
class MarketBuffer:
    """Per-market buffer for coalescing messages."""
    messages: deque = field(default_factory=deque)
    last_process_time: float = field(default_factory=time.time)
    message_count: int = 0
    last_seq: Optional[int] = None
    
    # Coalescing configuration
    max_buffer_size: int = 50
    max_age_seconds: float = 0.100  # 100ms max age for buffered messages
    max_batch_size: int = 10  # Max messages to process in one batch
    
    def add_message(self, message: BufferedMessage) -> bool:
        """Add a message to the buffer. Returns True if added, False if dropped."""
        if len(self.messages) >= self.max_buffer_size:
            logger.warning(f"Market buffer full for {message.market_id} - dropping oldest message")
            self.messages.popleft()
        
        self.messages.append(message)
        self.message_count += 1
        
        # Update sequence tracking
        if message.seq is not None:
            if self.last_seq is None or message.seq > self.last_seq:
                self.last_seq = message.seq
        
        return True
    
    def should_process(self) -> bool:
        """Check if buffer should be processed based on time or size."""
        now = time.time()
        
        # Process if buffer is getting full
        if len(self.messages) >= self.max_batch_size:
            return True
        
        # Process if oldest message is too old
        if self.messages and (now - self.messages[0].timestamp) >= self.max_age_seconds:
            return True
        
        # Process if it's been too long since last processing
        if (now - self.last_process_time) >= self.max_age_seconds:
            return True
        
        return False
    
    def get_messages_to_process(self) -> List[BufferedMessage]:
        """Get messages that should be processed now."""
        if not self.messages:
            return []
        
        # Get all messages up to the max batch size
        messages = list(self.messages)
        if len(messages) > self.max_batch_size:
            messages = messages[:self.max_batch_size]
            # Keep remaining messages in buffer - convert to list first
            remaining_messages = list(self.messages)[self.max_batch_size:]
            self.messages = deque(remaining_messages)
        else:
            # Clear all processed messages
            self.messages.clear()
        
        self.last_process_time = time.time()
        return messages
    
    def get_stats(self) -> Dict[str, Any]:
        """Get buffer statistics."""
        return {
            "buffer_size": len(self.messages),
            "message_count": self.message_count,
            "last_process_time": self.last_process_time,
            "last_seq": self.last_seq,
            "age_seconds": time.time() - self.last_process_time if self.messages else 0
        }


class CoalescingBuffer:
    """
    Coalescing buffer for Kalshi WebSocket messages.
    
    Reduces redundant work by:
    1. Buffering rapid updates for the same market
    2. Processing messages in batches
    3. Coalescing redundant orderbook deltas
    4. Prioritizing recent messages over old ones
    """
    
    def __init__(self, 
                 max_age_seconds: float = 0.100,
                 max_buffer_size: int = 50,
                 max_batch_size: int = 10,
                 cleanup_interval: float = 1.0):
        """
        Initialize coalescing buffer.
        
        Args:
            max_age_seconds: Maximum age of buffered messages before forced processing
            max_buffer_size: Maximum messages per market buffer
            max_batch_size: Maximum messages to process in one batch
            cleanup_interval: Interval for cleaning up empty buffers
        """
        self.max_age_seconds = max_age_seconds
        self.max_buffer_size = max_buffer_size
        self.max_batch_size = max_batch_size
        self.cleanup_interval = cleanup_interval
        
        # Per-market buffers
        self.market_buffers: Dict[str, MarketBuffer] = defaultdict(
            lambda: MarketBuffer(
                max_buffer_size=max_buffer_size,
                max_age_seconds=max_age_seconds,
                max_batch_size=max_batch_size
            )
        )
        
        # Statistics
        self.total_messages_buffered = 0
        self.total_messages_processed = 0
        self.total_messages_dropped = 0
        self.total_batches_processed = 0
        self.start_time = time.time()
        
        # Background cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
    
    def start(self) -> None:
        """Start the coalescing buffer background tasks."""
        if self._running:
            return
        
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop(), name="coalescing-buffer-cleanup")
        logger.info("Coalescing buffer started")
    
    def stop(self) -> None:
        """Stop the coalescing buffer background tasks."""
        if not self._running:
            return
        
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                asyncio.get_running_loop().run_until_complete(self._cleanup_task)
            except (asyncio.CancelledError, RuntimeError):
                pass
        
        logger.info("Coalescing buffer stopped")
    
    def add_message(self, data: Dict[str, Any]) -> bool:
        """
        Add a message to the coalescing buffer.
        
        Args:
            data: Raw WebSocket message data
            
        Returns:
            True if message was added, False if dropped
        """
        # Extract market ID
        market_id = data.get("ticker") or data.get("market_ticker", "")
        if not market_id:
            # Global messages (not market-specific) - don't buffer
            return False
        
        # Create buffered message
        seq = data.get("seq")
        buffered_msg = BufferedMessage(
            data=data,
            timestamp=time.time(),
            seq=seq,
            market_id=market_id
        )
        
        # Add to market-specific buffer
        buffer = self.market_buffers[market_id]
        added = buffer.add_message(buffered_msg)
        
        if added:
            self.total_messages_buffered += 1
        else:
            self.total_messages_dropped += 1
        
        return added
    
    def get_ready_markets(self) -> List[str]:
        """
        Get list of markets that have messages ready to be processed.
        
        Returns:
            List of market IDs that should be processed now
        """
        ready_markets = []
        
        for market_id, buffer in self.market_buffers.items():
            if buffer.should_process():
                ready_markets.append(market_id)
        
        return ready_markets
    
    def process_market(self, market_id: str) -> List[Dict[str, Any]]:
        """
        Process all buffered messages for a specific market.
        
        Args:
            market_id: Market identifier to process
            
        Returns:
            List of processed messages (coalesced and optimized)
        """
        buffer = self.market_buffers[market_id]
        messages = buffer.get_messages_to_process()
        
        if not messages:
            return []
        
        # Coalesce messages based on type
        processed_messages = self._coalesce_messages(market_id, messages)
        
        self.total_messages_processed += len(messages)
        self.total_batches_processed += 1
        
        logger.debug(
            f"Processed {len(messages)} buffered messages for {market_id} -> {len(processed_messages)} coalesced"
        )
        
        return processed_messages
    
    def _coalesce_messages(self, market_id: str, messages: List[BufferedMessage]) -> List[Dict[str, Any]]:
        """
        Coalesce multiple messages into a minimal set.
        
        Args:
            market_id: Market identifier
            messages: List of buffered messages to coalesce
            
        Returns:
            List of coalesced messages
        """
        if not messages:
            return []
        
        # Group messages by type
        by_type: Dict[str, List[BufferedMessage]] = defaultdict(list)
        for msg in messages:
            msg_type = msg.data.get("type", "unknown")
            by_type[msg_type].append(msg)
        
        coalesced = []
        
        # Process each message type
        for msg_type, type_messages in by_type.items():
            if msg_type == "orderbook_delta":
                # Coalesce orderbook deltas - keep only the latest
                coalesced.extend(self._coalesce_orderbook_deltas(market_id, type_messages))
            elif msg_type == "ticker":
                # Coalesce ticker messages - keep only the latest
                coalesced.extend(self._coalesce_ticker_messages(market_id, type_messages))
            elif msg_type == "trade":
                # Trades are unique - keep all
                coalesced.extend([msg.data for msg in type_messages])
            else:
                # Other message types - keep all
                coalesced.extend([msg.data for msg in type_messages])
        
        return coalesced
    
    def _coalesce_orderbook_deltas(self, market_id: str, messages: List[BufferedMessage]) -> List[Dict[str, Any]]:
        """
        Coalesce orderbook delta messages.
        
        For orderbook deltas, we only need the latest state since intermediate
        states are immediately superseded.
        """
        if not messages:
            return []
        
        # Sort by sequence number if available, otherwise by timestamp
        messages.sort(key=lambda m: (m.seq or 0, m.timestamp))
        
        # Keep only the latest delta
        latest_message = messages[-1]
        
        # Update the message to indicate it was coalesced
        coalesced_data = latest_message.data.copy()
        coalesced_data["_coalesced"] = True
        coalesced_data["_coalesced_count"] = len(messages)
        coalesced_data["_original_seq_range"] = [
            messages[0].seq,
            messages[-1].seq
        ] if messages[0].seq is not None else None
        
        return [coalesced_data]
    
    def _coalesce_ticker_messages(self, market_id: str, messages: List[BufferedMessage]) -> List[Dict[str, Any]]:
        """
        Coalesce ticker messages.
        
        For ticker messages, we only need the latest price information.
        """
        if not messages:
            return []
        
        # Sort by sequence number if available, otherwise by timestamp
        messages.sort(key=lambda m: (m.seq or 0, m.timestamp))
        
        # Keep only the latest ticker
        latest_message = messages[-1]
        
        # Update the message to indicate it was coalesced
        coalesced_data = latest_message.data.copy()
        coalesced_data["_coalesced"] = True
        coalesced_data["_coalesced_count"] = len(messages)
        
        return [coalesced_data]
    
    async def _cleanup_loop(self) -> None:
        """Background task to cleanup empty buffers and collect statistics."""
        while self._running:
            try:
                await asyncio.sleep(self.cleanup_interval)
                self._cleanup_empty_buffers()
                self._log_statistics()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Coalescing buffer cleanup error: {e}")
    
    def _cleanup_empty_buffers(self) -> None:
        """Remove empty buffers to free memory."""
        empty_markets = [
            market_id for market_id, buffer in self.market_buffers.items()
            if len(buffer.messages) == 0 and 
               (time.time() - buffer.last_process_time) > 60.0  # 1 minute idle
        ]
        
        for market_id in empty_markets:
            del self.market_buffers[market_id]
        
        if empty_markets:
            logger.debug(f"Cleaned up {len(empty_markets)} empty market buffers")
    
    def _log_statistics(self) -> None:
        """Log periodic statistics."""
        uptime = time.time() - self.start_time
        active_markets = len(self.market_buffers)
        total_buffered = sum(len(buf.messages) for buf in self.market_buffers.values())
        
        logger.info(
            f"Coalescing buffer stats: uptime={uptime:.1f}s, "
            f"active_markets={active_markets}, total_buffered={total_buffered}, "
            f"total_processed={self.total_messages_processed}, "
            f"total_dropped={self.total_messages_dropped}, "
            f"batches_processed={self.total_batches_processed}"
        )
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get comprehensive statistics."""
        uptime = time.time() - self.start_time
        active_markets = len(self.market_buffers)
        total_buffered = sum(len(buf.messages) for buf in self.market_buffers.values())
        
        market_stats = {}
        for market_id, buffer in self.market_buffers.items():
            market_stats[market_id] = buffer.get_stats()
        
        return {
            "uptime_seconds": uptime,
            "active_markets": active_markets,
            "total_buffered_messages": total_buffered,
            "total_messages_buffered": self.total_messages_buffered,
            "total_messages_processed": self.total_messages_processed,
            "total_messages_dropped": self.total_messages_dropped,
            "total_batches_processed": self.total_batches_processed,
            "messages_per_second": self.total_messages_processed / uptime if uptime > 0 else 0,
            "drop_rate": self.total_messages_dropped / max(1, self.total_messages_buffered),
            "coalescing_efficiency": 1.0 - (self.total_messages_processed / max(1, self.total_messages_buffered)),
            "market_buffers": market_stats
        }
