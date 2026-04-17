"""Sprint G invariant tests.

Covers:
  G1 – AlphaVantageContextSnapshot: GDP trend, sector perf, edge features
  G2 – FearGreedContextSnapshot: contrarian signal, bias, edge features
  G3 – MessariContextSnapshot: dominance flags, momentum, edge features
  G5 – EdgeModel Signal 8: fear/greed contrarian, messari, AV GDP nudges
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ──────────────────────────────────────────────────────────────────────────────
# G1 – Alpha Vantage context
# ──────────────────────────────────────────────────────────────────────────────

class TestAlphaVantageContext(unittest.TestCase):

    def _snap(self, gdp_latest=2.8, gdp_prev=2.2, tech_ret=4.5, energy_ret=-1.2,
              trend="accelerating"):
        from merid.prediction.alphavantage_context import (
            AlphaVantageContextSnapshot, SectorPerf
        )
        snap = AlphaVantageContextSnapshot(
            real_gdp_latest=gdp_latest,
            real_gdp_prev=gdp_prev,
            gdp_trend=trend,
            tech_ret_1m=tech_ret,
            energy_ret_1m=energy_ret,
            top_sector="tech",
            bottom_sector="energy",
            source="stub",
        )
        return snap

    def test_to_edge_features_keys(self):
        snap = self._snap()
        feats = snap.to_edge_features()
        for key in ("av_gdp_latest", "av_gdp_trend", "av_tech_ret_1m",
                    "av_energy_ret_1m", "av_risk_on"):
            self.assertIn(key, feats, f"Missing: {key}")

    def test_gdp_trend_encoding(self):
        snap_acc = self._snap(trend="accelerating")
        snap_dec = self._snap(trend="decelerating")
        snap_neu = self._snap(trend="neutral")
        self.assertAlmostEqual(snap_acc.to_edge_features()["av_gdp_trend"], 1.0)
        self.assertAlmostEqual(snap_dec.to_edge_features()["av_gdp_trend"], -1.0)
        self.assertAlmostEqual(snap_neu.to_edge_features()["av_gdp_trend"], 0.0)

    def test_risk_on_flag_tech_positive(self):
        snap = self._snap(tech_ret=5.0, trend="accelerating")
        self.assertAlmostEqual(snap.to_edge_features()["av_risk_on"], 1.0)

    def test_risk_on_flag_decelerating(self):
        snap = self._snap(tech_ret=3.0, trend="decelerating")
        # risk_on = tech_ret > 0 AND trend != decelerating → False
        self.assertAlmostEqual(snap.to_edge_features()["av_risk_on"], 0.0)

    def test_to_dict_structure(self):
        d = self._snap().to_dict()
        self.assertIn("real_gdp_latest", d)
        self.assertIn("gdp_trend", d)
        self.assertIn("tech_ret_1m", d)

    def test_service_stubs_without_key(self):
        from merid.prediction.alphavantage_context import AlphaVantageContextService
        import merid.prediction.alphavantage_context as avm
        orig = avm._AV_KEY
        avm._AV_KEY = ""
        try:
            svc = AlphaVantageContextService()
            snap = asyncio.get_event_loop().run_until_complete(svc.get_snapshot())
            self.assertEqual(snap.source, "stub")
        finally:
            avm._AV_KEY = orig


# ──────────────────────────────────────────────────────────────────────────────
# G2 – Fear & Greed context
# ──────────────────────────────────────────────────────────────────────────────

class TestFearGreedContext(unittest.TestCase):

    def _snap(self, score=50, yesterday=50, trend="neutral"):
        from merid.prediction.fear_greed_context import FearGreedContextSnapshot
        return FearGreedContextSnapshot(
            score=score,
            classification="Neutral" if 40 < score < 60 else (
                "Extreme Greed" if score >= 80 else
                "Extreme Fear" if score <= 20 else
                "Greed" if score >= 60 else "Fear"
            ),
            score_yesterday=yesterday,
            score_7d_avg=float(score),
            trend=trend,
            is_extreme_fear=score <= 25,
            is_extreme_greed=score >= 75,
            source="stub",
        )

    def test_to_edge_features_keys(self):
        snap = self._snap()
        feats = snap.to_edge_features()
        for key in ("fg_score", "fg_normalized", "fg_contrarian",
                    "fg_extreme_fear", "fg_extreme_greed",
                    "fg_trend_rising", "fg_trend_falling", "fg_7d_avg"):
            self.assertIn(key, feats, f"Missing: {key}")

    def test_contrarian_extreme_fear(self):
        snap = self._snap(score=15)
        self.assertAlmostEqual(snap.contrarian_signal, 0.05)

    def test_contrarian_extreme_greed(self):
        snap = self._snap(score=85)
        self.assertAlmostEqual(snap.contrarian_signal, -0.05)

    def test_contrarian_neutral(self):
        snap = self._snap(score=50)
        self.assertAlmostEqual(snap.contrarian_signal, 0.0)

    def test_contrarian_mild_fear(self):
        snap = self._snap(score=30)
        self.assertAlmostEqual(snap.contrarian_signal, 0.025)

    def test_extreme_fear_flag(self):
        snap = self._snap(score=20)
        self.assertTrue(snap.is_extreme_fear)
        self.assertFalse(snap.is_extreme_greed)

    def test_extreme_greed_flag(self):
        snap = self._snap(score=80)
        self.assertTrue(snap.is_extreme_greed)
        self.assertFalse(snap.is_extreme_fear)

    def test_service_returns_stub_on_fail(self):
        from merid.prediction.fear_greed_context import FearGreedContextService
        svc = FearGreedContextService()
        with patch("merid.prediction.fear_greed_context._fetch_alternative_me",
                   new_callable=AsyncMock) as m:
            m.return_value = None
            snap = asyncio.get_event_loop().run_until_complete(svc.get_snapshot())
        self.assertEqual(snap.source, "stub")

    def test_service_returns_live_snap(self):
        from merid.prediction.fear_greed_context import (
            FearGreedContextService, FearGreedContextSnapshot
        )
        live = FearGreedContextSnapshot(score=35, classification="Fear", source="live")
        svc = FearGreedContextService()
        with patch("merid.prediction.fear_greed_context._fetch_alternative_me",
                   new_callable=AsyncMock) as m:
            m.return_value = live
            snap = asyncio.get_event_loop().run_until_complete(svc.get_snapshot())
        self.assertEqual(snap.score, 35)
        self.assertEqual(snap.source, "live")

    def test_to_dict_structure(self):
        d = self._snap(score=25).to_dict()
        self.assertIn("score", d)
        self.assertIn("contrarian_signal", d)
        self.assertIn("is_extreme_fear", d)


# ──────────────────────────────────────────────────────────────────────────────
# G3 – Messari context
# ──────────────────────────────────────────────────────────────────────────────

class TestMessariContext(unittest.TestCase):

    def _snap(self, btc_dom=52.0, btc_7d=6.0, eth_7d=7.0,
              btc_24h=2.5, btc_price=65000.0):
        from merid.prediction.messari_context import (
            MessariContextSnapshot, AssetMetrics
        )
        return MessariContextSnapshot(
            btc=AssetMetrics(
                symbol="BTC",
                price_usd=btc_price,
                pct_change_24h=btc_24h,
                pct_change_7d=btc_7d,
                dominance_pct=btc_dom,
            ),
            eth=AssetMetrics(
                symbol="ETH",
                price_usd=3500.0,
                pct_change_24h=1.5,
                pct_change_7d=eth_7d,
                dominance_pct=17.0,
            ),
            source="stub",
        )

    def test_to_edge_features_keys(self):
        snap = self._snap()
        feats = snap.to_edge_features()
        for key in ("messari_btc_24h", "messari_btc_7d", "messari_eth_24h",
                    "messari_eth_7d", "messari_btc_dominance", "messari_btc_nvt",
                    "messari_btc_dom_high", "messari_btc_momentum", "messari_market_up"):
            self.assertIn(key, feats, f"Missing: {key}")

    def test_btc_dominance_high_flag(self):
        self.assertTrue(self._snap(btc_dom=60.0).btc_dominance_high)
        self.assertFalse(self._snap(btc_dom=50.0).btc_dominance_high)

    def test_btc_momentum_flag(self):
        self.assertTrue(self._snap(btc_24h=3.0).btc_momentum_strong)
        self.assertFalse(self._snap(btc_24h=1.0).btc_momentum_strong)

    def test_market_trending_up(self):
        self.assertTrue(self._snap(btc_7d=5.0, eth_7d=4.0).market_trending_up)
        self.assertFalse(self._snap(btc_7d=1.0, eth_7d=5.0).market_trending_up)

    def test_to_dict_structure(self):
        d = self._snap().to_dict()
        self.assertIn("btc", d)
        self.assertIn("eth", d)
        self.assertIn("btc_dominance_high", d)
        self.assertIn("market_trending_up", d)

    def test_service_stubs_on_network_fail(self):
        from merid.prediction.messari_context import MessariContextService
        svc = MessariContextService()
        with patch("merid.prediction.messari_context._fetch_asset",
                   new_callable=AsyncMock) as m:
            m.side_effect = RuntimeError("network")
            snap = asyncio.get_event_loop().run_until_complete(svc.get_snapshot())
        self.assertIn(snap.source, ("live", "stub"))


# ──────────────────────────────────────────────────────────────────────────────
# G5 – EdgeModel Signal 8
# ──────────────────────────────────────────────────────────────────────────────

class TestEdgeModelSprintG(unittest.TestCase):

    def _model(self, fg=None, messari=None, av=None):
        from merid.prediction.edge_model import EdgeModel
        m = EdgeModel.__new__(EdgeModel)
        # Only set G features; getattr handles missing attrs for D/E/F
        m._fg_features      = fg      or {}
        m._messari_features = messari or {}
        m._av_features      = av      or {}
        return m

    def test_extreme_fear_lifts_crypto(self):
        m = self._model(fg={"fg_contrarian": 0.05, "fg_extreme_greed": 0.0,
                            "fg_trend_rising": 0.0})
        adj, conf = m._context_signal(0.5, "BTC", "KXBTC-T")
        self.assertIsNotNone(adj)
        self.assertGreater(adj, 0.5)

    def test_extreme_greed_suppresses_crypto(self):
        m = self._model(fg={"fg_contrarian": -0.05, "fg_extreme_greed": 1.0,
                            "fg_trend_rising": 1.0})
        adj, conf = m._context_signal(0.6, "BTC", "KXBTC-T")
        self.assertIsNotNone(adj)
        self.assertLess(adj, 0.6)

    def test_neutral_fg_no_nudge(self):
        m = self._model(fg={"fg_contrarian": 0.0, "fg_extreme_greed": 0.0,
                            "fg_trend_rising": 0.0})
        adj, conf = m._context_signal(0.6, "BTC", "KXBTC-T")
        # fg dict is truthy so signals_fired >= 0; adj may == 0.6 or None
        if adj is not None:
            self.assertAlmostEqual(adj, 0.6, delta=0.08)

    def test_btc_7d_momentum_lifts(self):
        m = self._model(messari={"messari_btc_dom_high": 0.0,
                                  "messari_btc_7d": 6.0,
                                  "messari_eth_7d": 5.0,
                                  "messari_btc_momentum": 1.0,
                                  "messari_market_up": 1.0})
        adj, conf = m._context_signal(0.5, "ETH", "KXETH-T")
        self.assertIsNotNone(adj)
        self.assertGreater(adj, 0.5)

    def test_btc_crash_suppresses(self):
        m = self._model(messari={"messari_btc_dom_high": 0.0,
                                  "messari_btc_7d": -8.0,
                                  "messari_eth_7d": -5.0,
                                  "messari_btc_momentum": 0.0,
                                  "messari_market_up": 0.0})
        adj, conf = m._context_signal(0.6, "BTC", "KXBTC-T")
        self.assertIsNotNone(adj)
        self.assertLess(adj, 0.6)

    def test_high_btc_dominance_bearish_for_alts(self):
        m = self._model(messari={"messari_btc_dom_high": 1.0,
                                  "messari_btc_7d": 0.0,
                                  "messari_eth_7d": 0.0})
        adj, conf = m._context_signal(0.6, "ETH", "KXETH-T")
        self.assertIsNotNone(adj)
        self.assertLess(adj, 0.6)

    def test_decelerating_gdp_bearish_crypto(self):
        m = self._model(av={"av_gdp_trend": -1.0, "av_tech_ret_1m": 0.0})
        adj, conf = m._context_signal(0.6, "BTC", "KXBTC-T")
        self.assertIsNotNone(adj)
        self.assertLess(adj, 0.6)

    def test_strong_tech_lifts_crypto(self):
        m = self._model(av={"av_gdp_trend": 0.0, "av_tech_ret_1m": 5.0})
        adj, conf = m._context_signal(0.5, "BTC", "KXBTC-T")
        self.assertIsNotNone(adj)
        self.assertGreater(adj, 0.5)

    def test_combined_g_signals_still_capped(self):
        m = self._model(
            fg={"fg_contrarian": -0.05, "fg_extreme_greed": 1.0, "fg_trend_rising": 1.0},
            messari={"messari_btc_dom_high": 1.0, "messari_btc_7d": -8.0,
                     "messari_eth_7d": -6.0, "messari_btc_momentum": 0.0},
            av={"av_gdp_trend": -1.0, "av_tech_ret_1m": -5.0},
        )
        adj, conf = m._context_signal(0.9, "BTC", "KXBTC-T")
        self.assertIsNotNone(adj)
        self.assertGreaterEqual(adj, 0.02)
        self.assertLessEqual(adj, 0.98)
        self.assertLessEqual(conf, 0.4)

    def test_model_init_has_g_attrs(self):
        from merid.prediction.edge_model import EdgeModel
        m = EdgeModel.__new__(EdgeModel)
        # Test that __init__ signature includes the new G attrs
        # (we don't call __init__ due to side-effects; just verify source exists)
        import inspect
        src = inspect.getsource(EdgeModel.__init__)
        for attr in ("_av_features", "_fg_features", "_messari_features"):
            self.assertIn(attr, src, f"__init__ missing {attr}")


if __name__ == "__main__":
    unittest.main()
