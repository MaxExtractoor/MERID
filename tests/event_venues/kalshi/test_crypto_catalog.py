"""Tests for merid/event_venues/kalshi/crypto_catalog.py.

Uses fixture-based CatalogMarket objects to verify that:
  - KalshiCryptoCatalog covers all five assets when fixtures include them
  - kalshi_ticker_to_asset returns non-null for every ticker in all_active_tickers
  - WS subscription helpers build correct ticker lists
  - Coverage checks correctly identify missing assets
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from unittest.mock import MagicMock

import pytest

from merid.event_venues.kalshi.crypto_catalog import (
    KalshiCryptoCatalog,
    assert_each_asset_represented,
    build_kalshi_crypto_catalog_from_catalog_markets,
    check_ws_ticker_asset_coverage,
    collect_crypto_ws_subscription_tickers,
    kalshi_ticker_to_asset,
    summarize_crypto_ws_coverage,
)
from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS, ACTIVE_CRYPTO_WS_TIMEFRAMES


# ── Fixture helpers ──────────────────────────────────────────────────────────


def _make_catalog_market(
    ticker: str,
    asset: str,
    timeframe: str,
    status: str = "open",
) -> MagicMock:
    """Create a minimal CatalogMarket mock."""
    market = MagicMock()
    market.ticker = ticker
    market.status = status

    cm = MagicMock()
    cm.asset = asset
    cm.timeframe = timeframe
    cm.market = market
    cm.market.ticker = ticker
    cm.market.status = status
    return cm


def _make_full_universe_markets() -> list:
    """One open market per (asset, timeframe) for all five assets × four timeframes."""
    markets = []
    for asset in ACTIVE_CRYPTO_ASSETS:
        for tf in ACTIVE_CRYPTO_WS_TIMEFRAMES:
            ticker = f"KX{asset}-TF{tf.upper()}-T50000"
            markets.append(_make_catalog_market(ticker, asset, tf))
    return markets


# ── kalshi_ticker_to_asset ────────────────────────────────────────────────────


class TestKalshiTickerToAsset:
    def test_btc_ticker_returns_btc(self) -> None:
        assert kalshi_ticker_to_asset("KXBTCD-25JUN-T100000") == "BTC"

    def test_eth_ticker_returns_eth(self) -> None:
        assert kalshi_ticker_to_asset("KXETH15-25JUN-T3200") == "ETH"

    def test_sol_ticker_returns_sol(self) -> None:
        assert kalshi_ticker_to_asset("KXSOLD-25JUN-T250") == "SOL"

    def test_xrp_ticker_returns_xrp(self) -> None:
        assert kalshi_ticker_to_asset("KXXRPD-25JUN-T050") == "XRP"

    def test_doge_ticker_returns_doge(self) -> None:
        assert kalshi_ticker_to_asset("KXDOGE15-25JUN-T010") == "DOGE"

    def test_bitcoin_long_form_returns_btc(self) -> None:
        assert kalshi_ticker_to_asset("KXBITCOIN-25JUN-T100000") == "BTC"

    def test_non_crypto_returns_none(self) -> None:
        assert kalshi_ticker_to_asset("KXCPI-25JUN-100") is None

    def test_unknown_prefix_returns_none(self) -> None:
        assert kalshi_ticker_to_asset("UNKNOWN-TICKER") is None

    def test_empty_string_returns_none(self) -> None:
        assert kalshi_ticker_to_asset("") is None


# ── KalshiCryptoCatalog ───────────────────────────────────────────────────────


class TestKalshiCryptoCatalog:
    def test_reload_keeps_crypto_markets(self) -> None:
        catalog = KalshiCryptoCatalog()
        markets = _make_full_universe_markets()
        kept = catalog.reload(markets)
        assert kept == 20  # 5 assets × 4 timeframes

    def test_reload_excludes_non_crypto_asset(self) -> None:
        catalog = KalshiCryptoCatalog()
        markets = _make_full_universe_markets()
        markets.append(_make_catalog_market("KXCPI-25JUN-100", "CPI", "daily"))
        kept = catalog.reload(markets)
        assert kept == 20  # CPI excluded

    def test_reload_excludes_inactive_timeframe(self) -> None:
        catalog = KalshiCryptoCatalog()
        markets = _make_full_universe_markets()
        markets.append(_make_catalog_market("KXBTC-25JUN-MONTHLY", "BTC", "monthly"))
        kept = catalog.reload(markets)
        assert kept == 20  # monthly excluded

    def test_reload_excludes_closed_markets(self) -> None:
        catalog = KalshiCryptoCatalog()
        markets = [
            _make_catalog_market("KXBTCD-OPEN-T50000", "BTC", "daily", "open"),
            _make_catalog_market("KXBTCD-CLOSED-T50000", "BTC", "daily", "closed"),
        ]
        kept = catalog.reload(markets)
        assert kept == 1

    def test_iter_tickers_returns_correct_asset_timeframe(self) -> None:
        catalog = KalshiCryptoCatalog()
        catalog.reload(_make_full_universe_markets())
        tickers = catalog.iter_tickers("BTC", "daily")
        assert len(tickers) == 1
        assert "BTC" in tickers[0].upper() or "KXBTC" in tickers[0].upper()

    def test_all_active_tickers_covers_all_five_assets(self) -> None:
        catalog = KalshiCryptoCatalog()
        catalog.reload(_make_full_universe_markets())
        tickers = catalog.all_active_tickers()
        assert len(tickers) == 20

    def test_all_active_tickers_each_resolves_to_asset(self) -> None:
        catalog = KalshiCryptoCatalog()
        catalog.reload(_make_full_universe_markets())
        for ticker in catalog.all_active_tickers():
            asset = kalshi_ticker_to_asset(ticker)
            assert asset is not None, f"ticker {ticker!r} did not resolve to an asset"
            assert asset in ACTIVE_CRYPTO_ASSETS

    def test_assets_covered_returns_all_five(self) -> None:
        catalog = KalshiCryptoCatalog()
        catalog.reload(_make_full_universe_markets())
        assert set(catalog.assets_covered()) == set(ACTIVE_CRYPTO_ASSETS)

    def test_len_matches_kept_count(self) -> None:
        catalog = KalshiCryptoCatalog()
        markets = _make_full_universe_markets()
        catalog.reload(markets)
        assert len(catalog) == 20

    def test_reload_empty_gives_zero(self) -> None:
        catalog = KalshiCryptoCatalog()
        assert catalog.reload([]) == 0

    def test_grid_summary_has_all_assets(self) -> None:
        catalog = KalshiCryptoCatalog()
        catalog.reload(_make_full_universe_markets())
        summary = catalog.grid_summary()
        assert set(summary.keys()) == set(ACTIVE_CRYPTO_ASSETS)

    def test_grid_summary_has_all_timeframes(self) -> None:
        catalog = KalshiCryptoCatalog()
        catalog.reload(_make_full_universe_markets())
        summary = catalog.grid_summary()
        for asset_row in summary.values():
            assert set(asset_row.keys()) == set(ACTIVE_CRYPTO_WS_TIMEFRAMES)


# ── build_kalshi_crypto_catalog_from_catalog_markets ─────────────────────────


class TestBuildCatalog:
    def test_factory_produces_correct_count(self) -> None:
        markets = _make_full_universe_markets()
        catalog = build_kalshi_crypto_catalog_from_catalog_markets(markets)
        assert len(catalog) == 20


# ── collect_crypto_ws_subscription_tickers ────────────────────────────────────


class TestCollectWsTickers:
    def test_returns_all_tickers_from_catalog(self) -> None:
        markets = _make_full_universe_markets()
        catalog = build_kalshi_crypto_catalog_from_catalog_markets(markets)
        tickers = collect_crypto_ws_subscription_tickers(catalog)
        assert len(tickers) == 20

    def test_empty_catalog_returns_empty_list(self) -> None:
        catalog = KalshiCryptoCatalog()
        tickers = collect_crypto_ws_subscription_tickers(catalog)
        assert tickers == []


# ── summarize_crypto_ws_coverage ─────────────────────────────────────────────


class TestSummarizeCoverage:
    def test_full_universe_coverage_complete(self) -> None:
        markets = _make_full_universe_markets()
        catalog = build_kalshi_crypto_catalog_from_catalog_markets(markets)
        tickers = collect_crypto_ws_subscription_tickers(catalog)
        coverage = summarize_crypto_ws_coverage(tickers)
        assert coverage["coverage_complete"] is True
        assert coverage["missing_assets"] == []

    def test_missing_asset_detected(self) -> None:
        # Exclude DOGE markets
        markets = [
            m for m in _make_full_universe_markets() if m.asset != "DOGE"
        ]
        catalog = build_kalshi_crypto_catalog_from_catalog_markets(markets)
        tickers = collect_crypto_ws_subscription_tickers(catalog)
        coverage = summarize_crypto_ws_coverage(tickers)
        assert coverage["coverage_complete"] is False
        assert "DOGE" in coverage["missing_assets"]

    def test_total_ticker_count_matches(self) -> None:
        markets = _make_full_universe_markets()
        catalog = build_kalshi_crypto_catalog_from_catalog_markets(markets)
        tickers = collect_crypto_ws_subscription_tickers(catalog)
        coverage = summarize_crypto_ws_coverage(tickers)
        assert coverage["total_tickers"] == 20


# ── assert_each_asset_represented ────────────────────────────────────────────


class TestAssertEachAssetRepresented:
    def test_passes_with_full_coverage(self) -> None:
        markets = _make_full_universe_markets()
        catalog = build_kalshi_crypto_catalog_from_catalog_markets(markets)
        tickers = collect_crypto_ws_subscription_tickers(catalog)
        # Should not raise
        assert_each_asset_represented(tickers)

    def test_raises_when_asset_missing(self) -> None:
        markets = [m for m in _make_full_universe_markets() if m.asset != "SOL"]
        catalog = build_kalshi_crypto_catalog_from_catalog_markets(markets)
        tickers = collect_crypto_ws_subscription_tickers(catalog)
        with pytest.raises(RuntimeError, match="SOL"):
            assert_each_asset_represented(tickers)


# ── check_ws_ticker_asset_coverage ───────────────────────────────────────────


class TestCheckWsTickerAssetCoverage:
    def test_full_coverage_returns_true(self) -> None:
        markets = _make_full_universe_markets()
        catalog = build_kalshi_crypto_catalog_from_catalog_markets(markets)
        tickers = collect_crypto_ws_subscription_tickers(catalog)
        ok, missing = check_ws_ticker_asset_coverage(tickers)
        assert ok is True
        assert missing == []

    def test_partial_coverage_returns_false_non_strict(self) -> None:
        markets = [m for m in _make_full_universe_markets() if m.asset != "XRP"]
        catalog = build_kalshi_crypto_catalog_from_catalog_markets(markets)
        tickers = collect_crypto_ws_subscription_tickers(catalog)
        ok, missing = check_ws_ticker_asset_coverage(tickers, strict=False)
        assert ok is False
        assert "XRP" in missing

    def test_strict_mode_raises_on_missing_asset(self) -> None:
        markets = [m for m in _make_full_universe_markets() if m.asset != "ETH"]
        catalog = build_kalshi_crypto_catalog_from_catalog_markets(markets)
        tickers = collect_crypto_ws_subscription_tickers(catalog)
        with pytest.raises(RuntimeError, match="ETH"):
            check_ws_ticker_asset_coverage(tickers, strict=True)
