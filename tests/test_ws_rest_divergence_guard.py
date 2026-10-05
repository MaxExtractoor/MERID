"""
Tests for the source-aware WS/REST divergence guard in order_router.py.

These tests verify that WebSocket is treated as the authoritative live feed,
REST is used for reconciliation only, and divergence is classified by freshness
and source rather than blindly blocking marketable orders.
"""

import asyncio
import time
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merid.event_venues.kalshi.market_state import BookHealth
from merid.event_venues.kalshi.order_router import OrderIntent, _ws_rest_divergence_guard
from merid.event_venues.kalshi.port import OrderbookLevel, OrderbookResult
from merid.prediction.trading_mode import TradingMode


def _make_ws_state(
    best_bid_cents=79,
    best_ask_cents=80,
    data_source="WS_ORDERBOOK_DELTA_LIVE",
    snapshot_complete=True,
    live_sequence_confirmed=True,
    book_initialized=True,
    book_health=BookHealth.LIVE,
    last_ws_update_ts=None,
):
    if last_ws_update_ts is None:
        last_ws_update_ts = time.monotonic()
    return SimpleNamespace(
        ticker="KXSOL15M-26AUG301500-00",
        best_bid_cents=best_bid_cents,
        best_ask_cents=best_ask_cents,
        data_source=data_source,
        snapshot_complete=snapshot_complete,
        live_sequence_confirmed=live_sequence_confirmed,
        book_initialized=book_initialized,
        book_health=book_health,
        last_ws_update_ts=last_ws_update_ts,
        last_book_update_ts=last_ws_update_ts,
    )


def _make_market_state_store(state, snapshot_ts=1000.0):
    store = MagicMock()
    store.get.return_value = state
    store._validate_yes_no_invariants.return_value = True
    # Real snapshot marker so the aligned-divergence tracker reads a float, not
    # a MagicMock.  Tests bump the book's _snapshot_ts to simulate a landed
    # WS resnapshot; deltas never touch it.
    book = SimpleNamespace(_snapshot_ts=snapshot_ts)
    store._ob = SimpleNamespace(_books={state.ticker: book} if state else {})
    return store


def _make_port(rest_yes_bid=70, rest_yes_ask=74, timestamp=None, success=True):
    if timestamp is None:
        timestamp = time.time()
    port = AsyncMock()

    async def _get_orderbook(_ticker):
        if not success:
            return OrderbookResult(success=False, error="timeout")
        yes_levels = [OrderbookLevel(price_cents=rest_yes_bid, size=Decimal("100"), side="yes")]
        no_levels = [OrderbookLevel(price_cents=100 - rest_yes_ask, size=Decimal("100"), side="no")]
        return OrderbookResult(
            success=True,
            yes_levels=yes_levels,
            no_levels=no_levels,
            timestamp=timestamp,
        )

    port.get_orderbook.side_effect = _get_orderbook
    return port


def _make_intent(side="no", action="buy", price_cents=25, execution_mode=None):
    return OrderIntent(
        ticker="KXSOL15M-26AUG301500-00",
        side=side,
        action=action,
        price_cents=price_cents,
        count=1,
        source="merid.prediction.agent_grid_15m",
        aggressiveness=1.0,
        execution_mode=execution_mode,
    )





@pytest.mark.asyncio
async def test_favorable_drift_blocks_thesis_stale_fill():
    """A locked WS top diverging from a crashed REST book must not hand us a
    'favorable' fill: BUY_YES decided at 62c while REST sits at 43/44 is the
    market repricing against the thesis (adverse selection), not improvement.

    Reproduces KXBTC15M-26SEP251115-15 (2026-09-25): WS book locked at 62/62
    on a dying socket while the exchange traded 43/44; the IOC filled at 43c
    and the contract settled NO for -45c.
    """
    state = _make_ws_state(best_bid_cents=62, best_ask_cents=62)
    store = _make_market_state_store(state)
    port = _make_port(rest_yes_bid=43, rest_yes_ask=44)

    intent = _make_intent(side="yes", action="buy", price_cents=64)
    intent.selected_outcome_price_cents = 62

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            intent, port, TradingMode.LIVE, time.monotonic()
        )

    assert result is not None
    assert result.status == "rejected"
    assert result.reason.startswith("market_repriced:favorable_drift:")


@pytest.mark.asyncio
async def test_favorable_drift_within_cap_allows():
    """Small price improvement (<= cap) is normal and must still fill."""
    state = _make_ws_state(best_bid_cents=62, best_ask_cents=62)
    store = _make_market_state_store(state)
    port = _make_port(rest_yes_bid=57, rest_yes_ask=58)

    intent = _make_intent(side="yes", action="buy", price_cents=64)
    intent.selected_outcome_price_cents = 62  # drift = 62-58 = 4c <= 8c cap

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            intent, port, TradingMode.LIVE, time.monotonic()
        )

    assert result is None


@pytest.mark.asyncio
async def test_favorable_drift_never_blocks_exit():
    """Reduce-only exits bypass the drift guard entirely."""
    state = _make_ws_state(best_bid_cents=62, best_ask_cents=62)
    store = _make_market_state_store(state)
    port = _make_port(rest_yes_bid=43, rest_yes_ask=44)

    intent = _make_intent(side="yes", action="sell", price_cents=57)
    intent.source = "position_monitor_exit"

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            intent, port, TradingMode.LIVE, time.monotonic()
        )

    assert result is None


@pytest.mark.asyncio
async def test_favorable_drift_blocks_no_side_crash():
    """NO-side symmetric case: BUY_NO decided at 45c while fresh ask is 33c —
    the tape repriced toward YES; the NO thesis is stale."""
    state = _make_ws_state(best_bid_cents=55, best_ask_cents=55)  # no ask = 45
    store = _make_market_state_store(state)
    port = _make_port(rest_yes_bid=66, rest_yes_ask=67)  # no ask = 33

    intent = _make_intent(side="no", action="buy", price_cents=47)
    intent.selected_outcome_price_cents = 45  # drift = 45-33 = 12c > 8c cap

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            intent, port, TradingMode.LIVE, time.monotonic()
        )

    assert result is not None
    assert result.status == "rejected"
    assert "favorable_drift" in result.reason


@pytest.mark.asyncio
async def test_ws_authoritative_allows_marketable_divergence():
    """If WS is authoritative and the order is marketable against WS, allow."""
    state = _make_ws_state()
    store = _make_market_state_store(state)
    port = _make_port()

    # BUY_NO at 30c is marketable against both WS (ask 21c) and REST (ask 30c).
    # Decision priced the edge at no-ask 23c: drift to the live 21c WS ask is
    # 2c, inside the favorable-drift cap, so the allow path is exercised.
    intent = _make_intent(price_cents=30)
    intent.selected_outcome_price_cents = 23
    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            intent,
            port,
            TradingMode.LIVE,
            time.monotonic(),
        )

    assert result is None


@pytest.mark.asyncio
async def test_ws_authoritative_blocks_not_marketable():
    """A fresh WS book with a non-marketable price must still be blocked."""
    state = _make_ws_state()
    store = _make_market_state_store(state)
    port = _make_port()

    # BUY_NO at 10c is below the WS NO ask of 21c -> not marketable for a taker.
    intent = _make_intent(price_cents=10)

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            intent,
            port,
            TradingMode.LIVE,
            time.monotonic(),
        )

    assert result is not None
    assert result.status == "rejected"
    assert "not_marketable" in result.reason


@pytest.mark.asyncio
async def test_pending_divergence_does_not_quarantine_fresh_ws():
    """2026-09-29 source-aware contract: a *single* comparable WS/REST mismatch
    is pending evidence, not corruption.  The fresh, contiguous WS book keeps
    its authority — the order is judged on WS alone (edge_lost_at_submit when
    not marketable) and the book is NOT quarantined.  Quarantine is reserved
    for divergence that survives a forced WS snapshot rebuild."""
    state = _make_ws_state()
    state.executable = True
    store = _make_market_state_store(state)
    # Fresh REST 9c away from WS on the NO-ask side -> comparable divergence.
    port = _make_port(rest_yes_bid=70, rest_yes_ask=74)

    intent = _make_intent(price_cents=10)  # below WS NO ask (21c)

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            intent,
            port,
            TradingMode.LIVE,
            time.monotonic(),
        )

    assert result is not None
    assert result.status == "rejected"
    assert "not_marketable" in result.reason
    # Pending divergence must not invalidate a fresh authoritative WS book.
    store._set_snapshot_complete.assert_not_called()
    store._set_book_health.assert_not_called()
    store._maybe_trigger_book_recovery.assert_not_called()


@pytest.mark.asyncio
async def test_persistent_divergence_after_resnapshot_quarantines():
    """The hard-integrity path: a comparable mismatch that persists after a
    forced WS snapshot rebuild is a genuine semantic defect — the book is
    quarantined (INVALID + FULL_SNAPSHOT + RESYNC_REQUESTED) and the order is
    blocked with ``divergence_persistent_after_resnapshot``."""
    state = _make_ws_state()
    state.executable = True
    store = _make_market_state_store(state)
    # 39c divergence on the NO side exceeds the 25c hard limit -> the first
    # comparable observation already escalates to the verify state.
    port = _make_port(rest_yes_bid=40, rest_yes_ask=41)

    intent = _make_intent(price_cents=10)

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        # Observation 1: comparable + hard -> WS_VERIFYING, resnapshot forced.
        result = await _ws_rest_divergence_guard(
            intent, port, TradingMode.LIVE, time.monotonic()
        )
        assert result is not None
        assert result.status == "rejected"
        assert "divergence_pending_resnapshot" in result.reason
        store._maybe_trigger_book_recovery.assert_called_once_with(
            intent.ticker, "aligned_divergence"
        )
        store._set_snapshot_complete.assert_not_called()  # not quarantined yet

        # A forced WS snapshot rebuild lands (apply_snapshot re-stamps the
        # book's _snapshot_ts); the feeds still disagree on the next aligned
        # check -> persistent semantic defect -> quarantine.
        store._ob._books[intent.ticker]._snapshot_ts += 1.0
        result = await _ws_rest_divergence_guard(
            intent, port, TradingMode.LIVE, time.monotonic()
        )

    assert result is not None
    assert result.status == "rejected"
    assert "divergence_persistent_after_resnapshot" in result.reason
    store._set_snapshot_complete.assert_called_with(
        intent.ticker, False, "divergence_persistent"
    )
    store._set_book_health.assert_called_with(
        intent.ticker, BookHealth.RESYNC_REQUESTED, "divergence_persistent"
    )
    assert state.data_quality == "INVALID"
    assert state.executable is False
    assert state.book_initialized is False
    assert state.recovery_required_source == "FULL_SNAPSHOT"


@pytest.mark.asyncio
async def test_comparable_agreement_clears_verify_state():
    """A comparable agreement must reset the persistence tracker — a resolved
    mismatch cannot hold the ticker in WS_VERIFYING forever."""
    from merid.event_venues.kalshi import order_router as _or

    state = _make_ws_state()
    store = _make_market_state_store(state)
    divergent_port = _make_port(rest_yes_bid=40, rest_yes_ask=41)   # hard div
    coherent_port = _make_port(rest_yes_bid=79, rest_yes_ask=80)    # agrees

    intent = _make_intent(price_cents=25)  # marketable on WS NO ask 21; drift-safe
    intent.selected_outcome_price_cents = 25

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        # Hard comparable divergence -> verify (this order pauses).
        r1 = await _ws_rest_divergence_guard(
            intent, divergent_port, TradingMode.LIVE, time.monotonic()
        )
        assert r1 is not None and "divergence_pending_resnapshot" in r1.reason
        assert _or._aligned_div[intent.ticker]["verify_ts"] == 1000.0

        # Comparable agreement clears the tracker before a snapshot lands.
        r2 = await _ws_rest_divergence_guard(
            intent, coherent_port, TradingMode.LIVE, time.monotonic()
        )
        assert r2 is None
        assert _or._aligned_div[intent.ticker]["verify_ts"] is None
        assert _or._aligned_div[intent.ticker]["n"] == 0

        # The next divergence starts a fresh persistence count (pending, allow).
        r3 = await _ws_rest_divergence_guard(
            intent, divergent_port, TradingMode.LIVE, time.monotonic()
        )
        assert r3 is not None  # hard divergence -> verify again
        assert "divergence_pending_resnapshot" in r3.reason


@pytest.mark.asyncio
async def test_marketable_rejection_does_not_resync():
    """An order blocked only because it is not marketable against the *WS* book
    while feeds agree (coherent path) must not invalidate the book."""
    state = _make_ws_state()
    store = _make_market_state_store(state)
    port = _make_port(rest_yes_bid=79, rest_yes_ask=80)  # coherent with WS 79/80

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            _make_intent(price_cents=25),  # BUY_NO 25 >= NO ask 21 -> marketable
            port,
            TradingMode.LIVE,
            time.monotonic(),
        )

    assert result is None
    store._set_snapshot_complete.assert_not_called()
    store._set_book_health.assert_not_called()


@pytest.mark.asyncio
async def test_stale_ws_allows_rest_marketable():
    """If WS is stale but REST is fresh and marketable, allow via REST."""
    state = _make_ws_state(last_ws_update_ts=time.monotonic() - 60.0)
    store = _make_market_state_store(state)
    port = _make_port(rest_yes_bid=70, rest_yes_ask=74)

    # REST NO ask is 100 - 70 = 30c. BUY_NO at 30c is marketable.
    intent = _make_intent(price_cents=30)

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            intent,
            port,
            TradingMode.LIVE,
            time.monotonic(),
        )

    assert result is None


@pytest.mark.asyncio
async def test_stale_rest_allows_ws_marketable():
    """If REST is stale/lagging but WS is fresh and marketable, allow."""
    state = _make_ws_state()
    store = _make_market_state_store(state)
    # REST timestamp is much older than WS last update.
    port = _make_port(rest_yes_bid=70, rest_yes_ask=74, timestamp=time.time() - 60.0)

    intent = _make_intent(price_cents=25)

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            intent,
            port,
            TradingMode.LIVE,
            time.monotonic(),
        )

    assert result is None


@pytest.mark.asyncio
async def test_rest_unavailable_allows_ws_marketable():
    """If the REST fetch fails and WS is fresh/marketable, allow."""
    state = _make_ws_state()
    store = _make_market_state_store(state)
    port = _make_port(success=False)

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            _make_intent(),
            port,
            TradingMode.LIVE,
            time.monotonic(),
        )

    assert result is None


@pytest.mark.asyncio
async def test_crossed_book_rejected_and_resync():
    """An internally crossed/inconsistent book is an integrity failure."""
    state = _make_ws_state(best_bid_cents=85, best_ask_cents=80)  # inverted
    store = _make_market_state_store(state)
    port = _make_port()

    # Make the invariant validator reflect the crossed state.
    def _validate_invariant(ticker, yb, ya, nb, na):
        return not (yb is not None and ya is not None and yb > ya)

    store._validate_yes_no_invariants.side_effect = _validate_invariant

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            _make_intent(),
            port,
            TradingMode.LIVE,
            time.monotonic(),
        )

    assert result is not None
    assert result.status == "rejected"
    assert "inconsistent" in result.reason or "ws_book_inconsistent" in result.reason
    store._set_snapshot_complete.assert_called_once()
    store._set_book_health.assert_called_once()


@pytest.mark.asyncio
async def test_hard_divergence_rejected():
    """A comparable divergence beyond the hard limit escalates straight to
    WS_VERIFYING on the first observation: the order pauses and a forced WS
    snapshot rebuild is triggered.  It is not yet a quarantine — that requires
    the disagreement to survive the rebuild."""
    state = _make_ws_state()
    store = _make_market_state_store(state)
    # REST is ~39c away on the NO ask side: YES bid 40 -> NO ask 60, WS NO ask 21.
    port = _make_port(rest_yes_bid=40, rest_yes_ask=41)

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            _make_intent(),
            port,
            TradingMode.LIVE,
            time.monotonic(),
        )

    assert result is not None
    assert result.status == "rejected"
    assert "divergence_pending_resnapshot" in result.reason
    store._maybe_trigger_book_recovery.assert_called_once_with(
        "KXSOL15M-26AUG301500-00", "aligned_divergence"
    )


@pytest.mark.asyncio
async def test_coherent_feeds_allowed():
    """If WS and REST agree within tolerance, allow regardless of marketable check."""
    state = _make_ws_state()
    store = _make_market_state_store(state)
    port = _make_port(rest_yes_bid=79, rest_yes_ask=80)

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            _make_intent(),
            port,
            TradingMode.LIVE,
            time.monotonic(),
        )

    assert result is None


@pytest.mark.asyncio
async def test_ws_snapshot_isolates_concurrent_state_mutation():
    """The guard must snapshot WS state before awaiting REST; concurrent WS updates
    must not influence the divergence decision for that order."""
    state = _make_ws_state(best_bid_cents=50, best_ask_cents=50)
    store = _make_market_state_store(state)

    async def _mutating_get_orderbook(_ticker):
        # Simulate a WS callback mutating the shared state while the REST
        # fetch is in flight.  Without a snapshot this would make the guard
        # see a 30c divergence and reject.
        state.best_bid_cents = 80
        state.best_ask_cents = 80
        return OrderbookResult(
            success=True,
            yes_levels=[OrderbookLevel(price_cents=50, size=Decimal("100"), side="yes")],
            no_levels=[OrderbookLevel(price_cents=50, size=Decimal("100"), side="no")],
            timestamp=time.time(),
        )

    port = AsyncMock()
    port.get_orderbook.side_effect = _mutating_get_orderbook

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            _make_intent(price_cents=50),
            port,
            TradingMode.LIVE,
            time.monotonic(),
        )

    assert result is None


@pytest.mark.asyncio
async def test_locked_ws_divergent_allows_rest_marketable_and_resyncs():
    """2026-09-25: a locked WS top (bid==ask) diverging from a fresh REST pull is
    a split-tape artifact — one ladder side is awaiting its delta.  Prefer the
    fresh marketable REST quote for execution AND mark the WS book for resync
    so the frozen top does not keep vetoing orders."""
    # WS YES locked at 79/79 -> NO-space book 21/21 (locked).  REST YES 70/74
    # -> NO ask = 30c; divergence vs locked WS NO-ask 21c is 9c > tolerance.
    state = _make_ws_state(best_bid_cents=79, best_ask_cents=79)
    store = _make_market_state_store(state)
    port = _make_port(rest_yes_bid=70, rest_yes_ask=74)

    intent = _make_intent(price_cents=30)  # BUY_NO @30 marketable vs REST ask 30

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            intent,
            port,
            TradingMode.LIVE,
            time.monotonic(),
        )

    assert result is None
    # Locked divergent WS must be marked for resync, not trusted as-is.
    store._set_snapshot_complete.assert_called_once_with(
        intent.ticker, False, "ws_locked_divergent"
    )
    store._set_book_health.assert_called_once_with(
        intent.ticker, BookHealth.RESYNC_REQUESTED, "ws_locked_divergent"
    )
    store._maybe_trigger_book_recovery.assert_called_once_with(
        intent.ticker, "ws_locked_divergent"
    )


@pytest.mark.asyncio
async def test_locked_ws_divergent_blocks_when_rest_not_marketable():
    """Locked divergent WS with a fresh but non-marketable REST still rejects —
    the REST-preference only applies when the fresh quote can actually fill."""
    state = _make_ws_state(best_bid_cents=79, best_ask_cents=79)
    store = _make_market_state_store(state)
    port = _make_port(rest_yes_bid=70, rest_yes_ask=74)

    intent = _make_intent(price_cents=10)  # below REST NO ask 30c -> not marketable

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            intent,
            port,
            TradingMode.LIVE,
            time.monotonic(),
        )

    assert result is not None
    assert result.status == "rejected"
    assert "stale_ws" in result.reason
    store._set_snapshot_complete.assert_called_once_with(
        intent.ticker, False, "ws_stale_at_order"
    )
    store._maybe_trigger_book_recovery.assert_called_once_with(
        intent.ticker, "ws_stale_at_order"
    )


@pytest.mark.asyncio
async def test_fresh_unlocked_ws_divergent_blocks_not_marketable():
    """A fresh, *unlocked* WS book that diverges from REST is trusted as the
    live feed — an order marketable on REST but not on WS still rejects."""
    state = _make_ws_state()  # fresh 79/80
    store = _make_market_state_store(state)
    port = _make_port(rest_yes_bid=70, rest_yes_ask=74)

    intent = _make_intent(price_cents=10)  # below WS NO ask 21c

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            intent,
            port,
            TradingMode.LIVE,
            time.monotonic(),
        )

    assert result is not None
    assert result.status == "rejected"
    assert "not_marketable" in result.reason


def _make_exit_intent(side="yes", action="sell", price_cents=40):
    intent = _make_intent(side=side, action=action, price_cents=price_cents)
    intent.entry_or_exit = "exit"
    intent.reduce_only = True
    return intent


@pytest.mark.asyncio
async def test_reduce_only_exit_bypasses_no_fresh_feed():
    """2026-09-24 incident: a settlement-guard exit was vetoed by
    ``no_fresh_feed`` at T-48s and the position expired unclosed (-60c).
    A limit-bounded reduce-only exit must never be freshness-vetoed."""
    state = _make_ws_state(last_ws_update_ts=time.monotonic() - 60.0)
    store = _make_market_state_store(state)
    port = _make_port(success=False)  # REST unavailable too

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            _make_exit_intent(),
            port,
            TradingMode.LIVE,
            time.monotonic(),
        )

    assert result is None


@pytest.mark.asyncio
async def test_entry_still_blocked_on_no_fresh_feed():
    """The exit carve-out must not leak to entries: same stale-feed
    conditions still reject an entry order."""
    state = _make_ws_state(last_ws_update_ts=time.monotonic() - 60.0)
    store = _make_market_state_store(state)
    port = _make_port(success=False)

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            _make_intent(),
            port,
            TradingMode.LIVE,
            time.monotonic(),
        )

    assert result is not None
    assert result.status == "rejected"
    assert "no_fresh_feed" in result.reason


@pytest.mark.asyncio
async def test_ws_resyncing_fresh_rest_marketable_allows():
    """2026-10-05 relax (KALSHI-015): an entry emitted on a healthy WS book
    must not die on the authority label when the WS resyncs during routing —
    a fresh REST pull IS verified exchange truth, and the order's own limit
    price caps the worst-case fill.  Reproduces the KXBTC15M-…1815 loss:
    BUY_NO intent with +4.3c claimed EV rejected ws_resyncing while REST was
    <500ms stale.  Only the no-fresh-feed case stays blocked."""
    state = _make_ws_state(
        snapshot_complete=False,
        live_sequence_confirmed=False,
        book_health=BookHealth.RESYNC_REQUESTED,
    )
    store = _make_market_state_store(state)
    port = _make_port(rest_yes_bid=70, rest_yes_ask=74)

    # REST NO ask = 30c; BUY_NO at 30c is marketable on REST.
    intent = _make_intent(price_cents=30)

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            intent, port, TradingMode.LIVE, time.monotonic()
        )

    assert result is None
    assert getattr(intent, "_submit_quote_source", None) == "rest"


@pytest.mark.asyncio
async def test_ws_resyncing_fresh_rest_not_marketable_rejects():
    """The fallback still fails closed on price: if the fresh REST ask is
    above the order's limit the order is not marketable on the only trusted
    book and must be rejected — the limit never gets lifted past the edge."""
    state = _make_ws_state(
        snapshot_complete=False,
        live_sequence_confirmed=False,
        book_health=BookHealth.RESYNC_REQUESTED,
    )
    store = _make_market_state_store(state)
    port = _make_port(rest_yes_bid=70, rest_yes_ask=74)

    # REST NO ask = 30c; BUY_NO at 25c cannot fill.
    intent = _make_intent(price_cents=25)

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            intent, port, TradingMode.LIVE, time.monotonic()
        )

    assert result is not None
    assert result.status == "rejected"
    assert result.reason.startswith("edge_lost_at_submit:not_marketable")


@pytest.mark.asyncio
async def test_ws_resyncing_rest_unavailable_still_rejects():
    """No fresh feed at all remains a hard reject: WS resyncing AND the REST
    pull failed — nothing trustworthy to judge the order on."""
    state = _make_ws_state(
        snapshot_complete=False,
        live_sequence_confirmed=False,
        book_health=BookHealth.RESYNC_REQUESTED,
    )
    store = _make_market_state_store(state)
    port = _make_port(success=False)

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            _make_intent(price_cents=30), port, TradingMode.LIVE, time.monotonic()
        )

    assert result is not None
    assert result.status == "rejected"
    assert result.reason == "ws_resyncing:ws_not_authoritative"


@pytest.mark.asyncio
async def test_ws_resyncing_stale_rest_still_rejects():
    """A REST pull older than max_rest_age_ms does not qualify as fresh
    exchange truth — resync + stale REST still rejects."""
    state = _make_ws_state(
        snapshot_complete=False,
        live_sequence_confirmed=False,
        book_health=BookHealth.RESYNC_REQUESTED,
    )
    store = _make_market_state_store(state)
    port = _make_port(rest_yes_bid=70, rest_yes_ask=74, timestamp=time.time() - 60.0)

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            _make_intent(price_cents=30), port, TradingMode.LIVE, time.monotonic()
        )

    assert result is not None
    assert result.status == "rejected"
    assert result.reason == "ws_resyncing:ws_not_authoritative"


@pytest.mark.asyncio
async def test_ws_resyncing_inconsistent_rest_book_rejects():
    """Fresh but internally inconsistent REST book (crossed) must not
    authorize an entry — integrity invariants still apply on the fallback leg."""
    state = _make_ws_state(
        snapshot_complete=False,
        live_sequence_confirmed=False,
        book_health=BookHealth.RESYNC_REQUESTED,
    )
    store = _make_market_state_store(state)
    # Crossed REST book: yes bid > yes ask.
    port = _make_port(rest_yes_bid=76, rest_yes_ask=70)

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            _make_intent(price_cents=30), port, TradingMode.LIVE, time.monotonic()
        )

    assert result is not None
    assert result.status == "rejected"
    assert "rest_book_inconsistent" in result.reason


@pytest.mark.asyncio
async def test_ws_resyncing_fresh_rest_hard_divergence_rejects():
    """A fresh REST pull that disagrees with the WS book beyond the hard
    limit is an integrity failure, not a fallback opportunity — the
    comparable-divergence machinery still vetoes."""
    state = _make_ws_state(
        snapshot_complete=False,
        live_sequence_confirmed=False,
        book_health=BookHealth.RESYNC_REQUESTED,
    )
    store = _make_market_state_store(state)
    # WS NO side is 20/21; REST YES 40/41 -> NO side 59/60 -> ~39c divergence.
    port = _make_port(rest_yes_bid=40, rest_yes_ask=41)

    intent = _make_intent(price_cents=60)

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            intent, port, TradingMode.LIVE, time.monotonic()
        )

    assert result is not None
    assert result.status == "rejected"


@pytest.mark.asyncio
async def test_reduce_only_exit_bypasses_hard_divergence():
    """Hard-limit feed divergence is an integrity failure for entries, but a
    reduce-only exit is limit-bounded and only shrinks exposure — it proceeds."""
    state = _make_ws_state()
    store = _make_market_state_store(state)
    port = _make_port(rest_yes_bid=40, rest_yes_ask=41)

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            _make_exit_intent(),
            port,
            TradingMode.LIVE,
            time.monotonic(),
        )

    assert result is None


@pytest.mark.asyncio
async def test_reduce_only_exit_bypasses_stale_ws():
    """Stale WS + non-marketable REST rejects entries but must not trap an exit."""
    state = _make_ws_state(last_ws_update_ts=time.monotonic() - 60.0)
    store = _make_market_state_store(state)
    # REST YES 74/75 -> 5c divergence (above tolerance, below hard limit), and
    # a SELL_YES at 80c is above the REST bid (74) -> not marketable -> the
    # stale-WS block branch is reached, where the exit bypass must apply.
    port = _make_port(rest_yes_bid=74, rest_yes_ask=75)

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            _make_exit_intent(price_cents=80),
            port,
            TradingMode.LIVE,
            time.monotonic(),
        )

    assert result is None


@pytest.mark.asyncio
async def test_reduce_only_exit_bypasses_inconsistent_ws_book():
    """A crossed/corrupted WS book blocks entries but not a reduce-only exit."""
    state = _make_ws_state(best_bid_cents=85, best_ask_cents=80)
    store = _make_market_state_store(state)
    port = _make_port()

    def _validate_invariant(ticker, yb, ya, nb, na):
        return not (yb is not None and ya is not None and yb > ya)

    store._validate_yes_no_invariants.side_effect = _validate_invariant

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            _make_exit_intent(),
            port,
            TradingMode.LIVE,
            time.monotonic(),
        )

    assert result is None


@pytest.mark.asyncio
async def test_phantom_high_ws_ask_repriced_against_rest():
    """2026-09-25 audit: the single largest entry blocker was
    ``ws_rest_divergence:not_marketable`` (1,339 rejects).  One recurring mode:
    a fresh-but-corrupted WS top sitting ABOVE a just-fetched REST book
    (phantom ask left by dropped deltas during a fast move).  For a buy, the
    exchange only ever fills at the real ask — the fresh REST ask — so the
    reprice check must compare against REST, not max(ws, rest)."""
    state = _make_ws_state(best_bid_cents=61, best_ask_cents=62)  # phantom-high
    store = _make_market_state_store(state)
    port = _make_port(rest_yes_bid=44, rest_yes_ask=45)  # real book 44/45

    # BUY_YES priced at the real ask (45c).  WS says 62c -> not marketable on
    # WS, marketable on REST.  Divergence 17c: above tolerance, below hard
    # limit, and the WS top is not locked (61 < 62) -> divergent reprice path.
    intent = _make_intent(side="yes", action="buy", price_cents=45)
    intent.selected_outcome_price_cents = 45
    intent.ev_net_cents = 10.0  # edge budget -> epc > 45

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            intent, port, TradingMode.LIVE, time.monotonic()
        )

    assert result is None  # allowed via REST-bounded reprice
    assert intent.price_cents >= 45


@pytest.mark.asyncio
async def test_rest_ask_beyond_edge_budget_still_rejects():
    """The REST-ask reprice must not soften the edge bound: when the real ask
    moved past the edge-preserving budget, the entry still rejects."""
    state = _make_ws_state(best_bid_cents=61, best_ask_cents=62)
    store = _make_market_state_store(state)
    port = _make_port(rest_yes_bid=78, rest_yes_ask=79)  # real move UP to 79c

    intent = _make_intent(side="yes", action="buy", price_cents=45)
    intent.selected_outcome_price_cents = 45
    intent.ev_net_cents = 10.0  # epc ~54 << 79

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            intent, port, TradingMode.LIVE, time.monotonic()
        )

    assert result is not None
    assert result.status == "rejected"
    assert "not_marketable" in result.reason


def test_stop_candidate_exits_pass_agent_whitelist():
    """Reduce-only stop-candidate exits carry agent_id='stop_candidate' and are
    already in allowed_sources; they must not die at the entry agent whitelist
    (255 protective exits were rejected as unauthorized_agent:stop_candidate)."""
    from merid.event_venues.kalshi.order_router import _is_kalshi_15m_crypto_agent

    assert _is_kalshi_15m_crypto_agent("stop_candidate") is True
    # Entries from unrecognized agents must still be refused.
    assert _is_kalshi_15m_crypto_agent("rogue_agent_x") is False
    assert _is_kalshi_15m_crypto_agent("") is False


@pytest.mark.parametrize("side", ["yes", "no"])
@pytest.mark.parametrize("action", ["buy", "sell"])
def test_maker_quote_inside_spread_is_valid(side, action):
    from merid.event_venues.kalshi.order_router import _is_marketable_against_book

    intent = _make_intent(side, action, 50, execution_mode="maker")
    intent.aggressiveness = 0.0
    intent.post_only = True
    book = {"bid_cents": 40, "ask_cents": 60}
    assert _is_marketable_against_book(intent, book)
    intent.price_cents = 60 if action == "buy" else 40
    assert not _is_marketable_against_book(intent, book)


@pytest.mark.parametrize("side", ["yes", "no"])
@pytest.mark.parametrize("quantity, expected_cap", [("1", 47), ("0.01", 46)])
def test_edge_budget_uses_exact_order_fee(side, quantity, expected_cap):
    from merid.event_venues.kalshi.order_router import _max_edge_preserving_buy_price

    intent = _make_intent(side=side, price_cents=47)
    intent.count_fp = Decimal(quantity)
    intent.selected_outcome_price_cents = 47
    intent.ev_net_cents = Decimal("2.10")
    intent.fee_cents = Decimal("1.75")
    intent.min_required_edge = Decimal("0.02")
    assert _max_edge_preserving_buy_price(intent) == expected_cap


@pytest.mark.asyncio
async def test_reprice_requires_economic_budget(monkeypatch):
    monkeypatch.setenv("MERID_ENTRY_MAX_CHASE_CENTS", "5")
    store = _make_market_state_store(_make_ws_state(53, 54))
    intent = _make_intent(side="yes", price_cents=50)
    intent.selected_outcome_price_cents = 50
    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            intent, _make_port(53, 54), TradingMode.LIVE, time.monotonic()
        )
    assert result is not None
    assert result.status == "rejected"
    assert intent.price_cents == 50


@pytest.mark.asyncio
async def test_divergent_reprice_cannot_bypass_favorable_drift(monkeypatch):
    monkeypatch.setenv("MERID_ENTRY_MAX_IMPROVEMENT_CENTS", "8")
    store = _make_market_state_store(_make_ws_state(61, 62))
    intent = _make_intent(side="yes", price_cents=60)
    intent.selected_outcome_price_cents = 60
    intent.ev_net_cents = 10
    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            intent, _make_port(44, 45), TradingMode.LIVE, time.monotonic()
        )
    assert result is not None
    assert "favorable_drift" in result.reason
    assert intent.price_cents == 60


@pytest.mark.asyncio
@pytest.mark.parametrize("fresh_ws", [False, True])
async def test_rest_error_requires_valid_fresh_ws(fresh_ws):
    state = _make_ws_state(last_ws_update_ts=time.monotonic() - (0 if fresh_ws else 60))
    store = _make_market_state_store(state)
    port = AsyncMock()
    port.get_orderbook.side_effect = RuntimeError("offline REST failure")
    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            _make_intent(), port, TradingMode.LIVE, time.monotonic()
        )
    if fresh_ws:
        assert result is None
    else:
        assert result is not None
        assert result.status == "rejected"


@pytest.mark.asyncio
async def test_ws_age_rechecked_after_rest_wait():
    store = _make_market_state_store(_make_ws_state())
    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store), patch(
        "merid.event_venues.kalshi.order_router._ws_age_ms", side_effect=[0.0, 6000.0]
    ):
        result = await _ws_rest_divergence_guard(
            _make_intent(), _make_port(success=False), TradingMode.LIVE, time.monotonic()
        )
    assert result is not None
    assert result.reason == "untrusted:no_fresh_feed"


@pytest.mark.asyncio
@pytest.mark.parametrize("side", ["yes", "no"])
@pytest.mark.parametrize("ask, ws_age_s, allowed", [(54, 0, True), (56, 0, False), (54, 60, False)])
async def test_locked_fresh_ws_reprices_within_both_caps(side, ask, ws_age_s, allowed, monkeypatch):
    monkeypatch.setenv("MERID_ENTRY_MAX_CHASE_CENTS", "5")
    store = _make_market_state_store(_make_ws_state(50, 50, last_ws_update_ts=time.monotonic() - ws_age_s))
    port = _make_port(ask - 1, ask) if side == "yes" else _make_port(100 - ask, 101 - ask)
    intent = _make_intent(side=side, price_cents=50)
    intent.selected_outcome_price_cents = 50
    intent.ev_net_cents = 10
    intent.min_required_edge = Decimal("0.02")
    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(intent, port, TradingMode.LIVE, time.monotonic())
    if allowed:
        assert result is None
        assert ask <= intent.price_cents <= 55
    else:
        assert result is not None
        assert result.status == "rejected"
        assert intent.price_cents == 50
    store._maybe_trigger_book_recovery.assert_called_once()


@pytest.mark.asyncio
async def test_unconfirmed_ws_repriced_on_agreeing_fresh_rest():
    """2026-10-05 relax: an unconfirmed WS no longer vetoes a reprice when the
    fresh REST pull agrees exactly (0c divergence, internally consistent).
    The REST leg is verified exchange truth; the bounded reprice stays inside
    the edge budget and the chase cap — the order's own limit is the price
    protection.  An agreeing, diverging, or stale REST leg would still gate
    this through the normal consistency/marketability checks."""
    store = _make_market_state_store(_make_ws_state(53, 54, live_sequence_confirmed=False))
    intent = _make_intent(side="yes", price_cents=50)
    intent.selected_outcome_price_cents = 50
    intent.ev_net_cents = 10
    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            intent, _make_port(53, 54), TradingMode.LIVE, time.monotonic()
        )
    assert result is None
    # Repriced up to, but never past, selected price + chase cap (50+5).
    assert 54 <= intent.price_cents <= 55
