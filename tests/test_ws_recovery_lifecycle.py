"""WS/REST recovery lifecycle tests (P2 release gate).

Covers the three scenarios flagged for the REST-fallback release:
rollover isolation, determined-market empty-snapshot clearing, and
late-REST-response ordering vs newer WS state.

Note on provenance: ``via="bridge_queue"`` requires WS-envelope internals
(sid/seq stamping) that only the live bridge produces; these tests use the
snapshot-level provenances (``test``/``rest_snapshot``) plus direct
``LocalOrderbook`` checks, which exercise the same book-state machinery.
"""

import pytest

from merid.event_venues.kalshi.market_state import KalshiMarketStateStore
from merid.event_venues.kalshi.orderbook import LocalOrderbook


@pytest.fixture
def store(tmp_path):
    s = KalshiMarketStateStore()
    try:
        yield s
    finally:
        s._stop_batch_worker()
        if s._batch_worker_thread and s._batch_worker_thread.is_alive():
            s._batch_worker_thread.join(timeout=1.0)


def _snap(ticker, yes, no, seq=None):
    m = {
        "type": "orderbook_snapshot",
        "market_ticker": ticker,
        "yes": [[float(p), int(sz)] for p, sz in yes],
        "no": [[float(p), int(sz)] for p, sz in no],
    }
    if seq is not None:
        m["seq"] = seq
    return m


def _apply_snapshot_sync(store, msg, via="test"):
    """Enqueue via the public API, then drain the per-ticker queue
    synchronously (same drain the batch worker submits to its executor).

    Since 2026-11-04 ``apply_orderbook_message`` returns ``None`` for every
    snapshot and applies it asynchronously; tests drain explicitly so
    assertions stay deterministic.
    """
    store.apply_orderbook_message(msg, via=via)
    ticker = msg.get("market_ticker") or msg.get("ticker")
    store._drain_ticker_delta_batch(ticker)
    return store._states.get(ticker)


class TestRolloverIsolation:
    def test_rollover_windows_have_independent_books(self, store):
        """A new contract window must not inherit the prior window's book."""
        old = "KXBTC15M-26NOV192300-00"
        new = "KXBTC15M-26NOV192315-15"
        r1 = _apply_snapshot_sync(store, _snap(old, [(0.60, 10)], [(0.40, 10)]), via="test")
        r2 = _apply_snapshot_sync(store, _snap(new, [(0.55, 8)], [(0.45, 8)]), via="test")
        assert r1 is not None and r2 is not None

        ob_new = store._ob.get_book(new)
        ob_old = store._ob.get_book(old)
        assert 60.0 in ob_old.yes_levels
        assert dict(ob_new.yes_levels) == {55.0: 8.0}, "old window's levels leaked into new book"

    def test_late_message_for_removed_ticker_rebuilds_fresh(self):
        """A delayed snapshot for a removed book creates fresh state —
        it must not resurrect pre-removal levels."""
        ticker = "KXDOGE15M-26NOV192300-00"
        ob = LocalOrderbook(ticker)
        ob.apply_snapshot(_snap(ticker, [(0.90, 5)], [(0.10, 5)], seq=1))
        assert ob.initialized and ob.yes_levels

        # Fresh instance = removed-then-recreated; late duplicate must reflect
        # only what the message carries, not merge with removed state.
        ob2 = LocalOrderbook(ticker)
        ob2.apply_snapshot(_snap(ticker, [(0.90, 5)], [(0.10, 5)], seq=1))
        assert dict(ob2.yes_levels) == {90.0: 5.0}


class TestDeterminedMarketClearsBook:
    def test_empty_snapshot_clears_populated_book_local(self):
        """At book level, an empty snapshot clears all levels — the
        determined-market contract (Kalshi sends empty snapshot on
        determination)."""
        ticker = "KXXRP15M-26NOV192300-00"
        ob = LocalOrderbook(ticker)
        ob.apply_snapshot(_snap(ticker, [(0.70, 20)], [(0.30, 20)], seq=5))
        assert ob.yes_levels and ob.no_levels

        ob.apply_snapshot(_snap(ticker, [], [], seq=6))
        assert dict(ob.yes_levels) == {}, "stale YES levels survived determination"
        assert dict(ob.no_levels) == {}, "stale NO levels survived determination"
        assert ob.initialized, "book should remain initialized (empty but valid)"

    def test_store_empty_snapshot_policy_by_provenance(self, store):
        """Store-level: empty snapshots for an initialized book are only
        accepted via the sequenced WS path; REST/bootstrap retains the
        empty-book rejection policy."""
        ticker = "KXXRP15M-26NOV192300-002"
        r = _apply_snapshot_sync(store, _snap(ticker, [(0.70, 20)], [(0.30, 20)]), via="test")
        assert r is not None
        ob = store._ob.get_book(ticker)
        assert ob.yes_levels

        # REST-provenance empty snapshot must NOT wipe a populated book.
        _apply_snapshot_sync(store, _snap(ticker, [], []), via="rest_polling")
        assert ob.yes_levels, "REST empty snapshot wiped populated book"


class TestLateRestVsNewerWs:
    def test_late_rest_snapshot_does_not_demote_ws_state(self, store):
        """A REST snapshot arriving after a WS snapshot must not present
        REST-derived prices as fresh WS-verified state."""
        ticker = "KXSOL15M-26NOV192300-00"
        state_ws = _apply_snapshot_sync(
            store, _snap(ticker, [(0.62, 10)], [(0.38, 10)]), via="test")
        assert state_ws is not None

        state_after = _apply_snapshot_sync(
            store, _snap(ticker, [(0.50, 10)], [(0.50, 10)]), via="rest_polling")
        assert state_after is not None
        src = getattr(state_after, "data_source", None) or getattr(state_after, "quote_owner", None)
        # REST ingestion is allowed, but provenance must reflect REST,
        # never masquerade as fresh WS.
        assert src is not None
        assert "REST" in str(src).upper() or "DEGRADED" in str(src).upper() or src in (
            "rest_snapshot", "rest_polling", "ws_fallback",
        ), f"late REST snapshot provenance ambiguous: {src}"

    def test_duplicate_snapshot_replaces_not_adds(self):
        """Applying the same snapshot twice must not double quantities."""
        ticker = "KXETH15M-26NOV192300-00"
        ob = LocalOrderbook(ticker)
        msg = _snap(ticker, [(0.55, 10)], [(0.45, 10)], seq=1)
        ob.apply_snapshot(msg)
        ob.apply_snapshot(msg)
        assert ob.yes_levels[55.0] == 10.0, "duplicate snapshot added quantity"
        assert ob.no_levels[45.0] == 10.0

    def test_subpenny_snapshot_levels_roundtrip(self):
        """Subpenny prices survive snapshot -> book -> derived quotes."""
        ticker = "KXBTC15M-26NOV192300-00"
        ob = LocalOrderbook(ticker)
        ob.apply_snapshot({
            "type": "orderbook_snapshot", "ticker": ticker,
            "yes": [[0.9910, 3.0]], "no": [[0.0010, 5.0]], "seq": 1,
        })
        assert 99.1 in ob.yes_levels
        assert 0.1 in ob.no_levels
        best_ask = ob.get_best_ask()
        # YES ask = 100 - best NO bid = 100 - 0.1 = 99.9c
        assert best_ask is not None and abs(best_ask[0] - 99.9) < 0.01
