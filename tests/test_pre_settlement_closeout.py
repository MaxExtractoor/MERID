import asyncio
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from merid.event_venues.kalshi import order_router as router
from merid.event_venues.kalshi.settlement_aligned_exit import pre_settlement_closeout_due
from merid.event_venues.kalshi.stop_candidate import loss_sell_blocked
from merid.position_management import position_monitor as pm
from merid.position_management.exit_audit import ExitPriceSnapshot
from merid.position_management.exit_policy import ExitReason
from merid.position_management.position import Position, PositionSide
from merid.prediction.venue_gate import TradingMode


@pytest.mark.parametrize("remaining,expected", [(120, True), (60, True), (0.01, True), (121, False), (0, False), (-1, False), (None, False), ("NaN", False), ("Infinity", False), ("bad", False)])
def test_closeout_deadline(remaining, expected):
    assert pre_settlement_closeout_due(remaining) is expected


def _intent(**kwargs):
    return router.OrderIntent(ticker="KXBTC15M-26NOV101200-00", side="yes", action="buy", price_cents=50, count=4, **kwargs)


@pytest.fixture
def expiry_clock(monkeypatch):
    from merid.event_venues.kalshi.expiry_fallback import parse_kalshi_15m_window_end_utc
    expiry = int(parse_kalshi_15m_window_end_utc(_intent().ticker).timestamp())
    monkeypatch.setattr(router, "_now_unix_s", lambda: expiry - 300)
    return expiry


@pytest.mark.parametrize("lane", ["cheap_no_settle", "settlement_convergence"])
def test_settlement_lanes_rejected(expiry_clock, lane):
    assert router._pre_settlement_entry_denial(_intent(decision_lane=lane)) == "settlement_lane_incompatible_with_closeout"


@pytest.mark.parametrize("remaining,denied", [(151, False), (150, True), (120, True), (0, True), (-1, True)])
def test_no_new_entries_at_deadline(monkeypatch, expiry_clock, remaining, denied):
    monkeypatch.setattr(router, "_now_unix_s", lambda: expiry_clock - remaining)
    reason = router._pre_settlement_entry_denial(_intent())
    assert (reason == "pre_settlement_entry_deadline") is denied


@pytest.mark.parametrize("expiration", [None, 9999999999])
def test_resting_entries_expire_before_closeout(expiry_clock, expiration):
    intent = _intent(order_expiration_ts=expiration, max_rest_seconds=600)
    assert router._resolve_gtc_expiration(intent) == expiry_clock - 120


def test_exit_is_exempt_from_entry_deadline(expiry_clock):
    intent = _intent(reduce_only=True, entry_or_exit="exit")
    assert router._pre_settlement_entry_denial(intent) is None


def test_invalid_deadline_plan_rejected():
    plan = router.PositionLifecyclePlan(closeout_seconds_before_expiry=0)
    assert router._validate_lifecycle_plan(plan) == "invalid_pre_settlement_deadline"
    plan = router.PositionLifecyclePlan(hold_to_settlement_enabled=True)
    assert router._validate_lifecycle_plan(plan) == "intentional_settlement_not_allowed"


def test_derived_plan_requires_closeout():
    plan = router.derive_lifecycle_plan(_intent())
    assert plan.exit_mode == "PRE_SETTLEMENT_CLOSEOUT"
    assert plan.closeout_seconds_before_expiry == 120
    assert not plan.hold_to_settlement_enabled
    assert router._validate_lifecycle_plan(plan) is None


def test_disabled_exit_policy_still_derives_closeout(monkeypatch):
    monkeypatch.setenv("MERID_DISABLE_EXIT_POLICY", "1")
    monkeypatch.setenv("MERID_PROFIT_ONLY_EXITS", "1")
    policy = router.resolve_exit_policy(edge_result=None, asset="BTC", regime="normal")
    assert policy.mode == "PRE_SETTLEMENT_CLOSEOUT"
    intent = _intent(exit_policy=router.exit_policy_to_dict(policy))
    plan = router.derive_lifecycle_plan(intent)
    assert plan.exit_mode == "PRE_SETTLEMENT_CLOSEOUT"
    assert plan.hold_to_settlement_enabled is False
    assert router._validate_lifecycle_plan(plan) is None


@pytest.mark.parametrize("reason", [ExitReason.SETTLEMENT_GUARD, "EXPIRY_LIQUIDATION"])
def test_deadline_bypasses_profit_floor(monkeypatch, reason):
    monkeypatch.setenv("MERID_PROFIT_ONLY_EXITS", "1")
    monkeypatch.setenv("MERID_LOSS_EXITS_ENABLED", "0")
    assert not loss_sell_blocked(reason, 1, 90, hold_value_cents=99, peak_price_cents=99, entry_edge=0.2)
    assert loss_sell_blocked("TAKE_PROFIT", 1, 90)


def _position():
    return Position(position_id="closeout-position", market_id=_intent().ticker, side=PositionSide.YES, size=4, avg_entry_price_cents=50)


def _snapshot(position):
    return ExitPriceSnapshot(market_id=position.market_id, position_side=position.side, mid_cents=10, own_side_bid_cents=10, own_side_ask_cents=12, opposite_bid_cents=88, opposite_ask_cents=90, book_age_ms=0, data_source="ws", data_quality="GOOD", executable=True, has_bid_size=True, snapshot_id="closeout-book", seconds_to_expiry=100)


def test_monitor_emits_full_closeout_before_other_candidates(monkeypatch):
    monkeypatch.setattr(pm, "_seconds_to_expiry_from_ticker", lambda _: 100)
    monitor = object.__new__(pm.PositionMonitor)
    monitor._is_exit_intent_in_flight = Mock(return_value=False)
    monitor._emit_exit_intent = AsyncMock()
    position = _position()
    position.decision_lane = "cheap_no_settle"
    position.exit_triggered = True
    position.exit_reason = "scale_out"
    position.size = 1
    snapshot = _snapshot(position)
    decision = asyncio.run(monitor._check_position(position, snapshot))
    assert decision.reason == ExitReason.SETTLEMENT_GUARD
    assert decision.contracts_to_close is None
    assert not position.exit_triggered
    monitor._emit_exit_intent.assert_awaited_once()
    args, kwargs = monitor._emit_exit_intent.await_args
    assert args == (position, ExitReason.SETTLEMENT_GUARD, 10)
    assert kwargs["snapshot"] is snapshot


def test_confirmed_flat_position_not_rearmed(monkeypatch):
    monitor = object.__new__(pm.PositionMonitor)
    monitor._emit_exit_intent = AsyncMock()
    position = _position()
    position.size = 0
    assert asyncio.run(monitor._check_position(position, _snapshot(position))) is None
    monitor._emit_exit_intent.assert_not_awaited()


def test_live_scaling_fails_closed_without_child_submission(monkeypatch):
    route = AsyncMock()
    monkeypatch.setattr(router, "_route_live", route)
    result = asyncio.run(router._execute_scaled_order(_intent(scaling_enabled=True), TradingMode.LIVE, time.monotonic()))
    assert result.status == "rejected"
    assert result.reason == "scaled_live_execution_not_validated"
    route.assert_not_awaited()
