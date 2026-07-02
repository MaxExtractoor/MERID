"""
Tests for Phase 2: Coalescing buffer implementation.

Tests the coalescing buffer functionality to ensure it reduces redundant work
by buffering rapid updates for the same market and processing them in batches.
"""

import asyncio
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any

from merid.event_venues.kalshi.coalescing_buffer import (
    CoalescingBuffer,
    BufferedMessage,
    MarketBuffer
)


class TestBufferedMessage:
    """Test the BufferedMessage dataclass."""
    
    def test_buffered_message_creation(self):
        """Test creating a buffered message."""
        data = {"type": "orderbook_delta", "ticker": "KXBTC15M-26JUN010745-45", "seq": 123}
        
        msg = BufferedMessage(
            data=data,
            timestamp=time.time(),
            seq=123,
            market_id="KXBTC15M-26JUN010745-45"
        )
        
        assert msg.data == data
        assert msg.seq == 123
        assert msg.market_id == "KXBTC15M-26JUN010745-45"
        assert isinstance(msg.timestamp, float)
    
    def test_buffered_message_post_init(self):
        """Test that market_id is extracted from data if not provided."""
        data = {"ticker": "KXETH15M-26JUN010745-55"}
        
        msg = BufferedMessage(
            data=data,
            timestamp=time.time()
        )
        
        assert msg.market_id == "KXETH15M-26JUN010745-55"


class TestMarketBuffer:
    """Test the MarketBuffer class."""
    
    def test_market_buffer_initialization(self):
        """Test creating a market buffer."""
        buffer = MarketBuffer(
            max_buffer_size=100,
            max_age_seconds=0.050,
            max_batch_size=10
        )
        
        assert buffer.max_buffer_size == 100
        assert buffer.max_age_seconds == 0.050
        assert buffer.max_batch_size == 10
        assert len(buffer.messages) == 0
        assert buffer.message_count == 0
        assert buffer.last_seq is None
    
    def test_add_message(self):
        """Test adding messages to buffer."""
        buffer = MarketBuffer()
        data = {"type": "orderbook_delta", "ticker": "KXBTC15M-26JUN010745-45"}
        
        msg = BufferedMessage(data=data, timestamp=time.time(), seq=1)
        
        # Add message
        result = buffer.add_message(msg)
        
        assert result is True
        assert len(buffer.messages) == 1
        assert buffer.message_count == 1
        assert buffer.last_seq == 1
    
    def test_add_message_overflow(self):
        """Test buffer overflow handling."""
        buffer = MarketBuffer(max_buffer_size=2)
        data = {"type": "orderbook_delta", "ticker": "KXBTC15M-26JUN010745-45"}
        
        # Add messages up to capacity
        msg1 = BufferedMessage(data=data, timestamp=time.time(), seq=1)
        msg2 = BufferedMessage(data=data, timestamp=time.time(), seq=2)
        msg3 = BufferedMessage(data=data, timestamp=time.time(), seq=3)
        
        buffer.add_message(msg1)
        buffer.add_message(msg2)
        
        # Adding third message should drop the first
        result = buffer.add_message(msg3)
        
        assert result is True
        assert len(buffer.messages) == 2  # Should still be at max capacity
        assert buffer.message_count == 3  # But count includes dropped message
        assert buffer.last_seq == 3
    
    def test_should_process_by_time(self):
        """Test processing trigger by time."""
        buffer = MarketBuffer(max_age_seconds=0.050)
        data = {"type": "orderbook_delta", "ticker": "KXBTC15M-26JUN010745-45"}
        
        msg = BufferedMessage(data=data, timestamp=time.time())
        buffer.add_message(msg)
        
        # Should not process immediately
        assert buffer.should_process() is False
        
        # Wait past max age
        time.sleep(0.060)
        
        # Should process now
        assert buffer.should_process() is True
    
    def test_should_process_by_batch_size(self):
        """Test processing trigger by batch size."""
        buffer = MarketBuffer(max_batch_size=3)
        data = {"type": "orderbook_delta", "ticker": "KXBTC15M-26JUN010745-45"}
        
        # Add messages up to batch size
        for i in range(3):
            msg = BufferedMessage(data=data, timestamp=time.time(), seq=i+1)
            buffer.add_message(msg)
        
        # Should process due to batch size
        assert buffer.should_process() is True
    
    def test_get_messages_to_process(self):
        """Test getting messages to process."""
        buffer = MarketBuffer(max_batch_size=3)
        data = {"type": "orderbook_delta", "ticker": "KXBTC15M-26JUN010745-45"}
        
        # Add messages
        for i in range(5):
            msg = BufferedMessage(data=data, timestamp=time.time(), seq=i+1)
            buffer.add_message(msg)
        
        # Get messages to process
        messages = buffer.get_messages_to_process()
        
        # Should return max_batch_size messages
        assert len(messages) == 3
        assert buffer.last_process_time > 0
        
        # Should keep remaining messages
        assert len(buffer.messages) == 2
    
    def test_get_stats(self):
        """Test getting buffer statistics."""
        buffer = MarketBuffer()
        data = {"type": "orderbook_delta", "ticker": "KXBTC15M-26JUN010745-45"}
        
        msg = BufferedMessage(data=data, timestamp=time.time(), seq=1)
        buffer.add_message(msg)
        
        stats = buffer.get_stats()
        
        assert stats["buffer_size"] == 1
        assert stats["message_count"] == 1
        assert stats["last_seq"] == 1
        assert stats["age_seconds"] >= 0


class TestCoalescingBuffer:
    """Test the CoalescingBuffer class."""
    
    def test_coalescing_buffer_initialization(self):
        """Test creating a coalescing buffer."""
        buffer = CoalescingBuffer(
            max_age_seconds=0.050,
            max_buffer_size=100,
            max_batch_size=10
        )
        
        assert buffer.max_age_seconds == 0.050
        assert buffer.max_buffer_size == 100
        assert buffer.max_batch_size == 10
        assert len(buffer.market_buffers) == 0
        assert buffer.total_messages_buffered == 0
        assert buffer.total_messages_processed == 0
    
    @pytest.mark.asyncio
    async def test_start_stop(self):
        """Test starting and stopping the buffer."""
        buffer = CoalescingBuffer()
        
        # Start buffer
        buffer.start()
        assert buffer._running is True
        assert buffer._cleanup_task is not None
        
        # Stop buffer
        buffer.stop()
        assert buffer._running is False
    
    def test_add_message_with_market_id(self):
        """Test adding a message with market ID."""
        buffer = CoalescingBuffer()
        data = {
            "type": "orderbook_delta",
            "ticker": "KXBTC15M-26JUN010745-45",
            "seq": 123
        }
        
        result = buffer.add_message(data)
        
        assert result is True
        assert buffer.total_messages_buffered == 1
        assert "KXBTC15M-26JUN010745-45" in buffer.market_buffers
        assert len(buffer.market_buffers["KXBTC15M-26JUN010745-45"].messages) == 1
    
    def test_add_message_without_market_id(self):
        """Test adding a message without market ID."""
        buffer = CoalescingBuffer()
        data = {"type": "error", "msg": "test error"}
        
        result = buffer.add_message(data)
        
        assert result is False  # Non-market messages are not buffered
        assert buffer.total_messages_buffered == 0
    
    def test_get_ready_markets(self):
        """Test getting markets ready for processing."""
        buffer = CoalescingBuffer(max_age_seconds=0.050)
        data = {"type": "orderbook_delta", "ticker": "KXBTC15M-26JUN010745-45"}
        
        # Add message
        buffer.add_message(data)
        
        # Should not be ready immediately
        ready_markets = buffer.get_ready_markets()
        assert len(ready_markets) == 0
        
        # Wait past max age
        time.sleep(0.060)
        
        # Should be ready now
        ready_markets = buffer.get_ready_markets()
        assert len(ready_markets) == 1
        assert "KXBTC15M-26JUN010745-45" in ready_markets
    
    def test_process_market(self):
        """Test processing messages for a market."""
        buffer = CoalescingBuffer()
        data = {"type": "orderbook_delta", "ticker": "KXBTC15M-26JUN010745-45"}
        
        # Add multiple messages
        for i in range(5):
            data_copy = data.copy()
            data_copy["seq"] = i + 1
            buffer.add_message(data_copy)
        
        # Process market
        processed = buffer.process_market("KXBTC15M-26JUN010745-45")
        
        assert len(processed) > 0
        assert buffer.total_messages_processed == 5
        assert buffer.total_batches_processed == 1
    
    def test_coalesce_orderbook_deltas(self):
        """Test coalescing orderbook delta messages."""
        buffer = CoalescingBuffer()
        
        # Create multiple orderbook delta messages
        messages = []
        for i in range(5):
            data = {
                "type": "orderbook_delta",
                "ticker": "KXBTC15M-26JUN010745-45",
                "seq": i + 1,
                "price_dollars": 0.50 + i * 0.01
            }
            msg = BufferedMessage(data=data, timestamp=time.time(), seq=i+1, market_id="KXBTC15M-26JUN010745-45")
            messages.append(msg)
        
        # Coalesce messages
        coalesced = buffer._coalesce_messages("KXBTC15M-26JUN010745-45", messages)
        
        # Should return only the latest message
        assert len(coalesced) == 1
        assert coalesced[0]["_coalesced"] is True
        assert coalesced[0]["_coalesced_count"] == 5
        assert coalesced[0]["price_dollars"] == 0.54  # Latest price
    
    def test_coalesce_ticker_messages(self):
        """Test coalescing ticker messages."""
        buffer = CoalescingBuffer()
        
        # Create multiple ticker messages
        messages = []
        for i in range(3):
            data = {
                "type": "ticker",
                "ticker": "KXBTC15M-26JUN010745-45",
                "seq": i + 1,
                "bid": 0.48 + i * 0.01,
                "ask": 0.52 + i * 0.01
            }
            msg = BufferedMessage(data=data, timestamp=time.time(), seq=i+1, market_id="KXBTC15M-26JUN010745-45")
            messages.append(msg)
        
        # Coalesce messages
        coalesced = buffer._coalesce_messages("KXBTC15M-26JUN010745-45", messages)
        
        # Should return only the latest message
        assert len(coalesced) == 1
        assert coalesced[0]["_coalesced"] is True
        assert coalesced[0]["_coalesced_count"] == 3
        assert coalesced[0]["bid"] == 0.50  # Latest bid
    
    def test_coalesce_trade_messages(self):
        """Test that trade messages are not coalesced."""
        buffer = CoalescingBuffer()
        
        # Create multiple trade messages
        messages = []
        for i in range(3):
            data = {
                "type": "trade",
                "ticker": "KXBTC15M-26JUN010745-45",
                "trade_id": f"trade_{i}",
                "price": 0.50 + i * 0.01
            }
            msg = BufferedMessage(data=data, timestamp=time.time(), market_id="KXBTC15M-26JUN010745-45")
            messages.append(msg)
        
        # Coalesce messages
        coalesced = buffer._coalesce_messages("KXBTC15M-26JUN010745-45", messages)
        
        # Should return all trade messages (trades are unique)
        assert len(coalesced) == 3
        assert not any(msg.get("_coalesced") for msg in coalesced)
    
    def test_get_statistics(self):
        """Test getting comprehensive statistics."""
        buffer = CoalescingBuffer()
        
        # Add some messages
        data = {"type": "orderbook_delta", "ticker": "KXBTC15M-26JUN010745-45"}
        for i in range(10):
            data_copy = data.copy()
            data_copy["seq"] = i + 1
            buffer.add_message(data_copy)
        
        # Process some messages
        buffer.process_market("KXBTC15M-26JUN010745-45")
        
        # Get statistics
        stats = buffer.get_statistics()
        
        assert stats["total_messages_buffered"] == 10
        assert stats["total_messages_processed"] == 10
        assert stats["total_batches_processed"] == 1
        assert stats["active_markets"] == 1
        assert stats["messages_per_second"] >= 0.0  # Allow for zero in tests
        assert stats["drop_rate"] == 0.0
        assert stats["coalescing_efficiency"] >= 0.0
        assert "market_buffers" in stats


class TestCoalescingBufferIntegration:
    """Integration tests for coalescing buffer with realistic scenarios."""
    
    def test_high_frequency_orderbook_updates(self):
        """Test handling high-frequency orderbook updates."""
        buffer = CoalescingBuffer(max_age_seconds=0.050, max_batch_size=20)
        
        # Simulate rapid orderbook updates
        market_id = "KXBTC15M-26JUN010745-45"
        updates = []
        
        for i in range(50):
            data = {
                "type": "orderbook_delta",
                "ticker": market_id,
                "seq": i + 1,
                "price_dollars": 0.50 + (i * 0.001),
                "delta_fp": 100 + i
            }
            updates.append(data)
            buffer.add_message(data)
            
            # Small delay to simulate real timing
            time.sleep(0.001)
        
        # Wait for processing trigger
        time.sleep(0.060)
        
        # Process the market
        processed = buffer.process_market(market_id)
        
        # Should have coalesced many updates into few messages
        assert len(processed) <= 5  # Should be much less than 50
        assert any(msg.get("_coalesced") for msg in processed)
        
        # Check statistics
        stats = buffer.get_statistics()
        assert stats["total_messages_buffered"] == 50
        assert stats["coalescing_efficiency"] > 0.5  # Should be reasonable efficiency
    
    def test_multiple_markets(self):
        """Test handling multiple markets simultaneously."""
        buffer = CoalescingBuffer(max_age_seconds=0.050)
        
        markets = ["KXBTC15M-26JUN010745-45", "KXETH15M-26JUN010745-55", "KXSOL15M-26JUN010745-65"]
        
        # Add messages to multiple markets
        for market_id in markets:
            for i in range(10):
                data = {
                    "type": "orderbook_delta",
                    "ticker": market_id,
                    "seq": i + 1,
                    "price_dollars": 0.50 + i * 0.01
                }
                buffer.add_message(data)
        
        # Wait for processing trigger
        time.sleep(0.060)
        
        # All markets should be ready
        ready_markets = buffer.get_ready_markets()
        assert len(ready_markets) == 3
        
        # Process each market
        total_processed = 0
        for market_id in markets:
            processed = buffer.process_market(market_id)
            total_processed += len(processed)
        
        # Should have coalesced each market separately
        assert total_processed <= 9  # Should be less than 30 total messages
    
    def test_mixed_message_types(self):
        """Test handling mixed message types for the same market."""
        buffer = CoalescingBuffer()
        market_id = "KXBTC15M-26JUN010745-45"
        
        # Add different message types
        messages = [
            {"type": "orderbook_delta", "ticker": market_id, "seq": 1, "price": 0.50},
            {"type": "orderbook_delta", "ticker": market_id, "seq": 2, "price": 0.51},
            {"type": "ticker", "ticker": market_id, "seq": 3, "bid": 0.49},
            {"type": "ticker", "ticker": market_id, "seq": 4, "bid": 0.50},
            {"type": "trade", "ticker": market_id, "trade_id": "t1", "price": 0.50},
            {"type": "trade", "ticker": market_id, "trade_id": "t2", "price": 0.51},
        ]
        
        for msg in messages:
            buffer.add_message(msg)
        
        # Wait for processing trigger
        time.sleep(0.060)
        
        # Process market
        processed = buffer.process_market(market_id)
        
        # Should have coalesced orderbook deltas and tickers, but not trades
        orderbook_msgs = [msg for msg in processed if msg["type"] == "orderbook_delta"]
        ticker_msgs = [msg for msg in processed if msg["type"] == "ticker"]
        trade_msgs = [msg for msg in processed if msg["type"] == "trade"]
        
        assert len(orderbook_msgs) == 1  # Coalesced
        assert len(ticker_msgs) == 1     # Coalesced
        assert len(trade_msgs) == 2      # Not coalesced
        
        # Check coalescing metadata
        assert orderbook_msgs[0]["_coalesced_count"] == 2
        assert ticker_msgs[0]["_coalesced_count"] == 2
        assert not any(msg.get("_coalesced") for msg in trade_msgs)
    
    @pytest.mark.asyncio
    async def test_background_cleanup(self):
        """Test background cleanup task."""
        buffer = CoalescingBuffer(cleanup_interval=0.100)
        
        # Add messages to create buffers
        for i in range(3):
            data = {"type": "orderbook_delta", "ticker": f"KXBTC15M-26JUN010745-{45+i}"}
            buffer.add_message(data)
        
        assert len(buffer.market_buffers) == 3
        
        # Start buffer (starts cleanup task)
        buffer.start()
        
        # Process all messages to empty buffers
        for market_id in list(buffer.market_buffers.keys()):
            buffer.process_market(market_id)
        
        # Manually set last_process_time to simulate idle time
        for market_buffer in buffer.market_buffers.values():
            market_buffer.last_process_time = time.time() - 70.0  # 70 seconds ago
        
        # Manually trigger cleanup to test logic
        buffer._cleanup_empty_buffers()
        
        # Empty buffers should be cleaned up
        assert len(buffer.market_buffers) == 0
        
        # Stop buffer
        buffer.stop()


if __name__ == "__main__":
    pytest.main([__file__])
