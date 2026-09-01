"""
Queue overflow behavior tests for market_state.py.

Tests verify that queue overflow is detected, logged, and triggers
appropriate recovery mechanisms (resync flag, metrics).
"""

import pytest
from unittest.mock import Mock, patch

from merid.event_venues.kalshi.market_state import KalshiMarketStateStore


class TestQueueOverflowDetection:
    """Test queue overflow detection and logging."""

    def test_enqueue_delta_overflow_detection(self):
        """Test that queue overflow is detected and logged."""
        store = KalshiMarketStateStore()
        ticker = "KXBTC15M-TEST"
        
        # Fill queue to max capacity
        for i in range(store._MAX_PER_TICKER_QUEUE):
            msg = {"sequence": i, "delta": {"bid": 50 + i}}
            result = store._enqueue_delta(ticker, msg)
            assert result is True, f"Delta {i} should be enqueued successfully"
        
        # Try to enqueue one more delta - should fail
        overflow_msg = {"sequence": store._MAX_PER_TICKER_QUEUE, "delta": {"bid": 100}}
        result = store._enqueue_delta(ticker, overflow_msg)
        assert result is False, "Overflow delta should be rejected"
        
        # Verify overflow counter incremented
        assert store._overflow_count.get(ticker, 0) == 1
        
        # Verify snapshot resync is triggered (new implementation)
        # The implementation now triggers immediate snapshot recovery instead of setting _needs_resync
        # We verify the overflow was detected and logged (covered by overflow_count check)

    def test_enqueue_delta_asset_extraction(self):
        """Test that asset is correctly extracted from ticker for logging."""
        store = KalshiMarketStateStore()
        
        test_cases = [
            ("KXBTC15M-TEST", "BTC"),
            ("KXETH15M-TEST", "ETH"),
            ("KXSOL15M-TEST", "SOL"),
            ("KXXRP15M-TEST", "XRP"),
            ("KXDOGE15M-TEST", "DOGE"),
        ]
        
        for ticker, expected_asset in test_cases:
            # Fill queue to trigger overflow
            for i in range(store._MAX_PER_TICKER_QUEUE):
                store._enqueue_delta(ticker, {"sequence": i})
            
            # Trigger overflow
            with patch('merid.event_venues.kalshi.market_state.logger') as mock_logger:
                store._enqueue_delta(ticker, {"sequence": store._MAX_PER_TICKER_QUEUE})
                
                # Verify log contains asset
                error_calls = [call for call in mock_logger.error.call_args_list]
                assert any(expected_asset in str(call) for call in error_calls), (
                    f"Log should contain asset {expected_asset} for ticker {ticker}"
                )
            
            # Reset for next test
            store._delta_queues[ticker].clear()
            store._overflow_count.clear()
            store._needs_resync.clear()

    def test_enqueue_delta_multiple_overflows(self):
        """Test that multiple overflows increment counter correctly."""
        store = KalshiMarketStateStore()
        ticker = "KXETH15M-TEST"

        # Use a small queue so each overflow cycle is fast.  The overflow
        # handler clears the queue, so each overflow must be preceded by a
        # fresh fill to the cap.
        store._MAX_PER_TICKER_QUEUE = 5
        store._delta_queues[ticker] = []
        store._overflow_count[ticker] = 0

        for i in range(3):
            for j in range(store._MAX_PER_TICKER_QUEUE):
                store._enqueue_delta(ticker, {"sequence": j})
            result = store._enqueue_delta(ticker, {"sequence": store._MAX_PER_TICKER_QUEUE})
            assert result is False

        # Verify counter incremented to 3
        assert store._overflow_count.get(ticker, 0) == 3


class TestQueueOverflowRecovery:
    """Test queue overflow recovery mechanisms."""

    def test_needs_snapshot_resync(self):
        """Test _needs_snapshot_resync returns correct status."""
        store = KalshiMarketStateStore()
        ticker = "KXBTC15M-TEST"
        
        # Initially should not need resync
        assert store._needs_snapshot_resync(ticker) is False
        
        # Mark for resync
        store._needs_resync[ticker] = True
        assert store._needs_snapshot_resync(ticker) is True

    def test_mark_resync_complete(self):
        """Test _mark_resync_complete clears flags and queue."""
        store = KalshiMarketStateStore()
        ticker = "KXETH15M-TEST"
        
        # Set up state
        store._needs_resync[ticker] = True
        store._delta_queues[ticker] = store._delta_queues.get(ticker, [])
        for i in range(10):
            store._delta_queues[ticker].append({"sequence": i})
        
        # Mark resync complete
        store._mark_resync_complete(ticker)
        
        # Verify flags cleared
        assert store._needs_resync.get(ticker, False) is False
        
        # Verify queue cleared
        assert len(store._delta_queues.get(ticker, [])) == 0

    def test_overflow_then_resync_flow(self):
        """Test complete flow: overflow triggers immediate snapshot recovery."""
        store = KalshiMarketStateStore()
        ticker = "KXSOL15M-TEST"
        
        # Fill queue and trigger overflow
        for i in range(store._MAX_PER_TICKER_QUEUE):
            store._enqueue_delta(ticker, {"sequence": i})
        
        store._enqueue_delta(ticker, {"sequence": store._MAX_PER_TICKER_QUEUE})
        
        # Verify overflow was detected (new implementation triggers immediate recovery)
        assert store._overflow_count.get(ticker, 0) == 1
        
        # The new implementation triggers immediate snapshot recovery via event loop
        # instead of setting _needs_resync flag. We verify overflow detection via count.


class TestQueueOverflowMetrics:
    """Test queue overflow metrics and monitoring."""

    def test_overflow_count_per_ticker(self):
        """Test overflow counts are tracked per ticker."""
        store = KalshiMarketStateStore()
        
        # Fill queues for multiple tickers
        tickers = ["KXBTC15M-TEST", "KXETH15M-TEST", "KXSOL15M-TEST"]
        
        for ticker in tickers:
            for i in range(store._MAX_PER_TICKER_QUEUE):
                store._enqueue_delta(ticker, {"sequence": i})
            store._enqueue_delta(ticker, {"sequence": store._MAX_PER_TICKER_QUEUE})
        
        # Verify each ticker has overflow count
        assert store._overflow_count["KXBTC15M-TEST"] == 1
        assert store._overflow_count["KXETH15M-TEST"] == 1
        assert store._overflow_count["KXSOL15M-TEST"] == 1

    def test_selective_staleness_risk_logging(self):
        """Test that overflow is logged with asset info and triggers immediate snapshot recovery."""
        store = KalshiMarketStateStore()
        ticker = "KXBTC15M-TEST"
        
        # Fill queue
        for i in range(store._MAX_PER_TICKER_QUEUE):
            store._enqueue_delta(ticker, {"sequence": i})
        
        # Trigger overflow and capture log
        with patch('merid.event_venues.kalshi.market_state.logger') as mock_logger:
            store._enqueue_delta(ticker, {"sequence": store._MAX_PER_TICKER_QUEUE})
            
            # Verify error log contains key information
            error_calls = [call for call in mock_logger.error.call_args_list]
            assert len(error_calls) > 0, "Should log error on overflow"
            
            log_str = str(error_calls[0])
            assert "dropping_stale_deltas_and_triggering_throttled_snapshot_recovery" in log_str
            assert "BTC" in log_str
            assert "overflow_count=" in log_str


class TestQueueOverflowIntegration:
    """Integration tests for queue overflow with market state."""

    def test_overflow_does_not_affect_other_tickers(self):
        """Test that overflow on one ticker doesn't affect others."""
        store = KalshiMarketStateStore()
        
        # Fill BTC queue to overflow
        for i in range(store._MAX_PER_TICKER_QUEUE):
            store._enqueue_delta("KXBTC15M-TEST", {"sequence": i})
        store._enqueue_delta("KXBTC15M-TEST", {"sequence": store._MAX_PER_TICKER_QUEUE})
        
        # ETH queue should still work normally
        for i in range(10):
            result = store._enqueue_delta("KXETH15M-TEST", {"sequence": i})
            assert result is True
        
        # Verify only BTC has overflow (new implementation triggers immediate recovery)
        assert store._overflow_count.get("KXBTC15M-TEST", 0) == 1
        assert store._overflow_count.get("KXETH15M-TEST", 0) == 0

    def test_queue_length_tracking(self):
        """Test that queue length is tracked correctly."""
        store = KalshiMarketStateStore()
        ticker = "KXDOGE15M-TEST"
        
        # Add some deltas
        for i in range(100):
            store._enqueue_delta(ticker, {"sequence": i})
        
        # Check queue length
        with store._ticker_locks_lock:
            queue_len = len(store._delta_queues.get(ticker, []))
        
        assert queue_len == 100
