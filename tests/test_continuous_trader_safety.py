"""Unit tests for KalshiContinuousTrader safety and exposure helpers."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class TestAvgPriceAndExposure(unittest.TestCase):
    def test_avg_price_from_payload(self):
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader

        self.assertEqual(
            KalshiContinuousTrader._avg_price_cents_from_position_payload(
                {"avg_price": 42},
            ),
            42,
        )
        self.assertEqual(
            KalshiContinuousTrader._avg_price_cents_from_position_payload({}),
            0,
        )

    def test_exposure_uses_entry_not_flat_50(self):
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader, TraderConfig

        t = KalshiContinuousTrader.__new__(KalshiContinuousTrader)
        t.config = TraderConfig()
        pos = {"qty": 2, "side": "yes", "avg_price_cents": 30}
        self.assertEqual(t._position_cost_basis_cents(pos), 60)
        agg = {"A": pos}
        self.assertEqual(t._aggregate_position_exposure_cents(agg), 60)

    def test_exposure_unknown_entry_is_conservative(self):
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader, TraderConfig

        t = KalshiContinuousTrader.__new__(KalshiContinuousTrader)
        t.config = TraderConfig()
        pos = {"qty": 2, "side": "yes", "avg_price_cents": 0}
        self.assertEqual(t._position_cost_basis_cents(pos), 200)


class TestResolveTraderMinEdge(unittest.TestCase):
    def test_diagnostic_profile_uses_default_floor(self):
        from merid.trading import kalshi_continuous_trader as kct

        with patch.dict(
            os.environ,
            {"KALSHI_CT_PROFILE": "diagnostic", "KALSHI_TRADER_MIN_EDGE": ""},
            clear=False,
        ):
            me = kct._resolve_trader_min_edge(smoke_test=False)
        self.assertEqual(str(me), "0.008")

    def test_diagnostic_overridden_by_env(self):
        from merid.trading import kalshi_continuous_trader as kct

        with patch.dict(
            os.environ,
            {"KALSHI_CT_PROFILE": "diagnostic", "KALSHI_TRADER_MIN_EDGE": "0.015"},
            clear=False,
        ):
            me = kct._resolve_trader_min_edge(smoke_test=False)
        self.assertEqual(str(me), "0.015")


class TestStrikeSeriesPerMarket(unittest.TestCase):
    def test_infer_differs_for_15m_vs_daily_series(self):
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader

        _, tf15 = KalshiContinuousTrader._infer_asset_timeframe("KXBTC15M")
        _, tfh = KalshiContinuousTrader._infer_asset_timeframe("KXBTC")
        _, tfd = KalshiContinuousTrader._infer_asset_timeframe("KXBTCD1")
        self.assertEqual(tf15, "15m")
        self.assertEqual(tfh, "1h")
        self.assertEqual(tfd, "daily")


class TestLivePmGate(unittest.TestCase):
    def test_demo_env_allows_without_pm_live(self):
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader, TraderConfig

        t = KalshiContinuousTrader.__new__(KalshiContinuousTrader)
        t.config = TraderConfig(dry_run=False)
        t._guardian = None  # not wired in __new__ bypass
        t._base_url = "https://demo-api.kalshi.co/trade-api/v2"  # required by _live_api_orders_allowed
        with patch.dict(os.environ, {"KALSHI_ENV": "demo"}, clear=False):
            ok, reason = t._live_api_orders_allowed()
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_dry_run_allows_even_if_live_env(self):
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader, TraderConfig

        t = KalshiContinuousTrader.__new__(KalshiContinuousTrader)
        t.config = TraderConfig(dry_run=True)
        t._guardian = None  # not wired in __new__ bypass
        t._base_url = "https://api.elections.kalshi.com/trade-api/v2"  # required by _live_api_orders_allowed
        with patch.dict(os.environ, {"KALSHI_ENV": "live"}, clear=False):
            ok, _ = t._live_api_orders_allowed()
        self.assertTrue(ok)


class TestTransportFailureStatus(unittest.TestCase):
    def test_constant_is_zero(self):
        import merid.trading.kalshi_continuous_trader as ctmod

        self.assertEqual(ctmod._CT_TRANSPORT_FAILURE_STATUS, 0)


class TestPerAssetConfig(unittest.TestCase):
    def test_default_asset_exposure_pcts(self):
        from merid.trading.kalshi_continuous_trader import TraderConfig
        cfg = TraderConfig()
        self.assertEqual(cfg.asset_max_exposure_pct["BTC"], 0.30)
        self.assertEqual(cfg.asset_max_exposure_pct["ETH"], 0.30)
        self.assertEqual(cfg.asset_max_exposure_pct["SOL"], 0.30)
        self.assertEqual(cfg.asset_max_exposure_pct["XRP"], 0.30)
        self.assertEqual(cfg.asset_max_exposure_pct["DOGE"], 0.30)
        self.assertEqual(cfg.asset_exposure_default_pct, 0.10)

    def test_default_series_multipliers(self):
        from merid.trading.kalshi_continuous_trader import TraderConfig
        cfg = TraderConfig()
        self.assertEqual(cfg.series_exposure_multiplier["15m"],   0.40)
        self.assertEqual(cfg.series_exposure_multiplier["1h"],    0.70)
        self.assertEqual(cfg.series_exposure_multiplier["daily"], 1.00)

    def test_global_max_exposure_pct_default(self):
        from merid.trading.kalshi_continuous_trader import TraderConfig
        cfg = TraderConfig()
        self.assertEqual(cfg.global_max_exposure_pct, 0.50)

    def test_min_asset_cap_cents_default(self):
        from merid.trading.kalshi_continuous_trader import TraderConfig
        cfg = TraderConfig()
        self.assertEqual(cfg.min_asset_cap_cents, 100)

    def test_from_env_reads_asset_exposure_overrides(self):
        import os
        import unittest.mock
        from merid.trading.kalshi_continuous_trader import TraderConfig
        env_patch = {
            "KALSHI_TRADER_EXPOSURE_BTC":  "0.25",
            "KALSHI_TRADER_EXPOSURE_ETH":  "0.18",
            "KALSHI_TRADER_GLOBAL_EXPOSURE": "0.50",
            "KALSHI_TRADER_MIN_ASSET_CAP_CENTS": "200",
        }
        with unittest.mock.patch.dict(os.environ, env_patch):
            cfg = TraderConfig.from_env()
        self.assertAlmostEqual(cfg.asset_max_exposure_pct["BTC"], 0.25)
        self.assertAlmostEqual(cfg.asset_max_exposure_pct["ETH"], 0.18)
        self.assertAlmostEqual(cfg.global_max_exposure_pct, 0.50)
        self.assertEqual(cfg.min_asset_cap_cents, 200)


class TestTraderConfigFromEnvExposureFields(unittest.TestCase):
    """from_env wires cents/global/asset pcts; series multipliers stay dataclass defaults."""

    def test_from_env_preserves_series_exposure_multiplier_defaults(self):
        import unittest.mock
        from merid.trading.kalshi_continuous_trader import TraderConfig

        baseline = TraderConfig()
        with unittest.mock.patch.dict(
            os.environ,
            {"KALSHI_TRADER_EXPOSURE_BTC": "0.22"},
            clear=False,
        ):
            cfg = TraderConfig.from_env()
        self.assertEqual(cfg.series_exposure_multiplier, baseline.series_exposure_multiplier)
        self.assertAlmostEqual(cfg.asset_max_exposure_pct["BTC"], 0.22)


class TestPerAssetExposureBreakdown(unittest.TestCase):
    def _make_trader(self):
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader, TraderConfig

        t = KalshiContinuousTrader.__new__(KalshiContinuousTrader)
        t.config = TraderConfig()
        return t

    def test_single_btc_position(self):
        t = self._make_trader()
        positions = {
            "KXBTC-26MAR2717-T58900": {"qty": 3, "side": "yes", "avg_price_cents": 100},
        }
        result = t._per_asset_exposure_cents(positions)
        self.assertEqual(result, {"BTC": 300})

    def test_btc_and_eth_positions(self):
        t = self._make_trader()
        positions = {
            "KXBTC-26MAR2717-T58900":   {"qty": 3, "side": "yes", "avg_price_cents": 100},
            "KXETH15M-26MAR251945-45":  {"qty": 1, "side": "yes", "avg_price_cents": 45},
            "KXSOL15M-26MAR251945-10":  {"qty": 2, "side": "yes", "avg_price_cents": 10},
        }
        result = t._per_asset_exposure_cents(positions)
        self.assertEqual(result["BTC"], 300)
        self.assertEqual(result["ETH"], 45)
        self.assertEqual(result["SOL"], 20)
        self.assertNotIn("XRP", result)

    def test_zero_qty_positions_excluded(self):
        t = self._make_trader()
        positions = {
            "KXBTC-26MAR2717-T58900": {"qty": 0, "side": "yes", "avg_price_cents": 100},
            "KXETH15M-26MAR251945-45": {"qty": 2, "side": "yes", "avg_price_cents": 45},
        }
        result = t._per_asset_exposure_cents(positions)
        self.assertNotIn("BTC", result)
        self.assertEqual(result["ETH"], 90)

    def test_multiple_btc_series_aggregated(self):
        t = self._make_trader()
        positions = {
            "KXBTC15M-26MAR251945-45":  {"qty": 2, "side": "yes", "avg_price_cents": 20},
            "KXBTC-26MAR2717-T58900":   {"qty": 1, "side": "yes", "avg_price_cents": 30},
        }
        result = t._per_asset_exposure_cents(positions)
        self.assertEqual(result["BTC"], 70)

    def test_per_asset_sum_matches_aggregate_exposure(self):
        t = self._make_trader()
        positions = {
            "KXBTC15M-26MAR251945-45": {"qty": 1, "side": "yes", "avg_price_cents": 40},
            "KXETH15M-26MAR251945-45": {"qty": 2, "side": "yes", "avg_price_cents": 30},
        }
        agg = t._aggregate_position_exposure_cents(positions)
        by_asset = t._per_asset_exposure_cents(positions)
        self.assertEqual(agg, sum(by_asset.values()))

    def test_short_side_uses_abs_qty_same_as_aggregate(self):
        t = self._make_trader()
        positions = {
            "KXBTC-26MAR2717-T58900": {"qty": -2, "side": "no", "avg_price_cents": 25},
        }
        self.assertEqual(t._aggregate_position_exposure_cents(positions), 50)
        self.assertEqual(t._per_asset_exposure_cents(positions), {"BTC": 50})


class TestEvaluateEntryExposureSkip(unittest.TestCase):
    """Single-sourced evaluator: per-asset gate runs before global."""

    def _cfg(self):
        from merid.trading.kalshi_continuous_trader import TraderConfig

        return TraderConfig(
            asset_max_exposure_pct={"BTC": 0.20, "ETH": 0.15, "SOL": 0.10, "XRP": 0.10, "DOGE": 0.10},
            asset_exposure_default_pct=0.10,
            series_exposure_multiplier={"15m": 0.40, "1h": 0.70, "daily": 1.00, "weekly": 1.00},
            global_max_exposure_pct=0.40,
            min_asset_cap_cents=50,
        )

    def test_per_asset_skip_even_when_global_has_headroom(self):
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader

        cfg = self._cfg()
        balance = 1211
        total = 400
        per_asset = {"BTC": 250}
        cost = 10
        btc_cap_daily = max(50, int(balance * 0.20 * 1.0))
        self.assertLess(total + cost, int(balance * cfg.global_max_exposure_pct))
        self.assertGreater(per_asset["BTC"] + cost, btc_cap_daily)
        st = KalshiContinuousTrader.evaluate_entry_exposure_skip(
            balance, total, per_asset, cost, "BTC", "daily", cfg,
        )
        self.assertEqual(st, "per_asset")

    def test_global_skip_when_per_asset_has_headroom(self):
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader

        cfg = self._cfg()
        balance = 1211
        total = 480
        per_asset = {"ETH": 50}
        cost = 10
        eth_cap_15m = max(50, int(balance * 0.15 * 0.40))
        self.assertLessEqual(per_asset["ETH"] + cost, eth_cap_15m)
        self.assertGreater(total + cost, int(balance * cfg.global_max_exposure_pct))
        st = KalshiContinuousTrader.evaluate_entry_exposure_skip(
            balance, total, per_asset, cost, "ETH", "15m", cfg,
        )
        self.assertEqual(st, "global")

    def test_large_notional_blocked_by_per_asset_cap(self):
        """High balance / generous bankroll sizing does not bypass per-asset caps."""
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader

        cfg = self._cfg()
        balance = 5_000_000  # $50,000
        total = 0
        per_asset = {}
        cost = 2_000_000  # $20,000 notional vs 20% per-asset daily = $10,000
        st = KalshiContinuousTrader.evaluate_entry_exposure_skip(
            balance, total, per_asset, cost, "BTC", "daily", cfg,
        )
        self.assertEqual(st, "per_asset")

    def test_unknown_asset_bucket_uses_default_pct(self):
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader

        cfg = self._cfg()
        balance = 1000
        st = KalshiContinuousTrader.evaluate_entry_exposure_skip(
            balance, 0, {}, 500, "UNK", "daily", cfg,
        )
        self.assertEqual(st, "per_asset")
        cap = max(cfg.min_asset_cap_cents, int(balance * cfg.asset_exposure_default_pct * 1.0))
        self.assertGreater(500, cap)


class TestPerAssetExposureSkipLogic(unittest.TestCase):
    """Two-stage per-asset + global cap math (config-driven, no I/O)."""

    def _make_trader_with_balance(self, balance_cents: int):
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader, TraderConfig

        t = KalshiContinuousTrader.__new__(KalshiContinuousTrader)
        t.config = TraderConfig(
            asset_max_exposure_pct={"BTC": 0.20, "ETH": 0.15, "SOL": 0.10, "XRP": 0.10, "DOGE": 0.10},
            asset_exposure_default_pct=0.10,
            series_exposure_multiplier={"15m": 0.40, "1h": 0.70, "daily": 1.00, "weekly": 1.00},
            global_max_exposure_pct=0.40,
            min_asset_cap_cents=50,
        )
        t._balance_cents = balance_cents
        return t

    def _asset_cap(self, t, balance_cents, asset, tf):
        max_pct = t.config.asset_max_exposure_pct.get(asset, t.config.asset_exposure_default_pct)
        mult = t.config.series_exposure_multiplier.get(tf, 1.0)
        return max(t.config.min_asset_cap_cents, int(balance_cents * max_pct * mult))

    def test_btc_at_cap_does_not_block_eth(self):
        balance = 1211
        t = self._make_trader_with_balance(balance)
        btc_cap = self._asset_cap(t, balance, "BTC", "daily")
        eth_cap = self._asset_cap(t, balance, "ETH", "15m")
        self.assertGreater(300, btc_cap, "BTC exposure must exceed BTC daily cap")
        self.assertLess(0 + 9, eth_cap, "ETH/15m candidate fits when ETH exposure is 0")

    def test_btc_at_cap_does_not_block_sol(self):
        balance = 1211
        t = self._make_trader_with_balance(balance)
        sol_cap = self._asset_cap(t, balance, "SOL", "15m")
        self.assertLess(0 + 12, sol_cap, "SOL/15m candidate fits when SOL exposure is 0")

    def test_btc_additional_trade_blocked_when_at_btc_cap(self):
        balance = 1211
        t = self._make_trader_with_balance(balance)
        btc_cap = self._asset_cap(t, balance, "BTC", "daily")
        btc_existing = 300
        cost = 18
        self.assertGreater(btc_existing + cost, btc_cap)
        self.assertEqual(btc_cap, 242)

    def test_eth_at_eth_cap_does_not_block_sol(self):
        balance = 1211
        t = self._make_trader_with_balance(balance)
        eth_cap_15m = self._asset_cap(t, balance, "ETH", "15m")
        sol_cap_15m = self._asset_cap(t, balance, "SOL", "15m")
        eth_existing = eth_cap_15m
        sol_existing = 0
        sol_cost = 12
        self.assertGreater(eth_existing + sol_cost, eth_cap_15m)
        self.assertLessEqual(sol_existing + sol_cost, sol_cap_15m)

    def test_global_cap_blocks_all_when_total_at_ceiling(self):
        balance = 1211
        t = self._make_trader_with_balance(balance)
        global_cap = int(balance * t.config.global_max_exposure_pct)
        total_existing = 484
        cost = 5
        self.assertGreater(total_existing + cost, global_cap)
        self.assertEqual(global_cap, 484)

    def test_small_bankroll_min_cap_floor_allows_micro_trades(self):
        balance = 1000
        t = self._make_trader_with_balance(balance)
        eth_cap = self._asset_cap(t, balance, "ETH", "15m")
        self.assertGreaterEqual(eth_cap, 50)
        self.assertGreater(eth_cap, 5)

    def test_tiny_bankroll_floor_prevents_lockout(self):
        balance = 300
        t = self._make_trader_with_balance(balance)
        sol_cap = self._asset_cap(t, balance, "SOL", "15m")
        self.assertEqual(sol_cap, 50)
        self.assertGreater(sol_cap, 5)


class TestInferAssetTimeframeEdgeCases(unittest.TestCase):
    def test_kx_only_resolves_to_unk_asset(self):
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader

        asset, tf = KalshiContinuousTrader._infer_asset_timeframe("KX")
        self.assertEqual(asset, "UNK")


class TestUnkAssetExposureBehavior(unittest.TestCase):
    """New / unknown series → UNK: warn, default pct for per-asset gate, global still enforced."""

    def test_warn_if_unk_logs_once_for_unk_only(self):
        import unittest.mock
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader, TraderConfig

        t = KalshiContinuousTrader.__new__(KalshiContinuousTrader)
        t.config = TraderConfig()
        with unittest.mock.patch("merid.trading.kalshi_continuous_trader.logger") as log_mock:
            t._warn_if_unk_asset_for_exposure("KXNEW-26JAN01-T1", "KXNEW", "UNK")
            log_mock.warning.assert_called_once()
            log_mock.warning.reset_mock()
            t._warn_if_unk_asset_for_exposure("KXBTC-26JAN01-T1", "KXBTC", "BTC")
            log_mock.warning.assert_not_called()

    def test_unk_per_asset_uses_default_pct(self):
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader, TraderConfig

        cfg = TraderConfig(asset_exposure_default_pct=0.10, min_asset_cap_cents=50)
        balance = 1000
        cap = max(cfg.min_asset_cap_cents, int(balance * cfg.asset_exposure_default_pct * 1.0))
        self.assertEqual(cap, 100)
        st = KalshiContinuousTrader.evaluate_entry_exposure_skip(
            balance, 0, {}, 150, "UNK", "daily", cfg,
        )
        self.assertEqual(st, "per_asset")

    def test_unk_still_blocked_by_global_cap_when_per_asset_allows(self):
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader, TraderConfig

        cfg = TraderConfig(
            asset_max_exposure_pct={"BTC": 0.20, "ETH": 0.15, "SOL": 0.10, "XRP": 0.10, "DOGE": 0.10},
            asset_exposure_default_pct=0.10,
            series_exposure_multiplier={"15m": 0.40, "1h": 0.70, "daily": 1.00, "weekly": 1.00},
            global_max_exposure_pct=0.40,
            min_asset_cap_cents=50,
        )
        balance = 1211
        st = KalshiContinuousTrader.evaluate_entry_exposure_skip(
            balance, 480, {}, 10, "UNK", "daily", cfg,
        )
        self.assertEqual(st, "global")


class TestCalibratedExposureValues(unittest.TestCase):
    """Concrete cap values for typical bankrolls (run with pytest -s to print)."""

    def _show_caps(self, balance_cents: int):
        from merid.trading.kalshi_continuous_trader import TraderConfig

        cfg = TraderConfig()
        bal = balance_cents
        print(f"\n--- Balance: ${bal/100:.2f} ---")
        for asset, pct in cfg.asset_max_exposure_pct.items():
            for tf, mult in cfg.series_exposure_multiplier.items():
                raw = int(bal * pct * mult)
                floor = max(cfg.min_asset_cap_cents, raw)
                print(f"  {asset}/{tf}: raw={raw}¢  floor={floor}¢")
        print(f"  GLOBAL: {int(bal * cfg.global_max_exposure_pct)}¢")

    def test_show_caps_for_12_dollars(self):
        self._show_caps(1211)

    def test_anchor_1211_eth_1h_cap_cents(self):
        """Pinned integer math for $12.11 bankroll (1211¢) per risk calibration doc."""
        from merid.trading.kalshi_continuous_trader import TraderConfig

        cfg = TraderConfig()
        bal = 1211
        raw_eth_1h = int(bal * cfg.asset_max_exposure_pct["ETH"] * cfg.series_exposure_multiplier["1h"])
        self.assertEqual(raw_eth_1h, 254)   # 1211 * 0.30 * 0.70 = 254
        self.assertEqual(int(bal * cfg.global_max_exposure_pct), 605)  # 1211 * 0.50

    def test_show_caps_for_100_dollars(self):
        self._show_caps(10000)

    def test_show_caps_for_1000_dollars(self):
        self._show_caps(100000)


if __name__ == "__main__":
    unittest.main()
