"""Test KalshiMarketCatalog 15m metadata backfill."""

import asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

from merid.resilience.result import OperationResult
from merid.event_venues.base import EventMarket, EventOutcome
from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog


@pytest.fixture
def metadata_catalog():
    catalog = KalshiMarketCatalog(client=AsyncMock())
    catalog._metadata_backfill_enabled = True
    catalog._metadata_backfill_max_age_s = 60.0
    catalog._metadata_backfill_max_attempts = 3
    catalog._metadata_backfill_retry_delay_s = 0.0
    catalog._metadata_failure_threshold = 2
    return catalog


def _build_ticker(now_utc: datetime, minutes_ahead: int = 15) -> tuple[str, datetime]:
    """Return a 15m BTC ticker and matching expiry (UTC) in the test future."""
    et = now_utc.astimezone(ZoneInfo("America/New_York"))
    expiry_et = et + timedelta(minutes=minutes_ahead)
    body = expiry_et.strftime("%y%b%d%H%M").upper()
    ticker = f"KXBTC15M-{body}-45"
    expiry_utc = expiry_et.astimezone(timezone.utc)
    return ticker, expiry_utc


def _make_event_market(
    now_utc: datetime,
    open_time: datetime,
    floor_strike: float | None,
    minutes_ahead: int = 15,
    strike_price: float | None = None,
) -> EventMarket:
    market_id, end_date = _build_ticker(now_utc, minutes_ahead)
    raw = {
        "status": "open",
        "series_ticker": "KXBTC15M",
        "event_ticker": "KXBTC15M",
        "close_time": end_date.isoformat(),
    }
    if floor_strike is not None:
        raw["floor_strike"] = floor_strike
    if strike_price is not None:
        raw["strike_price"] = strike_price

    return EventMarket(
        market_id=market_id,
        venue="kalshi",
        question="Will BTC be above the target price?",
        description="Will BTC be above the target price at expiry?",
        outcomes=[
            EventOutcome(outcome_id="yes", outcome_name="Yes", price=Decimal("0.5")),
            EventOutcome(outcome_id="no", outcome_name="No", price=Decimal("0.5")),
        ],
        open_time=open_time,
        end_date=end_date,
        raw_data=raw,
    )


@pytest.mark.asyncio
async def test_backfill_resolves_metadata_for_recently_opened_market(metadata_catalog):
    """A 15m market missing floor_strike and opened recently is backfilled."""
    now = datetime.now(timezone.utc)
    open_time = now - timedelta(seconds=5)

    # Initial market has no floor_strike → invalid_metadata
    initial = _make_event_market(
        now_utc=now,
        open_time=open_time,
        floor_strike=None,
    )
    catalog_market = metadata_catalog._enrich(initial, now)
    assert catalog_market.health_status == "invalid_metadata"
    assert catalog_market.floor_strike is None

    # Backfill endpoint returns a market with floor_strike populated
    resolved = _make_event_market(
        now_utc=now,
        open_time=open_time,
        floor_strike=80000.0,
    )
    metadata_catalog._client.get_market_result = AsyncMock(
        return_value=OperationResult.ok(resolved)
    )

    updated = await metadata_catalog._backfill_15m_metadata([catalog_market], now)
    assert len(updated) == 1
    assert updated[0].health_status == "ok"
    assert updated[0].floor_strike == 80000.0


@pytest.mark.asyncio
async def test_backfill_skips_stale_market(metadata_catalog):
    """A market missing floor_strike but opened long ago is not retried."""
    now = datetime.now(timezone.utc)
    open_time = now - timedelta(minutes=5)

    initial = _make_event_market(
        now_utc=now,
        open_time=open_time,
        floor_strike=None,
    )
    catalog_market = metadata_catalog._enrich(initial, now)

    updated = await metadata_catalog._backfill_15m_metadata([catalog_market], now)
    assert len(updated) == 1
    assert updated[0].health_status == "invalid_metadata"
    metadata_catalog._client.get_market_result.assert_not_called()


@pytest.mark.asyncio
async def test_backfill_skips_without_open_time(metadata_catalog):
    """A market with no open_time is quarantined, not retried."""
    now = datetime.now(timezone.utc)

    initial = _make_event_market(
        now_utc=now,
        open_time=None,
        floor_strike=None,
    )
    catalog_market = metadata_catalog._enrich(initial, now)

    updated = await metadata_catalog._backfill_15m_metadata([catalog_market], now)
    assert len(updated) == 1
    assert updated[0].health_status == "invalid_metadata"
    metadata_catalog._client.get_market_result.assert_not_called()


@pytest.mark.asyncio
async def test_backfill_gives_up_after_max_attempts(metadata_catalog):
    """If Kalshi never populates floor_strike, the market stays invalid."""
    now = datetime.now(timezone.utc)
    open_time = now - timedelta(seconds=5)

    initial = _make_event_market(
        now_utc=now,
        open_time=open_time,
        floor_strike=None,
    )
    catalog_market = metadata_catalog._enrich(initial, now)

    # Always missing; use the same market_id so backfill keeps re-enriching
    still_missing = _make_event_market(
        now_utc=now,
        open_time=open_time,
        floor_strike=None,
    )
    metadata_catalog._client.get_market_result = AsyncMock(
        return_value=OperationResult.ok(still_missing)
    )

    updated = await metadata_catalog._backfill_15m_metadata([catalog_market], now)
    assert len(updated) == 1
    assert updated[0].health_status == "invalid_metadata"
    assert metadata_catalog._client.get_market_result.call_count == 3
