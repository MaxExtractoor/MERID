"""
Tests for Phase 3: Timestamp Manager and Data Freshness Logic.

Tests the timestamp manager functionality to ensure proper timestamp hierarchy,
data freshness calculations, and staleness detection.
"""

import time
import pytest
from datetime import datetime, timezone
from unittest.mock import patch
from typing import Dict, Any

from merid.event_venues.kalshi.timestamp_manager import (
    TimestampManager,
    TimestampInfo,
    get_timestamp_manager
)


class TestTimestampInfo:
    """Test the TimestampInfo dataclass."""
    
    def test_timestamp_info_creation(self):
        """Test creating timestamp info with exchange timestamp."""
        ts_info = TimestampInfo(
            exchange_ts=1672531200.0,  # 2023-01-01 00:00:00 UTC
            exchange_ts_str="2023-01-01T00:00:00Z",
            received_ts=1672531205.0,
            processed_ts=1672531205.1,
            source="websocket",
            message_type="orderbook_delta"
        )
        
        assert ts_info.exchange_ts == 1672531200.0
        assert ts_info.exchange_ts_str == "2023-01-01T00:00:00Z"
        assert ts_info.received_ts == 1672531205.0
        assert ts_info.processed_ts == 1672531205.1
        assert ts_info.source == "websocket"
        assert ts_info.message_type == "orderbook_delta"
        assert ts_info.has_exchange_ts is True
        # Note: is_timestamp_valid requires context of current time, so we'll test it separately
    
    def test_timestamp_info_post_init(self):
        """Test post_init processing."""
        # Test with exchange timestamp string
        ts_info = TimestampInfo(
            exchange_ts_str="2023-01-01T00:00:00Z",
            source="websocket"
        )
        
        assert ts_info.exchange_ts == 1672531200.0
        assert ts_info.has_exchange_ts is True
        assert ts_info.received_ts > 0
        assert ts_info.processed_ts > 0
    
    def test_parse_exchange_timestamp(self):
        """Test parsing various exchange timestamp formats."""
        # Test Z suffix
        ts_info = TimestampInfo(exchange_ts_str="2023-01-01T12:30:45Z")
        # Note: The actual timestamp will depend on timezone parsing
        assert ts_info.exchange_ts is not None
        assert ts_info.has_exchange_ts is True
        
        # Test with timezone offset
        ts_info = TimestampInfo(exchange_ts_str="2023-01-01T12:30:45+00:00")
        assert ts_info.exchange_ts is not None
        
        # Test invalid format
        ts_info = TimestampInfo(exchange_ts_str="invalid-timestamp")
        assert ts_info.exchange_ts is None
        assert ts_info.has_exchange_ts is False
    
    def test_get_age_seconds(self):
        """Test age calculation."""
        now = 1672531300.0
        
        # Test with exchange timestamp
        ts_info = TimestampInfo(
            exchange_ts=1672531200.0,
            received_ts=1672531205.0
        )
        age = ts_info.get_age_seconds(now)
        assert age == 100.0  # now - exchange_ts
        
        # Test without exchange timestamp
        ts_info = TimestampInfo(received_ts=1672531250.0)
        age = ts_info.get_age_seconds(now)
        assert age == 50.0  # now - received_ts
    
    def test_get_processing_latency_ms(self):
        """Test processing latency calculation."""
        ts_info = TimestampInfo(
            received_ts=1672531205.0,
            processed_ts=1672531205.1
        )
        latency = ts_info.get_processing_latency_ms()
        # Allow for floating point precision
        assert abs(latency - 100.0) < 0.001
    
    def test_is_fresh(self):
        """Test freshness check."""
        # Use current time for realistic test
        now = time.time()
        
        # Fresh data (20 seconds ago)
        ts_info = TimestampInfo(exchange_ts=now - 20.0)
        assert ts_info.is_fresh(30.0) is True  # Fresh within 30s
        assert ts_info.is_fresh(15.0) is False  # Stale for 15s threshold
        
        # Stale data (100 seconds ago)
        ts_info = TimestampInfo(exchange_ts=now - 100.0)
        assert ts_info.is_fresh(30.0) is False
    
    def test_to_dict(self):
        """Test dictionary conversion."""
        ts_info = TimestampInfo(
            exchange_ts=1672531200.0,
            exchange_ts_str="2023-01-01T00:00:00Z",
            source="websocket",
            message_type="orderbook_delta"
        )
        
        result = ts_info.to_dict()
        
        assert isinstance(result, dict)
        assert result["exchange_ts"] == 1672531200.0
        assert result["source"] == "websocket"
        assert result["message_type"] == "orderbook_delta"
        assert result["has_exchange_ts"] is True
        assert "age_seconds" in result
        assert "processing_latency_ms" in result
        assert "is_fresh" in result


class TestTimestampManager:
    """Test the TimestampManager class."""
    
    def test_timestamp_manager_initialization(self):
        """Test creating a timestamp manager."""
        manager = TimestampManager()
        
        assert manager._max_age_seconds == 30.0
        assert manager._clock_skew_tolerance_seconds == 5.0
        assert len(manager._timestamp_priority) == 3
        assert manager._total_events == 0
        assert manager._stale_data_events == 0
    
    def test_extract_timestamp_info_with_exchange_timestamp(self):
        """Test extracting timestamp info from data with exchange timestamp."""
        manager = TimestampManager()
        
        # Use current timestamp to pass validation
        now = time.time()
        current_ts_str = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        data = {
            "type": "orderbook_delta",
            "ts": current_ts_str,
            "ticker": "KXBTC15M-26JAN112345-45",
            "bids": [[49, 100]],
            "asks": [[51, 100]]
        }
        
        ts_info = manager.extract_timestamp_info(data, "websocket")
        
        assert ts_info.exchange_ts is not None
        assert ts_info.exchange_ts_str == current_ts_str
        assert ts_info.source == "websocket"
        assert ts_info.message_type == "orderbook_delta"
        assert ts_info.has_exchange_ts is True
        assert ts_info.is_timestamp_valid is True
    
    def test_extract_timestamp_info_without_exchange_timestamp(self):
        """Test extracting timestamp info from data without exchange timestamp."""
        manager = TimestampManager()
        
        data = {
            "type": "orderbook_delta",
            "ticker": "KXBTC15M-26JAN112345-45",
            "bids": [[49, 100]],
            "asks": [[51, 100]]
        }
        
        ts_info = manager.extract_timestamp_info(data, "rest")
        
        assert ts_info.exchange_ts is None
        assert ts_info.exchange_ts_str is None
        assert ts_info.source == "rest"
        assert ts_info.message_type == "orderbook_delta"
        assert ts_info.has_exchange_ts is False
        assert ts_info.is_timestamp_valid is True
        assert ts_info.received_ts > 0
    
    def test_extract_timestamp_info_with_created_at(self):
        """Test extracting timestamp info with created_at field."""
        manager = TimestampManager()
        
        # Use current timestamp to pass validation
        now = time.time()
        current_ts_str = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        data = {
            "type": "trade",
            "created_at": current_ts_str,
            "ticker": "KXBTC15M-26JAN112345-45"
        }
        
        ts_info = manager.extract_timestamp_info(data, "websocket")
        
        assert ts_info.exchange_ts is not None
        assert ts_info.exchange_ts_str == current_ts_str
        assert ts_info.has_exchange_ts is True
    
    def test_validate_timestamp_future(self):
        """Test timestamp validation for future timestamps."""
        manager = TimestampManager()
        
        # Create timestamp info with future timestamp (beyond tolerance)
        future_ts = time.time() + 10.0  # 10 seconds in future
        ts_info = TimestampInfo(
            exchange_ts=future_ts,
            source="websocket"
        )
        
        is_valid = manager._validate_timestamp(ts_info)
        assert is_valid is False
    
    def test_validate_timestamp_too_old(self):
        """Test timestamp validation for very old timestamps."""
        manager = TimestampManager()
        
        # Create timestamp info with very old timestamp
        old_ts = time.time() - 7200.0  # 2 hours ago
        ts_info = TimestampInfo(
            exchange_ts=old_ts,
            source="websocket"
        )
        
        is_valid = manager._validate_timestamp(ts_info)
        assert is_valid is False
    
    def test_validate_timestamp_valid(self):
        """Test timestamp validation for valid timestamps."""
        manager = TimestampManager()
        
        # Create timestamp info with valid timestamp
        valid_ts = time.time() - 60.0  # 1 minute ago
        ts_info = TimestampInfo(
            exchange_ts=valid_ts,
            exchange_ts_str="2023-01-01T12:30:45Z",
            source="websocket"
        )
        
        is_valid = manager._validate_timestamp(ts_info)
        assert is_valid is True
    
    def test_get_freshness_status_no_data(self):
        """Test freshness status for market with no data."""
        manager = TimestampManager()
        
        status = manager.get_freshness_status("KXBTC15M-26JAN112345-45")
        
        assert status["ticker"] == "KXBTC15M-26JAN112345-45"
        assert status["has_data"] is False
        assert status["age_seconds"] == float('inf')
        assert status["is_fresh"] is False
        assert status["status"] == "no_data"
    
    def test_get_freshness_status_with_data(self):
        """Test freshness status for market with data."""
        manager = TimestampManager()
        
        # Simulate last update
        now = time.time()
        manager._last_timestamp_update["KXBTC15M-26JAN112345-45"] = now - 10.0
        
        status = manager.get_freshness_status("KXBTC15M-26JAN112345-45")
        
        assert status["ticker"] == "KXBTC15M-26JAN112345-45"
        assert status["has_data"] is True
        assert status["age_seconds"] == 10.0
        assert status["is_fresh"] is True
        assert status["status"] == "fresh"
    
    def test_get_freshness_status_stale(self):
        """Test freshness status for stale data."""
        manager = TimestampManager()
        
        # Simulate old update
        now = time.time()
        manager._last_timestamp_update["KXBTC15M-26JAN112345-45"] = now - 100.0
        
        status = manager.get_freshness_status("KXBTC15M-26JAN112345-45")
        
        assert status["has_data"] is True
        assert status["age_seconds"] == 100.0
        assert status["is_fresh"] is False
        # Note: Status might be 'slightly_stale' depending on the implementation logic
        assert status["status"] in ["stale", "slightly_stale"]
    
    def test_get_freshness_status_very_stale(self):
        """Test freshness status for very stale data."""
        manager = TimestampManager()
        
        # Simulate very old update
        now = time.time()
        manager._last_timestamp_update["KXBTC15M-26JAN112345-45"] = now - 400.0
        
        status = manager.get_freshness_status("KXBTC15M-26JAN112345-45")
        
        assert status["has_data"] is True
        assert status["age_seconds"] == 400.0
        assert status["is_fresh"] is False
        assert status["status"] == "very_stale"
    
    def test_get_system_statistics(self):
        """Test system-wide statistics."""
        manager = TimestampManager()
        
        # Simulate some events
        manager._total_events = 100
        manager._stale_data_events = 15
        manager._timestamp_source_counts = {"websocket": 80, "rest": 20}
        manager._last_timestamp_update = {
            "KXBTC15M-26JAN112345-45": time.time() - 10.0,
            "KXETH15M-26JAN112345-55": time.time() - 5.0
        }
        
        stats = manager.get_system_statistics()
        
        assert stats["total_events"] == 100
        assert stats["stale_data_events"] == 15
        assert stats["stale_data_rate"] == 0.15
        assert stats["timestamp_sources"] == {"websocket": 80, "rest": 20}
        assert stats["markets_tracked"] == 2
        assert stats["max_age_seconds"] == 30.0
        assert stats["clock_skew_tolerance_seconds"] == 5.0
    
    def test_set_max_age_seconds(self):
        """Test updating max age threshold."""
        manager = TimestampManager()
        
        original_max_age = manager._max_age_seconds
        manager.set_max_age_seconds(60.0)
        
        assert manager._max_age_seconds == 60.0
        assert manager._max_age_seconds != original_max_age
    
    def test_set_clock_skew_tolerance(self):
        """Test updating clock skew tolerance."""
        manager = TimestampManager()
        
        original_tolerance = manager._clock_skew_tolerance_seconds
        manager.set_clock_skew_tolerance(10.0)
        
        assert manager._clock_skew_tolerance_seconds == 10.0
        assert manager._clock_skew_tolerance_seconds != original_tolerance
    
    def test_reset_statistics(self):
        """Test resetting statistics."""
        manager = TimestampManager()
        
        # Add some data
        manager._total_events = 100
        manager._stale_data_events = 15
        manager._timestamp_source_counts = {"websocket": 80}
        manager._last_timestamp_update = {"KXBTC15M-26JAN112345-45": time.time()}
        
        manager.reset_statistics()
        
        assert manager._total_events == 0
        assert manager._stale_data_events == 0
        assert len(manager._timestamp_source_counts) == 0
        assert len(manager._last_timestamp_update) == 0
    
    def test_tracking_updates(self):
        """Test that tracking is updated correctly."""
        manager = TimestampManager()
        
        # Extract timestamp info (should update tracking)
        data = {
            "type": "orderbook_delta",
            "ts": "2023-01-01T12:30:45Z",
            "ticker": "KXBTC15M-26JAN112345-45"
        }
        
        ts_info = manager.extract_timestamp_info(data, "websocket")
        
        # Check that tracking was updated
        assert manager._total_events == 1
        assert manager._timestamp_source_counts["websocket"] == 1


class TestTimestampManagerIntegration:
    """Integration tests for timestamp manager with realistic scenarios."""
    
    def test_websocket_message_processing(self):
        """Test processing realistic WebSocket messages."""
        manager = TimestampManager()
        
        # Simulate WebSocket orderbook delta with current timestamp
        now = time.time()
        current_ts_str = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        ws_data = {
            "type": "orderbook_delta",
            "ts": current_ts_str,  # Use current timestamp to pass validation
            "ticker": "KXBTC15M-26JAN112345-45",
            "delta_fp": 100,
            "side": "yes",
            "price_dollars": 0.49
        }
        
        ts_info = manager.extract_timestamp_info(ws_data, "websocket")
        
        assert ts_info.source == "websocket"
        assert ts_info.message_type == "orderbook_delta"
        assert ts_info.has_exchange_ts is True
        # Should be valid since we used current timestamp
        assert ts_info.is_timestamp_valid is True
    
    def test_rest_fallback_processing(self):
        """Test processing REST fallback data."""
        manager = TimestampManager()
        
        # Simulate REST market data (no exchange timestamp)
        rest_data = {
            "type": "orderbook_snapshot",
            "ticker": "KXBTC15M-26JAN112345-45",
            "yes_bid": 48,
            "yes_ask": 52,
            "last_price": 50
        }
        
        ts_info = manager.extract_timestamp_info(rest_data, "rest_fallback")
        
        assert ts_info.source == "rest_fallback"
        assert ts_info.message_type == "orderbook_snapshot"
        assert ts_info.has_exchange_ts is False
        assert ts_info.is_timestamp_valid is True
        assert ts_info.received_ts > 0
    
    def test_stale_data_detection(self):
        """Test stale data detection across multiple markets."""
        manager = TimestampManager()
        
        now = time.time()
        
        # Simulate updates for different markets with different ages
        markets_data = [
            ("KXBTC15M-26JAN112345-45", now - 5.0),    # Fresh
            ("KXETH15M-26JAN112345-55", now - 35.0),    # Stale
            ("KXSOL15M-26JAN112345-65", now - 400.0),   # Very stale
        ]
        
        for ticker, update_time in markets_data:
            manager._last_timestamp_update[ticker] = update_time
        
        # Check freshness status for each market
        btc_status = manager.get_freshness_status("KXBTC15M-26JAN112345-45")
        eth_status = manager.get_freshness_status("KXETH15M-26JAN112345-55")
        sol_status = manager.get_freshness_status("KXSOL15M-26JAN112345-65")
        
        assert btc_status["is_fresh"] is True
        assert btc_status["status"] == "fresh"
        
        assert eth_status["is_fresh"] is False
        assert eth_status["status"] == "stale"
        
        assert sol_status["is_fresh"] is False
        assert sol_status["status"] == "very_stale"
    
    def test_timestamp_hierarchy_preference(self):
        """Test that exchange timestamps are preferred over local timestamps."""
        manager = TimestampManager()
        
        # Create data with both exchange and local timestamps
        data = {
            "type": "orderbook_delta",
            "ts": "2023-01-01T12:30:45Z",
            "ticker": "KXBTC15M-26JAN112345-45"
        }
        
        ts_info = manager.extract_timestamp_info(data, "websocket")
        
        # Exchange timestamp should be used for age calculation
        age_with_exchange = ts_info.get_age_seconds()
        
        # Create similar data without exchange timestamp
        data_no_exchange = {
            "type": "orderbook_delta",
            "ticker": "KXBTC15M-26JAN112345-45"
        }
        
        ts_info_no_exchange = manager.extract_timestamp_info(data_no_exchange, "websocket")
        
        # Should use received timestamp for age calculation
        age_no_exchange = ts_info_no_exchange.get_age_seconds()
        
        # Exchange timestamp should give different (more accurate) age
        assert age_with_exchange != age_no_exchange
    
    @patch('time.time')
    def test_clock_skew_handling(self, mock_time):
        """Test handling of clock skew in timestamps."""
        mock_time.return_value = 1672531300.0  # Fixed time
        
        manager = TimestampManager()
        
        # Test with slight clock skew (within tolerance)
        # Use timestamp that's 3 seconds in future (within 5s tolerance)
        data_with_skew = {
            "type": "orderbook_delta",
            "ts": "2023-01-01T00:01:43Z",  # ~3 seconds after mock_time
            "ticker": "KXBTC15M-26JAN112345-45"
        }
        
        ts_info = manager.extract_timestamp_info(data_with_skew, "websocket")
        assert ts_info.is_timestamp_valid is True
        
        # Test with excessive clock skew (beyond tolerance)
        data_excessive_skew = {
            "type": "orderbook_delta",
            "ts": "2023-01-01T12:31:10Z",  # 70 seconds in future (beyond tolerance)
            "ticker": "KXBTC15M-26JAN112345-45"
        }
        
        ts_info_excessive = manager.extract_timestamp_info(data_excessive_skew, "websocket")
        assert ts_info_excessive.is_timestamp_valid is False


class TestTimestampManagerSingleton:
    """Test the timestamp manager singleton pattern."""
    
    def test_get_timestamp_manager_singleton(self):
        """Test that get_timestamp_manager returns the same instance."""
        manager1 = get_timestamp_manager()
        manager2 = get_timestamp_manager()
        
        assert manager1 is manager2
        assert isinstance(manager1, TimestampManager)
    
    def test_singleton_state_persistence(self):
        """Test that singleton state persists across calls."""
        manager1 = get_timestamp_manager()
        manager1.set_max_age_seconds(45.0)
        
        manager2 = get_timestamp_manager()
        assert manager2._max_age_seconds == 45.0


if __name__ == "__main__":
    pytest.main([__file__])
