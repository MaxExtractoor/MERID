# -*- coding: utf-8 -*-
"""Regression: divergent cover-reprice must fire on fresh REST, not only
time-aligned (comparable) REST.

2026-10-20 live incident (KXXRP15M-26OCT192115-15): a window-quota BUY_NO@80c
IOC was accepted with filled=0 — the real book had run to no_ask=86c during the
~4.3s decision->submit pipeline.  The divergence guard saw the fresh REST leg
(no=85/86) but skipped the cover-reprice because it required `rest_comparable`
(the WS BBO must not move during the REST fetch) — a condition that fails
exactly when the market is moving.  The order then IOC'd into a stale ask.

For a bounded taker buy, covering a *fresh* REST ask inside the edge budget is
strictly dominant: a limit order fills at best ask or dies, so lifting the
ceiling can only convert guaranteed misses into bounded fills.

The chase bound (selected + MERID_ENTRY_MAX_CHASE_CENTS) stays the outer cap —
raised to 8c in .env alongside this change (the 5c default clipped the lane's
own ~87c edge budget to 85c, one cent short of the real ask).
"""

import os
import time
from types import SimpleNamespace

import pytest

from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    _max_edge_preserving_buy_price,
    _ws_rest_divergence_guard,
)


def _taker_buy_intent(price_cents: int, basis: int, ev_net: float,
                      min_edge: float, p_selected: float) -> OrderIntent:
    intent = OrderIntent(
        ticker="KXXRP15M-TEST",
        price_cents=price_cents,
        count=1,
        side="yes",
        action="buy",
        order_type="limit",
        time_in_force="ioc",
        source="test",
    )
    intent.aggressiveness = 1.0
    intent.post_only = False
    intent.selected_outcome_price_cents = basis
    intent.ev_net_cents = ev_net
    intent.min_required_edge = min_edge
    intent.p_selected = p_selected
    return intent


def _ws_state(yes_bid: int, yes_ask: int):
    from merid.event_venues.kalshi.market_state import BookHealth
    now = time.monotonic()
    return SimpleNamespace(
        best_bid_cents=yes_bid,
        best_ask_cents=yes_ask,
        data_source="WS_ORDERBOOK_DELTA_LIVE",
        snapshot_complete=True,
        live_sequence_confirmed=True,
        book_initialized=True,
        book_health=BookHealth.LIVE,
        last_ws_update_ts=now,
        last_book_update_ts=now,
    )


class _MovingStore:
    """WS book changes between the pre-fetch snapshot and the post-fetch
    re-read, so `rest_comparable` (aligned timing proof) is False even though
    the REST leg is fresh — the exact live condition."""

    def __init__(self, first, second):
        self._states = [first, second]

    def get(self, ticker):
        return self._states.pop(0) if len(self._states) > 1 else self._states[0]

    def _validate_yes_no_invariants(self, ticker, yb, ya, nb, na):
        return True

    def _set_snapshot_complete(self, *a, **k):
        pass

    def _set_book_health(self, *a, **k):
        pass

    def _maybe_trigger_book_recovery(self, *a, **k):
        pass

    def book_state(self, ticker):
        return ""


class _StubPort:
    def __init__(self, yes_bid: int, yes_ask: int, stale: bool = False):
        self._yb = yes_bid
        self._ya = yes_ask
        self._stale = stale

    async def get_orderbook(self, ticker):
        return SimpleNamespace(
            success=True,
            yes_levels=[SimpleNamespace(price_cents=self._yb, size=100.0)],
            no_levels=[SimpleNamespace(price_cents=100 - self._ya, size=100.0)],
            timestamp=time.time() - (60.0 if self._stale else 0.0),
        )


def _patch_store(monkeypatch, store):
    import merid.event_venues.kalshi.market_state as ms
    monkeypatch.setattr(ms, "get_kalshi_market_state_store", lambda: store)


@pytest.mark.asyncio
async def test_fresh_divergent_rest_reprices_when_not_comparable(monkeypatch):
    """Live replay: WS yes=79/80 marketable, fresh REST yes=85/86, book moved
    during the fetch (non-comparable).  Guard must lift the limit into the
    edge budget instead of IOC-ing into the stale ask."""
    monkeypatch.setenv("MERID_ENTRY_MAX_CHASE_CENTS", "8")
    # pre-fetch snapshot 79/80; post-fetch re-read moved to 80/81 -> not comparable
    _patch_store(monkeypatch, _MovingStore(_ws_state(79, 80), _ws_state(80, 81)))
    intent = _taker_buy_intent(
        price_cents=80, basis=80, ev_net=-8.4, min_edge=-0.15, p_selected=0.90
    )
    epc = _max_edge_preserving_buy_price(intent)
    # lane floor -15c authorizes ~88c cap; chase bound selected+8 = 88
    assert epc is not None and epc >= 86

    port = _StubPort(85, 86)
    result = await _ws_rest_divergence_guard(intent, port, mode=None, t0=time.monotonic())
    assert result is None  # allowed
    assert intent.price_cents >= 86  # lifted to cover the real ask


@pytest.mark.asyncio
async def test_stale_rest_never_drives_cover_reprice(monkeypatch):
    """A REST leg past max_rest_age must not chase — WS stays the quote source."""
    monkeypatch.setenv("MERID_ENTRY_MAX_CHASE_CENTS", "8")
    _patch_store(monkeypatch, _MovingStore(_ws_state(79, 80), _ws_state(80, 81)))
    intent = _taker_buy_intent(
        price_cents=80, basis=80, ev_net=-8.4, min_edge=-0.15, p_selected=0.90
    )
    port = _StubPort(85, 86, stale=True)
    result = await _ws_rest_divergence_guard(intent, port, mode=None, t0=time.monotonic())
    # WS-authoritative allow at the original limit (or a clean reject — but
    # never a lift toward a stale REST quote).
    assert intent.price_cents == 80


@pytest.mark.asyncio
async def test_cover_reprice_still_bounded_by_edge_budget(monkeypatch):
    """Fresh REST ask beyond the edge budget must not be chased."""
    monkeypatch.setenv("MERID_ENTRY_MAX_CHASE_CENTS", "8")
    _patch_store(monkeypatch, _MovingStore(_ws_state(79, 80), _ws_state(80, 81)))
    intent = _taker_buy_intent(
        price_cents=80, basis=80, ev_net=-8.4, min_edge=-0.15, p_selected=0.90
    )
    epc = _max_edge_preserving_buy_price(intent) or 0
    port = _StubPort(epc + 5, epc + 6)  # real ask past the cap
    result = await _ws_rest_divergence_guard(intent, port, mode=None, t0=time.monotonic())
    assert intent.price_cents <= epc
