from __future__ import annotations

from datetime import datetime, timezone
from unittest import mock

import pytest

pytestmark = [
    pytest.mark.kalshi_live_ready,
    pytest.mark.p0_live_blocker,
]


def test_session_guard_summary_maintenance_day_true_when_exchange_closed() -> None:
    from merid.prediction.session_guard import SessionGuard

    guard = SessionGuard()

    fake = mock.MagicMock()
    fake.ok = True
    fake.trading_open_now = False
    fake.reason = "adhoc"
    fake.next_open_time_utc = "2026-03-26T08:00:00+00:00"
    fake.estimated_resume_time_utc = None
    fake.active_window_utc = None

    with mock.patch(
        "merid.event_venues.kalshi.exchange_availability.get_kalshi_exchange_availability",
        return_value=mock.MagicMock(snapshot=lambda: fake),
    ):
        s = guard.summary()

    assert s["trading_allowed"] is False
    assert s["maintenance_day"] is True
    assert isinstance(s["maintenance_window"], str)


def test_session_guard_summary_maintenance_day_false_when_exchange_open() -> None:
    from merid.prediction.session_guard import SessionGuard

    guard = SessionGuard()

    fake = mock.MagicMock()
    fake.ok = True
    fake.trading_open_now = True
    fake.reason = "open"
    fake.next_open_time_utc = None
    fake.estimated_resume_time_utc = None
    fake.active_window_utc = None

    with mock.patch(
        "merid.event_venues.kalshi.exchange_availability.get_kalshi_exchange_availability",
        return_value=mock.MagicMock(snapshot=lambda: fake),
    ):
        s = guard.summary()

    assert s["trading_allowed"] is True
    assert s["maintenance_day"] is False

