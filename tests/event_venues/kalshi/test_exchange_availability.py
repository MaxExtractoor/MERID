from __future__ import annotations

from datetime import datetime, timezone

import pytest

from merid.event_venues.kalshi.exchange_availability import compute_kalshi_exchange_availability

pytestmark = [
    pytest.mark.kalshi_live_ready,
    pytest.mark.p0_live_blocker,
]


def test_weekly_thursday_3_5_et_window_blocks_inside() -> None:
    # 2026-03-26 is a Thursday. 03:30 ET should be inside weekly maintenance.
    # 03:30 ET == 07:30 UTC (EDT is UTC-4 in late March).
    now = datetime(2026, 3, 26, 7, 30, 0, tzinfo=timezone.utc)
    snap = compute_kalshi_exchange_availability(
        now=now,
        schedule=None,
        status=None,
        maintenance_grace_seconds=0,
        tz_name="America/New_York",
    )
    assert snap.trading_open_now is False
    assert snap.reason in ("scheduled", "unknown")


def test_weekly_thursday_3_5_et_window_allows_outside() -> None:
    # 06:00 ET == 10:00 UTC (outside maintenance).
    now = datetime(2026, 3, 26, 10, 0, 0, tzinfo=timezone.utc)
    snap = compute_kalshi_exchange_availability(
        now=now,
        schedule=None,
        status=None,
        maintenance_grace_seconds=0,
        tz_name="America/New_York",
    )
    assert snap.trading_open_now is True


def test_status_estimated_resume_time_blocks_until_resume() -> None:
    now = datetime(2026, 3, 26, 6, 0, 0, tzinfo=timezone.utc)
    status = {"exchange_estimated_resume_time": "2026-03-26T08:00:00Z"}
    snap = compute_kalshi_exchange_availability(
        now=now,
        schedule=None,
        status=status,
        maintenance_grace_seconds=0,
        tz_name="America/New_York",
    )
    assert snap.trading_open_now is False
    assert snap.estimated_resume_time_utc == "2026-03-26T08:00:00+00:00"
    assert snap.next_open_time_utc == "2026-03-26T08:00:00+00:00"


def test_grace_buffer_expands_windows() -> None:
    schedule = {
        "maintenance_windows": [
            {"start_datetime": "2026-03-26T07:00:00Z", "end_datetime": "2026-03-26T08:00:00Z"},
        ]
    }
    # With 120s grace, 06:59:00Z should be blocked (window starts at 07:00Z, grace pushes to 06:58Z).
    now = datetime(2026, 3, 26, 6, 59, 0, tzinfo=timezone.utc)
    snap = compute_kalshi_exchange_availability(
        now=now,
        schedule=schedule,
        status=None,
        maintenance_grace_seconds=120,
        tz_name="America/New_York",
    )
    assert snap.trading_open_now is False

