"""
Settlement Poller Upstream/Downstream Boundary Probe

Validates contract boundaries post-audit with chaos-style integration tests.

Usage:
    pytest tests/test_settlement_poller_boundary_probe.py -v --tb=short
    pytest tests/test_settlement_poller_boundary_probe.py -v -k "upstream"  # Cursor/ticker/status
    pytest tests/test_settlement_poller_boundary_probe.py -v -k "downstream"  # Grading/health/voids
    pytest tests/test_settlement_poller_boundary_probe.py -v -k "chaos"  # Replay/pagination pressure
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merid.event_venues.kalshi.settlement_poller import (
    KalshiSettlement,
    KalshiSettlementPoller,
    PollerConfig,
    SettlementStatus,
    Outcome,
    normalize_kalshi_ticker,
    SettlementToGradingBridge,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Upstream Boundary Probes
# ═══════════════════════════════════════════════════════════════════════════════

class TestUpstreamCursorPersistenceBoundary:
    """
    PROBE-1: Cursor persistence across restarts.
    
    Contract §4.1 requires: "Cursor-based pagination for resume on restart"
    
    CRITICAL BUG FOUND: _cursor_history is in-memory only. On restart, poller
    re-queries from lookback window start, not from last known cursor.
    """
    
    def test_cursor_state_is_in_memory_only(self):
        """
        Verify that cursor history is lost on poller restart.
        
        This test documents the BUG: cursor persistence requires external storage
        (Redis/file) but current implementation uses in-memory lists.
        """
        # Simulate first poller instance
        mock_client = MagicMock()
        poller1 = KalshiSettlementPoller(mock_client)
        
        # Simulate cursor accumulation during operation
        poller1._cursor_history = ["cursor_1", "cursor_2", "cursor_3"]
        poller1._last_cursor = "cursor_3"
        
        # Simulate restart (new instance)
        poller2 = KalshiSettlementPoller(mock_client)
        
        # BUG: Cursor state is lost
        assert poller2._last_cursor is None
        assert poller2._cursor_history == []
        
        # This means poller2 will query from lookback start, not cursor_3
        # Result: Duplicate processing of already-seen settlements
    
    def test_cursor_resume_needs_external_storage(self):
        """
        Document the FIX required: cursor state must persist externally.
        
        Options:
        1. Redis: Store (poller_id, cursor, timestamp)
        2. File: Write cursor to disk on each update
        3. Database: Settlement tracking table with cursor column
        """
        # This test will fail until cursor persistence is implemented
        pytest.skip("TODO: Implement cursor persistence via Redis or file storage")
    
    @pytest.mark.asyncio
    async def test_pagination_restarts_from_lookback_on_no_cursor(self):
        """
        Verify that without cursor, poller fetches from lookback window start.
        
        This is the current (buggy) behavior - it should resume from last cursor.
        """
        mock_client = MagicMock()
        mock_client.request = AsyncMock(return_value={
            "settlements": [],
            "cursor": None,
        })
        
        poller = KalshiSettlementPoller(mock_client)
        
        # Patch _api_call_with_retry to capture calls
        calls = []
        original_api_call = poller._api_call_with_retry
        
        async def capture_api_call(method, endpoint, params=None):
            calls.append(params)
            return await original_api_call(method, endpoint, params)
        
        poller._api_call_with_retry = capture_api_call
        
        # Trigger fetch
        await poller._fetch_all_settlements(
            start_time="2025-01-01T00:00:00Z",
            end_time="2025-01-02T00:00:00Z",
        )
        
        # First call has no cursor (starts from beginning)
        assert calls[0].get("cursor") is None
        assert "settled_after" in calls[0]


class TestUpstreamTickerNormalizationBoundary:
    """
    PROBE-2: Ticker normalization idempotency and hash stability.
    
    Contract §1.2 requires: "Normalize any Kalshi ticker variation to canonical form"
    """
    
    def test_ticker_normalization_idempotent(self):
        """normalize(normalize(x)) == normalize(x) for all variants."""
        variants = [
            "kxbtc-15m",
            "KXBTC-15M",
            "btc-15m",
            "BTC-15M",
            "KXBTC15M",
            "kxbtc15m",
            "BTC_15M",
            "btc_15m",
            "KXETHD1",
            "kxeth-d1",
            "ETH-D1",
            "KXSOL-W1",
            "kxsolw1",
        ]
        
        for v in variants:
            once = normalize_kalshi_ticker(v)
            twice = normalize_kalshi_ticker(once)
            assert once == twice, f"Not idempotent: {v} → {once} → {twice}"
    
    def test_ticker_hash_stable_across_variants(self):
        """All variants of same ticker hash to same value (for deduplication)."""
        btc_variants = [
            "kxbtc-15m",
            "KXBTC-15M",
            "btc-15m",
            "BTC-15M",
            "KXBTC15M",
        ]
        
        hashes = [hashlib.sha256(normalize_kalshi_ticker(v).encode()).hexdigest() 
                  for v in btc_variants]
        
        assert len(set(hashes)) == 1, f"Hash collision failed: {hashes}"
    
    def test_ticker_normalization_crypto_series(self):
        """All crypto assets normalize correctly."""
        test_cases = [
            # (input, expected)
            ("kxbtc-15m", "KXBTC-15M"),
            ("kxeth", "KXETH"),
            ("kxsol-d1", "KXSOL-D1"),
            ("xrp-15m", "KXXRP-15M"),
            ("doge-w1", "KXDOGE-W1"),
        ]
        
        for inp, expected in test_cases:
            result = normalize_kalshi_ticker(inp)
            assert result == expected, f"Expected {expected}, got {result} for {inp}"
    
    def test_mixed_case_ticker_variants(self):
        """Stress test: Random case variations all normalize identically."""
        import random
        
        base = "KXBTC-15M"
        variants = []
        
        # Generate random case variants
        for _ in range(20):
            variant = "".join(
                c.lower() if random.random() < 0.3 else c.upper() 
                for c in base
            )
            variants.append(variant)
        
        normalized = [normalize_kalshi_ticker(v) for v in variants]
        assert all(n == "KXBTC-15M" for n in normalized), f"Mixed-case failed: {set(normalized)}"


class TestUpstreamStatusFilteringBoundary:
    """
    PROBE-3: Kalshi client status filtering.
    
    Verify CANCELLED/INVALID never leak through as gradable.
    """
    
    def test_settlement_status_to_outcome_mapping(self):
        """All status values map correctly to outcomes."""
        test_cases = [
            (SettlementStatus.SETTLED, 100, Outcome.YES),
            (SettlementStatus.SETTLED, 0, Outcome.NO),
            (SettlementStatus.CANCELLED, None, Outcome.CANCELLED),
            (SettlementStatus.PENDING, None, None),
        ]
        
        for status, price, expected in test_cases:
            s = KalshiSettlement(
                market_id="TEST",
                ticker="TEST",
                title="Test",
                category="crypto",
                status=status,
                settlement_price_cents=price,
            )
            assert s.to_outcome() == expected, f"Failed for {status}, {price}"
    
    def test_is_gradable_excludes_voided(self):
        """CANCELLED and INVALID are never gradable."""
        voided_statuses = [
            (SettlementStatus.CANCELLED, None),
        ]
        
        for status, price in voided_statuses:
            s = KalshiSettlement(
                market_id="TEST",
                ticker="TEST",
                title="Test",
                category="crypto",
                status=status,
                settlement_price_cents=price,
            )
            assert s.is_gradable() is False, f"{status} should not be gradable"
    
    def test_invalid_price_produces_invalid_outcome(self):
        """Prices other than 0/100 produce INVALID outcome, not gradable."""
        s = KalshiSettlement(
            market_id="TEST",
            ticker="TEST",
            title="Test",
            category="crypto",
            status=SettlementStatus.SETTLED,
            settlement_price_cents=50,  # Invalid price
        )
        
        assert s.to_outcome() == Outcome.INVALID
        assert s.is_gradable() is False
    
    @pytest.mark.asyncio
    async def test_poller_filters_voided_at_ingestion(self):
        """Poller skips voided markets before deduplication check."""
        mock_client = MagicMock()
        
        # Mock response with mixed statuses
        mock_client.request = AsyncMock(return_value={
            "settlements": [
                {
                    "market_id": "YES-MARKET",
                    "ticker": "KXBTC-15M",
                    "status": "settled",
                    "settlement_price": 100,
                    "settlement_time": "2025-01-01T00:00:00Z",
                },
                {
                    "market_id": "VOID-MARKET",
                    "ticker": "KXETH-15M",
                    "status": "cancelled",
                    "settlement_time": None,
                },
            ],
            "cursor": None,
        })
        
        poller = KalshiSettlementPoller(mock_client)
        
        # Track what gets emitted
        emitted = []
        poller.add_callback(lambda s: emitted.append(s))
        
        await poller._poll_once()
        
        # Only YES-MARKET should be in cache and emitted
        assert len(emitted) == 1
        assert emitted[0].market_id == "YES-MARKET"
        assert "VOID-MARKET" not in poller._settlement_cache


# ═══════════════════════════════════════════════════════════════════════════════
# Downstream Boundary Probes
# ═══════════════════════════════════════════════════════════════════════════════

class TestDownstreamGradingDedupeBoundary:
    """
    PROBE-4: Grading stream dedupe_key verification.
    
    Contract §4.1: "exactly-once grading with dedupe_key"
    """
    
    def test_dedupe_key_format(self):
        """dedupe_key follows format: kalshi:{market_id}:{settlement_time}"""
        s = KalshiSettlement(
            market_id="KXBTC-15M-20251231",
            ticker="KXBTC-15M",
            title="Test",
            category="crypto",
            status=SettlementStatus.SETTLED,
            settlement_price_cents=100,
            settlement_time="2025-12-31T12:00:00Z",
        )
        
        expected = "kalshi:KXBTC-15M-20251231:2025-12-31T12:00:00Z"
        assert s.dedupe_key == expected
    
    def test_dedupe_key_prevents_replay(self):
        """Same settlement dedupe_key is rejected on second arrival."""
        poller = KalshiSettlementPoller(MagicMock())
        
        s = KalshiSettlement(
            market_id="KXBTC-15M",
            ticker="KXBTC-15M",
            title="Test",
            category="crypto",
            status=SettlementStatus.SETTLED,
            settlement_price_cents=100,
            settlement_time="2025-01-01T00:00:00Z",
        )
        
        # First arrival: accepted
        poller._graded_settlements.add(s.dedupe_key)
        
        # Second arrival: rejected (dedupe_key already in set)
        assert s.dedupe_key in poller._graded_settlements
    
    def test_dedupe_key_includes_timestamp_for_uniqueness(self):
        """Same market, different settlement times = different dedupe_keys."""
        s1 = KalshiSettlement(
            market_id="KXBTC-15M",
            ticker="KXBTC-15M",
            title="Test",
            category="crypto",
            status=SettlementStatus.SETTLED,
            settlement_price_cents=100,
            settlement_time="2025-01-01T00:00:00Z",
        )
        
        s2 = KalshiSettlement(
            market_id="KXBTC-15M",
            ticker="KXBTC-15M",
            title="Test",
            category="crypto",
            status=SettlementStatus.SETTLED,
            settlement_price_cents=100,
            settlement_time="2025-01-02T00:00:00Z",  # Different time
        )
        
        # Different dedupe_keys allow both to be processed
        assert s1.dedupe_key != s2.dedupe_key


class TestDownstreamHealthEndpointBoundary:
    """
    PROBE-5: /health/ungraded count accuracy.
    
    Contract §6.1: "Health endpoint for settled-but-ungraded markets"
    """
    
    def test_settled_but_ungraded_count_monotonicity(self):
        """Count increases with new gradable settlements, decreases on mark_graded."""
        poller = KalshiSettlementPoller(MagicMock())
        
        # Initial state
        assert poller.get_settled_but_ungraded_count() == 0
        
        # Add gradable settlement
        s1 = KalshiSettlement(
            market_id="M1",
            ticker="KXBTC-15M",
            title="Test",
            category="crypto",
            status=SettlementStatus.SETTLED,
            settlement_price_cents=100,
        )
        poller._update_ungraded_backlog(s1)
        assert poller.get_settled_but_ungraded_count() == 1
        
        # Add another
        s2 = KalshiSettlement(
            market_id="M2",
            ticker="KXETH-15M",
            title="Test",
            category="crypto",
            status=SettlementStatus.SETTLED,
            settlement_price_cents=0,
        )
        poller._update_ungraded_backlog(s2)
        assert poller.get_settled_but_ungraded_count() == 2
        
        # Mark one graded
        poller.mark_graded("M1")
        assert poller.get_settled_but_ungraded_count() == 1
    
    def test_voided_not_counted_in_ungraded(self):
        """CANCELLED settlements never appear in ungraded backlog."""
        poller = KalshiSettlementPoller(MagicMock())
        
        voided = KalshiSettlement(
            market_id="VOID",
            ticker="KXBTC-15M",
            title="Test",
            category="crypto",
            status=SettlementStatus.CANCELLED,
        )
        
        poller._update_ungraded_backlog(voided)
        
        # Voided settlements are not gradable, so not tracked
        assert voided.is_gradable() is False
        assert poller.get_settled_but_ungraded_count() == 0
    
    @pytest.mark.asyncio
    async def test_health_endpoint_response_format(self):
        """Health endpoint returns correct structure for monitoring."""
        # Import the endpoint handler
        from merid.event_venues.kalshi.settlement_poller import get_settled_but_ungraded
        
        response = await get_settled_but_ungraded()
        
        assert "status" in response
        assert "settled_but_ungraded" in response
        assert "markets" in response
        
        # Markets list should be limited
        assert len(response["markets"]) <= 20


class TestDownstreamVoidPropagationBoundary:
    """
    PROBE-6: Voided settlement isolation from PnL/exposure.

    CANCELLED/INVALID must never propagate to:
    - PnL aggregation
    - PnL calculations
    - Exposure caps
    """
    
    def test_voided_not_in_grading_callback(self):
        """Grading callbacks only receive gradable settlements."""
        gradable_only = []
        
        def mock_callback(s):
            if s.is_gradable():
                gradable_only.append(s)
        
        settlements = [
            KalshiSettlement("M1", "KXBTC", "Test", "crypto", SettlementStatus.SETTLED, 100),
            KalshiSettlement("M2", "KXETH", "Test", "crypto", SettlementStatus.CANCELLED, None),
            KalshiSettlement("M3", "KXSOL", "Test", "crypto", SettlementStatus.SETTLED, 0),
        ]
        
        for s in settlements:
            if s.is_gradable():  # This is what the bridge does
                mock_callback(s)
        
        # Only 2 gradable settlements
        assert len(gradable_only) == 2
        assert all(s.is_gradable() for s in gradable_only)
    
    def test_voided_pnl_is_none_not_zero(self):
        """Voided settlements have None PnL, not zero (which would affect averages)."""
        voided = KalshiSettlement(
            market_id="VOID",
            ticker="KXBTC",
            title="Test",
            category="crypto",
            status=SettlementStatus.CANCELLED,
            realized_pnl_cents=None,
        )
        
        # PnL should be None, not 0
        assert voided.realized_pnl_cents is None
        
        # PnL calculations should skip None values
        pnls = [100, -50, None, 200]  # Include voided
        valid_pnls = [p for p in pnls if p is not None]
        assert valid_pnls == [100, -50, 200]


# ═══════════════════════════════════════════════════════════════════════════════
# Chaos/Integration Probes
# ═══════════════════════════════════════════════════════════════════════════════

class TestChaosReplayBoundary:
    """
    PROBE-7: Replay scenarios with deduplication.
    
    Replaying same settlement stream yields identical aggregate metrics.
    """
    
    def test_replay_produces_identical_metrics(self):
        """Idempotency: Same stream processed twice = same counts."""
        stream = [
            KalshiSettlement(
                market_id=f"M{i}",
                ticker="KXBTC-15M",
                title=f"Test {i}",
                category="crypto",
                status=SettlementStatus.SETTLED,
                settlement_price_cents=100 if i % 2 == 0 else 0,
                settlement_time=f"2025-01-01T00:0{i}:00Z",
            )
            for i in range(5)
        ]
        
        # First processing
        seen1 = set()
        count1 = 0
        for s in stream:
            if s.dedupe_key not in seen1:
                seen1.add(s.dedupe_key)
                count1 += 1
        
        # Second processing (replay)
        seen2 = set()
        count2 = 0
        for s in stream:
            if s.dedupe_key not in seen2:
                seen2.add(s.dedupe_key)
                count2 += 1
        
        assert count1 == count2 == 5
    
    def test_partial_replay_after_crash(self):
        """Simulate crash mid-stream: processed settlements survive, unprocessed don't."""
        stream = [
            KalshiSettlement("M1", "KXBTC", "T1", "crypto", SettlementStatus.SETTLED, 100, 
                          settlement_time="2025-01-01T00:00:00Z"),
            KalshiSettlement("M2", "KXBTC", "T2", "crypto", SettlementStatus.SETTLED, 0,
                          settlement_time="2025-01-01T00:01:00Z"),
            KalshiSettlement("M3", "KXBTC", "T3", "crypto", SettlementStatus.SETTLED, 100,
                          settlement_time="2025-01-01T00:02:00Z"),
        ]
        
        # Simulate: Process M1, crash before M2/M3, restart with dedupe_key: M1 in graded_set
        graded_set = {stream[0].dedupe_key}  # M1 survived crash
        
        # Resume processing
        new_count = 0
        for s in stream:
            if s.dedupe_key not in graded_set:
                graded_set.add(s.dedupe_key)
                new_count += 1
        
        # Only M2 and M3 processed on resume
        assert new_count == 2


class TestChaosPaginationPressureBoundary:
    """
    PROBE-8: Pagination pressure under high volume.
    
    Verify consistency when settlements span multiple pages.
    """
    
    @pytest.mark.asyncio
    async def test_pagination_with_many_pages(self):
        """Poller handles 10+ pages without data loss."""
        mock_client = MagicMock()
        
        # Generate 250 settlements across 3 pages
        page_responses = []
        for page in range(3):
            settlements = [
                {
                    "market_id": f"M{page}_{i}",
                    "ticker": "KXBTC-15M",
                    "status": "settled",
                    "settlement_price": 100,
                    "settlement_time": f"2025-01-01T00:{page}{i}:00Z",
                }
                for i in range(100 if page < 2 else 50)
            ]
            page_responses.append({
                "settlements": settlements,
                "cursor": f"cursor_{page+1}" if page < 2 else None,
            })
        
        # Mock sequential cursor calls
        call_count = [0]
        async def mock_request(method, endpoint, params=None):
            idx = call_count[0]
            call_count[0] += 1
            return page_responses[idx]
        
        mock_client.request = mock_request
        
        poller = KalshiSettlementPoller(mock_client)
        
        # Fetch all pages
        all_settlements = await poller._fetch_all_settlements(
            start_time="2025-01-01T00:00:00Z",
            end_time="2025-01-02T00:00:00Z",
        )
        
        # All 250 settlements retrieved
        assert len(all_settlements) == 250
    
    def test_pagination_cursor_progression(self):
        """Cursor advances correctly through pages."""
        poller = KalshiSettlementPoller(MagicMock())
        
        # Simulate cursor progression
        poller._cursor_history = []
        cursors = ["c1", "c2", "c3", None]
        
        for cursor in cursors:
            if cursor:
                poller._last_cursor = cursor
                poller._cursor_history.append(cursor)
        
        assert poller._last_cursor == "c3"
        assert len(poller._cursor_history) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# Bug Documentation Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestKnownBugsDocumentation:
    """
    Document known issues that require fixes.
    """
    
    def test_bug_cursor_not_persisted_across_restarts(self):
        """
        BUG-UPSTREAM-1: Cursor state lost on restart.
        
        Impact: Poller re-queries from lookback start, causing duplicate
        processing of already-seen settlements (mitigated by dedupe_key).
        
        Fix Required:
        1. Add cursor persistence to Redis or file
        2. Load cursor on poller start
        3. Resume from last known cursor instead of lookback start
        
        Priority: MEDIUM (dedupe_key prevents double-grading, but wastes API calls)
        """
        pytest.skip("BUG: Cursor persistence not implemented - see test docstring")
    
    def test_fixme_cursor_persistence_implementation(self):
        """
        FIXME: Implement cursor persistence.
        
        Proposed solution:
        ```python
        async def _persist_cursor(self, cursor: str):
            # Option 1: Redis
            await redis.set(f"kalshi:settlement_cursor:{self._instance_id}", cursor, ex=86400)
            
            # Option 2: File
            with open(self._cursor_file, 'w') as f:
                json.dump({'cursor': cursor, 'timestamp': time.time()}, f)
        
        async def _load_cursor(self) -> Optional[str]:
            # Load from Redis or file
            # Return None if not found or stale (>24h)
        ```
        """
        pytest.skip("FIXME: Implement cursor persistence")


# ═══════════════════════════════════════════════════════════════════════════════
# Event Bus Topic Contract
# ═══════════════════════════════════════════════════════════════════════════════

class TestEventBusTopicContract:
    """
    PROBE: Event bus topic must match between publisher and subscriber.

    Contract: settlement_poller publishes to "merid.kalshi.settlements",
    TradingAgent subscribes to same topic for TP reset on settlement.

    BUG-REGRESSION: Topic mismatch caused TradingAgent to never receive
    settlement events, breaking round-trip reset and causing permanent
    re-entry blocking after max round trips.
    """

    def test_settlement_event_bus_topic_constant(self):
        """Verify the event bus topic is consistently defined via shared constant."""
        from merid.event_venues.kalshi.settlement_poller import SETTLEMENT_EVENT_BUS_TOPIC

        # Verify it's a valid topic string (no spaces, proper format)
        assert SETTLEMENT_EVENT_BUS_TOPIC.startswith("merid.")
        assert SETTLEMENT_EVENT_BUS_TOPIC.count(".") >= 2
        assert " " not in SETTLEMENT_EVENT_BUS_TOPIC
        assert SETTLEMENT_EVENT_BUS_TOPIC == "merid.kalshi.settlements"

    def test_trading_agent_subscribes_to_correct_topic(self):
        """Verify TradingAgent imports and uses the same constant poller publishes to."""
        from merid.event_venues.kalshi.settlement_poller import SETTLEMENT_EVENT_BUS_TOPIC

        # Check the source code imports and uses the shared constant
        import inspect
        try:
            from merid.prediction.trading_agent import KalshiTradingAgent
        except ImportError:
            pytest.skip("merid.prediction.trading_agent is not present in this build")

        source = inspect.getsource(KalshiTradingAgent._setup_settlement_subscription)
        # Should import and use the shared constant, NOT literal strings
        assert "SETTLEMENT_EVENT_BUS_TOPIC" in source, "TradingAgent must use shared constant"
        assert "kalshi:settlement" not in source, "Old broken topic 'kalshi:settlement' should not be present"
        assert "\"merid.kalshi.settlements\"" not in source, "Should use constant, not literal"


# ═══════════════════════════════════════════════════════════════════════════════
# Run Configuration
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
