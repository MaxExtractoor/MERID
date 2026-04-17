import pytest

from monitoring import kalshi_metrics
from merid.event_venues.kalshi.ws_metrics import (
    on_ws_connect,
    on_ws_disconnect,
    on_ws_reconnect,
)


@pytest.fixture(autouse=True)
def reset_collector():
    kalshi_metrics._collector = None  # type: ignore[attr-defined]
    yield
    kalshi_metrics._collector = None  # type: ignore[attr-defined]


def test_ws_metrics_track_state_transitions():
    collector = kalshi_metrics.get_kalshi_metrics_collector()

    assert collector.ws_connection_state.get() == 0

    on_ws_connect()
    assert collector.ws_connection_state.get() == 1

    on_ws_disconnect()
    assert collector.ws_connection_state.get() == 0

    on_ws_reconnect()
    assert collector.ws_connection_state.get() == 1
    assert collector.ws_reconnects.get() == 1
