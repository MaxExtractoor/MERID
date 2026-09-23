"""Kalshi profile + operator-surface smoke tests.

Current production contract:

- The production web app is ``web.main_15m_lean.app``.
- ``15m_live`` runtime mode requires ``MERID_PROFILE=kalshi_crypto_15m_v2``
  (enforced by ``merid.validation.profile_resolver.validate_15m_profile``).
  The legacy ``kalshi-only``/``full`` profiles are not valid for the 15m app.
- Tier-1 operator endpoints (``/api/v1/kalshi/*``, ``/api/v1/kalshi-grid/*``)
  must be registered on the app.
- Legacy non-Kalshi routers (mining / institutional / wallet / treasury /
  recovery) must not be registered on the 15m app.

The previous version of this file exercised per-profile router gating in the
old ``web.main.create_app``; that entrypoint is now a legacy compatibility
stub and the gating moved to ``validate_15m_profile`` at startup.

Run:
    pytest tests/test_kalshi_only_profile.py -v
"""
from __future__ import annotations

from typing import Set, Tuple

import pytest
from starlette.testclient import TestClient

# ── Tier-1 endpoints that MUST be registered on the 15m app ────────────
KALSHI_CORE_ENDPOINTS = [
    ("GET", "/api/v1/kalshi/health"),
    ("GET", "/api/v1/kalshi/balance"),
    ("GET", "/api/v1/kalshi/positions"),
    ("GET", "/api/v1/kalshi/orders"),
    ("GET", "/api/v1/kalshi/fills"),
    ("GET", "/api/v1/kalshi/pnl"),
    ("GET", "/api/v1/kalshi/catalog"),
    ("GET", "/api/v1/kalshi/markets"),
    ("GET", "/api/v1/kalshi-grid/summary"),
    ("GET", "/api/v1/kalshi-grid/edge-snapshots"),
    ("GET", "/api/v1/kalshi-grid/edge-aggregations"),
    ("GET", "/api/v1/kalshi-grid/scheduler-metrics"),
]

# ── Endpoints that MUST be absent on the 15m app ────────────────────────
# These belong to legacy non-Kalshi routers that the 15m entrypoint does
# not register.
NON_KALSHI_ENDPOINTS = [
    ("GET", "/api/v1/mining/status"),
    ("GET", "/api/v1/institutional/systems/status"),
    ("GET", "/api/v1/wallet/balance"),
    ("GET", "/api/v1/treasury/status"),
    ("GET", "/api/v1/recovery/status"),
    ("GET", "/api/v1/treasury/yield/sources"),
]


@pytest.fixture(scope="module")
def app_15m():
    """Import the production 15m app (module-level; lifespan not entered)."""
    from web.main_15m_lean import app
    return app


@pytest.fixture(scope="module")
def app_routes(app_15m) -> Set[Tuple[str, str]]:
    """All (METHOD, path) pairs registered on the 15m app."""
    routes: Set[Tuple[str, str]] = set()
    for route in app_15m.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            for method in route.methods:
                routes.add((method.upper(), route.path))
    return routes


class TestProfileValidation:
    """15m_live mode must pin MERID_PROFILE=kalshi_crypto_15m_v2."""

    def test_valid_profile_accepted(self):
        from merid.validation.profile_resolver import validate_15m_profile
        validate_15m_profile("kalshi_crypto_15m_v2", "15m_live")  # no raise

    @pytest.mark.parametrize("bad", ["kalshi-only", "full", "paper", "test", ""])
    def test_invalid_profiles_rejected(self, bad):
        from merid.validation.profile_resolver import validate_15m_profile
        with pytest.raises(ValueError):
            validate_15m_profile(bad, "15m_live")

    def test_other_runtime_modes_unvalidated(self):
        """Non-15m_live modes are outside this validator's scope."""
        from merid.validation.profile_resolver import validate_15m_profile
        validate_15m_profile("anything", "dev")  # no raise


class TestKalshiOperatorSurface:
    """Tier-1 Kalshi endpoints must be present on the 15m app."""

    def test_app_boots(self, app_15m):
        assert app_15m is not None

    @pytest.mark.parametrize("method,path", KALSHI_CORE_ENDPOINTS)
    def test_core_endpoint_registered(self, app_routes, method, path):
        assert (method, path) in app_routes, (
            f"{method} {path} is not registered on the 15m app"
        )

    @pytest.mark.parametrize("method,path", NON_KALSHI_ENDPOINTS)
    def test_non_kalshi_endpoint_absent(self, app_routes, method, path):
        """Legacy non-Kalshi routers must not be registered."""
        assert (method, path) not in app_routes, (
            f"{method} {path} is registered on the 15m app -- "
            f"legacy router leaked into the lean entrypoint"
        )

    def test_route_count_sanity(self, app_routes):
        assert len(app_routes) > 30, (
            f"Only {len(app_routes)} routes on the 15m app -- "
            f"app may not have loaded correctly"
        )

    def test_health_endpoint_returns_json(self, app_15m):
        """GET /api/v1/kalshi/health must return JSON (degrades gracefully)."""
        client = TestClient(app_15m, raise_server_exceptions=False)
        resp = client.get("/api/v1/kalshi/health")
        assert resp.status_code not in (404, 405), (
            f"GET /api/v1/kalshi/health returned {resp.status_code}"
        )
        ct = resp.headers.get("content-type", "")
        assert "json" in ct.lower(), (
            f"GET /api/v1/kalshi/health returned content-type '{ct}'"
        )
