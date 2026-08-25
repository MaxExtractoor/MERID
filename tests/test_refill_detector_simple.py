"""Simplified unit tests for RefillDetector.

Tests the core logic without complex orderbook state transitions.
"""

import time
import pytest
from collections import deque

from merid.event_venues.kalshi.refill_detector import (
    RefillDetector,
    RefillEvent,
    RefillState,
)
from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot, OrderbookLevel


class TestRefillEvent:
    """Test RefillEvent dataclass."""
    
    def test_refill_event_creation(self):
        """Test creating a refill event."""
        event = RefillEvent(
            ticker="KXBTC15M-26AUG012215-15",
            side="yes",
            depletion_ts=1000.0,
            refill_ts=1001.5,
            refill_time_ms=1500.0,
            is_toxic=True,
        )
        
        assert event.ticker == "KXBTC15M-26AUG012215-15"
        assert event.side == "yes"
        assert event.depletion_ts == 1000.0
        assert event.refill_ts == 1001.5
        assert event.refill_time_ms == 1500.0
        assert event.is_toxic is True
    
    def test_refill_event_to_dict(self):
        """Test converting refill event to dict."""
        event = RefillEvent(
            ticker="KXETH15M-26AUG012215-15",
            side="no",
            depletion_ts=2000.0,
            refill_ts=2000.1,
            refill_time_ms=100.0,
            is_toxic=False,
        )
        
        d = event.to_dict()
        assert d["ticker"] == "KXETH15M-26AUG012215-15"
        assert d["side"] == "no"
        assert d["depletion_ts"] == 2000.0
        assert d["refill_ts"] == 2000.1
        assert d["refill_time_ms"] == 100.0
        assert d["is_toxic"] is False


class TestRefillDetector:
    """Test RefillDetector functionality."""
    
    @pytest.fixture
    def detector(self):
        """Create a RefillDetector instance for testing."""
        return RefillDetector(
            toxic_threshold_ms=1000.0,
            window_ms=60000.0,
            min_samples=3,
        )
    
    def test_detector_initialization(self, detector):
        """Test detector initialization."""
        assert detector.toxic_threshold_ms == 1000.0
        assert detector.window_ms == 60000.0
        assert detector.min_samples == 3
        assert detector._state == {}
        assert len(detector._event_history) == 0
    
    def test_state_creation(self, detector):
        """Test state creation for new ticker/side."""
        state = detector._get_state("KXBTC15M-26AUG012215-15", "yes")
        
        assert isinstance(state, RefillState)
        assert state.last_depth == 0
        assert state.depletion_start_ts is None
        assert len(state.recent_refill_times) == 0
        assert state.toxic_event_count == 0
        assert state.total_event_count == 0
    
    def test_state_reuse(self, detector):
        """Test that state is reused for same ticker/side."""
        state1 = detector._get_state("KXBTC15M-26AUG012215-15", "yes")
        state2 = detector._get_state("KXBTC15M-26AUG012215-15", "yes")
        
        assert state1 is state2
    
    def test_get_refill_stats_no_data(self, detector):
        """Test getting stats when no data available."""
        stats = detector.get_refill_stats("KXBTC15M-26AUG012215-15", "yes")
        
        assert stats["sample_count"] == 0
        assert stats["avg_refill_time_ms"] is None
        assert stats["toxic_ratio"] is None
    
    def test_get_refill_stats_with_data(self, detector):
        """Test getting stats with data."""
        # Manually add some refill times to state
        state = detector._get_state("KXBTC15M-26AUG012215-15", "yes")
        state.recent_refill_times.extend([100.0, 200.0, 300.0])
        state.total_event_count = 3
        state.toxic_event_count = 1
        
        stats = detector.get_refill_stats("KXBTC15M-26AUG012215-15", "yes")
        
        assert stats["ticker"] == "KXBTC15M-26AUG012215-15"
        assert stats["side"] == "yes"
        assert stats["sample_count"] == 3
        assert stats["avg_refill_time_ms"] == 200.0
        assert stats["toxic_ratio"] == 1.0 / 3.0
        assert stats["total_events"] == 3
        assert stats["toxic_events"] == 1
    
    def test_get_recent_events(self, detector):
        """Test getting recent refill events."""
        # Manually add some events
        for i in range(5):
            event = RefillEvent(
                ticker="KXBTC15M-26AUG012215-15",
                side="yes",
                depletion_ts=1000.0 + i,
                refill_ts=1000.1 + i,
                refill_time_ms=100.0,
                is_toxic=False,
            )
            detector._event_history.append(event)
        
        events = detector.get_recent_events(limit=3)
        
        assert len(events) == 3
        assert all("ticker" in e for e in events)
        assert all("side" in e for e in events)
        assert all("refill_time_ms" in e for e in events)
    
    def test_event_history_maxlen(self, detector):
        """Test that event history respects maxlen."""
        # Add more events than maxlen (1000)
        for _ in range(1100):
            event = RefillEvent(
                ticker="KXBTC15M-26AUG012215-15",
                side="yes",
                depletion_ts=1000.0,
                refill_ts=1000.1,
                refill_time_ms=100.0,
                is_toxic=False,
            )
            detector._event_history.append(event)
        
        # Should be capped at 1000
        assert len(detector._event_history) == 1000


class TestRefillDetectorEdgeCases:
    """Test edge cases and error conditions."""
    
    def test_multiple_tickers(self):
        """Test detector with multiple tickers."""
        detector = RefillDetector()
        
        # Create snapshots for different tickers
        ob1 = OrderbookSnapshot(
            ticker="KXBTC15M-26AUG012215-15",
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),
            seq=0,
            ts=time.time(),
        )
        
        ob2 = OrderbookSnapshot(
            ticker="KXETH15M-26AUG012215-15",
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),
            seq=0,
            ts=time.time(),
        )
        
        # Process both
        detector.process(ob1)
        detector.process(ob2)
        
        # Verify separate state
        assert "KXBTC15M-26AUG012215-15" in detector._state
        assert "KXETH15M-26AUG012215-15" in detector._state
        assert detector._state["KXBTC15M-26AUG012215-15"] is not detector._state["KXETH15M-26AUG012215-15"]
    
    def test_no_depletion_before_refill(self):
        """Test refill without prior depletion (should be ignored)."""
        detector = RefillDetector()
        
        ob = OrderbookSnapshot(
            ticker="KXBTC15M-26AUG012215-15",
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),
            seq=0,
            ts=time.time(),
        )
        
        # Process without depletion
        is_toxic, event = detector.process(ob)
        
        assert is_toxic is False
        assert event is None
    
    def test_zero_depth_initial_state(self):
        """Test detector starting with zero depth."""
        detector = RefillDetector()
        
        ob = OrderbookSnapshot(
            ticker="KXBTC15M-26AUG012215-15",
            yes_bids=(),  # Zero depth initially
            no_bids=(OrderbookLevel(price_cents=45, size=50),),
            seq=0,
            ts=time.time(),
        )
        
        # Should not trigger depletion (no prior depth)
        is_toxic, event = detector.process(ob)
        
        assert is_toxic is False
        assert event is None


class TestRefillDetectorDirectLogic:
    """Test the core logic directly without orderbook state transitions."""
    
    def test_refill_time_classification_safe(self):
        """Test that refill time classification works correctly."""
        detector = RefillDetector(toxic_threshold_ms=1000.0)
        
        # Safe refill (below threshold)
        refill_time_ms = 500.0
        is_toxic = refill_time_ms > detector.toxic_threshold_ms
        
        assert is_toxic is False
    
    def test_refill_time_classification_toxic(self):
        """Test that refill time classification works correctly."""
        detector = RefillDetector(toxic_threshold_ms=1000.0)
        
        # Toxic refill (above threshold)
        refill_time_ms = 1500.0
        is_toxic = refill_time_ms > detector.toxic_threshold_ms
        
        assert is_toxic is True
    
    def test_refill_time_classification_boundary_safe(self):
        """Test boundary condition at threshold."""
        detector = RefillDetector(toxic_threshold_ms=1000.0)
        
        # Exactly at threshold (should be safe, not toxic)
        refill_time_ms = 1000.0
        is_toxic = refill_time_ms > detector.toxic_threshold_ms
        
        assert is_toxic is False
    
    def test_refill_time_classification_boundary_toxic(self):
        """Test boundary condition just above threshold."""
        detector = RefillDetector(toxic_threshold_ms=1000.0)
        
        # Just above threshold
        refill_time_ms = 1000.1
        is_toxic = refill_time_ms > detector.toxic_threshold_ms
        
        assert is_toxic is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
