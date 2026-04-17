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


def test_classify_no_action_reason_buckets() -> None:
    from merid.prediction.trading_agent import _classify_pm_no_action_reason

    assert _classify_pm_no_action_reason("edge below threshold") == "edge_below_threshold"
    assert _classify_pm_no_action_reason("confidence below minimum") == "confidence"
    assert _classify_pm_no_action_reason("something unknown") == "other"
