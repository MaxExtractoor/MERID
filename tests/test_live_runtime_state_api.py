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
