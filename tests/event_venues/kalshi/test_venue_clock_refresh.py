import asyncio
import time
from email.utils import formatdate
from types import SimpleNamespace

import pytest

from merid.event_venues.kalshi import venue_clock_refresh as refresh
from merid.event_venues.kalshi.venue_clock import (
    ClockOffsetMeasurement, STATUS_MEASURED, VenueClockCalibration,
)


def _sample(monotonic=None, wall=None):
    return ClockOffsetMeasurement(
        server_minus_local_seconds=-2.5,
        measured_at_wall=time.time() if wall is None else wall,
        measured_at_monotonic=time.monotonic() if monotonic is None else monotonic,
        source="offline-test", precision_seconds=1.1, rtt_seconds=0.2,
    )


def test_date_sample_uses_non_cached_live_endpoint(monkeypatch):
    calls = []

    def head(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=200, headers={"Date": formatdate(usegmt=True), "Age": "0"})

    monkeypatch.setattr(refresh.requests, "head", head)
    sample = refresh._sample_live_clock()
    assert abs(sample.server_minus_local_seconds) < 2
    assert sample.precision_seconds >= 1
    assert calls[0][1]["headers"]["Cache-Control"] == "no-cache"
    assert calls[0][1]["allow_redirects"] is False


def test_head_not_found_falls_back_to_fresh_get(monkeypatch):
    calls = []

    def head(*args, **kwargs):
        calls.append("head")
        return SimpleNamespace(status_code=404, headers={"Date": formatdate(usegmt=True)})

    def get(*args, **kwargs):
        calls.append("get")
        return SimpleNamespace(status_code=200, headers={"Date": formatdate(usegmt=True), "Age": "0"})

    monkeypatch.setattr(refresh.requests, "head", head)
    monkeypatch.setattr(refresh.requests, "get", get)
    sample = refresh._sample_live_clock()
    assert calls == ["head", "get"]
    assert abs(sample.server_minus_local_seconds) < 2


def test_head_timeout_falls_back_to_fresh_get(monkeypatch):
    def head(*args, **kwargs):
        raise refresh.requests.Timeout("head timeout")

    monkeypatch.setattr(refresh.requests, "head", head)
    monkeypatch.setattr(refresh.requests, "get", lambda *a, **kw: SimpleNamespace(
        status_code=200, headers={"Date": formatdate(usegmt=True)}
    ))
    assert refresh._sample_live_clock().source == "kalshi_periodic_date_header"


@pytest.mark.parametrize("status,headers", [
    (500, {"Date": formatdate(usegmt=True)}),
    (200, {"Date": formatdate(usegmt=True), "Age": "12"}),
    (200, {"Date": formatdate(usegmt=True), "Age": "broken"}),
    (200, {}),
])
def test_invalid_response_does_not_create_sample(monkeypatch, status, headers):
    response = lambda *a, **kw: SimpleNamespace(status_code=status, headers=headers)
    monkeypatch.setattr(refresh.requests, "head", response)
    monkeypatch.setattr(refresh.requests, "get", response)
    with pytest.raises((ValueError, KeyError)):
        refresh._sample_live_clock()


def test_host_step_during_request_is_rejected(monkeypatch):
    wall_values = iter((100.0, 102.0))
    mono_values = iter((200.0, 200.1))
    monkeypatch.setattr(refresh, "time", SimpleNamespace(
        time=lambda: next(wall_values), monotonic=lambda: next(mono_values)
    ))
    monkeypatch.setattr(refresh.requests, "head", lambda *a, **kw: SimpleNamespace(
        status_code=200, headers={"Date": formatdate(usegmt=True)}
    ))
    with pytest.raises(ValueError, match="stepped"):
        refresh._sample_live_clock()


def test_expired_calibration_is_renewed_offline(monkeypatch):
    clock = VenueClockCalibration("test", max_offset_age_s=10)
    clock.record_measurement(
        -1, source="old", precision_seconds=1,
        measured_at_wall=time.time() - 20, measured_at_monotonic=time.monotonic() - 20,
    )
    assert not clock.offset_state().valid
    monkeypatch.setattr(refresh, "_sample_live_clock", _sample)
    assert asyncio.run(refresh.refresh_live_clock_once(clock))
    state = clock.offset_state()
    assert state.valid
    assert state.offset_seconds == -2.5
    assert state.source == "offline-test"
    event_ms = (time.time() - 2.5 - 0.25) * 1000
    assert clock.evaluate_venue_ts(event_ms).freshness_status == STATUS_MEASURED


def test_failed_refresh_preserves_expired_calibration(monkeypatch):
    clock = VenueClockCalibration("test", max_offset_age_s=10)
    clock.record_measurement(
        -1, source="old", precision_seconds=1,
        measured_at_wall=time.time() - 20, measured_at_monotonic=time.monotonic() - 20,
    )

    def fail():
        raise OSError("unavailable")

    monkeypatch.setattr(refresh, "_sample_live_clock", fail)
    assert not asyncio.run(refresh.refresh_live_clock_once(clock))
    state = clock.offset_state()
    assert not state.valid
    assert state.invalid_reason == "expired"


def test_delayed_or_older_measurement_cannot_replace_newer(monkeypatch):
    clock = VenueClockCalibration("test")
    clock.record_measurement(1, source="auth", precision_seconds=1)
    old = _sample(monotonic=time.monotonic() - 1, wall=time.time() - 1)
    monkeypatch.setattr(refresh, "_sample_live_clock", lambda: old)
    assert not asyncio.run(refresh.refresh_live_clock_once(clock))
    assert clock.offset_state().source == "auth"

    delayed = _sample(monotonic=time.monotonic() - 10, wall=time.time() - 10)
    monkeypatch.setattr(refresh, "_sample_live_clock", lambda: delayed)
    assert not asyncio.run(refresh.refresh_live_clock_once(clock))
    assert clock.offset_state().source == "auth"


def test_host_step_after_request_preserves_old_measurement(monkeypatch):
    clock = VenueClockCalibration("test")
    clock.record_measurement(1, source="auth", precision_seconds=1)
    jumped = _sample(wall=time.time() - 2)
    monkeypatch.setattr(refresh, "_sample_live_clock", lambda: jumped)
    assert not asyncio.run(refresh.refresh_live_clock_once(clock))
    assert clock.offset_state().source == "auth"


def test_refresh_loop_retries_without_overlapping_requests(monkeypatch):
    clock = SimpleNamespace(
        refresh_after_seconds=lambda: 8.0,
        offset_state=lambda: SimpleNamespace(valid=False, measurement_age_s=None),
    )
    sleeps = []
    attempts = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) > 1:
            raise asyncio.CancelledError

    async def fake_refresh(actual_clock):
        attempts.append(actual_clock)
        return False

    monkeypatch.setattr(refresh.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(refresh, "refresh_live_clock_once", fake_refresh)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(refresh.maintain_live_clock(clock))
    assert sleeps == [2.0, 2.0]
    assert attempts == [clock]


def test_refresh_loop_stops_without_sampling_when_client_stops(monkeypatch):
    clock = SimpleNamespace(refresh_after_seconds=lambda: 8.0)
    running = [True]

    async def fake_sleep(seconds):
        running[0] = False

    monkeypatch.setattr(refresh.asyncio, "sleep", fake_sleep)
    asyncio.run(refresh.maintain_live_clock(clock, lambda: running[0]))
