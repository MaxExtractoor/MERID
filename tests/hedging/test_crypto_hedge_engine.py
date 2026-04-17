"""Comprehensive tests for the CryptoHedgeEngine.

Coverage:
  1. Config loading and parsing
  2. ExposureSnapshot construction
  3. CryptoHedgeEngine deterministic behavior
  4. Hedge order properties (side, count, client_tag)
  5. Adjacent-horizon hedging
  6. Cross-asset hedging (disabled by default)
  7. Integration: order_router.compute_hedge_intents
  8. Integration: CT cycle hedge pass wiring
  9. API endpoint existence
 10. Frontend constant existence
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure repo root on sys.path
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


# ═══════════════════════════════════════════════════════════════════════════
# 1. Config Loading
# ═══════════════════════════════════════════════════════════════════════════


class TestHedgeConfigLoading(unittest.TestCase):
    """Tests for merid.hedging.config."""

    def test_load_from_yaml(self):
        from merid.hedging.config import load_hedge_config

        cfg = load_hedge_config()
        self.assertTrue(cfg.enabled)
        self.assertFalse(cfg.use_cross_asset_hedging)
        self.assertGreater(cfg.max_drawdown_pct, 0)

    def test_asset_slices_present(self):
        from merid.hedging.config import load_hedge_config

        cfg = load_hedge_config()
        for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            self.assertIn(asset, cfg.asset_slices, f"Missing slice for {asset}")

    def test_timeframe_rules_present(self):
        from merid.hedging.config import load_hedge_config

        cfg = load_hedge_config()
        for tf in ("15m", "1h", "daily", "weekly", "monthly"):
            self.assertIn(tf, cfg.timeframes, f"Missing rule for {tf}")

    def test_slice_value_cents(self):
        from merid.hedging.config import load_hedge_config

        cfg = load_hedge_config()
        btc_slice = cfg.slice_value_cents("BTC", 100000)
        self.assertGreater(btc_slice, 0)
        # BTC slice_pct = 0.25 → 25000
        self.assertAlmostEqual(btc_slice, 25000.0)

    def test_max_net_exposure_cents(self):
        from merid.hedging.config import load_hedge_config

        cfg = load_hedge_config()
        # 15m: max_net = 5% of BTC slice (25% of 100k = 25k → 5% = 1250)
        max_net = cfg.max_net_exposure_cents("BTC", "15m", 100000)
        self.assertGreater(max_net, 0)

    def test_missing_file_returns_disabled(self):
        from merid.hedging.config import load_hedge_config

        cfg = load_hedge_config("/nonexistent/path.yaml")
        self.assertFalse(cfg.enabled)

    def test_get_slice_fallback(self):
        from merid.hedging.config import load_hedge_config

        cfg = load_hedge_config()
        # Unknown asset returns default
        s = cfg.get_slice("UNKNOWN_COIN")
        self.assertAlmostEqual(s.slice_pct_of_bankroll, 0.10)

    def test_get_timeframe_rule_fallback(self):
        from merid.hedging.config import load_hedge_config

        cfg = load_hedge_config()
        r = cfg.get_timeframe_rule("5s")  # non-existent
        self.assertAlmostEqual(r.target_hedge_ratio, 0.5)

    def test_cross_asset_disabled_by_default(self):
        from merid.hedging.config import load_hedge_config

        cfg = load_hedge_config()
        self.assertFalse(cfg.cross_asset_enabled)

    def test_cross_asset_pairs_parsed(self):
        from merid.hedging.config import load_hedge_config

        cfg = load_hedge_config()
        self.assertGreater(len(cfg.cross_asset_pairs), 0)
        self.assertEqual(cfg.cross_asset_pairs[0].base, "BTC")
        self.assertEqual(cfg.cross_asset_pairs[0].hedge, "ETH")

    def test_frozen_config(self):
        from merid.hedging.config import load_hedge_config

        cfg = load_hedge_config()
        with self.assertRaises(Exception):
            cfg.enabled = False  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════
# 2. ExposureSnapshot
# ═══════════════════════════════════════════════════════════════════════════


class TestExposureSnapshot(unittest.TestCase):
    """Tests for merid.hedging.exposure."""

    def test_empty_snapshot(self):
        from merid.hedging.exposure import ExposureSnapshot

        snap = ExposureSnapshot()
        self.assertEqual(snap.net_delta_cents("BTC", "1h"), 0)
        self.assertEqual(len(snap.all_asset_timeframes()), 0)

    def test_cell_exposure_math(self):
        from merid.hedging.exposure import CellExposure

        cell = CellExposure(
            asset="BTC",
            timeframe="1h",
            yes_notional_cents=5000,
            no_notional_cents=2000,
            yes_contracts=10,
            no_contracts=4,
        )
        self.assertEqual(cell.net_delta_cents, 3000)  # 5000 - 2000
        self.assertEqual(cell.gross_cents, 7000)

    def test_cell_with_pending(self):
        from merid.hedging.exposure import CellExposure

        cell = CellExposure(
            asset="ETH",
            timeframe="15m",
            yes_notional_cents=1000,
            no_notional_cents=500,
            pending_yes_cents=200,
            pending_no_cents=100,
        )
        # net = (1000+200) - (500+100) = 600
        self.assertEqual(cell.net_delta_cents, 600)

    def test_get_cell_creates_on_access(self):
        from merid.hedging.exposure import ExposureSnapshot

        snap = ExposureSnapshot()
        cell = snap.get_cell("SOL", "daily")
        self.assertEqual(cell.asset, "SOL")
        self.assertEqual(cell.timeframe, "daily")
        self.assertEqual(cell.net_delta_cents, 0)

    def test_all_asset_timeframes_non_empty(self):
        from merid.hedging.exposure import ExposureSnapshot

        snap = ExposureSnapshot()
        cell = snap.get_cell("BTC", "1h")
        cell.yes_notional_cents = 100
        atfs = snap.all_asset_timeframes()
        self.assertIn(("BTC", "1h"), atfs)

    def test_build_exposure_snapshot_graceful(self):
        """build_exposure_snapshot should return empty snapshot even if no infra."""
        from merid.hedging.exposure import build_exposure_snapshot

        snap = build_exposure_snapshot()
        # Should not crash — returns empty if position_cache unavailable
        self.assertIsNotNone(snap)


# ═══════════════════════════════════════════════════════════════════════════
# 3. CryptoHedgeEngine — Core Determinism
# ═══════════════════════════════════════════════════════════════════════════


class TestCryptoHedgeEngineDeterminism(unittest.TestCase):
    """Same inputs must produce identical outputs."""

    def _make_config(self):
        from merid.hedging.config import (
            AssetSliceConfig,
            HedgeConfig,
            TimeframeHedgeRule,
        )

        return HedgeConfig(
            enabled=True,
            asset_slices={
                "BTC": AssetSliceConfig(slice_pct_of_bankroll=0.25),
                "ETH": AssetSliceConfig(slice_pct_of_bankroll=0.25),
                "SOL": AssetSliceConfig(slice_pct_of_bankroll=0.10),
                "XRP": AssetSliceConfig(slice_pct_of_bankroll=0.10),
                "DOGE": AssetSliceConfig(slice_pct_of_bankroll=0.10),
            },
            timeframes={
                "1h": TimeframeHedgeRule(
                    max_net_exposure_pct_of_slice=7.5,
                    target_hedge_ratio=0.5,
                ),
            },
        )

    def _make_exposure(self, asset="BTC", tf="1h", yes=5000, no=1000):
        from merid.hedging.exposure import ExposureSnapshot

        snap = ExposureSnapshot()
        cell = snap.get_cell(asset, tf)
        cell.yes_notional_cents = yes
        cell.no_notional_cents = no
        return snap

    def test_same_inputs_same_outputs(self):
        from merid.hedging.engine import CryptoHedgeEngine

        engine = CryptoHedgeEngine()
        cfg = self._make_config()
        snap = self._make_exposure()

        r1 = engine.compute_hedge_orders(snap, cfg, bankroll_cents=100000)
        r2 = engine.compute_hedge_orders(snap, cfg, bankroll_cents=100000)
        self.assertEqual(len(r1.orders), len(r2.orders))
        for o1, o2 in zip(r1.orders, r2.orders):
            self.assertEqual(o1.asset, o2.asset)
            self.assertEqual(o1.side, o2.side)
            self.assertEqual(o1.count, o2.count)

    def test_no_exposure_no_orders(self):
        from merid.hedging.engine import CryptoHedgeEngine
        from merid.hedging.exposure import ExposureSnapshot

        engine = CryptoHedgeEngine()
        cfg = self._make_config()
        snap = ExposureSnapshot()

        result = engine.compute_hedge_orders(snap, cfg, bankroll_cents=100000)
        self.assertEqual(len(result.orders), 0)

    def test_disabled_config_no_orders(self):
        from merid.hedging.config import HedgeConfig
        from merid.hedging.engine import CryptoHedgeEngine

        engine = CryptoHedgeEngine()
        cfg = HedgeConfig(enabled=False)
        snap = self._make_exposure()

        result = engine.compute_hedge_orders(snap, cfg, bankroll_cents=100000)
        self.assertEqual(len(result.orders), 0)

    def test_zero_bankroll_no_orders(self):
        from merid.hedging.engine import CryptoHedgeEngine

        engine = CryptoHedgeEngine()
        cfg = self._make_config()
        snap = self._make_exposure()

        result = engine.compute_hedge_orders(snap, cfg, bankroll_cents=0)
        self.assertEqual(len(result.orders), 0)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Hedge Order Properties
# ═══════════════════════════════════════════════════════════════════════════


class TestHedgeOrderProperties(unittest.TestCase):
    """Verify hedge order side, action, client_tag, source."""

    def _make_config(self):
        from merid.hedging.config import (
            AssetSliceConfig,
            HedgeConfig,
            TimeframeHedgeRule,
        )

        return HedgeConfig(
            enabled=True,
            asset_slices={
                "BTC": AssetSliceConfig(slice_pct_of_bankroll=0.25),
                "ETH": AssetSliceConfig(slice_pct_of_bankroll=0.25),
                "SOL": AssetSliceConfig(slice_pct_of_bankroll=0.10),
                "XRP": AssetSliceConfig(slice_pct_of_bankroll=0.10),
                "DOGE": AssetSliceConfig(slice_pct_of_bankroll=0.10),
            },
            timeframes={
                "1h": TimeframeHedgeRule(
                    max_net_exposure_pct_of_slice=7.5,
                    target_hedge_ratio=0.5,
                ),
            },
        )

    def test_long_exposure_hedges_with_no_side(self):
        """Net YES (long) → hedge by buying NO."""
        from merid.hedging.engine import CryptoHedgeEngine
        from merid.hedging.exposure import ExposureSnapshot

        engine = CryptoHedgeEngine()
        cfg = self._make_config()
        snap = ExposureSnapshot()
        cell = snap.get_cell("BTC", "1h")
        cell.yes_notional_cents = 10000
        cell.no_notional_cents = 0  # heavily long

        result = engine.compute_hedge_orders(snap, cfg, bankroll_cents=100000)
        # Should produce hedge orders for BTC:1h
        btc_orders = [o for o in result.orders if o.asset == "BTC" and o.timeframe == "1h"]
        self.assertGreater(len(btc_orders), 0)
        self.assertEqual(btc_orders[0].side, "no")  # hedge long by buying NO

    def test_short_exposure_hedges_with_yes_side(self):
        """Net NO (short) → hedge by buying YES."""
        from merid.hedging.engine import CryptoHedgeEngine
        from merid.hedging.exposure import ExposureSnapshot

        engine = CryptoHedgeEngine()
        cfg = self._make_config()
        snap = ExposureSnapshot()
        cell = snap.get_cell("BTC", "1h")
        cell.yes_notional_cents = 0
        cell.no_notional_cents = 10000  # heavily short

        result = engine.compute_hedge_orders(snap, cfg, bankroll_cents=100000)
        btc_orders = [o for o in result.orders if o.asset == "BTC" and o.timeframe == "1h"]
        self.assertGreater(len(btc_orders), 0)
        self.assertEqual(btc_orders[0].side, "yes")  # hedge short by buying YES

    def test_all_orders_buy_action(self):
        """Hedge orders are always buy (opening a new position on opposite side)."""
        from merid.hedging.engine import CryptoHedgeEngine
        from merid.hedging.exposure import ExposureSnapshot

        engine = CryptoHedgeEngine()
        cfg = self._make_config()
        snap = ExposureSnapshot()
        cell = snap.get_cell("BTC", "1h")
        cell.yes_notional_cents = 5000

        result = engine.compute_hedge_orders(snap, cfg, bankroll_cents=100000)
        for o in result.orders:
            self.assertEqual(o.action, "buy")

    def test_client_tag_prefix(self):
        """All hedge orders have HEDGE_ prefixed client_tag."""
        from merid.hedging.engine import CryptoHedgeEngine, HEDGE_CLIENT_TAG_PREFIX
        from merid.hedging.exposure import ExposureSnapshot

        engine = CryptoHedgeEngine()
        cfg = self._make_config()
        snap = ExposureSnapshot()
        cell = snap.get_cell("ETH", "1h")
        cell.yes_notional_cents = 8000

        result = engine.compute_hedge_orders(snap, cfg, bankroll_cents=100000)
        for o in result.orders:
            if o.asset == "ETH":
                self.assertTrue(
                    o.client_tag.startswith(HEDGE_CLIENT_TAG_PREFIX),
                    f"Expected HEDGE_ prefix, got: {o.client_tag}",
                )

    def test_hedge_count_positive(self):
        from merid.hedging.engine import CryptoHedgeEngine
        from merid.hedging.exposure import ExposureSnapshot

        engine = CryptoHedgeEngine()
        cfg = self._make_config()
        snap = ExposureSnapshot()
        cell = snap.get_cell("SOL", "1h")
        cell.yes_notional_cents = 3000

        result = engine.compute_hedge_orders(snap, cfg, bankroll_cents=100000)
        for o in result.orders:
            self.assertGreater(o.count, 0)


# ═══════════════════════════════════════════════════════════════════════════
# 5. Adjacent Horizon Hedging
# ═══════════════════════════════════════════════════════════════════════════


class TestAdjacentHorizonHedging(unittest.TestCase):
    """Verify adjacent-horizon spill when same-TF cap is breached."""

    def test_adjacent_horizon_generated(self):
        from merid.hedging.config import (
            AssetSliceConfig,
            HedgeConfig,
            TimeframeHedgeRule,
        )
        from merid.hedging.engine import CryptoHedgeEngine
        from merid.hedging.exposure import ExposureSnapshot

        cfg = HedgeConfig(
            enabled=True,
            asset_slices={
                "BTC": AssetSliceConfig(slice_pct_of_bankroll=0.25),
                "ETH": AssetSliceConfig(slice_pct_of_bankroll=0.25),
                "SOL": AssetSliceConfig(slice_pct_of_bankroll=0.10),
                "XRP": AssetSliceConfig(slice_pct_of_bankroll=0.10),
                "DOGE": AssetSliceConfig(slice_pct_of_bankroll=0.10),
            },
            timeframes={
                "1h": TimeframeHedgeRule(
                    max_net_exposure_pct_of_slice=7.5,
                    target_hedge_ratio=0.5,
                    allow_adjacent_horizons=("15m", "daily"),
                ),
                "15m": TimeframeHedgeRule(
                    max_net_exposure_pct_of_slice=5.0,
                    target_hedge_ratio=0.5,
                ),
                "daily": TimeframeHedgeRule(
                    max_net_exposure_pct_of_slice=10.0,
                    target_hedge_ratio=1.0,
                ),
            },
        )
        snap = ExposureSnapshot()
        cell = snap.get_cell("BTC", "1h")
        # Very heavy exposure — exceed max_net to trigger adjacent
        cell.yes_notional_cents = 50000

        engine = CryptoHedgeEngine()
        result = engine.compute_hedge_orders(snap, cfg, bankroll_cents=100000)

        # Should have primary 1h hedge + adjacent horizon hedge
        btc_1h = [o for o in result.orders if o.asset == "BTC" and o.timeframe == "1h"]
        btc_adj = [o for o in result.orders if o.asset == "BTC" and o.timeframe in ("15m", "daily")]
        self.assertGreater(len(btc_1h), 0)
        self.assertGreater(len(btc_adj), 0, "Expected adjacent-horizon hedge order")
        # Adjacent should have reason "same_asset_nearby_horizon"
        for o in btc_adj:
            self.assertEqual(o.hedge_reason, "same_asset_nearby_horizon")


# ═══════════════════════════════════════════════════════════════════════════
# 6. OrderIntent Conversion
# ═══════════════════════════════════════════════════════════════════════════


class TestOrderIntentConversion(unittest.TestCase):
    """CryptoHedgeEngine.to_order_intents() produces valid OrderIntent objects."""

    def test_to_order_intents(self):
        from merid.hedging.engine import (
            CryptoHedgeEngine,
            HedgeOrder,
            HedgeResult,
            HEDGE_AGENT_ID,
            HEDGE_SOURCE,
            HEDGE_STRATEGY_GROUP,
        )

        engine = CryptoHedgeEngine()
        result = HedgeResult(orders=[
            HedgeOrder(
                asset="BTC",
                timeframe="1h",
                side="no",
                action="buy",
                price_cents=50,
                count=5,
                hedge_reason="same_asset_same_horizon",
                target_ticker="KXBTC-TEST",
                client_tag="HEDGE_BTC_1h_abc123",
            ),
        ])
        intents = engine.to_order_intents(result)
        self.assertEqual(len(intents), 1)
        intent = intents[0]
        self.assertEqual(intent.ticker, "KXBTC-TEST")
        self.assertEqual(intent.side, "no")
        self.assertEqual(intent.action, "buy")
        self.assertEqual(intent.count, 5)
        self.assertEqual(intent.source, HEDGE_SOURCE)
        self.assertEqual(intent.agent_id, HEDGE_AGENT_ID)
        self.assertEqual(intent.group_id, HEDGE_STRATEGY_GROUP)
        self.assertTrue(intent.client_tag.startswith("HEDGE_"))


# ═══════════════════════════════════════════════════════════════════════════
# 7. Metrics
# ═══════════════════════════════════════════════════════════════════════════


class TestHedgeEngineMetrics(unittest.TestCase):
    """Verify metrics tracking."""

    def test_metrics_increment(self):
        from merid.hedging.config import (
            AssetSliceConfig,
            HedgeConfig,
            TimeframeHedgeRule,
        )
        from merid.hedging.engine import CryptoHedgeEngine
        from merid.hedging.exposure import ExposureSnapshot

        engine = CryptoHedgeEngine()
        cfg = HedgeConfig(
            enabled=True,
            asset_slices={
                "BTC": AssetSliceConfig(slice_pct_of_bankroll=0.25),
                "ETH": AssetSliceConfig(slice_pct_of_bankroll=0.25),
                "SOL": AssetSliceConfig(slice_pct_of_bankroll=0.10),
                "XRP": AssetSliceConfig(slice_pct_of_bankroll=0.10),
                "DOGE": AssetSliceConfig(slice_pct_of_bankroll=0.10),
            },
            timeframes={
                "1h": TimeframeHedgeRule(
                    max_net_exposure_pct_of_slice=7.5,
                    target_hedge_ratio=0.5,
                ),
            },
        )
        snap = ExposureSnapshot()
        cell = snap.get_cell("BTC", "1h")
        cell.yes_notional_cents = 5000

        m_before = engine.metrics()
        engine.compute_hedge_orders(snap, cfg, bankroll_cents=100000)
        m_after = engine.metrics()
        self.assertEqual(m_after["total_calls"], m_before["total_calls"] + 1)


# ═══════════════════════════════════════════════════════════════════════════
# 8. Integration: compute_hedge_intents in order_router
# ═══════════════════════════════════════════════════════════════════════════


class TestComputeHedgeIntentsRouter(unittest.TestCase):
    """order_router.compute_hedge_intents() end-to-end."""

    def test_function_exists(self):
        from merid.event_venues.kalshi.order_router import compute_hedge_intents
        self.assertTrue(callable(compute_hedge_intents))

    def test_returns_list(self):
        from merid.event_venues.kalshi.order_router import compute_hedge_intents
        result = compute_hedge_intents(bankroll_cents=100000)
        self.assertIsInstance(result, list)

    def test_empty_when_disabled(self):
        from merid.hedging.config import HedgeConfig, _reset_hedge_config

        _reset_hedge_config()
        # Temporarily patch to return disabled
        with patch("merid.hedging.config.load_hedge_config", return_value=HedgeConfig(enabled=False)):
            _reset_hedge_config()
            from merid.hedging.config import get_hedge_config
            # Force reload
            from merid.event_venues.kalshi.order_router import compute_hedge_intents
            result = compute_hedge_intents(bankroll_cents=100000)
            self.assertEqual(len(result), 0)
        _reset_hedge_config()


# ═══════════════════════════════════════════════════════════════════════════
# 9. CT Cycle Wiring
# ═══════════════════════════════════════════════════════════════════════════


class TestCTCycleWiring(unittest.TestCase):
    """Verify hedge engine is wired into kalshi_continuous_trader."""

    def test_hedge_pass_present_in_ct(self):
        """_run_cycle_inner should contain the hedge pass block."""
        import inspect
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader

        src = inspect.getsource(KalshiContinuousTrader._run_cycle_inner)
        self.assertIn("HEDGE-PASS", src)
        self.assertIn("get_hedge_engine", src)
        self.assertIn("build_exposure_snapshot", src)


# ═══════════════════════════════════════════════════════════════════════════
# 10. API Endpoint
# ═══════════════════════════════════════════════════════════════════════════


class TestHedgeMetricsApi(unittest.TestCase):
    """Verify hedge metrics endpoint exists."""

    def test_endpoint_file_has_route(self):
        src = Path(_REPO / "web" / "api" / "kalshi_metrics_api.py").read_text()
        self.assertIn("/hedge", src)
        self.assertIn("get_hedge_metrics", src)

    def test_handler_importable(self):
        from web.api.kalshi_metrics_api import get_hedge_metrics
        self.assertTrue(callable(get_hedge_metrics))


# ═══════════════════════════════════════════════════════════════════════════
# 11. Frontend Constant
# ═══════════════════════════════════════════════════════════════════════════


class TestFrontendConstant(unittest.TestCase):
    """Verify KALSHI_METRICS_HEDGE constant exists."""

    def test_constant_in_file(self):
        path = _REPO / "web" / "react" / "src" / "config" / "constants.ts"
        src = path.read_text()
        self.assertIn("KALSHI_METRICS_HEDGE", src)
        self.assertIn("/api/v1/kalshi/metrics/hedge", src)


# ═══════════════════════════════════════════════════════════════════════════
# 12. Module Structure
# ═══════════════════════════════════════════════════════════════════════════


class TestModuleStructure(unittest.TestCase):
    """Verify package exports and singleton patterns."""

    def test_init_exports(self):
        import merid.hedging

        self.assertTrue(hasattr(merid.hedging, "HedgeConfig"))
        self.assertTrue(hasattr(merid.hedging, "CryptoHedgeEngine"))
        self.assertTrue(hasattr(merid.hedging, "get_hedge_config"))
        self.assertTrue(hasattr(merid.hedging, "get_hedge_engine"))

    def test_engine_singleton(self):
        from merid.hedging.engine import get_hedge_engine

        a = get_hedge_engine()
        b = get_hedge_engine()
        self.assertIs(a, b)

    def test_config_singleton(self):
        from merid.hedging.config import get_hedge_config

        a = get_hedge_config()
        b = get_hedge_config()
        self.assertIs(a, b)

    def test_yaml_file_exists(self):
        path = _REPO / "config" / "kalshi_crypto_hedging.yaml"
        self.assertTrue(path.exists(), f"Missing: {path}")

    def test_exposure_module_importable(self):
        from merid.hedging.exposure import ExposureSnapshot, CellExposure, build_exposure_snapshot
        self.assertTrue(callable(build_exposure_snapshot))


# ═══════════════════════════════════════════════════════════════════════════
# 13. Deterministic Client Tag
# ═══════════════════════════════════════════════════════════════════════════


class TestDeterministicClientTag(unittest.TestCase):
    """Client tags must be deterministic within the same 60s bucket."""

    def test_same_bucket_same_tag(self):
        from merid.hedging.engine import CryptoHedgeEngine

        tag1 = CryptoHedgeEngine._deterministic_tag("BTC", "1h", "no", 5, 50)
        tag2 = CryptoHedgeEngine._deterministic_tag("BTC", "1h", "no", 5, 50)
        self.assertEqual(tag1, tag2)

    def test_different_side_different_tag(self):
        from merid.hedging.engine import CryptoHedgeEngine

        tag_no = CryptoHedgeEngine._deterministic_tag("BTC", "1h", "no", 5, 50)
        tag_yes = CryptoHedgeEngine._deterministic_tag("BTC", "1h", "yes", 5, 50)
        self.assertNotEqual(tag_no, tag_yes)

    def test_different_asset_different_tag(self):
        from merid.hedging.engine import CryptoHedgeEngine

        tag_btc = CryptoHedgeEngine._deterministic_tag("BTC", "1h", "no", 5, 50)
        tag_eth = CryptoHedgeEngine._deterministic_tag("ETH", "1h", "no", 5, 50)
        self.assertNotEqual(tag_btc, tag_eth)

    def test_different_count_different_tag(self):
        from merid.hedging.engine import CryptoHedgeEngine

        tag_5 = CryptoHedgeEngine._deterministic_tag("BTC", "1h", "no", 5, 50)
        tag_10 = CryptoHedgeEngine._deterministic_tag("BTC", "1h", "no", 10, 50)
        self.assertNotEqual(tag_5, tag_10)

    def test_hedge_prefix(self):
        from merid.hedging.engine import CryptoHedgeEngine, HEDGE_CLIENT_TAG_PREFIX

        tag = CryptoHedgeEngine._deterministic_tag("BTC", "1h", "no", 5, 50)
        self.assertTrue(tag.startswith(HEDGE_CLIENT_TAG_PREFIX))


# ═══════════════════════════════════════════════════════════════════════════
# 14. No Double Hedging Invariant
# ═══════════════════════════════════════════════════════════════════════════


class TestNoDoubleHedging(unittest.TestCase):
    """Same exposure computed twice must produce identical (dedup-able) orders."""

    def test_dedup_by_client_tag(self):
        from merid.hedging.config import (
            AssetSliceConfig,
            HedgeConfig,
            TimeframeHedgeRule,
        )
        from merid.hedging.engine import CryptoHedgeEngine
        from merid.hedging.exposure import ExposureSnapshot

        engine = CryptoHedgeEngine()
        cfg = HedgeConfig(
            enabled=True,
            asset_slices={
                "BTC": AssetSliceConfig(slice_pct_of_bankroll=0.25),
                "ETH": AssetSliceConfig(slice_pct_of_bankroll=0.25),
                "SOL": AssetSliceConfig(slice_pct_of_bankroll=0.10),
                "XRP": AssetSliceConfig(slice_pct_of_bankroll=0.10),
                "DOGE": AssetSliceConfig(slice_pct_of_bankroll=0.10),
            },
            timeframes={
                "1h": TimeframeHedgeRule(
                    max_net_exposure_pct_of_slice=7.5,
                    target_hedge_ratio=0.5,
                ),
            },
        )
        snap = ExposureSnapshot()
        cell = snap.get_cell("BTC", "1h")
        cell.yes_notional_cents = 5000

        r1 = engine.compute_hedge_orders(snap, cfg, bankroll_cents=100000)
        r2 = engine.compute_hedge_orders(snap, cfg, bankroll_cents=100000)

        tags_1 = {o.client_tag for o in r1.orders}
        tags_2 = {o.client_tag for o in r2.orders}
        # Same tags → downstream dedup gate will block the second set
        self.assertEqual(tags_1, tags_2)


# ═══════════════════════════════════════════════════════════════════════════
# 15. Hedge Reduces Exposure Invariant
# ═══════════════════════════════════════════════════════════════════════════


class TestHedgeReducesExposure(unittest.TestCase):
    """Hedge orders must reduce net directional exposure, not increase it."""

    def test_long_hedge_reduces_net(self):
        from merid.hedging.config import (
            AssetSliceConfig,
            HedgeConfig,
            TimeframeHedgeRule,
        )
        from merid.hedging.engine import CryptoHedgeEngine
        from merid.hedging.exposure import ExposureSnapshot

        engine = CryptoHedgeEngine()
        cfg = HedgeConfig(
            enabled=True,
            asset_slices={
                "BTC": AssetSliceConfig(slice_pct_of_bankroll=0.25),
                "ETH": AssetSliceConfig(slice_pct_of_bankroll=0.25),
                "SOL": AssetSliceConfig(slice_pct_of_bankroll=0.10),
                "XRP": AssetSliceConfig(slice_pct_of_bankroll=0.10),
                "DOGE": AssetSliceConfig(slice_pct_of_bankroll=0.10),
            },
            timeframes={
                "1h": TimeframeHedgeRule(
                    max_net_exposure_pct_of_slice=7.5,
                    target_hedge_ratio=0.5,
                ),
            },
        )
        snap = ExposureSnapshot()
        cell = snap.get_cell("BTC", "1h")
        cell.yes_notional_cents = 10000  # net long

        result = engine.compute_hedge_orders(snap, cfg, bankroll_cents=100000)
        btc_1h = [o for o in result.orders if o.asset == "BTC" and o.timeframe == "1h"]

        for o in btc_1h:
            # Long exposure → hedge side should be "no" (opposing)
            self.assertEqual(o.side, "no")
            # Simulated effect: hedge notional ≤ net exposure
            hedge_notional = o.count * o.price_cents
            self.assertLessEqual(hedge_notional, cell.yes_notional_cents)


if __name__ == "__main__":
    unittest.main()
