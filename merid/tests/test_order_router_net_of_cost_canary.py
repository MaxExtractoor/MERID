"""Canary tests for the round-trip net-of-cost gate.

These tests prove the gate is active in paper/canary runs, rejects unprofitable
intents, defaults to maker, and refuses to trade on stale or unknown books.
"""

import time as _time
import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock

from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    _round_trip_net_of_cost_gate,
)


class _MockMarketState:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestNetOfCostCanary:
    def _intent(self, **overrides):
        defaults = {
            "ticker": "KXBTC15M-TEST-50000",
            "side": "yes",
            "action": "buy",
            "price_cents": 50,
            "count": 1,
            "count_fp": Decimal("1"),
            "edge_pct": 3.0,
            "aggressiveness": 0.0,
            "post_only": True,
        }
        defaults.update(overrides)
        return OrderIntent(**defaults)

    def _state(self, **overrides):
        defaults = {
            "best_bid_cents": 49,
            "best_ask_cents": 51,
            "book_initialized": True,
            "last_book_update_wall_ts": _time.time(),
        }
        defaults.update(overrides)
        return _MockMarketState(**defaults)

    @pytest.fixture(autouse=True)
    def _patch_store(self, monkeypatch):
        from merid.event_venues.kalshi import market_state

        class _FakeStore:
            def __init__(self, test):
                self._test = test

            def get(self, ticker):
                return getattr(self._test, "_market_state", None)

        monkeypatch.setattr(
            market_state, "get_kalshi_market_state_store", lambda: _FakeStore(self)
        )

    def test_high_edge_maker_allowed(self):
        self._market_state = self._state()
        intent = self._intent(edge_pct=10.0, aggressiveness=0.0)
        reason = _round_trip_net_of_cost_gate(intent)
        assert reason is None
        assert intent.policy_mode == "NEUTRAL_MM"

    def test_low_edge_rejected(self):
        self._market_state = self._state()
        intent = self._intent(edge_pct=0.05, aggressiveness=0.0)
        reason = _round_trip_net_of_cost_gate(intent)
        assert reason and "net_of_cost" in reason

    def test_aggressive_taker_allowed_when_profitable(self):
        self._market_state = self._state(best_bid_cents=49, best_ask_cents=50)
        intent = self._intent(edge_pct=15.0, aggressiveness=1.0, post_only=False)
        reason = _round_trip_net_of_cost_gate(intent)
        assert reason is None
        assert intent.policy_mode == "AGGRESSIVE_CONVICTION"

    def test_no_market_state_rejects(self):
        self._market_state = None
        intent = self._intent(edge_pct=3.0)
        reason = _round_trip_net_of_cost_gate(intent)
        assert reason == "net_of_cost:market_state_unavailable"

    def test_stale_book_rejects(self):
        self._market_state = self._state(
            last_book_update_wall_ts=_time.time() - 600.0
        )
        intent = self._intent(edge_pct=3.0)
        reason = _round_trip_net_of_cost_gate(intent)
        assert reason and "stale_book" in reason

    def test_locked_book_rejects(self):
        self._market_state = self._state(best_bid_cents=52, best_ask_cents=48)
        intent = self._intent(edge_pct=3.0)
        reason = _round_trip_net_of_cost_gate(intent)
        assert reason and "locked_or_crossed_book" in reason

    def test_exit_orders_bypass_gate(self):
        self._market_state = None
        intent = self._intent(
            action="sell",
            side="yes",
            is_exit_order=True,
            reduce_only=True,
            edge_pct=0.0,
        )
        reason = _round_trip_net_of_cost_gate(intent)
        assert reason is None
