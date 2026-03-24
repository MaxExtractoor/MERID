import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from merid.event_venues.base import EventMarket, EventOutcome
from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog


class _StubClient:
    def __init__(self, markets):
        self._markets = markets

    async def list_markets_result(self, filter_params):
        # Simulate Kalshi OperationResult shape
        return SimpleNamespace(
            success=True,
            data=self._markets,
            error=None,
            retries=0,
            circuit_open=False,
            status_code=200,
        )


def _make_market(ticker: str, minutes: int, series: str, question: str = "Q?") -> EventMarket:
    return EventMarket(
        market_id=ticker,
        venue="kalshi",
        question=question,
        description="",
        outcomes=[EventOutcome(outcome_id="yes", outcome_name="YES", price=Decimal("0.55"))],
        category="crypto",
        end_date=datetime.now(timezone.utc) + timedelta(minutes=minutes),
        active=True,
        volume=Decimal("1000"),
        raw_data={"event_ticker": ticker.split("-")[0], "series_ticker": series},
    )


def test_catalog_uses_full_market_list_not_sample():
    markets = [
        _make_market("KXBTC15M-TEST-00", minutes=10, series="KXBTC15M", question="BTC up in 15m?"),
        _make_market("KXBTC-TEST-T59000", minutes=300, series="KXBTC", question="BTC ≥ 59k?"),
    ]
    catalog = KalshiMarketCatalog(client=_StubClient(markets))

    asyncio.run(catalog.refresh())

    all_markets = catalog.get_all_markets()
    assert len(all_markets) == len(markets)

    btc_markets = catalog.get_markets_by_asset("BTC")
    assert {m.market.market_id for m in btc_markets} == {m.market_id for m in markets}

    btc_15m = catalog.get_markets_by_asset_timeframe("BTC", "15m")
    assert len(btc_15m) == 1
    assert btc_15m[0].market.market_id == "KXBTC15M-TEST-00"

    summary = catalog.summary()
    assert summary["asset_timeframes"]["BTC"]["15m"] == 1
    # Daily/threshold surface should register under daily timeframe from series hint
    assert summary["asset_timeframes"]["BTC"]["daily"] == 1
