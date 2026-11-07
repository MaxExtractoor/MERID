"""Tests for trade-snapshot veto latency attribution (2026-11-03).

``validate_trade_snapshot`` reports WHICH freshness bound tripped;
``_snapshot_reject_diag`` must attribute the age to a pipeline stage so an
``ORDERBOOK_STALE:7014ms,RTI_BOOK_TIME_SKEW`` veto identifies where the
seconds went (upstream/wire lag vs consumer stall vs quiet ticker vs
as-of misalignment).  The sid arrival stamp backing the
"quiet ticker vs stalled feed" discriminator is covered too.
"""

import logging
import time
from types import SimpleNamespace

import pytest

from merid.event_venues.kalshi.market_state import KalshiMarketStateStore
from merid.prediction import agent_grid_15m as ag


TICKER = "KXBTC15M-DIAG"


def _fake_state(*, book_wall_age_s=7.0, apply_age_s=0.2, event_age_ms=6800.0):
    return SimpleNamespace(
        ticker=TICKER,
        last_book_update_wall_ts=time.time() - book_wall_age_s,
        last_book_update_ts=time.monotonic() - book_wall_age_s,
        ws_last_apply_mono_ns=time.monotonic_ns() - int(apply_age_s * 1e9),
        ws_last_event_age_ms=event_age_ms,
        ws_last_event_age_src="venue_ts_corrected",
        ws_last_event_age_status="measured",
        ws_last_queue_wait_ms=12.5,
        ws_queue_depth=0,
        ws_last_seq=42,
        book_initialized=True,
        live_sequence_confirmed=True,
        snapshot_complete=True,
        executable=True,
        data_quality="GOOD",
        transition="VALID",
        book_health="LIVE",
        data_source="WS_ORDERBOOK_DELTA_LIVE",
        quote_owner="WS_FRESH_VERIFIED",
        invalidation_cause="",
        recovery_required_source="",
        book_gap_total=0,
        book_resync_total=1,
        last_rest_quote_update_ts=0.0,
    )


def _fake_obs(*, recv_age_ms=500.0, source_age_ms=700.0):
    now_ms = time.time() * 1000.0
    observed = int(now_ms - recv_age_ms)
    return SimpleNamespace(
        asset="BTC",
        value=65000.0,
        observed_ts_ms=observed,
        observed_ts_mono_ns=time.monotonic_ns() - int(recv_age_ms * 1e6),
        source_ts_ms=int(now_ms - source_age_ms),
        age_ms=source_age_ms - recv_age_ms,
        event_loop_lag_ms=3,
        sequence=1234,
        timestamp_quality="source",
        execution_eligible=True,
    )


class TestSidFrameAge:
    def test_unknown_ticker_returns_none(self):
        store = KalshiMarketStateStore()
        assert store.sid_frame_age_ms(TICKER) is None

    def test_fresh_after_sequenced_frame(self):
        store = KalshiMarketStateStore()
        store._check_sid_delta_sequence(4, 100, TICKER)
        age = store.sid_frame_age_ms(TICKER)
        assert age is not None
        assert age < 500.0

    def test_follows_ticker_sid_mapping(self):
        store = KalshiMarketStateStore()
        store._check_sid_delta_sequence(7, 10, "KXETH15M-OTHER")
        # TICKER has never arrived -> no sid mapping -> None
        assert store.sid_frame_age_ms(TICKER) is None
        assert store.sid_frame_age_ms("KXETH15M-OTHER") is not None

    def test_cleared_on_invalidate_all(self):
        store = KalshiMarketStateStore()
        store._check_sid_delta_sequence(4, 100, TICKER)
        store.invalidate_all_live_sequence()
        assert store.sid_frame_age_ms(TICKER) is None


class TestSnapshotRejectDiag:
    def _diag(self, store, state, obs, failures, **kw):
        return ag._snapshot_reject_diag(
            store, "BTC", TICKER, state, obs, list(failures), **kw
        )

    def test_upstream_lag_attribution(self):
        """Applied promptly but venue event was already old -> upstream."""
        store = KalshiMarketStateStore()
        state = _fake_state(book_wall_age_s=7.0, apply_age_s=0.2,
                            event_age_ms=6800.0)
        diag = self._diag(store, state, _fake_obs(),
                          ["ORDERBOOK_STALE:7014ms"])
        assert diag["attribution"].startswith("upstream_lag")
        assert diag["book"]["apply_age_ms"] < 1000
        assert diag["book"]["event_age_ms"] == 6800.0
        assert diag["quote_age_ms"] >= 6000

    def test_ticker_quiet_when_sid_alive(self):
        """Old book + old apply + live sid -> quiet ticker, not dead feed."""
        store = KalshiMarketStateStore()
        store._check_sid_delta_sequence(4, 100, TICKER)
        state = _fake_state(book_wall_age_s=7.0, apply_age_s=7.0,
                            event_age_ms=400.0)
        diag = self._diag(store, state, _fake_obs(),
                          ["ORDERBOOK_STALE:7014ms"])
        assert diag["attribution"].startswith("ticker_quiet_or_selective")
        assert diag["book"]["sid"] == 4
        assert diag["book"]["sid_frame_age_ms"] <= 500.0

    def test_subscription_stalled_when_sid_silent(self):
        store = KalshiMarketStateStore()
        store._check_sid_delta_sequence(4, 100, TICKER)
        store._sid_last_frame_mono_ns[4] = time.monotonic_ns() - int(8e9)
        state = _fake_state(book_wall_age_s=7.0, apply_age_s=7.0,
                            event_age_ms=400.0)
        diag = self._diag(store, state, _fake_obs(),
                          ["ORDERBOOK_STALE:7014ms"])
        assert diag["attribution"].startswith("subscription_stalled")
        assert diag["book"]["sid_frame_age_ms"] >= 7000

    def test_consumer_backlog_when_deltas_pending(self):
        from collections import deque

        store = KalshiMarketStateStore()
        store._delta_queues[TICKER] = deque([{"seq": 1}])
        state = _fake_state(book_wall_age_s=7.0, apply_age_s=7.0,
                            event_age_ms=400.0)
        diag = self._diag(store, state, _fake_obs(),
                          ["ORDERBOOK_STALE:7014ms"])
        assert diag["attribution"].startswith("consumer_backlog")
        assert diag["book"]["pending_deltas"] == 1

    def test_skew_only_attribution(self):
        """Fresh book, old RTI receipt -> as-of misalignment, not book lag."""
        store = KalshiMarketStateStore()
        state = _fake_state(book_wall_age_s=0.2, apply_age_s=0.2,
                            event_age_ms=150.0)
        obs = _fake_obs(recv_age_ms=2000.0)
        diag = self._diag(store, state, obs,
                          ["RTI_BOOK_TIME_SKEW:1800ms"])
        assert diag["attribution"] == "rti_book_as_of_misaligned"
        assert diag["skew_ms"] >= 1500
        assert diag["rti"]["source_age_ms"] is not None

    def test_eval_age_and_fields_present(self):
        store = KalshiMarketStateStore()
        state = _fake_state()
        t0 = time.monotonic_ns() - int(50e6)
        diag = self._diag(store, state, _fake_obs(),
                          ["ORDERBOOK_STALE:7014ms"],
                          eval_t0_mono_ns=t0, run_id="test-run")
        assert diag["eval_ms"] >= 50.0
        assert diag["run_id"] == "test-run"
        assert diag["book"]["seq"] == 42
        assert diag["rti"]["sequence"] == 1234
        assert "budgets_ms" in diag

    def test_missing_store_and_obs_is_safe(self):
        diag = ag._snapshot_reject_diag(
            None, "BTC", TICKER, None, None, ["MARKET_STATE_MISSING"],
        )
        assert diag["attribution"] is not None
        assert diag["quote_age_ms"] is None
        assert diag["rti"]["recv_age_ms"] is None


class TestEmitBounded:
    def test_emits_once_per_interval_and_counts_suppressed(
        self, caplog, monkeypatch
    ):
        monkeypatch.setattr(
            ag, "_SNAPSHOT_REJECT_DIAG_MIN_INTERVAL_S", 60.0
        )
        ag._snapshot_reject_diag_last_ts.clear()
        ag._snapshot_reject_diag_suppressed.clear()
        diag = {"kind": "trade_snapshot_reject_diag", "ticker": TICKER}
        with caplog.at_level(logging.WARNING,
                             logger="merid.prediction.agent_grid_15m"):
            ag._emit_snapshot_reject_diag(TICKER, dict(diag))
            ag._emit_snapshot_reject_diag(TICKER, dict(diag))
            ag._emit_snapshot_reject_diag(TICKER, dict(diag))
        lines = [
            r for r in caplog.records
            if "TRADE-SNAPSHOT-REJECT-DIAG" in r.getMessage()
        ]
        assert len(lines) == 1
        assert ag._snapshot_reject_diag_suppressed[TICKER] == 2

    def test_suppressed_count_included_on_next_emit(
        self, caplog, monkeypatch
    ):
        monkeypatch.setattr(
            ag, "_SNAPSHOT_REJECT_DIAG_MIN_INTERVAL_S", 0.0
        )
        ag._snapshot_reject_diag_last_ts.clear()
        ag._snapshot_reject_diag_suppressed.clear()
        ag._snapshot_reject_diag_suppressed[TICKER] = 3
        with caplog.at_level(logging.WARNING,
                             logger="merid.prediction.agent_grid_15m"):
            ag._emit_snapshot_reject_diag(TICKER, {"ticker": TICKER})
        lines = [
            r.getMessage() for r in caplog.records
            if "TRADE-SNAPSHOT-REJECT-DIAG" in r.getMessage()
        ]
        assert len(lines) == 1
        assert '"suppressed": 3' in lines[0]
