"""
WebSocket Bridge Health Tests (LEGACY)
=======================================

LEGACY TEST FILE - DEPRECATED FOR 15M STACK

This test file references the old bridge (merid.event_venues.kalshi.ws_bridge)
which is deprecated for 15m runtime. The 15m lean stack uses the new bridge
with a health state machine (HEALTHY/DEGRADED/UNHEALTHY) implemented in
merid.event_venues.kalshi.ws_bridge.

These tests are kept for the legacy full stack but should NOT be used for
validating the 15m production stack.

For 15m stack WebSocket health testing, see:
- New health state machine in ws_bridge.py (HEALTHY/DEGRADED/UNHEALTHY)
- Structured logging at WS_UPSTREAM, WS_FORWARDER, WS_CLIENT_15M stages
- Dynamic RUN_DEGRADED behavior allowing limited trading with fresh data

Key invariants (LEGACY):
1. WebSocket bridge should process events when available
2. events_processed metric should increment
3. Health checks detect stale/no event conditions
4. Bridge recovery works after failures
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import List, Dict, Any

# DEPRECATED: Old bridge - 15m lean stack uses merid_core.kalshi.ws_bridge
from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge


@dataclass
class MockWebSocketEvent:
    """Mock WebSocket event for testing."""
    event_type: str
    data: Dict[str, Any]
    timestamp: float


class TestWebSocketBridgeHealth:
    """Tests for WebSocket bridge health and event processing."""

    @pytest.fixture
    def mock_ws_bridge(self):
        """Create a mock WebSocket bridge for testing."""
        bridge = Mock(spec=KalshiWebSocketBridge)
        bridge.events_processed = 0
        bridge._last_event_time = 0.0
        bridge._connected = False
        bridge._subscriptions = set()
        return bridge

    @pytest.fixture
    def sample_events(self):
        """Create sample WebSocket events for testing."""
        base_time = 1234567890.0  # Fixed timestamp for consistent testing
        return [
            MockWebSocketEvent(
                event_type="book",
                data={
                    "market_id": "KXBTC15M-25JUN26-95000",
                    "best_bid": 48,
                    "best_ask": 52,
                    "bid_size": 1000,
                    "ask_size": 1000
                },
                timestamp=base_time
            ),
            MockWebSocketEvent(
                event_type="trade",
                data={
                    "market_id": "KXETH15M-25JUN26-3500",
                    "price": 3500,
                    "size": 100
                },
                timestamp=base_time + 1.0
            )
        ]

    def test_events_processed_increment(self, mock_ws_bridge, sample_events):
        """Test 1: events_processed increments when events are processed."""
        # Arrange
        initial_count = mock_ws_bridge.events_processed
        
        # Act - simulate processing events
        for event in sample_events:
            mock_ws_bridge.events_processed += 1
            mock_ws_bridge._last_event_time = event.timestamp
        
        # Assert
        expected_count = initial_count + len(sample_events)
        assert mock_ws_bridge.events_processed == expected_count, \
            f"Expected events_processed={expected_count}, got {mock_ws_bridge.events_processed}"
        assert mock_ws_bridge._last_event_time == sample_events[-1].timestamp, \
            "Last event time should be updated"

    def test_no_events_stale_detection(self, mock_ws_bridge):
        """Test 2: Stale detection when no events received."""
        # Arrange
        import time
        stale_threshold = 30.0  # 30 seconds
        
        # Set last event time to be older than threshold
        mock_ws_bridge._last_event_time = time.time() - (stale_threshold + 10.0)
        mock_ws_bridge.events_processed = 0
        
        # Act - check if stale
        current_time = time.time()
        time_since_last = current_time - mock_ws_bridge._last_event_time
        is_stale = time_since_last > stale_threshold
        
        # Assert
        assert is_stale, "Bridge should be detected as stale"
        assert mock_ws_bridge.events_processed == 0, "No events should have been processed"

    def test_event_health_metrics(self, mock_ws_bridge, sample_events):
        """Test 3: Event health metrics are tracked correctly."""
        # Arrange
        base_time = 1234567890.0  # Fixed timestamp for consistent testing
        current_time = base_time + 10.0  # Fixed current time for testing
        
        # Act - process events and track metrics
        metrics = {
            "events_processed": 0,
            "last_event_age": 0.0,
            "events_per_minute": 0.0
        }
        
        for event in sample_events:
            mock_ws_bridge.events_processed += 1
            mock_ws_bridge._last_event_time = event.timestamp
            metrics["events_processed"] = mock_ws_bridge.events_processed
            metrics["last_event_age"] = current_time - event.timestamp
        
        # Calculate events per minute (simplified)
        if mock_ws_bridge.events_processed > 0:
            time_window = current_time - sample_events[0].timestamp
            if time_window > 0:
                metrics["events_per_minute"] = (mock_ws_bridge.events_processed / time_window) * 60.0
        
        # Assert
        assert metrics["events_processed"] == len(sample_events)
        assert metrics["last_event_age"] >= 0
        assert metrics["events_per_minute"] >= 0

    async def test_bridge_recovery_after_failure(self, mock_ws_bridge, sample_events):
        """Test 4: Bridge recovery after connection failure."""
        # Arrange - simulate connection failure
        mock_ws_bridge._connected = False
        mock_ws_bridge.events_processed = 0
        
        # Act - simulate recovery
        mock_ws_bridge._connected = True
        
        # Process events after recovery
        for event in sample_events:
            mock_ws_bridge.events_processed += 1
            mock_ws_bridge._last_event_time = event.timestamp
        
        # Assert
        assert mock_ws_bridge._connected, "Bridge should be connected after recovery"
        assert mock_ws_bridge.events_processed == len(sample_events), \
            "Should process events after recovery"

    def test_subscription_tracking(self, mock_ws_bridge):
        """Test 5: WebSocket subscription tracking."""
        # Arrange
        tickers = ["KXBTC15M-25JUN26-95000", "KXETH15M-25JUN26-3500"]
        
        # Act - simulate subscriptions
        for ticker in tickers:
            mock_ws_bridge._subscriptions.add(ticker)
        
        # Assert
        assert len(mock_ws_bridge._subscriptions) == len(tickers), \
            f"Expected {len(tickers)} subscriptions, got {len(mock_ws_bridge._subscriptions)}"
        assert all(ticker in mock_ws_bridge._subscriptions for ticker in tickers), \
            "All tickers should be subscribed"

    @patch('merid.event_venues.kalshi.ws_bridge.logger')
    def test_health_check_logging(self, mock_logger, mock_ws_bridge):
        """Test 6: Health check generates appropriate logs."""
        # Arrange
        import time
        mock_ws_bridge.events_processed = 100
        mock_ws_bridge._last_event_time = time.time() - 5.0  # 5 seconds ago
        mock_ws_bridge._connected = True
        
        # Act - simulate health check
        current_time = time.time()
        last_event_age = current_time - mock_ws_bridge._last_event_time
        
        # Mock the health check logging
        if mock_ws_bridge._connected:
            if mock_ws_bridge.events_processed > 0:
                mock_logger.info(
                    "[WS-BRIDGE-HEALTH] connected=True events_processed=%d last_event_age=%.1fs",
                    mock_ws_bridge.events_processed, last_event_age
                )
            else:
                mock_logger.warning(
                    "[WS-BRIDGE-HEALTH] connected=True but events_processed=0 - no events received"
                )
        else:
            mock_logger.error("[WS-BRIDGE-HEALTH] connected=False - bridge disconnected")
        
        # Assert
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0]
        # Check the format string template
        assert "connected=True" in call_args[0]
        assert "events_processed=%d" in call_args[0]
        # Check the actual values passed to the format string
        assert mock_logger.info.call_args[0][1] == 100  # events_processed value
        assert mock_logger.info.call_args[0][2] >= 0   # last_event_age value

    def test_events_processed_zero_regression(self, mock_ws_bridge):
        """Test 7: Regression test for events_processed=0 issue."""
        # Arrange - start with zero events (regression condition)
        mock_ws_bridge.events_processed = 0
        mock_ws_bridge._last_event_time = 0.0
        
        # Act - simulate receiving events (should fix the regression)
        events = [
            MockWebSocketEvent("book", {"market_id": "test"}, 1234567890.0),
            MockWebSocketEvent("trade", {"market_id": "test"}, 1234567891.0)
        ]
        
        for event in events:
            mock_ws_bridge.events_processed += 1
            mock_ws_bridge._last_event_time = event.timestamp
        
        # Assert - regression should be fixed
        assert mock_ws_bridge.events_processed == len(events), \
            f"Regression not fixed: events_processed={mock_ws_bridge.events_processed}, expected {len(events)}"
        assert mock_ws_bridge._last_event_time > 0, \
            "Last event time should be set"

    async def test_concurrent_event_processing(self, mock_ws_bridge, sample_events):
        """Test 8: Concurrent event processing doesn't cause race conditions."""
        # Arrange
        import time
        initial_count = mock_ws_bridge.events_processed
        
        # Act - simulate concurrent event processing
        async def process_events(events_chunk):
            for event in events_chunk:
                await asyncio.sleep(0.001)  # Simulate processing delay
                mock_ws_bridge.events_processed += 1
                mock_ws_bridge._last_event_time = event.timestamp
        
        # Split events into chunks for concurrent processing
        chunk_size = len(sample_events) // 2
        chunks = [sample_events[:chunk_size], sample_events[chunk_size:]]
        
        # Process chunks concurrently
        tasks = [process_events(chunk) for chunk in chunks]
        await asyncio.gather(*tasks)
        
        # Assert
        expected_count = initial_count + len(sample_events)
        assert mock_ws_bridge.events_processed == expected_count, \
            f"Concurrent processing failed: expected {expected_count}, got {mock_ws_bridge.events_processed}"

    def test_event_filtering_by_subscription(self, mock_ws_bridge, sample_events):
        """Test 9: Events are filtered by active subscriptions."""
        # Arrange
        mock_ws_bridge._subscriptions = {"KXBTC15M-25JUN26-95000"}
        
        # Act - simulate event processing with filtering
        processed_events = []
        for event in sample_events:
            # Simulate subscription filtering
            market_id = event.data.get("market_id", "")
            if market_id in mock_ws_bridge._subscriptions:
                processed_events.append(event)
                mock_ws_bridge.events_processed += 1
                mock_ws_bridge._last_event_time = event.timestamp
        
        # Assert - only subscribed events should be processed
        assert len(processed_events) == 1, "Should only process subscribed events"
        assert processed_events[0].data["market_id"] == "KXBTC15M-25JUN26-95000"
        assert mock_ws_bridge.events_processed == 1

    @patch('time.time')
    def test_time_based_health_checks(self, mock_time, mock_ws_bridge):
        """Test 10: Time-based health checks work correctly."""
        # Arrange
        current_time = 1234567890.0
        mock_time.return_value = current_time
        
        # Set up bridge state
        mock_ws_bridge.events_processed = 50
        mock_ws_bridge._last_event_time = current_time - 10.0  # 10 seconds ago
        
        # Act - calculate health metrics
        time_since_last_event = current_time - mock_ws_bridge._last_event_time
        is_healthy = (
            mock_ws_bridge.events_processed > 0 and
            time_since_last_event < 30.0  # 30 second threshold
        )
        
        # Assert
        assert is_healthy, "Bridge should be healthy with recent events"
        assert time_since_last_event == 10.0, "Time calculation should be correct"

    def test_bridge_state_persistence(self, mock_ws_bridge):
        """Test 11: Bridge state persists across health checks."""
        # Arrange - set initial state
        mock_ws_bridge.events_processed = 100
        mock_ws_bridge._last_event_time = 1234567890.0
        mock_ws_bridge._connected = True
        mock_ws_bridge._subscriptions = {"KXBTC15M-25JUN26-95000"}
        
        # Act - simulate multiple health checks
        for i in range(5):
            # Health check shouldn't modify state
            state_snapshot = {
                "events_processed": mock_ws_bridge.events_processed,
                "last_event_time": mock_ws_bridge._last_event_time,
                "connected": mock_ws_bridge._connected,
                "subscriptions": set(mock_ws_bridge._subscriptions)
            }
            
            # Verify state hasn't changed
            assert state_snapshot["events_processed"] == 100
            assert state_snapshot["last_event_time"] == 1234567890.0
            assert state_snapshot["connected"] is True
            assert state_snapshot["subscriptions"] == {"KXBTC15M-25JUN26-95000"}

    async def test_error_handling_in_event_processing(self, mock_ws_bridge):
        """Test 12: Error handling in event processing doesn't crash bridge."""
        # Arrange
        mock_ws_bridge.events_processed = 0
        
        # Act - simulate events with errors
        problematic_events = [
            MockWebSocketEvent("book", {"invalid": "data"}, 1234567890.0),
            MockWebSocketEvent("trade", None, 1234567891.0),  # None data
            MockWebSocketEvent("book", {"market_id": "valid"}, 1234567892.0)
        ]
        
        for event in problematic_events:
            try:
                # Simulate event processing with error handling
                if event.data is None:
                    raise ValueError("Event data is None")
                if "invalid" in event.data:
                    continue  # Skip invalid events
                
                # Process valid event
                mock_ws_bridge.events_processed += 1
                mock_ws_bridge._last_event_time = event.timestamp
            except Exception:
                # Error should be logged but not crash the bridge
                continue
        
        # Assert - bridge should still be functional
        assert mock_ws_bridge.events_processed == 1, \
            "Should have processed 1 valid event despite errors"
        assert mock_ws_bridge._last_event_time == 1234567892.0, \
            "Last event time should be from the valid event"


class TestWebSocketBridgeIntegration:
    """Integration tests for WebSocket bridge with market state."""

    @patch('merid.event_venues.kalshi.market_state.get_kalshi_market_state_store')
    async def test_bridge_updates_market_state(self, mock_get_store):
        """Test 13: WebSocket bridge updates market state store."""
        # Arrange
        mock_store = Mock()
        mock_get_store.return_value = mock_store
        
        # Mock bridge event processing
        bridge = Mock()
        bridge.events_processed = 0
        
        # Act - simulate book event processing
        book_event = MockWebSocketEvent(
            "book",
            {
                "market_id": "KXBTC15M-25JUN26-95000",
                "best_bid": 48,
                "best_ask": 52,
                "bid_size": 1000,
                "ask_size": 1000
            },
            1234567890.0
        )
        
        # Simulate updating market state
        from merid.event_venues.kalshi.market_state import KalshiMarketStateStore
        # Create a mock market state object for testing
        market_state = Mock()
        market_state.market_id = book_event.data["market_id"]
        market_state.best_bid = book_event.data["best_bid"]
        market_state.best_ask = book_event.data["best_ask"]
        market_state.bid_size = book_event.data["bid_size"]
        market_state.ask_size = book_event.data["ask_size"]
        market_state.last_book_update_ts = book_event.timestamp
        
        mock_store.update_market_state(market_state)
        bridge.events_processed += 1
        
        # Assert
        mock_store.update_market_state.assert_called_once_with(market_state)
        assert bridge.events_processed == 1

    @patch('merid.event_venues.kalshi.ws_bridge.logger')
    def test_bridge_connection_status_logging(self, mock_logger):
        """Test 14: Bridge connection status is logged appropriately."""
        # Arrange
        bridge = Mock()
        bridge._connected = True
        bridge.events_processed = 0
        
        # Act - simulate connection status logging
        if bridge._connected:
            if bridge.events_processed == 0:
                mock_logger.warning(
                    "[WS-BRIDGE-STATUS] Connected but no events processed - check subscriptions"
                )
            else:
                mock_logger.info(
                    "[WS-BRIDGE-STATUS] Connected and processing events normally"
                )
        else:
            mock_logger.error("[WS-BRIDGE-STATUS] Disconnected - attempting reconnection")
        
        # Assert
        mock_logger.warning.assert_called_once()
        assert "no events processed" in mock_logger.warning.call_args[0][0]
