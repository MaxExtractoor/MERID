from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_module(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_grid_status_keeps_raw_agents_and_adds_agent_cards(monkeypatch):
    kalshi_grid_api = _load_module("kalshi_grid_api_test", "web/api/kalshi_grid_api.py")

    raw_agent = {
        "name": "kalshi-btc-15m",
        "running": True,
        "enabled": True,
        "cycles_run": 12,
        "orders_placed": 5,
        "last_error": "boom",
        "config": {"assets": ["BTC"], "timeframes": ["15m"]},
        "performance": {"profit_factor": 1.2, "sharpe_ratio": 0.9},
    }
    grid = MagicMock()
    grid.summary.return_value = {
        "agents": [raw_agent],
        "portfolio_risk": {"kill_switch_active": False, "latest_snapshot": {}},
    }
    monkeypatch.setattr(kalshi_grid_api, "_get_grid", lambda: grid)
    monkeypatch.setattr(
        kalshi_grid_api,
        "_get_venue_gate",
        lambda: SimpleNamespace(summary=lambda: {"mode": "paper", "is_live": False, "live_enabled": False}),
    )

    result = await kalshi_grid_api.grid_status()

    assert result["agents"][0]["config"]["assets"] == ["BTC"]
    assert result["agents"][0]["last_error"] == "boom"
    assert result["agent_cards"][0]["asset"] == "BTC"
    assert result["agent_cards"][0]["timeframe"] == "15m"


@pytest.mark.asyncio
async def test_pipeline_venues_exposes_flat_venues_contract(monkeypatch):
    unified_pipeline = _load_module("unified_pipeline_test", "web/api/unified_pipeline.py")

    mode_manager = MagicMock()
    mode_manager.summary.return_value = {
        "disabled_domains": [],
        "venues": [
            {"venue": "kalshi", "domain": "prediction", "mode": "paper", "enabled": True},
        ],
    }
    adapter_registry = MagicMock()
    adapter_registry.summary.return_value = [
        {"venue": "kalshi", "domain": "prediction", "supports_trading": True},
    ]
    monkeypatch.setattr(unified_pipeline, "get_mode_manager", lambda: mode_manager)
    monkeypatch.setattr(unified_pipeline, "get_adapter_registry", lambda: adapter_registry)

    result = await unified_pipeline.pipeline_venues()

    assert result["venues"] == [
        {
            "venue": "kalshi",
            "domain": "prediction",
            "mode": "PAPER",
            "enabled": True,
            "supports_trading": True,
            "adapter_registered": True,
            "lastModeChange": None,
        }
    ]


@pytest.mark.asyncio
async def test_alert_history_contract_contains_source_and_detail(monkeypatch):
    signals_api = _load_module("signals_api_test", "web/api/signals_api.py")

    alert_router = MagicMock()
    alert_router.get_history.return_value = [
        {
            "id": "a1",
            "timestamp": "2026-04-04T00:00:00Z",
            "severity": "critical",
            "channel": "telegram",
            "source": "risk_controller",
            "title": "Limit Breach",
            "message": "Daily loss limit breached",
            "type": "risk",
            "status": "open",
        }
    ]
    monkeypatch.setattr(signals_api, "_get_alert_router", lambda: alert_router)

    result = await signals_api.get_alert_history()

    assert result["alerts"][0]["source"] == "risk_controller"
    assert result["alerts"][0]["detail"] == "Daily loss limit breached"
    assert result["alerts"][0]["type"] == "risk"
    assert result["alerts"][0]["status"] == "open"


@pytest.mark.asyncio
async def test_auto_promoter_promotions_exposes_evaluations(monkeypatch):
    auto_promoter_api = _load_module("auto_promoter_api_test", "web/api/auto_promoter_api.py")

    promoter = MagicMock()
    promoter.status.return_value = {
        "total_promotions": 1,
        "recent_evaluations": [
            {
                "agent": "kalshi-btc-15m",
                "from_phase": "PAPER",
                "to_phase": "SHADOW",
                "promoted": True,
                "timestamp": "2026-04-04T00:00:00Z",
                "blocked_by": None,
                "gates": [],
            }
        ],
    }
    monkeypatch.setattr(auto_promoter_api, "_get_promoter", lambda: promoter)

    result = await auto_promoter_api.get_recent_promotions(limit=20)

    assert result["evaluations"][0]["agent"] == "kalshi-btc-15m"
    assert result["promotions"][0]["direction"] == "PAPER→SHADOW"


@pytest.mark.asyncio
async def test_real_data_endpoints_profile_and_logs_use_canonical_contract(monkeypatch):
    real_data_endpoints = _load_module("real_data_endpoints_test", "web/api/real_data_endpoints.py")

    monkeypatch.setattr(
        "utils.logger.get_log_ring_buffer",
        lambda: [
            {
                "id": "1",
                "timestamp": "2026-04-04T00:00:00Z",
                "level": "INFO",
                "component": "system",
                "message": "ready",
                "ts": 1.0,
            }
        ],
    )

    profile = await real_data_endpoints.get_user_profile()
    logs = await real_data_endpoints.get_logs_real()
    stats = await real_data_endpoints.get_log_stats()

    assert profile["accountType"] == "operator"
    assert "createdAt" in profile
    assert logs[0]["component"] == "system"
    assert stats["totalLogs"] == 1
