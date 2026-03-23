import builtins
import time

import pytest

from merid.signals.ws_price_feed import CoinbasePriceFeed


@pytest.mark.asyncio
async def test_connect_fails_fast_when_websockets_missing(monkeypatch):
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "websockets":
            raise ImportError("missing websockets")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    feed = CoinbasePriceFeed(["BTC-USD"])
    with pytest.raises(RuntimeError, match="websockets dependency missing"):
        await feed.connect()


def test_health_flags_stale_feed():
    feed = CoinbasePriceFeed(["BTC-USD"])
    feed._running = True
    feed._connected_at = time.time() - 10
    feed._last_message_at = time.time() - 60
    feed._read_timeout = 5

    healthy, reason = feed.health()
    assert healthy is False
    assert reason == "stale_feed"


def test_backoff_progression_has_jitter():
    current = 1.0
    next_val = CoinbasePriceFeed._next_backoff(current)
    assert 0.5 <= next_val <= 30.0
