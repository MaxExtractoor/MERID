"""Execution gate / slippage / divergence regression tests.

These tests verify that the exit price guard rejects exits that would execute
at a price outside the configured slippage or max-loss bounds, and that stale
market data is rejected before any price-bound check.
"""

import time
from types import SimpleNamespace
import pytest

from merid.loop_15m import _run_exit_price_guard


def _make_position(market_id="KXBTC15M-TEST", entry_price=50, size=1, outcome_side="yes"):
    return SimpleNamespace(
        position_id="pos-1",
        market_id=market_id,
        avg_entry_price_cents=entry_price,
        size=size,
        outcome_side=outcome_side,
        thesis_side=outcome_side,
    )


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


def test_exit_guard_rejects_expiry_liquidation_beyond_emergency_max_loss(monkeypatch):
    """An emergency exit whose worst-case net PnL exceeds the emergency max loss is rejected."""
    # Near expiry, best bid has collapsed far below the entry.
    state = _make_state(best_bid_cents=30, seconds_to_expiry=30.0)
    _patch_get_market_state(monkeypatch, state)

    position = _make_position(entry_price=50)
    approved, approved_price, record, _ = _run_exit_price_guard(
        position=position,
        exit_reason="expiry_liquidation",
        exit_price_cents=30,
        count=1,
    )

    assert approved is False
    assert record["status"] == "rejected"
    assert record["reject_reason"] == "max_loss_exceeded"
    assert record["is_emergency"] is True


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
