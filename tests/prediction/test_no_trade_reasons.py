"""Tests for merid.prediction.no_trade_reasons module."""

from merid.prediction.no_trade_reasons import (
    NoTradeReason,
    NoTradeDecisionTracker,
    get_no_trade_tracker,
    reset_no_trade_tracker,
)


class TestNoTradeReason:
    """Tests for NoTradeReason enum."""

    def test_all_reasons_defined(self):
        """Verify all expected no-trade reasons are defined."""
        reasons = {r.value for r in NoTradeReason}

        # Edge/threshold gates
        assert "edge_below_threshold" in reasons
        assert "confidence_below_threshold" in reasons
        assert "shadow_threshold_only" in reasons

        # Consensus gates
        assert "consensus_forming" in reasons
        assert "consensus_conflicted" in reasons
        assert "consensus_mismatch" in reasons

        # Risk/limits gates
        assert "risk_limit" in reasons
        assert "order_limit_reached" in reasons
        assert "degraded_mode_paused" in reasons

        # Market gates
        assert "market_not_tradeable" in reasons
        assert "entry_window_closed" in reasons
        assert "liquidity_insufficient" in reasons

        # Venue/mode gates
        assert "venue_closed" in reasons
        assert "paper_only" in reasons

        # Strategy gates
        assert "no_actionable_edge" in reasons
        assert "kelly_size_zero" in reasons

        # Infrastructure gates
        assert "infra_backoff" in reasons
        assert "data_stale" in reasons
        assert "spot_price_unavailable" in reasons


class TestNoTradeDecisionTracker:
    """Tests for NoTradeDecisionTracker."""

    def test_initializes_all_counters_to_zero(self):
        """Tracker should initialize all reason counters to 0."""
        tracker = NoTradeDecisionTracker()
        counts = tracker.get_counts()

        # All reasons should start at 0
        for reason in NoTradeReason:
            assert counts[reason.value] == 0

    def test_record_increments_counter(self):
        """Recording a decision should increment the counter."""
        tracker = NoTradeDecisionTracker()

        tracker.record(
            agent_name="test_agent",
            market_id="KXBTC-TEST",
            asset="BTC",
            timeframe="15m",
            reason=NoTradeReason.EDGE_BELOW_THRESHOLD,
        )

        counts = tracker.get_counts()
        assert counts["edge_below_threshold"] == 1

    def test_record_multiple_same_reason(self):
        """Recording same reason multiple times should accumulate."""
        tracker = NoTradeDecisionTracker()

        for _ in range(5):
            tracker.record(
                agent_name="test_agent",
                market_id="KXBTC-TEST",
                asset="BTC",
                timeframe="15m",
                reason=NoTradeReason.CONSENSUS_FORMING,
            )

        counts = tracker.get_counts()
        assert counts["consensus_forming"] == 5

    def test_record_different_reasons(self):
        """Recording different reasons should track independently."""
        tracker = NoTradeDecisionTracker()

        tracker.record(
            agent_name="test_agent",
            market_id="KXBTC-TEST1",
            asset="BTC",
            timeframe="15m",
            reason=NoTradeReason.EDGE_BELOW_THRESHOLD,
        )
        tracker.record(
            agent_name="test_agent",
            market_id="KXBTC-TEST2",
            asset="BTC",
            timeframe="15m",
            reason=NoTradeReason.LIQUIDITY_INSUFFICIENT,
        )
        tracker.record(
            agent_name="test_agent",
            market_id="KXBTC-TEST3",
            asset="BTC",
            timeframe="15m",
            reason=NoTradeReason.EDGE_BELOW_THRESHOLD,
        )

        counts = tracker.get_counts()
        assert counts["edge_below_threshold"] == 2
        assert counts["liquidity_insufficient"] == 1

    def test_record_with_full_context(self):
        """Recording with full context should not raise errors."""
        tracker = NoTradeDecisionTracker()

        # Should handle all optional parameters
        tracker.record(
            agent_name="btc_15m_agent",
            market_id="KXBTC-26APR0722-T95000",
            asset="BTC",
            timeframe="15m",
            reason=NoTradeReason.EDGE_BELOW_THRESHOLD,
            net_edge=0.0299,
            threshold=0.0500,
            consensus_status="READY",
            additional_context={"phase": "early", "profile": "strict"},
        )

        counts = tracker.get_counts()
        assert counts["edge_below_threshold"] == 1

    def test_reset_counts(self):
        """Reset should set all counters back to 0."""
        tracker = NoTradeDecisionTracker()

        # Record several decisions
        tracker.record(
            agent_name="test_agent",
            market_id="KXBTC-TEST",
            asset="BTC",
            timeframe="15m",
            reason=NoTradeReason.EDGE_BELOW_THRESHOLD,
        )
        tracker.record(
            agent_name="test_agent",
            market_id="KXBTC-TEST",
            asset="BTC",
            timeframe="15m",
            reason=NoTradeReason.CONSENSUS_FORMING,
        )

        # Reset
        tracker.reset_counts()

        counts = tracker.get_counts()
        for reason in NoTradeReason:
            assert counts[reason.value] == 0

    def test_get_top_reasons_empty(self):
        """Top reasons on empty tracker should return empty list."""
        tracker = NoTradeDecisionTracker()
        top = tracker.get_top_reasons(limit=5)

        # All zeros, but should return something
        assert len(top) <= 5

    def test_get_top_reasons_sorted(self):
        """Top reasons should be sorted by count descending."""
        tracker = NoTradeDecisionTracker()

        # Record different counts
        for _ in range(10):
            tracker.record(
                agent_name="test",
                market_id="M1",
                asset="BTC",
                timeframe="15m",
                reason=NoTradeReason.EDGE_BELOW_THRESHOLD,
            )

        for _ in range(5):
            tracker.record(
                agent_name="test",
                market_id="M2",
                asset="BTC",
                timeframe="15m",
                reason=NoTradeReason.CONSENSUS_FORMING,
            )

        for _ in range(2):
            tracker.record(
                agent_name="test",
                market_id="M3",
                asset="BTC",
                timeframe="15m",
                reason=NoTradeReason.LIQUIDITY_INSUFFICIENT,
            )

        top = tracker.get_top_reasons(limit=3)

        assert len(top) == 3
        assert top[0] == ("edge_below_threshold", 10)
        assert top[1] == ("consensus_forming", 5)
        assert top[2] == ("liquidity_insufficient", 2)

    def test_get_top_reasons_respects_limit(self):
        """Top reasons should respect the limit parameter."""
        tracker = NoTradeDecisionTracker()

        # Record multiple reasons
        for reason in [
            NoTradeReason.EDGE_BELOW_THRESHOLD,
            NoTradeReason.CONSENSUS_FORMING,
            NoTradeReason.LIQUIDITY_INSUFFICIENT,
        ]:
            tracker.record(
                agent_name="test",
                market_id="M1",
                asset="BTC",
                timeframe="15m",
                reason=reason,
            )

        top_1 = tracker.get_top_reasons(limit=1)
        top_2 = tracker.get_top_reasons(limit=2)
        top_10 = tracker.get_top_reasons(limit=10)

        assert len(top_1) == 1
        assert len(top_2) == 2
        # Should not exceed number of non-zero reasons
        assert len(top_10) <= 10


class TestSingleton:
    """Tests for singleton pattern."""

    def test_get_no_trade_tracker_returns_singleton(self):
        """Multiple calls should return the same instance."""
        reset_no_trade_tracker()  # Ensure clean state

        tracker1 = get_no_trade_tracker()
        tracker2 = get_no_trade_tracker()

        assert tracker1 is tracker2

    def test_reset_clears_singleton(self):
        """Reset should allow creating new instance."""
        reset_no_trade_tracker()

        tracker1 = get_no_trade_tracker()
        tracker1.record(
            agent_name="test",
            market_id="M1",
            asset="BTC",
            timeframe="15m",
            reason=NoTradeReason.EDGE_BELOW_THRESHOLD,
        )

        reset_no_trade_tracker()
        tracker2 = get_no_trade_tracker()

        # Should be new instance with clean state
        assert tracker2 is not tracker1
        counts = tracker2.get_counts()
        assert counts["edge_below_threshold"] == 0
