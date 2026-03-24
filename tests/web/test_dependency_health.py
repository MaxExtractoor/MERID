import importlib.util
from pathlib import Path
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _load_dependency_health():
    path = Path(__file__).resolve().parents[2] / "web" / "api" / "dependency_health.py"
    spec = importlib.util.spec_from_file_location("dependency_health_test", path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec and spec.loader
    spec.loader.exec_module(module)  # type: ignore[arg-type]
    return module


dh = _load_dependency_health()


def _fresh_iso(seconds_ago: int = 10) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(dh.router)
    return app


def test_dependency_health_healthy(monkeypatch):
    monkeypatch.delenv("MERID_DISABLE_KALSHI_WS", raising=False)
    monkeypatch.delenv("KALSHI_WS_DISABLED", raising=False)
    monkeypatch.delenv("MERID_DISABLE_MARKET_CATALOG", raising=False)
    monkeypatch.delenv("KALSHI_CATALOG_DISABLED", raising=False)

    monkeypatch.setattr(
        dh,
        "_load_ws_summary",
        lambda: {
            "running": True,
            "events_forwarded": 12,
            "ws_client": {
                "connected": True,
                "last_msg_ago_s": 5,
                "subscriptions": 4,
                "reconnect_count": 0,
            },
        },
    )
    monkeypatch.setattr(
        dh,
        "_load_catalog_summary",
        lambda: {
            "market_count": 25,
            "last_refresh": _fresh_iso(15),
            "categories": {"crypto": 20},
            "assets": {"BTC": 10, "ETH": 5},
            "timeframes": {"15m": 5, "1h": 5},
            "running": True,
            "refresh_count": 3,
        },
    )

    client = TestClient(_make_app())
    resp = client.get("/api/v1/dependencies/health")
    data = resp.json()

    assert resp.status_code == 200
    assert data["overall_status"] == "healthy"
    assert data["dependencies"]["kalshi_websocket"]["status"] == "healthy"
    assert data["dependencies"]["market_catalog"]["status"] == "healthy"


def test_dependency_health_degraded_ws(monkeypatch):
    monkeypatch.setattr(
        dh,
        "_load_ws_summary",
        lambda: {
            "running": True,
            "ws_client": {"connected": True, "last_msg_ago_s": dh.WS_MAX_STALE_S + 10},
        },
    )
    monkeypatch.setattr(
        dh,
        "_load_catalog_summary",
        lambda: {
            "market_count": 5,
            "last_refresh": _fresh_iso(30),
            "categories": {},
            "assets": {},
            "timeframes": {},
            "running": True,
            "refresh_count": 1,
        },
    )

    client = TestClient(_make_app())
    resp = client.get("/api/v1/dependencies/health")
    data = resp.json()

    ws = data["dependencies"]["kalshi_websocket"]
    assert ws["status"] == "degraded"
    assert "stale_stream" in ws["issues"]
    assert data["overall_status"] == "degraded"


def test_dependency_health_disabled_env(monkeypatch):
    monkeypatch.setenv("MERID_DISABLE_KALSHI_WS", "true")
    monkeypatch.setenv("MERID_DISABLE_MARKET_CATALOG", "1")

    client = TestClient(_make_app())
    resp = client.get("/api/v1/dependencies/health")
    data = resp.json()

    assert data["dependencies"]["kalshi_websocket"]["status"] == "disabled"
    assert data["dependencies"]["market_catalog"]["status"] == "disabled"
    assert data["overall_status"] in ("healthy", "disabled")
