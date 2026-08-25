"""Smoke tests for the legacy KalshiWebSocketBridge module.

The legacy bridge is no longer the primary forwarder for the 15m lean stack,
but the module must remain importable and the forward loop must register the
market state event loop so REST re-sync coroutines can be scheduled.
"""

import inspect

import pytest

from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge


def test_legacy_ws_bridge_forward_loop_is_coroutine():
    """The legacy bridge has the async forward loop used to register the event loop."""
    assert hasattr(KalshiWebSocketBridge, "_forward_loop_with_drain")
    assert inspect.iscoroutinefunction(KalshiWebSocketBridge._forward_loop_with_drain)
