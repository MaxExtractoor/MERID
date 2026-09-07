"""Unit tests for the WebSocket bridge sync-request debounce logic.

These tests bypass the heavy ``KalshiWebSocketBridge`` constructor to exercise
``request_immediate_sync`` and ``set_markets`` in isolation.
"""
from __future__ import annotations

import time

from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge


def _fresh_bridge() -> KalshiWebSocketBridge:
    """Create a bare bridge instance with only the sync fields initialized."""
    bridge = KalshiWebSocketBridge.__new__(KalshiWebSocketBridge)
    bridge._sync_requested = False
    bridge._last_sync_request_ts = 0.0
    bridge._sync_request_min_interval_s = 5.0
    bridge._last_sync_attempt_ts = 0.0
    bridge._desired_tickers: list[str] = []
    bridge._desired_tickers_set = frozenset()
    bridge._desired_tickers_gen = 0
    return bridge


def test_request_immediate_sync_accepts_first_call():
    bridge = _fresh_bridge()
    assert bridge.request_immediate_sync("catalog_rollover") is True
    assert bridge._sync_requested is True
    assert bridge._last_sync_attempt_ts == 0.0
    assert bridge._last_sync_request_ts > 0.0


def test_request_immediate_sync_debounces_duplicate_calls():
    bridge = _fresh_bridge()
    assert bridge.request_immediate_sync("catalog_rollover") is True

    # A second call immediately must be suppressed.
    assert bridge.request_immediate_sync("catalog_rollover") is False
    assert bridge._sync_requested is True
    assert bridge._last_sync_attempt_ts == 0.0

    # Even after the debounce interval passes, while a sync is still pending
    # the call only re-signals the existing request and does not reset cooldown.
    bridge._last_sync_request_ts = time.monotonic() - 10.0
    assert bridge.request_immediate_sync("catalog_rollover") is False
    assert bridge._sync_requested is True


def test_request_immediate_sync_can_request_again_after_completion():
    bridge = _fresh_bridge()
    assert bridge.request_immediate_sync("catalog_rollover") is True

    # Simulate a successful sync clearing the flag.
    bridge._sync_requested = False
    bridge._last_sync_request_ts = time.monotonic() - 10.0
    assert bridge.request_immediate_sync("catalog_rollover") is True


def test_set_markets_records_last_sync_request_ts():
    bridge = _fresh_bridge()
    bridge.set_markets(["KXBTC15M-26SEP071800-00"])
    assert bridge._sync_requested is True
    assert bridge._last_sync_request_ts > 0.0
    assert bridge._last_sync_attempt_ts == 0.0


def test_set_markets_skips_unchanged_desired_tickers():
    bridge = _fresh_bridge()
    bridge.set_markets(["KXBTC15M-26SEP071800-00"])
    bridge._sync_requested = False
    bridge._last_sync_attempt_ts = 1.0

    # Same desired set should be a no-op and must not re-request.
    bridge.set_markets(["KXBTC15M-26SEP071800-00"])
    assert bridge._sync_requested is False
    assert bridge._last_sync_attempt_ts == 1.0
