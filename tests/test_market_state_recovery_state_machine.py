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
