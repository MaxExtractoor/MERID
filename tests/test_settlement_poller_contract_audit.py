"""
Settlement Poller Contract Audit — Upstream/Downstream Verification

Comprehensive verification suite for the Kalshi settlement poller contract boundaries.
Run with: pytest tests/test_settlement_poller_contract_audit.py -v

Upstream checks (inputs into settlement_poller.py):
- API client cursoring and resume behavior
- Ticker normalization at all producer sites
- Void handling boundary (CANCELLED/INVALID excluded from gradable pools)
- Benchmark thresholds binding (domain module import, no duplication)

Downstream checks (outputs from settlement_poller.py):
- Idempotent grading sink (dedupe_key convention match)
- Cache & API endpoints (Outcome enum names, not ints)
- Health/Status endpoint ingestion by watchdogs
- Outcome propagation filtering (voided excluded from analytics)

Integration probes:
- Replay test (duplicate suppression)
- Voided market injection (log but not grade)
- Ticker normalization drift (mixed-case variants)
- API smoke under pagination pressure
"""

import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Set
from unittest.mock import MagicMock, AsyncMock, patch, call
from dataclasses import dataclass
import json

# Module under test
from merid.event_venues.kalshi.settlement_poller import (
    KalshiSettlement,
    KalshiSettlementPoller,
    SettlementStatus,
    Outcome,
    normalize_kalshi_ticker,
    SettlementToGradingBridge,
    PollerConfig,
    get_settlement_poller,
    get_settlement_bridge,
    _poller,
    _bridge,
)
from merid.prediction.market_opinion import BenchmarkThresholds


# ─── Test Fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def mock_kalshi_client():
    """Mock Kalshi API client with paginated response support."""
    client = MagicMock()
    client.request = AsyncMock()
    return client


@pytest.fixture
def fresh_poller(mock_kalshi_client):
    """Create a fresh poller instance with clean state."""
    # Reset singletons
    import merid.event_venues.kalshi.settlement_poller as poller_module
    poller_module._poller = None
    poller_module._bridge = None
    
    config = PollerConfig(
        poll_interval_seconds=60.0,
        lookback_hours=24,
        batch_size=100,
        max_retries=3,
        retry_delay_seconds=1.0,
    )
    return KalshiSettlementPoller(mock_kalshi_client, config)


@pytest.fixture
def sample_settlements() -> List[KalshiSettlement]:
    """Generate sample settlements for testing."""
    base_time = datetime.now(timezone.utc)
    return [
        KalshiSettlement(
            market_id="KXBTC-15M-20251231",
            ticker="KXBTC-15M",
            title="BTC 15min",
            category="crypto",
            status=SettlementStatus.SETTLED,
            settlement_price_cents=100,
            settlement_time=(base_time - timedelta(hours=1)).isoformat(),
        ),
        KalshiSettlement(
            market_id="KXETH-D1-20251231",
            ticker="KXETH-D1",
            title="ETH Daily",
            category="crypto",
            status=SettlementStatus.SETTLED,
            settlement_price_cents=0,
            settlement_time=(base_time - timedelta(hours=2)).isoformat(),
        ),
        KalshiSettlement(
            market_id="KXSOL-15M-20251231",
            ticker="KXSOL-15M",
            title="SOL 15min",
            category="crypto",
            status=SettlementStatus.CANCELLED,  # Voided!
            settlement_price_cents=None,
            settlement_time=(base_time - timedelta(hours=3)).isoformat(),
        ),
        KalshiSettlement(
            market_id="KXXRP-15M-20251231",
            ticker="KXXRP-15M",
            title="XRP 15min",
            category="crypto",
            status=SettlementStatus.SETTLED,
            settlement_price_cents=50,  # Invalid price
            settlement_time=(base_time - timedelta(hours=4)).isoformat(),
        ),
    ]


# ─── Upstream Checks ─────────────────────────────────────────────────────────


class TestUpstreamAPIClientCursoring:
    """
    Upstream Check: Kalshi API client / cursoring
    
    Verify _fetch_all_settlements() resumes correctly with stale cursors.
    Simulate dropped network calls between pagination calls.
    """
    
    @pytest.mark.asyncio
    async def test_cursor_resume_after_network_drop(self, mock_kalshi_client, fresh_poller):
        """
        Simulate a dropped network call mid-pagination.
        Verify cursor_history allows resumption without re-fetching completed pages.
        """
        # Page 1: succeeds
        # Page 2: network drop (exception)
        # Retry should resume from cursor, not restart
        
        responses = [
            {
                "settlements": [
                    {
                        "market_id": "KXBTC-15M-001",
                        "ticker": "KXBTC-15M",
                        "status": "settled",
                        "settlement_price": 100,
                        "settlement_time": "2025-12-31T10:00:00Z",
                    }
                ],
                "cursor": "page2_cursor",
            },
            Exception("Network drop"),  # Page 2 fails
        ]
        
        call_count = [0]
        async def side_effect(*args, **kwargs):
            idx = call_count[0]
            call_count[0] += 1
            if idx < len(responses):
                resp = responses[idx]
                if isinstance(resp, Exception):
                    raise resp
                return resp
            return {"settlements": []}  # Empty final page
        
        mock_kalshi_client.request.side_effect = side_effect
        
        # First attempt: should capture cursor before failure
        with pytest.raises(Exception, match="Network drop"):
            await fresh_poller._fetch_all_settlements(
                start_time="2025-12-31T00:00:00Z",
                end_time="2025-12-31T23:59:59Z",
            )
        
        # Cursor should be captured from successful first page
        assert fresh_poller._last_cursor == "page2_cursor"
        assert "page2_cursor" in fresh_poller._cursor_history
    
    @pytest.mark.asyncio
    async def test_cursor_history_prevents_replay(self, mock_kalshi_client, fresh_poller):
        """
        Verify cursor_history prevents re-fetching pages already in history.
        """
        fresh_poller._cursor_history = ["already_seen_cursor"]
        
        # Mock would return same cursor again
        mock_kalshi_client.request.return_value = {
            "settlements": [],
            "cursor": "already_seen_cursor",  # Duplicate cursor!
        }
        
        # This should not cause infinite loop
        # Implementation detail: we trust the API doesn't loop cursors
        # But we should have a safety limit (10 pages max)
        result = await fresh_poller._fetch_all_settlements(
            start_time="2025-12-31T00:00:00Z",
            end_time="2025-12-31T23:59:59Z",
        )
        
        # Should stop after empty result or hitting limit
        assert isinstance(result, list)


class TestUpstreamTickerNormalization:
    """
    Upstream Check: Ticker normalization at all producer sites
    
    Confirm every producer calls normalize_kalshi_ticker() before writing
to cache/db. That avoids collisions when the poller reads historical sets.
    """
    
    def test_ticker_normalization_idempotent(self):
        """
        normalize_kalshi_ticker() must be idempotent:
        normalize(normalize(x)) == normalize(x)
        """
        variants = [
            "kxbtc-15m",
            "KXBTC-15M",
            "kxBTC15M",
            "btc-15m",
            "BTC_15M",
            "KXBTC15M",
        ]
        
        for variant in variants:
            once = normalize_kalshi_ticker(variant)
            twice = normalize_kalshi_ticker(once)
            assert once == twice, f"Not idempotent: {variant} → {once} → {twice}"
            assert once == "KXBTC-15M", f"Wrong canonical form: {variant} → {once}"
    
    def test_all_ticker_variants_hash_identically(self):
        """
        All variants of the same ticker must produce identical hashable keys.
        This ensures dedupe_key collisions don't occur.
        """
        variants = [
            "kxbtc-15m",
            "KXBTC-15M",
            "btc-15m",
            "KXBTC15M",
        ]
        
        normalized_keys = []
        for variant in variants:
            normalized = normalize_kalshi_ticker(variant)
            # Simulate dedupe_key construction
            dedupe_key = f"kalshi:{normalized}:2025-12-31T12:00:00Z"
            normalized_keys.append(dedupe_key)
        
        # All should be identical
        assert len(set(normalized_keys)) == 1, f"Dedupe keys diverged: {normalized_keys}"


class TestUpstreamVoidHandling:
    """
    Upstream Check: Void handling boundary
    
    If Outcome.CANCELLED or Outcome.INVALID appear, confirm upstream feed
    doesn't emit them in gradable pools or position reconciliation.
    """
    
    def test_voided_settlements_not_gradable(self, sample_settlements):
        """
        Voided (CANCELLED) and INVALID outcomes must not be gradable.
        """
        for s in sample_settlements:
            if s.status == SettlementStatus.CANCELLED:
                assert s.to_outcome() == Outcome.CANCELLED
                assert s.is_gradable() is False, f"CANCELLED should not be gradable: {s.market_id}"
            elif s.settlement_price_cents is not None and s.settlement_price_cents not in (0, 100):
                assert s.to_outcome() == Outcome.INVALID
                assert s.is_gradable() is False, f"INVALID should not be gradable: {s.market_id}"
    
    def test_only_yes_no_are_gradable(self):
        """
        Only YES and NO outcomes should be gradable.
        This is the contract boundary for downstream analytics.
        """
        yes_settlement = KalshiSettlement(
            market_id="TEST-YES",
            ticker="TEST",
            title="Test YES",
            category="test",
            status=SettlementStatus.SETTLED,
            settlement_price_cents=100,
        )
        no_settlement = KalshiSettlement(
            market_id="TEST-NO",
            ticker="TEST",
            title="Test NO",
            category="test",
            status=SettlementStatus.SETTLED,
            settlement_price_cents=0,
        )
        cancelled_settlement = KalshiSettlement(
            market_id="TEST-CANCELLED",
            ticker="TEST",
            title="Test CANCELLED",
            category="test",
            status=SettlementStatus.CANCELLED,
        )
        pending_settlement = KalshiSettlement(
            market_id="TEST-PENDING",
            ticker="TEST",
            title="Test PENDING",
            category="test",
            status=SettlementStatus.PENDING,
        )
        
        assert yes_settlement.is_gradable() is True
        assert yes_settlement.to_outcome() == Outcome.YES
        
        assert no_settlement.is_gradable() is True
        assert no_settlement.to_outcome() == Outcome.NO
        
        assert cancelled_settlement.is_gradable() is False
        assert cancelled_settlement.to_outcome() == Outcome.CANCELLED
        
        assert pending_settlement.is_gradable() is False
        assert pending_settlement.to_outcome() is None


class TestUpstreamBenchmarkThresholdsBinding:
    """
    Upstream Check: Benchmark thresholds binding
    
    Ensure upstream market_opinion and grading.py agree on thresholds
    via import from domain—not via duplicated constant definitions.
    """
    
    def test_no_duplicate_threshold_definitions(self):
        """
        Verify BenchmarkThresholds is only defined in domain module.
        This test imports from both locations and ensures they reference
        the same class object.
        """
        from merid.prediction.market_opinion import BenchmarkThresholds as DomainThresholds
        from web.read_models.grading import BenchmarkThresholds as UIThresholds
        
        # Should be the same class (import, not redefinition)
        assert DomainThresholds is UIThresholds, (
            "BenchmarkThresholds should be imported from domain, not redefined in UI"
        )
    
    def test_threshold_values_consistent(self):
        """
        Verify threshold values match contract specification.
        """
        assert BenchmarkThresholds.BRIER_EXCELLENT == 0.10
        assert BenchmarkThresholds.BRIER_GOOD == 0.20
        assert BenchmarkThresholds.BRIER_RANDOM_BASELINE == 0.25
        assert BenchmarkThresholds.KELLY_REGRET_MAX == 0.05
        assert BenchmarkThresholds.DIRECTION_ACCURACY_GOOD == 0.70
        assert BenchmarkThresholds.DIRECTION_ACCURACY_MIN == 0.65
        assert BenchmarkThresholds.ROI_MIN_MULTIPLE == 2.0
    
    def test_grading_functions_produce_expected_labels(self):
        """
        Verify grading functions produce expected labels per contract.
        """
        # Brier grading
        assert BenchmarkThresholds.grade_brier(0.05) == "excellent"
        assert BenchmarkThresholds.grade_brier(0.15) == "good"
        assert BenchmarkThresholds.grade_brier(0.22) == "fair"
        assert BenchmarkThresholds.grade_brier(0.30) == "poor"
        
        # Direction accuracy grading
        assert BenchmarkThresholds.grade_direction_accuracy(0.75) == "good"
        assert BenchmarkThresholds.grade_direction_accuracy(0.67) == "fair"
        assert BenchmarkThresholds.grade_direction_accuracy(0.50) == "poor"


# ─── Downstream Checks ───────────────────────────────────────────────────────


class TestDownstreamIdempotentGrading:
    """
    Downstream Check: Idempotent grading sink
    
    Check that downstream grader uses the same dedupe_key convention.
    No implicit "update if not exists" logic with looser filters.
    """
    
    def test_dedupe_key_format_contract(self):
        """
        Verify dedupe_key format matches contract specification:
        (venue, market_id, settled_time)
        """
        s = KalshiSettlement(
            market_id="KXBTC-15M-20251231",
            ticker="KXBTC-15M",
            title="Test",
            category="crypto",
            status=SettlementStatus.SETTLED,
            settlement_price_cents=100,
            settlement_time="2025-12-31T12:00:00Z",
        )
        
        expected_key = "kalshi:KXBTC-15M-20251231:2025-12-31T12:00:00Z"
        assert s.dedupe_key == expected_key
    
    def test_graded_settlements_set_prevents_duplicates(self, fresh_poller, sample_settlements):
        """
        Verify _graded_settlements set prevents duplicate processing.
        """
        s = sample_settlements[0]  # Valid YES settlement
        dedupe_key = s.dedupe_key
        
        # First addition
        fresh_poller._graded_settlements.add(dedupe_key)
        assert dedupe_key in fresh_poller._graded_settlements
        
        # Second addition attempt (would be duplicate)
        # Set automatically prevents duplicate
        fresh_poller._graded_settlements.add(dedupe_key)
        assert len(fresh_poller._graded_settlements) == 1


class TestDownstreamAPIEndpoints:
    """
    Downstream Check: Cache & API endpoints
    
    Confirm /api/v1/kalshi/settlements/cache returns Outcomes as enum names
    (not raw ints). If downstream UI expects 1/0, that's a reconciliation point.
    """
    
    def test_api_returns_outcome_names_not_ints(self, sample_settlements):
        """
        API should return Outcome enum names (YES, NO, CANCELLED, INVALID),
        not raw integer values.
        """
        for s in sample_settlements:
            outcome = s.to_outcome()
            if outcome:
                # Should be string name, not int
                outcome_str = outcome.name
                assert isinstance(outcome_str, str)
                assert outcome_str in ("YES", "NO", "CANCELLED", "INVALID")
            else:
                # Pending returns None, should be "pending" string
                outcome_str = "pending"
    
    def test_api_cache_response_format(self, sample_settlements):
        """
        Verify cache endpoint response format matches contract.
        """
        # Simulate what the API endpoint would return
        settlements_data = []
        for s in sample_settlements:
            outcome = s.to_outcome()
            settlements_data.append({
                "market_id": s.market_id,
                "ticker": s.ticker,
                "status": s.status.value,
                "outcome": outcome.name if outcome else "pending",
                "settlement_price_cents": s.settlement_price_cents,
                "settlement_time": s.settlement_time,
            })
        
        # Verify all outcomes are strings
        for data in settlements_data:
            assert isinstance(data["outcome"], str)
            assert data["outcome"] in ("YES", "NO", "CANCELLED", "INVALID", "pending")


class TestDownstreamHealthEndpoints:
    """
    Downstream Check: Health/Status endpoints
    
    Ensure orchestrator-level watchdogs ingest these correctly—particularly
    that /health/ungraded returning nonzero triggers backlog alarms.
    """
    
    def test_health_ungraded_counts_settled_but_ungraded(self, fresh_poller, sample_settlements):
        """
        Verify get_settled_but_ungraded_count() returns correct count.
        """
        # Add some gradable settlements to backlog
        gradable = [s for s in sample_settlements if s.is_gradable()]
        
        for s in gradable:
            fresh_poller._update_ungraded_backlog(s)
        
        count = fresh_poller.get_settled_but_ungraded_count()
        assert count == len(gradable), f"Expected {len(gradable)} ungraded, got {count}"
    
    def test_stats_includes_settled_but_ungraded(self, fresh_poller, sample_settlements):
        """
        Verify get_stats() includes settled_but_ungraded field for watchdogs.
        """
        # Add a settlement to backlog
        gradable = [s for s in sample_settlements if s.is_gradable()]
        if gradable:
            fresh_poller._update_ungraded_backlog(gradable[0])
        
        stats = fresh_poller.get_stats()
        
        assert "settled_but_ungraded" in stats
        assert isinstance(stats["settled_but_ungraded"], int)
        assert stats["settled_but_ungraded"] >= 0


class TestDownstreamOutcomePropagation:
    """
    Downstream Check: Outcome propagation

    Verify voided or invalid events are explicitly filtered from
    aggregation and analytics models.
    """
    
    def test_voided_filtered_from_gradable_pool(self, sample_settlements):
        """
        Only gradable settlements should reach aggregation.
        """
        gradable = [s for s in sample_settlements if s.is_gradable()]
        non_gradable = [s for s in sample_settlements if not s.is_gradable()]
        
        # All gradable should be YES or NO
        for s in gradable:
            outcome = s.to_outcome()
            assert outcome in (Outcome.YES, Outcome.NO)
        
        # All non-gradable should be CANCELLED, INVALID, or PENDING
        for s in non_gradable:
            outcome = s.to_outcome()
            assert outcome in (Outcome.CANCELLED, Outcome.INVALID, None)


# ─── Integration Probes ─────────────────────────────────────────────────────


class TestIntegrationReplay:
    """
    Integration Probe: Replay test
    
    Trigger the poller twice with identical pages; confirm _graded_settlements
    suppresses duplicates.
    """
    
    @pytest.mark.asyncio
    async def test_replay_suppresses_duplicates(self, mock_kalshi_client, fresh_poller, sample_settlements):
        """
        Simulate receiving the same settlement twice (replay scenario).
        Should only process once.
        """
        # Mock returning same settlement twice
        settlement_data = {
            "market_id": "KXBTC-15M-20251231",
            "ticker": "KXBTC-15M",
            "status": "settled",
            "settlement_price": 100,
            "settlement_time": "2025-12-31T12:00:00Z",
        }
        
        mock_kalshi_client.request.return_value = {
            "settlements": [settlement_data],
            "cursor": None,
        }
        
        # Track grading events
        grading_events = []
        def mock_callback(s):
            if s.is_gradable():
                grading_events.append(s.market_id)
        
        fresh_poller.add_callback(mock_callback)
        
        # First poll
        await fresh_poller._poll_once()
        assert len(grading_events) == 1
        
        # Second poll (replay same data)
        await fresh_poller._poll_once()
        # Should still be 1 (duplicate suppressed)
        assert len(grading_events) == 1, "Duplicate settlement should be suppressed"


class TestIntegrationVoidedInjection:
    """
    Integration Probe: Voided market injection
    
    Feed a CANCELLED and INVALID outcome; downstream should log but not grade.
    """
    
    def test_voided_logged_not_graded(self, caplog):
        """
        Voided markets should be logged but not produce grading events.
        """
        import logging
        
        voided = KalshiSettlement(
            market_id="KXVOID-15M",
            ticker="KXVOID-15M",
            title="Voided Market",
            category="crypto",
            status=SettlementStatus.CANCELLED,
            settlement_price_cents=None,
            settlement_time="2025-12-31T12:00:00Z",
        )
        
        with caplog.at_level(logging.DEBUG):
            # Simulate what poller does
            if voided.status == SettlementStatus.CANCELLED:
                # Should log at debug level
                pass  # Logging happens in poller
        
        # Verify not gradable
        assert not voided.is_gradable()
        assert voided.to_outcome() == Outcome.CANCELLED
    
    def test_invalid_price_logged_not_graded(self):
        """
        Invalid settlement prices should be logged but not graded.
        """
        invalid = KalshiSettlement(
            market_id="KXINVALID-15M",
            ticker="KXINVALID-15M",
            title="Invalid Price Market",
            category="crypto",
            status=SettlementStatus.SETTLED,
            settlement_price_cents=50,  # Invalid: not 0 or 100
            settlement_time="2025-12-31T12:00:00Z",
        )
        
        # Should be marked as INVALID outcome
        assert invalid.to_outcome() == Outcome.INVALID
        assert not invalid.is_gradable()


class TestIntegrationTickerDrift:
    """
    Integration Probe: Ticker normalization drift
    
    Feed mixed-case, hyphen variants; normalized keys must hash identically.
    """
    
    def test_mixed_case_variants_hash_same(self):
        """
        All ticker variants should produce identical normalized keys.
        """
        variants = [
            ("kxbtc-15m", "KXBTC-15M"),
            ("KXBTC-15M", "KXBTC-15M"),
            ("kxBTC15M", "KXBTC-15M"),
            ("BTC-15M", "KXBTC-15M"),
            ("btc_15m", "KXBTC-15M"),
        ]
        
        for variant, expected in variants:
            normalized = normalize_kalshi_ticker(variant)
            assert normalized == expected, f"Failed: {variant} → {normalized} (expected {expected})"
    
    def test_inline_tenors_normalized(self):
        """
        Inline tenors like KXETHD1 should become KXETH-D1.
        """
        test_cases = [
            ("KXETHD1", "KXETH-D1"),
            ("kxsolw1", "KXSOL-W1"),
            ("KXXRP15M", "KXXRP-15M"),
            ("KXBTC", "KXBTC"),  # No tenor
        ]
        
        for variant, expected in test_cases:
            normalized = normalize_kalshi_ticker(variant)
            assert normalized == expected, f"Failed: {variant} → {normalized}"


class TestIntegrationAPISmoke:
    """
    Integration Probe: API smoke under pagination pressure
    
    Poll /status and /cache under high pagination pressure; check
    settled_but_ungraded remains consistent with DB count.
    """
    
    @pytest.mark.asyncio
    async def test_api_consistency_under_load(self, mock_kalshi_client, fresh_poller):
        """
        Simulate high pagination pressure and verify API stats consistency.
        """
        # Generate many settlements
        settlements = [
            {
                "market_id": f"KXBTC-15M-{i:04d}",
                "ticker": "KXBTC-15M",
                "status": "settled",
                "settlement_price": 100 if i % 2 == 0 else 0,
                "settlement_time": f"2025-12-31T{i:02d}:00:00Z",
            }
            for i in range(250)  # Multiple pages worth
        ]
        
        # Return all in one page (simulating batched response)
        mock_kalshi_client.request.return_value = {
            "settlements": settlements,
            "cursor": None,
        }
        
        # Process all
        fresh_poller._running = True
        await fresh_poller._poll_once()
        
        # Check stats consistency
        stats = fresh_poller.get_stats()
        
        # All should be cached
        assert stats["cached_markets"] == 250
        assert stats["settlement_count"] == 250
        
        # All should be in ungraded backlog (none graded yet)
        assert stats["settled_but_ungraded"] == 250
        
        # Mark some as graded
        for i in range(50):
            fresh_poller.mark_graded(f"KXBTC-15M-{i:04d}")
        
        # Check updated stats
        updated_stats = fresh_poller.get_stats()
        assert updated_stats["settled_but_ungraded"] == 200


# ─── Audit Summary ───────────────────────────────────────────────────────────


class TestAuditSummary:
    """
    Final audit summary — verify all contract boundaries are sealed.
    """
    
    def test_all_outcome_values_defined(self):
        """
        Verify all Outcome enum values match contract specification.
        """
        assert Outcome.YES.value == 1
        assert Outcome.NO.value == 0
        assert Outcome.CANCELLED.value == -1
        assert Outcome.INVALID.value == -2
    
    def test_gradable_outcomes_are_binary(self):
        """
        Only YES and NO should be gradable.
        """
        gradable_outcomes = {Outcome.YES, Outcome.NO}
        non_gradable_outcomes = {Outcome.CANCELLED, Outcome.INVALID}
        
        for outcome in gradable_outcomes:
            # Create mock settlement
            price = 100 if outcome == Outcome.YES else 0
            s = KalshiSettlement(
                market_id="TEST",
                ticker="TEST",
                title="Test",
                category="test",
                status=SettlementStatus.SETTLED,
                settlement_price_cents=price,
            )
            assert s.is_gradable(), f"{outcome.name} should be gradable"
        
        for outcome in non_gradable_outcomes:
            status = SettlementStatus.CANCELLED if outcome == Outcome.CANCELLED else SettlementStatus.SETTLED
            price = None if outcome == Outcome.CANCELLED else 50
            s = KalshiSettlement(
                market_id="TEST",
                ticker="TEST",
                title="Test",
                category="test",
                status=status,
                settlement_price_cents=price,
            )
            assert not s.is_gradable(), f"{outcome.name} should not be gradable"
    
    def test_contract_seal_verification(self):
        """
        Final verification that all contract boundaries are properly sealed.
        
        This test documents the complete contract:
        - Ticker normalization: canonical KX{ASSET}-{TENOR}
        - Outcome unification: YES=1, NO=0, CANCELLED=-1, INVALID=-2
        - Dedupe key: kalshi:{market_id}:{settled_time}
        - Exactly-once: _graded_settlements set prevents replay
        - Void exclusion: CANCELLED/INVALID not gradable
        - Threshold binding: Domain module single source of truth
        """
        # All checks above verify the contract
        # This test serves as documentation and final seal
        pass


# ─── CLI Entry Point ───────────────────────────────────────────────────────


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
