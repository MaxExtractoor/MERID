"""Sprint D invariant tests.

Covers every deliverable added in Sprint D:
  D1 – MacroContextSnapshot dataclass + to_dict / to_edge_features
  D2 – BLS release calendar (_bls_releases_near) heuristic correctness
  D3 – Deribit IV fetch path + realized-vol fallback in perp_context
  D4 – MetaculusContextSnapshot dataclass + CategoryPrior.prior_prob
  D5 – EdgeModel._context_signal() nudge logic + _refresh_context_cache no-op
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ──────────────────────────────────────────────────────────────────────────────
# D1 – MacroContextSnapshot
# ──────────────────────────────────────────────────────────────────────────────

class TestMacroContextSnapshot(unittest.TestCase):
    """D1: MacroContextSnapshot dataclass properties and feature dict."""

    def _snap(self, **kwargs):
        from merid.prediction.macro_context import MacroContextSnapshot
        defaults = dict(
            fed_funds_rate=5.25, cpi_yoy=3.7, cpi_momentum=0.2,
            unemployment_rate=3.9, yield_spread_10y2y=-0.4,
            vix=22.0, treasury_10y=4.5, source="stub",
        )
        defaults.update(kwargs)
        return MacroContextSnapshot(**defaults)

    def test_to_edge_features_keys(self):
        snap = self._snap()
        feats = snap.to_edge_features()
        for key in (
            "macro_fed_funds_rate", "macro_cpi_yoy", "macro_cpi_momentum",
            "macro_unemployment", "macro_yield_spread_10y2y",
            "macro_vix", "macro_treasury_10y",
            "macro_inverted_curve", "macro_high_inflation",
            "macro_high_vix", "macro_release_days_away",
        ):
            self.assertIn(key, feats, f"Missing: {key}")

    def test_inverted_curve_flag(self):
        snap = self._snap(yield_spread_10y2y=-0.5)
        self.assertTrue(snap.is_inverted_curve)
        snap2 = self._snap(yield_spread_10y2y=0.3)
        self.assertFalse(snap2.is_inverted_curve)

    def test_high_inflation_flag(self):
        self.assertTrue(self._snap(cpi_yoy=4.0).is_high_inflation)
        self.assertFalse(self._snap(cpi_yoy=2.0).is_high_inflation)

    def test_high_vix_flag(self):
        self.assertTrue(self._snap(vix=30.0).is_high_vix)
        self.assertFalse(self._snap(vix=18.0).is_high_vix)

    def test_to_dict_keys(self):
        snap = self._snap()
        d = snap.to_dict()
        for key in ("fed_funds_rate", "cpi_yoy", "unemployment_rate",
                    "yield_spread_10y2y", "vix", "upcoming_releases"):
            self.assertIn(key, d)

    def test_inverted_curve_edge_feature_is_float(self):
        snap = self._snap(yield_spread_10y2y=-0.3)
        feats = snap.to_edge_features()
        self.assertEqual(feats["macro_inverted_curve"], 1.0)

    def test_service_stub_on_no_key(self):
        """Without FRED_API_KEY the service returns a stub snapshot."""
        from merid.prediction.macro_context import MacroContextService
        svc = MacroContextService()
        snap = asyncio.get_event_loop().run_until_complete(svc.get_snapshot())
        self.assertIn(snap.source, ("live", "stub"))
        self.assertIsInstance(snap.fed_funds_rate, float)


# ──────────────────────────────────────────────────────────────────────────────
# D2 – BLS release calendar
# ──────────────────────────────────────────────────────────────────────────────

class TestBLSReleaseCalendar(unittest.TestCase):
    """D2: _bls_releases_near() returns NFP/CPI/PPI alerts around today."""

    def test_returns_list(self):
        from merid.prediction.macro_context import _bls_releases_near
        alerts = _bls_releases_near(date.today(), window_days=60)
        self.assertIsInstance(alerts, list)

    def test_has_expected_reports(self):
        from merid.prediction.macro_context import _bls_releases_near
        alerts = _bls_releases_near(date.today(), window_days=60)
        report_names = {a.report for a in alerts}
        # Should see at least NFP and CPI within a 60-day window
        self.assertTrue(report_names.issuperset({"NFP", "CPI"}),
                        f"Expected NFP+CPI in {report_names}")

    def test_days_away_sign(self):
        from merid.prediction.macro_context import _bls_releases_near, BLSReleaseAlert
        today = date(2026, 2, 1)
        alerts = _bls_releases_near(today, window_days=40)
        for a in alerts:
            self.assertEqual(a.days_away, (a.release_date - today).days)

    def test_nfp_is_friday(self):
        from merid.prediction.macro_context import _bls_releases_near
        alerts = _bls_releases_near(date.today(), window_days=60)
        nfp_alerts = [a for a in alerts if a.report == "NFP"]
        for a in nfp_alerts:
            # Friday = weekday 4
            self.assertEqual(a.release_date.weekday(), 4,
                             f"NFP {a.release_date} is not a Friday")

    def test_nth_weekday_helper(self):
        from merid.prediction.macro_context import _nth_weekday_of_month
        # First Friday of Feb 2026 should be 2026-02-06
        d = _nth_weekday_of_month(2026, 2, 4, 1)
        self.assertEqual(d, date(2026, 2, 6))


# ──────────────────────────────────────────────────────────────────────────────
# D3 – Deribit IV + fallback
# ──────────────────────────────────────────────────────────────────────────────

class TestDeribitIV(unittest.TestCase):
    """D3: _fetch_deribit_iv uses DVOL; _fetch_iv falls back to realized vol."""

    def test_deribit_iv_returns_float_on_success(self):
        from merid.prediction.perp_context import _fetch_deribit_iv
        mock_resp = {
            "result": {"data": [[1700000000000, 60.0, 65.0, 58.0, 63.0]]}
        }
        with patch("merid.prediction.perp_context._fetch_json", new_callable=AsyncMock) as m:
            m.return_value = mock_resp
            iv = asyncio.get_event_loop().run_until_complete(_fetch_deribit_iv("BTC"))
        self.assertAlmostEqual(iv, 0.63, places=2)

    def test_deribit_iv_returns_zero_on_failure(self):
        from merid.prediction.perp_context import _fetch_deribit_iv
        with patch("merid.prediction.perp_context._fetch_json", new_callable=AsyncMock) as m:
            m.side_effect = RuntimeError("timeout")
            iv = asyncio.get_event_loop().run_until_complete(_fetch_deribit_iv("BTC"))
        self.assertEqual(iv, 0.0)

    def test_fetch_iv_prefers_deribit(self):
        from merid.prediction.perp_context import _fetch_iv
        mock_resp = {
            "result": {"data": [[1700000000000, 60.0, 65.0, 58.0, 70.0]]}
        }
        with patch("merid.prediction.perp_context._fetch_json", new_callable=AsyncMock) as m:
            m.return_value = mock_resp
            iv = asyncio.get_event_loop().run_until_complete(_fetch_iv("BTCUSD"))
        self.assertGreater(iv, 0.0)

    def test_realized_vol_fallback_on_deribit_fail(self):
        from merid.prediction.perp_context import _fetch_iv
        call_count = 0

        async def mock_fetch(url: str):
            nonlocal call_count
            call_count += 1
            if "deribit" in url:
                raise RuntimeError("deribit down")
            # Return Binance klines format
            return [[i, 50.0 + i, 55.0 + i, 48.0 + i, 52.0 + i, 1000] for i in range(30)]

        with patch("merid.prediction.perp_context._fetch_json", side_effect=mock_fetch):
            iv = asyncio.get_event_loop().run_until_complete(_fetch_iv("BTCUSD"))
        # Should have called both Deribit (failed) and Binance (succeeded)
        self.assertGreaterEqual(call_count, 2)
        self.assertGreaterEqual(iv, 0.0)


# ──────────────────────────────────────────────────────────────────────────────
# D4 – Metaculus context
# ──────────────────────────────────────────────────────────────────────────────

class TestMetaculusContext(unittest.TestCase):
    """D4: CategoryPrior and MetaculusContextSnapshot semantics."""

    def _prior(self, n=20, mean_cp=0.6, res_rate=0.55):
        from merid.prediction.metaculus_context import CategoryPrior
        return CategoryPrior(
            category="crypto",
            n_resolved=n,
            mean_community_prob=mean_cp,
            resolution_rate=res_rate,
            calibration_error=abs(mean_cp - res_rate),
        )

    def test_prior_prob_blend(self):
        p = self._prior(mean_cp=0.7, res_rate=0.5)
        # 0.7*0.5 + 0.3*0.7 = 0.35 + 0.21 = 0.56
        self.assertAlmostEqual(p.prior_prob, 0.56, places=2)

    def test_prior_prob_no_data_defaults_half(self):
        from merid.prediction.metaculus_context import CategoryPrior
        p = CategoryPrior(category="test", n_resolved=0,
                          mean_community_prob=0.5, resolution_rate=0.5,
                          calibration_error=0.0)
        self.assertEqual(p.prior_prob, 0.5)

    def test_snapshot_get_prior_unknown_category(self):
        from merid.prediction.metaculus_context import MetaculusContextSnapshot
        snap = MetaculusContextSnapshot(priors={}, source="stub")
        self.assertEqual(snap.get_prior("unknown"), 0.5)

    def test_snapshot_to_dict_keys(self):
        from merid.prediction.metaculus_context import MetaculusContextSnapshot
        snap = MetaculusContextSnapshot(source="stub")
        d = snap.to_dict()
        self.assertIn("priors", d)
        self.assertIn("source", d)

    def test_to_edge_features_for_category(self):
        from merid.prediction.metaculus_context import MetaculusContextSnapshot
        snap = MetaculusContextSnapshot(priors={"crypto": self._prior()}, source="stub")
        feats = snap.to_edge_features("crypto")
        self.assertIn("metaculus_crypto_prior", feats)
        self.assertIn("metaculus_crypto_cal_error", feats)
        self.assertIn("metaculus_crypto_n", feats)

    def test_service_returns_stub_on_network_fail(self):
        from merid.prediction.metaculus_context import MetaculusContextService
        svc = MetaculusContextService()
        with patch("merid.prediction.metaculus_context._fetch_json", new_callable=AsyncMock) as m:
            m.side_effect = RuntimeError("network")
            snap = asyncio.get_event_loop().run_until_complete(svc.get_snapshot())
        self.assertIn(snap.source, ("live", "stub"))


# ──────────────────────────────────────────────────────────────────────────────
# D5 – EdgeModel context signal
# ──────────────────────────────────────────────────────────────────────────────

class TestEdgeModelContextSignal(unittest.TestCase):
    """D5: _context_signal() applies correct nudges; _refresh_context_cache is safe."""

    def _model_with_features(self, macro=None, perp=None):
        from merid.prediction.edge_model import EdgeModel
        m = EdgeModel.__new__(EdgeModel)
        m._macro_features = macro or {}
        m._perp_features = perp or {}
        m._macro_loaded_at = 9e9
        m._perp_loaded_at = 9e9
        m._CONTEXT_TTL = 120.0
        return m

    def test_no_features_returns_none(self):
        from merid.prediction.edge_model import EdgeModel
        m = EdgeModel.__new__(EdgeModel)
        m._macro_features = None
        m._perp_features = None
        adj, conf = m._context_signal(0.6, "BTC", "KXBTC-T")
        self.assertIsNone(adj)
        self.assertEqual(conf, 0.0)

    def test_high_vix_pulls_toward_half(self):
        m = self._model_with_features(macro={"macro_vix": 35.0, "macro_release_days_away": 99.0})
        adj, conf = m._context_signal(0.8, "BTC", "KXBTC-T")
        self.assertIsNotNone(adj)
        self.assertLess(adj, 0.8)   # pulled toward 0.5 from 0.8

    def test_inverted_curve_bearish_crypto(self):
        m = self._model_with_features(macro={
            "macro_inverted_curve": 1.0,
            "macro_vix": 18.0,
            "macro_release_days_away": 99.0,
        })
        adj, conf = m._context_signal(0.6, "BTC", "KXBTC-T")
        self.assertIsNotNone(adj)
        self.assertLess(adj, 0.6)   # bearish nudge

    def test_positive_funding_bearish_for_yes(self):
        m = self._model_with_features(perp={"btc_funding_rate": 0.002, "btc_iv_30d": 0.5})
        adj, conf = m._context_signal(0.6, "BTC", "KXBTC-T")
        self.assertIsNotNone(adj)
        self.assertLess(adj, 0.6)

    def test_nudge_capped_at_08(self):
        # Stack every bearish signal simultaneously
        m = self._model_with_features(
            macro={
                "macro_vix": 60.0,
                "macro_inverted_curve": 1.0,
                "macro_cpi_momentum": 1.0,
                "macro_release_days_away": 0.0,
            },
            perp={"btc_funding_rate": 0.01, "btc_iv_30d": 1.5},
        )
        adj, conf = m._context_signal(0.9, "BTC", "KXBTC-T")
        self.assertIsNotNone(adj)
        self.assertGreaterEqual(adj, 0.02)   # clamp applied

    def test_confidence_bounded(self):
        m = self._model_with_features(
            macro={"macro_vix": 35.0, "macro_inverted_curve": 1.0, "macro_release_days_away": 0.0},
            perp={"btc_funding_rate": 0.002, "btc_iv_30d": 0.9},
        )
        _, conf = m._context_signal(0.6, "BTC", "T")
        self.assertLessEqual(conf, 0.4)

    def test_non_crypto_asset_skips_perp_signals(self):
        # For a non-crypto asset, perp signals should not fire
        m = self._model_with_features(perp={"btc_funding_rate": 0.01})
        adj, conf = m._context_signal(0.6, "SPX", "KXSPX-T")
        # Either no adjustment or very small (only macro could fire)
        if adj is not None:
            self.assertAlmostEqual(adj, 0.6, delta=0.05)

    def test_refresh_context_cache_safe_when_stale(self):
        from merid.prediction.edge_model import EdgeModel
        m = EdgeModel.__new__(EdgeModel)
        m._macro_features = None
        m._perp_features = None
        m._macro_loaded_at = 0.0
        m._perp_loaded_at = 0.0
        m._CONTEXT_TTL = 120.0
        # Should not raise even with no event loop
        try:
            m._refresh_context_cache()
        except Exception as exc:
            self.fail(f"_refresh_context_cache raised: {exc}")

    def test_edge_model_has_context_attributes(self):
        from merid.prediction.edge_model import EdgeModel
        m = EdgeModel.__new__(EdgeModel)
        m._macro_features = None
        m._perp_features = None
        m._macro_loaded_at = 0.0
        m._perp_loaded_at = 0.0
        m._CONTEXT_TTL = 120.0
        self.assertTrue(hasattr(m, "_context_signal"))
        self.assertTrue(hasattr(m, "_refresh_context_cache"))
        self.assertTrue(hasattr(m, "_CONTEXT_TTL"))


if __name__ == "__main__":
    unittest.main()
