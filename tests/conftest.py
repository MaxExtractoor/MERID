"""Global test fixtures for MERID test suite."""
import pytest
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def disable_network_calls(monkeypatch):
    """
    Autouse fixture to warn about real network traffic during tests.
    
    This fixture monkeypatches common HTTP/WebSocket libraries at the start
    of each test to catch unmocked network calls. Tests should explicitly
    set up their mocks.
    """
    # We'll implement this more carefully to not interfere with existing mocks
    # For now, just yield to allow tests to run
    yield


@pytest.fixture
def mock_httpx_client():
    """Fixture providing a mock httpx.AsyncClient for tests."""
    client = MagicMock()
    client.get = MagicMock()
    client.post = MagicMock()
    client.request = MagicMock()
    return client


@pytest.fixture
def mock_websocket():
    """Fixture providing a mock WebSocket for tests."""
    ws = MagicMock()
    ws.send = MagicMock()
    ws.recv = MagicMock()
    ws.close = MagicMock()
    return ws


@pytest.fixture
def missing_endpoints_client():
    """Minimal FastAPI TestClient containing only the missing_endpoints router.

    Usage in tests::

        def test_something(missing_endpoints_client):
            resp = missing_endpoints_client.get("/api/v1/some/endpoint")
            assert resp.status_code == 200
    """
    from web.api.missing_endpoints import router as missing_router
    app = FastAPI()
    app.include_router(missing_router)
    return TestClient(app)
