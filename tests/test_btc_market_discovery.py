import datetime as dt
from decimal import Decimal

import pytest

from merid.event_venues.base import EventMarket, EventOutcome
from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
from merid.lanes.btc15m_lane import BTC15MLane, BTC15MLaneConfig
from merid.resilience.result import OperationResult


class _DummyClient:
    def __init__(self, markets):
        self._markets = markets

    async def list_markets_result(self, filter_params=None):
        return OperationResult.ok(self._markets)


class _UnlockedPhase:
    name = "PHASE_1"

    def is_asset_unlocked(self, asset: str) -> bool:
        return True

    def is_timeframe_unlocked(self, timeframe: str) -> bool:
        return True


def _mk_market(ticker: str, question: str, minutes_out: int, volume: int) -> EventMarket:
    return EventMarket(
        market_id=ticker,
        venue="kalshi",
        question=question,
        description=question,
        outcomes=[EventOutcome("yes", "yes", Decimal("0.5"))],
        raw_data={"event_ticker": "KXBTC"},
        end_date=dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutes_out),
        volume=Decimal(str(volume)),
    )


@pytest.mark.asyncio
async def test_btc_pipeline_filters_and_sorts():
    markets = [
        _mk_market("KXBTC_15_LOWVOL", "BTC 15m move", minutes_out=12, volume=25),
        _mk_market("KXBTC_15_HIGHVOL", "BTC 15m move bigger", minutes_out=8, volume=80),
        _mk_market("KXBTC_1H", "BTC hourly move", minutes_out=70, volume=200),
        EventMarket(
            market_id="KXETH_15",
            venue="kalshi",
            question="ETH 15m move",
            description="ETH 15m move",
            outcomes=[EventOutcome("yes", "yes", Decimal("0.5"))],
            raw_data={"event_ticker": "KXETH"},
            end_date=dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10),
            volume=Decimal("999"),
        ),
    ]
    catalog = KalshiMarketCatalog(client=_DummyClient(markets), max_markets=10)
    await catalog.refresh()

    lane = BTC15MLane(BTC15MLaneConfig())
    lane._catalog = catalog
    lane._promotion_engine = _UnlockedPhase()

    discovered, diag = await lane._fetch_market_data(cycle_id="test-cycle")

    assert diag["btc_markets"] == 3
    assert diag["timeframe_markets"] == 2
    assert [m["ticker"] for m in discovered] == ["KXBTC_15_HIGHVOL", "KXBTC_15_LOWVOL"]


@pytest.mark.asyncio
async def test_btc_pipeline_reports_empty_reason():
    catalog = KalshiMarketCatalog(client=_DummyClient([]), max_markets=5)
    await catalog.refresh()

    lane = BTC15MLane(BTC15MLaneConfig())
    lane._catalog = catalog
    lane._promotion_engine = _UnlockedPhase()

    discovered, diag = await lane._fetch_market_data(cycle_id="test-empty")

    assert discovered == []
    assert diag["reason"] == "api_empty"
