"""Tests for the end-to-end disabling of stop-loss and loss-cap exits.

Verifies that when MERID_DISABLE_LOSS_STOPS=1:
1. Upstream: LiveConfig, Position, and contract gates reflect disabled stops.
2. Midstream: PositionMonitor tail-loss floor, residual-runner floor, and
   stop-loss evaluation are suppressed.
3. Downstream: StopCandidate submission for price/loss/thesis stops returns None,
   loss-sell floor salvage exemptions are removed, and OrderRouter rejects any
   stop-loss exit order attempt with "stop_loss_disabled_by_policy" while preserving
   take-profit, settlement, and operational safety exits.
"""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.kalshi.stop_candidate import (
    LOSS_STOP_TRIGGER_REASONS,
    StopCandidate,
    loss_stops_disabled,
    loss_exits_enabled,
    no_edge_loss_salvage_enabled,
    model_edge_tail_floor_salvage_enabled,
    _maybe_submit_stop_candidate_impl,
    resolve_loss_sell_floor,
)
from merid.position_management.position_monitor import (
    _get_tail_loss_floor_config,
    _residual_runner_floor_enabled,
    PositionMonitor,
)
from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    OrderResult,
    TradingMode,
    _is_stop_loss_exit_denied,
    _route_live,
)


@pytest.fixture(autouse=True)
def enable_disable_loss_stops(monkeypatch):
    """Enable MERID_DISABLE_LOSS_STOPS by default for this audit test suite."""
    monkeypatch.setenv("MERID_DISABLE_LOSS_STOPS", "1")


def test_loss_stops_disabled_flag(monkeypatch):
    """loss_stops_disabled() returns True when env var is set."""
    assert loss_stops_disabled() is True

    monkeypatch.setenv("MERID_DISABLE_LOSS_STOPS", "0")
    assert loss_stops_disabled() is False


def test_salvage_carveouts_overridden_when_stops_disabled(monkeypatch):
    """Even if salvage flags are requested on, loss_stops_disabled() force-disables them."""
    monkeypatch.setenv("MERID_LOSS_EXITS_ENABLED", "1")
    monkeypatch.setenv("MERID_NO_EDGE_LOSS_SALVAGE_ENABLED", "1")
    monkeypatch.setenv("MERID_MODEL_EDGE_TAIL_FLOOR_SALVAGE_ENABLED", "1")

    assert loss_exits_enabled() is False
    assert no_edge_loss_salvage_enabled() is False
    assert model_edge_tail_floor_salvage_enabled() is False


def test_position_monitor_tail_loss_floor_config(monkeypatch):
    """Tail-loss floor is disabled when MERID_DISABLE_LOSS_STOPS=1."""
    monkeypatch.setenv("MERID_TAIL_LOSS_ENABLED", "1")
    cfg = _get_tail_loss_floor_config()
    assert cfg["enabled"] is False

    # When flag is 0, normal env governs
    monkeypatch.setenv("MERID_DISABLE_LOSS_STOPS", "0")
    cfg_normal = _get_tail_loss_floor_config()
    assert cfg_normal["enabled"] is True


def test_position_monitor_residual_runner_floor(monkeypatch):
    """Residual-runner floor is disabled when MERID_DISABLE_LOSS_STOPS=1."""
    assert _residual_runner_floor_enabled() is False

    monkeypatch.setenv("MERID_DISABLE_LOSS_STOPS", "0")
    monkeypatch.setenv("MERID_RESIDUAL_RUNNER_FLOOR", "1")
    assert _residual_runner_floor_enabled() is True


def test_position_monitor_evaluate_stop_loss():
    """PositionMonitor._evaluate_stop_loss returns disabled_by_policy."""
    monitor = PositionMonitor()
    mock_pos = MagicMock()
    mock_pos.stop_loss_enabled = True
    mock_pos.stop_loss_price_cents = 30

    triggered, kind = monitor._evaluate_stop_loss(mock_pos, 25, None)
    assert triggered is False
    assert kind == "disabled_by_policy"


@pytest.mark.asyncio
async def test_stop_candidate_submission_suppressed_for_loss_triggers():
    """Stop candidates for loss/price triggers are suppressed and return None."""
    for trigger in ("LOSS_CAP", "HARD_STOP", "STOP_LOSS", "TRAILING_STOP", "SOFT_STOP"):
        sc = StopCandidate(
            market_ticker="KXSOL15M-26NOV161200-00",
            trigger_reason=trigger,
            position_from_exchange_cc=-100,
            executable_exit_cents=52,
        )
        res = await _maybe_submit_stop_candidate_impl(sc, force=True)
        assert res is None, f"Expected None for suppressed trigger {trigger}, got {res}"


def test_order_router_denial_for_stop_loss_exits():
    """_is_stop_loss_exit_denied identifies stop-loss exit intents and denies them."""
    # 1. Stop loss exit intent -> denied
    sl_intent = OrderIntent(
        ticker="KXSOL15M-26NOV161200-00",
        action="sell",
        side="sell_no",
        price_cents=50,
        count=1.0,
        entry_or_exit="exit",
        exit_reason="stop_loss",
    )
    assert _is_stop_loss_exit_denied(sl_intent) == "stop_loss_disabled_by_policy"

    # 2. Loss cap exit intent -> denied
    loss_cap_intent = OrderIntent(
        ticker="KXSOL15M-26NOV161200-00",
        action="sell",
        side="sell_no",
        price_cents=52,
        count=1.0,
        entry_or_exit="exit",
        exit_reason="loss_cap",
    )
    assert _is_stop_loss_exit_denied(loss_cap_intent) == "stop_loss_disabled_by_policy"

    # 3. Stop candidate source/agent -> denied
    sc_intent = OrderIntent(
        ticker="KXSOL15M-26NOV161200-00",
        action="sell",
        side="sell_no",
        price_cents=52,
        count=1.0,
        entry_or_exit="exit",
        source="stop_candidate_ioc",
        agent_id="stop_candidate",
    )
    assert _is_stop_loss_exit_denied(sc_intent) == "stop_loss_disabled_by_policy"


def test_order_router_permits_take_profit_and_closeout():
    """_is_stop_loss_exit_denied does NOT deny take-profit or pre-settlement closeouts."""
    tp_intent = OrderIntent(
        ticker="KXSOL15M-26NOV161200-00",
        action="sell",
        side="sell_no",
        price_cents=95,
        count=1.0,
        entry_or_exit="exit",
        exit_reason="take_profit",
    )
    assert _is_stop_loss_exit_denied(tp_intent) is None

    hard_profit_intent = OrderIntent(
        ticker="KXSOL15M-26NOV161200-00",
        action="sell",
        side="sell_no",
        price_cents=92,
        count=1.0,
        entry_or_exit="exit",
        exit_reason="hard_profit_lock",
    )
    assert _is_stop_loss_exit_denied(hard_profit_intent) is None

    closeout_intent = OrderIntent(
        ticker="KXSOL15M-26NOV161200-00",
        action="sell",
        side="sell_no",
        price_cents=80,
        count=1.0,
        entry_or_exit="exit",
        exit_reason="settlement_guard",
    )
    assert _is_stop_loss_exit_denied(closeout_intent) is None


def test_order_router_permits_entry_orders():
    """_is_stop_loss_exit_denied never denies entry orders."""
    entry_intent = OrderIntent(
        ticker="KXSOL15M-26NOV161200-00",
        action="buy",
        side="buy_no",
        price_cents=30,
        count=1.0,
        entry_or_exit="entry",
    )
    assert _is_stop_loss_exit_denied(entry_intent) is None


@pytest.mark.asyncio
async def test_route_live_rejects_stop_loss_exit():
    """_route_live rejects a stop loss exit with reason='stop_loss_disabled_by_policy'."""
    sl_intent = OrderIntent(
        ticker="KXSOL15M-26NOV161200-00",
        action="sell",
        side="sell_no",
        price_cents=50,
        count=1.0,
        entry_or_exit="exit",
        exit_reason="stop_loss",
    )
    result = await _route_live(sl_intent, TradingMode.LIVE, 0.0)
    assert result.status == "rejected"
    assert result.reason == "stop_loss_disabled_by_policy"
