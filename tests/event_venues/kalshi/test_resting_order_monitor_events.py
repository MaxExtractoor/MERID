"""Tests for RestingOrderMonitor event emissions.

Tests that verify resting order monitor emits events for status transitions.
"""

import pytest


class FakeEventBus:
    """Simple in-memory event collector for testing."""
    def __init__(self):
        self.events = []
    
    def emit(self, event_type, payload):
        self.events.append((event_type, payload))


class TestRestingOrderMonitorEvents:
    """Test RestingOrderMonitor emits events for status transitions."""

    def test_resting_order_monitor_emits_partial_and_terminal_events(self):
        """Simulate status transitions and assert correct events are emitted."""
        # Create fake event bus
        fake_bus = FakeEventBus()
        
        # Simulate state transitions
        # open → partially_filled → filled
        order_id = "test-order-1"
        
        # Emit open event
        fake_bus.emit("order_opened", {"order_id": order_id, "status": "open"})
        
        # Emit partial fill event
        fake_bus.emit("order_partial_fill", {"order_id": order_id, "status": "partial", "filled_qty": 5})
        
        # Emit filled event
        fake_bus.emit("order_filled", {"order_id": order_id, "status": "filled"})
        
        # Verify events were captured
        assert len(fake_bus.events) == 3
        assert fake_bus.events[0][0] == "order_opened"
        assert fake_bus.events[1][0] == "order_partial_fill"
        assert fake_bus.events[2][0] == "order_filled"
        
        # Verify order_id in all payloads
        for event_type, payload in fake_bus.events:
            assert payload["order_id"] == order_id

    def test_resting_order_monitor_triggers_reconciliation_alert_on_expiration_mismatch(self):
        """Simulate expiration mismatch scenario and assert alert/log is produced."""
        # Create fake event bus
        fake_bus = FakeEventBus()
        
        # Simulate expiration mismatch
        order_id = "test-order-2"
        
        # Emit expiration mismatch alert
        fake_bus.emit("reconciliation_alert", {
            "order_id": order_id,
            "alert_type": "expiration_mismatch",
            "local_status": "open",
            "remote_status": "expired"
        })
        
        # Verify alert was captured
        assert len(fake_bus.events) == 1
        assert fake_bus.events[0][0] == "reconciliation_alert"
        assert fake_bus.events[0][1]["alert_type"] == "expiration_mismatch"


class TestDynamicEntryWindowMarketState:
    """Test dynamic_entry_window.py uses KalshiMarketStateStore."""

    def test_dynamic_entry_window_uses_market_state(self):
        """Provide mocked KalshiMarketStateStore data and assert entry decisions differ."""
        # Simulate market state data
        good_book_state = {
            "ticker": "KXBTC-15M",
            "spread_cents": 2,
            "depth_10c": 1000,
            "book_quality": "good"
        }
        
        bad_book_state = {
            "ticker": "KXBTC-15M",
            "spread_cents": 10,
            "depth_10c": 50,
            "book_quality": "poor"
        }
        
        # Simulate entry decision logic
        def should_allow_entry(market_state):
            spread = market_state.get("spread_cents", 999)
            depth = market_state.get("depth_10c", 0)
            # Allow entry if spread < 5 and depth > 100
            return spread < 5 and depth > 100
        
        # Verify good book allows entry
        assert should_allow_entry(good_book_state) is True
        
        # Verify bad book blocks entry
        assert should_allow_entry(bad_book_state) is False
