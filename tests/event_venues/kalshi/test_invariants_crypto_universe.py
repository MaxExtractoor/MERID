"""Invariant tests for the canonical crypto universe.

Verifies that all modules that define or reference crypto assets/timeframes
use the canonical values from ``config.kalshi_crypto_config`` and that the
Discover health endpoint correctly reports coverage status.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from config.kalshi_crypto_config import (
    ACTIVE_CRYPTO_ASSETS,
    ACTIVE_CRYPTO_WS_TIMEFRAMES,
    ALL_CRYPTO_ASSETS,
)
from merid.event_venues.kalshi.crypto_catalog import (
    KalshiCryptoCatalog,
    build_kalshi_crypto_catalog_from_catalog_markets,
    collect_crypto_ws_subscription_tickers,
    kalshi_ticker_to_asset,
    summarize_crypto_ws_coverage,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_market(ticker: str, asset: str, timeframe: str) -> MagicMock:
    market = MagicMock()
    market.ticker = ticker
    market.status = "open"
    cm = MagicMock()
    cm.asset = asset
    cm.timeframe = timeframe
    cm.market = market
    cm.market.ticker = ticker
    cm.market.status = "open"
    return cm


def _full_universe() -> list:
    markets = []
    for asset in ACTIVE_CRYPTO_ASSETS:
        for tf in ACTIVE_CRYPTO_WS_TIMEFRAMES:
            ticker = f"KX{asset}-{tf.upper()}-T50000"
            markets.append(_make_market(ticker, asset, tf))
    return markets


# ── Canonical universe consistency ───────────────────────────────────────────


class TestCanonicalUniverseConsistency:
    """All asset/timeframe references should be rooted in config.kalshi_crypto_config."""

    def test_continuous_trader_uses_canonical_assets(self) -> None:
        from merid.trading.kalshi_continuous_trader import _CRYPTO_ASSETS
        assert set(_CRYPTO_ASSETS) == ALL_CRYPTO_ASSETS

    def test_continuous_trader_uses_canonical_timeframes(self) -> None:
        from merid.trading.kalshi_continuous_trader import _CRYPTO_TIMEFRAMES
        assert set(_CRYPTO_TIMEFRAMES) == set(ACTIVE_CRYPTO_WS_TIMEFRAMES)

    def test_kalshi_universe_alias_matches_active(self) -> None:
        from config.kalshi_universe import KALSHI_CRYPTO_ASSETS
        assert list(KALSHI_CRYPTO_ASSETS) == ACTIVE_CRYPTO_ASSETS

    def test_all_crypto_assets_is_frozenset_of_active(self) -> None:
        assert isinstance(ALL_CRYPTO_ASSETS, frozenset)
        assert ALL_CRYPTO_ASSETS == frozenset(ACTIVE_CRYPTO_ASSETS)


# ── Crypto catalog coverage ───────────────────────────────────────────────────


class TestCryptoCatalogCoverage:
    """With seeded fixture, catalog must show all five assets."""

    def test_all_five_assets_in_catalog(self) -> None:
        catalog = build_kalshi_crypto_catalog_from_catalog_markets(_full_universe())
        covered = set(catalog.assets_covered())
        assert covered == ALL_CRYPTO_ASSETS

    def test_ws_tickers_cover_all_five_assets(self) -> None:
        catalog = build_kalshi_crypto_catalog_from_catalog_markets(_full_universe())
        tickers = collect_crypto_ws_subscription_tickers(catalog)
        covered = {kalshi_ticker_to_asset(t) for t in tickers} - {None}
        assert covered == ALL_CRYPTO_ASSETS

    def test_ticker_asset_resolution_is_complete(self) -> None:
        """Every ticker returned by all_active_tickers() must resolve to a known asset."""
        catalog = build_kalshi_crypto_catalog_from_catalog_markets(_full_universe())
        for ticker in catalog.all_active_tickers():
            asset = kalshi_ticker_to_asset(ticker)
            assert asset is not None, f"{ticker!r} did not resolve to an asset"
            assert asset in ALL_CRYPTO_ASSETS

    def test_missing_asset_logged_as_missing(self) -> None:
        """When DOGE markets are absent, coverage must report DOGE as missing."""
        markets = [m for m in _full_universe() if m.asset != "DOGE"]
        catalog = build_kalshi_crypto_catalog_from_catalog_markets(markets)
        tickers = collect_crypto_ws_subscription_tickers(catalog)
        coverage = summarize_crypto_ws_coverage(tickers)
        assert coverage["coverage_complete"] is False
        assert "DOGE" in coverage["missing_assets"]

    def test_all_timeframes_present_in_grid(self) -> None:
        catalog = build_kalshi_crypto_catalog_from_catalog_markets(_full_universe())
        summary = catalog.grid_summary()
        for asset in ACTIVE_CRYPTO_ASSETS:
            row = summary[asset]
            for tf in ACTIVE_CRYPTO_WS_TIMEFRAMES:
                assert tf in row, f"{asset}/{tf} missing from grid summary"
                assert row[tf] >= 1, f"{asset}/{tf} has zero markets in seeded fixture"


# ── Discover-health endpoint ──────────────────────────────────────────────────


class TestDiscoverHealthEndpoint:
    """discover-health API integration tests."""

    @pytest.fixture(autouse=True)
    def _stub_missing_deps(self, monkeypatch):
        """Stub heavy optional dependencies so the test can import discover_health_api."""
        import sys
        import types

        # Only stub if dotenv is absent (local sandbox without full requirements)
        if "dotenv" not in sys.modules:
            monkeypatch.setitem(sys.modules, "dotenv", types.ModuleType("dotenv"))
            dotenv_mod = sys.modules["dotenv"]
            dotenv_mod.load_dotenv = lambda *a, **kw: None  # type: ignore[attr-defined]

    def _import_compute(self):
        """Import _compute_discover_health, bypassing web/api/__init__.py side-effects."""
        import importlib.util
        from pathlib import Path
        api_file = Path(__file__).parent.parent.parent.parent / "web" / "api" / "discover_health_api.py"
        spec = importlib.util.spec_from_file_location("discover_health_api_isolated", api_file)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_endpoint_imported_successfully(self) -> None:
        mod = self._import_compute()
        assert hasattr(mod, "router")

    def test_compute_discover_health_returns_all_assets(self) -> None:
        mod = self._import_compute()
        markets = _full_universe()
        result = mod._compute_discover_health(markets)
        assert set(result["assets"].keys()) == ALL_CRYPTO_ASSETS

    def test_compute_discover_health_marks_missing_asset(self) -> None:
        mod = self._import_compute()
        markets = [m for m in _full_universe() if m.asset != "XRP"]
        result = mod._compute_discover_health(markets)
        xrp = result["assets"]["XRP"]
        assert xrp["markets_discovered"] == 0
        assert xrp["ws_subscribed"] == 0

    def test_compute_discover_health_full_coverage(self) -> None:
        mod = self._import_compute()
        result = mod._compute_discover_health(_full_universe())
        for asset in ACTIVE_CRYPTO_ASSETS:
            row = result["assets"][asset]
            assert row["markets_discovered"] >= 1, f"{asset} has no markets discovered"
            assert row["ws_subscribed"] >= 1, f"{asset} has no ws_subscribed tickers"
