"""Coinbase ws_client TLS context: built once, off the event loop.

Regression for the 2026-11-05 wedge: websockets.connect() used to build a
fresh SSLContext inside the loop thread on every reconnect; multi-second
cert-store loads stalled the shared FastAPI loop.  These tests verify the
context is constructed off-loop via asyncio.to_thread and reused.
"""
import asyncio
import ssl
import time
from unittest.mock import patch

import pytest

from merid.event_venues.coinbase.ws_client import CoinbaseWebSocketClient


def test_tls_context_built_off_loop_and_reused(monkeypatch):
    """A slow create_default_context must not stall a concurrent coroutine."""
    real_factory = ssl.create_default_context
    calls = []

    def slow_factory(*a, **k):
        calls.append(1)
        time.sleep(0.5)  # blocking, would freeze the loop if run on it
        return real_factory(*a, **k)

    monkeypatch.setattr(ssl, "create_default_context", slow_factory)

    async def scenario():
        client = CoinbaseWebSocketClient()
        ticks = 0
        stop = asyncio.Event()

        async def ticker():
            nonlocal ticks
            while not stop.is_set():
                ticks += 1
                await asyncio.sleep(0.01)

        t = asyncio.create_task(ticker())
        ctx1 = await client._ensure_ssl_context()
        ctx2 = await client._ensure_ssl_context()
        stop.set()
        await t
        return ctx1, ctx2, ticks

    ctx1, ctx2, ticks = asyncio.run(scenario())
    assert len(calls) == 1                      # built once, reused
    assert ctx1 is ctx2                         # same object on reconnect
    assert ticks > 10                           # loop kept running during 0.5s build
    assert ctx1.verify_mode == ssl.CERT_REQUIRED
    assert ctx1.check_hostname is True


def test_tls_context_init_serialized_under_race(monkeypatch):
    """Concurrent first-connects must not build duplicate contexts."""
    real_factory = ssl.create_default_context
    calls = []

    def slow_factory(*a, **k):
        calls.append(1)
        time.sleep(0.05)
        return real_factory(*a, **k)

    monkeypatch.setattr(ssl, "create_default_context", slow_factory)

    async def scenario():
        client = CoinbaseWebSocketClient()
        return await asyncio.gather(
            client._ensure_ssl_context(),
            client._ensure_ssl_context(),
            client._ensure_ssl_context(),
        )

    ctxs = asyncio.run(scenario())
    assert len(calls) == 1
    assert ctxs[0] is ctxs[1] is ctxs[2]
