"""Kalshi-only profile smoke test: verify the app boots cleanly when
``MERID_PROFILE=kalshi-only`` and that operator-critical endpoints are
reachable while non-Kalshi routers are suppressed.

Run:
    pytest tests/test_kalshi_only_profile.py -v
"""
from __future__ import annotations

import os
from typing import Set, Tuple

import pytest
from starlette.testclient import TestClient

# ── Tier-1 endpoints that MUST be reachable in kalshi-only mode ─────────
# These power the core operator surfaces (Overview, Portfolio, Grid, etc.)
KALSHI_CORE_ENDPOINTS = [
    ("GET", "/api/v1/kalshi/health"),
    ("GET", "/api/v1/kalshi/balance"),
    ("GET", "/api/v1/kalshi/positions"),
    ("GET", "/api/v1/kalshi/orders"),
    ("GET", "/api/v1/kalshi/fills"),
    ("GET", "/api/v1/kalshi/pnl"),
    ("GET", "/api/v1/kalshi/catalog"),
    ("GET", "/api/v1/kalshi/markets"),
    ("GET", "/api/v1/kalshi-grid/status"),
    ("GET", "/api/v1/kalshi-grid/health"),
    ("GET", "/api/v1/kalshi-grid/mode"),
    ("GET", "/api/v1/operator/kill-switch-status"),
    ("GET", "/api/v1/operator/risk-state"),
    ("GET", "/api/v1/operator/summary"),
]

# ── Endpoints that MUST be absent (404) in kalshi-only mode ─────────────
# These belong to routers gated behind `if not _kalshi_only`.
NON_KALSHI_ENDPOINTS = [
    ("GET", "/api/v1/mining/status"),
    ("GET", "/api/v1/institutional/systems/status"),
    ("GET", "/api/v1/wallet/balance"),
    ("GET", "/api/v1/treasury/status"),
    ("GET", "/api/v1/recovery/status"),
    ("GET", "/api/v1/treasury/yield/sources"),
]


@pytest.fixture(scope="module")
def app_kalshi_only(monkeypatch_module):
    """Create a FastAPI app with the kalshi-only profile."""
    monkeypatch_module.setenv("MERID_PROFILE", "kalshi-only")

    async def _noop_lifespan(app):
        yield

    from web.main import create_app
    return create_app(lifespan=_noop_lifespan)


@pytest.fixture(scope="module")
def app_full(monkeypatch_module):
    """Create a FastAPI app with the full profile (for route-count comparison)."""
    monkeypatch_module.setenv("MERID_PROFILE", "full")

    async def _noop_lifespan(app):
        yield

    from web.main import create_app
    return create_app(lifespan=_noop_lifespan)


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch (pytest's built-in is function-scoped)."""
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def client_kalshi_only(app_kalshi_only) -> TestClient:
    return TestClient(app_kalshi_only, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def kalshi_only_routes(app_kalshi_only) -> Set[Tuple[str, str]]:
    """All (METHOD, path) pairs registered in kalshi-only mode."""
    routes: Set[Tuple[str, str]] = set()
    for route in app_kalshi_only.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            for method in route.methods:
                routes.add((method.upper(), route.path))
    return routes


class TestKalshiOnlyProfile:
    """Smoke tests for the kalshi-only deployment profile."""

    def test_app_boots(self, app_kalshi_only):
        """The app must create successfully in kalshi-only mode."""
        assert app_kalshi_only is not None

    @pytest.mark.parametrize("method,path", KALSHI_CORE_ENDPOINTS)
    def test_core_endpoint_reachable(self, client_kalshi_only, method, path):
        """Tier-1 Kalshi endpoints must not return 404 or 500.

        We accept 2xx (success), 4xx (auth/config guards), or 503
        (no Kalshi client configured) -- but never 404 (route missing)
        or 500 (unhandled crash).
        """
        resp = client_kalshi_only.request(method, path)
        assert resp.status_code not in (404, 405), (
            f"{method} {path} returned {resp.status_code} in kalshi-only mode"
        )

    @pytest.mark.parametrize("method,path", NON_KALSHI_ENDPOINTS)
    def test_non_kalshi_endpoint_absent(self, client_kalshi_only, method, path):
        """Non-Kalshi endpoints must return 404 when profile is kalshi-only.

        If this fails, a non-Kalshi router is leaking into the minimal
        profile -- check the ``if not _kalshi_only`` guards in main.py.
        """
        resp = client_kalshi_only.request(method, path)
        assert resp.status_code in (404, 405), (
            f"{method} {path} returned {resp.status_code} -- "
            f"expected 404/405 in kalshi-only mode (router not suppressed?)"
        )

    def test_kalshi_only_has_fewer_routes(self, app_kalshi_only, app_full):
        """The kalshi-only profile must register fewer routes than full."""
        ko_count = sum(
            1 for r in app_kalshi_only.routes
            if hasattr(r, "methods") and hasattr(r, "path")
        )
        full_count = sum(
            1 for r in app_full.routes
            if hasattr(r, "methods") and hasattr(r, "path")
        )
        assert ko_count < full_count, (
            f"kalshi-only has {ko_count} routes, full has {full_count} -- "
            f"profile gating may not be working"
        )

    def test_core_endpoints_return_json(self, client_kalshi_only):
        """A sample of core GET endpoints must return JSON (not HTML errors)."""
        sample = [
            "/api/v1/kalshi/health",
            "/api/v1/kalshi-grid/status",
            "/api/v1/operator/kill-switch-status",
        ]
        for path in sample:
            resp = client_kalshi_only.get(path)
            ct = resp.headers.get("content-type", "")
            assert "json" in ct.lower(), (
                f"GET {path} returned content-type '{ct}' -- expected JSON"
            )

    def test_route_count_sanity(self, kalshi_only_routes):
        """Kalshi-only should still have a meaningful number of routes."""
        assert len(kalshi_only_routes) > 30, (
            f"Only {len(kalshi_only_routes)} routes in kalshi-only -- "
            f"too few, app may not have loaded correctly"
        )
