"""Strict-passivity evaluation for post_only orders (2026-09-29).

Covers ``_post_only_strict_passivity``: maker orders whose limit would cross
a fresh BBO are repriced to the nearest strictly-passive price inside the
signal's edge budget, or rejected when no in-budget passive price exists.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    _post_only_strict_passivity,
)


def _intent(**kw):
    base = dict(
        ticker="KXDOGE15M-T",
        price_cents=51,
        count=1,
        side="no",
        action="buy",
        execution_mode="maker",
        post_only=True,
        selected_outcome_price_cents=51,
        ev_net_cents=5.0,
        fee_cents=0.5,
    )
    base.update(kw)
    return OrderIntent(**base)


def test_passive_buy_untouched():
    px, rej = _post_only_strict_passivity(
        _intent(), {"bid_cents": 49, "ask_cents": 52}
    )
    assert px is None and rej is None


def test_crossing_buy_repriced_to_strictly_passive():
    # Buy at 51 while ask=50 -> crosses.  Strict passive = ask-1 = 49.
    px, rej = _post_only_strict_passivity(
        _intent(price_cents=51), {"bid_cents": 48, "ask_cents": 50}
    )
    assert rej is None
    assert px == 49


def test_crossing_buy_at_touch_counts_as_cross():
    # Buy at exactly the ask is marketable on Kalshi -> reprice down one tick.
    px, rej = _post_only_strict_passivity(
        _intent(price_cents=50), {"bid_cents": 48, "ask_cents": 50}
    )
    assert rej is None
    assert px == 49


def test_crossing_buy_over_budget_rejected():
    # selected_outcome_price=20 -> chase cap = 25; ask-1 = 49 > 25.
    px, rej = _post_only_strict_passivity(
        _intent(price_cents=51, selected_outcome_price_cents=20),
        {"bid_cents": 48, "ask_cents": 50},
    )
    assert px is None
    assert rej is not None and "over_budget" in rej


def test_crossing_buy_no_passive_price():
    px, rej = _post_only_strict_passivity(
        _intent(price_cents=5), {"bid_cents": 1, "ask_cents": 1}
    )
    assert px is None
    assert rej is not None and "no_passive_price" in rej


def test_passive_sell_untouched():
    px, rej = _post_only_strict_passivity(
        _intent(action="sell", price_cents=60), {"bid_cents": 50, "ask_cents": 55}
    )
    assert px is None and rej is None


def test_crossing_sell_repriced():
    px, rej = _post_only_strict_passivity(
        _intent(action="sell", price_cents=45), {"bid_cents": 50, "ask_cents": 55}
    )
    assert rej is None
    assert px == 51


def test_missing_book_fields_noop():
    px, rej = _post_only_strict_passivity(
        _intent(), {"bid_cents": None, "ask_cents": None}
    )
    assert px is None and rej is None
