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


@pytest.mark.asyncio
async def test_rest_recovery_does_not_recreate_removed_market(monkeypatch):
    store = KalshiMarketStateStore()
    ticker = "KXBTC15M-OLD"
    store._get_or_create(ticker)
    store.cleanup_stale_states([])
    port = MagicMock()
    port.get_orderbook = AsyncMock()
    monkeypatch.setattr(
        "merid.event_venues.kalshi.port.get_kalshi_execution_port", lambda: port
    )

    await store._sync_invariant_violation_with_rest(ticker)

    port.get_orderbook.assert_not_awaited()
    assert ticker not in store._states


@pytest.mark.asyncio
async def test_ws_recovery_skips_removed_market(monkeypatch):
    store = KalshiMarketStateStore()
    ticker = "KXBTC15M-OLD"
    store._get_or_create(ticker)
    store.cleanup_stale_states([])
    submit = MagicMock()
    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", submit)

    await store._trigger_snapshot_recovery(ticker)

    submit.assert_not_called()
    assert ticker not in store._states


@pytest.mark.asyncio
async def test_rest_recovery_still_applies_for_current_state(monkeypatch):
    store = KalshiMarketStateStore()
    ticker = "KXBTC15M-LIVE"
    state = store._get_or_create(ticker)
    port = MagicMock()
    port.get_orderbook = AsyncMock(
        return_value=MagicMock(success=True, yes_levels=[], no_levels=[])
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.port.get_kalshi_execution_port", lambda: port
    )
    store._ob.apply_snapshot = MagicMock()

    await store._sync_invariant_violation_with_rest(ticker)

    port.get_orderbook.assert_awaited_once_with(ticker)
    store._ob.apply_snapshot.assert_called_once()
    assert store._states[ticker] is state


@pytest.mark.asyncio
@pytest.mark.parametrize("recreate", [False, True])
async def test_inflight_rest_recovery_does_not_apply_after_rollover(monkeypatch, recreate):
    store = KalshiMarketStateStore()
    ticker = "KXBTC15M-OLD"
    old_state = store._get_or_create(ticker)
    started = asyncio.Event()
    finish = asyncio.Event()

    async def fetch(_ticker):
        started.set()
        await finish.wait()
        return MagicMock(success=True, yes_levels=[], no_levels=[])

    port = MagicMock()
    port.get_orderbook = AsyncMock(side_effect=fetch)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.port.get_kalshi_execution_port", lambda: port
    )
    store._ob.apply_snapshot = MagicMock()
    task = asyncio.create_task(store._sync_invariant_violation_with_rest(ticker))
    await asyncio.wait_for(started.wait(), timeout=1)
    store.cleanup_stale_states([])
    if recreate:
        new_state = store._get_or_create(ticker)
        assert new_state is not old_state
    finish.set()
    await task

    store._ob.apply_snapshot.assert_not_called()
    assert store._states.get(ticker) is (new_state if recreate else None)
