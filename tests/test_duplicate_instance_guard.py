"""Regression tests: single-instance guard for the 15m live server.

2026-09-27 incident: a second uvicorn process ran the entire trading
lifespan (WS subscriptions, REST reconciliation, live entry loop) for ~60s
before its port-8011 bind failed — FastAPI runs lifespan before the bind.
Two concurrent live loops can double-submit orders.  The guard acquires an
OS mutex + probes the port before any startup side effects.
"""

from __future__ import annotations

import socket
import sys
import threading

import pytest

from merid import single_instance
from merid.single_instance import (
    DuplicateInstanceError,
    acquire_live_instance_guard,
    release_guard_for_tests,
)


@pytest.fixture(autouse=True)
def _release_guard():
    """Ensure the mutex is dropped after each test so tests don't interfere."""
    release_guard_for_tests()
    yield
    release_guard_for_tests()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestSingleInstanceMutex:
    def test_first_acquire_succeeds_on_free_port(self):
        port = _free_port()
        resolved = acquire_live_instance_guard(port=port)
        assert resolved == port

    def test_second_acquire_raises_duplicate(self):
        """The core incident: a second instance must be refused."""
        port = _free_port()
        acquire_live_instance_guard(port=port)
        with pytest.raises(DuplicateInstanceError, match="mutex|another"):
            acquire_live_instance_guard(port=_free_port())

    def test_acquire_after_release_succeeds(self):
        acquire_live_instance_guard(port=_free_port())
        release_guard_for_tests()
        # A restarted process must be able to take over once the old one let go.
        acquire_live_instance_guard(port=_free_port())

    def test_port_probe_detects_existing_listener(self):
        """Even a non-MERID process owning the port must refuse startup."""
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        try:
            with pytest.raises(DuplicateInstanceError, match="port"):
                acquire_live_instance_guard(port=port)
        finally:
            listener.close()


class TestPortResolution:
    def test_env_var_wins(self, monkeypatch):
        monkeypatch.setenv("MERID_HTTP_PORT", "9123")
        monkeypatch.setattr(sys, "argv", ["uvicorn", "--port", "9999"])
        assert single_instance._resolve_port() == 9123

    def test_argv_long_form(self, monkeypatch):
        monkeypatch.delenv("MERID_HTTP_PORT", raising=False)
        monkeypatch.setattr(sys, "argv", ["python", "-m", "uvicorn", "web.main_15m_lean:app", "--port", "8123"])
        assert single_instance._resolve_port() == 8123

    def test_argv_equals_form(self, monkeypatch):
        monkeypatch.delenv("MERID_HTTP_PORT", raising=False)
        monkeypatch.setattr(sys, "argv", ["uvicorn", "app:app", "--port=8124"])
        assert single_instance._resolve_port() == 8124

    def test_default_when_nothing_set(self, monkeypatch):
        monkeypatch.delenv("MERID_HTTP_PORT", raising=False)
        monkeypatch.setattr(sys, "argv", ["python"])
        assert single_instance._resolve_port() == 8011
