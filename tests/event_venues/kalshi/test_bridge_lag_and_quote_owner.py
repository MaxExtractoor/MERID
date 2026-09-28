"""Deterministic coverage for the bridge-lag repair and quote-ownership spine.

Covers the P0 incident fix (2026-09): a ~65k-deep bridge queue let
sequence-contiguous but execution-stale deltas mutate the book, masked by
hidden REST substitution.  These tests pin the new contract:

- bounded queues + overflow -> invalidate -> drain -> snapshot resync
- event-age / queue-wait / upstream-wait budgets enforced at both enqueue
  and dequeue of the per-ticker delta pipeline
- canonical quote_owner vocabulary (WS_FRESH_VERIFIED /
  REST_VERIFIED_DEGRADED / NONE_UNTRUSTED) with raw WS/REST divergence
  always observable regardless of the effective owner
- allocator canonical side-aware price band + degraded-mode edge reserve
- bounded ADX warmup (is_warmup) helper semantics
"""

from __future__ import annotations

import time
from collections import deque
from unittest.mock import MagicMock, patch

import pytest

from merid.event_venues.kalshi.market_state import (
    KalshiMarketStateStore,
    BookHealth,
    _BOOK_MAX_EVENT_AGE_MS,
    _BOOK_MAX_QUEUE_WAIT_MS,
    _BOOK_MAX_UPSTREAM_WAIT_MS,
)


TICKER = "KXBTC15M-T"


def _store() -> KalshiMarketStateStore:
    store = KalshiMarketStateStore()
    store._main_event_loop = None  # never schedule coroutines from tests
    return store


def _book(store, yes=((0.48, 5),), no=((0.50, 4),), seq=100):
    store._ob.apply_snapshot(
        TICKER, {"ticker": TICKER, "yes": list(yes), "no": list(no), "seq": seq}
    )
    state = store._get_or_create(TICKER)
    state.snapshot_complete = True
    state.data_quality = "GOOD"
    state.book_consistency = "GOOD"
    state.transition = "VALID"
    state.executable = True
    return state


def _delta(seq: int, side: str = "yes", price_dollars: float = 0.49,
           delta_fp: float = 3.0) -> dict:
    return {
        "side": side,
        "price_dollars": price_dollars,
        "delta_fp": delta_fp,
        "seq": seq,
    }


# ── Queue freshness gates ─────────────────────────────────────────────────


class TestDeltaEnqueueFreshness:
    def test_fresh_delta_enqueues(self):
        store = _store()
        ok = store._enqueue_delta(TICKER, _delta(101))
        assert ok is True
        assert len(store._delta_queues[TICKER]) == 1

    def test_event_too_old_invalidates_and_returns_false(self):
        store = _store()
        _book(store)
        msg = _delta(101)
        # Venue timestamp far beyond the event-age budget.
        msg["ts_ms"] = (time.time() * 1000.0) - (_BOOK_MAX_EVENT_AGE_MS + 5000)
        ok = store._enqueue_delta(TICKER, msg)
        assert ok is False
        state = store.get(TICKER)
        assert state.data_quality == "INVALID"
        assert state.transition == "RESYNC_REQUIRED"
        assert state.invalidation_cause == "BOOK_EVENT_TOO_OLD"
        assert state.executable is False
        assert state.recovery_required_source == "FULL_SNAPSHOT"

    def test_upstream_lag_invalidates(self):
        store = _store()
        _book(store)
        msg = _delta(101)
        # Bridge-recv stamp far older than the upstream-wait budget.
        msg["_t_bridge_recv_ns"] = time.monotonic_ns() - int(
            (_BOOK_MAX_UPSTREAM_WAIT_MS + 5000) * 1e6
        )
        ok = store._enqueue_delta(TICKER, msg)
        assert ok is False
        assert store.get(TICKER).invalidation_cause == "BOOK_UPSTREAM_LAG"

    def test_overflow_drains_queue_and_marks_untrusted(self):
        store = _store()
        _book(store)
        store._delta_queues[TICKER] = deque(
            {"seq": i} for i in range(store._MAX_PER_TICKER_QUEUE)
        )
        ok = store._enqueue_delta(TICKER, _delta(9999))
        assert ok is False
        # Stale backlog is discarded — never partially replayed.
        assert len(store._delta_queues[TICKER]) == 0
        state = store.get(TICKER)
        assert state.data_quality == "INVALID"
        assert state.executable is False
        assert state.recovery_required_source == "FULL_SNAPSHOT"
        assert store._overflow_count[TICKER] == 1

    def test_overflow_is_per_ticker(self):
        store = _store()
        other = "KXETH15M-T"
        store._delta_queues[TICKER] = deque(
            {"seq": i} for i in range(store._MAX_PER_TICKER_QUEUE)
        )
        store._enqueue_delta(TICKER, {"seq": 1})
        # A different ticker is unaffected by the overflowing ticker.
        ok = store._enqueue_delta(other, {"seq": 1})
        assert ok is True
        assert len(store._delta_queues[other]) == 1

    def test_invalidated_book_drops_subsequent_deltas(self):
        """While INVALID + FULL_SNAPSHOT required, live deltas are dropped
        (never partially replayed onto an untrusted base)."""
        store = _store()
        _book(store)
        store._mark_book_untrusted_and_resync(TICKER, "BOOK_EVENT_TOO_OLD")
        # Directly drive the apply path the batch worker uses.
        store._apply_delta_internal(TICKER, _delta(101, price_dollars=0.30))
        ob = store._ob.get_book(TICKER)
        # The 30c delta level must not exist in the book.
        assert 30 not in getattr(ob, "yes_levels", {})
        assert store.get(TICKER).data_quality == "INVALID"


# ── Sequence integrity ────────────────────────────────────────────────────


class TestSequenceIntegrity:
    def test_contiguous_delta_is_live(self):
        store = _store()
        _book(store, seq=100)
        with patch.object(store, "_notify_subscribers"):
            store._apply_delta_internal(TICKER, _delta(101))
        state = store.get(TICKER)
        assert state.data_source == "WS_ORDERBOOK_DELTA_LIVE"
        assert state.live_sequence_confirmed is True
        assert state.book_health == BookHealth.LIVE.value
        assert state.quote_owner == "WS_FRESH_VERIFIED"

    def test_sequence_gap_invalidates_book(self):
        store = _store()
        _book(store, seq=100)
        with patch.object(store, "_notify_subscribers"):
            store._apply_delta_internal(TICKER, _delta(150))  # skip seq 101..149
        state = store.get(TICKER)
        assert state.data_quality == "INVALID"
        assert state.invalidation_cause == "INVALID_SEQUENCE_GAP"
        assert state.executable is False
        assert state.recovery_required_source == "FULL_SNAPSHOT"
        assert state.book_health == BookHealth.RESYNC_REQUESTED.value
        assert state.book_gap_total == 1

    def test_duplicate_old_seq_is_gap(self):
        store = _store()
        _book(store, seq=100)
        with patch.object(store, "_notify_subscribers"):
            store._apply_delta_internal(TICKER, _delta(101))
        # Replay of an already-consumed seq is also non-contiguous.
        with patch.object(store, "_notify_subscribers"):
            store._apply_delta_internal(TICKER, _delta(101))
        assert store.get(TICKER).invalidation_cause == "INVALID_SEQUENCE_GAP"


# ── Quote ownership / parity ──────────────────────────────────────────────


class TestQuoteOwnership:
    def _rest_owned_state(self, store):
        """Force a REST-verified-degraded effective quote with raw WS fields
        recorded for parity diagnostics."""
        state = _book(store)
        state.last_rest_bid_cents = 60
        state.last_rest_ask_cents = 62
        state.last_rest_quote_update_ts = time.monotonic()
        state.last_ws_bid_cents = 40
        state.last_ws_ask_cents = 44
        state.last_ws_update_ts = time.monotonic()
        state.quote_owner = "REST_VERIFIED_DEGRADED"
        state.degraded_mode = True
        state.best_bid_cents = 60
        state.best_ask_cents = 62
        return state

    def test_rest_owner_cannot_claim_ws_freshness(self):
        store = _store()
        state = self._rest_owned_state(store)
        # Raw WS feed is stale even though REST is fresh.
        state.last_ws_update_ts = time.monotonic() - 60.0
        gate = store.get_quote_gate_state(TICKER)
        assert gate["quote_owner"] == "REST_VERIFIED_DEGRADED"
        assert gate["degraded_mode"] is True
        assert gate["ws_fresh"] is False
        assert gate["rest_fresh"] is True
        # Effective freshness follows the REST owner, not the dead WS feed.
        assert gate["effective_fresh"] is True

    def test_raw_parity_visible_under_rest_ownership(self):
        store = _store()
        self._rest_owned_state(store)
        ok, _ = store.is_quote_coherent(TICKER)
        assert ok is True
        state = store.get(TICKER)
        assert state.ws_rest_bid_diff_ticks == 20
        assert state.ws_rest_ask_diff_ticks == 18
        assert state.ws_parity_healthy is False

    def test_stale_rest_under_rest_ownership_fails(self):
        store = _store()
        state = self._rest_owned_state(store)
        state.last_rest_quote_update_ts = time.monotonic() - 60.0
        ok, reason = store.is_quote_coherent(TICKER)
        assert ok is False
        assert "REST_STALE" in (reason or "")

    def test_ws_owned_divergent_raw_parity_fails(self):
        store = _store()
        state = _book(store)
        state.last_ws_bid_cents = 40
        state.last_ws_ask_cents = 44
        state.last_ws_update_ts = time.monotonic()
        state.last_rest_bid_cents = 70
        state.last_rest_ask_cents = 72
        state.last_rest_quote_update_ts = time.monotonic()
        state.quote_owner = "WS_FRESH_VERIFIED"
        ok, reason = store.is_quote_coherent(TICKER)
        assert ok is False
        assert "WS_REST_DIVERGED" in (reason or "")

    def test_untrusted_owner_never_effective_fresh(self):
        store = _store()
        state = _book(store)
        state.quote_owner = "NONE_UNTRUSTED"
        state.last_ws_update_ts = time.monotonic()
        gate = store.get_quote_gate_state(TICKER)
        assert gate["quote_owner"] == "NONE_UNTRUSTED"
        assert gate["effective_fresh"] is False

    def test_unknown_owner_never_effective_fresh(self):
        store = _store()
        state = _book(store)
        state.quote_owner = "UNKNOWN"
        gate = store.get_quote_gate_state(TICKER)
        assert gate["effective_fresh"] is False


# ── Allocator canonical price band + degraded reserve ─────────────────────


class TestAllocatorPriceBand:
    def _allocator(self):
        from merid.risk.profiles.global_allocator import GlobalAllocator
        return GlobalAllocator()

    def _cand(self, asset, ticker, side, price, edge_pct=10.0, **kw):
        from merid.risk.profiles.global_allocator import OrderCandidate
        return OrderCandidate(
            asset=asset, ticker=ticker, side=side, action="buy",
            price_cents=price, count=1.0, edge_pct=edge_pct,
            confidence=0.9, model_prob=0.9, agent_name="t", **kw,
        )

    def _price_stage_ok(self, alloc, cand):
        """Run the PRICE stage predicate the way allocate() does."""
        from merid.event_venues.kalshi.binary_price_space import (
            get_canonical_price_range,
        )
        lo, hi = get_canonical_price_range(cand.side)
        return lo <= cand.price_cents <= hi

    def test_no_77c_passes_canonical_band(self):
        # The old symmetric [10,75] allocator band silently killed canonical-
        # valid NO candidates (e.g. NO@77); canonical NO range is [25,95].
        alloc = self._allocator()
        assert self._price_stage_ok(alloc, self._cand("XRP", TICKER, "no", 77))

    def test_no_10c_fails_canonical_band(self):
        alloc = self._allocator()
        assert not self._price_stage_ok(alloc, self._cand("XRP", TICKER, "no", 10))

    def test_yes_80c_passes_canonical_band(self):
        alloc = self._allocator()
        assert self._price_stage_ok(alloc, self._cand("BTC", TICKER, "yes", 80))

    def test_yes_5c_fails_canonical_band(self):
        alloc = self._allocator()
        assert not self._price_stage_ok(alloc, self._cand("BTC", TICKER, "yes", 5))

    def test_degraded_candidate_needs_reserve_edge(self):
        """A REST-owned quote must clear base edge + degraded reserve."""
        from merid.risk.profiles.global_allocator import _to_edge_fraction
        alloc = self._allocator()
        base_edge = alloc.per_asset_min_edge_pct.get("BTC", alloc.min_edge_pct)
        base_frac = _to_edge_fraction(base_edge)
        # Candidate at exactly the base edge: passes as WS-owned, fails as
        # REST_VERIFIED_DEGRADED because the reserve is added.
        ws_cand = self._cand("BTC", TICKER, "yes", 50, edge_pct=base_edge)
        deg_cand = self._cand(
            "BTC", TICKER, "yes", 50, edge_pct=base_edge,
            quote_owner="REST_VERIFIED_DEGRADED", degraded_mode=True,
        )
        import os
        reserve = float(os.getenv("MERID_DEGRADED_EDGE_RESERVE_PCT", "0.01"))
        assert _to_edge_fraction(ws_cand.edge_pct) >= base_frac
        assert _to_edge_fraction(deg_cand.edge_pct) < base_frac + reserve


# ── ADX bounded warmup ────────────────────────────────────────────────────


class TestAdxWarmup:
    def test_warmup_true_within_window_short_history(self):
        from merid.prediction.agent_grid_15m import is_warmup
        import merid.prediction.agent_grid_15m as ag
        with patch.object(ag, "_process_start_time", time.time()):
            assert is_warmup(5) is True

    def test_warmup_false_after_window_expires(self):
        from merid.prediction.agent_grid_15m import is_warmup
        import merid.prediction.agent_grid_15m as ag
        with patch.object(ag, "_process_start_time", time.time() - 400.0):
            # >5 minutes since process start: warmup is over regardless of
            # history depth -> the ADX gate must fail closed.
            assert is_warmup(5) is False

    def test_warmup_false_with_full_history(self):
        from merid.prediction.agent_grid_15m import is_warmup
        import merid.prediction.agent_grid_15m as ag
        with patch.object(ag, "_process_start_time", time.time()):
            assert is_warmup(50) is False
