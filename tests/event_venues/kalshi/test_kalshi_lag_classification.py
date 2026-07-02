"""Tests for Kalshi lag classification and staleness features."""

from __future__ import annotations

import time
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

# Configure logging to prevent test hanging
logging.basicConfig(level=logging.WARNING)

from merid.event_venues.kalshi.market_state import (
    KalshiMarketStateStore,
    LagClassifier,
    StalenessRegime,
)


# ── Helpers ────────────────────────────────────────────────────────────────


def _iso(seconds_from_now: float) -> str:
    """Return an ISO-8601 string *seconds_from_now* seconds in the future."""
    dt = datetime.now(timezone.utc) + timedelta(seconds=seconds_from_now)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _snapshot_msg(ticker: str, yes: list, no: list) -> dict:
    return {
        "type": "orderbook_snapshot",
        "ticker": ticker,
        "yes": yes,
        "no": no,
    }


# ── LagClassifier Enum ─────────────────────────────────────────────────────


class TestLagClassifier:
    def test_enum_values(self):
        """LagClassifier enum has all expected values."""
        assert LagClassifier.NORMAL == "normal"
        assert LagClassifier.WS_CONNECTION_ISSUE == "ws_connection_issue"
        assert LagClassifier.NETWORK_LATENCY == "network_latency"
        assert LagClassifier.EXCHANGE_API_DELAY == "exchange_api_delay"
        assert LagClassifier.LOCAL_PROCESSING_LAG == "local_processing_lag"

    def test_enum_string_comparison(self):
        """LagClassifier values can be compared as strings."""
        assert LagClassifier.NORMAL.value == "normal"
        assert str(LagClassifier.NORMAL) == "LagClassifier.NORMAL"


# ── Lag Classification Tracking Fields ────────────────────────────────────


class TestLagTrackingFields:
    def setup_method(self):
        logging.getLogger("merid.event_venues.kalshi.market_state").setLevel(logging.WARNING)
        self.store = KalshiMarketStateStore()

    def test_initial_lag_tracking_fields(self):
        """All lag tracking fields are initialized to default values."""
        assert self.store._ws_last_ping_monotonic == 0.0
        assert self.store._ws_last_pong_sent_monotonic == 0.0
        assert self.store._ws_pong_rtt_ms == 0.0
        assert self.store._rest_latency_ms == 0.0
        assert self.store._rest_user_ts_lag_s == 0.0
        assert self.store._net_ping_ms == 0.0
        assert self.store._processing_lag_ms == 0.0
        assert self.store._current_lag_class == LagClassifier.NORMAL

    def test_processing_lag_tracking_fields(self):
        """Processing lag tracking fields are initialized."""
        assert isinstance(self.store._msg_recv_monotonic, dict)
        assert isinstance(self.store._msg_proc_monotonic, dict)
        assert len(self.store._msg_recv_monotonic) == 0
        assert len(self.store._msg_proc_monotonic) == 0

    def test_cadence_tracking_fields(self):
        """WS message cadence tracking fields are initialized."""
        assert isinstance(self.store._book_update_timestamps, dict)
        assert isinstance(self.store._baseline_update_intervals, dict)
        assert isinstance(self.store._updates_per_minute, dict)
        assert self.store._cadence_window_seconds == 60.0

    def test_rtt_volatility_fields(self):
        """RTT volatility tracking fields are initialized."""
        assert isinstance(self.store._ws_rtt_samples, list)
        assert isinstance(self.store._rest_rtt_samples, list)
        assert isinstance(self.store._rtt_sample_timestamps, list)
        assert self.store._rtt_window_seconds == 300.0
        assert self.store._ws_rtt_mean == 0.0
        assert self.store._ws_rtt_std == 0.0
        assert self.store._rest_rtt_mean == 0.0
        assert self.store._rest_rtt_std == 0.0

    def test_rate_limiting_fields(self):
        """Rate limiting tracking fields are initialized."""
        assert self.store._rest_calls_per_minute == 0.0
        assert isinstance(self.store._rest_call_timestamps, list)
        assert self.store._adaptive_poll_interval == 60.0
        assert self.store._base_poll_interval == 60.0
        assert self.store._min_poll_interval == 30.0
        assert self.store._max_poll_interval == 300.0
        assert self.store._rate_limit_hits == 0
        assert self.store._last_429_timestamp == 0.0
        assert self.store._backoff_until == 0.0


# ── Lag Tracking Update Methods ─────────────────────────────────────────────


class TestLagTrackingUpdateMethods:
    def setup_method(self):
        logging.getLogger("merid.event_venues.kalshi.market_state").setLevel(logging.WARNING)
        self.store = KalshiMarketStateStore()

    def test_update_ws_ping_tracking_ping_received(self):
        """WS ping tracking updates on ping received."""
        now = time.monotonic()
        self.store._update_ws_ping_tracking(ping_received=True)
        assert self.store._ws_last_ping_monotonic > 0
        assert self.store._ws_last_ping_monotonic >= now

    def test_update_ws_ping_tracking_pong_sent(self):
        """WS ping tracking updates on pong sent."""
        now = time.monotonic()
        self.store._update_ws_ping_tracking(pong_sent=True)
        assert self.store._ws_last_pong_sent_monotonic > 0
        assert self.store._ws_last_pong_sent_monotonic >= now

    def test_update_ws_ping_tracking_rtt_calculation(self):
        """WS ping tracking calculates RTT when ping received after pong sent."""
        # Simulate: we sent a pong, then Kalshi sends us a ping
        self.store._update_ws_ping_tracking(pong_sent=True)
        pong_time = self.store._ws_last_pong_sent_monotonic
        assert pong_time > 0  # Verify pong time was recorded
        
        time.sleep(0.02)  # 20ms delay to ensure measurable RTT
        self.store._update_ws_ping_tracking(ping_received=True)
        
        # RTT is calculated as (ping_received - pong_sent)
        # The RTT is stored in _ws_pong_rtt_ms
        # Verify the calculation happened
        expected_rtt = (self.store._ws_last_ping_monotonic - pong_time) * 1000.0
        assert self.store._ws_pong_rtt_ms > 0, f"RTT should be > 0, got {self.store._ws_pong_rtt_ms}. pong_time={pong_time}, ping_time={self.store._ws_last_ping_monotonic}, expected_rtt={expected_rtt}"
        # RTT should be approximately the delay in ms (allowing for timing variance)
        assert self.store._ws_pong_rtt_ms >= 10  # At least 10ms

    def test_update_rest_latency_tracking(self):
        """REST latency tracking updates."""
        self.store._update_rest_latency_tracking(150.5)
        assert self.store._rest_latency_ms == 150.5

    def test_update_network_ping_tracking(self):
        """Network ping tracking updates."""
        self.store._update_network_ping_tracking(25.0)
        assert self.store._net_ping_ms == 25.0

    def test_update_processing_lag_tracking(self):
        """Processing lag tracking updates."""
        self.store._update_processing_lag_tracking(5.5)
        assert self.store._processing_lag_ms == 5.5

    def test_record_msg_recv_timestamp(self):
        """Message receive timestamp is recorded."""
        ticker = "KXBTC15M-T"
        now = time.monotonic()
        self.store._record_msg_recv_timestamp(ticker)
        assert ticker in self.store._msg_recv_monotonic
        assert self.store._msg_recv_monotonic[ticker] >= now

    def test_record_msg_proc_timestamp(self):
        """Message processing timestamp is recorded and lag calculated."""
        ticker = "KXBTC15M-T"
        self.store._record_msg_recv_timestamp(ticker)
        assert ticker in self.store._msg_recv_monotonic  # Verify recv was recorded
        
        recv_time = self.store._msg_recv_monotonic[ticker]
        
        time.sleep(0.05)  # 50ms delay to ensure measurable lag (more robust for parallel tests)
        self.store._record_msg_proc_timestamp(ticker)
        assert ticker in self.store._msg_proc_monotonic
        
        # Verify lag was calculated (allowing for timing variance)
        # The lag should be approximately the delay between recv and proc
        expected_lag = (self.store._msg_proc_monotonic[ticker] - recv_time) * 1000.0
        assert self.store._processing_lag_ms > 0, f"Processing lag should be > 0, got {self.store._processing_lag_ms}. recv_time={recv_time}, proc_time={self.store._msg_proc_monotonic[ticker]}, expected_lag={expected_lag}"
        assert self.store._processing_lag_ms >= 30  # At least 30ms (allowing for timing variance)


# ── Lag Classification ───────────────────────────────────────────────────────


class TestLagClassification:
    def setup_method(self):
        logging.getLogger("merid.event_venues.kalshi.market_state").setLevel(logging.WARNING)
        self.store = KalshiMarketStateStore()

    def test_classify_lag_normal_by_default(self):
        """Lag classification returns NORMAL when no issues detected."""
        lag_class = self.store._classify_lag()
        assert lag_class == LagClassifier.NORMAL

    def test_classify_lag_ws_connection_issue(self):
        """Lag classification detects WS connection issue."""
        # Simulate long ping gap (>30s)
        self.store._ws_last_ping_monotonic = time.monotonic() - 35.0
        lag_class = self.store._classify_lag()
        assert lag_class == LagClassifier.WS_CONNECTION_ISSUE

    def test_classify_lag_network_latency(self):
        """Lag classification detects network latency."""
        # Simulate elevated network ping and REST latency
        self.store._net_ping_ms = 250.0  # > 200ms threshold
        self.store._rest_latency_ms = 600.0  # > 500ms threshold
        lag_class = self.store._classify_lag()
        assert lag_class == LagClassifier.NETWORK_LATENCY

    def test_classify_lag_exchange_api_delay(self):
        """Lag classification detects exchange API delay."""
        # Simulate REST user timestamp lag
        self.store._rest_user_ts_lag_s = 35.0  # > 30s threshold
        lag_class = self.store._classify_lag()
        assert lag_class == LagClassifier.EXCHANGE_API_DELAY

    def test_classify_lag_local_processing_lag(self):
        """Lag classification detects local processing lag."""
        # Simulate processing lag
        self.store._processing_lag_ms = 150.0  # > 100ms threshold
        lag_class = self.store._classify_lag()
        assert lag_class == LagClassifier.LOCAL_PROCESSING_LAG

    def test_classify_lag_priority_order(self):
        """Lag classification respects priority order (WS connection first)."""
        # Set multiple issues
        self.store._ws_last_ping_monotonic = time.monotonic() - 35.0
        self.store._net_ping_ms = 250.0
        self.store._rest_user_ts_lag_s = 35.0
        self.store._processing_lag_ms = 150.0
        
        # WS connection issue should be detected first
        lag_class = self.store._classify_lag()
        assert lag_class == LagClassifier.WS_CONNECTION_ISSUE


# ── WS Message Cadence Tracking ─────────────────────────────────────────────


class TestWSCadenceTracking:
    def setup_method(self):
        logging.getLogger("merid.event_venues.kalshi.market_state").setLevel(logging.WARNING)
        self.store = KalshiMarketStateStore()

    def test_record_book_update_timestamp(self):
        """Book update timestamp is recorded."""
        ticker = "KXBTC15M-T"
        now = time.monotonic()
        self.store._record_book_update_timestamp(ticker, now)
        assert ticker in self.store._book_update_timestamps
        assert len(self.store._book_update_timestamps[ticker]) == 1

    def test_get_updates_per_minute(self):
        """Updates per minute is calculated."""
        ticker = "KXBTC15M-T"
        now = time.monotonic()
        
        # Add 30 updates within the window
        for i in range(30):
            self.store._record_book_update_timestamp(ticker, now + i)
        
        updates_per_min = self.store._get_updates_per_minute(ticker)
        assert updates_per_min > 0
        # Should be approximately 30 updates in 60s window
        assert 25 < updates_per_min < 35

    def test_update_baseline_interval(self):
        """Baseline interval is calculated from recent updates."""
        ticker = "KXBTC15M-T"
        now = time.monotonic()
        
        # Add updates with 2-second intervals
        for i in range(10):
            self.store._record_book_update_timestamp(ticker, now + i * 2.0)
        
        self.store._update_baseline_interval(ticker)
        assert ticker in self.store._baseline_update_intervals
        # Baseline should be approximately 2 seconds
        baseline = self.store._baseline_update_intervals[ticker]
        assert 1.5 < baseline < 2.5

    def test_cadence_window_pruning(self):
        """Old timestamps are pruned from the window."""
        ticker = "KXBTC15M-T"
        now = time.monotonic()
        
        # Add old timestamps outside the window
        old_timestamp = now - 120.0  # 2 minutes ago
        self.store._record_book_update_timestamp(ticker, old_timestamp)
        
        # Add recent timestamp
        self.store._record_book_update_timestamp(ticker, now)
        
        # Only recent timestamp should remain
        assert len(self.store._book_update_timestamps[ticker]) == 1
        assert self.store._book_update_timestamps[ticker][0] >= now - 60.0


# ── RTT Volatility Tracking ─────────────────────────────────────────────────


class TestRTTVolatilityTracking:
    def setup_method(self):
        logging.getLogger("merid.event_venues.kalshi.market_state").setLevel(logging.WARNING)
        self.store = KalshiMarketStateStore()

    def test_record_rtt_sample_ws(self):
        """WS RTT sample is recorded."""
        now = time.monotonic()
        self.store._record_rtt_sample("ws", 45.0, now)
        assert len(self.store._ws_rtt_samples) == 1
        assert self.store._ws_rtt_samples[0] == 45.0

    def test_record_rtt_sample_rest(self):
        """REST RTT sample is recorded."""
        now = time.monotonic()
        self.store._record_rtt_sample("rest", 150.0, now)
        assert len(self.store._rest_rtt_samples) == 1
        assert self.store._rest_rtt_samples[0] == 150.0

    def test_update_rtt_stats(self):
        """RTT mean and std are calculated."""
        # Add samples
        for rtt in [40.0, 45.0, 50.0, 55.0, 60.0]:
            self.store._record_rtt_sample("ws", rtt, time.monotonic())
        
        # Check mean
        expected_mean = sum([40.0, 45.0, 50.0, 55.0, 60.0]) / 5
        assert abs(self.store._ws_rtt_mean - expected_mean) < 0.1
        
        # Check std is calculated
        assert self.store._ws_rtt_std > 0

    def test_get_rtt_volatility_score(self):
        """RTT volatility score (coefficient of variation) is calculated."""
        # Add samples with some variance
        for rtt in [40.0, 45.0, 50.0, 55.0, 60.0]:
            self.store._record_rtt_sample("ws", rtt, time.monotonic())
        
        volatility = self.store._get_rtt_volatility_score("ws")
        assert volatility > 0
        # Coefficient of variation should be reasonable
        assert volatility < 1.0

    def test_rtt_window_pruning(self):
        """Old RTT samples are pruned from the window."""
        now = time.monotonic()
        
        # Add old sample outside window
        self.store._record_rtt_sample("ws", 45.0, now - 400.0)
        
        # Add recent sample
        self.store._record_rtt_sample("ws", 50.0, now)
        
        # Only recent sample should remain
        assert len(self.store._ws_rtt_samples) == 1


# ── Rate Limiting & Adaptive Polling ───────────────────────────────────────


class TestRateLimiting:
    def setup_method(self):
        logging.getLogger("merid.event_venues.kalshi.market_state").setLevel(logging.WARNING)
        self.store = KalshiMarketStateStore()

    def test_record_rest_call(self):
        """REST call is recorded for rate tracking."""
        self.store._record_rest_call()
        assert self.store._rest_calls_per_minute == 1.0
        assert len(self.store._rest_call_timestamps) == 1

    def test_record_rest_call_pruning(self):
        """Old REST call timestamps are pruned."""
        now = time.monotonic()
        
        # Add old call outside 1-minute window
        self.store._rest_call_timestamps.append(now - 120.0)
        
        # Add recent call
        self.store._record_rest_call()
        
        # Only recent call should remain
        assert len(self.store._rest_call_timestamps) == 1
        assert self.store._rest_calls_per_minute == 1.0

    def test_record_rate_limit_hit(self):
        """Rate limit hit is recorded and backoff is triggered."""
        self.store._record_rate_limit_hit()
        assert self.store._rate_limit_hits == 1
        assert self.store._last_429_timestamp > 0
        assert self.store._backoff_until > time.monotonic()

    def test_check_backoff_active(self):
        """Backoff check returns True when in backoff period."""
        self.store._record_rate_limit_hit()
        assert self.store._check_backoff() is True

    def test_check_backoff_inactive(self):
        """Backoff check returns False when backoff period expired."""
        self.store._record_rate_limit_hit()
        # Manually set backoff to past
        self.store._backoff_until = time.monotonic() - 1.0
        assert self.store._check_backoff() is False

    def test_update_adaptive_poll_interval_healthy_calm(self):
        """Poll interval increases when WS is healthy and market is calm."""
        self.store._update_adaptive_poll_interval(ws_healthy=True, market_activity=0.2)
        # Should increase from base 60s
        assert self.store._adaptive_poll_interval > 60.0

    def test_update_adaptive_poll_interval_unhealthy_active(self):
        """Poll interval decreases when WS is unhealthy or market is active."""
        self.store._update_adaptive_poll_interval(ws_healthy=False, market_activity=0.8)
        # Should decrease from base 60s
        assert self.store._adaptive_poll_interval < 60.0

    def test_update_adaptive_poll_interval_respects_bounds(self):
        """Poll interval respects min and max bounds."""
        # Test max bound
        self.store._update_adaptive_poll_interval(ws_healthy=True, market_activity=0.1)
        assert self.store._adaptive_poll_interval <= self.store._max_poll_interval
        
        # Test min bound
        self.store._update_adaptive_poll_interval(ws_healthy=False, market_activity=0.9)
        assert self.store._adaptive_poll_interval >= self.store._min_poll_interval

    def test_get_adaptive_poll_interval(self):
        """Current adaptive poll interval is returned."""
        interval = self.store._get_adaptive_poll_interval()
        assert interval == self.store._adaptive_poll_interval


# ── REST Reconciliation ─────────────────────────────────────────────────────


class TestRESTReconciliation:
    def setup_method(self):
        logging.getLogger("merid.event_venues.kalshi.market_state").setLevel(logging.WARNING)
        self.store = KalshiMarketStateStore()

    def test_reconcile_returns_none_without_state(self):
        """Reconciliation returns None when no state exists."""
        result = self.store._reconcile_with_rest("KXBTC15M-T", {})
        assert result is None

    def test_reconcile_returns_none_without_book(self):
        """Reconciliation returns None when book not initialized."""
        # Create state without book
        state = self.store._get_or_create("KXBTC15M-T")
        result = self.store._reconcile_with_rest("KXBTC15M-T", {})
        assert result is None

    def test_reconcile_returns_none_without_rest_data(self):
        """Reconciliation returns None when REST data missing."""
        # Create state with book
        msg = _snapshot_msg("KXBTC15M-T", [[0.60, 5]], [[0.40, 8]])
        self.store.apply_orderbook_message(msg)
        
        result = self.store._reconcile_with_rest("KXBTC15M-T", {})
        assert result is None

    def test_reconcile_validated(self):
        """Reconciliation validates when WS and REST agree."""
        # Create state with book
        msg = _snapshot_msg("KXBTC15M-T", [[0.60, 5]], [[0.40, 8]])
        self.store.apply_orderbook_message(msg)
        
        # REST data with matching prices
        rest_data = {
            "best_bid": 60,
            "best_ask": 60,  # 100 - 40 = 60
            "updated_time": _iso(0)
        }
        
        result = self.store._reconcile_with_rest("KXBTC15M-T", rest_data)
        assert result == "validated"

    def test_reconcile_ws_lag(self):
        """Reconciliation detects WS lag when REST leads."""
        # Create state with book
        msg = _snapshot_msg("KXBTC15M-T", [[0.60, 5]], [[0.40, 8]])
        self.store.apply_orderbook_message(msg)
        
        # REST data with newer timestamp
        rest_data = {
            "best_bid": 60,
            "best_ask": 60,
            "updated_time": _iso(10)  # 10 seconds in future
        }
        
        result = self.store._reconcile_with_rest("KXBTC15M-T", rest_data)
        assert result == "ws_lag"

    def test_reconcile_rest_lag(self):
        """Reconciliation detects expected REST lag when WS leads."""
        # Create state with book
        msg = _snapshot_msg("KXBTC15M-T", [[0.60, 5]], [[0.40, 8]])
        self.store.apply_orderbook_message(msg)
        
        # REST data with older timestamp
        rest_data = {
            "best_bid": 60,
            "best_ask": 60,
            "updated_time": _iso(-10)  # 10 seconds ago
        }
        
        result = self.store._reconcile_with_rest("KXBTC15M-T", rest_data)
        assert result == "rest_lag"

    def test_reconcile_price_divergence(self):
        """Reconciliation detects price divergence."""
        # Create state with book
        msg = _snapshot_msg("KXBTC15M-T", [[0.60, 5]], [[0.40, 8]])
        self.store.apply_orderbook_message(msg)
        
        # REST data with different prices
        rest_data = {
            "best_bid": 55,  # Different from WS bid of 60
            "best_ask": 65,
            "updated_time": _iso(0)
        }
        
        result = self.store._reconcile_with_rest("KXBTC15M-T", rest_data)
        assert result == "price_divergence"
