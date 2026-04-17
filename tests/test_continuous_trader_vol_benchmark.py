"""MERID_CT_VOL_BENCHMARK uses the named asset when spot exists."""

import logging
import unittest
from unittest.mock import patch

from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader


class TestVolBenchmarkSpot(unittest.TestCase):
    def test_sol_benchmark_when_configured(self):
        with patch.dict("os.environ", {"MERID_CT_VOL_BENCHMARK": "SOL"}, clear=False):
            spots = {"SOL": 123.4, "BTC": 70000.0}
            active = ["SOL", "BTC"]
            v, sym = KalshiContinuousTrader._vol_benchmark_spot_and_asset(spots, active)
            self.assertEqual(v, 123.4)
            self.assertEqual(sym, "SOL")

    def test_fallback_when_benchmark_missing_spot(self):
        with patch.dict("os.environ", {"MERID_CT_VOL_BENCHMARK": "SOL"}, clear=False):
            spots = {"BTC": 70000.0}
            active = ["BTC"]
            v, sym = KalshiContinuousTrader._vol_benchmark_spot_and_asset(spots, active)
            self.assertEqual(v, 70000.0)
            self.assertEqual(sym, "BTC")

    def test_ltc_env_warns_and_follows_default_order(self):
        with patch.dict("os.environ", {"MERID_CT_VOL_BENCHMARK": "LTC"}, clear=False):
            with self.assertLogs(
                "merid.trading.kalshi_continuous_trader", level=logging.WARNING
            ) as cm:
                v, sym = KalshiContinuousTrader._vol_benchmark_spot_and_asset(
                    {"ETH": 3000.0, "BTC": 70000.0},
                    ["ETH"],
                )
        self.assertEqual(v, 3000.0)
        self.assertEqual(sym, "ETH")
        self.assertTrue(any("MERID_CT_VOL_BENCHMARK=LTC" in x for x in cm.output))


def test_vol_benchmark_bankroll_log_line_includes_asset():
    """Cycle log format ties governing asset name to the chosen benchmark."""
    # Only SOL active so default ladder does not prefer BTC before SOL.
    spots = {"SOL": 200.0, "BTC": 100.0}
    v, sym = KalshiContinuousTrader._vol_benchmark_spot_and_asset(spots, ["SOL"])
    line = f"  Vol benchmark: asset={sym} spot={v:.2f} (governing bankroll vol track)"
    assert "Vol benchmark: asset=SOL" in line
    assert "200.00" in line
