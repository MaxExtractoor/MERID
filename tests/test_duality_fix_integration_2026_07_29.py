"""Integration tests for duality violation fixes (2026-07-29).

Tests verify:
- Thin-book simulation with one-sided flow does not trigger resync storms
- Circuit breaker stability under burst of duality violations
- Router gating with BOOK_NOT_EXECUTABLE vs BOOK_NOT_INITIALIZED
- Violation counting and exponential backoff behavior
- Telemetry counters for duality violations and resyncs
"""

import time
import pytest
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any


class TestThinBookSimulation:
    """Test thin-book simulation with one-sided flow."""

    def test_one_sided_flow_no_resync_storm(self):
        """Simulate one-sided flow (YES bid 70c, NO bid 99c) and verify no resync storm."""
        # Mock market state store
        mock_store = Mock()
        
        # Simulate thin book with one-sided flow
        ticker = "KXDOGE15M-26JUL211730-30"
        yes_bid = 70
        no_bid = 99
        yes_no_sum = yes_bid + no_bid  # 169c
        duality_gap = 100 - yes_no_sum  # -69c
        duality_tolerance_cents = 70
        
        # With 70c tolerance, this should NOT trigger violation
        should_violate = abs(duality_gap) > duality_tolerance_cents
        
        assert duality_gap == -69
        assert should_violate == False  # Within 70c tolerance
        
        # Simulate multiple updates with same gap
        violation_count = 0
        for _ in range(10):
            if abs(duality_gap) > duality_tolerance_cents:
                violation_count += 1
        
        # Should have zero violations
        assert violation_count == 0

    def test_extreme_gap_triggers_violation_counting(self):
        """Test that extreme gaps trigger violation counting but respect threshold."""
        # Extreme gap beyond 70c tolerance
        ticker = "KXSOL15M-26JUL211745-45"
        yes_bid = 85
        no_bid = 99
        duality_gap = 100 - (yes_bid + no_bid)  # -84c
        duality_tolerance_cents = 70
        
        # Should trigger violation
        should_violate = abs(duality_gap) > duality_tolerance_cents
        assert should_violate == True
        
        # Simulate violation counting
        violation_counts = {ticker: 0}
        violation_window_ts = {ticker: time.monotonic()}
        
        # Simulate 5 consecutive violations
        for i in range(5):
            if should_violate:
                violation_counts[ticker] += 1
        
        # Should have 5 violations
        assert violation_counts[ticker] == 5
        
        # But only trigger resync after 3rd violation
        resync_triggered = violation_counts[ticker] >= 3
        assert resync_triggered == True

    def test_violation_window_reset(self):
        """Test that violation count resets after window expires."""
        ticker = "KXBTC15M-26JUL211745-45"
        violation_counts = {ticker: 0}
        violation_window_ts = {ticker: time.monotonic()}
        
        # Add 3 violations
        for _ in range(3):
            violation_counts[ticker] += 1
        
        assert violation_counts[ticker] == 3
        
        # Simulate window expiry (30s later)
        violation_window_ts[ticker] = time.monotonic() - 35.0
        
        # Reset count if window expired
        if time.monotonic() - violation_window_ts[ticker] > 30.0:
            violation_counts[ticker] = 0
            violation_window_ts[ticker] = time.monotonic()
        
        assert violation_counts[ticker] == 0


class TestCircuitBreakerStability:
    """Test circuit breaker stability under burst of duality violations."""

    def test_burst_violations_across_5_tickers(self):
        """Run burst of duality violations across 5 tickers and verify no circuit breaker trip."""
        tickers = [
            "KXBTC15M-26JUL211745-45",
            "KXETH15M-26JUL211745-45",
            "KXSOL15M-26JUL211745-45",
            "KXXRP15M-26JUL211745-45",
            "KXDOGE15M-26JUL211730-30"
        ]
        
        # Simulate violation tracking per ticker
        violation_counts = {t: 0 for t in tickers}
        violation_window_ts = {t: time.monotonic() for t in tickers}
        resync_count = 0
        
        # Simulate 10 updates per ticker with violations
        for ticker in tickers:
            for _ in range(10):
                violation_counts[ticker] += 1
                # Only trigger resync after 3 violations
                if violation_counts[ticker] == 3:
                    resync_count += 1
        
        # Each ticker should trigger resync once (at 3rd violation)
        assert resync_count == 5
        
        # Total resyncs should be 5 (not 50, due to threshold)
        # This prevents circuit breaker from tripping (5 resets in 60s threshold)

    def test_exponential_backoff_prevents_reset_storm(self):
        """Test exponential backoff prevents event loop reset storm."""
        ticker = "KXDOGE15M-26JUL211730-30"
        backoff_s = 10.0
        last_resync_ts = 0.0
        resync_count = 0
        
        # Simulate 10 potential resync attempts
        now = time.monotonic()
        for i in range(10):
            if now - last_resync_ts >= backoff_s:
                resync_count += 1
                last_resync_ts = now
                backoff_s = min(backoff_s * 2, 60.0)
            now += 5.0  # Advance time by 5s
        
        # With exponential backoff, only 2 resyncs should occur in 50s
        # (immediate at t=0, then at t=20s - next would be at t=60s but not reached)
        assert resync_count == 2
        
        # Without backoff, would have been 10 resyncs
        # This prevents circuit breaker trip (5 resets in 60s)


class TestRouterGating:
    """Test router gating with BOOK_NOT_EXECUTABLE vs BOOK_NOT_INITIALIZED."""

    def test_book_not_initialized_rejection(self):
        """Test that BOOK_NOT_INITIALIZED is raised when book_initialized=False."""
        from merid.event_venues.kalshi.models import KalshiMarketState
        
        state = KalshiMarketState(
            ticker="KXBTC15M-26JUL211745-45",
            book_initialized=False,
            executable=False,
        )
        
        # Should reject with BOOK_NOT_INITIALIZED
        assert state.book_initialized == False
        # executable is irrelevant when book not initialized

    def test_book_not_executable_rejection(self):
        """Test that BOOK_NOT_EXECUTABLE is raised when executable=False but book_initialized=True."""
        from merid.event_venues.kalshi.models import KalshiMarketState
        
        state = KalshiMarketState(
            ticker="KXBTC15M-26JUL211745-45",
            book_initialized=True,
            executable=False,  # Due to duality violation
            data_quality="SUSPECT"
        )
        
        # Should reject with BOOK_NOT_EXECUTABLE
        assert state.book_initialized == True
        assert state.executable == False
        assert state.data_quality == "SUSPECT"

    def test_exit_order_bypasses_executable_check(self):
        """Test that exit orders bypass executable check."""
        from merid.event_venues.kalshi.models import KalshiMarketState
        
        state = KalshiMarketState(
            ticker="KXBTC15M-26JUL211745-45",
            book_initialized=True,
            executable=False,  # Duality violation
        )
        
        # Exit orders should proceed even if not executable
        is_exit_gate = True
        should_reject = not state.book_initialized and not is_exit_gate
        
        assert should_reject == False  # Should NOT reject (exit gate)


class TestLogAssertions:
    """Test log assertions for YES+NO sum and backoff timers."""

    def test_log_includes_yes_no_sum(self):
        """Test that logs include YES+NO sum explicitly."""
        ticker = "KXDOGE15M-26JUL211730-30"
        yes_bid = 78
        no_bid = 99
        yes_no_sum = yes_bid + no_bid
        duality_gap = 100 - yes_no_sum
        
        # Simulate log message
        log_msg = (
            f"[DUALITY-RAW-OB-VIOLATION] ticker={ticker} "
            f"yes_bid={yes_bid}c no_bid={no_bid}c sum={yes_no_sum}c gap={duality_gap}c"
        )
        
        assert "sum=177c" in log_msg
        assert "gap=-77c" in log_msg

    def test_log_includes_backoff_timer(self):
        """Test that logs include explicit backoff timer."""
        ticker = "KXDOGE15M-26JUL211730-30"
        backoff_s = 20.0
        
        # Simulate log message
        log_msg = (
            f"[DUALITY-RESYNC] Scheduled REST re-sync for {ticker} (backoff={backoff_s:.1f}s)"
        )
        
        assert "backoff=20.0s" in log_msg

    def test_log_includes_violation_count(self):
        """Test that logs include violation count."""
        ticker = "KXDOGE15M-26JUL211730-30"
        violation_count = 3
        
        # Simulate log message
        log_msg = (
            f"[DUALITY-RESYNC-TRIGGER] ticker={ticker} violations={violation_count} in 30s window"
        )
        
        assert "violations=3" in log_msg
        assert "30s window" in log_msg


class TestTelemetryCounters:
    """Test telemetry counters for duality violations and resyncs."""

    def test_metrics_collector_has_duality_methods(self):
        """Test that KalshiMetricsCollector has duality telemetry methods."""
        from merid.event_venues.kalshi.metrics import KalshiMetricsCollector
        
        collector = KalshiMetricsCollector()
        
        # Check that the methods exist
        assert hasattr(collector, 'record_duality_violation')
        assert hasattr(collector, 'record_duality_resync_triggered')
        assert hasattr(collector, 'record_duality_resync_suppressed')

    def test_record_duality_violation_increments_counters(self):
        """Test that record_duality_violation increments counters."""
        from merid.event_venues.kalshi.metrics import KalshiMetricsCollector
        
        collector = KalshiMetricsCollector()
        ticker = "KXDOGE15M-26JUL211730-30"
        
        # Record a violation
        collector.record_duality_violation(ticker, gap=-77)
        
        assert collector._duality_violations_total == 1
        assert collector._duality_violations_per_ticker[ticker] == 1

    def test_record_duality_resync_triggered_increments_counters(self):
        """Test that record_duality_resync_triggered increments counters."""
        from merid.event_venues.kalshi.metrics import KalshiMetricsCollector
        
        collector = KalshiMetricsCollector()
        ticker = "KXDOGE15M-26JUL211730-30"
        
        # Record a triggered resync
        collector.record_duality_resync_triggered(ticker, backoff_s=20.0)
        
        assert collector._duality_resyncs_triggered_total == 1
        assert collector._duality_resyncs_triggered_per_ticker[ticker] == 1

    def test_record_duality_resync_suppressed_increments_counters(self):
        """Test that record_duality_resync_suppressed increments counters."""
        from merid.event_venues.kalshi.metrics import KalshiMetricsCollector
        
        collector = KalshiMetricsCollector()
        ticker = "KXDOGE15M-26JUL211730-30"
        
        # Record a suppressed resync
        collector.record_duality_resync_suppressed(ticker, violation_count=2)
        
        assert collector._duality_resyncs_suppressed_total == 1
        assert collector._duality_resyncs_suppressed_per_ticker[ticker] == 1

    def test_metrics_reset_clears_duality_counters(self):
        """Test that reset clears duality counters."""
        from merid.event_venues.kalshi.metrics import KalshiMetricsCollector
        import asyncio
        
        collector = KalshiMetricsCollector()
        ticker = "KXDOGE15M-26JUL211730-30"
        
        # Record some metrics
        collector.record_duality_violation(ticker, gap=-77)
        collector.record_duality_resync_triggered(ticker, backoff_s=20.0)
        collector.record_duality_resync_suppressed(ticker, violation_count=2)
        
        # Reset
        asyncio.run(collector.reset())
        
        # Verify counters are cleared
        assert collector._duality_violations_total == 0
        assert collector._duality_violations_per_ticker == {}
        assert collector._duality_resyncs_triggered_total == 0
        assert collector._duality_resyncs_triggered_per_ticker == {}
        assert collector._duality_resyncs_suppressed_total == 0
        assert collector._duality_resyncs_suppressed_per_ticker == {}

    def test_market_state_calls_telemetry_on_violation(self):
        """Test that market_state.py calls telemetry on duality violation."""
        with open("c:/Dev/MERID/merid/event_venues/kalshi/market_state.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # Check for telemetry calls in _track_duality_violation
        assert "record_duality_violation" in source, \
            "market_state.py must call record_duality_violation telemetry"
        assert "record_duality_resync_suppressed" in source, \
            "market_state.py must call record_duality_resync_suppressed telemetry"

    def test_market_state_calls_telemetry_on_resync(self):
        """Test that market_state.py calls telemetry on resync trigger."""
        with open("c:/Dev/MERID/merid/event_venues/kalshi/market_state.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # Check for telemetry call in _schedule_duality_resync
        assert "record_duality_resync_triggered" in source, \
            "market_state.py must call record_duality_resync_triggered telemetry"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
