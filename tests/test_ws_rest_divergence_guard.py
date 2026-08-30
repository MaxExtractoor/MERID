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
async def test_ws_authoritative_allows_marketable_divergence():
    """If WS is authoritative and the order is marketable against WS, allow."""
    state = _make_ws_state()
    store = _make_market_state_store(state)
    port = _make_port()

    with patch("merid.event_venues.kalshi.market_state.get_kalshi_market_state_store", return_value=store):
        result = await _ws_rest_divergence_guard(
            _make_intent(),
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
