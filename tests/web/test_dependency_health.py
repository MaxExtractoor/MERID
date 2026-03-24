"""Tests for dependency health endpoint."""

from datetime import datetime, timedelta, timezone
from importlib import util
from pathlib import Path
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from merid.monitoring import dependency_health as dh


def _client(monkeypatch, ws_summary, catalog_summary):
    """Build a TestClient with injected dependency summaries."""
    monkeypatch.setattr(dh, "_get_ws_summary", lambda: ws_summary)
    monkeypatch.setattr(dh, "_get_catalog_summary", lambda: catalog_summary)
    app = FastAPI()
    module_path = Path(__file__).resolve().parents[2] / "web" / "api" / "dependency_health.py"
    spec = util.spec_from_file_location("dependency_health_api", module_path)
    module = util.module_from_spec(spec)
    sys.modules["dependency_health_api"] = module
    assert spec and spec.loader  # type: ignore
    spec.loader.exec_module(module)  # type: ignore
    dependency_router = module.router

    app.include_router(dependency_router)
    return TestClient(app)


def test_dependency_health_healthy(monkeypatch):
    now = datetime.now(timezone.utc)
    ws_summary = {
        "running": True,
        "ws_client": {"connected": True, "last_msg_ago_s": 5.0, "messages_received": 10},
    }
    catalog_summary = {
        "market_count": 8,
        "last_refresh": now.isoformat(),
        "refresh_count": 2,
        "running": True,
        "assets": {"btc": 4},
        "timeframes": {"15m": 4},
    }
    client = _client(monkeypatch, ws_summary, catalog_summary)

    resp = client.get("/api/v1/dependencies/health")
    data = resp.json()

    assert resp.status_code == 200
    assert data["overall_status"] == "healthy"
    assert data["dependencies"]["kalshi_websocket"]["status"] == "healthy"
    assert data["dependencies"]["market_catalog"]["status"] == "healthy"


def test_dependency_health_degraded(monkeypatch):
    now = datetime.now(timezone.utc)
    ws_summary = {
        "running": True,
        "ws_client": {"connected": True, "last_msg_ago_s": 150.0, "messages_received": 1},
        "queue_depth": 1,
    }
    catalog_summary = {
        "market_count": 0,
        "last_refresh": (now - timedelta(minutes=20)).isoformat(),
        "refresh_count": 3,
        "running": True,
    }
    client = _client(monkeypatch, ws_summary, catalog_summary)

    resp = client.get("/api/v1/dependencies/health")
    data = resp.json()

    assert resp.status_code == 200
    assert data["overall_status"] == "degraded"
    assert data["dependencies"]["kalshi_websocket"]["status"] == "degraded"
    assert data["dependencies"]["market_catalog"]["status"] == "degraded"


def test_dependency_health_disabled(monkeypatch):
    now = datetime.now(timezone.utc)
    ws_summary = {"running": False, "ws_client": {"connected": False}}
    catalog_summary = {
        "market_count": 5,
        "last_refresh": now.isoformat(),
        "refresh_count": 1,
        "running": True,
    }
    monkeypatch.setenv("MERID_DISABLE_KALSHI_WS", "1")
    monkeypatch.setenv("MERID_DISABLE_MARKET_CATALOG", "true")

    client = _client(monkeypatch, ws_summary, catalog_summary)

    resp = client.get("/api/v1/dependencies/health")
    data = resp.json()

    assert resp.status_code == 200
    assert data["overall_status"] == "disabled"
    assert data["dependencies"]["kalshi_websocket"]["status"] == "disabled"
    assert data["dependencies"]["market_catalog"]["status"] == "disabled"
