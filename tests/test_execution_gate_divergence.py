"""Execution gate / slippage / divergence regression tests.

These tests verify that the exit price guard rejects exits that would execute
at a price outside the configured slippage or max-loss bounds, and that stale
market data is rejected before any price-bound check.
"""

import time
from types import SimpleNamespace
import pytest

from merid.loop_15m import _run_exit_price_guard
from merid.event_venues.kalshi.position_cache import get_position_cache


def _make_position(market_id="KXBTC15M-TEST", entry_price=50, size=1, outcome_side="yes"):
    pos = SimpleNamespace(
        position_id="pos-1",
        market_id=market_id,
        avg_entry_price_cents=entry_price,
        size=size,
        outcome_side=outcome_side,
        thesis_side=outcome_side,
    )

    # 2026-08-30: _run_exit_price_guard is fail-closed on the canonical position
    # cache.  Unit tests must seed the cache with the same position the guard is
    # asked to evaluate, otherwise it rejects every close as flat/missing.
    pos._yes_exposure = lambda: int(size * 100) if outcome_side == "yes" else -int(size * 100)
    get_position_cache()._positions[market_id] = pos
    return pos


def _make_state(best_bid_cents: int, age_ms: int = 0, seconds_to_expiry: float = 600.0):
    return SimpleNamespace(
        best_bid_cents=best_bid_cents,
        best_ask_cents=best_bid_cents + 2,
        last_book_update_ts=time.monotonic() - (age_ms / 1000.0),
        seconds_to_expiry=seconds_to_expiry,
        book_source="ws_test",
    )


def _patch_get_market_state(monkeypatch, state):
    """Make stop_candidate._get_market_state return the supplied test state."""
    monkeypatch.setattr(
        "merid.event_venues.kalshi.stop_candidate._get_market_state",
        lambda _ticker: (state, None),
    )


def test_exit_guard_allows_profitable_take_profit(monkeypatch):
    """A fresh, profitable take-profit within slippage (zero) and profit floor is approved."""
    state = _make_state(best_bid_cents=60)  # 10c gross, well above fees + profit floor
    _patch_get_market_state(monkeypatch, state)

    position = _make_position(entry_price=50)
    approved, approved_price, record, _ = _run_exit_price_guard(
        position=position,
        exit_reason="take_profit",
        exit_price_cents=60,
        count=1,
    )

    assert approved is True, f"expected approval, got {record.get('reject_reason')}"
    assert record["status"] == "approved"
    assert record["best_bid_cents"] == 60


def test_exit_guard_rejects_stop_loss_beyond_max_loss(monkeypatch):
    """A discretionary stop whose worst-case net PnL exceeds the max loss bound is rejected."""
    # The market has fallen far below the entry; without a stop_price on the
    # position the guard falls back to the global max-loss bound.
    state = _make_state(best_bid_cents=30)
    _patch_get_market_state(monkeypatch, state)

    position = _make_position(entry_price=50)
    approved, approved_price, record, _ = _run_exit_price_guard(
        position=position,
        exit_reason="stop_loss",
        exit_price_cents=30,
        count=1,
    )

    assert approved is False
    assert record["status"] == "rejected"
    assert record["reject_reason"] == "max_loss_exceeded"


def test_exit_guard_rejects_stale_quote(monkeypatch):
    """A stale market quote is rejected before any price-bound check."""
    state = _make_state(best_bid_cents=60, age_ms=999_999)
    _patch_get_market_state(monkeypatch, state)

    position = _make_position(entry_price=50)
    approved, approved_price, record, _ = _run_exit_price_guard(
        position=position,
        exit_reason="take_profit",
        exit_price_cents=60,
        count=1,
    )

    assert approved is False
    assert record["status"] == "rejected"
    assert record["reject_reason"] == "stale_quote"
