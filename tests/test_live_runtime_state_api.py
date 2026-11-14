"""Regression tests for the live runtime state API."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from merid.observability.live_runtime_state import (
    LiveRuntimeState,
    get_live_runtime_state,
)
from web.api.live_runtime_state_router import router


class TestLiveRuntimeStateAPI:
    """Ensure the runtime-state endpoint returns a serializable 200."""

    @pytest.fixture
    def state_path(self) -> Path:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            f.write(json.dumps({"state": "LIVE_ENTRIES_ENABLED"}))
            path = Path(f.name)
        yield path
        try:
            os.unlink(path)
        except OSError:
            pass

    @pytest.fixture(autouse=True)
    def reset_singleton(self, state_path: Path):
        """Reset the global singleton so tests have a clean state."""
        import merid.observability.live_runtime_state as lrsm

        lrsm._live_runtime_state = None
        os.environ["MERID_LIVE_RUNTIME_STATE_PATH"] = str(state_path)
        yield
        lrsm._live_runtime_state = None
        os.environ.pop("MERID_LIVE_RUNTIME_STATE_PATH", None)

    @pytest.fixture
    def client(self, state_path: Path) -> TestClient:
        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        return TestClient(app)

    def test_get_endpoint_returns_200_with_entry_halted(self, client: TestClient):
        response = client.get("/api/v1/live-runtime-state/")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["state"] in {
            "LIVE_ENTRIES_ENABLED",
            "LIVE_ENTRIES_HALTED",
        }
        assert isinstance(data["entry_halted"], bool)
        assert "reason" in data
        assert "reason_codes" in data
        assert "transition_history" in data

    def test_to_dict_contains_entry_halted(self, state_path: Path):
        state = get_live_runtime_state(state_path)
        d = state.to_dict()
        assert "entry_halted" in d
        assert d["entry_halted"] is False


class TestLiveRuntimeStateOperatorActions:
    """Halt/recover endpoint auth + verified-recovery contract (2026-11-14).

    The UI emergency control previously POSTed /release with an empty body and
    no session header -> guaranteed 403/401.  /recover is the operator release
    path: authenticated, evidence-gated, fail-closed.
    """

    @pytest.fixture
    def state_path(self) -> Path:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            f.write(json.dumps({"state": "LIVE_ENTRIES_ENABLED"}))
            path = Path(f.name)
        yield path
        try:
            os.unlink(path)
        except OSError:
            pass

    @pytest.fixture(autouse=True)
    def reset_singleton(self, state_path: Path):
        import merid.observability.live_runtime_state as lrsm

        lrsm._live_runtime_state = None
        os.environ["MERID_LIVE_RUNTIME_STATE_PATH"] = str(state_path)
        yield
        lrsm._live_runtime_state = None
        os.environ.pop("MERID_LIVE_RUNTIME_STATE_PATH", None)

    @pytest.fixture
    def client(self) -> TestClient:
        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        return TestClient(app)

    @pytest.fixture(autouse=True)
    def _no_auth_bypass(self, monkeypatch):
        for var in (
            "MERID_SKIP_AUTH_FOR_TESTS",
            "MERID_SINGLE_USER_OPERATOR",
            "MERID_DEV_AUTH_BYPASS",
        ):
            monkeypatch.delenv(var, raising=False)

    @pytest.fixture
    def auth(self, monkeypatch):
        monkeypatch.setenv("MERID_SKIP_AUTH_FOR_TESTS", "1")

    def _halted_state(self):
        state = get_live_runtime_state()
        state.halt_entries("test_halt", ["RECONCILIATION_DIVERGENCE"])
        return state

    def test_halt_requires_session(self, client: TestClient):
        resp = client.post("/api/v1/live-runtime-state/halt", json={})
        assert resp.status_code == 401

    def test_recover_requires_session(self, client: TestClient):
        resp = client.post("/api/v1/live-runtime-state/recover", json={})
        assert resp.status_code == 401

    def test_release_requires_session(self, client: TestClient):
        resp = client.post("/api/v1/live-runtime-state/release", json={})
        assert resp.status_code == 401

    def test_halt_with_session(self, client: TestClient, auth):
        resp = client.post(
            "/api/v1/live-runtime-state/halt",
            json={"reason": "operator_halt_ui"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["state"] == "LIVE_ENTRIES_HALTED"

    def test_release_empty_body_still_refused(self, client: TestClient, auth):
        """The manual-token /release contract is unchanged: empty assertion
        must still 403 — /recover is the evidence path, not a bypass."""
        self._halted_state()
        resp = client.post("/api/v1/live-runtime-state/release", json={})
        assert resp.status_code == 403

    def test_recover_refused_when_evidence_missing(
        self, client: TestClient, auth
    ):
        """In a bare test process the recovery probes cannot verify exits,
        router, reconciliation, etc. — release must refuse fail-closed."""
        self._halted_state()
        resp = client.post("/api/v1/live-runtime-state/recover", json={})
        assert resp.status_code == 409, resp.text
        detail = resp.json()["detail"]
        assert detail["status"] == "recovery_refused"
        assert "missing" in detail
        # State must remain halted — no partial enablement.
        assert get_live_runtime_state().state == "LIVE_ENTRIES_HALTED"

    def test_recover_enables_with_complete_evidence(
        self, client: TestClient, auth, monkeypatch
    ):
        from datetime import datetime, timezone

        import web.api.live_runtime_state_router as router_mod

        evidence = {
            "resolved_failure": True,
            "fresh_reconciliation": True,
            "fill_watermark": datetime(2026, 11, 14, 1, 30, tzinfo=timezone.utc),
            "fill_watermark_at_halt": datetime(2026, 11, 14, 1, 20, tzinfo=timezone.utc),
            "no_critical_discrepancy": True,
            "exits_available": True,
            "router_available": True,
            "production_live": True,
            "reconciliation_snapshot_id": "recon_test",
        }
        monkeypatch.setattr(
            router_mod, "collect_runtime_recovery_evidence",
            lambda **kw: dict(evidence),
        )
        self._halted_state()
        resp = client.post(
            "/api/v1/live-runtime-state/recover",
            json={"reason": "operator_release_ui"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "enabled"
        assert data["recovery"] == "verified"
        assert get_live_runtime_state().state == "LIVE_ENTRIES_ENABLED"

    def test_recover_idempotent_when_already_enabled(
        self, client: TestClient, auth
    ):
        resp = client.post("/api/v1/live-runtime-state/recover", json={})
        assert resp.status_code == 200, resp.text
        assert resp.json()["recovery"] == "already_enabled"
