from __future__ import annotations

import pytest
from fastapi import FastAPI
from types import SimpleNamespace
from fastapi.testclient import TestClient

from web.api.moat import router as moat_router
from moat.moat_runtime import MoatRuntimeStatus


pytestmark = [
    pytest.mark.prod_integration,
    pytest.mark.quarantine,
]


@pytest.fixture(name="app_client")
def app_client_fixture(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(moat_router)

    class FakeRuntimeService:
        def __init__(self):
            self.status = MoatRuntimeStatus.STOPPED
            self.interval = 300.0
            self.cycle_count = 0
            self.metrics = {"advantage": {"strength": "strong", "advantage_ratio": 1.2, "trend": "flat"}}

        async def start(self, interval: float = 300.0):
            self.interval = interval
            self.status = MoatRuntimeStatus.RUNNING

        async def stop(self):
            self.status = MoatRuntimeStatus.STOPPED

        async def measure_now(self):
            self.cycle_count += 1
            return {
                "cycle": self.cycle_count,
                "metrics": self.metrics,
                "risks": [],
                "timestamp": "2026-01-16T00:00:00Z",
            }

        def get_status_payload(self):
            return {
                "status": self.status.value,
                "cycle_count": self.cycle_count,
                "interval": self.interval,
                "last_measurement": "2026-01-16T00:00:00Z",
                "metrics": self.metrics,
                "risks": [],
            }

        def submit_feature_proposal(self, name: str, description: str):
            return SimpleNamespace(
                proposal_id="proposal-1",
                approved=True,
                moat_score=0.9,
                moat_impacts={},
                recommendations=[],
                approval_reason=f"Approved: {name}",
            )

    runtime = FakeRuntimeService()
    monkeypatch.setattr("web.api.moat.get_moat_runtime_service", lambda: runtime)
    monkeypatch.setenv("MOAT_SERVICE_TOKEN", "test-token")

    client = TestClient(app)
    return client


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def test_moat_status_endpoint(app_client: TestClient) -> None:
    response = app_client.get("/moat/status", headers=_auth_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "stopped"
    assert "metrics" in payload


def test_moat_start_and_stop(app_client: TestClient) -> None:
    response = app_client.post("/moat/start", json={"interval": 120}, headers=_auth_headers())
    assert response.status_code == 200
    assert response.json()["status"] in {"starting", "running"}

    response = app_client.post("/moat/stop", headers=_auth_headers())
    assert response.status_code == 200
    assert response.json()["status"] == "stopped"


def test_moat_measure(app_client: TestClient) -> None:
    response = app_client.post("/moat/measure", headers=_auth_headers())
    assert response.status_code == 200
    payload = response.json()
    assert "payload" in payload
    assert "metrics" in payload["payload"]


def test_submit_feature_proposal(app_client: TestClient) -> None:
    response = app_client.post(
        "/moat/proposals",
        headers=_auth_headers(),
        json={"name": "New data pipeline", "description": "Adds data telemetry"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["proposal_id"]
    assert "moat_score" in payload
