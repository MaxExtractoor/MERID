"""Canonical Kalshi crypto series metadata."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_hourly_tickers_no_h1_suffix():
    from config.kalshi_crypto_series_meta import SERIES_META_BY_TICKER

    assert SERIES_META_BY_TICKER["KXBTC"].timeframe == "1h"
    assert "KXBTCH1" not in SERIES_META_BY_TICKER


def test_infer_doge_15m():
    from config.kalshi_crypto_series_meta import infer_asset_timeframe_from_ticker

    assert infer_asset_timeframe_from_ticker("KXDOGE15M") == ("DOGE", "15m")


def test_kalshi_universe_matches_meta():
    from config.kalshi_universe import KALSHI_CRYPTO_PRODUCTS
    from config.kalshi_crypto_series_meta import build_kalshi_crypto_products

    assert KALSHI_CRYPTO_PRODUCTS == build_kalshi_crypto_products()


def test_canonical_timeframe_from_series_ticker():
    from config.kalshi_crypto_series_meta import canonical_timeframe_from_series_ticker

    assert canonical_timeframe_from_series_ticker("KXBTC") == "1h"
    assert canonical_timeframe_from_series_ticker("KXBTCD1") == "daily"
    assert canonical_timeframe_from_series_ticker("KXBTC15M") == "15m"
    assert canonical_timeframe_from_series_ticker("KXBTCH1") == "1h"


# ============== Task 1: Monthly/Annual Series Extension ==============


def test_monthly_series_exist_for_all_assets():
    from config.kalshi_crypto_series_meta import get_series_meta

    assets = ("BTC", "ETH", "SOL", "XRP", "DOGE")
    for asset in assets:
        meta = get_series_meta(asset, "monthly")
        assert meta is not None, f"No monthly series for {asset}"
        assert meta.timeframe == "monthly"


def test_btc_annual_series_exists():
    from config.kalshi_crypto_series_meta import get_series_meta

    meta = get_series_meta("BTC", "annual")
    assert meta is not None
    assert meta.series_ticker == "KXBTCY"


def test_monthly_tickers_correct():
    from config.kalshi_crypto_series_meta import get_series_meta

    expected = {
        "BTC": "KXBTC1M",
        "ETH": "KXETH1M",
        "SOL": "KXSOL1M",
        "XRP": "KXXRP1M",
        "DOGE": "KXDOGE1M",
    }
    for asset, ticker in expected.items():
        meta = get_series_meta(asset, "monthly")
        assert meta.series_ticker == ticker


def test_new_series_in_by_ticker_index():
    from config.kalshi_crypto_series_meta import SERIES_META_BY_TICKER

    assert "KXBTC1M" in SERIES_META_BY_TICKER
    assert "KXBTCY" in SERIES_META_BY_TICKER


def test_supports_basis_defaults_true():
    from config.kalshi_crypto_series_meta import SERIES_META_LIST

    for meta in SERIES_META_LIST:
        assert meta.supports_basis is True


def test_supports_trend_defaults_true():
    from config.kalshi_crypto_series_meta import SERIES_META_LIST

    for meta in SERIES_META_LIST:
        assert meta.supports_trend is True


def test_timeframekey_covers_annual():
    from config.kalshi_crypto_series_meta import SeriesMeta

    # Confirm SeriesMeta accepts "annual" without a TypeError
    m = SeriesMeta("BTC", "annual", "KXBTCY", "annual", "cfb_rti_btc")
    assert m.timeframe == "annual"
