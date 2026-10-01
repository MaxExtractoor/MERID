"""Tests for WebSocket bridge sequence gap detection and message deduplication.

2026-07-08: Added sequence gap detection for orderbook events and message deduplication
to prevent duplicate message processing.

Run: py -m pytest tests/test_ws_bridge_sequence_and_dedup.py -v
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from typing import Dict, Any


class TestSequenceGapDetectionLogic:
    """Tests for sequence gap detection logic (unit tests for the algorithm)."""
    
    def test_sequence_gap_detection_algorithm(self):
        """Test the sequence gap detection algorithm logic."""
        # Simulate the sequence gap detection logic
        last_sequence = None
        sequence_gaps = 0
        sequence_gaps_list = []
        
        sequences = [1, 2, 5, 6]  # Gap: 3, 4 missing
        
        for seq in sequences:
            if last_sequence is not None:
                expected = last_sequence + 1
                if seq > expected:
                    gap = seq - expected
                    sequence_gaps += gap
                    sequence_gaps_list.append((expected, seq - 1))
            last_sequence = seq
        
        # Verify gap was detected
        assert sequence_gaps == 2, "Should detect 2 missing sequences"
        assert sequence_gaps_list == [(3, 4)], "Gap should be (3, 4)"
    
    def test_no_sequence_gap_with_consecutive_sequences(self):
        """Test that no gap is detected with consecutive sequences."""
        last_sequence = None
        sequence_gaps = 0
        sequence_gaps_list = []
        
        sequences = [1, 2, 3]  # No gaps
        
        for seq in sequences:
            if last_sequence is not None:
                expected = last_sequence + 1
                if seq > expected:
                    gap = seq - expected
                    sequence_gaps += gap
                    sequence_gaps_list.append((expected, seq - 1))
            last_sequence = seq
        
        # Verify no gap was detected
        assert sequence_gaps == 0, "No sequence gap should be detected"
        assert len(sequence_gaps_list) == 0, "Gap list should be empty"
    
    def test_multiple_sequence_gaps(self):
        """Test detection of multiple sequence gaps."""
        last_sequence = None
        sequence_gaps = 0
        sequence_gaps_list = []
        
        sequences = [1, 2, 5, 10]  # Gaps: 3,4 and 6,7,8,9
        
        for seq in sequences:
            if last_sequence is not None:
                expected = last_sequence + 1
                if seq > expected:
                    gap = seq - expected
                    sequence_gaps += gap
                    sequence_gaps_list.append((expected, seq - 1))
            last_sequence = seq
        
        # Verify gaps were detected
        assert sequence_gaps == 6, "Should detect 6 missing sequences"
        assert sequence_gaps_list == [(3, 4), (6, 9)], "Gaps should be (3,4) and (6,9)"


class TestMessageDeduplicationLogic:
    """Tests for message deduplication logic (unit tests for the algorithm)."""
    
    def test_message_deduplication_with_hash(self):
        """Test message deduplication using hash-based approach."""
        import hashlib
        
        message_cache = {}
        message_cache_size = 1000
        events_dropped = 0
        
        # Send the same event twice
        event1 = {"type": "orderbook_delta", "ticker": "KXBTC15M-26JUL050730-30", "seq": 1}
        event2 = {"type": "orderbook_delta", "ticker": "KXBTC15M-26JUL050730-30", "seq": 1}
        
        for event in [event1, event2]:
            ticker = event.get("ticker")
            event_type = event.get("type")
            if ticker and event_type:
                event_str = f"{ticker}:{event_type}:{str(event.get('seq', ''))}"
                event_hash = hashlib.md5(event_str.encode()).hexdigest()
                
                if ticker in message_cache:
                    if message_cache[ticker].get("hash") == event_hash:
                        events_dropped += 1
                        continue
                
                if len(message_cache) >= message_cache_size:
                    oldest_ticker = next(iter(message_cache))
                    del message_cache[oldest_ticker]
                
                message_cache[ticker] = {"hash": event_hash, "ts": 0}
        
        # Verify duplicate was dropped
        assert events_dropped == 1, "One duplicate event should be dropped"
        assert len(message_cache) == 1, "Cache should have one entry"
    
    def test_different_events_not_deduplicated(self):
        """Test that different events are not deduplicated."""
        import hashlib
        
        message_cache = {}
        message_cache_size = 1000
        events_dropped = 0
        events_processed = 0
        
        # Send different events
        events = [
            {"type": "orderbook_delta", "ticker": "KXBTC15M-26JUL050730-30", "seq": 1},
            {"type": "orderbook_delta", "ticker": "KXBTC15M-26JUL050730-30", "seq": 2},
            {"type": "orderbook_delta", "ticker": "KXETH15M-26JUL050730-30", "seq": 1},
        ]
        
        for event in events:
            ticker = event.get("ticker")
            event_type = event.get("type")
            if ticker and event_type:
                event_str = f"{ticker}:{event_type}:{str(event.get('seq', ''))}"
                event_hash = hashlib.md5(event_str.encode()).hexdigest()
                
                if ticker in message_cache:
                    if message_cache[ticker].get("hash") == event_hash:
                        events_dropped += 1
                        continue
                
                if len(message_cache) >= message_cache_size:
                    oldest_ticker = next(iter(message_cache))
                    del message_cache[oldest_ticker]
                
                message_cache[ticker] = {"hash": event_hash, "ts": 0}
                events_processed += 1
        
        # Verify no duplicates were dropped
        assert events_dropped == 0, "No duplicates should be dropped"
        assert events_processed == 3, "All 3 events should be processed"
    
    def test_message_cache_size_limit(self):
        """Test that message cache respects size limit."""
        import hashlib
        
        message_cache = {}
        message_cache_size = 3
        
        # Send events for different tickers
        events = [
            {"type": "orderbook_delta", "ticker": "KXBTC15M-26JUL050730-30", "seq": 1},
            {"type": "orderbook_delta", "ticker": "KXETH15M-26JUL050730-30", "seq": 1},
            {"type": "orderbook_delta", "ticker": "KXSOL15M-26JUL050730-30", "seq": 1},
            {"type": "orderbook_delta", "ticker": "KXXRP15M-26JUL050730-30", "seq": 1},  # Should evict oldest
        ]
        
        for event in events:
            ticker = event.get("ticker")
            event_type = event.get("type")
            if ticker and event_type:
                event_str = f"{ticker}:{event_type}:{str(event.get('seq', ''))}"
                event_hash = hashlib.md5(event_str.encode()).hexdigest()
                
                if ticker in message_cache:
                    if message_cache[ticker].get("hash") == event_hash:
                        continue
                
                if len(message_cache) >= message_cache_size:
                    oldest_ticker = next(iter(message_cache))
                    del message_cache[oldest_ticker]
                
                message_cache[ticker] = {"hash": event_hash, "ts": 0}
        
        # Cache should not exceed size limit
        assert len(message_cache) <= 3, "Cache should respect size limit"
    
    def test_deduplication_with_different_sequences(self):
        """Test that events with different sequences are not deduplicated."""
        import hashlib
        
        message_cache = {}
        message_cache_size = 1000
        events_dropped = 0
        events_processed = 0
        
        # Send events with same ticker but different sequences
        events = [
            {"type": "orderbook_delta", "ticker": "KXBTC15M-26JUL050730-30", "seq": 1},
            {"type": "orderbook_delta", "ticker": "KXBTC15M-26JUL050730-30", "seq": 2},
        ]
        
        for event in events:
            ticker = event.get("ticker")
            event_type = event.get("type")
            if ticker and event_type:
                event_str = f"{ticker}:{event_type}:{str(event.get('seq', ''))}"
                event_hash = hashlib.md5(event_str.encode()).hexdigest()
                
                if ticker in message_cache:
                    if message_cache[ticker].get("hash") == event_hash:
                        events_dropped += 1
                        continue
                
                if len(message_cache) >= message_cache_size:
                    oldest_ticker = next(iter(message_cache))
                    del message_cache[oldest_ticker]
                
                message_cache[ticker] = {"hash": event_hash, "ts": 0}
                events_processed += 1
        
        # Both events should be processed (different sequences)
        assert events_dropped == 0, "No duplicates should be dropped"
        assert events_processed == 2, "Both events should be processed"


class TestOrderbookSidSequenceTracking:
    """Regression tests for the real ``_enqueue_event`` orderbook seq tracker.

    Kalshi scopes the orderbook ``seq`` to the subscription (``sid``), not the
    market: one ``orderbook_delta`` subscribe covering all 5 crypto tickers
    multiplexes every ticker on a single seq space.  Tracking per ticker
    counted every other market's deltas as gaps (~600k false gaps/hr observed
    live 2026-10-01).  The tracker must key by ``sid``.
    """

    def _bridge(self):
        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge

        # Bridge enforces single instantiation per process; reset for tests.
        KalshiWebSocketBridge._instance_created = False
        return KalshiWebSocketBridge(ws=MagicMock())

    def _delta(self, sid, seq, ticker):
        return {
            "type": "orderbook_delta",
            "sid": sid,
            "seq": seq,
            "msg": {
                "market_ticker": ticker,
                "price_dollars": "0.45",
                "delta_fp": "10",
                "side": "no",
            },
        }

    def test_interleaved_tickers_same_sid_no_false_gaps(self):
        """All 5 tickers share one sid: interleaved deltas must NOT count as gaps."""
        import asyncio

        bridge = self._bridge()
        tickers = ["KXBTC15M-T", "KXETH15M-T", "KXSOL15M-T", "KXXRP15M-T", "KXDOGE15M-T"]
        seq = 100
        for _ in range(50):
            for t in tickers:
                asyncio.run(bridge._enqueue_event(self._delta(sid=1, seq=seq, ticker=t)))
                seq += 1

        assert bridge._sequence_gaps == 0, (
            f"shared-sid interleaved deltas produced {bridge._sequence_gaps} false gaps"
        )
        assert bridge._last_sequence.get("orderbook:sid1") == seq - 1

    def test_real_gap_on_sid_detected(self):
        """A dropped frame on the sid seq space still counts as a real gap."""
        import asyncio

        bridge = self._bridge()
        asyncio.run(bridge._enqueue_event(self._delta(sid=1, seq=10, ticker="KXBTC15M-T")))
        asyncio.run(bridge._enqueue_event(self._delta(sid=1, seq=15, ticker="KXETH15M-T")))

        assert bridge._sequence_gaps == 4
        assert bridge._sequence_gaps_list == [("orderbook:sid1", 11, 14)]

    def test_separate_sids_are_independent_seq_spaces(self):
        """A second subscription (e.g. rollover resubscribe) must not pollute sid1's tracker."""
        import asyncio

        bridge = self._bridge()
        # Old sid=1 at high seq, then new sid=7 starts at its own seq 1.
        asyncio.run(bridge._enqueue_event(self._delta(sid=1, seq=689000, ticker="KXBTC15M-T")))
        asyncio.run(bridge._enqueue_event(self._delta(sid=7, seq=1, ticker="KXBTC15M-T2")))
        asyncio.run(bridge._enqueue_event(self._delta(sid=7, seq=2, ticker="KXETH15M-T2")))
        asyncio.run(bridge._enqueue_event(self._delta(sid=1, seq=689001, ticker="KXETH15M-T")))

        assert bridge._sequence_gaps == 0
        assert bridge._last_sequence["orderbook:sid1"] == 689001
        assert bridge._last_sequence["orderbook:sid7"] == 2

    def test_snapshot_and_delta_share_sid_seq_space(self):
        """Kalshi sends snapshot then deltas on the same sid with one seq counter."""
        import asyncio

        bridge = self._bridge()
        asyncio.run(bridge._enqueue_event({
            "type": "orderbook_snapshot",
            "sid": 1,
            "seq": 5,
            "msg": {"market_ticker": "KXBTC15M-T", "yes_dollars_fp": [], "no_dollars_fp": []},
        }))
        asyncio.run(bridge._enqueue_event(self._delta(sid=1, seq=6, ticker="KXBTC15M-T")))
        asyncio.run(bridge._enqueue_event(self._delta(sid=1, seq=7, ticker="KXETH15M-T")))

        assert bridge._sequence_gaps == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
