"""Tests for GET /api/v1/ct/market-states (AUDIT-13).

Covers:
  - No filters → all candidates returned
  - assets= filter → only matching assets
  - timeframe= filter → only matching timeframe
  - assets= + timeframe= combined filter
  - Case-insensitive asset and timeframe matching
  - Graceful degradation when CT singleton unavailable
"""

from __future__ import annotations

import importlib.util
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── Module loading ─────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_ct_api_module():
    """Load web/api/ct_api.py directly, bypassing the web.api.__init__ chain."""
    module_path = _REPO_ROOT / "web" / "api" / "ct_api.py"
    mod_name = "_test_web_api_ct_api"
    spec = importlib.util.spec_from_file_location(mod_name, module_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


_ct_api_mod = _load_ct_api_module()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_candidates(specs: List[tuple]) -> List[Dict[str, Any]]:
    return [
        {"underlying": asset, "timeframe": tf, "ticker": f"KX{asset}-{tf.upper()}"}
        for asset, tf in specs
    ]


def _make_trader_mock(candidates: List[Dict]):
    trader = MagicMock()
    trader.status.return_value = {"candidates": candidates, "running": True}
    return trader


@contextmanager
def _patch_ct_module(mock_trader):
    """Inject a mock CT module into sys.modules so the lazy import succeeds."""
    ct_module = MagicMock()
    ct_module.get_continuous_trader.return_value = mock_trader
    old = sys.modules.get("merid.trading.kalshi_continuous_trader")
    sys.modules["merid.trading.kalshi_continuous_trader"] = ct_module
    try:
        yield ct_module
    finally:
        if old is None:
            sys.modules.pop("merid.trading.kalshi_continuous_trader", None)
        else:
            sys.modules["merid.trading.kalshi_continuous_trader"] = old


def _make_app():
    app = FastAPI()
    app.include_router(_ct_api_mod.router)
    return app


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestCTMarketStatesAPI:
    def _client_and_mock(self, specs):
        candidates = _make_candidates(specs)
        mock_trader = _make_trader_mock(candidates)
        return TestClient(_make_app(), raise_server_exceptions=False), mock_trader

    def test_no_filter_returns_all(self):
        specs = [("BTC", "15m"), ("ETH", "1h"), ("SOL", "daily")]
        client, mock_trader = self._client_and_mock(specs)
        with _patch_ct_module(mock_trader):
            resp = client.get("/api/v1/ct/market-states")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 3
        assert data["assets_filter"] is None
        assert data["timeframe_filter"] is None

    def test_assets_filter_returns_subset(self):
        specs = [("BTC", "15m"), ("ETH", "1h"), ("SOL", "daily")]
        client, mock_trader = self._client_and_mock(specs)
        with _patch_ct_module(mock_trader):
            resp = client.get("/api/v1/ct/market-states?assets=BTC,ETH")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert {m["underlying"] for m in data["market_states"]} == {"BTC", "ETH"}

    def test_timeframe_filter(self):
        specs = [("BTC", "15m"), ("ETH", "15m"), ("BTC", "1h")]
        client, mock_trader = self._client_and_mock(specs)
        with _patch_ct_module(mock_trader):
            resp = client.get("/api/v1/ct/market-states?timeframe=15m")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert all(m["timeframe"] == "15m" for m in data["market_states"])

    def test_combined_asset_and_timeframe_filter(self):
        specs = [("BTC", "15m"), ("ETH", "15m"), ("BTC", "1h"), ("SOL", "15m")]
        client, mock_trader = self._client_and_mock(specs)
        with _patch_ct_module(mock_trader):
            resp = client.get("/api/v1/ct/market-states?assets=BTC,ETH&timeframe=15m")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert {(m["underlying"], m["timeframe"]) for m in data["market_states"]} == {
            ("BTC", "15m"), ("ETH", "15m")
        }

    def test_assets_filter_case_insensitive(self):
        specs = [("BTC", "15m"), ("ETH", "1h")]
        client, mock_trader = self._client_and_mock(specs)
        with _patch_ct_module(mock_trader):
            resp = client.get("/api/v1/ct/market-states?assets=btc,eth")
        assert resp.status_code == 200
        assert resp.json()["count"] == 2

    def test_timeframe_filter_case_insensitive(self):
        specs = [("BTC", "15m"), ("ETH", "1H")]
        client, mock_trader = self._client_and_mock(specs)
        with _patch_ct_module(mock_trader):
            resp = client.get("/api/v1/ct/market-states?timeframe=1h")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["market_states"][0]["underlying"] == "ETH"

    def test_no_match_returns_empty(self):
        specs = [("BTC", "15m"), ("ETH", "1h")]
        client, mock_trader = self._client_and_mock(specs)
        with _patch_ct_module(mock_trader):
            resp = client.get("/api/v1/ct/market-states?assets=SOL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["market_states"] == []

    def test_unavailable_returns_graceful_fallback(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        # Don't inject any mock — allow the real import to fail (no credentials)
        resp = client.get("/api/v1/ct/market-states")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unavailable"
        assert data["count"] == 0
        assert data["market_states"] == []

    def test_response_includes_filter_metadata(self):
        specs = [("BTC", "15m"), ("ETH", "1h")]
        client, mock_trader = self._client_and_mock(specs)
        with _patch_ct_module(mock_trader):
            resp = client.get("/api/v1/ct/market-states?assets=BTC&timeframe=15m")
        data = resp.json()
        assert data["assets_filter"] == ["BTC"]
        assert data["timeframe_filter"] == "15m"
