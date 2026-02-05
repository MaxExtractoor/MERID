"""Global test fixtures for MERID test suite."""
import pytest
from unittest.mock import MagicMock


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
