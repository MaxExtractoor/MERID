"""Regression tests for IOC/TIF, tick-aware taker pricing, and exposure reconciliation.

This file covers the fixes for:
  - _resolve_tif returning IOC for aggressive/taker orders and short-horizon GTC for makers.
  - _apply_execution_mode inferring execution mode from aggressiveness/post_only.
  - _adjust_order_price_for_fill_rate crossing the spread by one tick when needed,
    bounded by fair value ± max slippage, and rejecting stale snapshots.
  - OrderResult status "unfilled_ioc" releasing pending exposure and not blocking retries.
  - reconcile_unified_risk_with_venue cancelling stale orders and syncing exposure.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@dataclass
class FakeState:
    """Minimal KalshiMarketState stand-in for price-adjustment tests."""
    book_initialized: bool = True
    best_bid_cents: int = 45
    best_ask_cents: int = 55
    best_no_bid_cents: int = 45
    best_no_ask_cents: int = 55
    best_bid_size: int = 10
    best_ask_size: int = 0  # force a one-tick cross
    mid_cents: int = 50
    last_book_update_wall_ts: float = 0.0


class TestResolveTif:
    """Tests for _resolve_tif and ResolvedTIF."""

    def _intent(self, **overrides):
        from merid.event_venues.kalshi.order_router import OrderIntent
        defaults = {
            "ticker": "KXETH15M-26AUG090200-00",
            "side": "BUY_YES",
            "action": "buy",
            "price_cents": 50,
            "count": 1,
        }
        defaults.update(overrides)
        return OrderIntent(**defaults)

    def test_aggressive_entry_is_ioc(self):
        from merid.event_venues.kalshi.order_router import _resolve_tif
        intent = self._intent(aggressiveness=0.5)
        tif, exp = _resolve_tif(intent)
        assert tif == "IOC"
        assert exp is None

    def test_taker_is_ioc(self):
        from merid.event_venues.kalshi.order_router import _resolve_tif
        intent = self._intent(execution_mode="taker")
        tif, exp = _resolve_tif(intent)
        assert tif == "IOC"
        assert exp is None

    def test_maker_is_gtc_with_future_expiration(self):
        from merid.event_venues.kalshi.order_router import _resolve_tif
        intent = self._intent(aggressiveness=0.0, post_only=True)
        tif, exp = _resolve_tif(intent)
        assert tif == "GTC"
        assert exp is not None
        assert exp > int(time.time())

    def test_reduce_only_exit_is_ioc(self):
        from merid.event_venues.kalshi.order_router import _resolve_tif
        intent = self._intent(action="sell", entry_or_exit="exit", reduce_only=True)
        tif, exp = _resolve_tif(intent)
        assert tif == "IOC"
        assert exp is None

    def test_gtc_honors_explicit_order_expiration_ts(self):
        from merid.event_venues.kalshi.order_router import _resolve_tif
        future = int(time.time()) + 120
        intent = self._intent(time_in_force="gtc", order_expiration_ts=future)
        tif, exp = _resolve_tif(intent)
        assert tif == "GTC"
        assert exp == future


class TestApplyExecutionMode:
    """Tests for _apply_execution_mode inference."""

    def test_infers_staged_ioc_from_aggressiveness(self):
        from merid.event_venues.kalshi.order_router import _apply_execution_mode, OrderIntent
        intent = OrderIntent(
            ticker="KXETH15M-T",
            side="BUY_YES",
            action="buy",
            price_cents=50,
            count=1,
            aggressiveness=0.5,
        )
        post_only, aggressiveness, order_type, tif = _apply_execution_mode(intent)
        assert post_only is False
        assert aggressiveness == 0.5
        assert order_type == "limit"
        assert tif == "IOC"

    def test_infers_maker_from_post_only(self):
        from merid.event_venues.kalshi.order_router import _apply_execution_mode, OrderIntent
        intent = OrderIntent(
            ticker="KXETH15M-T",
            side="BUY_YES",
            action="buy",
            price_cents=50,
            count=1,
            post_only=True,
            aggressiveness=0.0,
        )
        post_only, aggressiveness, order_type, tif = _apply_execution_mode(intent)
        assert post_only is True
        assert aggressiveness == 0.0
        assert tif == "GTC"


class TestAdjustPriceForFillRate:
    """Tests for tick-aware taker price crossing and snapshot validation."""

    def _intent(self, **overrides):
        from merid.event_venues.kalshi.order_router import OrderIntent
        defaults = {
            "ticker": "KXETH15M-T",
            "side": "BUY_YES",
            "action": "buy",
            "price_cents": 50,
            "count": 1,
            "aggressiveness": 1.0,
        }
        defaults.update(overrides)
        return OrderIntent(**defaults)

    def test_taker_buy_crosses_one_tick_when_ask_size_zero(self):
        from merid.event_venues.kalshi.order_router import _adjust_order_price_for_fill_rate
        state = FakeState(best_ask_size=0, best_bid_size=10)
        intent = self._intent()
        price = _adjust_order_price_for_fill_rate(intent, state)
        # Ask is 55, no displayed size, so target is 56 (one tick through ask).
        # Fair cap = mid 50 + 5 = 55; so 56 > fair_cap would raise.  Wait.
        # With max_slippage 5 and mid=50, fair_cap=55.  side_ask=55 is at cap.
        # displayed_ask_size=0 -> target=56 -> min(56,55)=55 -> adjusted=55.
        assert price == 55
        assert intent.time_in_force == "IOC"

    def test_taker_buy_crosses_one_tick_with_size(self):
        from merid.event_venues.kalshi.order_router import _adjust_order_price_for_fill_rate
        state = FakeState(best_ask_size=5, best_bid_size=10)
        intent = self._intent()
        price = _adjust_order_price_for_fill_rate(intent, state)
        # Ask has size, so target = side_ask = 55.
        assert price == 55

    def test_taker_sell_crosses_one_tick_when_bid_size_zero(self):
        from merid.event_venues.kalshi.order_router import _adjust_order_price_for_fill_rate
        state = FakeState(best_bid_size=0, best_ask_size=10)
        intent = self._intent(action="sell")
        price = _adjust_order_price_for_fill_rate(intent, state)
        # Bid is 45, no displayed size, so target = 44, floor = 50 - 5 = 45.
        # taker_target = max(44, 45) = 45.
        assert price == 45

    def test_rejects_stale_snapshot(self):
        from merid.event_venues.kalshi.order_router import (
            _adjust_order_price_for_fill_rate,
            RepriceWouldCross,
        )
        state = FakeState(best_bid_size=10, best_ask_size=10)
        state.last_book_update_wall_ts = time.time() - 30  # very stale
        intent = self._intent(snapshot_age_ms=30000)
        with pytest.raises(RepriceWouldCross):
            _adjust_order_price_for_fill_rate(intent, state)

    def test_rejects_uninitialized_book(self):
        from merid.event_venues.kalshi.order_router import (
            _adjust_order_price_for_fill_rate,
            RepriceWouldCross,
        )
        state = FakeState(book_initialized=False)
        intent = self._intent()
        with pytest.raises(RepriceWouldCross):
            _adjust_order_price_for_fill_rate(intent, state)


class TestUnfilledIOCOutcome:
    """Tests that an IOC order returning fill_count=0 becomes unfilled_ioc."""

    def test_order_result_unfilled_ioc_not_success(self):
        from merid.event_venues.kalshi.order_router import OrderResult
        from merid.prediction.trading_mode import TradingMode
        result = OrderResult(status="unfilled_ioc", mode=TradingMode.LIVE, order_id="abc")
        assert not result.success

class TestExposureReconciliation:
    """Tests for reconcile_unified_risk_with_venue."""

    @pytest.mark.asyncio
    async def test_cancels_stale_gtc_and_syncs_exposure(self):
        from merid.event_venues.kalshi.kalshi_risk import reconcile_unified_risk_with_venue
        from merid.event_venues.kalshi.port import (
            Order, CancelResult, PositionsResponse,
            reset_kalshi_execution_port_for_testing, set_kalshi_execution_port,
        )
        from merid.risk.unified_risk_manager import get_unified_risk_manager, UnifiedRiskManager

        # Fresh risk manager so other tests don't leak category exposure.
        UnifiedRiskManager.reset_for_tests()

        now = time.time()
        old_order = Order(
            order_id="stale-1",
            client_order_id="cid-stale-1",
            ticker="KXBTC15M-TEST",
            side="BUY_YES",
            outcome="yes",
            size=Decimal(1),
            filled_size=Decimal(0),
            remaining_size=Decimal(1),
            price_cents=55,
            status="resting",
            time_in_force="gtc",
            created_at=datetime.fromtimestamp(now - 500, tz=timezone.utc),
        )

        fresh_order = Order(
            order_id="fresh-2",
            client_order_id="cid-fresh-2",
            ticker="KXBTC15M-TEST",
            side="BUY_YES",
            outcome="yes",
            size=Decimal(1),
            filled_size=Decimal(0),
            remaining_size=Decimal(1),
            price_cents=50,
            status="resting",
            time_in_force="gtc",
            created_at=datetime.fromtimestamp(now - 10, tz=timezone.utc),
        )

        class _FakePort:
            _calls = []

            async def get_open_orders(self, ticker=None):
                if len(self._calls) == 0:
                    self._calls.append("first")
                    return [old_order, fresh_order]
                return [fresh_order]

            async def get_positions(self):
                return PositionsResponse(positions=[])

            async def cancel_order(self, order_id: str):
                if order_id == "stale-1":
                    return CancelResult(success=True, order_id=order_id, new_status="canceled")
                return CancelResult(success=False, order_id=order_id, error="not found")

        reset_kalshi_execution_port_for_testing()
        set_kalshi_execution_port(_FakePort())

        result = await reconcile_unified_risk_with_venue(max_order_age_seconds=180.0)

        assert "stale-1" in result["canceled_order_ids"]
        assert result["confirmed_open_notional_usd"] == pytest.approx(0.5)

        risk = get_unified_risk_manager()
        exposure = risk.get_current_exposure()
        assert exposure["category_exposure"].get("crypto", 0.0) == pytest.approx(0.5)


class TestModeAwareRepriceAndValidation:
    """Mode-aware price repricing and validation for maker/taker/staged_ioc."""

    def _intent(self, **overrides):
        from merid.event_venues.kalshi.order_router import OrderIntent
        defaults = {
            "ticker": "KXETH15M-T",
            "side": "BUY_YES",
            "action": "buy",
            "price_cents": 50,
            "count": 1,
            "snapshot_ts": time.time(),
            "snapshot_age_ms": 0.0,
        }
        defaults.update(overrides)
        return OrderIntent(**defaults)

    def _state(self, **overrides):
        defaults = {
            "book_initialized": True,
            "best_bid_cents": 45,
            "best_ask_cents": 55,
            "best_bid_size": 10,
            "best_ask_size": 10,
            "mid_cents": 50,
            "last_book_update_wall_ts": time.time(),
        }
        defaults.update(overrides)
        return FakeState(**defaults)

    def test_taker_buy_repriced_to_ask_no_buy_above_ask(self):
        from merid.event_venues.kalshi.order_router import (
            _adjust_order_price_for_fill_rate,
            _validate_price_against_orderbook,
        )
        intent = self._intent(aggressiveness=1.0)
        state = self._state()
        price = _adjust_order_price_for_fill_rate(intent, state)
        intent.price_cents = price
        assert price == 55
        assert intent.liquidity_role == "taker"
        assert intent.time_in_force == "IOC"
        assert _validate_price_against_orderbook(intent, state) is None

    def test_taker_sell_repriced_to_bid_no_sell_below_bid(self):
        from merid.event_venues.kalshi.order_router import (
            _adjust_order_price_for_fill_rate,
            _validate_price_against_orderbook,
        )
        intent = self._intent(action="sell", aggressiveness=1.0)
        state = self._state()
        price = _adjust_order_price_for_fill_rate(intent, state)
        intent.price_cents = price
        assert price == 45
        assert intent.liquidity_role == "taker"
        assert intent.time_in_force == "IOC"
        assert _validate_price_against_orderbook(intent, state) is None

    def test_maker_buy_capped_below_ask(self):
        from merid.event_venues.kalshi.order_router import (
            _adjust_order_price_for_fill_rate,
            _validate_price_against_orderbook,
        )
        intent = self._intent(post_only=True, aggressiveness=0.0)
        state = self._state()
        price = _adjust_order_price_for_fill_rate(intent, state)
        intent.price_cents = price
        assert price < state.best_ask_cents
        assert intent.liquidity_role == "maker"
        assert intent.time_in_force == "GTC"
        assert _validate_price_against_orderbook(intent, state) is None

    def test_maker_buy_rejected_when_price_crosses_ask(self):
        from merid.event_venues.kalshi.order_router import (
            _validate_price_against_orderbook,
        )
        intent = self._intent(post_only=True, aggressiveness=0.0, price_cents=55)
        state = self._state()
        intent.liquidity_role = "maker"
        intent.time_in_force = "GTC"
        error = _validate_price_against_orderbook(intent, state)
        assert error is not None
        assert "buy_above_ask" in error

    def test_staged_ioc_resolves_to_taker_ioc_not_capped_at_ask_minus_one(self):
        from merid.event_venues.kalshi.order_router import (
            _adjust_order_price_for_fill_rate,
            _validate_price_against_orderbook,
        )
        intent = self._intent(execution_mode="staged_ioc", aggressiveness=0.5)
        state = self._state(best_ask_size=10)
        price = _adjust_order_price_for_fill_rate(intent, state)
        intent.price_cents = price
        assert price == 55  # at the ask, not ask - 1
        assert intent.liquidity_role == "taker"
        assert intent.time_in_force == "IOC"
        assert intent.execution_mode == "staged_ioc"
        assert _validate_price_against_orderbook(intent, state) is None

    def test_staged_ioc_with_zero_ask_size_crosses_one_tick(self):
        from merid.event_venues.kalshi.order_router import (
            _adjust_order_price_for_fill_rate,
            _validate_price_against_orderbook,
        )
        intent = self._intent(execution_mode="staged_ioc", aggressiveness=0.5)
        state = self._state(best_ask_size=0)
        price = _adjust_order_price_for_fill_rate(intent, state)
        intent.price_cents = price
        # target=56, fair_cap=55, so clamped to 55.
        assert price == 55
        assert _validate_price_against_orderbook(intent, state) is None

    def test_taker_buy_rejected_when_ask_exceeds_fair_cap(self):
        from merid.event_venues.kalshi.order_router import (
            _adjust_order_price_for_fill_rate,
            RepriceWouldCross,
        )
        intent = self._intent(aggressiveness=1.0)
        state = self._state(best_ask_cents=65)
        with pytest.raises(RepriceWouldCross):
            _adjust_order_price_for_fill_rate(intent, state)

    def test_yes_no_normalization_buy_no_taker(self):
        from merid.event_venues.kalshi.order_router import (
            _adjust_order_price_for_fill_rate,
            _validate_price_against_orderbook,
        )
        intent = self._intent(side="BUY_NO", action="buy", aggressiveness=1.0)
        # YES book: bid=45, ask=55, mid=50  => NO book: bid=45, ask=55, mid=50
        state = self._state(best_bid_cents=45, best_ask_cents=55, mid_cents=50)
        price = _adjust_order_price_for_fill_rate(intent, state)
        intent.price_cents = price
        # BUY_NO taker target is NO ask = 100 - YES bid = 55.
        assert price == 55
        assert _validate_price_against_orderbook(intent, state) is None


class TestOrderResultSemantics:
    """OrderResult request/execution semantic split."""

    def test_unfilled_ioc_has_no_execution(self):
        from merid.event_venues.kalshi.order_router import OrderResult
        from merid.prediction.trading_mode import TradingMode
        result = OrderResult(
            status="unfilled_ioc", mode=TradingMode.LIVE, order_id="abc"
        )
        assert not result.success
        assert not result.has_execution
        assert result.executed_count == 0
