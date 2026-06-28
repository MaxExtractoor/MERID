"""Kalshi WS Protect-as-gate tests for core.execution_gate."""

from unittest.mock import MagicMock, patch


_EXEC_GATE_DEP_OK = {
    "dependencies": [],
    "any_critical_down": False,
    "healthy_count": 0,
    "degraded_count": 0,
    "down_count": 0,
    "total": 0,
    "timestamp": 0.0,
}


def _base_gate_patches():
    """Patch non-WS checks so we can isolate WS gating behavior."""
    return (
        patch("core.dependency_health.check_all_dependencies", return_value=_EXEC_GATE_DEP_OK),
        patch("core.execution_gate.check_pnl_consistency", return_value={"consistent": True, "max_divergence_usd": 0, "threshold_usd": 5}),
        patch("core.execution_gate.check_price_feed_staleness", return_value={"safe_to_trade": True, "stale_symbols": [], "critical_count": 0}),
        patch(
            "merid.event_venues.kalshi.exchange_availability.get_kalshi_exchange_availability",
            return_value=MagicMock(snapshot=MagicMock(return_value=MagicMock(ok=True, trading_open_now=True, reason="ok", next_open_time_utc=None, estimated_resume_time_utc=None, error=None))),
        ),
    )


def _mock_kill_switch_off_modules():
    mock_rc = MagicMock()
    mock_rc._global_kill = False
    mock_kalshi_recon = MagicMock()
    mock_kalshi_recon.has_critical_discrepancies = MagicMock(return_value=False)
    mock_recon = MagicMock()
    mock_recon.has_critical_discrepancies = MagicMock(return_value=False)
    mock_recon._has_ever_completed = True
    return {
        "merid.risk.kill_switches": MagicMock(risk_controller=mock_rc),
        "merid.reconciliation": mock_kalshi_recon,
        "trading.reconciliation": mock_recon,
    }


def test_kalshi_disabled_profile_gate_ignores_ws_status():
    from core.execution_gate import check_execution_gate

    with patch.dict("os.environ", {"MERID_PM_TRADING_MODE": "paper", "MERID_PM_LIVE_ENABLED": "false", "KALSHI_USE_DEMO": "true"}, clear=False):
        with patch.dict("sys.modules", _mock_kill_switch_off_modules()):
            p1, p2, p3, p4 = _base_gate_patches()
            with p1, p2, p3, p4:
                # Even if WS reports disconnected, gate should be open (no WS requirement).
                with patch("merid.event_venues.kalshi.ws_bridge.get_kalshi_ws_status", return_value={"connected": False, "subscribed_tickers": 0}):
                    res = check_execution_gate()
    assert res.blocked is False


def test_kalshi_enabled_ws_disconnected_denies():
    from core.execution_gate import check_execution_gate

    env = {
        "MERID_PM_TRADING_MODE": "live",
        "MERID_PM_LIVE_ENABLED": "true",
        "KALSHI_USE_DEMO": "false",
        "MERID_EXEC_GATE_REQUIRE_KALSHI_WS": "1",
        # Avoid unrelated RTI feed gate tripping in this unit test
        "KALSHI_ENV": "demo",
    }
    with patch.dict("os.environ", env, clear=False):
        with patch.dict("sys.modules", _mock_kill_switch_off_modules()):
            p1, p2, p3, p4 = _base_gate_patches()
            with p1, p2, p3, p4:
                with patch("merid.event_venues.kalshi.ws_bridge.get_kalshi_ws_status", return_value={"connected": False, "subscribed_tickers": 10}):
                    res = check_execution_gate()
    assert res.blocked is True
    assert any(r.source == "kalshi_ws" and "kalshi_ws:not_connected" in r.message.lower() for r in res.reasons)


def test_kalshi_enabled_ws_connected_zero_tickers_denies():
    from core.execution_gate import check_execution_gate

    env = {
        "MERID_PM_TRADING_MODE": "live",
        "MERID_PM_LIVE_ENABLED": "true",
        "KALSHI_USE_DEMO": "false",
        "MERID_EXEC_GATE_REQUIRE_KALSHI_WS": "1",
        "KALSHI_ENV": "demo",
    }
    with patch.dict("os.environ", env, clear=False):
        with patch.dict("sys.modules", _mock_kill_switch_off_modules()):
            p1, p2, p3, p4 = _base_gate_patches()
            with p1, p2, p3, p4:
                with patch("merid.event_venues.kalshi.ws_bridge.get_kalshi_ws_status", return_value={"connected": True, "subscribed_tickers": 0}):
                    res = check_execution_gate()
    assert res.blocked is True
    assert any(r.source == "kalshi_ws" and "kalshi_ws:no_subscriptions" in r.message.lower() for r in res.reasons)


def test_kalshi_enabled_ws_connected_with_tickers_allows():
    from core.execution_gate import check_execution_gate

    env = {
        "MERID_PM_TRADING_MODE": "live",
        "MERID_PM_LIVE_ENABLED": "true",
        "KALSHI_USE_DEMO": "false",
        "MERID_EXEC_GATE_REQUIRE_KALSHI_WS": "1",
        "KALSHI_ENV": "demo",
    }
    with patch.dict("os.environ", env, clear=False):
        with patch.dict("sys.modules", _mock_kill_switch_off_modules()):
            p1, p2, p3, p4 = _base_gate_patches()
            with p1, p2, p3, p4:
                with patch("merid.event_venues.kalshi.ws_bridge.get_kalshi_ws_status", return_value={"connected": True, "subscribed_tickers": 12}):
                    res = check_execution_gate()
    assert res.blocked is False


def test_kalshi_enabled_ws_stale_denies():
    from core.execution_gate import check_execution_gate

    env = {
        "MERID_PM_TRADING_MODE": "live",
        "MERID_PM_LIVE_ENABLED": "true",
        "KALSHI_USE_DEMO": "false",
        "MERID_EXEC_GATE_REQUIRE_KALSHI_WS": "1",
        "KALSHI_ENV": "live",
        "MERID_EXEC_GATE_KALSHI_WS_STALE_S": "10",
        # Avoid unrelated RTI feed gate tripping in this unit test
        "MERID_ALLOW_NULL_CFB": "1",
    }
    with patch.dict("os.environ", env, clear=False):
        with patch.dict("sys.modules", _mock_kill_switch_off_modules()):
            p1, p2, p3, p4 = _base_gate_patches()
            with p1, p2, p3, p4:
                with patch(
                    "merid.event_venues.kalshi.ws_bridge.get_kalshi_ws_status",
                    return_value={
                        "connected": True,
                        "subscribed_tickers": 3,
                        "expected_ws_url": "wss://external-api-ws.kalshi.com/trade-api/ws/v2",
                        "ws_client": {"last_msg_ago_s": 99, "uptime_s": 100, "ws_url": "wss://external-api-ws.kalshi.com/trade-api/ws/v2"},
                    },
                ):
                    res = check_execution_gate()
    assert res.blocked is True
    assert any(r.source == "kalshi_ws" and "stale" in r.message.lower() for r in res.reasons)
