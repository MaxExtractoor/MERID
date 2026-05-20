"""P1-6: Crypto universe / CT wiring must not drift across config, CT, spot, and risk labels."""

from __future__ import annotations

import pytest

from config.kalshi_universe import (
    ACTIVE_CRYPTO_WS_TIMEFRAMES,
    KALSHI_CRYPTO_ASSETS,
    KALSHI_CRYPTO_PRODUCTS,
    KALSHI_CRYPTO_PRODUCT_VALUE_SUFFIXES,
    EXPECTED_SERIES_TICKERS,
    kalshi_agent_grid_catalog_series_tickers,
    kalshi_ct_default_series_tickers,
)
from merid.event_venues.kalshi.constants import ALL_CRYPTO_ASSETS
from merid.event_venues.kalshi.invariants import KALSHI_CRYPTOTIMEFRAMES
from merid.event_venues.kalshi.market_selector import ALL_TIMEFRAMES, resolve_series_ticker
from merid.trading.crypto_spot_service import (
    ASSET_TO_COINBASE_PRODUCT,
    ASSET_TO_BINANCEUS_SYMBOL,
)
from merid.trading.kalshi_continuous_trader import TraderConfig

pytestmark = pytest.mark.kalshi_live_ready


def _parse_kalshi_crypto_product_key(key: str) -> tuple[str, str]:
    parts = key.split("_", 1)
    if len(parts) != 2:
        raise ValueError(f"Bad KALSHI_CRYPTO_PRODUCTS key: {key!r}")
    return parts[0], parts[1]


def test_all_crypto_assets_matches_kalshi_universe_and_spot_maps() -> None:
    assert set(KALSHI_CRYPTO_ASSETS) == set(ALL_CRYPTO_ASSETS)
    assert set(ASSET_TO_COINBASE_PRODUCT.keys()) == ALL_CRYPTO_ASSETS
    assert set(ASSET_TO_BINANCEUS_SYMBOL.keys()) == ALL_CRYPTO_ASSETS


def test_kalshi_cryptotimeframes_matches_ct_selector_tenors() -> None:
    """KALSHI_CRYPTOTIMEFRAMES is the same ordered universe CT resolves via market_selector."""
    assert list(KALSHI_CRYPTOTIMEFRAMES) == list(ALL_TIMEFRAMES)


def test_active_crypto_ws_timeframes_matches_market_selector() -> None:
    """WS subscription filter must stay aligned with CT / grid timeframes."""
    assert ACTIVE_CRYPTO_WS_TIMEFRAMES == ALL_TIMEFRAMES


def test_fifteen_minute_series_targets_include_all_five_assets() -> None:
    """15m strategy / grid must not silently drop ETH/SOL/XRP/DOGE vs BTC-only."""
    tickers = [f"{resolve_series_ticker(a, '15m')}-WATCHLIST" for a in KALSHI_CRYPTO_ASSETS]
    assert len(tickers) == 5
    joined = " ".join(tickers)
    for sym in ("KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"):
        assert sym in joined


def test_trader_config_default_series_equals_ct_allowlist() -> None:
    default = TraderConfig().series_tickers
    expected = kalshi_ct_default_series_tickers()
    assert sorted(default) == sorted(expected)
    assert len(default) == len(expected)


def test_agent_grid_catalog_tickers_cover_ct_and_monthly_annual() -> None:
    grid = set(kalshi_agent_grid_catalog_series_tickers())
    ct = set(kalshi_ct_default_series_tickers())
    assert ct <= grid
    monthly_annual = {
        t
        for k, tickers in KALSHI_CRYPTO_PRODUCTS.items()
        if k.endswith("_MONTHLY") or k.endswith("_ANNUAL")
        for t in tickers
    }
    assert monthly_annual <= grid


def test_ct_default_series_subset_of_kalshi_crypto_products() -> None:
    flat_all = [t for tickers in KALSHI_CRYPTO_PRODUCTS.values() for t in tickers]
    ct_set = set(kalshi_ct_default_series_tickers())
    assert ct_set <= set(flat_all)
    monthly_annual = {
        t
        for k, tickers in KALSHI_CRYPTO_PRODUCTS.items()
        if k.endswith("_MONTHLY") or k.endswith("_ANNUAL")
        for t in tickers
    }
    assert ct_set.isdisjoint(monthly_annual)


def test_kalshi_crypto_products_keys_parse_and_match_assets_and_suffix_allowlist() -> None:
    """Wiring drift: new product rows must use a known asset and tenor suffix."""
    for key in KALSHI_CRYPTO_PRODUCTS:
        asset, suffix = _parse_kalshi_crypto_product_key(key)
        assert asset in ALL_CRYPTO_ASSETS, f"Unknown asset in key {key!r}"
        assert suffix in KALSHI_CRYPTO_PRODUCT_VALUE_SUFFIXES, (
            f"Unknown tenor suffix {suffix!r} in key {key!r} — extend "
            f"KALSHI_CRYPTO_PRODUCT_VALUE_SUFFIXES and docs if intentional"
        )


def test_ct_default_tickers_are_expected_known_series() -> None:
    for t in kalshi_ct_default_series_tickers():
        assert t in EXPECTED_SERIES_TICKERS, f"{t} missing from KALSHI_CRYPTO_SERIES_TICKERS"
