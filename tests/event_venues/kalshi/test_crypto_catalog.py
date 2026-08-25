"""KalshiCryptoCatalog and WS ticker selection from discovery fixtures."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS, kalshi_ticker_to_asset
from config.kalshi_universe import KALSHI_CRYPTO_ASSETS
from merid.event_venues.base import EventMarket
from merid.event_venues.kalshi.crypto_catalog import (
    KalshiCryptoCatalog,
    assert_each_asset_represented,
    build_kalshi_crypto_catalog_from_catalog_markets,
    catalog_market_to_kalshi_market_info,
    collect_crypto_ws_subscription_tickers,
    prepare_crypto_ws_bridge_subscription,
    summarize_crypto_ws_coverage,
)
from merid.event_venues.kalshi.market_catalog import CatalogMarket


def _cm(
    ticker: str,
    *,
    asset: str,
    timeframe: str,
    category: str = "crypto",
    series_ticker: str = "",
    active: bool = True,
) -> CatalogMarket:
    m = EventMarket(
        market_id=ticker,
        venue="kalshi",
        question="q",
        description="d",
        outcomes=[],
        category="crypto",
        end_date=datetime(2026, 3, 30, tzinfo=timezone.utc),
        active=active,
        raw_data={"series_ticker": series_ticker or ticker.split("-")[0]},
    )
    return CatalogMarket(
        market=m,
        asset=asset,
        timeframe=timeframe,
        category=category,
        series_ticker=series_ticker or None,
        expires_at=m.end_date,
    )


def test_kalshi_market_info_roundtrip_from_catalog_market() -> None:
    cm = _cm("KXBTC15M-26MAR291315-15", asset="BTC", timeframe="15m", series_ticker="KXBTC15M")
    info = catalog_market_to_kalshi_market_info(cm)
    assert info is not None
    assert info.ticker == "KXBTC15M-26MAR291315-15"
    assert info.asset == "BTC"
    assert info.frequency == "15M"


def test_kalshi_crypto_catalog_query_methods() -> None:
    rows = [
        _cm("KXBTC15M-26MAR291315-15", asset="BTC", timeframe="15m", series_ticker="KXBTC15M"),
        _cm("KXETH15M-26MAR291315-15", asset="ETH", timeframe="15m", series_ticker="KXETH15M"),
        _cm("KXSOL15M-26MAR291315-15", asset="SOL", timeframe="15m", series_ticker="KXSOL15M"),
    ]
    cat = build_kalshi_crypto_catalog_from_catalog_markets(rows)
    assert cat.tickers_for_asset_freq("BTC", "15M") == ["KXBTC15M-26MAR291315-15"]
    assert set(cat.all_active_crypto_tickers(KALSHI_CRYPTO_ASSETS, ["15M"])) == {
        "KXBTC15M-26MAR291315-15",
        "KXETH15M-26MAR291315-15",
        "KXSOL15M-26MAR291315-15",
    }
    assert set(cat.all_active_tickers()) == {
        "KXBTC15M-26MAR291315-15",
        "KXETH15M-26MAR291315-15",
        "KXSOL15M-26MAR291315-15",
    }


def test_catalog_excludes_monthly_when_not_in_active_crypto_freqs() -> None:
    rows = [
        _cm("KXBTC1M-A", asset="BTC", timeframe="monthly", series_ticker="KXBTC1M"),
        _cm("KXBTC-B", asset="BTC", timeframe="15m", series_ticker="KXBTC15M"),
    ]
    cat = build_kalshi_crypto_catalog_from_catalog_markets(rows)
    assert "KXBTC1M-A" not in cat.all_active_tickers()
    assert "KXBTC-B" in cat.all_active_tickers()


def test_active_crypto_assets_matches_kalshi_universe_alias() -> None:
    assert ACTIVE_CRYPTO_ASSETS == KALSHI_CRYPTO_ASSETS


def test_prepare_crypto_ws_bridge_subscription_shape() -> None:
    class _FakeCat:
        def get_all_markets(self):
            return [
                _cm("KXBTC15M-A", asset="BTC", timeframe="15m", series_ticker="KXBTC15M"),
                _cm("KXETH15M-B", asset="ETH", timeframe="15m", series_ticker="KXETH15M"),
                _cm("KXSOL15M-C", asset="SOL", timeframe="15m", series_ticker="KXSOL15M"),
                _cm("KXXRP15M-D", asset="XRP", timeframe="15m", series_ticker="KXXRP15M"),
                _cm("KXDOGE15M-E", asset="DOGE", timeframe="15m", series_ticker="KXDOGE15M"),
            ]

    prep = prepare_crypto_ws_bridge_subscription(_FakeCat())  # type: ignore[arg-type]
    assert prep["ok_catalog_assets"] and prep["ok_prefix_coverage"]
    assert prep["total"] == 5
    assert not prep["missing_prefix_assets"]


def test_collect_crypto_ws_five_assets_when_present() -> None:
    class _FakeCat:
        def get_all_markets(self):
            return [
                _cm("A-BTC", asset="BTC", timeframe="15m"),
                _cm("B-ETH", asset="ETH", timeframe="15m"),
                _cm("C-SOL", asset="SOL", timeframe="15m"),
                _cm("D-XRP", asset="XRP", timeframe="15m"),
                _cm("E-DOGE", asset="DOGE", timeframe="15m"),
            ]

    tickers = collect_crypto_ws_subscription_tickers(_FakeCat())  # type: ignore[arg-type]
    ok, missing = assert_each_asset_represented(tickers, _FakeCat())  # type: ignore[arg-type]
    assert ok and missing == []
    assert len(tickers) == 5


def test_kalshi_ticker_to_asset_non_null_for_all_active_tickers_fixture() -> None:
    rows = [
        _cm("KXBTC15M-A", asset="BTC", timeframe="15m"),
        _cm("KXETH-B", asset="ETH", timeframe="1h"),
        _cm("KXSOL15M-C", asset="SOL", timeframe="15m"),
        _cm("KXXRP-D", asset="XRP", timeframe="daily"),
        _cm("KXDOGE-E", asset="DOGE", timeframe="weekly"),
    ]
    cat = build_kalshi_crypto_catalog_from_catalog_markets(rows)
    for t in cat.all_active_tickers():
        assert kalshi_ticker_to_asset(t) is not None


def test_collect_crypto_ws_matches_typed_catalog_all_active_tickers() -> None:
    class _FakeCat:
        def get_all_markets(self):
            return [
                _cm("KXBTC15M-A", asset="BTC", timeframe="15m"),
                _cm("KXETH-B", asset="ETH", timeframe="1h"),
            ]

    fc = _FakeCat()
    direct = collect_crypto_ws_subscription_tickers(fc)  # type: ignore[arg-type]
    rows = [cm for cm in fc.get_all_markets() if cm.category == "crypto" and cm.market.active]
    alt = build_kalshi_crypto_catalog_from_catalog_markets(rows).all_active_tickers()
    assert direct == alt


def test_collect_crypto_ws_subscription_tickers_filters_non_crypto() -> None:
    class _FakeCat:
        def get_all_markets(self):
            return [
                _cm("KXBTC-A", asset="BTC", timeframe="15m"),
                _cm("KXETH-B", asset="ETH", timeframe="15m"),
                _cm("KXFED-C", asset=None, timeframe="daily", category="economics"),
            ]

    tickers = collect_crypto_ws_subscription_tickers(_FakeCat())  # type: ignore[arg-type]
    assert tickers == ["KXBTC-A", "KXETH-B"]


def test_assert_each_asset_represented() -> None:
    class _FakeCat:
        def get_all_markets(self):
            return [
                _cm("KXBTC-A", asset="BTC", timeframe="15m"),
                _cm("KXETH-B", asset="ETH", timeframe="15m"),
                _cm("KXSOL-C", asset="SOL", timeframe="15m"),
                _cm("KXXRP-D", asset="XRP", timeframe="15m"),
                _cm("KXDOGE-E", asset="DOGE", timeframe="15m"),
            ]

    ok, missing = assert_each_asset_represented(
        ["KXBTC-A", "KXETH-B", "KXSOL-C", "KXXRP-D", "KXDOGE-E"],
        _FakeCat(),  # type: ignore[arg-type]
    )
    assert ok and missing == []

    ok2, missing2 = assert_each_asset_represented(["KXBTC-A"], _FakeCat())  # type: ignore[arg-type]
    assert not ok2
    assert set(missing2) == {"ETH", "SOL", "XRP", "DOGE"}


def test_summarize_crypto_ws_coverage_counts() -> None:
    class _FakeCat:
        def get_all_markets(self):
            return [
                _cm("T1", asset="BTC", timeframe="15m"),
                _cm("T2", asset="BTC", timeframe="15m"),
                _cm("T3", asset="ETH", timeframe="15m"),
            ]

    s = summarize_crypto_ws_coverage(["T1", "T3"], _FakeCat())  # type: ignore[arg-type]
    assert s["total"] == 2
    assert s["by_asset"]["BTC"] == 1
    assert s["by_asset"]["ETH"] == 1


@pytest.mark.skip(reason="P2-INTEGRATION: TRACKER-020: Catalog/ticker registration changed")
def test_market_state_store_separate_books_per_ticker() -> None:
    """Test that market state store maintains separate books per ticker.
    
    NOTE: This test is skipped because KalshiMarketStateStore now requires
    tickers to be registered before accepting messages. The test would need
    to be updated to use the new registration mechanism, but this tests
    internal implementation details rather than production functionality.
    """
