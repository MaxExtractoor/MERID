"""Venue-clock refresh lifecycle (F1 repair, 2026-11-01).

The production WS path runs ``KalshiWebSocketBridge``, which previously never
spawned ``maintain_live_clock`` — the offset measured once at auth expired at
auth+TTL and every venue-age check degraded to ``unverified_offset_expired``.
These tests exercise the renewal loop the bridge now spawns at start() and
cancels at stop(): renewal must happen past TTL *without reconnect*, fresh
state must not be re-measured, and the predicate must stop the loop.
"""
import asyncio
from types import SimpleNamespace

import pytest

from merid.event_venues.kalshi import venue_clock_refresh as vcr


class _StubClock:
    """Minimal VenueClockCalibration stand-in with a controllable expiry."""

    def __init__(self, expired: bool):
        self._expired = expired

    def refresh_after_seconds(self) -> float:
        return 4.0  # -> poll_s = max(1, min(60, 1.0)) = 1.0s

    def offset_state(self):
        return SimpleNamespace(
            valid=not self._expired,
            measurement_age_s=99.0 if self._expired else 0.0,
        )


@pytest.mark.asyncio
async def test_expired_clock_is_renewed_then_skipped(monkeypatch):
    clock = _StubClock(expired=True)
    calls = []

    async def _fake_refresh(c):
        calls.append(1)
        c._expired = False  # renewal succeeded: offset becomes fresh
        return True

    monkeypatch.setattr(vcr, "refresh_live_clock_once", _fake_refresh)
    flags = iter([True, True, True, False])
    await vcr.maintain_live_clock(clock, should_continue=lambda: next(flags, False))
    # Exactly one renewal; polls after that see a fresh offset and skip.
    assert calls == [1]


@pytest.mark.asyncio
async def test_fresh_clock_is_not_remeasured(monkeypatch):
    clock = _StubClock(expired=False)
    calls = []

    async def _fake_refresh(c):
        calls.append(1)
        return True

    monkeypatch.setattr(vcr, "refresh_live_clock_once", _fake_refresh)
    flags = iter([True, True, False])
    await vcr.maintain_live_clock(clock, should_continue=lambda: next(flags, False))
    assert calls == []


@pytest.mark.asyncio
async def test_stop_predicate_exits_before_any_refresh(monkeypatch):
    calls = []

    async def _fake_refresh(c):
        calls.append(1)
        return True

    monkeypatch.setattr(vcr, "refresh_live_clock_once", _fake_refresh)
    await vcr.maintain_live_clock(
        _StubClock(expired=True), should_continue=lambda: False
    )
    assert calls == []


@pytest.mark.asyncio
async def test_failed_refresh_retries_bounded_non_overlapping(monkeypatch):
    clock = _StubClock(expired=True)
    calls = []

    async def _fake_refresh(c):
        calls.append(1)
        await asyncio.sleep(0)
        return False  # failure: state stays expired; retry on the next poll

    monkeypatch.setattr(vcr, "refresh_live_clock_once", _fake_refresh)
    flags = iter([True, True, True, False])
    await vcr.maintain_live_clock(clock, should_continue=lambda: next(flags, False))
    # Invariant: at least one attempt, never more than one per poll
    # (awaited serially — no tight un-awaited loop, no overlap).
    # OBSERVED: an elapsed interval below the retry threshold defers the
    # attempt until a later poll — with poll_s at the 1.0s floor, a 15.625ms
    # monotonic granularity (measured: get_clock_info -> GetTickCount64 on
    # CPython 3.11.9/MSC v.1938) can read post-sleep elapsed as ~0.984s and
    # skip one retry cycle.  Bounded either way; exact count is not asserted.
    assert 1 <= len(calls) <= 3
