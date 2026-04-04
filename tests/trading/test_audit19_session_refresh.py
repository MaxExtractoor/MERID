"""Tests for AUDIT-19 minimal session refresh / 401 handling.

Covers:
  - GET  /api/v1/auth/session      returns 401 + expired=True on expired session
  - GET  /api/v1/auth/session      returns near_expiry hint when session is close to expiry
  - POST /api/v1/auth/session/refresh  extends a valid session
  - POST /api/v1/auth/session/refresh  returns 401 + expired=True on expired session
  - UserManager.refresh_session()  extends expiry in place
  - UserManager.is_session_near_expiry() detects near-expiry window
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── Module loading ─────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_auth_module():
    """Load web/api/auth.py directly, bypassing the web.api.__init__ chain."""
    module_path = _REPO_ROOT / "web" / "api" / "auth.py"
    mod_name = "_test_web_api_auth"
    spec = importlib.util.spec_from_file_location(mod_name, module_path)
    mod = importlib.util.module_from_spec(spec)
    # Stub require_dependency so email-validator absence doesn't abort import
    with patch("utils.deps.require_dependency"):
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
    return mod


_auth_mod = _load_auth_module()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def auth_client():
    """TestClient wired to the auth router (no heavy web.api chain)."""
    app = FastAPI()
    app.include_router(_auth_mod.router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def user_manager_fresh():
    """A fresh UserManager instance (not the global singleton)."""
    from auth.user_manager import UserManager
    return UserManager()


# ── UserManager unit tests ────────────────────────────────────────────────────

class TestUserManagerSessionRefresh:
    def test_refresh_extends_expiry(self, user_manager_fresh):
        um = user_manager_fresh
        from auth.user_manager import User
        user = User(user_id="u1", username="alice")
        um._users["u1"] = user
        session = um.create_session("u1", duration_seconds=10)
        original_expiry = session.expires_at

        refreshed = um.refresh_session(session.session_id, extend_seconds=3600)
        assert refreshed is not None
        assert refreshed.expires_at > original_expiry
        assert refreshed.expires_at == pytest.approx(time.time() + 3600, abs=5)

    def test_refresh_expired_session_returns_none(self, user_manager_fresh):
        um = user_manager_fresh
        from auth.user_manager import User
        user = User(user_id="u2", username="bob")
        um._users["u2"] = user
        session = um.create_session("u2", duration_seconds=1)
        session.expires_at = time.time() - 1
        result = um.refresh_session(session.session_id)
        assert result is None

    def test_refresh_unknown_session_returns_none(self, user_manager_fresh):
        result = user_manager_fresh.refresh_session("nonexistent-token")
        assert result is None

    def test_is_session_near_expiry_true_when_within_window(self, user_manager_fresh):
        um = user_manager_fresh
        from auth.user_manager import User
        user = User(user_id="u3", username="carol")
        um._users["u3"] = user
        session = um.create_session("u3", duration_seconds=1800)
        assert um.is_session_near_expiry(session.session_id, window_seconds=3600) is True

    def test_is_session_near_expiry_false_when_outside_window(self, user_manager_fresh):
        um = user_manager_fresh
        from auth.user_manager import User
        user = User(user_id="u4", username="dave")
        um._users["u4"] = user
        session = um.create_session("u4", duration_seconds=90000)
        assert um.is_session_near_expiry(session.session_id, window_seconds=3600) is False

    def test_is_session_near_expiry_false_for_expired_session(self, user_manager_fresh):
        um = user_manager_fresh
        from auth.user_manager import User
        user = User(user_id="u5", username="eve")
        um._users["u5"] = user
        session = um.create_session("u5", duration_seconds=1)
        session.expires_at = time.time() - 1
        assert um.is_session_near_expiry(session.session_id, window_seconds=3600) is False


# ── API endpoint tests ────────────────────────────────────────────────────────

class TestSessionValidateAPI:
    def test_expired_session_returns_401_with_expired_flag(self, auth_client):
        """AUDIT-19: 401 on expired session must include expired=True."""
        from auth.user_manager import user_manager, User
        user = User(user_id="api_u1", username="api_alice")
        user_manager._users["api_u1"] = user
        session = user_manager.create_session("api_u1", duration_seconds=1)
        session.expires_at = time.time() - 1

        resp = auth_client.get(
            "/api/v1/auth/session",
            headers={"X-Session-ID": session.session_id},
        )
        assert resp.status_code == 401
        detail = resp.json()["detail"]
        assert detail["expired"] is True
        assert "expired" in detail["message"].lower()

    def test_missing_session_id_returns_401_expired_false(self, auth_client):
        resp = auth_client.get("/api/v1/auth/session")
        assert resp.status_code == 401
        detail = resp.json()["detail"]
        assert detail["expired"] is False

    def test_valid_session_includes_near_expiry_flag(self, auth_client):
        """near_expiry=True when session expires within the 1-hour window."""
        from auth.user_manager import user_manager, User
        user = User(user_id="api_u2", username="api_bob")
        user_manager._users["api_u2"] = user
        session = user_manager.create_session("api_u2", duration_seconds=600)

        resp = auth_client.get(
            "/api/v1/auth/session",
            headers={"X-Session-ID": session.session_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "valid"
        assert data["near_expiry"] is True

    def test_valid_session_long_ttl_near_expiry_false(self, auth_client):
        from auth.user_manager import user_manager, User
        user = User(user_id="api_u3", username="api_carol")
        user_manager._users["api_u3"] = user
        session = user_manager.create_session("api_u3", duration_seconds=172800)

        resp = auth_client.get(
            "/api/v1/auth/session",
            headers={"X-Session-ID": session.session_id},
        )
        assert resp.status_code == 200
        assert resp.json()["near_expiry"] is False


class TestSessionRefreshAPI:
    def test_refresh_valid_session_returns_200_and_new_expiry(self, auth_client):
        """POST /session/refresh must extend expiry and return expires_at."""
        from auth.user_manager import user_manager, User
        user = User(user_id="api_u4", username="api_dave")
        user_manager._users["api_u4"] = user
        session = user_manager.create_session("api_u4", duration_seconds=600)
        old_expiry = session.expires_at

        resp = auth_client.post(
            "/api/v1/auth/session/refresh",
            headers={"X-Session-ID": session.session_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "refreshed"
        assert data["expires_at"] > old_expiry

    def test_refresh_expired_session_returns_401_expired_flag(self, auth_client):
        """AUDIT-19: refresh of expired session must return 401 expired=True."""
        from auth.user_manager import user_manager, User
        user = User(user_id="api_u5", username="api_eve")
        user_manager._users["api_u5"] = user
        session = user_manager.create_session("api_u5", duration_seconds=1)
        session.expires_at = time.time() - 1

        resp = auth_client.post(
            "/api/v1/auth/session/refresh",
            headers={"X-Session-ID": session.session_id},
        )
        assert resp.status_code == 401
        detail = resp.json()["detail"]
        assert detail["expired"] is True
        assert "expired" in detail["message"].lower()

    def test_refresh_missing_session_id_returns_401(self, auth_client):
        resp = auth_client.post("/api/v1/auth/session/refresh")
        assert resp.status_code == 401
        assert resp.json()["detail"]["expired"] is False
