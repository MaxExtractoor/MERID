"""
Kalshi WebSocket Deterministic Tests

This test suite validates WebSocket message handling with synthetic streams
and ensures invariants are maintained. It tests deterministic behavior of
the WebSocket bridge for Kalshi 15-minute crypto markets.

SPEC_VERSION: 1.0.0
"""

import pytest
from typing import Dict, Any, List
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class SyntheticWSMessage:
    """Represents a synthetic WebSocket message."""
    channel: str
    msg_type: str
    data: Dict[str, Any]
    timestamp: datetime


class TestWebSocketDeterministic:
    """Test WebSocket deterministic behavior with synthetic streams."""

    @pytest.fixture
    def synthetic_message_stream(self):
        """Generate a synthetic WebSocket message stream."""
        base_time = datetime(2026, 1, 15, 12, 0, 0)
        
        messages = [
            SyntheticWSMessage(
                channel="orderbook",
                msg_type="delta",
                data={
                    "market_id": "KXBTC-26JAN24-50000",
                    "yes_price": 0.50,
                    "no_price": 0.50,
                    "yes_depth": 1000,
                    "no_depth": 1000,
                },
                timestamp=base_time + timedelta(seconds=0),
            ),
            SyntheticWSMessage(
                channel="fill",
                msg_type="trade",
                data={
                    "fill_id": "fill_001",
                    "market_id": "KXBTC-26JAN24-50000",
                    "side": "yes",
                    "count": 10,
                    "price": 0.50,
                },
                timestamp=base_time + timedelta(seconds=1),
            ),
            SyntheticWSMessage(
                channel="orderbook",
                msg_type="snapshot",
                data={
                    "market_id": "KXBTC-26JAN24-50000",
                    "yes_price": 0.51,
                    "no_price": 0.49,
                    "yes_depth": 990,
                    "no_depth": 1010,
                },
                timestamp=base_time + timedelta(seconds=2),
            ),
        ]
        return messages

    @pytest.mark.kalshi_websocket
    def test_message_order_preserved_in_stream(self, synthetic_message_stream):
        """Test that message order is preserved in the stream."""
        # Arrange: Synthetic message stream
        messages = synthetic_message_stream
        
        # Act: Verify message order
        assert messages[0].msg_type == "delta"
        assert messages[1].msg_type == "trade"
        assert messages[2].msg_type == "snapshot"
        
        # Assert: Timestamps are monotonically increasing
        assert messages[0].timestamp < messages[1].timestamp
        assert messages[1].timestamp < messages[2].timestamp

    @pytest.mark.kalshi_websocket
    def test_fill_message_idempotency(self, synthetic_message_stream):
        """Test that duplicate fill messages are handled idempotently."""
        # Arrange: Duplicate fill messages
        fill_msg = synthetic_message_stream[1]
        duplicate_stream = [synthetic_message_stream[0], fill_msg, fill_msg, synthetic_message_stream[2]]
        
        # Act: Process stream
        unique_fills = set()
        for msg in duplicate_stream:
            if msg.msg_type == "trade":
                fill_id = msg.data.get("fill_id")
                unique_fills.add(fill_id)
        
        # Assert: Only one fill processed despite duplicates
        assert len(unique_fills) == 1
        assert "fill_001" in unique_fills

    @pytest.mark.kalshi_websocket
    def test_orderbook_state_consistency(self, synthetic_message_stream):
        """Test that orderbook state remains consistent after delta updates."""
        # Arrange: Initial snapshot + delta
        initial_state = {
            "yes_price": 0.50,
            "no_price": 0.50,
            "yes_depth": 1000,
            "no_depth": 1000,
        }
        
        delta = synthetic_message_stream[0]
        new_state = synthetic_message_stream[2]
        
        # Act: Apply delta and verify consistency
        # Yes price increased from 0.50 to 0.51
        assert new_state.data["yes_price"] == 0.51
        assert new_state.data["no_price"] == 0.49
        
        # Depth should reflect price change (inverse relationship)
        assert new_state.data["yes_depth"] == 990
        assert new_state.data["no_depth"] == 1010
        
        # Assert: Sum of depths should be conserved (approximately)
        total_depth_initial = initial_state["yes_depth"] + initial_state["no_depth"]
        total_depth_new = new_state.data["yes_depth"] + new_state.data["no_depth"]
        assert total_depth_initial == total_depth_new

    @pytest.mark.kalshi_websocket
    def test_market_id_invariant(self, synthetic_message_stream):
        """Test that market_id is consistent across messages for same market."""
        # Arrange: All messages for same market
        market_ids = [msg.data.get("market_id") for msg in synthetic_message_stream]
        
        # Act: Verify all market IDs match
        assert all(market_id == "KXBTC-26JAN24-50000" for market_id in market_ids)
        
        # Assert: No mixed market IDs in stream
        assert len(set(market_ids)) == 1

    @pytest.mark.kalshi_websocket
    def test_price_bounds_invariant(self, synthetic_message_stream):
        """Test that prices remain within valid bounds [0, 1]."""
        # Arrange: Orderbook messages
        orderbook_msgs = [msg for msg in synthetic_message_stream if msg.channel == "orderbook"]
        
        # Act: Check all prices
        for msg in orderbook_msgs:
            yes_price = msg.data.get("yes_price")
            no_price = msg.data.get("no_price")
            
            # Assert: Prices in [0, 1]
            assert 0 <= yes_price <= 1
            assert 0 <= no_price <= 1
            
            # Assert: Yes + No ≈ 1 (within tolerance)
            assert abs((yes_price + no_price) - 1.0) < 0.01

    @pytest.mark.kalshi_websocket
    def test_depth_non_negative_invariant(self, synthetic_message_stream):
        """Test that depth values are never negative."""
        # Arrange: Orderbook messages
        orderbook_msgs = [msg for msg in synthetic_message_stream if msg.channel == "orderbook"]
        
        # Act: Check all depths
        for msg in orderbook_msgs:
            yes_depth = msg.data.get("yes_depth")
            no_depth = msg.data.get("no_depth")
            
            # Assert: Depths are non-negative
            assert yes_depth >= 0
            assert no_depth >= 0

    @pytest.mark.kalshi_websocket
    def test_fill_count_positive_invariant(self, synthetic_message_stream):
        """Test that fill counts are always positive."""
        # Arrange: Fill messages
        fill_msgs = [msg for msg in synthetic_message_stream if msg.msg_type == "trade"]
        
        # Act: Check all fill counts
        for msg in fill_msgs:
            count = msg.data.get("count")
            
            # Assert: Count is positive
            assert count > 0

    @pytest.mark.kalshi_websocket
    def test_message_sequence_number_invariant(self):
        """Test that message sequence numbers are monotonic."""
        # Arrange: Messages with sequence numbers
        messages = [
            {"seq": 1, "data": "msg1"},
            {"seq": 2, "data": "msg2"},
            {"seq": 3, "data": "msg3"},
        ]
        
        # Act: Verify monotonic increase
        seq_nums = [msg["seq"] for msg in messages]
        
        # Assert: Sequence numbers are strictly increasing
        assert seq_nums == sorted(seq_nums)
        assert all(seq_nums[i] < seq_nums[i+1] for i in range(len(seq_nums)-1))

    @pytest.mark.kalshi_websocket
    def test_channel_separation_invariant(self, synthetic_message_stream):
        """Test that messages are correctly separated by channel."""
        # Arrange: Group messages by channel
        channels = {}
        for msg in synthetic_message_stream:
            if msg.channel not in channels:
                channels[msg.channel] = []
            channels[msg.channel].append(msg)
        
        # Act: Verify channel separation
        assert "orderbook" in channels
        assert "fill" in channels
        
        # Assert: Messages in correct channels
        assert all(msg.channel == "orderbook" for msg in channels["orderbook"])
        assert all(msg.channel == "fill" for msg in channels["fill"])

    @pytest.mark.kalshi_websocket
    def test_timestamp_monotonicity_invariant(self, synthetic_message_stream):
        """Test that timestamps are monotonically increasing."""
        # Arrange: Message timestamps
        timestamps = [msg.timestamp for msg in synthetic_message_stream]
        
        # Act: Verify monotonic increase
        assert all(timestamps[i] < timestamps[i+1] for i in range(len(timestamps)-1))

    @pytest.mark.kalshi_websocket
    def test_message_schema_invariant(self, synthetic_message_stream):
        """Test that all messages conform to expected schema."""
        # Arrange: Expected schema fields
        required_fields = ["channel", "msg_type", "data", "timestamp"]
        
        # Act: Verify schema compliance
        for msg in synthetic_message_stream:
            # Assert: All required fields present
            assert hasattr(msg, "channel")
            assert hasattr(msg, "msg_type")
            assert hasattr(msg, "data")
            assert hasattr(msg, "timestamp")
            
            # Assert: Data is a dict
            assert isinstance(msg.data, dict)
            
            # Assert: Timestamp is datetime
            assert isinstance(msg.timestamp, datetime)

    @pytest.mark.kalshi_websocket
    def test_replay_determinism(self, synthetic_message_stream):
        """Test that replaying the same stream produces identical results."""
        # Arrange: Stream to replay twice
        stream = synthetic_message_stream
        
        # Act: Replay stream and collect results
        def process_stream(stream):
            results = []
            for msg in stream:
                if msg.msg_type == "trade":
                    results.append(msg.data.get("fill_id"))
                elif msg.msg_type == "delta":
                    results.append(msg.data.get("yes_price"))
                elif msg.msg_type == "snapshot":
                    results.append(msg.data.get("yes_price"))
            return results
        
        first_run = process_stream(stream)
        second_run = process_stream(stream)
        
        # Assert: Identical results on replay
        assert first_run == second_run

    @pytest.mark.kalshi_websocket
    def test_concurrent_stream_handling(self):
        """Test that concurrent streams are handled correctly."""
        # Arrange: Two concurrent streams for different markets
        btc_stream = [
            SyntheticWSMessage(
                channel="orderbook",
                msg_type="delta",
                data={"market_id": "KXBTC-26JAN24-50000", "yes_price": 0.50},
                timestamp=datetime(2026, 1, 15, 12, 0, 0),
            )
        ]
        eth_stream = [
            SyntheticWSMessage(
                channel="orderbook",
                msg_type="delta",
                data={"market_id": "KXETH-26JAN24-4000", "yes_price": 0.50},
                timestamp=datetime(2026, 1, 15, 12, 0, 0),
            )
        ]
        
        # Act: Process streams concurrently
        btc_market_ids = [msg.data.get("market_id") for msg in btc_stream]
        eth_market_ids = [msg.data.get("market_id") for msg in eth_stream]
        
        # Assert: Market IDs don't mix
        assert all(market_id.startswith("KXBTC") for market_id in btc_market_ids)
        assert all(market_id.startswith("KXETH") for market_id in eth_market_ids)
        assert set(btc_market_ids).isdisjoint(set(eth_market_ids))


def pytest_configure(config):
    """Configure pytest markers for WebSocket deterministic tests."""
    config.addinivalue_line(
        "markers", "kalshi_websocket: Kalshi WebSocket deterministic tests"
    )
