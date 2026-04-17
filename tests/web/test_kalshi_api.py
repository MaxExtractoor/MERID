"""Tests for web/api/kalshi_api.py"""

import pytest
from starlette.testclient import TestClient

from web.main import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_kalshi_endpoints_require_auth(client, monkeypatch):
    """Test that Kalshi endpoints require authentication."""
    monkeypatch.setenv("MERID_ENV", "production")
    monkeypatch.delenv("MERID_SKIP_AUTH_FOR_TESTS", raising=False)
    resp = client.get("/api/v1/kalshi/markets")
    assert resp.status_code == 401


def test_kalshi_endpoints_with_auth(client):
    """Test that Kalshi endpoints work with authentication."""
    from web.api.auth import get_current_session

    fake_session = {"user_id": "test", "role": "user"}
    client.app.dependency_overrides[get_current_session] = lambda: fake_session

    try:
        resp = client.get("/api/v1/kalshi/markets")
        assert resp.status_code == 200
    finally:
        del client.app.dependency_overrides[get_current_session]


def test_kalshi_endpoints_invalid_auth(client):
    """Test that invalid auth returns 401."""
    from web.api.auth import get_current_session
    from fastapi import HTTPException

    def invalid_session():
        raise HTTPException(status_code=401, detail="Invalid session")

    client.app.dependency_overrides[get_current_session] = invalid_session

    try:
        resp = client.get("/api/v1/kalshi/markets")
        assert resp.status_code == 401
    finally:
        del client.app.dependency_overrides[get_current_session]
