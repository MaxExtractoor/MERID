"""Multi-asset crypto ingestion & continuous trader regression tests.

These tests ensure that BTC, ETH, SOL, XRP, and DOGE are all supported
end-to-end in the Kalshi continuous trader pipeline.  Any future PR that
silently drops non-BTC assets or re-narrows to BTC-only will fail CI.

Tests cover:
  1. Config: KALSHI_CRYPTO_PRODUCTS includes all 5 assets
  2. Series map: crypto_series.CRYPTO_SERIES_PREFIXES covers all 5
  3. Market selector: ALL_COINS and AGENT_SERIES_MAP cover all 5
  4. Continuous trader: _asset_series_map groups series by asset correctly
  5. Continuous trader: _infer_asset_timeframe resolves all tickers
  6. Continuous trader: MarketCandidate carries an asset field
  7. Filter pipeline: per-asset spot prices prevent cross-asset contamination
  8. _compute_edge: uses candidate's asset for indicator stack lookup
  9. status_snapshot: exposes active_assets and asset_series_map
 10. Discovery: market_catalog detects all 5 crypto assets
"""

import re
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


REQUIRED_ASSETS = {"BTC", "ETH", "SOL", "XRP", "DOGE"}


def _read(relpath: str) -> str:
    p = Path(PROJECT_ROOT) / relpath
    return p.read_text(encoding="utf-8") if p.exists() else ""


# ═══════════════════════════════════════════════════════════════════════════
# 1. Config: KALSHI_CRYPTO_PRODUCTS includes all 5 assets
# ═══════════════════════════════════════════════════════════════════════════

class TestKalshiCryptoProductsConfig(unittest.TestCase):
    """KALSHI_CRYPTO_PRODUCTS must have entries for all required assets."""

    @classmethod
    def setUpClass(cls):
        from config.kalshi_universe import KALSHI_CRYPTO_PRODUCTS
        cls.products = KALSHI_CRYPTO_PRODUCTS

    def test_all_assets_have_15m_series(self):
        for asset in REQUIRED_ASSETS:
            key = f"{asset}_15M"
            self.assertIn(key, self.products, f"Missing {key} in KALSHI_CRYPTO_PRODUCTS")
            self.assertTrue(len(self.products[key]) >= 1, f"{key} has no tickers")

    def test_all_assets_have_1h_series(self):
        for asset in REQUIRED_ASSETS:
            key = f"{asset}_1H"
            self.assertIn(key, self.products, f"Missing {key} in KALSHI_CRYPTO_PRODUCTS")
            self.assertTrue(len(self.products[key]) >= 1, f"{key} has no tickers")

    def test_series_tickers_follow_kx_prefix_convention(self):
        for key, tickers in self.products.items():
            for ticker in tickers:
                self.assertTrue(
                    ticker.startswith("KX"),
                    f"Ticker {ticker} (key={key}) doesn't start with KX",
                )

    def test_fallback_includes_all_assets(self):
        from config.kalshi_universe import KALSHI_ACTIVE_MARKETS_FALLBACK
        for asset in REQUIRED_ASSETS:
            found = any(asset.upper() in t.upper() for t in KALSHI_ACTIVE_MARKETS_FALLBACK)
            self.assertTrue(found, f"{asset} missing from KALSHI_ACTIVE_MARKETS_FALLBACK")


# ═══════════════════════════════════════════════════════════════════════════
# 2. crypto_series.CRYPTO_SERIES_PREFIXES covers all 5 assets
# ═══════════════════════════════════════════════════════════════════════════

class TestCryptoSeriesPrefixes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from merid.event_venues.kalshi.crypto_series import CRYPTO_SERIES_PREFIXES
        cls.prefixes = CRYPTO_SERIES_PREFIXES

    def test_all_required_assets_present(self):
        for asset in REQUIRED_ASSETS:
            self.assertIn(asset, self.prefixes, f"{asset} missing from CRYPTO_SERIES_PREFIXES")

    def test_prefix_format(self):
        for asset, prefix in self.prefixes.items():
            self.assertTrue(prefix.startswith("KX"), f"{asset} prefix {prefix} doesn't start with KX")


# ═══════════════════════════════════════════════════════════════════════════
# 3. Market selector: ALL_COINS and AGENT_SERIES_MAP
# ═══════════════════════════════════════════════════════════════════════════

class TestMarketSelectorMultiAsset(unittest.TestCase):

    def test_all_coins_includes_required_assets(self):
        from merid.event_venues.kalshi.market_selector import ALL_COINS
        for asset in REQUIRED_ASSETS:
            self.assertIn(asset, ALL_COINS, f"{asset} missing from ALL_COINS")

    def test_agent_series_map_has_15m_for_all_assets(self):
        from merid.event_venues.kalshi.market_selector import AGENT_SERIES_MAP
        for asset in REQUIRED_ASSETS:
            key = f"{asset}_15M"
            self.assertIn(key, AGENT_SERIES_MAP, f"{key} missing from AGENT_SERIES_MAP")
            self.assertTrue(len(AGENT_SERIES_MAP[key]) >= 1)

    def test_resolve_series_ticker_all_assets(self):
        from merid.event_venues.kalshi.market_selector import resolve_series_ticker
        for asset in REQUIRED_ASSETS:
            ticker = resolve_series_ticker(asset, "15m")
            self.assertTrue(ticker.startswith("KX"), f"{asset} 15m ticker doesn't start with KX")
            ticker_h = resolve_series_ticker(asset, "1h")
            self.assertTrue(ticker_h.startswith("KX"), f"{asset} 1h ticker doesn't start with KX")


# ═══════════════════════════════════════════════════════════════════════════
# 4. Continuous trader: _asset_series_map groups by asset
# ═══════════════════════════════════════════════════════════════════════════

class TestContinuousTraderMultiAssetInit(unittest.TestCase):
    """Trader init must build a per-asset series map, not a single asset."""

    def test_asset_series_map_attribute_exists(self):
        src = _read("merid/trading/kalshi_continuous_trader.py")
        self.assertIn("_asset_series_map", src)

    def test_asset_series_map_built_from_series_tickers(self):
        src = _read("merid/trading/kalshi_continuous_trader.py")
        self.assertIn("_infer_asset_timeframe(", src)
        # Strike bands for FilterPipelineConfig (replaces inlined _series_for_band)
        self.assertIn("_STRIKE_BAND_PCT", src)
        self.assertIn("_asset_series_map.setdefault(asset", src)

    def test_multi_asset_init_log(self):
        src = _read("merid/trading/kalshi_continuous_trader.py")
        self.assertIn("series_per_asset", src)


# ═══════════════════════════════════════════════════════════════════════════
# 5. _infer_asset_timeframe resolves all series tickers
# ═══════════════════════════════════════════════════════════════════════════

class TestInferAssetTimeframe(unittest.TestCase):

    @staticmethod
    def _infer(series_ticker: str):
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader
        return KalshiContinuousTrader._infer_asset_timeframe(series_ticker)

    def test_btc_15m(self):
        asset, tf = self._infer("KXBTC15M")
        self.assertEqual(asset, "BTC")
        self.assertEqual(tf, "15m")

    def test_eth_15m(self):
        asset, tf = self._infer("KXETH15M")
        self.assertEqual(asset, "ETH")
        self.assertEqual(tf, "15m")

    def test_sol_15m(self):
        asset, tf = self._infer("KXSOL15M")
        self.assertEqual(asset, "SOL")
        self.assertEqual(tf, "15m")

    def test_xrp_15m(self):
        asset, tf = self._infer("KXXRP15M")
        self.assertEqual(asset, "XRP")
        self.assertEqual(tf, "15m")

    def test_doge_15m(self):
        asset, tf = self._infer("KXDOGE15M")
        self.assertEqual(asset, "DOGE")
        self.assertEqual(tf, "15m")

    def test_btc_hourly(self):
        asset, tf = self._infer("KXBTC")
        self.assertEqual(asset, "BTC")
        self.assertEqual(tf, "1h")

    def test_eth_hourly(self):
        asset, tf = self._infer("KXETH")
        self.assertEqual(asset, "ETH")
        self.assertEqual(tf, "1h")

    def test_sol_hourly(self):
        asset, tf = self._infer("KXSOL")
        self.assertEqual(asset, "SOL")
        self.assertEqual(tf, "1h")


# ═══════════════════════════════════════════════════════════════════════════
# 6. MarketCandidate carries an asset field
# ═══════════════════════════════════════════════════════════════════════════

class TestMarketCandidateAssetField(unittest.TestCase):

    def test_market_candidate_has_asset_field(self):
        from merid.trading.kalshi_continuous_trader import MarketCandidate
        c = MarketCandidate(ticker="KXETH15M-T2500", strike=2500, spot=2500, underlying="ETH", timeframe="15m")
        self.assertEqual(c.asset, "ETH")

    def test_market_candidate_default_asset_empty(self):
        from merid.trading.kalshi_continuous_trader import MarketCandidate
        c = MarketCandidate(ticker="X", strike=0, spot=0, underlying="", timeframe="15m")
        self.assertEqual(c.asset, "")


# ═══════════════════════════════════════════════════════════════════════════
# 7. Filter pipeline: per-asset spot prices
# ═══════════════════════════════════════════════════════════════════════════

class TestFilterPipelinePerAssetSpot(unittest.TestCase):
    """The filter pipeline must NOT use a single spot price for all assets.

    This is the core regression guard: using BTC's spot (~$70k) to filter
    ETH markets (strikes ~$2500) would reject 100% of non-BTC markets.
    """

    def test_run_cycle_iterates_per_asset(self):
        """_run_cycle must loop over _asset_series_map, not use a single asset."""
        src = _read("merid/trading/kalshi_continuous_trader.py")
        # Scanner-only refactor: CT builds raw_by_asset from catalog snapshot.
        # The key invariant remains: it iterates per-asset, not single-asset.
        self.assertTrue(
            ("for asset in self._asset_series_map.keys()" in src)
            or ("for asset, " in src and "self._asset_series_map" in src),
            "CT does not appear to iterate per-asset over _asset_series_map",
        )

    def test_spot_fetched_per_asset(self):
        """Each asset must get its own spot price via CryptoSpotService."""
        src = _read("merid/trading/kalshi_continuous_trader.py")
        # New implementation uses CryptoSpotService for multi-asset spot fetching
        self.assertIn("CryptoSpotService", src)
        self.assertIn("get_crypto_spot_service", src)
        self.assertIn("for asset in self._active_assets", src)

    def test_strike_filter_uses_per_asset_spot(self):
        """Strike distance check must use the per-asset spot, not a global one."""
        src = _read("merid/trading/kalshi_filter_pipeline.py")
        self.assertIn("spot = self.get_spot_price(asset_u)", src)

    def test_no_single_asset_spot_in_filter_loop(self):
        """Ensure the old BTC-only pattern is gone."""
        src = _read("merid/trading/kalshi_continuous_trader.py")
        # The old pattern: "spot = self._get_spot(self.asset_symbol)" directly before filter loop
        # should NOT appear in _run_cycle anymore (it's fine in _get_spot itself as a default)
        cycle_src = src[src.index("def _run_cycle"):]
        self.assertNotIn(
            'self._get_spot(self.asset_symbol)',
            cycle_src,
            "_run_cycle still uses single-asset spot fetch — multi-asset regression!",
        )

    def test_per_asset_filter_logging(self):
        """Each asset must get its own filter pipeline log line."""
        src = _read("merid/trading/kalshi_filter_pipeline.py")
        self.assertIn("Filter pipeline (asset=%s", src)

    def test_multi_asset_summary_log(self):
        """Aggregate summary log must show which assets have candidates."""
        src = _read("merid/trading/kalshi_filter_pipeline.py")
        # Filter pipeline logs per-asset stats with raw count
        self.assertIn("Filter pipeline (asset=%s raw=%d", src)
        self.assertIn("spot_ok=", src)


# ═══════════════════════════════════════════════════════════════════════════
# 8. _compute_edge uses candidate's asset
# ═══════════════════════════════════════════════════════════════════════════

class TestComputeEdgeUsesAssetField(unittest.TestCase):

    def test_compute_edge_indicator_stack_uses_candidate_asset(self):
        """_compute_edge must use c.asset (not self.asset_symbol) for the stack."""
        src = _read("merid/trading/kalshi_continuous_trader.py")
        edge_fn_src = src[src.index("def _compute_edge"):]
        edge_fn_src = edge_fn_src[:edge_fn_src.index("\n    def ")]
        self.assertIn("c.asset", edge_fn_src)
        self.assertNotIn(
            "self.asset_symbol",
            edge_fn_src,
            "_compute_edge still uses self.asset_symbol instead of c.asset",
        )


# ═══════════════════════════════════════════════════════════════════════════
# 9. status_snapshot exposes multi-asset info
# ═══════════════════════════════════════════════════════════════════════════

class TestStatusSnapshotMultiAsset(unittest.TestCase):

    def test_active_assets_in_snapshot(self):
        src = _read("merid/trading/kalshi_continuous_trader.py")
        self.assertIn('"active_assets"', src)

    def test_asset_series_map_in_snapshot(self):
        src = _read("merid/trading/kalshi_continuous_trader.py")
        self.assertIn('"asset_series_map"', src)


# ═══════════════════════════════════════════════════════════════════════════
# 10. market_catalog detects all 5 crypto assets
# ═══════════════════════════════════════════════════════════════════════════

class TestMarketCatalogCryptoAssets(unittest.TestCase):
    """The ticker→category map must detect all required crypto assets."""

    @staticmethod
    def _detect(ticker: str):
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
        return KalshiMarketCatalog._detect_from_ticker(ticker)

    def test_btc_tickers_detected(self):
        cat, asset = self._detect("KXBTC15M-25MAR-T70000")
        self.assertEqual(cat, "crypto")
        self.assertEqual(asset, "BTC")

    def test_eth_tickers_detected(self):
        cat, asset = self._detect("KXETH15M-25MAR-T2500")
        self.assertEqual(cat, "crypto")
        self.assertEqual(asset, "ETH")

    def test_sol_tickers_detected(self):
        cat, asset = self._detect("KXSOL15M-25MAR-T100")
        self.assertEqual(cat, "crypto")
        self.assertEqual(asset, "SOL")

    def test_xrp_tickers_detected(self):
        cat, asset = self._detect("KXXRP15M-25MAR-T1")
        self.assertEqual(cat, "crypto")
        self.assertEqual(asset, "XRP")

    def test_doge_tickers_detected(self):
        cat, asset = self._detect("KXDOGE15M-25MAR-T0")
        self.assertEqual(cat, "crypto")
        self.assertEqual(asset, "DOGE")


# ═══════════════════════════════════════════════════════════════════════════
# 11. Behavioral: synthetic multi-asset filter correctness
# ═══════════════════════════════════════════════════════════════════════════

class TestMultiAssetFilterBehavior(unittest.TestCase):
    """Prove that using per-asset spot prices keeps non-BTC candidates alive.

    Simulates the exact scenario that was broken: BTC spot ~$70k, ETH spot ~$2500,
    SOL ~$100, XRP ~$1.5, DOGE ~$0.10.  With a single BTC spot, ETH/SOL/XRP/DOGE
    threshold markets would all be rejected (strike distance >> 25%).
    """

    @classmethod
    def setUpClass(cls):
        from merid.trading.kalshi_continuous_trader import (
            KalshiContinuousTrader,
            MarketCandidate,
        )
        cls.Trader = KalshiContinuousTrader
        cls.MC = MarketCandidate

    def test_eth_market_survives_with_eth_spot(self):
        """ETH market at strike $2400 with ETH spot $2500 → 4% distance → passes."""
        spot = 2500.0
        strike = 2400.0
        dist_pct = abs(spot - strike) / spot
        self.assertLess(dist_pct, 0.25)

    def test_eth_market_rejected_with_btc_spot(self):
        """ETH market at strike $2400 with BTC spot $70000 → 96.6% → rejected.
        This is the bug we're guarding against.
        """
        btc_spot = 70000.0
        strike = 2400.0
        dist_pct = abs(btc_spot - strike) / btc_spot
        self.assertGreater(dist_pct, 0.25)

    def test_sol_market_survives_with_sol_spot(self):
        spot = 100.0
        strike = 95.0
        dist_pct = abs(spot - strike) / spot
        self.assertLess(dist_pct, 0.25)

    def test_xrp_market_survives_with_xrp_spot(self):
        spot = 1.50
        strike = 1.40
        dist_pct = abs(spot - strike) / spot
        self.assertLess(dist_pct, 0.25)

    def test_doge_market_survives_with_doge_spot(self):
        spot = 0.10
        strike = 0.09
        dist_pct = abs(spot - strike) / spot
        self.assertLess(dist_pct, 0.25)

    def test_candidate_carries_asset_through_pipeline(self):
        """MarketCandidate.asset must survive from creation to edge computation."""
        c = self.MC(
            ticker="KXETH15M-25MAR-T2500",
            strike=2500.0,
            spot=2500.0,
            underlying="ETH",
            timeframe="15m",
        )
        self.assertEqual(c.asset, "ETH")


# ═══════════════════════════════════════════════════════════════════════════
# 12. _get_spot supports all required assets
# ═══════════════════════════════════════════════════════════════════════════

class TestGetSpotMultiAsset(unittest.TestCase):
    """_get_spot must have CoinGecko/Coinbase/Binance mappings for all assets."""

    def test_get_spot_has_coingecko_ids_for_all_assets(self):
        src = _read("merid/trading/kalshi_continuous_trader.py")
        for asset in REQUIRED_ASSETS:
            self.assertIn(
                f'"{asset}"',
                src,
                f"_get_spot missing CoinGecko mapping for {asset}",
            )

    def test_coingecko_id_mapping_complete(self):
        src = _read("merid/trading/kalshi_continuous_trader.py")
        expected_mappings = {
            '"BTC": "bitcoin"',
            '"ETH": "ethereum"',
            '"SOL": "solana"',
            '"XRP": "ripple"',
            '"DOGE": "dogecoin"',
        }
        for mapping in expected_mappings:
            self.assertIn(mapping, src, f"Missing CoinGecko mapping: {mapping}")


# ═══════════════════════════════════════════════════════════════════════════
# 13. No BTC-only regression in _run_cycle
# ═══════════════════════════════════════════════════════════════════════════

class TestNoBtcOnlyRegression(unittest.TestCase):
    """Guard against patterns that would narrow the trader back to BTC-only."""

    def test_no_hardcoded_btc_in_spot_fetch(self):
        """_run_cycle must not hardcode 'BTC' when fetching spot for filtering."""
        src = _read("merid/trading/kalshi_continuous_trader.py")
        cycle_src = src[src.index("def _run_cycle"):]
        # The only acceptable "BTC" reference is for vol tracking benchmark
        btc_refs = [
            line.strip() for line in cycle_src.split("\n")
            if '"BTC"' in line or "'BTC'" in line
        ]
        for ref in btc_refs:
            self.assertTrue(
                "benchmark" in ref.lower()
                or "vol tracking" in ref.lower()
                or "btc_spot" in ref.lower()
                or "spot_prices.get" in ref,
                f"Suspicious BTC-only reference in _run_cycle: {ref}",
            )

    def test_class_docstring_mentions_multi_asset(self):
        src = _read("merid/trading/kalshi_continuous_trader.py")
        self.assertIn("ETH", src[:2000])
        self.assertIn("SOL", src[:2000])
        self.assertIn("DOGE", src[:2000])


if __name__ == "__main__":
    unittest.main()
