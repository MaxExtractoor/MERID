import importlib.util
import sys
import types
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_MODULE_PATH = _REPO_ROOT / "web" / "api" / "kalshi_grid_api.py"
_SPEC = importlib.util.spec_from_file_location("kalshi_grid_api", _MODULE_PATH)
kalshi_grid_api = importlib.util.module_from_spec(_SPEC)  # type: ignore[arg-type]
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(kalshi_grid_api)  # type: ignore[attr-defined]


class DummyGrid:
    """Lightweight grid stub with a preset summary."""

    def __init__(self, summary: dict):
        self._summary = summary

    def summary(self) -> dict:
        return self._summary


def _make_base_summary():
    return {
        "venue_health": {"connected": True, "circuit": {"state": "closed"}, "error_rate": 0.0},
        "metrics": {},
        "portfolio_risk": {},
        "session": {},
        "running": True,
    }


@pytest.mark.asyncio
async def test_grid_health_dependencies_healthy(monkeypatch):
    now = datetime.now(timezone.utc)
    grid = DummyGrid(_make_base_summary())
    monkeypatch.setattr(kalshi_grid_api, "_get_grid", lambda: grid)

    mock_catalog = types.SimpleNamespace(
        summary=lambda: {
            "market_count": 25,
            "last_refresh": now.isoformat(),
            "refresh_count": 2,
            "categories": {},
            "assets": {},
            "timeframes": {},
            "running": True,
        }
    )
    mock_ws = types.SimpleNamespace(summary=lambda: {"running": True, "events_forwarded": 10, "subscribed_tickers": 4})

    # Stub out heavy venue modules to avoid importing real dependencies
    cat_module = types.ModuleType("market_catalog")
    cat_module.get_market_catalog = lambda: mock_catalog
    ws_module = types.ModuleType("ws_bridge")
    ws_module.get_ws_bridge = lambda: mock_ws
    kalshi_pkg = types.ModuleType("merid.event_venues.kalshi")
    event_pkg = types.ModuleType("merid.event_venues")
    merid_pkg = types.ModuleType("merid")

    kalshi_pkg.market_catalog = cat_module
    kalshi_pkg.ws_bridge = ws_module
    event_pkg.kalshi = kalshi_pkg
    merid_pkg.event_venues = event_pkg

    monkeypatch.setitem(sys.modules, "merid", merid_pkg)
    monkeypatch.setitem(sys.modules, "merid.event_venues", event_pkg)
    monkeypatch.setitem(sys.modules, "merid.event_venues.kalshi", kalshi_pkg)
    monkeypatch.setitem(sys.modules, "merid.event_venues.kalshi.market_catalog", cat_module)
    monkeypatch.setitem(sys.modules, "merid.event_venues.kalshi.ws_bridge", ws_module)

    result = await kalshi_grid_api.grid_health()

    assert result["status"] == "healthy"
    assert result["dependencies"]["market_catalog"]["status"] == "healthy"
    assert result["dependencies"]["kalshi_websocket"]["status"] == "healthy"
    assert result["dependency_summary"]["healthy"] == 2


@pytest.mark.asyncio
async def test_grid_health_dependencies_degraded(monkeypatch):
    grid = DummyGrid(_make_base_summary())
    monkeypatch.setattr(kalshi_grid_api, "_get_grid", lambda: grid)

    stale_time = (datetime.now(timezone.utc) - timedelta(seconds=kalshi_grid_api.CATALOG_STALE_THRESHOLD_S + 10)).isoformat()

    mock_catalog = types.SimpleNamespace(
        summary=lambda: {
            "market_count": 0,
            "last_refresh": stale_time,
            "refresh_count": 1,
            "categories": {},
            "assets": {},
            "timeframes": {},
            "running": False,
        }
    )
    mock_ws = types.SimpleNamespace(summary=lambda: {"running": False, "events_forwarded": 0, "subscribed_tickers": 0})

    cat_module = types.ModuleType("market_catalog")
    cat_module.get_market_catalog = lambda: mock_catalog
    ws_module = types.ModuleType("ws_bridge")
    ws_module.get_ws_bridge = lambda: mock_ws
    kalshi_pkg = types.ModuleType("merid.event_venues.kalshi")
    event_pkg = types.ModuleType("merid.event_venues")
    merid_pkg = types.ModuleType("merid")

    kalshi_pkg.market_catalog = cat_module
    kalshi_pkg.ws_bridge = ws_module
    event_pkg.kalshi = kalshi_pkg
    merid_pkg.event_venues = event_pkg

    monkeypatch.setitem(sys.modules, "merid", merid_pkg)
    monkeypatch.setitem(sys.modules, "merid.event_venues", event_pkg)
    monkeypatch.setitem(sys.modules, "merid.event_venues.kalshi", kalshi_pkg)
    monkeypatch.setitem(sys.modules, "merid.event_venues.kalshi.market_catalog", cat_module)
    monkeypatch.setitem(sys.modules, "merid.event_venues.kalshi.ws_bridge", ws_module)

    result = await kalshi_grid_api.grid_health()

    assert result["status"] == "critical"
    assert result["dependencies"]["market_catalog"]["status"] == "degraded"
    assert result["dependencies"]["kalshi_websocket"]["status"] == "down"
    assert result["dependency_summary"]["degraded"] == 1
    assert result["dependency_summary"]["down"] == 1
    assert any("Market catalog" in issue for issue in result["issues"])
    assert any("WebSocket feed" in issue for issue in result["issues"])
