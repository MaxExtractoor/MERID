"""Tests for the Kalshi CF-RTI WebSocket stream."""
from __future__ import annotations

import asyncio
import os
import time
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


@pytest.mark.asyncio
async def test_recv_one_tags_message_with_received_at_mono_ns():
    """_recv_one annotates parsed frames with the monotonic receipt timestamp."""
    with patch.object(ws_module, "get_kalshi_config", _dummy_config):
        stream = ws_module.KalshiCfRtiStream(on_disconnect=lambda: None)

    stream._ws = MagicMock()

    async def _recv():
        return '{"type":"noop"}'

    stream._ws.recv = _recv

    data = await stream._recv_one(timeout=1.0)
    assert data is not None
    assert "received_at_mono_ns" in data
    assert isinstance(data["received_at_mono_ns"], int)
    assert data["received_at_mono_ns"] > 0


@pytest.mark.asyncio
async def test_forward_frame_includes_event_loop_lag_ms():
    """_forward_frame measures the time from recv to processing."""
    with patch.object(ws_module, "get_kalshi_config", _dummy_config):
        stream = ws_module.KalshiCfRtiStream(on_disconnect=lambda: None)

    received = []

    def on_frame(frame):
        received.append(frame)

    stream.on_frame = on_frame

    # Simulate a frame whose JSON payload contains a value and index_id.
    raw_msg = {
        "index_id": "BRTI",
        "data": '{"value": 65000.0, "timestamp": 1788819357.5}',
    }

    await stream._forward_frame(
        raw_msg,
        sid=1,
        seq=100,
        received_at_mono_ns=time.monotonic_ns() - 5_000_000,  # 5ms ago
    )

    assert len(received) == 1
    frame = received[0]
    assert frame.data["event_loop_lag_ms"] is not None
    assert isinstance(frame.data["event_loop_lag_ms"], int)
    assert frame.data["event_loop_lag_ms"] >= 0
