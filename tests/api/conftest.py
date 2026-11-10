"""Shared fixtures for tests/api."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """FastAPI TestClient for the 15m lean app."""
    # Lazy import: importing web.main_15m_lean at conftest scope runs the full
    # app module during pytest collection — including for runs that deselect
    # every tests/api test (e.g. `-m kalshi_risk`).  Under coverage that heavy
    # import chain can hit C-extension double-load errors before any api test
    # executes.  Deferring to fixture time keeps collection cheap and safe.
    from web.main_15m_lean import app
    return TestClient(app)
