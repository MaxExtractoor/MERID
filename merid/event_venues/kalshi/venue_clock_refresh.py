"""Bounded, off-loop renewal of the live Kalshi venue-clock measurement."""

from __future__ import annotations

import asyncio
import time
from email.utils import parsedate_to_datetime
from typing import Callable, Optional

import requests

from merid.event_venues.kalshi.venue_clock import ClockOffsetMeasurement, VenueClockCalibration
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.venue_clock_refresh")

_MARKETS_URL = "https://external-api.kalshi.com/trade-api/v2/markets"
_MAX_RTT_S = 2.5
_MAX_DELIVERY_DELAY_S = 5.0
_MAX_WALL_STEP_S = 0.5


def _sample_live_clock() -> ClockOffsetMeasurement:
    """Measure the existing live REST Date clock without blocking the WS loop."""
    wall_start = time.time()
    mono_start = time.monotonic()
    response = requests.head(
        _MARKETS_URL, params={"limit": 1},
        headers={"Cache-Control": "no-cache"},
        timeout=2, allow_redirects=False,
    )
    wall_end = time.time()
    mono_end = time.monotonic()
    rtt = mono_end - mono_start
    if not (0 <= rtt <= _MAX_RTT_S):
        raise ValueError("clock request RTT outside bounds")
    if abs((wall_end - wall_start) - rtt) > _MAX_WALL_STEP_S:
        raise ValueError("host clock stepped during clock request")
    if not (200 <= response.status_code < 300 or response.status_code == 405):
        raise ValueError("clock request failed")
    age = response.headers.get("Age")
    if age is not None and (not str(age).isdigit() or int(age) != 0):
        raise ValueError("cached clock response")
    server_time = parsedate_to_datetime(response.headers["Date"])
    if server_time.tzinfo is None:
        raise ValueError("clock response has no timezone")
    midpoint = wall_start + (wall_end - wall_start) / 2.0
    return ClockOffsetMeasurement(
        server_minus_local_seconds=server_time.timestamp() - midpoint,
        measured_at_wall=wall_end,
        measured_at_monotonic=mono_end,
        source="kalshi_periodic_date_header",
        precision_seconds=1.0 + rtt / 2.0,
        rtt_seconds=rtt,
    )


async def refresh_live_clock_once(clock: VenueClockCalibration) -> bool:
    """Publish only a recent, ordered sample; failures leave old state untouched."""
    try:
        measurement = await asyncio.to_thread(_sample_live_clock)
        elapsed = time.monotonic() - measurement.measured_at_monotonic
        if not (0 <= elapsed <= _MAX_DELIVERY_DELAY_S):
            raise ValueError("clock sample delivery delayed")
        predicted_wall = measurement.measured_at_wall + elapsed
        if abs(time.time() - predicted_wall) > _MAX_WALL_STEP_S:
            raise ValueError("host clock stepped after clock request")
        return clock.record_measurement_if_newer(measurement)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("[VENUE-CLOCK] periodic calibration failed: %s", exc)
        return False


async def maintain_live_clock(
    clock: VenueClockCalibration,
    should_continue: Optional[Callable[[], bool]] = None,
) -> None:
    """Renew before expiry and retry without overlapping requests."""
    refresh_after = clock.refresh_after_seconds()
    poll_s = max(1.0, min(60.0, refresh_after / 4.0))
    last_attempt = 0.0
    while should_continue is None or should_continue():
        await asyncio.sleep(poll_s)
        if should_continue is not None and not should_continue():
            return
        state = clock.offset_state()
        if state.valid and state.measurement_age_s is not None and state.measurement_age_s < refresh_after:
            continue
        now = time.monotonic()
        if now - last_attempt < poll_s:
            continue
        last_attempt = now
        await refresh_live_clock_once(clock)
