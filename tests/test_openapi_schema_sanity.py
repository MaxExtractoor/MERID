"""OpenAPI schema sanity check for kalshi-only profile.

Ensures the app's ``/openapi.json`` exposes a minimum number of paths
and that core Kalshi operations are present with expected methods.

Run:
    MERID_PROFILE=kalshi-only pytest tests/test_openapi_schema_sanity.py -v
"""
from __future__ import annotations

import os
from typing import Dict, Set

import pytest
from starlette.testclient import TestClient


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch
    m = MonkeyPatch()
    yield m
    m.undo()


@pytest.fixture(scope="module")
def app(monkeypatch_module):
    """Create the FastAPI app in kalshi-only profile."""
    monkeypatch_module.setenv("MERID_PROFILE", "kalshi-only")

    async def _noop_lifespan(app):
        yield

    from web.main import create_app
    return create_app(lifespan=_noop_lifespan)


@pytest.fixture(scope="module")
def openapi_schema(app) -> Dict:
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/openapi.json")
    assert resp.status_code == 200, f"Failed to fetch /openapi.json: {resp.status_code}"
    return resp.json()


# ── Minimum path count ────────────────────────────────────────────────
# Bump this number as the app grows; lowering it should require review.
MIN_PATH_COUNT = 30


# ── Core operations that MUST appear in kalshi-only profile ───────────
REQUIRED_OPERATIONS: list[tuple[str, str]] = [
    ("get", "/api/v1/kalshi/positions"),
    ("get", "/api/v1/kalshi/orders"),
    ("get", "/api/v1/kalshi/fills"),
    ("get", "/api/v1/kalshi/pnl"),
    ("get", "/api/v1/kalshi/health"),
    ("get", "/api/v1/kalshi/balance"),
    ("get", "/api/v1/system/health"),
    ("get", "/api/v1/system/contract-health"),
    ("get", "/api/v1/operator/summary"),
]


class TestOpenAPISchemaSanity:
    """Structural sanity checks on the OpenAPI schema."""

    def test_schema_has_minimum_paths(self, openapi_schema):
        """Schema must expose at least MIN_PATH_COUNT paths."""
        paths = openapi_schema.get("paths", {})
        assert len(paths) >= MIN_PATH_COUNT, (
            f"OpenAPI schema only has {len(paths)} paths "
            f"(minimum: {MIN_PATH_COUNT}). App may not have loaded correctly."
        )

    def test_core_operations_present(self, openapi_schema):
        """Core Kalshi operations must appear with expected HTTP methods."""
        paths = openapi_schema.get("paths", {})
        missing = []
        for method, path in REQUIRED_OPERATIONS:
            if path not in paths:
                missing.append(f"  {method.upper():6s}  {path}  (path missing)")
            elif method not in paths[path]:
                available = ", ".join(paths[path].keys())
                missing.append(
                    f"  {method.upper():6s}  {path}  "
                    f"(method missing; available: {available})"
                )

        assert not missing, (
            f"Required operations missing from OpenAPI schema:\n"
            + "\n".join(missing)
        )

    def test_schema_title_and_version(self, openapi_schema):
        """Schema must have a title and version."""
        info = openapi_schema.get("info", {})
        assert info.get("title"), "OpenAPI schema missing 'info.title'"
        assert info.get("version"), "OpenAPI schema missing 'info.version'"

    def test_no_empty_path_objects(self, openapi_schema):
        """Every path must have at least one operation defined."""
        paths = openapi_schema.get("paths", {})
        empty = [p for p, ops in paths.items() if not ops]
        assert not empty, f"Paths with no operations: {empty}"
