"""Market-state recovery state-machine tests.

These tests verify that the market-state store transitions through
healthy, suspect, and invalid states deterministically and that a clean
snapshot (or contiguous delta sequence) restores executable state.
"""

import pytest
import time

from merid.event_venues.kalshi.market_state import KalshiMarketStateStore


@pytest.fixture
def store(tmp_path):
    """Create an isolated KalshiMarketStateStore and stop its batch worker."""
    s = KalshiMarketStateStore()
    try:
        yield s
    finally:
        s._stop_batch_worker()
        if s._batch_worker_thread and s._batch_worker_thread.is_alive():
            s._batch_worker_thread.join(timeout=1.0)


def _snapshot(ticker, yes_levels, no_levels):
    """Build a flat orderbook_snapshot message."""
    return {
        "type": "orderbook_snapshot",
        "market_ticker": ticker,
        "yes": [[float(p), int(sz)] for p, sz in yes_levels],
        "no": [[float(p), int(sz)] for p, sz in no_levels],
    }


def test_healthy_snapshot_is_executable(store):
    """A non-crossed, dual YES/NO snapshot produces an executable market."""
    ticker = "KXBTC15M-TEST-001"
    msg = _snapshot(ticker, yes_levels=[(0.40, 10), (0.35, 5)], no_levels=[(0.59, 10), (0.55, 5)])

    state = store.apply_orderbook_message(msg, via="test")

    assert state is not None
    assert state.ticker == ticker
    assert state.book_initialized is True
    assert state.data_quality == "GOOD"
    assert state.executable is True
    assert state.transition == "VALID"
    assert state.best_bid_cents == 40
    assert state.best_ask_cents == 41


def test_duality_violation_blocks_then_clean_snapshot_recovers(store):
    """A YES+NO duality gap marks the book SUSPECT; a subsequent clean snapshot restores it."""
    ticker = "KXBTC15M-TEST-002"

    # Gap of 90c (5 + 5 = 10) exceeds the configured duality tolerance (80c).
    bad = _snapshot(ticker, yes_levels=[(0.05, 10)], no_levels=[(0.05, 10)])
    state = store.apply_orderbook_message(bad, via="test")

    assert state is not None
    assert state.executable is False
    assert state.data_quality in ("SUSPECT", "INVALID")
    assert state.transition == "RESYNC_REQUIRED"

    # Clean snapshot restores executable state.
    good = _snapshot(ticker, yes_levels=[(0.40, 10), (0.35, 5)], no_levels=[(0.59, 10), (0.55, 5)])
    state = store.apply_orderbook_message(good, via="test")

    assert state is not None
    assert state.book_initialized is True
    assert state.data_quality == "GOOD"
    assert state.executable is True
    assert state.transition == "VALID"


def test_crossed_book_blocks_and_clean_snapshot_recovers(store):
    """A crossed/locked book is SUSPECT (INVALID only after quarantine); a clean snapshot restores executable state."""
    ticker = "KXBTC15M-TEST-003"

    # Crossed: YES bid 60 >= YES ask 50 (from NO bid 50)
    crossed = _snapshot(ticker, yes_levels=[(0.60, 10)], no_levels=[(0.50, 10)])
    state = store.apply_orderbook_message(crossed, via="test")

    assert state is not None
    assert state.executable is False
    assert state.data_quality in ("SUSPECT", "INVALID")
    assert state.book_consistency == "INVERTED"
    assert state.transition == "RESYNC_REQUIRED"

    # Clean snapshot resets the violation and restores executable state.
    good = _snapshot(ticker, yes_levels=[(0.40, 10)], no_levels=[(0.59, 10)])
    state = store.apply_orderbook_message(good, via="test")

    assert state is not None
    assert state.data_quality == "GOOD"
    assert state.executable is True
    assert state.transition == "VALID"
    assert state.book_consistency == "GOOD"


def test_empty_snapshot_initializes_but_not_executable(store):
    """A completely empty orderbook snapshot initializes the book so deltas can be applied,
    but it is marked SUSPECT and non-executable until live deltas populate it."""
    ticker = "KXBTC15M-TEST-004"
    empty = _snapshot(ticker, yes_levels=[], no_levels=[])

    state = store.apply_orderbook_message(empty, via="test")

    assert state is not None
    assert state.book_initialized is True
    assert state.executable is False
    assert state.data_quality in ("SUSPECT", "INVALID", "UNKNOWN")


# ── Quote-owner hysteresis (2026-10-04) ─────────────────────────────────
#
# The REST poller (~2s) and lagged WS deltas used to fight over quote_owner:
# every REST apply claimed REST_VERIFIED_DEGRADED unconditionally and every
# in-parity delta reclaimed WS_FRESH_VERIFIED, so the effective quote's owner
# — and the BBO itself — flipped several times a second whenever WS/REST
# divergence hovered near the parity threshold.  These tests pin the
# hysteresis contract: demote fast, promote slow.


def _seed_ws_verified(store, ticker):
    """Apply a WS snapshot (40/41) and mark the book fully WS-verified."""
    snap = _snapshot(ticker, yes_levels=[(0.40, 10)], no_levels=[(0.59, 10)])
    store.apply_orderbook_message(snap, via="bridge_queue")
    st = store._states[ticker]
    st.snapshot_complete = True
    st.live_sequence_confirmed = True
    st.data_quality = "GOOD"
    st.quote_owner = "WS_FRESH_VERIFIED"
    st.last_ws_update_ts = time.monotonic()
    return st


def _rest_poll(store, ticker, *, yes_bid, no_bid):
    """Apply a REST polling snapshot (yes_bid / ask = 100 - no_bid)."""
    msg = _snapshot(
        ticker, yes_levels=[(yes_bid, 10)], no_levels=[(no_bid, 10)]
    )
    return store.apply_orderbook_message(msg, via="rest_polling")


def _drive_ws_delta(store, ticker, *, side="yes", price_cents=40, size_delta=1):
    """Apply one WS orderbook delta synchronously (bypasses the async queue)."""
    msg = {
        "market_ticker": ticker,
        "side": side,
        "price": price_cents,
        "delta_fp": size_delta,
    }
    lock = store._get_ticker_lock(ticker)
    with lock:
        store._apply_delta_internal(ticker, msg)


def test_rest_poll_does_not_demote_verified_ws_book(store):
    """An in-parity REST poll refreshes markers but must not take the quote."""
    ticker = "KXBTC15M-TEST-H1"
    st = _seed_ws_verified(store, ticker)

    _rest_poll(store, ticker, yes_bid=0.40, no_bid=0.59)

    assert st.quote_owner == "WS_FRESH_VERIFIED"
    assert st.degraded_mode is False
    assert st.best_bid_cents == 40
    assert st.best_ask_cents == 41


def test_rest_poll_claims_quote_when_ws_divergent(store):
    """A fresh REST quote far from the WS book demotes to REST ownership."""
    ticker = "KXBTC15M-TEST-H2"
    st = _seed_ws_verified(store, ticker)

    # REST sees 60/61 while last_ws_* still says 40/41 -> 20c divergence.
    _rest_poll(store, ticker, yes_bid=0.60, no_bid=0.39)

    assert st.quote_owner == "REST_VERIFIED_DEGRADED"
    assert st.degraded_mode is True
    assert store.book_state(ticker) == "DEGRADED_REST_ONLY"


def test_rest_poll_claims_quote_when_ws_stale(store):
    """An in-parity REST poll still claims the quote when the WS book is stale."""
    ticker = "KXBTC15M-TEST-H3"
    st = _seed_ws_verified(store, ticker)
    st.last_ws_update_ts = time.monotonic() - 10.0  # beyond the 1.5s entry budget

    _rest_poll(store, ticker, yes_bid=0.40, no_bid=0.59)

    assert st.quote_owner == "REST_VERIFIED_DEGRADED"
    assert st.degraded_mode is True


def test_ws_deltas_require_parity_streak_to_reclaim_from_rest(store):
    """WS reclaims ownership only after MERID_WS_PROMOTE_STREAK in-parity deltas."""
    from merid.event_venues.kalshi import market_state as ms_mod

    ticker = "KXBTC15M-TEST-H4"
    st = _seed_ws_verified(store, ticker)

    # REST poll diverges -> REST owns the effective quote (60/61).
    _rest_poll(store, ticker, yes_bid=0.60, no_bid=0.39)
    assert st.quote_owner == "REST_VERIFIED_DEGRADED"

    # The shared book now holds REST's levels; deltas that keep the
    # delta-derived BBO in parity (60/61) build the promotion streak.
    needed = ms_mod._WS_PROMOTE_STREAK
    for i in range(needed - 1):
        _drive_ws_delta(store, ticker, side="yes", price_cents=60, size_delta=1)
        assert st.quote_owner == "REST_VERIFIED_DEGRADED", (
            f"WS reclaimed after only {i + 1} in-parity deltas"
        )
        assert st.degraded_mode is True
        assert st.best_bid_cents == 60
        assert st.best_ask_cents == 61

    _drive_ws_delta(store, ticker, side="yes", price_cents=60, size_delta=1)
    assert st.quote_owner == "WS_FRESH_VERIFIED"
    assert st.degraded_mode is False
    assert store.book_state(ticker) == "HEALTHY"


def test_divergent_delta_resets_promote_streak(store):
    """A divergent (but valid) delta mid-streak demotes immediately and resets the count."""
    from merid.event_venues.kalshi import market_state as ms_mod

    ticker = "KXBTC15M-TEST-H5"
    st = _seed_ws_verified(store, ticker)

    _rest_poll(store, ticker, yes_bid=0.60, no_bid=0.39)
    assert st.quote_owner == "REST_VERIFIED_DEGRADED"

    _drive_ws_delta(store, ticker, side="yes", price_cents=60, size_delta=1)
    _drive_ws_delta(store, ticker, side="yes", price_cents=60, size_delta=1)
    assert store._ws_promote_streak[ticker] == 2

    # Move the delta-derived book to a divergent-but-valid 50/51 market:
    # remove REST's 60 bid, add a 50 bid and a 49 NO bid (ask=51).  The book
    # stays two-sided and uncrossed; only the price diverges from REST 60/61.
    _drive_ws_delta(store, ticker, side="yes", price_cents=50, size_delta=10)
    _drive_ws_delta(store, ticker, side="yes", price_cents=60, size_delta=-12)
    _drive_ws_delta(store, ticker, side="no", price_cents=49, size_delta=10)
    assert st.quote_owner == "REST_VERIFIED_DEGRADED"
    assert store._ws_promote_streak.get(ticker, 0) == 0
    assert st.best_bid_cents == 60  # REST BBO still the effective quote
    assert st.best_ask_cents == 61

    # Bring the WS book back to parity without crossing: remove the 49 NO
    # level first (ask back to 61, book stays 50/61 divergent), then restore
    # the 60 YES bid.  The parity streak rebuilds from zero.
    _drive_ws_delta(store, ticker, side="no", price_cents=49, size_delta=-10)
    assert st.quote_owner == "REST_VERIFIED_DEGRADED"
    _drive_ws_delta(store, ticker, side="yes", price_cents=60, size_delta=10)
    for i in range(ms_mod._WS_PROMOTE_STREAK - 2):
        _drive_ws_delta(store, ticker, side="yes", price_cents=60, size_delta=1)
        assert st.quote_owner == "REST_VERIFIED_DEGRADED"
    _drive_ws_delta(store, ticker, side="yes", price_cents=60, size_delta=1)
    assert st.quote_owner == "WS_FRESH_VERIFIED"


def test_rest_owned_book_stable_while_rest_polls(store):
    """Interleaved REST polls + parity deltas hold a stable REST owner (no flap)."""
    ticker = "KXBTC15M-TEST-H6"
    st = _seed_ws_verified(store, ticker)

    _rest_poll(store, ticker, yes_bid=0.60, no_bid=0.39)
    assert st.quote_owner == "REST_VERIFIED_DEGRADED"

    # In-parity delta followed by a fresh REST poll: owner must not flip.
    _drive_ws_delta(store, ticker, side="yes", price_cents=60, size_delta=1)
    _rest_poll(store, ticker, yes_bid=0.60, no_bid=0.39)
    assert st.quote_owner == "REST_VERIFIED_DEGRADED"

    _drive_ws_delta(store, ticker, side="yes", price_cents=60, size_delta=1)
    _rest_poll(store, ticker, yes_bid=0.60, no_bid=0.39)
    assert st.quote_owner == "REST_VERIFIED_DEGRADED"
