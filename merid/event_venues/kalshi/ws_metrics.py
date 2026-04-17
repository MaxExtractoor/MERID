"""Helper hooks for Kalshi WebSocket health metrics."""

from monitoring import kalshi_metrics


def on_ws_connect() -> None:
    """Hook called when the Kalshi WebSocket connects."""
    kalshi_metrics.set_kalshi_ws_connection_state(True)


def on_ws_disconnect() -> None:
    """Hook called when the Kalshi WebSocket disconnects."""
    kalshi_metrics.set_kalshi_ws_connection_state(False)


def on_ws_reconnect() -> None:
    """Hook called when the Kalshi WebSocket successfully reconnects."""
    kalshi_metrics.record_kalshi_ws_reconnect()
    kalshi_metrics.set_kalshi_ws_connection_state(True)
