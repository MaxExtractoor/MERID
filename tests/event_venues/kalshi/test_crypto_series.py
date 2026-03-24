import asyncio
from unittest.mock import AsyncMock

import pytest

from core.cache import cache
from merid.event_venues.base import EventMarket
from merid.event_venues.kalshi import crypto_series
from merid.event_venues.kalshi.crypto_series import (
    fetch_markets_batch,
    group_frequencies_by_asset,
    list_crypto_series,
)
from merid.resilience import OperationResult


@pytest.mark.asyncio
async def test_list_crypto_series_filters_targets_and_normalizes(monkeypatch):
    client = AsyncMock()
    client.list_series = AsyncMock(
        return_value=OperationResult.ok(
            [
                {"ticker": "kxbtc", "tags": ["BTC", "crypto"], "frequency": "15_minute", "title": "BTC 15m", "volume_fp": "10"},
                {"ticker": "KXETH", "tags": ["ETH"], "frequency": "weekly", "title": "ETH weekly"},
                {"ticker": "KXALT", "tags": ["PEPE"], "frequency": "daily", "title": "PEPE daily"},
            ]
        )
    )

    series = await list_crypto_series(client, force_refresh=True, use_cache=False)
    assert len(series) == 2
    freqs = group_frequencies_by_asset(series)
    assert freqs["BTC"] == {"15m"}
    assert "1w" in freqs["ETH"]


@pytest.mark.asyncio
async def test_list_crypto_series_uses_cache(monkeypatch):
    cached = [{"ticker": "KXBTC", "asset": "BTC", "frequency": "15m", "title": "BTC 15m", "tags": ["BTC"]}]
    cache.set_json("kalshi:crypto_series:v1", cached, ttl=60)

    client = AsyncMock()
    client.list_series = AsyncMock()

    series = await list_crypto_series(client, force_refresh=False, use_cache=True)
    assert series == cached
    client.list_series.assert_not_awaited()

    cache.delete("kalshi:crypto_series:v1")


@pytest.mark.asyncio
async def test_fetch_markets_batch_retries_on_429(monkeypatch):
    market = EventMarket(
        market_id="KXBTC-TEST",
        venue="kalshi",
        question="BTC test",
        description="",
        outcomes=[],
    )

    fail_result = OperationResult.fail(Exception("429"), status_code=429)
    success_result = OperationResult.ok([market])

    client = AsyncMock()
    client.list_markets_result = AsyncMock(side_effect=[fail_result, success_result])

    sleep_calls = []

    async def fake_sleep(duration: float):
        sleep_calls.append(duration)

    monkeypatch.setattr(crypto_series.asyncio, "sleep", fake_sleep)

    markets = await fetch_markets_batch(
        client,
        ["KXBTC"],
        status="open",
        throttle_seconds=0.0,
        backoff_schedule=(0.01, 0.02),
    )

    assert len(markets) == 1
    assert client.list_markets_result.await_count == 2
    assert sleep_calls  # backoff occurred
