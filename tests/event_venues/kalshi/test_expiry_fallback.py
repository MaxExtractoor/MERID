"""Tests for ticker-based crypto interval expiry repair."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from merid.event_venues.base import EventMarket, EventOutcome
from merid.event_venues.kalshi.expiry_fallback import (
    apply_crypto_interval_expiry_fallback,
    expiry_fallback_enabled,
)


def _minimal_market(market_id: str, end_date: datetime | None) -> EventMarket:
    return EventMarket(
        market_id=market_id,
        venue="kalshi",
        question="q",
        description="d",
        outcomes=[
            EventOutcome(
                outcome_id="y",
                outcome_name="Yes",
                price=Decimal("0.5"),
            )
        ],
        end_date=end_date,
    )


def test_apply_fallback_repairs_stale_end_date(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MERID_PM_EXPIRY_FALLBACK_CRYPTO", "true")
    assert expiry_fallback_enabled() is True
    # 26APR071830 → 2026-04-07 18:30 America/New_York; window ends +15m
    m = _minimal_market(
        "KXBTC15M-26APR071830-30",
        datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    now = datetime(2026, 4, 7, 22, 0, tzinfo=timezone.utc)
    out = apply_crypto_interval_expiry_fallback(m, now)
    assert out.end_date is not None
    assert out.end_date.tzinfo is not None
    assert out.end_date > now


def test_apply_fallback_respects_good_end_date(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MERID_PM_EXPIRY_FALLBACK_CRYPTO", "true")
    future = datetime(2030, 1, 1, tzinfo=timezone.utc)
    m = _minimal_market("KXBTC15M-26APR071830-30", future)
    now = datetime(2026, 4, 7, 22, 0, tzinfo=timezone.utc)
    out = apply_crypto_interval_expiry_fallback(m, now)
    assert out.end_date == future


def test_disabled_leaves_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MERID_PM_EXPIRY_FALLBACK_CRYPTO", "false")
    assert expiry_fallback_enabled() is False
    stale = datetime(2020, 1, 1, tzinfo=timezone.utc)
    m = _minimal_market("KXBTC15M-26APR071830-30", stale)
    out = apply_crypto_interval_expiry_fallback(
        m, datetime(2026, 4, 7, 22, 0, tzinfo=timezone.utc)
    )
    assert out.end_date == stale


def test_non_interval_ticker_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MERID_PM_EXPIRY_FALLBACK_CRYPTO", "true")
    stale = datetime(2020, 1, 1, tzinfo=timezone.utc)
    m = _minimal_market("KXBTCD-26APR07-T12345", stale)
    out = apply_crypto_interval_expiry_fallback(
        m, datetime(2026, 4, 7, 22, 0, tzinfo=timezone.utc)
    )
    assert out.end_date == stale


def test_ticker_expiry_day_24_canonical_not_poisoned_by_legacy() -> None:
    """Regression: 2026-08-24 incident.

    On days with DD >= 24 the legacy day-first regex (DDMON + HHMMSS) parses
    the same body with hh >= 24 and fails.  The early-return
    ``legacy_match and legacy_dt is None`` used to fire even when the canonical
    year-first parse succeeded, so every live 15m position was rejected by
    PositionMonitor as expired and no exit policy ever ran (100% losses).
    """
    from merid.event_venues.kalshi.expiry_fallback import parse_kalshi_15m_ticker_expiry

    expiry_dt, is_15m = parse_kalshi_15m_ticker_expiry("KXXRP15M-26AUG240045-45")
    assert is_15m is True
    assert expiry_dt is not None
    # 2026-08-24 00:45 America/New_York = 04:45 UTC
    assert expiry_dt == datetime(2026, 8, 24, 4, 45, tzinfo=timezone.utc)

    expiry_dt2, _ = parse_kalshi_15m_ticker_expiry("KXBTC15M-26AUG241330-30")
    assert expiry_dt2 == datetime(2026, 8, 24, 17, 30, tzinfo=timezone.utc)

    # Day 23 (legacy parse succeeds with hh=23) still prefers canonical.
    expiry_dt3, _ = parse_kalshi_15m_ticker_expiry("KXXRP15M-26AUG232330-30")
    assert expiry_dt3 == datetime(2026, 8, 24, 3, 30, tzinfo=timezone.utc)


def test_is_expired_ticker_live_on_day_24() -> None:
    """A live 15m ticker on DD >= 24 must not be treated as expired."""
    from merid.position_management.position_monitor import _is_expired_ticker

    # Far-future ticker is never expired.
    assert _is_expired_ticker("KXBTC15M-30DEC312359-00") is False
