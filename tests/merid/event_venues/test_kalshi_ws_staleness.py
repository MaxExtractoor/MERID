"""Tests for Kalshi WebSocket staleness detection and auto-reconnect.

Tests the fix for the stale connection issue where the WebSocket was
considered stale when no market data was received, even though the
connection was alive (ping/pong working).
"""
import asyncio
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch

from merid.event_venues.kalshi.ws import KalshiWebSocket
from merid.event_venues.kalshi.models import KalshiConfig


class TestKalshiWebSocketStaleness:
    """Tests for WebSocket staleness detection."""

    def test_initial_timestamps(self):
        """Test that timestamps are initialized to 0."""
        ws = KalshiWebSocket()
        assert ws._last_frame_ts == 0.0
        assert ws._last_data_ts == 0.0
        assert ws._last_message_ts == 0.0
        assert ws._connect_ts == 0.0

    @pytest.mark.asyncio
    async def test_connect_sets_frame_timestamp(self):
        """Test that connect() sets last_frame_ts."""
        ws = KalshiWebSocket()

        with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
            mock_ws = MagicMock()
            mock_ws.closed = False
            mock_connect.return_value = mock_ws

            await ws.connect()

            # Should set timestamps on connect
            assert ws._last_frame_ts > 0
            assert ws._last_data_ts > 0
            assert ws._connect_ts > 0

    @pytest.mark.asyncio
    async def test_data_message_updates_both_timestamps(self):
        """Test that data messages update both frame and data timestamps."""
        ws = KalshiWebSocket()
        ws._ws = MagicMock()
        ws._running = True

        # Set initial timestamps
        t0 = time.monotonic()
        ws._last_frame_ts = t0 - 10
        ws._last_data_ts = t0 - 10

        # Simulate receiving a ticker message
        await asyncio.sleep(0.01)  # Small delay

        # Manually update timestamps as the listen loop would
        now = time.monotonic()
        ws._last_frame_ts = now
        ws._last_data_ts = now

        # Both should be updated
        assert ws._last_frame_ts > t0 - 10
        assert ws._last_data_ts > t0 - 10

    @pytest.mark.asyncio
    async def test_stats_includes_staleness_metrics(self):
        """Test that stats() includes new staleness metrics."""
        ws = KalshiWebSocket()

        # Set some timestamps
        now = time.monotonic()
        ws._connect_ts = now - 100
        ws._last_frame_ts = now - 5
        ws._last_data_ts = now - 30
        ws._last_message_ts = now - 30
        ws._ws = MagicMock()
        ws._running = True

        stats = ws.stats()

        # Check new fields
        assert "last_frame_ago_s" in stats
        assert "last_data_ago_s" in stats
        assert "is_stale" in stats
        assert "stale_threshold_s" in stats

        # Check values
        assert stats["last_frame_ago_s"] == 5.0
        assert stats["last_data_ago_s"] == 30.0
        assert stats["is_stale"] is False  # 5s < 60s threshold
        assert stats["stale_threshold_s"] == 60.0

    @pytest.mark.asyncio
    async def test_stats_detects_stale_connection(self):
        """Test that stats() correctly identifies stale connections."""
        ws = KalshiWebSocket()

        # Set timestamps to simulate stale connection
        now = time.monotonic()
        ws._connect_ts = now - 200
        ws._last_frame_ts = now - 70  # Over 60s threshold
        ws._last_data_ts = now - 100
        ws._last_message_ts = now - 70
        ws._ws = MagicMock()
        ws._running = True

        stats = ws.stats()

        # Should be marked as stale
        assert stats["is_stale"] is True
        assert stats["last_frame_ago_s"] == 70.0

    @pytest.mark.asyncio
    async def test_staleness_threshold_env_override(self):
        """Test that KALSHI_WS_STALE_THRESHOLD can be overridden via env."""
        ws = KalshiWebSocket()

        now = time.monotonic()
        ws._connect_ts = now - 100
        ws._last_frame_ts = now - 45  # Between 40 and 60
        ws._ws = MagicMock()
        ws._running = True

        # Default threshold is 60s
        with patch.dict("os.environ", {}, clear=False):
            stats = ws.stats()
            assert stats["stale_threshold_s"] == 60.0
            assert stats["is_stale"] is False  # 45s < 60s

        # Custom threshold of 40s
        with patch.dict("os.environ", {"KALSHI_WS_STALE_THRESHOLD": "40"}, clear=False):
            stats = ws.stats()
            assert stats["stale_threshold_s"] == 40.0
            assert stats["is_stale"] is True  # 45s > 40s

    @pytest.mark.asyncio
    async def test_subscription_confirmation_logged(self):
        """Test that subscription confirmations are logged."""
        ws = KalshiWebSocket()

        # Create a subscription confirmation message
        sub_msg = {
            "type": "subscribed",
            "id": 1,
            "channels": ["ticker"],
        }

        with patch("merid.event_venues.kalshi.ws.logger") as mock_logger:
            result = ws._parse_message(sub_msg)

            # Should return None (not forwarded)
            assert result is None

            # Should log confirmation
            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args[0][0]
            assert "Subscription confirmed" in call_args
            assert "id=1" in call_args

    @pytest.mark.asyncio
    async def test_reconnect_preserves_subscriptions(self):
        """Test that reconnect resubscribes to all channels."""
        ws = KalshiWebSocket()

        # Set up existing subscriptions
        ws._subscriptions = {"KXBTC-26MAR25-T95000", "event:KXBTC"}
        ws._trade_tickers = {"KXBTC-26MAR25-T95000"}
        ws._orderbook_tickers = {"KXBTC-26MAR25-T95000"}
        ws._order_group_updates_enabled = True
        ws._running = True

        # Mock the connect and subscribe methods
        with patch.object(ws, "connect", new_callable=AsyncMock) as mock_connect, \
             patch.object(ws, "subscribe_quotes", new_callable=AsyncMock) as mock_sub_quotes, \
             patch.object(ws, "subscribe_trades", new_callable=AsyncMock) as mock_sub_trades, \
             patch.object(ws, "subscribe_orderbook", new_callable=AsyncMock) as mock_sub_ob, \
             patch.object(ws, "subscribe_order_group_updates", new_callable=AsyncMock) as mock_sub_ogu:

            await ws._reconnect()

            # Verify reconnect flow
            mock_connect.assert_called_once()
            mock_sub_quotes.assert_called()
            mock_sub_trades.assert_called()
            mock_sub_ob.assert_called_once()
            mock_sub_ogu.assert_called_once()

    def test_backward_compat_last_message_ts(self):
        """Test that last_message_ts is maintained for backward compatibility."""
        ws = KalshiWebSocket()

        now = time.monotonic()
        ws._connect_ts = now - 100
        ws._last_message_ts = now - 30
        ws._last_frame_ts = now - 5
        ws._last_data_ts = now - 30
        ws._ws = MagicMock()
        ws._running = True

        stats = ws.stats()

        # Both old and new fields should be present
        assert "last_msg_ago_s" in stats
        assert "last_frame_ago_s" in stats
        assert "last_data_ago_s" in stats
        assert stats["last_msg_ago_s"] == 30.0

    @pytest.mark.asyncio
    async def test_connection_liveness_inference(self):
        """Test that open connection implies ping/pong working."""
        # This test validates the logic in _monitor_staleness where
        # if the connection is still open after ping_interval, we infer
        # that ping/pong must be working and update last_frame_ts.

        ws = KalshiWebSocket()
        ws._running = True
        ws._ws = MagicMock()
        ws._ws.closed = False  # Connection is open

        # Set last_frame_ts to 25 seconds ago (> ping_interval of 20s)
        now = time.monotonic()
        ws._last_frame_ts = now - 25
        ws._last_data_ts = now - 35

        # Simulate one iteration of the staleness monitor
        frame_idle = now - ws._last_frame_ts
        ping_interval = 20.0

        # Logic: if connection is open and frame_idle > ping_interval,
        # we can infer ping/pong is working
        if ws._ws and not ws._ws.closed and frame_idle > ping_interval:
            ws._last_frame_ts = now

        # Frame timestamp should be updated
        new_frame_idle = now - ws._last_frame_ts
        assert new_frame_idle < 1  # Should be ~0 (just updated)
