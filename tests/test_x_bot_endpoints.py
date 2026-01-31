from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.env import capabilities

from social.x_bot_interface import XBotRateLimiter, XBotUserProfile
from web.api import x_bot as x_bot_module
from web.api.x_bot import router as x_bot_router


class DummyOrchestrator:
    def get_system_stats(self) -> Dict[str, Any]:
        return {
            "running": True,
            "active_agents": 5,
            "total_agents": 7,
            "recent_decisions": 3,
            "consensus_results": 10,
            "consensus_rate": 0.8,
            "twitter_enabled": True,
            "telegram_enabled": True,
            "news_monitoring": True,
            "price_streaming": True,
        }


class DummyAntiSilent:
    def get_health_report(self) -> Dict[str, Any]:
        return {
            "components": {"total": 2, "alive": 2, "safe_mode": 0},
            "data_feeds": {"total": 1, "healthy": 1},
            "incidents": {"total": 1, "active": 1, "critical": 0},
            "generated_at": "2026-01-15T00:00:00Z",
        }

    def get_active_incidents(self) -> List[Any]:
        failure_class = SimpleNamespace(value="strategy_stopped")
        return [
            SimpleNamespace(
                incident_id="incident_1",
                failure_class=failure_class,
                severity="high",
                component_id="agent_alpha",
                description="Agent stopped",
                evidence=["heartbeat missed"],
                resolved=False,
            )
        ]


class DummyPortfolioEngine:
    def __init__(self) -> None:
        self._positions = {}

    def get_total_value(self) -> float:
        return 1_000_000.0

    def get_total_pnl(self) -> float:
        return 12_345.67

    def get_allocation_by_class(self) -> Dict[Any, float]:
        class DummyAsset:
            def __init__(self, value: str) -> None:
                self.value = value

        return {DummyAsset("crypto_spot"): 0.6, DummyAsset("memecoin"): 0.05}


class DummyRiskCoordinator:
    def get_comprehensive_risk_status(self) -> Dict[str, Any]:
        return {
            "portfolio_risk": {"portfolio_value": 1_000_000.0},
            "active_stops": {"stop_losses": 0, "take_profits": 0, "trailing_stops": 0},
            "monitoring_active": True,
        }


class DummySocialEngine:
    def get_social_risk_status(self) -> Dict[str, Any]:
        return {"kill_switch_active": False}

    def get_top_asset_exposure(self, limit: int = 5) -> List[Dict[str, Any]]:
        return [{"asset": "BTC", "exposure": 10000.0, "constraints": {}}]


class DummySecurityDefense:
    def __init__(self) -> None:
        attack_vector = SimpleNamespace(value="prompt_injection")
        threat_level = SimpleNamespace(value="medium")
        self._incidents = [
            SimpleNamespace(
                incident_id="sec_incident_1",
                attack_vector=attack_vector,
                threat_level=threat_level,
                description="Prompt injection attempt",
                affected_components=["bot"],
                evidence={"prompt": "ignore rules"},
                resolved=False,
            )
        ]


@pytest.fixture(name="client")
def client_fixture(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    os.environ["X_BOT_SERVICE_TOKEN"] = "test-token"
    capabilities._get.cache_clear()  # type: ignore[attr-defined]

    app = FastAPI()
    app.include_router(x_bot_router)

    monkeypatch.setattr(x_bot_module, "get_agent_orchestrator", lambda: DummyOrchestrator())
    monkeypatch.setattr(x_bot_module, "get_anti_silent_failure_system", lambda: DummyAntiSilent())
    monkeypatch.setattr(x_bot_module, "get_portfolio_engine", lambda: DummyPortfolioEngine())
    monkeypatch.setattr(x_bot_module, "get_risk_coordinator", lambda: DummyRiskCoordinator())
    monkeypatch.setattr(x_bot_module, "get_social_aware_quant_engine", lambda: DummySocialEngine())
    monkeypatch.setattr(x_bot_module, "get_security_defense_system", lambda: DummySecurityDefense())

    return TestClient(app)


def test_status_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    os.environ["X_BOT_SERVICE_TOKEN"] = "token"
    capabilities._get.cache_clear()  # type: ignore[attr-defined]

    app = FastAPI()
    app.include_router(x_bot_router)
    test_client = TestClient(app)

    response = test_client.get("/x/status")
    assert response.status_code == 401


def test_status_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    os.environ["X_BOT_SERVICE_TOKEN"] = "token"
    capabilities._get.cache_clear()  # type: ignore[attr-defined]

    app = FastAPI()
    app.include_router(x_bot_router)
    test_client = TestClient(app)

    response = test_client.get("/x/status", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_status_endpoint_success(client: TestClient) -> None:
    response = client.get("/x/status", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["system_running"] is True
    assert payload["health"]["components"]["total"] == 2


def test_portfolio_endpoint_success(client: TestClient) -> None:
    response = client.get("/x/portfolio", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["portfolio_value"] == 1_000_000.0
    assert "allocation" in payload


def test_risk_endpoint_success(client: TestClient) -> None:
    response = client.get("/x/risk", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["portfolio_risk"]["portfolio_value"] == 1_000_000.0
    assert "social_kill_switch" in payload


def test_incidents_endpoint_success(client: TestClient) -> None:
    response = client.get("/x/incidents", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    sources = {incident["source"] for incident in payload["incidents"]}
    assert sources == {"anti_silent_failure", "security_defense"}


def test_social_intel_endpoint_success(client: TestClient) -> None:
    response = client.get("/x/social-intel", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["risk_status"]["kill_switch_active"] is False
    assert payload["top_assets"][0]["asset"] == "BTC"


def test_help_endpoint_success(client: TestClient) -> None:
    response = client.get("/x/help", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    payload = response.json()
    names = {cmd["name"] for cmd in payload["commands"]}
    assert {"status", "portfolio", "risk", "incidents", "social-intel", "help"} <= names


def test_rate_limiter_blocks_over_limit() -> None:
    limiter = XBotRateLimiter()
    profile = XBotUserProfile(user_id="user1", handle="@user1", max_commands_per_hour=2)
    assert limiter.check_and_record(profile) is True
    assert limiter.check_and_record(profile) is True
    assert limiter.check_and_record(profile) is False
