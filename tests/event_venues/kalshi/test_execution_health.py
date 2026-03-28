"""Tests for Kalshi execution health — WS staleness gate and health flags.

Validates:
  - KalshiWebSocket.stats() exposes the fields needed by health monitoring.
  - Staleness is correctly derived from last_message_ts.
  - A freshly connected WS (with recent messages) is NOT stale.
  - A WS with no messages for a long time IS stale.
  - Health stats structure is correct for dependency health endpoint.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from merid.event_venues.kalshi.ws import KalshiWebSocket


@pytest.fixture
def ws() -> KalshiWebSocket:
    return KalshiWebSocket()


# ── Stats structure ───────────────────────────────────────────────────────

def test_stats_returns_expected_fields(ws: KalshiWebSocket) -> None:
    """stats() must expose fields required by the health endpoint."""
    s = ws.stats()
    required = {
        "connected",
        "uptime_s",
        "messages_received",
        "errors_received",
        "reconnect_count",
        "last_msg_ago_s",
    }
    assert required.issubset(s.keys()), f"Missing keys: {required - s.keys()}"


def test_stats_initial_state(ws: KalshiWebSocket) -> None:
    """Before any connection, messages_received and errors_received are 0."""
    s = ws.stats()
    assert s["messages_received"] == 0
    assert s["errors_received"] == 0
    assert s["connected"] is False


# ── Staleness derivation ──────────────────────────────────────────────────

def test_no_messages_last_msg_ago_is_none(ws: KalshiWebSocket) -> None:
    """Before first message, last_msg_ago_s is None."""
    assert ws.stats()["last_msg_ago_s"] is None


def test_recent_message_means_not_stale(ws: KalshiWebSocket) -> None:
    """After a recent message, last_msg_ago_s should be close to 0."""
    ws._last_message_ts = time.monotonic()
    s = ws.stats()
    assert s["last_msg_ago_s"] is not None
    assert s["last_msg_ago_s"] < 5.0, "Expected < 5s after just setting ts"


def test_old_message_ts_shows_large_ago(ws: KalshiWebSocket) -> None:
    """A message received 120s ago produces last_msg_ago_s >= 120."""
    ws._last_message_ts = time.monotonic() - 120.0
    s = ws.stats()
    assert s["last_msg_ago_s"] >= 100.0


def test_staleness_threshold_env_default() -> None:
    """KALSHI_WS_STALE_THRESHOLD should default to a sane value (>0)."""
    import os
    threshold = float(os.getenv("KALSHI_WS_STALE_THRESHOLD", "60"))
    assert threshold > 0


# ── Health gate integration ───────────────────────────────────────────────

def test_ws_healthy_when_recent_message(ws: KalshiWebSocket) -> None:
    """Simulate a healthy WS: connected + recent message → not stale."""
    ws._running = True
    ws._ws = MagicMock()
    ws._last_message_ts = time.monotonic() - 5.0  # 5s ago

    s = ws.stats()
    assert s["connected"] is True
    assert s["last_msg_ago_s"] < 60.0  # within default stale threshold


def test_ws_stale_detection(ws: KalshiWebSocket) -> None:
    """Simulate stale WS: last message > stale threshold."""
    import os
    threshold = float(os.getenv("KALSHI_WS_STALE_THRESHOLD", "60"))
    ws._running = True
    ws._ws = MagicMock()
    ws._last_message_ts = time.monotonic() - (threshold + 10)

    s = ws.stats()
    assert s["last_msg_ago_s"] is not None
    assert s["last_msg_ago_s"] >= threshold


# ── Error counter ─────────────────────────────────────────────────────────

def test_error_counter_increments_on_error_message(ws: KalshiWebSocket) -> None:
    data = {"type": "error", "code": "bad_request", "msg": "test"}
    ws._handle_error_message(data)
    assert ws.stats()["errors_received"] == 1


def test_multiple_errors_counted_in_stats(ws: KalshiWebSocket) -> None:
    for i in range(3):
        ws._handle_error_message({"type": "error", "code": "bad_request", "msg": f"e{i}"})
    assert ws.stats()["errors_received"] == 3


# ── Reconnect counter ─────────────────────────────────────────────────────

def test_reconnect_count_exposed_in_stats(ws: KalshiWebSocket) -> None:
    assert "reconnect_count" in ws.stats()
    ws._reconnect_count = 3
    assert ws.stats()["reconnect_count"] == 3

