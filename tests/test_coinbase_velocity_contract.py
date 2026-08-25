"""
Contract tests for CoinbaseWebSocketClient velocity semantics.

These tests lock in the 60-second total-return meaning of the external
velocity feed so that a per-second rate cannot accidentally be reintroduced.
"""

import asyncio
import time
from dataclasses import dataclass

import pytest

from merid.event_venues.coinbase.ws_client import (
    CoinbaseAsset,
    CoinbaseWebSocketClient,
    SpotPrice,
)


@dataclass
class _VelocityCapture:
    """Helper to record the most recent velocity signal published."""

    signal = None
    call_count = 0

    def __call__(self, signal):
        self.signal = signal
        self.call_count += 1


@pytest.fixture
def client():
    """Return a client with a deterministic 60s window and 0.015% threshold."""
    c = CoinbaseWebSocketClient(assets=[CoinbaseAsset.BTC])
    c._velocity_window_seconds = 60
    c._velocity_threshold = 0.00015
    return c


def _add_prices(client, prices, base_time=1000.0):
    """Seed the client's price history with a list of (offset_seconds, price)."""
    for offset, price in prices:
        client._price_history[CoinbaseAsset.BTC.value].append(
            SpotPrice(
                asset=CoinbaseAsset.BTC.value,
                price=price,
                timestamp=base_time + offset,
                sequence=0,
            )
        )


@pytest.mark.asyncio
async def test_no_velocity_published_before_full_window(client, monkeypatch):
    """A 59.9s gap must NOT publish a velocity; it requires 60s."""
    monkeypatch.setattr(
        "merid.event_venues.coinbase.ws_client.time.time", lambda: 1059.9
    )

    capture = _VelocityCapture()
    client.on_velocity_signal = capture

    _add_prices(client, [(0.0, 100.0), (59.9, 100.05)])

    await client._calculate_velocity(CoinbaseAsset.BTC.value)

    assert capture.call_count == 0, "Velocity should not be published before 60s"
    assert client._velocity_published == 0


@pytest.mark.asyncio
async def test_velocity_is_total_60s_return(client, monkeypatch):
    """Velocity must equal (p_now / p_60s_ago) - 1.0, not a per-second rate."""
    monkeypatch.setattr(
        "merid.event_venues.coinbase.ws_client.time.time", lambda: 1060.0
    )

    capture = _VelocityCapture()
    client.on_velocity_signal = capture

    _add_prices(client, [(0.0, 100.0), (60.0, 100.15)])

    await client._calculate_velocity(CoinbaseAsset.BTC.value)

    assert capture.call_count == 1
    assert client._velocity_published == 1

    signal = capture.signal
    expected = (100.15 / 100.0) - 1.0
    assert signal is not None
    assert signal.asset == CoinbaseAsset.BTC.value
    assert signal.velocity == pytest.approx(expected, abs=1e-12)
    assert signal.window_seconds == 60
    assert signal.signal_type == "positive"
    assert signal.velocity > client._velocity_threshold


@pytest.mark.asyncio
async def test_velocity_signal_types(client, monkeypatch):
    """Classification must be positive / negative / neutral against the 0.015% threshold."""
    cases = [
        (100.02, "positive"),   # +0.020% > 0.015%
        (99.98, "negative"),    # -0.020% < -0.015%
        (100.0001, "neutral"),  # +0.0001% within dead band
        (99.9999, "neutral"),   # -0.0001% within dead band
    ]

    for price, expected_type in cases:
        capture = _VelocityCapture()
        client.on_velocity_signal = capture
        client._velocity_published = 0
        client._price_history[CoinbaseAsset.BTC.value].clear()

        monkeypatch.setattr(
            "merid.event_venues.coinbase.ws_client.time.time", lambda: 1060.0
        )

        _add_prices(client, [(0.0, 100.0), (60.0, price)])

        await client._calculate_velocity(CoinbaseAsset.BTC.value)

        assert capture.call_count == 1, f"Expected one signal for price {price}"
        assert capture.signal.signal_type == expected_type, (
            f"price={price} should yield {expected_type}, got {capture.signal.signal_type}"
        )


@pytest.mark.asyncio
async def test_velocity_uses_oldest_observation_at_or_before_horizon(client, monkeypatch):
    """The reference point is the most recent observation no newer than 60s ago."""
    monkeypatch.setattr(
        "merid.event_venues.coinbase.ws_client.time.time", lambda: 1062.0
    )

    capture = _VelocityCapture()
    client.on_velocity_signal = capture

    # At t=1062, window_ago = 1002.  The 50s-ago point (1050) is too recent,
    # so the algorithm must skip it and use the 62s-ago point (1000).
    _add_prices(
        client,
        [
            (0.0, 100.20),     # 62s-ago valid reference
            (50.0, 100.50),    # 12s-ago, too recent to be the reference
            (62.0, 100.20),    # current
        ],
    )

    await client._calculate_velocity(CoinbaseAsset.BTC.value)

    # If the 50s-ago point had been used the return would be -0.0030,
    # so a 0.0 result proves the 62s-ago point was selected.
    expected = 0.0
    assert capture.signal is not None
    assert capture.signal.velocity == pytest.approx(expected, abs=1e-12)


@pytest.mark.asyncio
async def test_velocity_ignores_out_of_order_timestamps(client, monkeypatch):
    """An out-of-order late tick cannot shift the 60s reference point."""
    monkeypatch.setattr(
        "merid.event_venues.coinbase.ws_client.time.time", lambda: 1060.0
    )

    capture = _VelocityCapture()
    client.on_velocity_signal = capture

    # Append a stale observation *after* a current one.
    _add_prices(client, [(0.0, 100.0), (60.0, 100.30)])
    client._price_history[CoinbaseAsset.BTC.value].append(
        SpotPrice(
            asset=CoinbaseAsset.BTC.value,
            price=99.50,
            timestamp=1000.0,  # older than the valid 60s-ago point
            sequence=0,
        )
    )

    await client._calculate_velocity(CoinbaseAsset.BTC.value)

    # The implementation must pick the chronologically latest sample
    # (100.30 at 1060) as the current price and the 60s-ago point
    # (99.50 at 1000) as the reference.  An out-of-order late tick
    # must not become the current price.
    assert capture.signal is not None
    assert capture.signal.timestamp == 1060.0
    expected = (100.30 - 99.50) / 99.50
    assert capture.signal.velocity == pytest.approx(expected, abs=1e-12)
    assert capture.signal.signal_type == "positive"


@pytest.mark.asyncio
async def test_get_velocity_returns_total_return_not_per_second(client, monkeypatch):
    """get_velocity must return the same 60s total return used for signals."""
    monkeypatch.setattr(
        "merid.event_venues.coinbase.ws_client.time.time", lambda: 1060.0
    )

    _add_prices(client, [(0.0, 100.0), (60.0, 100.05)])

    velocity = client.get_velocity(CoinbaseAsset.BTC.value)

    expected = (100.05 / 100.0) - 1.0
    assert velocity == pytest.approx(expected, abs=1e-12)
