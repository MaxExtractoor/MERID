"""Tests for LocalOrderbook one-sided delta sanitization.

Reproduces the live issue where a NO-side delta updates the book but
YES-side levels stay stale high, producing a crossed/locked book that
causes market_state to circuit-breaker and block all trading.
"""

from __future__ import annotations

import pytest

from merid.event_venues.kalshi.orderbook import LocalOrderbook


class TestOrderbookCrossedSanitization:
    """Sanity checks for one-sided delta and stale-bid removal."""

    def test_one_sided_no_delta_removes_stale_yes_bid(self):
        """A fresh NO bid should remove stale YES bids above the new YES ask."""
        book = LocalOrderbook("KXBTC15M-26AUG221830-30")

        # Snapshot with stale YES bid at 97c and NO bid at 30c (YES ask=70)
        book.apply_snapshot({
            "ticker": "KXBTC15M-26AUG221830-30",
            "yes": [[0.97, 100]],
            "no": [[0.30, 100]],
            "seq": 1,
        })

        # Fresh NO bid at 68c -> YES ask = 32c.  YES bid 97c is crossed.
        book.apply_delta({
            "side": "no",
            "price_dollars": 0.68,
            "delta_fp": 500,
            "seq": 2,
        })

        best_bid = book.get_best_bid()
        best_ask = book.get_best_ask()
        assert best_bid is None or best_bid[0] < best_ask[0] if best_ask else True
        assert 97 not in book.yes_levels, "stale YES bid 97 must be removed"

    def test_one_sided_yes_delta_removes_stale_no_bid(self):
        """A fresh YES bid should remove stale NO bids above the new NO ask."""
        book = LocalOrderbook("KXETH15M-26AUG221830-30")

        book.apply_snapshot({
            "ticker": "KXETH15M-26AUG221830-30",
            "yes": [[0.30, 100]],
            "no": [[0.97, 100]],
            "seq": 1,
        })

        # Fresh YES bid at 68c -> NO ask = 32c.  NO bid 97c is crossed.
        book.apply_delta({
            "side": "yes",
            "price_dollars": 0.68,
            "delta_fp": 500,
            "seq": 2,
        })

        best_bid = book.get_best_bid()
        best_ask = book.get_best_ask()
        assert best_bid is None or best_bid[0] < best_ask[0] if best_ask else True
        assert 97 not in book.no_levels, "stale NO bid 97 must be removed"

    def test_book_stays_non_crossed_after_multiple_one_sided_deltas(self):
        """A sequence of one-sided deltas should not leave the book crossed."""
        book = LocalOrderbook("KXBTC15M-26AUG221830-30")

        book.apply_snapshot({
            "ticker": "KXBTC15M-26AUG221830-30",
            "yes": [[0.50, 100]],
            "no": [[0.50, 100]],
            "seq": 1,
        })

        # Push NO side up repeatedly, leaving YES side stale.
        for i, price in enumerate([0.55, 0.60, 0.65], start=2):
            book.apply_delta({
                "side": "no",
                "price_dollars": price,
                "delta_fp": 100,
                "seq": i,
            })
            best_bid = book.get_best_bid()
            best_ask = book.get_best_ask()
            if best_bid and best_ask:
                assert best_bid[0] < best_ask[0], (
                    f"crossed after no delta {price}: bid={best_bid[0]} ask={best_ask[0]}"
                )

    def test_quote_fallback_does_not_clear_crossed_state(self):
        """A ticker quote must not overwrite or clear a crossed-book invalidation.

        Quote fallbacks are diagnostic only.  Only a permitted full-book recovery
        (REST full snapshot or clean WS snapshot) or a validated live WS delta may
        restore execution readiness.  This is a regression test for the 2026-08-22
        safety hardening.
        """
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store

        store = get_kalshi_market_state_store()
        ticker = "KXBTC15M-26AUG221830-30"

        # Seed a crossed book: YES bid 97c, YES ask derived from NO bid 68c = 32c.
        # The book is strictly crossed (97 > 32).
        state = store.apply_orderbook_message({
            "type": "orderbook_snapshot",
            "ticker": ticker,
            "yes": [[0.97, 100]],
            "no": [[0.68, 100]],
        }, via="test")

        # A healthy ticker quote (43/44) arrives, but the crossed book has not
        # been recovered through an authoritative source.  The quote is stored as
        # a fallback only and must not overwrite the executable BBO.
        store.apply_quote(ticker, bid_cents=43, ask_cents=44)

        state = store.get(ticker)
        assert state is not None
        assert state.best_bid_cents == 97
        assert state.best_ask_cents == 32
        assert state.fallback_yes_bid_cents == 43
        assert state.fallback_yes_ask_cents == 44
        assert state.quoted_bid_cents == 43
        assert state.quoted_ask_cents == 44
        assert state.book_consistency == "INVERTED"
        assert state.executable is False
        assert state.data_quality != "GOOD"
        assert state.recovery_attested is False
        assert state.transition in ("RESYNC_REQUIRED", "CIRCUIT_BREAKER")

        ready, _ = store.is_market_execution_ready(ticker)
        assert ready is False

    def test_main_event_loop_wiring_for_resync(self):
        """The forwarder can register its event loop so resync tasks can be scheduled."""
        import asyncio
        from merid.event_venues.kalshi.market_state import KalshiMarketStateStore

        store = KalshiMarketStateStore()
        try:
            captured = {}

            async def _register():
                captured["loop"] = asyncio.get_running_loop()
                store.set_main_event_loop(captured["loop"])

            asyncio.run(_register())
            assert store._main_event_loop is captured["loop"]

            # A non-running loop should be ignored.
            dead_loop = asyncio.new_event_loop()
            try:
                store.set_main_event_loop(dead_loop)
                assert store._main_event_loop is captured["loop"]
            finally:
                dead_loop.close()
        finally:
            store._stop_batch_worker()
