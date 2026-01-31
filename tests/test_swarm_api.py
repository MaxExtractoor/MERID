from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from swarm.swarm_lab import SwarmLabOrchestrator, get_swarm_lab_orchestrator
from web.api.swarm import router as swarm_router


@pytest.fixture(name="app_client")
def app_client_fixture(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(swarm_router)

    orchestrator = SwarmLabOrchestrator()

    async def start_mock(*_, **kwargs) -> None:
        orchestrator._status = orchestrator._status.STARTING  # type: ignore[attr-defined]
        orchestrator._status = orchestrator._status.RUNNING  # type: ignore[attr-defined]

    async def stop_mock() -> None:
        orchestrator._status = orchestrator._status.STOPPED

    orchestrator.start = start_mock  # type: ignore[assignment]
    orchestrator.stop = stop_mock  # type: ignore[assignment]

    monkeypatch.setattr("swarm.swarm_lab.get_swarm_lab_orchestrator", lambda: orchestrator)
    return TestClient(app)


def test_swarm_status_endpoint(app_client: TestClient) -> None:
    response = app_client.get("/swarm/status")
    assert response.status_code == 200
    payload = response.json()
    assert "metrics" in payload
    assert "status" in payload


def test_swarm_start_and_stop(app_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrator = SwarmLabOrchestrator()

    async def start_mock(*_, **kwargs) -> None:
        orchestrator._status = orchestrator._status.RUNNING  # type: ignore[attr-defined]

    async def stop_mock() -> None:
        orchestrator._status = orchestrator._status.STOPPED

    orchestrator.start = start_mock  # type: ignore[assignment]
    orchestrator.stop = stop_mock  # type: ignore[assignment]
    monkeypatch.setattr("swarm.swarm_lab.get_swarm_lab_orchestrator", lambda: orchestrator)

    response = app_client.post("/swarm/start")
    assert response.status_code == 200
    assert response.json()["status"] == "running"

    response = app_client.post("/swarm/stop")
    assert response.status_code == 200
    assert response.json()["status"] == "stopped"
