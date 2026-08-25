"""Order-router safety tests (2026-08-10).

Covers:
- Canonical signed-YES exit detection (no raw side/action heuristics)
- IOC worst-case executable fill exposure cap
- NO-side price adjustment spread/crossing in canonical YES space
"""

import time
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    _adjust_order_price_for_fill_rate,
    _is_exit_order,
    _prepare_order_for_gate,
    RepriceWouldCross,
)
from merid.prediction.trading_mode import TradingMode
from merid.event_venues.kalshi.position_cache import CachedPosition, get_position_cache


def _state(**overrides):
    defaults = dict(
        book_initialized=True,
        executable=True,
        book_age_s=0.0,
        book_updated_ts=time.time(),
        last_book_update_ts=time.time(),
        last_rest_update_ts=time.time(),
        mid_cents=50,
        best_bid_cents=45,
        best_ask_cents=55,
        best_bid_size=10,
        best_ask_size=10,
        best_no_bid_cents=None,
        best_no_ask_cents=None,
        depth_10c=100,
        yes_depth=100,
        no_depth=100,
        sequence=1,
        seconds_to_expiry=900,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _intent(**overrides):
    defaults = dict(
        ticker="KXBTC15M-TEST",
        side="BUY_YES",
        action="buy",
        price_cents=50,
        count=1,
        mode=TradingMode.LIVE,
        order_type="limit",
        time_in_force="gtc",
        edge_pct=5.0,
        aggressiveness=0.0,
        post_only=False,
        snapshot_ts=time.time(),
        snapshot_age_ms=0.0,
        model_prob=0.55,
        source="agent_grid_15m",
        agent_id="BTC_15M",
        group_id="BTC-15m-test",
        take_profit_price_cents=60,
        stop_loss_price_cents=40,
        confidence=0.5,
    )
    defaults.update(overrides)
    return OrderIntent(**defaults)


@pytest.fixture(autouse=True)
def _clear_position_cache():
    cache = get_position_cache()
    cache.clear_sync()
    yield
    cache.clear_sync()


class TestSignedYesExitDetection:
    def test_sell_no_with_long_no_position_is_exit(self):
        cache = get_position_cache()
        cache._positions["KXBTC15M-TEST"] = CachedPosition(
            market_id="KXBTC15M-TEST",
            agent_id="BTC_15M",
            contracts=10,
            side="no",
            thesis_side="no",
            avg_price_cents=50,
            quantity_cc=1000,
        )
        intent = _intent(side="SELL_NO", action="sell", count=10, source="agent_grid_15m")
        assert _is_exit_order(intent) is True

    def test_sell_no_without_position_is_entry(self):
        intent = _intent(side="SELL_NO", action="sell", count=10, source="agent_grid_15m")
        assert _is_exit_order(intent) is False

    def test_sell_yes_with_long_yes_position_is_exit(self):
        cache = get_position_cache()
        cache._positions["KXBTC15M-TEST"] = CachedPosition(
            market_id="KXBTC15M-TEST",
            agent_id="BTC_15M",
            contracts=10,
            side="yes",
            thesis_side="yes",
            avg_price_cents=50,
            quantity_cc=1000,
        )
        intent = _intent(side="SELL_YES", action="sell", count=10, source="agent_grid_15m")
        assert _is_exit_order(intent) is True

    def test_buy_no_with_long_yes_position_is_exit(self):
        cache = get_position_cache()
        cache._positions["KXBTC15M-TEST"] = CachedPosition(
            market_id="KXBTC15M-TEST",
            agent_id="BTC_15M",
            contracts=10,
            side="yes",
            thesis_side="yes",
            avg_price_cents=50,
            quantity_cc=1000,
        )
        # BUY NO on a long YES position reduces YES exposure -> exit.
        intent = _intent(side="BUY_NO", action="buy", count=10, source="agent_grid_15m")
        assert _is_exit_order(intent) is True

    def test_buy_yes_with_long_yes_position_is_entry(self):
        cache = get_position_cache()
        cache._positions["KXBTC15M-TEST"] = CachedPosition(
            market_id="KXBTC15M-TEST",
            agent_id="BTC_15M",
            contracts=10,
            side="yes",
            thesis_side="yes",
            avg_price_cents=50,
            quantity_cc=1000,
        )
        intent = _intent(side="BUY_YES", action="buy", count=1, source="agent_grid_15m")
        assert _is_exit_order(intent) is False

    def test_exit_markers_still_classify_without_position(self):
        # Explicit markers still classify as exit even without a position lookup.
        intent = _intent(side="SELL_YES", action="sell", count=1, source="position_monitor_exit")
        assert _is_exit_order(intent) is True


class TestIocWorstCaseExposureCap:
    @pytest.fixture(autouse=True)
    def _router_patches(self, monkeypatch):
        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_router._apply_risk_based_order_sizing",
            lambda intent, bankroll_usd=None: 1,
        )
        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_router._apply_depth_based_order_sizing",
            lambda intent, state=None: 1,
        )
        monkeypatch.setattr(
            "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
            lambda: MagicMock(
                get=MagicMock(return_value=_state()),
                is_market_entry_ready=MagicMock(return_value=(True, None)),
            ),
        )
        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_router.get_venue_gate",
            lambda: MagicMock(mode=TradingMode.LIVE, live_enabled=True),
        )

    def test_ioc_taker_rejected_when_adjusted_price_exceeds_cap(self):
        from merid.risk.global_slot_allocator import get_global_slot_allocator
        allocator = get_global_slot_allocator()
        allocator._slots.clear()
        # Fake an existing slot with $0.60 exposure so the $1.00 cap is nearly full.
        allocator._slots["slot-1"] = MagicMock(exposure_usd=0.60, asset="BTC", agent_id="BTC_15M")
        try:
            intent = _intent(
                side="BUY_YES", action="buy", price_cents=50, count=1,
                execution_mode="taker", aggressiveness=1.0, time_in_force="ioc",
            )
            result, _ = _prepare_order_for_gate(intent, TradingMode.LIVE, time.monotonic())
            assert result is not None
            assert result.status == "rejected"
            assert "executable_worst_case" in result.reason or "slot_allocator_executable" in result.reason
        finally:
            allocator._slots.clear()

    def test_maker_gtc_within_cap_is_allowed(self):
        from merid.risk.global_slot_allocator import get_global_slot_allocator
        allocator = get_global_slot_allocator()
        allocator._slots.clear()
        intent = _intent(
            side="BUY_YES", action="buy", price_cents=50, count=1,
            execution_mode="maker", aggressiveness=0.0, post_only=True,
        )
        result, _ = _prepare_order_for_gate(intent, TradingMode.LIVE, time.monotonic())
        assert result is None


class TestNoSidePriceAdjustment:
    def test_buy_no_taker_adjusts_to_no_ask(self):
        intent = _intent(
            side="BUY_NO", action="buy", price_cents=50, count=1,
            execution_mode="taker", aggressiveness=1.0,
        )
        price = _adjust_order_price_for_fill_rate(intent, _state())
        assert price == 55  # NO ask = 100 - YES bid = 55

    def test_sell_no_taker_adjusts_to_no_bid(self):
        intent = _intent(
            side="SELL_NO", action="sell", price_cents=50, count=1,
            execution_mode="taker", aggressiveness=1.0,
        )
        price = _adjust_order_price_for_fill_rate(intent, _state())
        assert price == 45  # NO bid = 100 - YES ask = 45

    def test_buy_no_maker_stays_below_no_ask(self):
        intent = _intent(
            side="BUY_NO", action="buy", price_cents=40, count=1,
            execution_mode="maker", aggressiveness=0.0, post_only=True,
        )
        price = _adjust_order_price_for_fill_rate(intent, _state())
        assert price < 55  # NO ask

    def test_crossed_yes_book_rejected_before_transformation(self):
        state = _state(best_bid_cents=60, best_ask_cents=50)  # crossed YES book
        intent = _intent(
            side="BUY_NO", action="buy", price_cents=50, count=1,
            execution_mode="taker", aggressiveness=1.0,
        )
        with pytest.raises(RepriceWouldCross):
            _adjust_order_price_for_fill_rate(intent, state)
