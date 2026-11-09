"""Offline contracts for canonical lifespan, probes, and entry authorization."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.datastructures import State


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    import web.main_15m_lean as main
    from merid.observability.live_runtime_state import LiveRuntimeState

    state = LiveRuntimeState(tmp_path / "runtime.json")
    app = main.app
    monkeypatch.setattr(app, "state", State())
    monkeypatch.setattr(main, "get_live_runtime_state", lambda: state)
    monkeypatch.setattr(main, "is_auto_execution_enabled", lambda: False)
    monkeypatch.setattr(main, "is_observe_only", lambda: True)
    monkeypatch.setattr("merid.single_instance.acquire_live_instance_guard", lambda **kw: 0)
    monkeypatch.setattr("merid.data.cf_rti_adapter.start_kalshi_rti_stream", lambda: None)
    monkeypatch.setattr("merid.audit.start_production_audit_harness", lambda: None)
    monkeypatch.setattr("merid.config.live_config.resolve_live_config", lambda: SimpleNamespace(
        profile_name="kalshi_crypto_15m_v2", profile_version="test", operation_mode="offline",
        config_hash="test", build_sha="test", max_contracts_per_order=1,
        fixed_exposure_cap_usd=1,
    ))
    monitor = SimpleNamespace(start=AsyncMock(), stop=AsyncMock())
    monkeypatch.setattr("merid.monitoring.position_state_monitor.get_position_state_monitor", lambda: monitor)
    safety = SimpleNamespace(
        initialize=AsyncMock(), start=AsyncMock(), stop=AsyncMock(), health_check=AsyncMock(return_value={}),
    )
    monkeypatch.setattr("core.data_safety_integration.DataSafetyCoordinator", lambda: safety)
    monkeypatch.setattr("data.unified_spot_service.get_unified_spot_service", lambda: SimpleNamespace(
        stop_refresh_loop=AsyncMock(),
    ))
    ledger = SimpleNamespace(close=MagicMock(return_value=True))
    monkeypatch.setattr("merid.execution.decision_audit_ledger.get_decision_audit_ledger", lambda: ledger)
    monkeypatch.setenv("MERID_ENABLE_ARBITRAGE", "0")
    monkeypatch.setenv("TRADING_ENABLED", "false")
    monkeypatch.setenv("MERID_PM_LIVE_ENABLED", "false")
    monkeypatch.setenv("MERID_ALLOW_LIVE_TRADES", "false")
    monkeypatch.setenv("MERID_PM_TRADING_MODE", "mock")

    async def infrastructure(application):
        application.state.kalshi_client = object()
        application.state.catalog = object()
        application.state.bankroll = object()

    async def trading(application):
        application.state.kalshi_15m_task = asyncio.create_task(asyncio.Event().wait())
        application.state.startup_completed = True

    p0 = AsyncMock(return_value=[(True, "offline fixture preflight")])
    p2 = AsyncMock(side_effect=trading)
    monkeypatch.setattr(main, "_run_startup_phases_v20260530", infrastructure)
    monkeypatch.setattr(main, "_run_full_startup_in_lifespan", p2)
    monkeypatch.setattr("merid.preflight.p0.run_p0_preflight_checks", p0)
    monkeypatch.setattr(main.asyncio, "all_tasks", lambda: set())
    return SimpleNamespace(main=main, app=app, state=state, p0=p0, p2=p2, safety=safety, ledger=ledger)


@pytest.mark.asyncio
async def test_lifespan_runs_preflight_and_drains_shutdown_without_live_permission(runtime):
    async with runtime.main.lifespan(runtime.app):
        runtime.p0.assert_awaited_once()
        runtime.p2.assert_awaited_once()
        assert not runtime.state.can_submit_live_entry()
        assert runtime.state.can_submit_exit()
        response = await runtime.main.readiness_check()
        assert response.status_code == 200
        assert json.loads(response.body)["loop_task_alive"] is True
        task = runtime.app.state.kalshi_15m_task
    assert task.cancelled()
    runtime.safety.stop.assert_awaited_once()
    runtime.ledger.close.assert_called_once()


@pytest.mark.asyncio
async def test_failed_preflight_never_starts_trading_stack(runtime):
    runtime.p0.return_value = [(False, "exchange_reconciliation failed")]
    with pytest.raises(RuntimeError, match="P0 preflight assertions failed"):
        async with runtime.main.lifespan(runtime.app):
            pytest.fail("A failed preflight must not yield a serving application")
    runtime.p2.assert_not_awaited()
    assert not runtime.state.can_submit_live_entry()
    assert runtime.state.can_submit_exit()
    assert runtime.state.state == "LIVE_ENTRIES_HALTED"


@pytest.mark.asyncio
async def test_liveness_does_not_imply_readiness(runtime):
    assert (await runtime.main.health_check())["status"] == "alive"
    response = await runtime.main.readiness_check()
    assert response.status_code == 503
    assert json.loads(response.body)["loop_task_alive"] is False
    assert not runtime.state.can_submit_live_entry()


def test_offline_guard_blocks_connections_even_when_errors_are_caught():
    import subprocess
    import sys

    code = (
        "import socket; from scripts import offline_gate_plugin as gate; "
        "s = socket.socket(); "
        "exec(\"try:\\n s.connect(('192.0.2.1', 443))\\nexcept OSError:\\n pass\"); "
        "assert len(gate._attempts) == 1; s.close()"
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=30)


def test_offline_environment_does_not_inherit_credentials(tmp_path, monkeypatch):
    from scripts.run_offline_gate import gate_environment

    monkeypatch.setenv("KALSHI_PRIVATE_KEY", "fixture-not-a-key")
    monkeypatch.setenv("GH_TOKEN", "fixture-not-a-token")
    env = gate_environment(tmp_path)
    assert "KALSHI_PRIVATE_KEY" not in env
    assert "GH_TOKEN" not in env
    assert env["MERID_ALLOW_LIVE_TRADES"] == "false"
    assert env["MERID_OBSERVE_ONLY"] == "1"


def test_durable_scan_ignores_directory_metadata_but_detects_content_changes(tmp_path, monkeypatch, request):
    import os

    config = next(p for p in request.config.pluginmanager.get_plugins() if hasattr(p, "_snapshot_durable_state"))
    monkeypatch.setattr(config, "_DURABLE_STATE_ROOT", tmp_path)
    directory = tmp_path / "nested"
    directory.mkdir()
    baseline = config._snapshot_durable_state()
    os.utime(directory, ns=(1_000_000_000, 1_000_000_000))
    assert config._snapshot_durable_state() == baseline
    artifact = directory / "state.json"
    artifact.write_text("{}", encoding="utf-8")
    created = config._snapshot_durable_state()
    assert created != baseline
    artifact.write_text('{"changed": true}', encoding="utf-8")
    assert config._snapshot_durable_state() != created
    artifact.unlink()
    assert config._snapshot_durable_state() == baseline


@pytest.mark.asyncio
async def test_cache_connects_only_when_used(monkeypatch):
    from merid.event_venues.kalshi.crypto_series import _CacheAdapter

    redis = MagicMock()
    redis.get.return_value = "cached"
    factory = MagicMock(return_value=redis)
    monkeypatch.setattr("redis.Redis", factory)
    cache = _CacheAdapter()
    factory.assert_not_called()
    assert await cache.get("key") == "cached"
    assert await cache.get("key") == "cached"
    factory.assert_called_once()
    redis.ping.assert_called_once()


@pytest.mark.asyncio
async def test_completed_loop_is_not_ready(runtime):
    async with runtime.main.lifespan(runtime.app):
        task = runtime.app.state.kalshi_15m_task
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        response = await runtime.main.readiness_check()
        assert response.status_code == 503
