"""Tests for web/api/orders_api.py"""

import pytest
from starlette.testclient import TestClient

from web.main import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_orders_endpoints_require_auth(client, monkeypatch):
    """Test that orders endpoints require authentication."""
    monkeypatch.setenv("MERID_ENV", "production")
    monkeypatch.delenv("MERID_SKIP_AUTH_FOR_TESTS", raising=False)
    monkeypatch.delenv("MERID_SINGLE_USER_OPERATOR", raising=False)
    resp = client.get("/api/v1/trading/orders/open")
    assert resp.status_code == 401


def test_orders_endpoints_with_auth(client):
    """Test that orders endpoints work with authentication."""
    from web.api.auth import get_current_session

    fake_session = {"user_id": "test", "role": "user"}
    client.app.dependency_overrides[get_current_session] = lambda: fake_session

    try:
        resp = client.get("/api/v1/trading/orders/open")
        assert resp.status_code == 200
        data = resp.json()
        # Endpoint may be a live implementation or a stub; both return a dict
        assert isinstance(data, dict)
    finally:
        del client.app.dependency_overrides[get_current_session]


def test_orders_endpoints_invalid_auth(client):
    """Test that invalid auth returns 401."""
    from web.api.auth import get_current_session

    from fastapi import HTTPException

    def invalid_session():
        raise HTTPException(status_code=401, detail="Invalid session")

    client.app.dependency_overrides[get_current_session] = invalid_session

    try:
        resp = client.get("/api/v1/trading/orders/open")
        assert resp.status_code == 401
        # Ensure no internal details leaked
        assert "Internal server error" not in resp.json().get("detail", "")
    finally:
        del client.app.dependency_overrides[get_current_session]
