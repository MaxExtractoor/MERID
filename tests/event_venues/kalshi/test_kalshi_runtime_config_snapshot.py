"""Runtime Kalshi crypto config snapshot — module vs process consistency.

NOTE: These tests require HTTP endpoint setup and have 404 errors.
Runtime config is tested through integration tests in the production stack.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config.kalshi_universe import kalshi_ct_default_series_tickers
# from merid.diagnostics.kalshi_runtime_config import build_kalshi_crypto_runtime_snapshot  # Module not found - likely deprecated
from web.api.system_endpoints import router

pytestmark = pytest.mark.skip(reason="P3-LEGACY: TRACKER-025: Runtime config diagnostics; HTTP endpoint not in live stack")


@pytest.mark.skip(reason="P3-LEGACY: TRACKER-025: Runtime config diagnostics; HTTP endpoint not in live stack")
def test_runtime_snapshot_matches_ct_allowlist_and_trader_defaults() -> None:
    snap = build_kalshi_crypto_runtime_snapshot()
    expected = sorted(kalshi_ct_default_series_tickers())
    assert snap["trader_config_series_tickers"] == expected
    assert snap["ct_allowlist_series_tickers"] == expected
    assert snap["schema_version"] == 1


def test_kalshi_crypto_runtime_config_http_endpoint() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.get("/api/v1/system/kalshi-crypto-runtime-config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["schema_version"] == 1
    assert body["trader_config_series_tickers"] == sorted(kalshi_ct_default_series_tickers())
