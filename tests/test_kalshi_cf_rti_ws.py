"""Tests for the Kalshi CF-RTI WebSocket stream."""
from __future__ import annotations

import asyncio
import os
from unittest.mock import MagicMock, patch

import pytest

from merid.data import kalshi_cf_rti_ws as ws_module
from merid.event_venues.kalshi.kalshi_config import KalshiConfig


def _dummy_config() -> KalshiConfig:
    return KalshiConfig(
        env="demo",
        rest_base_url="https://demo-api.kalshi.co/trade-api/v2",
        ws_base_url="wss://demo-api.kalshi.co/trade-api/ws/v2",
        api_key_id="test-key",
        private_key_path="",
        private_key_pem="-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC5Z5Z5Z5Z5Z5Z5\n-----END PRIVATE KEY-----",
    )


@pytest.mark.asyncio
async def test_process_messages_forces_reconnect_on_silence():
    """If no data arrives longer than MERID_CFB_RTI_SILENCE_RECONNECT_S, the loop reconnects."""
    os.environ["MERID_CFB_RTI_SILENCE_RECONNECT_S"] = "0.2"

    with patch.object(ws_module, "get_kalshi_config", _dummy_config):
        stream = ws_module.KalshiCfRtiStream(on_disconnect=lambda: None)

    stream._ws = MagicMock()
    stream._running = True
    stream._subscribe_and_indexlist = lambda: None
    disconnect_called = False

    def on_disconnect():
        nonlocal disconnect_called
        disconnect_called = True

    stream.on_disconnect = on_disconnect

    async def fake_recv_one(timeout):
        # Simulate a quiet socket: every recv times out.
        await asyncio.sleep(0.05)
        return None

    stream._recv_one = fake_recv_one

    start = asyncio.get_event_loop().time()
    await stream._process_messages()
    elapsed = asyncio.get_event_loop().time() - start

    assert disconnect_called
    assert elapsed >= 0.2


@pytest.mark.asyncio
async def test_process_messages_continues_while_data_arrives():
    """The loop keeps running while data arrives before the silence threshold."""
    os.environ["MERID_CFB_RTI_SILENCE_RECONNECT_S"] = "0.5"

    with patch.object(ws_module, "get_kalshi_config", _dummy_config):
        stream = ws_module.KalshiCfRtiStream(on_disconnect=lambda: None)

    stream._ws = MagicMock()
    stream._running = True
    stream._running_latch = 0  # count how many messages we let through

    async def _handle_message(data):
        pass

    stream._handle_message = _handle_message
    disconnect_called = False

    def on_disconnect():
        nonlocal disconnect_called
        disconnect_called = True

    stream.on_disconnect = on_disconnect

    async def fake_recv_one(timeout):
        # Keep returning data so the watchdog never triggers; then stop the stream
        # so the loop exits cleanly.
        if stream._running:
            stream._running_latch += 1
            if stream._running_latch >= 3:
                stream._running = False
            return {"type": "noop"}
        return None

    stream._recv_one = fake_recv_one

    await stream._process_messages()

    assert not disconnect_called
    assert stream._running_latch == 3
