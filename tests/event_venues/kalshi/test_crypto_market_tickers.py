import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from typing import TYPE_CHECKING

import pytest


class _DummyCatalog:
    def __init__(self, markets):
        self._markets = markets

    def get_markets_by_category(self, category, timeframe=None, asset=None):
        return [
            m for m in self._markets
            if (category is None or getattr(m, "category", None) == category)
            and (timeframe is None or getattr(m, "timeframe", None) == timeframe)
        ]


if TYPE_CHECKING:  # pragma: no cover - for type checkers only
    from merid.event_venues.kalshi.market_catalog import CatalogMarket


def _mk_market(ticker: str, asset: str):
    from merid.event_venues.base import EventMarket
    from merid.event_venues.kalshi.market_catalog import CatalogMarket

    ev = EventMarket(
        market_id=ticker,
        venue="kalshi",
        question=f"{asset} 15m test",
        description="",
        outcomes=[],
    )
    return CatalogMarket(
        market=ev,
        asset=asset,
        timeframe="15m",
        category="crypto",
    )


def test_normalize_series_ticker_handles_instance_codes():
    import importlib

    sys.path[:] = [str(ROOT)] + [p for p in sys.path if p != str(ROOT)]
    importlib.import_module("trading.trade_mode")
    from merid.event_venues.kalshi.crypto_markets import normalize_series_ticker

    assert normalize_series_ticker("KXBTC15M-26MAR231500-00") == "KXBTC15M"
    assert normalize_series_ticker("KXDOGE15M-26MAR231515-15") == "KXDOGE15M"
    assert normalize_series_ticker("") == ""


def test_build_crypto_market_tickers_includes_all_assets():
    import importlib

    sys.path[:] = [str(ROOT)] + [p for p in sys.path if p != str(ROOT)]
    importlib.import_module("trading.trade_mode")
    from merid.event_venues.kalshi.crypto_markets import build_crypto_market_tickers

    markets = [
        _mk_market("KXBTC15M-26MAR231500-00", "BTC"),
        _mk_market("KXETH15M-26MAR231515-15", "ETH"),
        _mk_market("KXSOL15M-26MAR231530-30", "SOL"),
        _mk_market("KXXRP15M-26MAR231545-45", "XRP"),
        _mk_market("KXDOGE15M-26MAR231600-00", "DOGE"),
    ]
    catalog = _DummyCatalog(markets)

    tickers = build_crypto_market_tickers(catalog, timeframe="15m")

    assert "KXDOGE15M-26MAR231600-00" in tickers
    for prefix in ("KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"):
        assert any(t.startswith(prefix) for t in tickers)
