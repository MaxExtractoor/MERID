"""Tests for CFB settlement methodology model and quarantine removal."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch


class TestQuarantinePermanentlyDisabled(unittest.TestCase):
    """Verify the CFB RTI quarantine is permanently disabled."""

    def test_should_quarantine_always_false(self):
        from merid.event_venues.kalshi.cfb_quarantine import should_quarantine_rti_markets
        self.assertFalse(should_quarantine_rti_markets())

    def test_should_quarantine_false_regardless_of_env(self):
        from merid.event_venues.kalshi.cfb_quarantine import should_quarantine_rti_markets
        with patch.dict(os.environ, {"MERID_CFB_RTI_ADAPTER": "null"}, clear=False):
            self.assertFalse(should_quarantine_rti_markets())
        with patch.dict(os.environ, {"MERID_CFB_RTI_ADAPTER": "live"}, clear=False):
            self.assertFalse(should_quarantine_rti_markets())

    def test_evaluate_rti_quarantine_always_none(self):
        from merid.event_venues.kalshi.cfb_quarantine import evaluate_rti_quarantine
        self.assertIsNone(evaluate_rti_quarantine("KXBTC15M-26MAR260730-30"))
        self.assertIsNone(evaluate_rti_quarantine("KXETH-26MAR2608-T2889"))
        self.assertIsNone(evaluate_rti_quarantine("ANYTHING"))

    def test_is_cfb_anchored_market_still_detects_crypto(self):
        """Detection functions preserved for informational tagging."""
        from merid.event_venues.kalshi.cfb_quarantine import is_cfb_anchored_market
        self.assertTrue(is_cfb_anchored_market({"category": "crypto", "ticker": "KXBTC"}))
        self.assertTrue(is_cfb_anchored_market({"rules": "cf benchmarks real-time index"}))
        self.assertFalse(is_cfb_anchored_market({"category": "economics", "ticker": "KXFED"}))

    def test_enforce_cfb_safety_returns_all_markets(self):
        """With quarantine disabled, enforce_cfb_safety must return all markets."""
        from merid.event_venues.kalshi.cfb_quarantine import enforce_cfb_safety
        markets = [
            {"category": "crypto", "ticker": "KXBTC-123"},
            {"category": "crypto", "ticker": "KXETH-456"},
            {"category": "economics", "ticker": "KXFED-789"},
        ]
        result = enforce_cfb_safety(markets)
        self.assertEqual(len(result), 3)

    def test_log_quarantine_status_runs(self):
        from merid.event_venues.kalshi.cfb_quarantine import (
            log_quarantine_status,
            reset_quarantine_log,
        )
        reset_quarantine_log()
        log_quarantine_status()  # should not raise


class TestCFBSettlementModel(unittest.TestCase):
    """Tests for the CF Benchmarks settlement methodology model."""

    def test_supported_assets(self):
        from merid.event_venues.kalshi.cfb_settlement import supported_assets
        assets = supported_assets()
        self.assertEqual(assets, ["BTC", "DOGE", "ETH", "SOL", "XRP"])

    def test_supported_timeframes_btc(self):
        from merid.event_venues.kalshi.cfb_settlement import supported_timeframes_for_asset
        tfs = supported_timeframes_for_asset("BTC")
        self.assertEqual(tfs, ["15m", "1h", "daily", "weekly"])

    def test_supported_timeframes_all_assets_have_four(self):
        from merid.event_venues.kalshi.cfb_settlement import (
            supported_assets,
            supported_timeframes_for_asset,
        )
        for asset in supported_assets():
            tfs = supported_timeframes_for_asset(asset)
            self.assertEqual(len(tfs), 4, f"{asset} should have 4 timeframes, got {tfs}")
            self.assertIn("15m", tfs)
            self.assertIn("1h", tfs)
            self.assertIn("daily", tfs)
            self.assertIn("weekly", tfs)

    def test_get_settlement_params_btc_15m(self):
        from merid.event_venues.kalshi.cfb_settlement import get_settlement_params
        p = get_settlement_params("BTC", "15m")
        self.assertIsNotNone(p)
        self.assertEqual(p.asset, "BTC")
        self.assertEqual(p.cfb_index, "BRTI")
        self.assertEqual(p.settlement_type, "rti_twap")
        self.assertEqual(p.twap_window_seconds, 300)
        self.assertEqual(p.twap_bins, 5)
        self.assertEqual(p.bin_duration_seconds, 60)

    def test_get_settlement_params_eth_daily(self):
        from merid.event_venues.kalshi.cfb_settlement import get_settlement_params
        p = get_settlement_params("ETH", "daily")
        self.assertIsNotNone(p)
        self.assertEqual(p.cfb_index, "ETHUSD_RR")
        self.assertEqual(p.settlement_type, "reference_rate")
        self.assertEqual(p.twap_window_seconds, 1800)
        self.assertEqual(p.twap_bins, 12)
        self.assertEqual(p.bin_duration_seconds, 150)

    def test_get_settlement_params_unknown_returns_none(self):
        from merid.event_venues.kalshi.cfb_settlement import get_settlement_params
        self.assertIsNone(get_settlement_params("BTC", "monthly"))
        self.assertIsNone(get_settlement_params("UNKNOWN", "15m"))

    def test_get_cfb_index(self):
        from merid.event_venues.kalshi.cfb_settlement import get_cfb_index
        self.assertEqual(get_cfb_index("BTC"), "BRTI")
        self.assertEqual(get_cfb_index("ETH"), "ETHUSD_RTI")
        self.assertEqual(get_cfb_index("SOL"), "SOLUSD_RTI")
        self.assertEqual(get_cfb_index("XRP"), "XRPUSD_RTI")
        self.assertEqual(get_cfb_index("DOGE"), "DOGEUSD_RTI")
        self.assertIsNone(get_cfb_index("UNKNOWN"))

    def test_get_cfb_reference_rate(self):
        from merid.event_venues.kalshi.cfb_settlement import get_cfb_reference_rate
        self.assertEqual(get_cfb_reference_rate("BTC"), "BRR")
        self.assertEqual(get_cfb_reference_rate("ETH"), "ETHUSD_RR")

    def test_is_rti_settlement_type(self):
        from merid.event_venues.kalshi.cfb_settlement import is_rti_settlement_type
        self.assertTrue(is_rti_settlement_type("BTC", "15m"))
        self.assertTrue(is_rti_settlement_type("ETH", "1h"))
        self.assertFalse(is_rti_settlement_type("BTC", "daily"))
        self.assertFalse(is_rti_settlement_type("SOL", "weekly"))
        self.assertFalse(is_rti_settlement_type("BTC", "monthly"))

    def test_settlement_guard_seconds_default(self):
        from merid.event_venues.kalshi.cfb_settlement import get_settlement_guard_seconds
        # 15m has tight 30s guard (short-dated contracts), 1h has standard 60s
        self.assertEqual(get_settlement_guard_seconds("BTC", "15m"), 30)
        self.assertEqual(get_settlement_guard_seconds("BTC", "1h"), 60)
        # Unknown asset falls back to per-timeframe default
        self.assertEqual(get_settlement_guard_seconds("UNKNOWN", "1h"), 60)

    def test_all_settlement_params_count(self):
        from merid.event_venues.kalshi.cfb_settlement import all_settlement_params
        params = all_settlement_params()
        # 5 assets × 4 timeframes = 20
        self.assertEqual(len(params), 20)

    def test_bin_duration_computed_correctly(self):
        from merid.event_venues.kalshi.cfb_settlement import all_settlement_params
        for p in all_settlement_params():
            expected = p.twap_window_seconds // p.twap_bins
            self.assertEqual(
                p.bin_duration_seconds, expected,
                f"{p.asset}/{p.timeframe}: bin_duration={p.bin_duration_seconds} != {expected}",
            )

    def test_constituent_exchanges_populated(self):
        from merid.event_venues.kalshi.cfb_settlement import get_settlement_params
        p = get_settlement_params("BTC", "15m")
        self.assertIsInstance(p.constituent_exchanges, tuple)
        self.assertGreater(len(p.constituent_exchanges), 0)
        self.assertIn("coinbase", p.constituent_exchanges)


class TestSeriesMetaUpdates(unittest.TestCase):
    """Tests for updated kalshi_crypto_series_meta.py."""

    def test_monthly_in_timeframe_key(self):
        """TimeframeKey now includes 'monthly'."""
        from config.kalshi_crypto_series_meta import TimeframeKey
        # Literal types — just verify the type annotation exists
        import typing
        args = typing.get_args(TimeframeKey)
        self.assertIn("monthly", args)

    def test_build_kalshi_crypto_products_includes_weekly(self):
        from config.kalshi_crypto_series_meta import build_kalshi_crypto_products
        products = build_kalshi_crypto_products()
        self.assertIn("BTC_WEEKLY", products)
        self.assertIn("ETH_WEEKLY", products)
        self.assertIn("SOL_WEEKLY", products)
        self.assertIn("XRP_WEEKLY", products)
        self.assertIn("DOGE_WEEKLY", products)

    def test_build_kalshi_crypto_products_includes_all_timeframes(self):
        from config.kalshi_crypto_series_meta import build_kalshi_crypto_products
        products = build_kalshi_crypto_products()
        for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            for tf_suffix in ("15M", "1H", "DAILY", "WEEKLY"):
                key = f"{asset}_{tf_suffix}"
                self.assertIn(key, products, f"Missing product key: {key}")

    def test_canonical_timeframe_from_series_weekly(self):
        from config.kalshi_crypto_series_meta import canonical_timeframe_from_series_ticker
        self.assertEqual(canonical_timeframe_from_series_ticker("KXBTCW1"), "weekly")
        self.assertEqual(canonical_timeframe_from_series_ticker("KXETHW1"), "weekly")

    def test_canonical_timeframe_monthly_suffix(self):
        from config.kalshi_crypto_series_meta import canonical_timeframe_from_series_ticker
        self.assertEqual(canonical_timeframe_from_series_ticker("KXBTCM1"), "monthly")


class TestExecutionGateNoRTIBlock(unittest.TestCase):
    """Execution gate must never block on rti_feed after quarantine removal."""

    def test_no_rti_feed_block_in_live_mode(self):
        """Even with KALSHI_ENV=live and no CFB adapter, no rti_feed block."""
        env = {
            "KALSHI_ENV": "live",
            "KALSHI_USE_DEMO": "false",
            "MERID_PM_TRADING_MODE": "live",
            "MERID_PM_LIVE_ENABLED": "true",
            "MERID_CFB_RTI_ADAPTER": "null",
        }
        with patch.dict(os.environ, env, clear=False):
            from core.execution_gate import check_execution_gate
            st = check_execution_gate()
            rti_reasons = [r for r in st.reasons if r.source == "rti_feed"]
            self.assertEqual(
                len(rti_reasons), 0,
                f"Execution gate should not block rti_feed, got: {rti_reasons}",
            )


if __name__ == "__main__":
    unittest.main()
