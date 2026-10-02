"""Tests for the 2026-10-02 book-state layer:

- derived per-ticker book state (HEALTHY/RESYNCING/DEGRADED_REST_ONLY/UNTRADEABLE)
- one BOOK_STATE_TRANSITION event per change
- deduplicated resync coordinator (one in-flight recovery per ticker)
- router cached-REST revalidation fallback (_rest_cache_book_from_store)
"""

import asyncio
import logging
import time
from unittest.mock import MagicMock, patch

import pytest

from merid.event_venues.kalshi.market_state import KalshiMarketStateStore
from merid.event_venues.kalshi.models import KalshiMarketState
from merid.event_venues.kalshi.order_router import _rest_cache_book_from_store


@pytest.fixture
def store():
    s = KalshiMarketStateStore()
    s._delta_queues = {}
    s._main_event_loop = None
    return s


def _mk_state(ticker: str, **kw) -> KalshiMarketState:
    st = KalshiMarketState(ticker=ticker)
    for k, v in kw.items():
        setattr(st, k, v)
    return st


class TestDerivedBookState:
    def test_uninitialized_when_no_state(self, store):
        assert store.book_state("KXBTCD-TEST") == "UNINITIALIZED"

    def test_healthy_when_ws_owned_executable(self, store):
        st = _mk_state(
            "T",
            quote_owner="WS_FRESH_VERIFIED",
            executable=True,
            data_quality="GOOD",
            transition="VALID",
            book_health="LIVE",
            book_initialized=True,
        )
        assert store._derive_book_state(st) == "HEALTHY"

    def test_degraded_rest_only_when_rest_owned_executable(self, store):
        st = _mk_state(
            "T",
            quote_owner="REST_VERIFIED_DEGRADED",
            executable=True,
            data_quality="SUSPECT",
            transition="VALID",
            book_health="RECOVERED",
            book_initialized=True,
        )
        assert store._derive_book_state(st) == "DEGRADED_REST_ONLY"

    def test_resyncing_when_invalid_with_recovery_source(self, store):
        st = _mk_state(
            "T",
            quote_owner="NONE_UNTRUSTED",
            executable=False,
            data_quality="INVALID",
            transition="RESYNC_REQUIRED",
            book_health="INVALID",
            recovery_required_source="FULL_SNAPSHOT",
            book_initialized=True,
        )
        assert store._derive_book_state(st) == "RESYNCING"

    def test_untradeable_when_invalid_no_recovery(self, store):
        st = _mk_state(
            "T",
            quote_owner="NONE_UNTRUSTED",
            executable=False,
            data_quality="INVALID",
            transition="RESYNC_REQUIRED",
            book_health="INVALID",
            recovery_required_source="",
            book_initialized=True,
        )
        assert store._derive_book_state(st) == "UNTRADEABLE"

    def test_untradeable_on_circuit_breaker(self, store):
        st = _mk_state(
            "T",
            quote_owner="WS_FRESH_VERIFIED",
            executable=False,
            data_quality="SUSPECT",
            transition="CIRCUIT_BREAKER",
            book_health="LIVE",
            book_initialized=True,
        )
        assert store._derive_book_state(st) == "UNTRADEABLE"


class TestBookStateTransitionEvents:
    def test_one_event_per_change(self, store, caplog):
        st = _mk_state(
            "KXBTCD-T",
            quote_owner="WS_FRESH_VERIFIED",
            executable=True,
            data_quality="GOOD",
            transition="VALID",
            book_health="LIVE",
            book_initialized=True,
        )
        store._states["KXBTCD-T"] = st
        with caplog.at_level(logging.INFO):
            store._note_book_state("KXBTCD-T", st, "ws_apply")
            store._note_book_state("KXBTCD-T", st, "ws_apply")  # no change -> no event
            st.data_quality = "INVALID"
            st.transition = "RESYNC_REQUIRED"
            st.quote_owner = "NONE_UNTRUSTED"
            st.executable = False
            st.recovery_required_source = "FULL_SNAPSHOT"
            store._note_book_state("KXBTCD-T", st, "seq_gap")
        events = [r for r in caplog.records if "BOOK-STATE-TRANSITION" in r.getMessage()]
        assert len(events) == 2
        assert "next_state" in events[0].getMessage()
        assert store._book_state_transition_total["KXBTCD-T"] == 2


class TestResyncDedup:
    def test_inflight_blocks_second_trigger(self, store):
        store._recovery_inflight_since["T"] = time.monotonic()
        assert store._maybe_trigger_book_recovery("T", "seq_gap") is False

    def test_stuck_slot_released(self, store):
        import merid.event_venues.kalshi.market_state as ms
        store._recovery_inflight_since["T"] = (
            time.monotonic() - ms._RECOVERY_INFLIGHT_STUCK_S - 1.0
        )
        # Time-throttle alone still blocks a brand-new retrigger...
        store._last_recovery_trigger_ts["T"] = time.monotonic()
        assert store._maybe_trigger_book_recovery("T", "retry") is False
        # ...but once both bounds pass, a new flight is allowed.
        store._last_recovery_trigger_ts["T"] = 0.0
        fake_loop = MagicMock()
        fake_loop.is_running.return_value = True
        fake_loop.is_closed.return_value = False
        store._main_event_loop = fake_loop
        fut = MagicMock()
        with patch("asyncio.run_coroutine_threadsafe", return_value=fut):
            assert store._maybe_trigger_book_recovery("T", "retry") is True
        assert "T" in store._recovery_inflight_since
        # Both task callbacks registered; completing both clears the slot.
        cb = fut.add_done_callback.call_args_list[0][0][0]
        cb(MagicMock())
        cb(MagicMock())
        assert "T" not in store._recovery_inflight_since

    def test_no_loop_returns_false(self, store):
        store._main_event_loop = None
        assert store._maybe_trigger_book_recovery("T", "gap") is False


class TestRestCacheFallback:
    def _patch_store(self, st):
        mock_store = MagicMock()
        mock_store.get.return_value = st
        return patch(
            "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
            return_value=mock_store,
        )

    def test_fresh_cached_rest_returns_book(self):
        st = _mk_state(
            "KXBTCD-T",
            last_rest_bid_cents=40,
            last_rest_ask_cents=45,
            last_rest_quote_update_ts=time.monotonic(),
        )
        with self._patch_store(st):
            book = _rest_cache_book_from_store("KXBTCD-T")
        assert book is not None
        assert book["yes_bid_cents"] == 40
        assert book["yes_ask_cents"] == 45
        assert book["no_ask_cents"] == 60  # 100 - bid
        assert book["no_bid_cents"] == 55  # 100 - ask
        assert book["source"] == "rest_store_cache"

    def test_stale_cached_rest_rejected(self):
        st = _mk_state(
            "KXBTCD-T",
            last_rest_bid_cents=40,
            last_rest_ask_cents=45,
            last_rest_quote_update_ts=time.monotonic() - 60.0,
        )
        with self._patch_store(st):
            assert _rest_cache_book_from_store("KXBTCD-T") is None

    def test_crossed_or_missing_rest_rejected(self):
        st = _mk_state(
            "KXBTCD-T",
            last_rest_bid_cents=50,
            last_rest_ask_cents=45,
            last_rest_quote_update_ts=time.monotonic(),
        )
        with self._patch_store(st):
            assert _rest_cache_book_from_store("KXBTCD-T") is None
        st2 = _mk_state("KXBTCD-T", last_rest_quote_update_ts=time.monotonic())
        with self._patch_store(st2):
            assert _rest_cache_book_from_store("KXBTCD-T") is None

    def test_no_state_returns_none(self):
        with self._patch_store(None):
            assert _rest_cache_book_from_store("KXBTCD-T") is None
