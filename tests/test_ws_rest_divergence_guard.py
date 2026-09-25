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


def _make_market_state_store(state):
    store = MagicMock()
    store.get.return_value = state
    store._validate_yes_no_invariants.return_value = True
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
async def test_not_marketable_marks_book_for_resync():
    """2026-09-24: WS books diverging from fresh REST kept feeding phantom-edge
    signals because the ``not_marketable`` rejection never invalidated the book.
    The guard must quarantine the ticker (INVALID + FULL_SNAPSHOT recovery
    requirement + RESYNC_REQUESTED) so deltas cannot re-arm execution, and
    trigger the throttled WS+REST snapshot recovery."""
    state = _make_ws_state()
    state.executable = True
    store = _make_market_state_store(state)
    # Fresh REST 20c away from WS on the NO-ask side -> not_marketable.
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
    store._set_snapshot_complete.assert_called_once_with(
        intent.ticker, False, "divergence_not_marketable"
    )
    store._set_book_health.assert_called_once_with(
        intent.ticker, BookHealth.RESYNC_REQUESTED, "divergence_not_marketable"
    )
    # Quarantine contract: deltas alone must not re-arm a divergent book.
    assert state.data_quality == "INVALID"
    assert state.executable is False
    assert state.book_initialized is False
    assert state.recovery_required_source == "FULL_SNAPSHOT"
    store._maybe_trigger_book_recovery.assert_called_once_with(
        intent.ticker, "divergence_not_marketable"
    )


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
    """Divergence beyond the hard limit is treated as a rollover/corruption."""
    state = _make_ws_state()
    store = _make_market_state_store(state)
    # REST is 40c away on the NO ask side: YES bid 40 -> NO ask 60, WS NO ask 21.
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
    assert "integrity_failure" in result.reason


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
