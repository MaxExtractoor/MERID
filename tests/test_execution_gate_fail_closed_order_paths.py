from __future__ import annotations

import asyncio
from unittest import mock

import pytest

pytestmark = [
    pytest.mark.kalshi_live_ready,
    pytest.mark.p0_live_blocker,
]



@pytest.fixture(autouse=True)
def _pass_upstream_gates():
    """Pass the gates upstream of the execution-gate checks under test.

    The router's P0 startup state machine (can_submit_live_entry), the intent
    contract/risk/sanity checks, and the net-of-cost economics gate all fire
    before the execution gate.  These tests target the execution gate itself,
    so upstream gates are patched through.
    """
    with mock.patch(
        "merid.event_venues.kalshi.order_router.can_submit_live_entry",
        return_value=True,
    ), mock.patch(
        "merid.event_venues.kalshi.order_router._check_intent_risk",
        return_value=None,
    ), mock.patch(
        "merid.event_venues.kalshi.order_router._check_sanity",
        return_value=None,
    ), mock.patch(
        "merid.event_venues.kalshi.order_router._round_trip_net_of_cost_gate",
        return_value=None,
    ), mock.patch(
        "merid.event_venues.kalshi.order_router._validate_signal_metadata",
        return_value=None,
    ), mock.patch(
        "merid.event_venues.kalshi.order_router._validate_position_lifecycle",
        return_value=None,
    ), mock.patch(
        "merid.event_venues.kalshi.order_router._validate_deployment_safety",
        return_value=None,
    ), mock.patch(
        "merid.event_venues.kalshi.order_router._check_bankroll_risk_cap",
        return_value=None,
    ):
        yield

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

    intent = OrderIntent(
        ticker="KXBTCD-TEST",
        side="yes",
        action="buy",
        price_cents=50,
        count=1,
        mode=TradingMode.LIVE,
        source="merid.prediction.agent_grid_15m",
        agent_id="BTC_15M",
        time_to_expiry_seconds=900,
    )

    # route_order_async does not consult core.execution_gate (kalshi_tools does).
    # The router's own live gate is the fail-closed analog on this path: the
    # autouse fixture patches it to True; override to halted and verify the
    # order is rejected before any Kalshi client contact.
    with mock.patch("merid.event_venues.kalshi.order_router.can_submit_live_entry", return_value=False):
        with mock.patch("merid.event_venues.kalshi.order_router._get_caller_module", return_value="tests.test_execution_gate"):
            with mock.patch("merid.event_venues.kalshi.client.get_kalshi_client") as get_client:
                res = asyncio.run(route_order_async(intent))

    assert res.status == "rejected"
    assert "live_runtime_state_halted" in (res.reason or "")
    assert get_client.call_count == 0


def test_route_order_async_live_exchange_maintenance_does_not_call_kalshi_client():
    from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
    from merid.prediction.venue_gate import TradingMode
    from merid.risk.kill_switches import risk_controller
    from merid.event_venues.kalshi.order_gate import reset_pre_trade_gate_for_testing

    intent = OrderIntent(
        ticker="KXBTCD-TEST",
        side="yes",
        action="buy",
        price_cents=50,
        count=1,
        mode=TradingMode.LIVE,
        source="merid.prediction.agent_grid_15m",
        agent_id="BTC_15M",
        time_to_expiry_seconds=900,
    )

    risk_controller.reset()
    reset_pre_trade_gate_for_testing()
    # Exchange-critical conditions fail closed through the kill switch on the
    # router path.
    risk_controller.trigger_dependency_health("exchange closed for maintenance")

    with mock.patch("merid.event_venues.kalshi.order_router._get_caller_module", return_value="tests.test_execution_gate"):
        with mock.patch("merid.event_venues.kalshi.client.get_kalshi_client") as get_client:
            res = asyncio.run(route_order_async(intent))

    assert res.status == "rejected"
    assert get_client.call_count == 0


def test_continuous_trader_live_cycle_gate_blocked_does_not_post_orders():
    """KalshiContinuousTrader is now a deliberate no-op status stub - the 15m
    loop is the only live trading path, so there is no cycle body that could
    post orders regardless of gate state."""
    import inspect

    from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader

    assert not hasattr(KalshiContinuousTrader, "_run_cycle_inner")
    assert not hasattr(KalshiContinuousTrader, "_post")
    src = inspect.getsource(KalshiContinuousTrader.run)
    assert "place_order" not in src and "route_order" not in src


def test_kalshi_place_order_tool_gate_blocked_does_not_call_kalshi_client():
    from merid.prediction import kalshi_tools

    gate = _blocked_price_feed_gate()

    tool_gate = mock.MagicMock()
    tool_gate.check_order.return_value = None
    tool_gate.should_simulate_fill.return_value = False

    risk_mgr = mock.MagicMock()
    risk_mgr._check_fills_integrity.return_value = (True, "ok")

    with mock.patch("core.execution_gate.check_execution_gate", return_value=gate):
        with mock.patch.object(kalshi_tools, "get_venue_gate", return_value=tool_gate):
            with mock.patch("merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk", return_value=risk_mgr):
                with mock.patch("merid.event_venues.kalshi.client.get_kalshi_client") as get_client:
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
        source="merid.prediction.agent_grid_15m",
        agent_id="BTC_15M",
        time_to_expiry_seconds=900,
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
        source="merid.prediction.agent_grid_15m",
        agent_id="BTC_15M",
        time_to_expiry_seconds=900,
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

