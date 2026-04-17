"""Sprint H invariant tests.

Covers:
  H1 – SignalCalibrator: Brier tracking, adaptive weights, persist/load
  H2 – CoinGeckoContextSnapshot: alt_season, market flags, edge features
  H3 – context-health endpoint structure
  H4 – EdgeModel Signal 9: CoinGecko market expanding/contracting/alt-season
"""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── Stub heavy dependencies to prevent ~49-second Neo4j/Redis cold start ──────
# utils.logger → neo4j_graph / agents.framework / core.cache on every fresh
# Python process.  Replace get_logger with stdlib before any merid import.
import logging as _logging
if "utils.logger" not in sys.modules:
    _ul = types.ModuleType("utils.logger")
    _ul.get_logger = _logging.getLogger  # type: ignore[attr-defined]
    sys.modules["utils.logger"] = _ul

# Bypass merid.prediction.__init__.py (eagerly imports consensus/debate/agents).
if "merid.prediction" not in sys.modules:
    _pkg = types.ModuleType("merid.prediction")
    _pkg.__path__ = [str(ROOT / "merid" / "prediction")]  # type: ignore[attr-defined]
    _pkg.__package__ = "merid.prediction"
    sys.modules["merid.prediction"] = _pkg


# ──────────────────────────────────────────────────────────────────────────────
# H1 – Signal Calibrator
# ──────────────────────────────────────────────────────────────────────────────

class TestSignalCalibrator(unittest.TestCase):

    def _fresh(self):
        from merid.prediction.signal_calibrator import SignalCalibrator
        return SignalCalibrator()

    def test_default_weight_is_neutral(self):
        cal = self._fresh()
        w = cal.weight("polygon_regime")
        self.assertAlmostEqual(w, 1.0, places=1)

    def test_perfect_signal_gets_high_weight(self):
        cal = self._fresh()
        # Record 15 perfect predictions (predicted=outcome every time)
        for _ in range(15):
            cal.record("polygon_regime", 1.0, 1)
        w = cal.weight("polygon_regime")
        # brier=0 → raw_weight=1.0 → should be at or above neutral
        self.assertGreaterEqual(w, 1.0)

    def test_random_signal_gets_low_weight(self):
        cal = self._fresh()
        # Brier=0.25 (random) → raw_weight=0 → weight near 0
        for i in range(20):
            # Always predict 0.5 for outcome that alternates: brier = (0.5)^2 = 0.25
            cal.record("macro_vix", 0.5, i % 2)
        # Another signal is still neutral (raw=1.0)
        # macro_vix raw = max(0, 1 - 0.25/0.25) = 0 → normalised weight should be low
        w = cal.weight("macro_vix")
        self.assertLessEqual(w, 1.0)

    def test_stats_returns_all_signal_names(self):
        from merid.prediction.signal_calibrator import SIGNAL_NAMES
        cal = self._fresh()
        stats = cal.stats()
        for name in SIGNAL_NAMES:
            self.assertIn(name, stats)

    def test_stats_contains_required_keys(self):
        cal = self._fresh()
        cal.record("fg_contrarian", 0.7, 1)
        stats = cal.stats()
        s = stats["fg_contrarian"]
        for key in ("observations", "brier_score", "adaptive_weight", "raw_weight"):
            self.assertIn(key, s)

    def test_brier_score_correct(self):
        cal = self._fresh()
        # predict 0.8, outcome 1 → brier = (0.8-1)^2 = 0.04
        # predict 0.2, outcome 0 → brier = (0.2-0)^2 = 0.04
        # mean = 0.04
        for _ in range(5):
            cal.record("perp_funding", 0.8, 1)
            cal.record("perp_funding", 0.2, 0)
        stat = cal._stats["perp_funding"]
        self.assertAlmostEqual(stat.brier_score, 0.04, places=3)

    def test_record_clamps_probability(self):
        cal = self._fresh()
        cal.record("macro_cpi", 1.5, 1)   # clamp to 1.0
        cal.record("macro_cpi", -0.5, 0)  # clamp to 0.0
        # Should not raise
        stat = cal._stats["macro_cpi"]
        self.assertEqual(stat.observations, 2)

    def test_unknown_signal_records_and_returns_weight(self):
        cal = self._fresh()
        cal.record("custom_signal", 0.6, 1)
        w = cal.weight("custom_signal")
        self.assertGreater(w, 0)

    def test_persist_and_load(self):
        import tempfile, json
        from merid.prediction.signal_calibrator import SignalCalibrator
        import merid.prediction.signal_calibrator as scm
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp = Path(f.name)
        orig_path = scm.PERSIST_PATH
        scm.PERSIST_PATH = tmp
        try:
            cal = SignalCalibrator()
            for _ in range(15):
                cal.record("messari_momentum", 0.9, 1)
            cal.persist()
            cal2 = SignalCalibrator()
            # loaded stats should have observations
            self.assertGreater(cal2._stats["messari_momentum"].observations, 0)
        finally:
            scm.PERSIST_PATH = orig_path
            tmp.unlink(missing_ok=True)

    def test_weights_returns_all_signals(self):
        from merid.prediction.signal_calibrator import SIGNAL_NAMES
        cal = self._fresh()
        w = cal.weights()
        for name in SIGNAL_NAMES:
            self.assertIn(name, w)

    def test_min_obs_threshold_neutral(self):
        cal = self._fresh()
        # Only 5 observations (< MIN_OBS=10) → should return neutral weight ~1.0
        for _ in range(5):
            cal.record("hurr_fl", 0.9, 1)
        w = cal.weight("hurr_fl")
        # raw_weight = 1.0 when < MIN_OBS
        self.assertAlmostEqual(cal._stats["hurr_fl"].raw_weight, 1.0)


# ──────────────────────────────────────────────────────────────────────────────
# H2 – CoinGecko context
# ──────────────────────────────────────────────────────────────────────────────

class TestCoinGeckoContext(unittest.TestCase):

    def _snap(self, btc_dom=48.0, mkt_chg=3.0, alt_season=True,
              top_gainer=15.0, top_loser=-5.0, total_mcap=2.5e12):
        from merid.prediction.coingecko_context import CoinGeckoContextSnapshot
        return CoinGeckoContextSnapshot(
            btc_dominance_pct=btc_dom,
            eth_dominance_pct=17.0,
            total_market_cap_usd=total_mcap,
            total_market_cap_change_24h=mkt_chg,
            total_volume_24h=1e11,
            alt_season=alt_season,
            top_gainer_symbol="SOL",
            top_gainer_pct=top_gainer,
            top_loser_pct=top_loser,
            source="stub",
        )

    def test_to_edge_features_keys(self):
        snap = self._snap()
        feats = snap.to_edge_features()
        for key in ("cg_btc_dom", "cg_market_change_24h", "cg_top_gainer",
                    "cg_top_loser", "cg_alt_season", "cg_market_expanding",
                    "cg_market_contracting", "cg_trending_count"):
            self.assertIn(key, feats, f"Missing: {key}")

    def test_market_expanding_flag(self):
        snap = self._snap(mkt_chg=3.5)
        self.assertTrue(snap.market_expanding)
        self.assertFalse(snap.market_contracting)

    def test_market_contracting_flag(self):
        snap = self._snap(mkt_chg=-3.0)
        self.assertTrue(snap.market_contracting)
        self.assertFalse(snap.market_expanding)

    def test_alt_season_flag(self):
        snap = self._snap(btc_dom=47.0, mkt_chg=2.5)
        self.assertTrue(snap.alt_season)

    def test_no_alt_season_high_btc_dom(self):
        snap = self._snap(btc_dom=60.0, alt_season=False)
        self.assertFalse(snap.alt_season)

    def test_to_dict_structure(self):
        d = self._snap().to_dict()
        self.assertIn("btc_dominance_pct", d)
        self.assertIn("alt_season", d)
        self.assertIn("top_gainer_pct", d)
        self.assertIn("trending", d)

    def test_service_stubs_on_fail(self):
        from merid.prediction.coingecko_context import CoinGeckoContextService
        svc = CoinGeckoContextService()
        err = RuntimeError("network")
        with patch("merid.prediction.coingecko_context._fetch_global",
                   new_callable=AsyncMock, side_effect=err), \
             patch("merid.prediction.coingecko_context._fetch_trending",
                   new_callable=AsyncMock, side_effect=err), \
             patch("merid.prediction.coingecko_context._fetch_top_markets",
                   new_callable=AsyncMock, side_effect=err):
            snap = asyncio.run(svc.get_snapshot())
        self.assertEqual(snap.source, "stub")

    def test_service_caches_result(self):
        from merid.prediction.coingecko_context import (
            CoinGeckoContextService, CoinGeckoContextSnapshot
        )
        live = CoinGeckoContextSnapshot(btc_dominance_pct=52.0, source="live",
                                         total_market_cap_usd=2e12)
        svc = CoinGeckoContextService()
        svc._cache = live
        svc._cache_ts = __import__("time").time()
        snap = asyncio.run(svc.get_snapshot())
        self.assertIs(snap, live)


# ──────────────────────────────────────────────────────────────────────────────
# H4 – EdgeModel Signal 9
# ──────────────────────────────────────────────────────────────────────────────

class TestEdgeModelSprintH(unittest.TestCase):

    def _model(self, coingecko=None):
        from merid.prediction.edge_model import EdgeModel
        m = EdgeModel.__new__(EdgeModel)
        m._coingecko_features = coingecko or {}
        return m

    def test_market_expanding_lifts_crypto(self):
        m = self._model(coingecko={
            "cg_market_expanding": 1.0, "cg_market_contracting": 0.0,
            "cg_alt_season": 0.0, "cg_top_gainer": 5.0,
        })
        adj, conf = m._context_signal(0.5, "BTC", "KXBTC-T")
        self.assertIsNotNone(adj)
        self.assertGreater(adj, 0.5)

    def test_market_contracting_suppresses_crypto(self):
        m = self._model(coingecko={
            "cg_market_expanding": 0.0, "cg_market_contracting": 1.0,
            "cg_alt_season": 0.0, "cg_top_gainer": 0.0,
        })
        adj, conf = m._context_signal(0.6, "ETH", "KXETH-T")
        self.assertIsNotNone(adj)
        self.assertLess(adj, 0.6)

    def test_alt_season_lifts_altcoins_not_btc(self):
        m = self._model(coingecko={
            "cg_market_expanding": 0.0, "cg_market_contracting": 0.0,
            "cg_alt_season": 1.0, "cg_top_gainer": 0.0,
        })
        adj_eth, _ = m._context_signal(0.5, "ETH", "KXETH-T")
        adj_btc, _ = m._context_signal(0.5, "BTC", "KXBTC-T")
        self.assertIsNotNone(adj_eth)
        self.assertGreater(adj_eth, 0.5)
        # BTC should not benefit from alt season
        if adj_btc is not None:
            self.assertLessEqual(adj_btc, adj_eth)

    def test_fomo_top_gainer_contrarian_nudge(self):
        m = self._model(coingecko={
            "cg_market_expanding": 0.0, "cg_market_contracting": 0.0,
            "cg_alt_season": 0.0, "cg_top_gainer": 45.0,
        })
        adj, conf = m._context_signal(0.6, "BTC", "KXBTC-T")
        self.assertIsNotNone(adj)
        self.assertLess(adj, 0.6)

    def test_non_crypto_no_coingecko_nudge(self):
        m = self._model(coingecko={
            "cg_market_expanding": 1.0, "cg_market_contracting": 0.0,
            "cg_alt_season": 1.0, "cg_top_gainer": 0.0,
        })
        adj, conf = m._context_signal(0.5, "SPX", "KXSPX-T")
        # coingecko only fires for crypto; SPX should get no nudge → returns None
        self.assertIsNone(adj)

    def test_combined_h_still_capped(self):
        from merid.prediction.edge_model import EdgeModel
        m = EdgeModel.__new__(EdgeModel)
        m._coingecko_features = {
            "cg_market_expanding": 1.0, "cg_market_contracting": 0.0,
            "cg_alt_season": 1.0, "cg_top_gainer": 50.0,
        }
        m._fg_features = {"fg_contrarian": -0.05, "fg_extreme_greed": 1.0,
                          "fg_trend_rising": 1.0}
        adj, conf = m._context_signal(0.9, "ETH", "KXETH-T")
        self.assertIsNotNone(adj)
        self.assertLessEqual(adj, 0.98)
        self.assertGreaterEqual(adj, 0.02)
        self.assertLessEqual(conf, 0.4)

    def test_model_has_coingecko_attr(self):
        import inspect
        from merid.prediction.edge_model import EdgeModel
        src = inspect.getsource(EdgeModel.__init__)
        self.assertIn("_coingecko_features", src)
        self.assertIn("_coingecko_loaded_at", src)


# ──────────────────────────────────────────────────────────────────────────────
# H3 – CoinMarketCap context
# ──────────────────────────────────────────────────────────────────────────────

class TestCMCContext(unittest.TestCase):

    def _snap(self, btc_dom=52.0, gainer_count=5, loser_count=3,
              top10_share=0.75, vol_ratio=0.06, fomo=False, panic=False):
        from merid.prediction.coinmarketcap_context import CMCContextSnapshot
        return CMCContextSnapshot(
            btc_dominance_pct=btc_dom,
            eth_dominance_pct=17.0,
            total_market_cap_usd=2.5e12,
            total_volume_24h=2.5e12 * vol_ratio,
            active_cryptocurrencies=12000,
            top10_market_cap_share=top10_share,
            gainer_count=gainer_count,
            loser_count=loser_count,
            top_gainer_symbol="SOL",
            top_gainer_pct=35.0,
            top_loser_symbol="LUNA",
            top_loser_pct=-28.0,
            vol_ratio=vol_ratio,
            source="stub",
        )

    def test_to_edge_features_keys(self):
        snap = self._snap()
        feats = snap.to_edge_features()
        for key in ("cmc_btc_dom", "cmc_gainer_count", "cmc_loser_count",
                    "cmc_top10_share", "cmc_vol_ratio", "cmc_fomo",
                    "cmc_panic", "cmc_concentrated", "cmc_top_gainer_pct",
                    "cmc_top_loser_pct"):
            self.assertIn(key, feats, f"Missing: {key}")

    def test_fomo_regime_flag(self):
        self.assertTrue(self._snap(gainer_count=12).fomo_regime)
        self.assertFalse(self._snap(gainer_count=5).fomo_regime)

    def test_panic_regime_flag(self):
        self.assertTrue(self._snap(loser_count=11).panic_regime)
        self.assertFalse(self._snap(loser_count=3).panic_regime)

    def test_concentrated_market_flag(self):
        self.assertTrue(self._snap(top10_share=0.72).concentrated_market)
        self.assertFalse(self._snap(top10_share=0.65).concentrated_market)

    def test_to_dict_structure(self):
        d = self._snap().to_dict()
        for key in ("btc_dominance_pct", "gainer_count", "loser_count",
                    "top10_market_cap_share", "fomo_regime", "panic_regime",
                    "top_gainer_symbol", "source"):
            self.assertIn(key, d, f"Missing: {key}")

    def test_service_stubs_without_key(self):
        from merid.prediction.coinmarketcap_context import CMCContextService
        import merid.prediction.coinmarketcap_context as cmcm
        orig = cmcm._CMC_KEY
        cmcm._CMC_KEY = ""
        try:
            svc = CMCContextService()
            snap = asyncio.run(svc.get_snapshot())
            self.assertEqual(snap.source, "stub")
        finally:
            cmcm._CMC_KEY = orig

    def test_service_stubs_on_network_fail(self):
        from merid.prediction.coinmarketcap_context import CMCContextService
        import merid.prediction.coinmarketcap_context as cmcm
        svc = CMCContextService()
        err = RuntimeError("network")
        with patch("merid.prediction.coinmarketcap_context._fetch_global",
                   new_callable=AsyncMock, side_effect=err), \
             patch("merid.prediction.coinmarketcap_context._fetch_listings",
                   new_callable=AsyncMock, side_effect=err):
            snap = asyncio.run(svc.get_snapshot())
        self.assertEqual(snap.source, "stub")

    def test_service_cache_hit(self):
        from merid.prediction.coinmarketcap_context import (
            CMCContextService, CMCContextSnapshot
        )
        live = CMCContextSnapshot(btc_dominance_pct=55.0, source="live",
                                   total_market_cap_usd=2e12)
        svc = CMCContextService()
        svc._cache = live
        svc._cache_ts = __import__("time").time()
        snap = asyncio.run(svc.get_snapshot())
        self.assertIs(snap, live)


# ──────────────────────────────────────────────────────────────────────────────
# H4 – EdgeModel Signal 10 (CMC)
# ──────────────────────────────────────────────────────────────────────────────

class TestEdgeModelSprintH_CMC(unittest.TestCase):

    def _model(self, cmc=None):
        from merid.prediction.edge_model import EdgeModel
        m = EdgeModel.__new__(EdgeModel)
        m._cmc_features = cmc or {}
        return m

    def test_fomo_contrarian_suppresses(self):
        m = self._model(cmc={
            "cmc_fomo": 1.0, "cmc_panic": 0.0,
            "cmc_concentrated": 0.0, "cmc_vol_ratio": 0.04,
        })
        adj, conf = m._context_signal(0.7, "BTC", "KXBTC-T")
        self.assertIsNotNone(adj)
        self.assertLess(adj, 0.7)

    def test_panic_contrarian_lifts(self):
        m = self._model(cmc={
            "cmc_fomo": 0.0, "cmc_panic": 1.0,
            "cmc_concentrated": 0.0, "cmc_vol_ratio": 0.04,
        })
        adj, conf = m._context_signal(0.4, "ETH", "KXETH-T")
        self.assertIsNotNone(adj)
        self.assertGreater(adj, 0.4)

    def test_concentration_bearish_for_small_alts(self):
        m = self._model(cmc={
            "cmc_fomo": 0.0, "cmc_panic": 0.0,
            "cmc_concentrated": 1.0, "cmc_vol_ratio": 0.04,
        })
        adj, conf = m._context_signal(0.6, "SOL", "KXSOL-T")
        self.assertIsNotNone(adj)
        self.assertLess(adj, 0.6)

    def test_concentration_neutral_for_btc(self):
        m = self._model(cmc={
            "cmc_fomo": 0.0, "cmc_panic": 0.0,
            "cmc_concentrated": 1.0, "cmc_vol_ratio": 0.04,
        })
        adj, conf = m._context_signal(0.6, "BTC", "KXBTC-T")
        # No signals fired for BTC from concentration alone → None
        self.assertIsNone(adj)

    def test_high_vol_ratio_lifts(self):
        m = self._model(cmc={
            "cmc_fomo": 0.0, "cmc_panic": 0.0,
            "cmc_concentrated": 0.0, "cmc_vol_ratio": 0.12,
        })
        adj, conf = m._context_signal(0.5, "BTC", "KXBTC-T")
        self.assertIsNotNone(adj)
        self.assertGreater(adj, 0.5)

    def test_non_crypto_no_cmc_nudge(self):
        m = self._model(cmc={
            "cmc_fomo": 1.0, "cmc_panic": 1.0,
            "cmc_concentrated": 1.0, "cmc_vol_ratio": 0.15,
        })
        adj, conf = m._context_signal(0.5, "OIL", "KXOIL-T")
        self.assertIsNone(adj)

    def test_model_has_cmc_attrs_in_init(self):
        import inspect
        from merid.prediction.edge_model import EdgeModel
        src = inspect.getsource(EdgeModel.__init__)
        self.assertIn("_cmc_features", src)
        self.assertIn("_cmc_loaded_at", src)


if __name__ == "__main__":
    unittest.main()
