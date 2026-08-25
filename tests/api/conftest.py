"""Shared fixtures for tests/api."""

import pytest
from fastapi.testclient import TestClient

from web.main_15m_lean import app


@pytest.fixture
def client():
    """FastAPI TestClient for the 15m lean app."""
    return TestClient(app)
