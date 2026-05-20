"""Tests for round-trip monitor."""

import pytest
from datetime import datetime, timedelta
from merid.event_venues.kalshi.round_trip_monitor import (
    RoundTripRecord,
    EntryRecord,
    AssetMetrics,
    Alert,
    RoundTripMonitor,
)


class TestRoundTripRecord:
    """Tests for RoundTripRecord dataclass."""
    
    def test_create_record(self):
        """Test creating a round-trip record."""
        record = RoundTripRecord(
            asset="BTC",
            ticker="KXBTC15M-12345",
            entry_intent_id="entry_123",
            exit_intent_id="exit_123",
            entry_timestamp=datetime.utcnow() - timedelta(minutes=5),
            exit_timestamp=datetime.utcnow(),
            entry_price_cents=50,
            exit_price_cents=55,
            count=10,
            action="buy",
            risk_tier="A",
            window_resolution_id="wr_123",
            exit_policy_id="ep_123",
            planned_sl_price_cents=45,
            planned_tp_price_cents=60,
            max_hold_seconds=900,
            actual_exit_reason="tp",
            realized_pnl_cents=50,  # (55-50)*10
            realized_hold_seconds=300,
        )
        assert record.asset == "BTC"
        assert record.risk_tier == "A"
        assert record.actual_exit_reason == "tp"
        assert record.realized_pnl_cents == 50
    
    def test_to_dict(self):
        """Test converting record to dict."""
        record = RoundTripRecord(
            asset="BTC",
            ticker="KXBTC15M-12345",
            entry_intent_id="entry_123",
            exit_intent_id="exit_123",
            entry_timestamp=datetime.utcnow() - timedelta(minutes=5),
            exit_timestamp=datetime.utcnow(),
            entry_price_cents=50,
            exit_price_cents=55,
            count=10,
            action="buy",
            risk_tier="A",
            window_resolution_id="wr_123",
            exit_policy_id="ep_123",
        )
        d = record.to_dict()
        assert d["asset"] == "BTC"
        assert d["ticker"] == "KXBTC15M-12345"
        assert "entry_timestamp" in d
        assert "exit_timestamp" in d


class TestEntryRecord:
    """Tests for EntryRecord dataclass."""
    
    def test_create_entry_record(self):
        """Test creating an entry record."""
        record = EntryRecord(
            intent_id="entry_123",
            ticker="KXBTC15M-12345",
            asset="BTC",
            timestamp=datetime.utcnow(),
            price_cents=50,
            count=10,
            action="buy",
            risk_tier="A",
            window_resolution_id="wr_123",
            exit_policy_id="ep_123",
            planned_sl_price_cents=45,
            planned_tp_price_cents=60,
            max_hold_seconds=900,
        )
        assert record.intent_id == "entry_123"
        assert record.asset == "BTC"
        assert record.risk_tier == "A"


class TestRoundTripMonitor:
    """Tests for RoundTripMonitor."""
    
    @pytest.fixture
    def monitor(self):
        """Create a monitor instance."""
        return RoundTripMonitor(max_round_trips_per_day=20, sl_violation_threshold_cents=5)
    
    def test_record_entry(self, monitor):
        """Test recording an entry."""
        record = EntryRecord(
            intent_id="entry_123",
            ticker="KXBTC15M-12345",
            asset="BTC",
            timestamp=datetime.utcnow(),
            price_cents=50,
            count=10,
            action="buy",
            risk_tier="A",
            window_resolution_id="wr_123",
            exit_policy_id="ep_123",
            planned_sl_price_cents=45,
            planned_tp_price_cents=60,
            max_hold_seconds=900,
        )
        monitor.record_entry(record)
        assert "entry_123" in monitor._entries
        assert len(monitor._entries) == 1
    
    def test_record_exit(self, monitor):
        """Test recording an exit and completing a round trip."""
        entry = EntryRecord(
            intent_id="entry_123",
            ticker="KXBTC15M-12345",
            asset="BTC",
            timestamp=datetime.utcnow() - timedelta(minutes=5),
            price_cents=50,
            count=10,
            action="buy",
            risk_tier="A",
            window_resolution_id="wr_123",
            exit_policy_id="ep_123",
            planned_sl_price_cents=45,
            planned_tp_price_cents=60,
            max_hold_seconds=900,
        )
        monitor.record_entry(entry)
        
        round_trip = monitor.record_exit(
            exit_intent_id="exit_123",
            entry_intent_id="entry_123",
            exit_price_cents=55,
            exit_reason="tp",
        )
        
        assert round_trip is not None
        assert round_trip.asset == "BTC"
        assert round_trip.actual_exit_reason == "tp"
        assert round_trip.realized_pnl_cents == 50  # (55-50)*10
        assert "entry_123" not in monitor._entries  # Entry removed after exit
        assert len(monitor._round_trips) == 1
    
    def test_record_exit_entry_not_found(self, monitor):
        """Test recording exit when entry not found."""
        round_trip = monitor.record_exit(
            exit_intent_id="exit_123",
            entry_intent_id="nonexistent",
            exit_price_cents=55,
            exit_reason="tp",
        )
        assert round_trip is None
    
    def test_sl_violation_detection(self, monitor):
        """Test SL violation detection."""
        entry = EntryRecord(
            intent_id="entry_123",
            ticker="KXBTC15M-12345",
            asset="BTC",
            timestamp=datetime.utcnow() - timedelta(minutes=5),
            price_cents=50,
            count=10,
            action="buy",
            risk_tier="A",
            window_resolution_id="wr_123",
            exit_policy_id="ep_123",
            planned_sl_price_cents=45,  # SL at 45 cents
            max_hold_seconds=900,
        )
        monitor.record_entry(entry)
        
        # Exit below SL (violation) - need to be at least 6 cents below SL (45-5=40 threshold)
        round_trip = monitor.record_exit(
            exit_intent_id="exit_123",
            entry_intent_id="entry_123",
            exit_price_cents=39,  # 6 cents below SL (triggers violation since 39 < 40)
            exit_reason="sl",
        )
        
        assert round_trip is not None
        # Check that violation was detected
        metrics = monitor.get_asset_metrics("BTC")
        assert metrics.sl_violation_count > 0
    
    def test_manual_override_alert(self, monitor):
        """Test manual override alert generation."""
        entry = EntryRecord(
            intent_id="entry_123",
            ticker="KXBTC15M-12345",
            asset="BTC",
            timestamp=datetime.utcnow() - timedelta(minutes=5),
            price_cents=50,
            count=10,
            action="buy",
            risk_tier="A",
            window_resolution_id="wr_123",
            exit_policy_id="ep_123",
            max_hold_seconds=900,
        )
        monitor.record_entry(entry)
        
        # Exit with manual reason
        monitor.record_exit(
            exit_intent_id="exit_123",
            entry_intent_id="entry_123",
            exit_price_cents=55,
            exit_reason="manual",
        )
        
        alerts = monitor.get_recent_alerts()
        manual_alerts = [a for a in alerts if a.alert_type == "manual_override"]
        assert len(manual_alerts) > 0
    
    def test_get_asset_metrics(self, monitor):
        """Test getting asset metrics."""
        entry = EntryRecord(
            intent_id="entry_123",
            ticker="KXBTC15M-12345",
            asset="BTC",
            timestamp=datetime.utcnow() - timedelta(minutes=5),
            price_cents=50,
            count=10,
            action="buy",
            risk_tier="A",
            window_resolution_id="wr_123",
            exit_policy_id="ep_123",
            max_hold_seconds=900,
        )
        monitor.record_entry(entry)
        monitor.record_exit(
            exit_intent_id="exit_123",
            entry_intent_id="entry_123",
            exit_price_cents=55,
            exit_reason="tp",
        )
        
        metrics = monitor.get_asset_metrics("BTC")
        assert metrics is not None
        assert metrics.total_round_trips == 1
        assert metrics.tp_hit_count == 1
    
    def test_get_summary(self, monitor):
        """Test getting summary statistics."""
        summary = monitor.get_summary()
        assert summary["total_round_trips"] == 0
        assert summary["pending_entries"] == 0
        assert summary["total_alerts"] == 0
    
    def test_excessive_round_trips_alert(self, monitor):
        """Test excessive round trips alert."""
        # Create many round trips today
        for i in range(25):  # Exceeds max_round_trips_per_day=20
            entry = EntryRecord(
                intent_id=f"entry_{i}",
                ticker="KXBTC15M-12345",
                asset="BTC",
                timestamp=datetime.utcnow(),
                price_cents=50,
                count=10,
                action="buy",
                risk_tier="A",
                window_resolution_id=f"wr_{i}",
                exit_policy_id=f"ep_{i}",
                max_hold_seconds=900,
            )
            monitor.record_entry(entry)
            monitor.record_exit(
                exit_intent_id=f"exit_{i}",
                entry_intent_id=f"entry_{i}",
                exit_price_cents=55,
                exit_reason="tp",
            )
        
        alerts = monitor.get_recent_alerts()
        excessive_alerts = [a for a in alerts if a.alert_type == "excessive_round_trips"]
        assert len(excessive_alerts) > 0


class TestRoundTripMonitorSingleton:
    """Tests for the singleton pattern."""
    
    def test_get_singleton(self):
        """Test that get_round_trip_monitor returns the same instance."""
        from merid.event_venues.kalshi.round_trip_monitor import get_round_trip_monitor
        
        monitor1 = get_round_trip_monitor()
        monitor2 = get_round_trip_monitor()
        assert monitor1 is monitor2
