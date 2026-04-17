from __future__ import annotations

import asyncio
from unittest import mock

import pytest

pytestmark = [
    pytest.mark.kalshi_live_ready,
    pytest.mark.p0_live_blocker,
]


def _blocked_price_feed_gate():
    from core.execution_gate import ExecutionGateStatus, BlockReason

    return ExecutionGateStatus(
        blocked=True,
        safe_to_trade=False,
        gate_state="blocked",
        reasons=[
            BlockReason(
                source="price_feed",
                severity="critical",
                message="price feed staleness critical",
            )
        ],
    )


def _blocked_exchange_maintenance_gate():
    from core.execution_gate import ExecutionGateStatus, BlockReason

    return ExecutionGateStatus(
        blocked=True,
        safe_to_trade=False,
        gate_state="blocked",
        reasons=[
            BlockReason(
                source="kalshi_exchange",
                severity="critical",
                message="Kalshi exchange closed for maintenance — live trading blocked",
                details="reason=scheduled resume_utc=2026-03-26T09:00:00+00:00",
            )
        ],
    )


def test_route_order_async_live_gate_blocked_does_not_call_kalshi_client():
    from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
    from merid.prediction.venue_gate import TradingMode

    gate = _blocked_price_feed_gate()
    intent = OrderIntent(
        ticker="KXBTCD-TEST",
        side="yes",
        action="buy",
        price_cents=50,
        count=1,
        mode=TradingMode.LIVE,
    )

    with mock.patch("core.execution_gate.check_execution_gate", return_value=gate):
        with mock.patch("merid.event_venues.kalshi.order_router._check_intent_risk", return_value=None):
            with mock.patch("merid.event_venues.kalshi.order_router._check_sanity", return_value=None):
                with mock.patch("merid.event_venues.kalshi.order_router._get_caller_module", return_value="tests.test_execution_gate"):
                    with mock.patch("merid.event_venues.kalshi.client.get_kalshi_client") as get_client:
                        res = asyncio.run(route_order_async(intent))

    assert res.status == "rejected"
    assert "execution_gate" in (res.reason or "") or "kill_switch" in (res.reason or "")
    assert get_client.call_count == 0


def test_route_order_async_live_exchange_maintenance_does_not_call_kalshi_client():
    from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
    from merid.prediction.venue_gate import TradingMode
    from merid.risk.kill_switches import risk_controller
    from merid.event_venues.kalshi.order_gate import reset_pre_trade_gate_for_testing

    gate = _blocked_exchange_maintenance_gate()
    intent = OrderIntent(
        ticker="KXBTCD-TEST",
        side="yes",
        action="buy",
        price_cents=50,
        count=1,
        mode=TradingMode.LIVE,
    )

    risk_controller.reset()
    reset_pre_trade_gate_for_testing()
    
    with mock.patch("core.execution_gate.check_execution_gate", return_value=gate):
        with mock.patch("merid.event_venues.kalshi.order_router._check_intent_risk", return_value=None):
            with mock.patch("merid.event_venues.kalshi.order_router._check_sanity", return_value=None):
                with mock.patch("merid.event_venues.kalshi.order_router._get_caller_module", return_value="tests.test_execution_gate"):
                    with mock.patch("merid.event_venues.kalshi.client.get_kalshi_client") as get_client:
                        res = asyncio.run(route_order_async(intent))

    assert res.status == "rejected"
    assert "execution_gate_blocked" in (res.reason or "")
    assert "exchange closed for maintenance" in (res.reason or "").lower()
    assert get_client.call_count == 0


def test_continuous_trader_live_cycle_gate_blocked_does_not_post_orders():
    from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader

    gate = _blocked_price_feed_gate()

    trader = KalshiContinuousTrader.__new__(KalshiContinuousTrader)
    trader._last_execution_gate = None
    trader._shutdown = False
    trader._post = mock.MagicMock()

    with mock.patch("core.execution_gate.check_execution_gate", return_value=gate):
        trader._run_cycle_inner()

    trader._post.assert_not_called()


def test_kalshi_place_order_tool_gate_blocked_does_not_call_kalshi_client():
    from merid.prediction import kalshi_tools

    gate = _blocked_price_feed_gate()

    tool_gate = mock.MagicMock()
    tool_gate.check_order.return_value = None
    tool_gate.should_simulate_fill.return_value = False

    session = mock.MagicMock()
    session.is_trading_allowed.return_value = True
    session.block_reason.return_value = "ok"

    risk_mgr = mock.MagicMock()
    risk_mgr._check_fills_integrity.return_value = (True, "ok")

    with mock.patch("core.execution_gate.check_execution_gate", return_value=gate):
        with mock.patch.object(kalshi_tools, "get_venue_gate", return_value=tool_gate):
            with mock.patch.object(kalshi_tools, "get_session_guard", return_value=session):
                with mock.patch("merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk", return_value=risk_mgr):
                    with mock.patch("merid.event_venues.kalshi.client.get_kalshi_client") as get_client:
                        with mock.patch("merid.event_venues.kalshi.order_router._check_intent_risk", return_value=None):
                            with mock.patch("merid.event_venues.kalshi.order_router._check_sanity", return_value=None):
                                with mock.patch("merid.event_venues.kalshi.order_router._get_caller_module", return_value="merid.prediction.kalshi_tools"):
                                    res = asyncio.run(
                                        kalshi_tools._kalshi_place_order(
                                            ticker="KXBTCD-TEST",
                                            side="yes",
                                            action="buy",
                                            price_cents=50,
                                            count=1,
                                        )
                                    )

    assert res.success is False
    assert get_client.call_count == 0


def test_kalshi_api_place_order_live_gate_blocked_does_not_call_kalshi_client():
    from web.api import kalshi_api

    gate = _blocked_price_feed_gate()

    with mock.patch("core.execution_gate.check_execution_gate", return_value=gate):
        with mock.patch.object(kalshi_api, "_get_risk", return_value=None):
            with mock.patch("merid.event_venues.kalshi.order_router._check_intent_risk", return_value=None):
                with mock.patch("merid.event_venues.kalshi.order_router._check_sanity", return_value=None):
                    with mock.patch("merid.event_venues.kalshi.order_router._get_caller_module", return_value="web.api.kalshi_api"):
                        with mock.patch("merid.event_venues.kalshi.client.get_kalshi_client") as get_client:
                            res = asyncio.run(
                                kalshi_api.place_order(
                                    ticker="KXBTCD-TEST",
                                    side="yes",
                                    action="buy",
                                    count=1,
                                    price_cents=50,
                                    mode="live",
                                )
                            )

    assert res["status"] == "rejected"
    assert get_client.call_count == 0


# ── BUG-3b: snapshot_ts staleness gate in _route_live() ─────────────────────

def test_route_order_async_live_stale_snapshot_rejected():
    """_route_live() must reject intents whose snapshot_ts is older than the
    configured threshold (KALSHI_ORDER_SNAPSHOT_MAX_AGE_S, default 90s).

    This verifies the router-level staleness gate added in BUG-3b — the check
    that closes the gap for callers who bypass KalshiTradingAgent.
    """
    import time as _time
    from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
    from merid.prediction.venue_gate import TradingMode
    from merid.risk.kill_switches import risk_controller
    from merid.event_venues.kalshi.order_gate import reset_pre_trade_gate_for_testing

    risk_controller.reset()
    reset_pre_trade_gate_for_testing()

    stale_intent = OrderIntent(
        ticker="KXBTCD-STALE",
        side="yes",
        action="buy",
        price_cents=50,
        count=1,
        mode=TradingMode.LIVE,
        snapshot_ts=_time.time() - 200,  # 200 s old — well beyond 90 s default
    )

    with mock.patch("merid.event_venues.kalshi.order_router._check_intent_risk", return_value=None):
        with mock.patch("merid.event_venues.kalshi.order_router._check_sanity", return_value=None):
            with mock.patch("merid.event_venues.kalshi.order_router._get_caller_module", return_value="tests.test_execution_gate"):
                with mock.patch("merid.event_venues.kalshi.client.get_kalshi_client") as get_client:
                    res = asyncio.run(route_order_async(stale_intent))

    assert res.status == "rejected", f"Expected rejected, got {res.status}"
    assert "stale_snapshot" in (res.reason or ""), f"Expected stale_snapshot in reason, got: {res.reason}"
    # Kalshi client must never be reached
    get_client.assert_not_called()


def test_route_order_async_live_fresh_snapshot_not_blocked_by_staleness_gate():
    """A fresh snapshot_ts must not be rejected by the staleness gate alone.

    The test mocks all downstream checks (kill switch, execution gate, risk manager,
    venue client) so the only path that can reject is the staleness check itself.
    """
    import time as _time
    from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
    from merid.prediction.venue_gate import TradingMode
    from merid.risk.kill_switches import risk_controller
    from merid.event_venues.kalshi.order_gate import reset_pre_trade_gate_for_testing
    from core.execution_gate import ExecutionGateStatus

    risk_controller.reset()
    reset_pre_trade_gate_for_testing()

    fresh_intent = OrderIntent(
        ticker="KXBTCD-FRESH",
        side="yes",
        action="buy",
        price_cents=50,
        count=1,
        mode=TradingMode.LIVE,
        snapshot_ts=_time.time(),  # fresh — should not be gated by staleness
    )

    clear_gate = ExecutionGateStatus(blocked=False, safe_to_trade=True, gate_state="clear")

    with mock.patch("merid.event_venues.kalshi.order_router._check_intent_risk", return_value=None):
        with mock.patch("merid.event_venues.kalshi.order_router._check_sanity", return_value=None):
            with mock.patch("merid.event_venues.kalshi.order_router._get_caller_module", return_value="tests.test_execution_gate"):
                with mock.patch("core.execution_gate.check_execution_gate", return_value=clear_gate):
                    with mock.patch("merid.event_venues.kalshi.order_router.get_venue_gate") as mock_vg:
                        mock_vg.return_value.live_enabled = False
                        mock_vg.return_value.log_order_decision = mock.MagicMock()
                        res = asyncio.run(route_order_async(fresh_intent))

    # live_not_enabled is the expected rejection reason — NOT stale_snapshot
    assert "stale_snapshot" not in (res.reason or ""), (
        f"Fresh snapshot should not be rejected for staleness; got reason: {res.reason}"
    )

