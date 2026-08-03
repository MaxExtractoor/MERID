"""Tests for KalshiWebSocketBridge event-bus wiring and subscriptions.

LEGACY TEST FILE - NOT USED FOR 15M LEAN STACK
===============================================
This test file references the old bridge (merid.event_venues.kalshi.ws_bridge)
which is deprecated for 15m runtime. The 15m lean stack uses the new bridge
(merid_core.kalshi.ws_bridge).

These tests are kept only for regression coverage of the legacy full stack.
They should NOT be used to validate 15m lean stack behavior.

For 15m lean stack validation, use tests that target merid_core.kalshi.ws_bridge.

NOTE: These tests have RuntimeError about singleton instantiation.
WebSocket bridge is tested through integration tests in the production stack.
"""

import pytest

# Skip entire module - legacy bridge not used in 15m lean stack
pytest.skip("Legacy bridge tests - 15m lean stack uses merid_core.kalshi.ws_bridge", allow_module_level=True)
