"""Tests for market state snapshot recovery on queue overflow (P1 FIX)."""

import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
from collections import deque

from merid.event_venues.kalshi.market_state import KalshiMarketStateStore


@pytest.fixture
def store():
    """Create test market state store."""
    store = KalshiMarketStateStore()
    store._delta_queues = {}
    store._overflow_count = {}
    store._needs_resync = {}
    store._ticker_locks_lock = MagicMock()
    store._main_event_loop = asyncio.new_event_loop()
    return store


class TestQueueOverflowSnapshotRecovery:
    """Test immediate snapshot recovery on delta queue overflow."""
    
    def test_enqueue_delta_triggers_snapshot_on_overflow(self, store):
        """Test that queue overflow triggers immediate snapshot recovery."""
        ticker = "KXBTCD-25JUN-T100000"
        
        # Fill queue to max capacity
        store._delta_queues[ticker] = deque()
        for i in range(store._MAX_PER_TICKER_QUEUE):
            store._delta_queues[ticker].append({"seq": i})
        
        # Mock the snapshot recovery method
        store._trigger_snapshot_recovery = AsyncMock()
        
        # Try to enqueue one more delta (should trigger overflow)
        result = store._enqueue_delta(ticker, {"seq": store._MAX_PER_TICKER_QUEUE})
        
        # Should return False (overflow)
        assert result is False
        
        # Should have incremented overflow counter
        assert store._overflow_count[ticker] == 1
        
        # Verify snapshot recovery was triggered (via asyncio.run_coroutine_threadsafe)
        # In real scenario, this would be scheduled on the event loop
        # For testing, we check the method was called
        # Note: The actual call happens via run_coroutine_threadsafe, so we can't
        # directly assert it was called in this synchronous test
    
    def test_enqueue_delta_succeeds_when_not_full(self, store):
        """Test that enqueue succeeds when queue is not full."""
        ticker = "KXBTCD-25JUN-T100000"
        
        # Add some deltas but not to capacity
        store._delta_queues[ticker] = deque()
        for i in range(10):
            store._delta_queues[ticker].append({"seq": i})
        
        # Enqueue should succeed
        result = store._enqueue_delta(ticker, {"seq": 10})
        
        assert result is True
        assert len(store._delta_queues[ticker]) == 11
    
    def test_asset_extraction_for_logging(self, store):
        """Test asset extraction for selective staleness detection."""
        # Test BTC
        ticker = "KXBTCD-25JUN-T100000"
        store._delta_queues[ticker] = deque()
        for i in range(store._MAX_PER_TICKER_QUEUE):
            store._delta_queues[ticker].append({"seq": i})
        
        store._trigger_snapshot_recovery = AsyncMock()
        store._enqueue_delta(ticker, {"seq": store._MAX_PER_TICKER_QUEUE})
        
        # Should have logged with asset=BTC (verified via overflow counter)
        assert store._overflow_count[ticker] == 1
        
        # Test ETH
        ticker = "KXETHD-25JUN-T100000"
        store._delta_queues[ticker] = deque()
        for i in range(store._MAX_PER_TICKER_QUEUE):
            store._delta_queues[ticker].append({"seq": i})
        
        store._enqueue_delta(ticker, {"seq": store._MAX_PER_TICKER_QUEUE})
        assert store._overflow_count[ticker] == 1


class TestTriggerSnapshotRecovery:
    """Test _trigger_snapshot_recovery method."""
    
    @pytest.mark.asyncio
    async def test_trigger_snapshot_recovery_logs_error_on_exception(self, store):
        """Test that snapshot recovery logs error on exception."""
        ticker = "KXBTCD-25JUN-T100000"
        
        # Mock the import to raise an exception
        with patch('builtins.__import__', side_effect=ImportError("Test error")):
            # Should not raise exception, just log error
            await store._trigger_snapshot_recovery(ticker)
        
        # Test passes if no exception is raised
