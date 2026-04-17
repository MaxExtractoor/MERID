"""Executable policy matrix: venue gate × risk_controller × execution_gate → router + CT preflight.

Loop-lag / spot-degraded / exchange maintenance are represented by the aggregated
``ExecutionGateStatus`` returned from ``check_execution_gate`` (blocked vs limited vs clear).

Router: ``_route_live`` order — kill_switch → live_enabled → execution_gate → … → client.
CT: ``_run_cycle_inner`` — **execution_gate first**, then ``risk_controller``, then KalshiRiskManager
(Router uses **risk_controller → live_enabled → execution_gate** — intentional asymmetry; see matrix tests.)
"""

from __future__ import annotations

import asyncio
from typing import Optional
from unittest import mock

import pytest

from core.execution_gate import BlockReason, ExecutionGateStatus, GateState

pytestmark = [
    pytest.mark.kalshi_live_ready,
    pytest.mark.p0_live_blocker,
]


def _eg(
    *,
    blocked: bool,
    safe_to_trade: bool,
    gate_state: str,
    reasons: Optional[list] = None,
) -> ExecutionGateStatus:
    return ExecutionGateStatus(
        blocked=blocked,
        safe_to_trade=safe_to_trade,
        gate_state=gate_state,
        reasons=reasons or [],
    )


def _blocked_feed() -> ExecutionGateStatus:
    return _eg(
        blocked=True,
        safe_to_trade=False,
        gate_state=GateState.BLOCKED.value,
        reasons=[
            BlockReason(
                source="price_feed",
                severity="critical",
                message="stale feed",
            )
        ],
    )


def _limited_loop_lag() -> ExecutionGateStatus:
    return _eg(
        blocked=False,
        safe_to_trade=True,
        gate_state=GateState.LIMITED.value,
        reasons=[
            BlockReason(
                source="loop_lag",
                severity="warning",
                message="Event loop lag elevated",
            )
        ],
    )


@pytest.mark.parametrize(
    "can_trade,live_enabled,eg,expected_substr",
    [
        (False, True, _eg(blocked=False, safe_to_trade=True, gate_state=GateState.CLEAR.value), "kill_switch:"),
        (True, False, _eg(blocked=False, safe_to_trade=True, gate_state=GateState.CLEAR.value), "live_not_enabled"),
        (True, True, _blocked_feed(), "execution_gate_blocked:"),
        (
            True,
            True,
            _eg(blocked=False, safe_to_trade=False, gate_state=GateState.CLEAR.value, reasons=[]),
            "execution_gate_blocked:",
        ),
        (
            True,
            True,
            _limited_loop_lag(),
            None,
        ),
    ],
    ids=[
        "kill_switch_first",
        "live_disabled",
        "exec_gate_blocked_critical",
        "exec_gate_unsafe_edge",
        "exec_gate_limited_passes_preflight",
    ],
)
def test_route_live_truth_table_rejections_or_pass_preflight(
    can_trade: bool,
    live_enabled: bool,
    eg: ExecutionGateStatus,
    expected_substr: Optional[str],
) -> None:
    from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
    from merid.prediction.venue_gate import TradingMode

    intent = OrderIntent(
        ticker="KXBTCD-TEST",
        side="yes",
        action="buy",
        price_cents=50,
        count=1,
        mode=TradingMode.LIVE,
    )

    mock_rc = mock.MagicMock()
    mock_rc.can_trade.return_value = can_trade
    mock_rc.get_kill_reason.return_value = "unit_test"

    mock_vg = mock.MagicMock()
    mock_vg.live_enabled = live_enabled

    with mock.patch.dict(
        "sys.modules",
        {
            "merid.risk.kill_switches": mock.MagicMock(risk_controller=mock_rc),
            "merid.reconciliation": mock.MagicMock(
                has_critical_discrepancies=mock.MagicMock(return_value=False)
            ),
        },
    ):
        with mock.patch(
            "merid.event_venues.kalshi.order_router.get_venue_gate",
            return_value=mock_vg,
        ), mock.patch(
            "core.execution_gate.check_execution_gate",
            return_value=eg,
        ), mock.patch(
            "merid.event_venues.kalshi.order_router._check_intent_risk",
            return_value=None,
        ), mock.patch(
            "merid.event_venues.kalshi.order_router._check_sanity",
            return_value=None,
        ), mock.patch(
            "merid.event_venues.kalshi.client.get_kalshi_client",
        ) as get_client:
            res = asyncio.run(route_order_async(intent))

    if expected_substr is not None:
        assert res.status == "rejected"
        assert expected_substr in (res.reason or ""), res.reason
        assert get_client.call_count == 0
    else:
        assert get_client.call_count == 1, "limited/clear preflight should reach Kalshi client factory"


@pytest.mark.parametrize(
    "check_gate,risk_can_trade,krm_kill,expect_post",
    [
        (_blocked_feed(), True, False, False),
        (
            _eg(blocked=False, safe_to_trade=True, gate_state=GateState.CLEAR.value),
            False,
            False,
            False,
        ),
        (
            _eg(blocked=False, safe_to_trade=True, gate_state=GateState.CLEAR.value),
            True,
            True,
            False,
        ),
    ],
    ids=[
        "gate_blocked_exits_before_risk",
        "gate_clear_risk_halt",
        "gate_clear_krm_kill",
    ],
)
def test_continuous_trader_preflight_truth_table(
    check_gate: ExecutionGateStatus,
    risk_can_trade: bool,
    krm_kill: bool,
    expect_post: bool,
) -> None:
    from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader

    trader = KalshiContinuousTrader.__new__(KalshiContinuousTrader)
    trader._last_execution_gate = None
    trader._shutdown = False
    trader._post = mock.MagicMock()
    trader._cycle = 0
    trader._active_assets = ["BTC"]

    mock_rc = mock.MagicMock()
    mock_rc.can_trade.return_value = risk_can_trade
    mock_rc.get_kill_reason.return_value = "unit"

    mock_krm = mock.MagicMock()
    mock_krm.kill_switch_active = krm_kill
    mock_krm.state = mock.MagicMock(kill_switch_reason="unit" if krm_kill else "")

    with mock.patch("core.execution_gate.check_execution_gate", return_value=check_gate):
        with mock.patch.dict(
            "sys.modules",
            {"merid.risk.kill_switches": mock.MagicMock(risk_controller=mock_rc)},
        ):
            with mock.patch(
                "merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk",
                return_value=mock_krm,
            ):
                trader._run_cycle_inner()

    if expect_post:
        trader._post.assert_called()
    else:
        trader._post.assert_not_called()
