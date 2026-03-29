from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.api.kalshi_grid_api import router


def test_execution_health_endpoint_shape(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    class _A:
        config = type("Cfg", (), {"assets": ["BTC"], "timeframes": ["15m"]})()

        def get_signals(self, _limit):
            return [{"ts": "2099-01-01T00:00:00+00:00"}]

        def get_orders(self, _limit):
            return [{"ts": "2099-01-01T00:00:00+00:00", "success": False, "error": "Risk blocked: cap"}]

        def get_fills(self, _limit):
            return []

    class _G:
        agents = [_A()]

    monkeypatch.setattr("web.api.kalshi_grid_api._get_grid", lambda: _G())
    resp = client.get("/api/v1/kalshi-grid/execution-health")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("signals", "orders_attempted", "orders_sent", "fills", "risk_rejections", "state", "per_asset_timeframe"):
        assert key in data
    assert data["state"] == "signals_rejected_by_risk"
