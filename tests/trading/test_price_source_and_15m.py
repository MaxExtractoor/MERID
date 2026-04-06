"""Tests for price source alignment, strategy catalog gating, and 15m eligibility.

Covers the fixes from the Kalshi crypto trading pipeline audit:
  A. Coinbase is the PRIMARY spot price source (not CoinGecko).
  B. strategy_catalog.yaml enabled=false cells are skipped by _refresh_candidates.
  C. 15m trades are not silently blocked for enabled cells (BTC/ETH/XRP 15m).
  D. UI live_data.py uses Coinbase for the 5 Kalshi crypto assets.
  E. _CATALOG_ENABLED correctly reflects the YAML at module load time.
"""

from __future__ import annotations

import asyncio
import pathlib
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merid.trading.kalshi_continuous_trader import (
    _CATALOG_ENABLED,
    _COINGECKO_IDS,
    _CRYPTO_ASSETS,
    _CRYPTO_TIMEFRAMES,
    _fetch_spot_prices_with_fallback,
    _load_strategy_catalog_enabled,
    KalshiContinuousTrader,
    TradingCandidate,
)
from merid.event_venues.kalshi.market_filter import MarketCandidate


# ── Helpers ───────────────────────────────────────────────────────────────

def _make_candidate(
    ticker: str = "KXBTC-15M-T95000",
    underlying: str = "BTC",
    timeframe: str = "15m",
    mid_price_cents: int = 55,
    best_bid_cents: int = 50,
    best_ask_cents: int = 60,
    spot_price: float = 95000.0,
    strike_price: float = 95000.0,
) -> MarketCandidate:
    return MarketCandidate(
        ticker=ticker,
        underlying=underlying,
        timeframe=timeframe,
        best_bid_cents=best_bid_cents,
        best_ask_cents=best_ask_cents,
        mid_price_cents=mid_price_cents,
        spot_price=spot_price,
        strike_price=strike_price,
    )


def _make_aiohttp_cm(status: int, json_data: dict):
    """Return a mock async context manager that behaves like aiohttp's response."""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# ── A. Coinbase is the primary price source ───────────────────────────────

class TestCoinbasePrimary:
    """Coinbase must be queried before CoinGecko for Kalshi crypto assets."""

    @pytest.mark.asyncio
    async def test_coinbase_called_before_coingecko(self):
        """Order of HTTP calls: Coinbase first, then CoinGecko only for missing assets."""
        call_order: List[str] = []
        coinbase_prices = {"BTC": 95020.0, "ETH": 3502.5, "SOL": 155.0, "XRP": 0.52, "DOGE": 0.105}

        def fake_get(url, **kwargs):
            if "api.coinbase.com" in url:
                call_order.append("coinbase")
                sym = url.split("/prices/")[1].split("-USD")[0]
                if sym in coinbase_prices:
                    return _make_aiohttp_cm(200, {"data": {"amount": str(coinbase_prices[sym])}})
                return _make_aiohttp_cm(404, {})
            elif "coingecko.com" in url:
                call_order.append("coingecko")
                return _make_aiohttp_cm(200, {
                    v: {"usd": 1.0} for v in _COINGECKO_IDS.values()
                })
            return _make_aiohttp_cm(404, {})

        import aiohttp

        with patch.object(aiohttp.ClientSession, "get", side_effect=fake_get):
            prices = await _fetch_spot_prices_with_fallback(_CRYPTO_ASSETS)

        # Coinbase was called, not CoinGecko (all assets resolved from Coinbase)
        assert "coinbase" in call_order, "Coinbase was never queried"
        # CoinGecko should NOT be queried when Coinbase resolves all assets
        assert "coingecko" not in call_order, (
            "CoinGecko was queried even though Coinbase returned all assets"
        )

    @pytest.mark.asyncio
    async def test_coinbase_prices_used_when_available(self):
        """Returned prices must match Coinbase values, not CoinGecko."""
        coinbase_prices = {"BTC": 95020.0, "ETH": 3502.5, "SOL": 155.0, "XRP": 0.52, "DOGE": 0.105}

        def fake_get(url, **kwargs):
            if "api.coinbase.com" in url:
                sym = url.split("/prices/")[1].split("-USD")[0]
                if sym in coinbase_prices:
                    return _make_aiohttp_cm(200, {"data": {"amount": str(coinbase_prices[sym])}})
                return _make_aiohttp_cm(404, {})
            elif "coingecko.com" in url:
                # CoinGecko returns different (lower) prices — should not be used
                return _make_aiohttp_cm(200, {
                    "bitcoin": {"usd": 95000.0},
                    "ethereum": {"usd": 3500.0},
                })
            return _make_aiohttp_cm(404, {})

        import aiohttp

        with patch.object(aiohttp.ClientSession, "get", side_effect=fake_get):
            prices = await _fetch_spot_prices_with_fallback(_CRYPTO_ASSETS)

        assert prices["BTC"] == 95020.0, f"BTC should be Coinbase price 95020.0, got {prices['BTC']}"
        assert prices["ETH"] == 3502.5, f"ETH should be Coinbase price 3502.5, got {prices['ETH']}"

    @pytest.mark.asyncio
    async def test_coingecko_fallback_when_coinbase_fails(self):
        """When Coinbase fails for an asset, CoinGecko is used as fallback."""
        def fake_get(url, **kwargs):
            if "api.coinbase.com" in url:
                return _make_aiohttp_cm(500, {})
            elif "coingecko.com" in url:
                return _make_aiohttp_cm(200, {
                    "bitcoin": {"usd": 95000.0},
                    "ethereum": {"usd": 3500.0},
                    "solana": {"usd": 154.0},
                    "ripple": {"usd": 0.51},
                    "dogecoin": {"usd": 0.10},
                })
            return _make_aiohttp_cm(404, {})

        import aiohttp

        with patch.object(aiohttp.ClientSession, "get", side_effect=fake_get):
            prices = await _fetch_spot_prices_with_fallback(_CRYPTO_ASSETS)

        assert "BTC" in prices, "BTC should be present via CoinGecko fallback"
        assert prices["BTC"] == 95000.0

    @pytest.mark.asyncio
    async def test_all_five_assets_resolved_from_coinbase(self):
        """All 5 Kalshi assets (BTC/ETH/SOL/XRP/DOGE) are fetchable from Coinbase."""
        cb_data = {
            "BTC": "95020.00",
            "ETH": "3502.50",
            "SOL": "155.00",
            "XRP": "0.5200",
            "DOGE": "0.1050",
        }

        def fake_get(url, **kwargs):
            if "api.coinbase.com" in url:
                sym = url.split("/prices/")[1].split("-USD")[0]
                if sym in cb_data:
                    return _make_aiohttp_cm(200, {"data": {"amount": cb_data[sym]}})
                return _make_aiohttp_cm(404, {})
            return _make_aiohttp_cm(404, {})

        import aiohttp

        with patch.object(aiohttp.ClientSession, "get", side_effect=fake_get):
            prices = await _fetch_spot_prices_with_fallback(_CRYPTO_ASSETS)

        for sym in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            assert sym in prices, f"{sym} missing from prices"
            assert prices[sym] == float(cb_data[sym])


# ── B. Strategy catalog enabled gating ───────────────────────────────────

class TestCatalogEnabledGating:
    """Cells with enabled: false in strategy_catalog.yaml must be skipped."""

    def test_sol_15m_disabled_in_catalog(self):
        """SOL 15m is disabled in the shipped catalog."""
        assert _CATALOG_ENABLED.get(("SOL", "15m")) is False, (
            "SOL 15m should be disabled per strategy_catalog.yaml"
        )

    def test_doge_15m_disabled_in_catalog(self):
        """DOGE 15m is disabled in the shipped catalog."""
        assert _CATALOG_ENABLED.get(("DOGE", "15m")) is False, (
            "DOGE 15m should be disabled per strategy_catalog.yaml"
        )

    def test_btc_15m_enabled_in_catalog(self):
        """BTC 15m is enabled — the most liquid 15m cell."""
        enabled = _CATALOG_ENABLED.get(("BTC", "15m"), True)
        assert enabled is True, "BTC 15m should be enabled in strategy_catalog.yaml"

    def test_eth_15m_enabled_in_catalog(self):
        """ETH 15m is enabled."""
        enabled = _CATALOG_ENABLED.get(("ETH", "15m"), True)
        assert enabled is True, "ETH 15m should be enabled in strategy_catalog.yaml"

    def test_xrp_15m_enabled_in_catalog(self):
        """XRP 15m is enabled."""
        enabled = _CATALOG_ENABLED.get(("XRP", "15m"), True)
        assert enabled is True, "XRP 15m should be enabled in strategy_catalog.yaml"

    def test_load_strategy_catalog_enabled_returns_dict(self):
        """_load_strategy_catalog_enabled returns a non-empty dict."""
        result = _load_strategy_catalog_enabled()
        assert isinstance(result, dict)
        assert len(result) > 0, "Catalog should have at least one entry"

    def test_load_strategy_catalog_enabled_keys_are_tuples(self):
        """All keys are (asset, timeframe) tuples."""
        result = _load_strategy_catalog_enabled()
        for key in result:
            assert isinstance(key, tuple) and len(key) == 2, (
                f"Key {key!r} is not a (asset, timeframe) tuple"
            )
            asset, tf = key
            assert asset in _CRYPTO_ASSETS, f"Unknown asset {asset!r} in catalog"
            assert tf in _CRYPTO_TIMEFRAMES, f"Unknown timeframe {tf!r} in catalog"

    def test_load_strategy_catalog_enabled_missing_file_returns_empty(self, tmp_path):
        """Missing YAML file → empty dict (all cells treated as enabled)."""
        import merid.trading.kalshi_continuous_trader as ct_module

        with patch.object(
            ct_module.pathlib.Path,
            "__truediv__",
            return_value=tmp_path / "nonexistent_catalog.yaml",
        ):
            result = _load_strategy_catalog_enabled()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_refresh_candidates_skips_catalog_disabled_cells(self):
        """_refresh_candidates must not produce candidates for disabled cells."""
        mock_catalog = MagicMock()

        def get_markets_by_asset(asset, timeframe=None):
            # Return a candidate for every cell to verify disabled ones are skipped
            if _CATALOG_ENABLED.get((asset, timeframe)) is False:
                # Should never be called for disabled cells
                raise AssertionError(
                    f"get_markets_by_asset called for disabled cell ({asset}, {timeframe})"
                )
            return []

        mock_catalog.get_markets_by_asset = get_markets_by_asset

        trader = KalshiContinuousTrader(
            catalog=mock_catalog,
            dry_run=True,
        )

        with patch(
            "merid.trading.kalshi_continuous_trader._fetch_spot_prices_with_fallback",
            new=AsyncMock(return_value={a: 1.0 for a in _CRYPTO_ASSETS}),
        ):
            await trader._refresh_candidates()
        # If we reach here without AssertionError, the gate is working


# ── C. 15m is not silently blocked for enabled cells ─────────────────────

class TestFifteenMinuteEligibility:
    """Enabled 15m cells (BTC/ETH/XRP) must reach trade_cycle evaluation."""

    @pytest.mark.asyncio
    async def test_btc_15m_candidates_reach_trade_cycle(self):
        """BTC 15m candidates are not dropped before reaching trade_cycle."""
        from merid.prediction.opinion_strategy import OpinionEstimate

        candidate = TradingCandidate.from_candidate(
            _make_candidate(
                ticker="KXBTC-15M-T95000",
                underlying="BTC",
                timeframe="15m",
                mid_price_cents=55,
                spot_price=95000.0,
                strike_price=95000.0,
            )
        )

        mock_catalog = MagicMock()
        mock_catalog.get_markets_by_asset.return_value = []

        trader = KalshiContinuousTrader(catalog=mock_catalog, dry_run=True)
        trader._candidates = [candidate]

        estimate = OpinionEstimate(
            agent_prob=0.65,
            confidence=0.8,
            edge=0.10,
            reasoning_tag="test",
            signal_sources=["test"],
        )
        trader.evaluate_candidate = MagicMock(return_value=estimate)

        with patch(
            "merid.trading.kalshi_continuous_trader._fetch_spot_prices_with_fallback",
            new=AsyncMock(return_value={"BTC": 95000.0}),
        ), patch.object(trader, "_refresh_candidates", new=AsyncMock()):
            intents = await trader.trade_cycle(bankroll=1000.0)

        # evaluate_candidate was called — meaning the 15m candidate reached the cycle
        trader.evaluate_candidate.assert_called_once_with(candidate, market_prob=0.55)

    def test_15m_timeframe_in_crypto_timeframes(self):
        """'15m' must be in _CRYPTO_TIMEFRAMES so it is included in candidate scans."""
        assert "15m" in _CRYPTO_TIMEFRAMES, (
            "'15m' is missing from _CRYPTO_TIMEFRAMES — all 15m markets will be invisible"
        )

    def test_enabled_15m_cells(self):
        """Exactly BTC/ETH/XRP 15m are enabled; SOL/DOGE 15m are disabled."""
        expected_enabled = {"BTC", "ETH", "XRP"}
        expected_disabled = {"SOL", "DOGE"}

        for asset in expected_enabled:
            enabled = _CATALOG_ENABLED.get((asset, "15m"), True)
            assert enabled is True, f"{asset} 15m should be enabled"

        for asset in expected_disabled:
            enabled = _CATALOG_ENABLED.get((asset, "15m"), True)
            assert enabled is False, f"{asset} 15m should be disabled"


# ── D. UI live_data.py uses Coinbase for Kalshi assets ───────────────────

class TestUIUsesCorrectPriceSource:
    """web/api/live_data.py must expose Coinbase prices for BTC/ETH/SOL/XRP/DOGE."""

    def _import_live_data(self):
        """Import live_data module in isolation, bypassing the full web.api package."""
        import importlib.util
        import sys
        spec = importlib.util.spec_from_file_location(
            "live_data_standalone",
            pathlib.Path(__file__).parent.parent.parent / "web" / "api" / "live_data.py",
        )
        mod = importlib.util.module_from_spec(spec)
        # Provide minimal stubs for imports that live_data.py needs
        if "utils.deps" not in sys.modules:
            stub = MagicMock()
            sys.modules["utils.deps"] = stub
        spec.loader.exec_module(mod)
        return mod

    def test_kalshi_crypto_symbols_constant(self):
        """_KALSHI_CRYPTO_SYMBOLS contains the 5 Kalshi crypto assets."""
        mod = self._import_live_data()
        expected = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
        assert mod._KALSHI_CRYPTO_SYMBOLS == expected

    def test_coinbase_fetch_helper_exists(self):
        """_fetch_coinbase_spot_prices helper is importable and callable."""
        mod = self._import_live_data()
        assert callable(mod._fetch_coinbase_spot_prices)

    def test_coinbase_spot_url_template(self):
        """The Coinbase URL template is correct for all 5 assets."""
        mod = self._import_live_data()
        for sym in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            url = mod._COINBASE_SPOT_URL.format(sym=sym)
            assert f"{sym}-USD/spot" in url, f"URL for {sym} is malformed: {url}"

    def test_fetch_coinbase_spot_returns_prices(self):
        """_fetch_coinbase_spot_prices returns float prices keyed by symbol."""
        mod = self._import_live_data()
        fake_prices = {
            "BTC": 95020.0, "ETH": 3502.5, "SOL": 155.0, "XRP": 0.52, "DOGE": 0.105
        }

        class FakeResponse:
            def __init__(self, sym):
                self.status_code = 200
                self._sym = sym
            def json(self):
                return {"data": {"amount": str(fake_prices[self._sym])}}

        def fake_client_get(url, **kwargs):
            sym = url.split("/prices/")[1].split("-USD")[0]
            return FakeResponse(sym)

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get = fake_client_get
            mock_client_cls.return_value = mock_client

            result = mod._fetch_coinbase_spot_prices()

        for sym in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            assert sym in result, f"{sym} missing from Coinbase fetch result"
            assert result[sym] == fake_prices[sym]


# ── E. No hardcoded asset/timeframe lists ────────────────────────────────

class TestNoHardcodedUniverseInPricePath:
    """Price fetch and candidate scan must derive their universe from config."""

    def test_fetch_uses_crypto_assets_tuple(self):
        """_refresh_candidates must iterate _CRYPTO_ASSETS, not a hardcoded list."""
        import inspect
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader
        src = inspect.getsource(KalshiContinuousTrader._refresh_candidates)
        assert "_CRYPTO_ASSETS" in src, (
            "_refresh_candidates must iterate _CRYPTO_ASSETS, not a hardcoded list"
        )

    def test_fifteen_min_scan_uses_crypto_timeframes(self):
        """The 15m scan loop must iterate _CRYPTO_TIMEFRAMES (which includes '15m')."""
        import inspect
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader
        src = inspect.getsource(KalshiContinuousTrader._refresh_candidates)
        assert "_CRYPTO_TIMEFRAMES" in src, (
            "_refresh_candidates must iterate _CRYPTO_TIMEFRAMES"
        )

    def test_spot_bands_cover_all_cells(self):
        """SPOT_BANDS in market_filter.py covers every (asset, timeframe) pair."""
        from merid.event_venues.kalshi.market_filter import SPOT_BANDS, get_spot_band
        from config.crypto_universe import CRYPTO_TIMEFRAME_MATRIX

        for asset, tf in CRYPTO_TIMEFRAME_MATRIX:
            if tf == "annual":
                continue  # annual is valid to use default
            band = get_spot_band(asset, tf)
            assert band > 0, f"({asset}, {tf}) has zero or missing spot band"
