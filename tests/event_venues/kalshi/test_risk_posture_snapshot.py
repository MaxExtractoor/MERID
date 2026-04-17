from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from merid.diagnostics.risk_posture import SNAPSHOT_SCHEMA_VERSION, build_risk_posture_snapshot
from web.api.system_endpoints import router

pytestmark = pytest.mark.kalshi_live_ready


def test_build_risk_posture_has_schema_and_execution_gate_shape() -> None:
    snap = build_risk_posture_snapshot()
    assert snap["schema_version"] == SNAPSHOT_SCHEMA_VERSION
    assert "execution_gate" in snap
    assert snap["execution_gate"] is not None
    eg = snap["execution_gate"]
    if isinstance(eg, dict) and "error" not in eg:
        assert "blocked" in eg
        assert "gate_state" in eg


def test_risk_posture_http_endpoint() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.get("/api/v1/system/risk-posture")
    assert r.status_code == 200
    body = r.json()
    assert body["schema_version"] == SNAPSHOT_SCHEMA_VERSION
    assert "risk_controller" in body
    assert "venue_gate" in body
