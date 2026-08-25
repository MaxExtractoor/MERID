"""Unit tests for RefillDetector.

Tests the refill time detection system for classifying toxic vs uninformed flow
in sparse liquidity conditions, based on Electronic Trading Hub research (2023).
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
    
    @pytest.fixture
    def mock_orderbook(self):
        """Create a mock OrderbookSnapshot for testing.
        
        Respects Kalshi's YES/NO duality: yes_ask = 100 - no_bid
        """
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot
        
        return OrderbookSnapshot(
            ticker="KXBTC15M-26AUG012215-15",
            yes_bids=(
                OrderbookLevel(price_cents=50, size=100),
            ),
            no_bids=(
                OrderbookLevel(price_cents=45, size=50),  # yes_ask = 100 - 45 = 55
            ),
            seq=0,
            ts=time.time(),
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
    
    def test_depletion_detection(self, detector, mock_orderbook):
        """Test detection of liquidity depletion."""
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot
        
        # First snapshot with depth
        is_toxic, event = detector.process(mock_orderbook)
        assert is_toxic is False
        assert event is None
        
        # Second snapshot with zero depth (depletion)
        mock_orderbook_depleted = OrderbookSnapshot(
            ticker=mock_orderbook.ticker,
            yes_bids=(),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),  # Deplete YES side only; keep NO side to avoid interference
            seq=mock_orderbook.seq,
            ts=time.time(),
        )
        is_toxic, event = detector.process(mock_orderbook_depleted)
        assert is_toxic is False
        assert event is None
        
        # Verify depletion was tracked
        state = detector._get_state(mock_orderbook.ticker, "yes")
        assert state.depletion_start_ts is not None
    
    def test_safe_refill_detection(self, detector, mock_orderbook):
        """Test detection of safe refill (fast refill)."""
        # Create a fresh detector for this test to avoid state interference
        detector = RefillDetector()
        
        # Start with depth
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot
        mock_orderbook_with_depth = OrderbookSnapshot(
            ticker=mock_orderbook.ticker,
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),
            seq=mock_orderbook.seq,
            ts=time.time(),
        )
        detector.process(mock_orderbook_with_depth)
        
        # Deplete YES side only
        mock_orderbook_depleted = OrderbookSnapshot(
            ticker=mock_orderbook.ticker,
            yes_bids=(),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),  # Keep NO side
            seq=mock_orderbook.seq,
            ts=time.time(),
        )
        detector.process(mock_orderbook_depleted)
        
        # Refill quickly (safe)
        time.sleep(0.05)  # 50ms
        mock_orderbook_refilled = OrderbookSnapshot(
            ticker=mock_orderbook.ticker,
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),
            seq=mock_orderbook.seq,
            ts=time.time(),
        )
        is_toxic, event = detector.process(mock_orderbook_refilled)
        
        assert is_toxic is False
        assert event is not None
        assert event.refill_time_ms < 1000.0
        assert event.is_toxic is False
    
    def test_toxic_refill_detection(self, detector, mock_orderbook):
        """Test detection of toxic refill (slow refill)."""
        # Create a fresh detector for this test
        detector = RefillDetector()
        
        # Start with depth
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot
        mock_orderbook_with_depth = OrderbookSnapshot(
            ticker=mock_orderbook.ticker,
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),
            seq=mock_orderbook.seq,
            ts=time.time(),
        )
        detector.process(mock_orderbook_with_depth)
        
        # Deplete
        mock_orderbook_depleted = OrderbookSnapshot(
            ticker=mock_orderbook.ticker,
            yes_bids=(),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),
            seq=mock_orderbook.seq,
            ts=time.time(),
        )
        detector.process(mock_orderbook_depleted)
        
        # Refill slowly (toxic)
        time.sleep(1.1)  # 1100ms > 1000ms threshold
        mock_orderbook_refilled = OrderbookSnapshot(
            ticker=mock_orderbook.ticker,
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),
            seq=mock_orderbook.seq,
            ts=time.time(),
        )
        is_toxic, event = detector.process(mock_orderbook_refilled)
        
        assert is_toxic is True
        assert event is not None
        assert event.refill_time_ms > 1000.0
        assert event.is_toxic is True
    
    def test_no_side_state(self, detector, mock_orderbook):
        """Test refill detection on NO side."""
        # Establish baseline depth (depletion requires a transition from >0 to 0)
        detector.process(mock_orderbook)
        # Deplete NO side
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot
        mock_orderbook_depleted = OrderbookSnapshot(
            ticker=mock_orderbook.ticker,
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(),
            seq=mock_orderbook.seq,
            ts=time.time(),
        )
        detector.process(mock_orderbook_depleted)
        
        # Refill NO side
        time.sleep(0.05)
        mock_orderbook_refilled = OrderbookSnapshot(
            ticker=mock_orderbook.ticker,
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(OrderbookLevel(price_cents=50, size=50),),
            seq=mock_orderbook.seq,
            ts=time.time(),
        )
        is_toxic, event = detector.process(mock_orderbook_refilled)
        
        assert is_toxic is False
        assert event is not None
        assert event.side == "no"
    
    def test_toxicity_based_on_history(self, detector, mock_orderbook):
        """Test toxicity classification based on recent history."""
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot
        # Establish baseline depth (depletion requires a transition from >0 to 0)
        detector.process(mock_orderbook)
        # Generate multiple toxic events
        for _ in range(3):
            # Deplete
            mock_orderbook_depleted = OrderbookSnapshot(
                ticker=mock_orderbook.ticker,
                yes_bids=(),
                no_bids=(OrderbookLevel(price_cents=45, size=50),),  # Deplete YES side only; keep NO side to avoid interference
                seq=mock_orderbook.seq,
                ts=time.time(),
            )
            detector.process(mock_orderbook_depleted)
            
            # Refill slowly (toxic)
            time.sleep(1.1)
            mock_orderbook_refilled = OrderbookSnapshot(
                ticker=mock_orderbook.ticker,
                yes_bids=(OrderbookLevel(price_cents=50, size=100),),
                no_bids=(OrderbookLevel(price_cents=45, size=50),),  # Deplete YES side only; keep NO side to avoid interference
                seq=mock_orderbook.seq,
                ts=time.time(),
            )
            detector.process(mock_orderbook_refilled)
        
        # Check state
        state = detector._get_state(mock_orderbook.ticker, "yes")
        assert state.total_event_count == 3
        assert state.toxic_event_count == 3
        
        # Should be toxic based on history
        is_toxic, _ = detector.process(mock_orderbook)
        assert is_toxic is True
    
    def test_get_refill_stats(self, detector, mock_orderbook):
        """Test getting refill statistics."""
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot
        # Establish baseline depth (depletion requires a transition from >0 to 0)
        detector.process(mock_orderbook)
        # Generate some refill events
        for i in range(5):
            # Deplete
            mock_orderbook_depleted = OrderbookSnapshot(
                ticker=mock_orderbook.ticker,
                yes_bids=(),
                no_bids=(OrderbookLevel(price_cents=45, size=50),),  # Deplete YES side only; keep NO side to avoid interference
                seq=mock_orderbook.seq,
                ts=time.time(),
            )
            detector.process(mock_orderbook_depleted)
            
            # Refill with varying times
            time.sleep(0.05 if i % 2 == 0 else 1.1)
            mock_orderbook_refilled = OrderbookSnapshot(
                ticker=mock_orderbook.ticker,
                yes_bids=(OrderbookLevel(price_cents=50, size=100),),
                no_bids=(OrderbookLevel(price_cents=45, size=50),),  # Deplete YES side only; keep NO side to avoid interference
                seq=mock_orderbook.seq,
                ts=time.time(),
            )
            detector.process(mock_orderbook_refilled)
        
        stats = detector.get_refill_stats(mock_orderbook.ticker, "yes")
        
        assert stats["ticker"] == mock_orderbook.ticker
        assert stats["side"] == "yes"
        assert stats["sample_count"] == 5
        assert stats["avg_refill_time_ms"] is not None
        assert stats["toxic_ratio"] is not None
        assert stats["total_events"] == 5
        assert stats["toxic_events"] == 2  # Every other one was toxic
    
    def test_get_refill_stats_no_data(self, detector):
        """Test getting stats when no data available."""
        stats = detector.get_refill_stats("KXBTC15M-26AUG012215-15", "yes")
        
        assert stats["sample_count"] == 0
        assert stats["avg_refill_time_ms"] is None
        assert stats["toxic_ratio"] is None
    
    def test_get_recent_events(self, detector, mock_orderbook):
        """Test getting recent refill events."""
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot
        # Generate some events
        for _ in range(5):
            mock_orderbook_depleted = OrderbookSnapshot(
                ticker=mock_orderbook.ticker,
                yes_bids=(),
                no_bids=(OrderbookLevel(price_cents=45, size=50),),  # Deplete YES side only; keep NO side to avoid interference
                seq=mock_orderbook.seq,
                ts=time.time(),
            )
            detector.process(mock_orderbook_depleted)
            time.sleep(0.05)
            mock_orderbook_refilled = OrderbookSnapshot(
                ticker=mock_orderbook.ticker,
                yes_bids=(OrderbookLevel(price_cents=50, size=100),),
                no_bids=(OrderbookLevel(price_cents=45, size=50),),  # Deplete YES side only; keep NO side to avoid interference
                seq=mock_orderbook.seq,
                ts=time.time(),
            )
            detector.process(mock_orderbook_refilled)
        
        events = detector.get_recent_events(limit=3)
        
        assert len(events) == 3
        assert all("ticker" in e for e in events)
        assert all("side" in e for e in events)
        assert all("refill_time_ms" in e for e in events)
    
    def test_event_history_maxlen(self, detector, mock_orderbook):
        """Test that event history respects maxlen."""
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot
        # Generate more events than maxlen (1000)
        for _ in range(1100):
            mock_orderbook_depleted = OrderbookSnapshot(
                ticker=mock_orderbook.ticker,
                yes_bids=(),
                no_bids=(OrderbookLevel(price_cents=45, size=50),),  # Deplete YES side only; keep NO side to avoid interference
                seq=mock_orderbook.seq,
                ts=time.time(),
            )
            detector.process(mock_orderbook_depleted)
            time.sleep(0.001)
            mock_orderbook_refilled = OrderbookSnapshot(
                ticker=mock_orderbook.ticker,
                yes_bids=(OrderbookLevel(price_cents=50, size=100),),
                no_bids=(OrderbookLevel(price_cents=45, size=50),),  # Deplete YES side only; keep NO side to avoid interference
                seq=mock_orderbook.seq,
                ts=time.time(),
            )
            detector.process(mock_orderbook_refilled)
        
        # Should be capped at 1000
        assert len(detector._event_history) == 1000


class TestRefillDetectorEdgeCases:
    """Test edge cases and error conditions."""
    
    def test_multiple_tickers(self):
        """Test detector with multiple tickers."""
        detector = RefillDetector()
        
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot
        
        # Create snapshots for different tickers
        ob1 = OrderbookSnapshot(
            ticker="KXBTC15M-26AUG012215-15",
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),  # Deplete YES side only; keep NO side to avoid interference
            seq=0,
            ts=time.time(),
        )
        
        ob2 = OrderbookSnapshot(
            ticker="KXETH15M-26AUG012215-15",
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),  # Deplete YES side only; keep NO side to avoid interference
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
        
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot
        
        ob = OrderbookSnapshot(
            ticker="KXBTC15M-26AUG012215-15",
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),  # Deplete YES side only; keep NO side to avoid interference
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
        
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot
        
        ob = OrderbookSnapshot(
            ticker="KXBTC15M-26AUG012215-15",
            yes_bids=(),  # Zero depth initially
            no_bids=(OrderbookLevel(price_cents=45, size=50),),  # Deplete YES side only; keep NO side to avoid interference
            seq=0,
            ts=time.time(),
        )
        
        # Should not trigger depletion (no prior depth)
        is_toxic, event = detector.process(ob)
        
        assert is_toxic is False
        assert event is None
    
    def test_boundary_condition_safe_refill(self):
        """Test refill just below threshold (boundary condition)."""
        detector = RefillDetector(toxic_threshold_ms=1000.0)
        
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot

        # Establish baseline depth (depletion requires a transition from >0 to 0)
        detector.process(OrderbookSnapshot(
            ticker="KXBTC15M-26AUG012215-15",
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),
            seq=0,
            ts=time.time(),
        ))

        # Deplete
        mock_orderbook_depleted = OrderbookSnapshot(
            ticker="KXBTC15M-26AUG012215-15",
            yes_bids=(),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),  # Deplete YES side only; keep NO side to avoid interference
            seq=0,
            ts=time.time(),
        )
        detector.process(mock_orderbook_depleted)

        # Refill at 950ms (just below threshold - should be safe)
        time.sleep(0.95)
        mock_orderbook_refilled = OrderbookSnapshot(
            ticker="KXBTC15M-26AUG012215-15",
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),  # Deplete YES side only; keep NO side to avoid interference
            seq=0,
            ts=time.time(),
        )
        is_toxic, event = detector.process(mock_orderbook_refilled)
        
        assert is_toxic is False
        assert event is not None
        assert event.refill_time_ms < 1000.0
        assert event.is_toxic is False
    
    def test_boundary_condition_toxic_refill(self):
        """Test refill just above threshold (boundary condition)."""
        detector = RefillDetector(toxic_threshold_ms=1000.0)
        
        from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot

        # Establish baseline depth (depletion requires a transition from >0 to 0)
        detector.process(OrderbookSnapshot(
            ticker="KXBTC15M-26AUG012215-15",
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),
            seq=0,
            ts=time.time(),
        ))

        # Deplete
        mock_orderbook_depleted = OrderbookSnapshot(
            ticker="KXBTC15M-26AUG012215-15",
            yes_bids=(),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),  # Deplete YES side only; keep NO side to avoid interference
            seq=0,
            ts=time.time(),
        )
        detector.process(mock_orderbook_depleted)

        # Refill at 1050ms (just above threshold - should be toxic)
        time.sleep(1.05)
        mock_orderbook_refilled = OrderbookSnapshot(
            ticker="KXBTC15M-26AUG012215-15",
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(OrderbookLevel(price_cents=45, size=50),),  # Deplete YES side only; keep NO side to avoid interference
            seq=0,
            ts=time.time(),
        )
        is_toxic, event = detector.process(mock_orderbook_refilled)
        
        assert is_toxic is True
        assert event is not None
        assert event.refill_time_ms > 1000.0
        assert event.is_toxic is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
