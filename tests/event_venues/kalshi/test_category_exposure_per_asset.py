"""Tests for per-asset correlated-cap upgrade in CategoryExposureTracker."""

from __future__ import annotations

import importlib
import os
import sys
import unittest
import unittest.mock
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parents[3])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class TestPerAssetCorrCaps(unittest.TestCase):
    def _make_tracker(self, asset_caps=None, default_corr_cap=800.0):
        from merid.event_venues.kalshi.category_exposure import CategoryExposureTracker

        return CategoryExposureTracker(
            corr_cap_usd=default_corr_cap,
            asset_caps_usd=asset_caps,
        )

    def test_per_asset_cap_limits_btc_independently(self):
        t = self._make_tracker(asset_caps={"BTC": 200.0, "ETH": 300.0})
        t.record_fill("crypto", "BTC", 200.0)
        ok, reason = t.check_correlated_cap("BTC", additional_usd=10.0)
        self.assertFalse(ok)
        self.assertIn("corr_stack_cap_exceeded:BTC", reason)
        ok_eth, _ = t.check_correlated_cap("ETH", additional_usd=10.0)
        self.assertTrue(ok_eth)

    def test_unlisted_asset_falls_back_to_default_corr_cap(self):
        t = self._make_tracker(asset_caps={"BTC": 200.0}, default_corr_cap=150.0)
        ok, _ = t.check_correlated_cap("SOL", additional_usd=100.0)
        self.assertTrue(ok)
        ok2, _ = t.check_correlated_cap("SOL", additional_usd=100.0)
        self.assertTrue(ok2)

    def test_check_and_reserve_uses_per_asset_cap(self):
        t = self._make_tracker(asset_caps={"BTC": 50.0})
        ok, _ = t.check_and_reserve("crypto", "BTC", additional_usd=60.0)
        self.assertFalse(ok)

    def test_calibrate_from_balance_sets_per_asset_caps(self):
        t = self._make_tracker()
        # Use higher balance so calculated caps exceed minimum thresholds ($25)
        t.calibrate_from_balance(
            balance_cents=50000,  # $500 balance
            asset_fractions={"BTC": 0.20, "ETH": 0.15, "SOL": 0.10, "XRP": 0.10, "DOGE": 0.10},
        )
        # BTC cap = max(20% of $500, $25 min) = $100
        ok, reason = t.check_correlated_cap("BTC", additional_usd=101.0)
        self.assertFalse(ok)
        self.assertIn("BTC", reason)
        # ETH cap = max(15% of $500, $25 min) = $75
        ok_eth, _ = t.check_correlated_cap("ETH", additional_usd=74.0)
        self.assertTrue(ok_eth)

    def test_snapshot_includes_per_asset_caps(self):
        t = self._make_tracker(asset_caps={"BTC": 200.0, "ETH": 150.0})
        snap = t.get_snapshot()
        self.assertIn("asset_caps", snap.to_dict())
        self.assertEqual(snap.to_dict()["asset_caps"].get("BTC"), 200.0)
        self.assertEqual(snap.to_dict()["asset_caps"].get("ETH"), 150.0)

    def test_env_var_sets_asset_caps(self):
        env_patch = {"MERID_ASSET_CAP_BTC_USD": "250.0", "MERID_ASSET_CAP_ETH_USD": "180.0"}
        with unittest.mock.patch.dict(os.environ, env_patch):
            import merid.event_venues.kalshi.category_exposure as mod

            importlib.reload(mod)
            self.assertAlmostEqual(mod._DEFAULT_ASSET_CAPS_USD.get("BTC"), 250.0)
            self.assertAlmostEqual(mod._DEFAULT_ASSET_CAPS_USD.get("ETH"), 180.0)
        import merid.event_venues.kalshi.category_exposure as mod

        importlib.reload(mod)

    def test_snapshot_asset_caps_is_always_plain_dict(self):
        t = self._make_tracker()
        snap = t.get_snapshot()
        self.assertIsInstance(snap.asset_caps, dict)
        self.assertIsInstance(snap.to_dict()["asset_caps"], dict)

    def test_constructor_caps_preserved_when_calibrate_without_asset_fractions(self):
        from merid.event_venues.kalshi.category_exposure import CategoryExposureTracker

        t = CategoryExposureTracker(
            corr_cap_usd=500.0,
            asset_caps_usd={"BTC": 75.0},
        )
        t.calibrate_from_balance(20_000)  # $200 — no asset_fractions
        snap = t.get_snapshot()
        self.assertAlmostEqual(snap.asset_caps.get("BTC", 0.0), 75.0)

    def test_calibrate_asset_fractions_merged_with_constructor_env_caps(self):
        """Balance-derived caps for calibrated keys; constructor/env keys override on overlap."""
        from merid.event_venues.kalshi.category_exposure import CategoryExposureTracker

        t = CategoryExposureTracker(
            corr_cap_usd=800.0,
            asset_caps_usd={"BTC": 250.0},
        )
        # Use higher balance ($200) so ETH cap (15% = $30) exceeds minimum ($25)
        t.calibrate_from_balance(20_000, asset_fractions={"BTC": 0.20, "ETH": 0.15})
        snap = t.get_snapshot()
        self.assertAlmostEqual(snap.asset_caps["BTC"], 250.0)  # Constructor cap preserved
        # ETH cap = max(15% of $200, $25 min) = $30
        self.assertAlmostEqual(snap.asset_caps["ETH"], 30.0)

    def test_calibrate_weird_fraction_sum_not_normalized(self):
        """Fractions are not renormalized to 1.0 — values are used as-is."""
        t = self._make_tracker()
        t.calibrate_from_balance(10_000, asset_fractions={"BTC": 2.5})
        snap = t.get_snapshot()
        self.assertAlmostEqual(snap.asset_caps["BTC"], 250.0)

    def test_only_one_per_asset_cap_others_use_default_corr_cap(self):
        t = self._make_tracker(asset_caps={"SOL": 40.0}, default_corr_cap=100.0)
        ok_btc, _ = t.check_correlated_cap("BTC", 90.0)
        self.assertTrue(ok_btc)
        t.record_fill("crypto", "SOL", 39.0)
        ok_sol, reason = t.check_correlated_cap("SOL", 5.0)
        self.assertFalse(ok_sol)
        self.assertIn("SOL", reason)


if __name__ == "__main__":
    unittest.main()
