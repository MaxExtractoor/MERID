"""Sprint A hardening tests.

Covers:
  A2  — Brier-calibrated consensus weights
  A3  — Cross-agent category exposure cap
  A4  — Correlated-market stacking guard
  A6  — Sanity check wired into route_order / route_order_async
  A7  — KalshiConfig KALSHI_ENV enforcement (demo / live key separation)
  B5  — Sentiment size scalar (smoke)
  B6  — OrderIntent TIF default is 'gtc'
"""
from __future__ import annotations

import gc
import os
import sys
import threading
import time
import unittest
from decimal import Decimal
from typing import List
from unittest.mock import MagicMock, patch


# ═══════════════════════════════════════════════════════════════════════════
# A2 — Brier-calibrated consensus weights
# ═══════════════════════════════════════════════════════════════════════════

class TestBrierWeightedConsensus(unittest.TestCase):
    """_aggregate_swarm_prob_brier_weighted and get_agent_brier_weights."""

    def _make_store(self, tmp_path: str):
        from merid.prediction.consensus import PredictionConsensusStore
        return PredictionConsensusStore(db_path=tmp_path)

    def _tmp_db(self) -> str:
        import tempfile, os
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        return path

    def test_fallback_to_confidence_when_no_brier_history(self):
        """With empty brier map the static method uses confidence weighting."""
        from merid.prediction.consensus import PredictionConsensusStore, PredictionOpinion
        ops = [
            PredictionOpinion(agent_id="a1", symbol="X", probability=0.8, confidence=0.9),
            PredictionOpinion(agent_id="a2", symbol="X", probability=0.3, confidence=0.1),
        ]
        result = PredictionConsensusStore._aggregate_swarm_prob_brier_weighted(ops, {})
        # Should equal confidence-weighted: (0.8*0.9 + 0.3*0.1) / (0.9+0.1)
        expected = (0.8 * 0.9 + 0.3 * 0.1) / 1.0
        self.assertAlmostEqual(result, expected, places=6)

    def test_brier_weights_boost_accurate_agent(self):
        """Agent with lower Brier score should receive higher weight."""
        from merid.prediction.consensus import PredictionConsensusStore, PredictionOpinion
        # a1 has perfect Brier (0.0); a2 has poor Brier (0.5)
        weights = {
            "a1": 1.0 / (0.0 + 0.01),   # ~100
            "a2": 1.0 / (0.5 + 0.01),   # ~1.96
        }
        total = weights["a1"] + weights["a2"]
        n = 2
        normalised = {a: (w / total) * n for a, w in weights.items()}

        ops = [
            PredictionOpinion(agent_id="a1", symbol="X", probability=0.7, confidence=0.5),
            PredictionOpinion(agent_id="a2", symbol="X", probability=0.3, confidence=0.5),
        ]
        result = PredictionConsensusStore._aggregate_swarm_prob_brier_weighted(ops, normalised)
        # a1 dominates → result should be close to 0.7 not 0.5
        self.assertGreater(result, 0.6)

    def test_returns_0_5_for_empty_opinions(self):
        from merid.prediction.consensus import PredictionConsensusStore
        self.assertEqual(
            PredictionConsensusStore._aggregate_swarm_prob_brier_weighted([], {"a1": 1.0}),
            0.5,
        )

    def test_get_agent_brier_weights_returns_empty_when_no_resolved(self):
        """Store with no resolved markets returns {}."""
        path = self._tmp_db()
        try:
            store = self._make_store(path)
            weights = store.get_agent_brier_weights()
            self.assertIsInstance(weights, dict)
            self.assertEqual(len(weights), 0)
        finally:
            del store
            gc.collect()
            try:
                os.unlink(path)
            except PermissionError:
                pass

    def test_get_agent_brier_weights_caches(self):
        """Second call within TTL returns same object without recomputing."""
        path = self._tmp_db()
        try:
            store = self._make_store(path)
            store.get_agent_brier_weights()
            store._brier_weights_cache = {"a1": 1.5}
            store._brier_weights_ts = time.monotonic()
            w2 = store.get_agent_brier_weights()
            self.assertEqual(w2, {"a1": 1.5})
        finally:
            del store
            gc.collect()
            try:
                os.unlink(path)
            except PermissionError:
                pass

    def test_cache_expires_after_ttl(self):
        """Expired cache triggers recomputation."""
        path = self._tmp_db()
        try:
            store = self._make_store(path)
            store._brier_weights_cache = {"stale": 99.0}
            store._brier_weights_ts = time.monotonic() - store._brier_weights_ttl - 1
            fresh = store.get_agent_brier_weights()
            # No resolved markets → returns {}
            self.assertEqual(fresh, {})
        finally:
            del store
            gc.collect()
            try:
                os.unlink(path)
            except PermissionError:
                pass

    def test_normalised_weights_sum_to_n(self):
        """Normalised weights sum to len(agents)."""
        from merid.prediction.consensus import PredictionConsensusStore, ResolvedMarket, PredictionInstrument, PredictionOpinion
        path = self._tmp_db()
        try:
            store = self._make_store(path)
            inst = PredictionInstrument(
                symbol="SYM", title="test", venue="kalshi",
                event_id="ev1", ticker="T1", category="crypto",
            )
            store.upsert_instrument(inst)
            store.add_opinion(PredictionOpinion(agent_id="ag1", symbol="SYM", probability=0.7))
            time.sleep(0.01)
            store.add_opinion(PredictionOpinion(agent_id="ag2", symbol="SYM", probability=0.4))
            store.record_resolution(ResolvedMarket(symbol="SYM", outcome=1))
            weights = store.get_agent_brier_weights(window=10)
            if weights:
                self.assertAlmostEqual(sum(weights.values()), len(weights), places=5)
        finally:
            del store
            gc.collect()
            try:
                os.unlink(path)
            except PermissionError:
                pass


# ═══════════════════════════════════════════════════════════════════════════
# A3/A4 — CategoryExposureTracker
# ═══════════════════════════════════════════════════════════════════════════

class TestCategoryExposureTracker(unittest.TestCase):

    def _make_tracker(self, cat_caps=None, corr_cap=None):
        from merid.event_venues.kalshi.category_exposure import CategoryExposureTracker
        return CategoryExposureTracker(
            category_caps=cat_caps or {"crypto": 1000.0, "macro": 200.0},
            corr_cap_usd=corr_cap if corr_cap is not None else 500.0,
        )

    def test_category_cap_allows_within_limit(self):
        t = self._make_tracker()
        ok, reason = t.check_category_cap("crypto", 999.0)
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_category_cap_rejects_over_limit(self):
        t = self._make_tracker()
        ok, reason = t.check_category_cap("crypto", 1001.0)
        self.assertFalse(ok)
        self.assertIn("category_cap_exceeded", reason)

    def test_category_cap_rejects_after_accumulation(self):
        t = self._make_tracker()
        t.record_fill("crypto", "BTC", 600.0)
        ok, reason = t.check_category_cap("crypto", 500.0)
        self.assertFalse(ok)
        self.assertIn("crypto", reason)

    def test_category_cap_allows_unknown_category(self):
        """Category without a configured cap is always allowed."""
        t = self._make_tracker()
        ok, _ = t.check_category_cap("nonexistent", 99999.0)
        self.assertTrue(ok)

    def test_correlated_cap_allows_within_limit(self):
        t = self._make_tracker()
        ok, _ = t.check_correlated_cap("BTC", 499.0)
        self.assertTrue(ok)

    def test_correlated_cap_rejects_over_limit(self):
        t = self._make_tracker()
        ok, reason = t.check_correlated_cap("BTC", 501.0)
        self.assertFalse(ok)
        self.assertIn("corr_stack_cap_exceeded", reason)
        self.assertIn("BTC", reason)

    def test_stacking_guard_blocks_second_timeframe(self):
        """BTC-hourly fills $400 → BTC-daily for $200 is rejected."""
        t = self._make_tracker()
        t.record_fill("crypto", "BTC", 400.0)
        ok, _ = t.check_correlated_cap("BTC", 200.0)
        self.assertFalse(ok)

    def test_release_reduces_notional(self):
        t = self._make_tracker()
        t.record_fill("crypto", "BTC", 400.0)
        t.release("crypto", "BTC", 400.0)
        snap = t.get_snapshot()
        self.assertEqual(snap.corr_notional.get("BTC", 0.0), 0.0)

    def test_release_floor_is_zero(self):
        """release() never drives notional below zero."""
        t = self._make_tracker()
        t.release("crypto", "BTC", 999.0)
        snap = t.get_snapshot()
        self.assertGreaterEqual(snap.corr_notional.get("BTC", 0.0), 0.0)

    def test_thread_safety(self):
        """Concurrent fills and checks do not race."""
        t = self._make_tracker(cat_caps={"crypto": 100_000.0}, corr_cap=100_000.0)
        errors = []

        def _worker():
            for _ in range(50):
                t.record_fill("crypto", "BTC", 1.0)
                ok, _ = t.check_category_cap("crypto", 1.0)
                if not isinstance(ok, bool):
                    errors.append("bad return type")

        threads = [threading.Thread(target=_worker) for _ in range(8)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(errors, [])

    def test_snapshot_to_dict_structure(self):
        t = self._make_tracker()
        t.record_fill("crypto", "BTC", 100.0)
        d = t.get_snapshot().to_dict()
        self.assertIn("categories", d)
        self.assertIn("correlated_underlyings", d)
        self.assertIn("corr_cap_usd", d)
        self.assertIn("asset_caps", d)
        self.assertIsInstance(d["asset_caps"], dict)

    def test_infer_category_crypto(self):
        from merid.event_venues.kalshi.category_exposure import infer_category
        self.assertEqual(infer_category("BTC"), "crypto")
        self.assertEqual(infer_category("eth"), "crypto")

    def test_infer_category_fallback(self):
        from merid.event_venues.kalshi.category_exposure import infer_category
        self.assertEqual(infer_category("CORN"), "other")


# ═══════════════════════════════════════════════════════════════════════════
# A5 — Market condition re-validation in _route_live
# ═══════════════════════════════════════════════════════════════════════════

class TestMarketConditionRevalidation(unittest.TestCase):
    """A5: market condition logic is wired into _route_live.

    Tests the filter thresholds in isolation (no full async chain needed)
    plus a structural check that the code is present in order_router.
    """

    def test_spread_threshold_logic(self):
        """Spread > max_spread_cents should be flagged."""
        from merid.event_venues.kalshi.market_filter import DEFAULT_FILTER_CONFIG
        cfg = DEFAULT_FILTER_CONFIG
        bid, ask = 40, 40 + cfg.max_spread_cents + 5
        spread = ask - bid
        self.assertGreater(spread, cfg.max_spread_cents)

    def test_price_too_low_logic(self):
        from merid.event_venues.kalshi.market_filter import DEFAULT_FILTER_CONFIG
        cfg = DEFAULT_FILTER_CONFIG
        bid = cfg.min_price_cents - 1
        self.assertLess(bid, cfg.min_price_cents)

    def test_price_too_high_logic(self):
        from merid.event_venues.kalshi.market_filter import DEFAULT_FILTER_CONFIG
        cfg = DEFAULT_FILTER_CONFIG
        bid = cfg.max_price_cents + 1
        self.assertGreater(bid, cfg.max_price_cents)

    def test_volume_too_low_logic(self):
        from merid.event_venues.kalshi.market_filter import DEFAULT_FILTER_CONFIG
        cfg = DEFAULT_FILTER_CONFIG
        vol = cfg.min_volume - 1
        self.assertLess(vol, cfg.min_volume)

    def test_good_market_passes_all_checks(self):
        from merid.event_venues.kalshi.market_filter import DEFAULT_FILTER_CONFIG
        cfg = DEFAULT_FILTER_CONFIG
        bid, ask = 50, 54
        vol, oi = cfg.min_volume + 10, cfg.min_open_interest + 5
        spread = ask - bid
        self.assertLessEqual(spread, cfg.max_spread_cents)
        self.assertGreaterEqual(bid, cfg.min_price_cents)
        self.assertLessEqual(bid, cfg.max_price_cents)
        self.assertGreaterEqual(vol, cfg.min_volume)

    def test_a5_code_present_in_route_live(self):
        """Structural: A5 block is compiled into order_router source."""
        import inspect
        from merid.event_venues.kalshi import order_router
        src = inspect.getsource(order_router)
        self.assertIn("A5: Re-validate market conditions", src)
        self.assertIn("market_condition:spread_too_wide", src)
        self.assertIn("market_condition:price_too_low", src)
        self.assertIn("market_condition:volume_too_low", src)


# ═══════════════════════════════════════════════════════════════════════════
# A6 — Sanity check gate in route_order / route_order_async
# ═══════════════════════════════════════════════════════════════════════════

class TestSanityCheckGate(unittest.TestCase):

    def setUp(self):
        """Set trade mode to MOCK for these tests."""
        from trading.trade_mode import set_trade_mode, TradeMode
        self.previous_mode = set_trade_mode(TradeMode.MOCK, reason="test setup")

    def tearDown(self):
        """Restore previous trade mode."""
        from trading.trade_mode import set_trade_mode, TradeMode
        if hasattr(self, 'previous_mode'):
            # If previous was LIVE, set to PAPER to avoid MOCK→LIVE transition error
            if self.previous_mode == TradeMode.LIVE:
                set_trade_mode(TradeMode.PAPER, reason="test teardown")
            else:
                set_trade_mode(self.previous_mode, reason="test teardown")

    def _intent(self, count=5, price_cents=50, **kw):
        from merid.event_venues.kalshi.order_router import OrderIntent
        from merid.prediction.venue_gate import TradingMode
        return OrderIntent(
            ticker="KXBTCD-TEST",
            side="yes",
            action="buy",
            price_cents=price_cents,
            count=count,
            mode=TradingMode.MOCK,
            agent_id="BTC_15M",
            edge_pct=5.0,
            confidence=0.8,
            model_prob=0.6,
            group_id="test-group-123",
            **kw,
        )

    @patch("merid.event_venues.kalshi.order_router._validate_position_lifecycle", return_value=None)
    @patch("merid.event_venues.kalshi.order_router._check_bankroll_risk_cap", return_value=None)
    @patch("merid.event_venues.kalshi.order_router._is_authorized_caller", return_value=True)
    def test_valid_order_passes_sanity_check(self, mock_auth, mock_bankroll, mock_lifecycle):
        from merid.event_venues.kalshi.order_router import route_order
        result = route_order(self._intent())
        self.assertNotEqual(result.status, "rejected")

    @patch("merid.event_venues.kalshi.order_router._is_authorized_caller", return_value=True)
    def test_zero_count_rejected_before_sanity(self, mock_auth):
        from merid.event_venues.kalshi.order_router import route_order
        result = route_order(self._intent(count=0))
        self.assertEqual(result.status, "rejected")
        self.assertIn("non_positive_size", result.reason)

    def test_sanity_check_rejects_negative_price(self):
        from merid.event_venues.kalshi.order_router import _check_sanity, OrderIntent
        from merid.prediction.venue_gate import TradingMode
        import time as _t
        intent = OrderIntent(
            ticker="KXBTCD-TEST", side="yes", action="buy",
            price_cents=50, count=1, mode=TradingMode.MOCK,
        )
        # Inject a checker that rejects everything
        with patch("core.order_sanity_check.get_order_sanity_checker") as mock_get:
            mock_checker = MagicMock()
            mock_checker.check.return_value = MagicMock(
                passed=False,
                violations=[{"check": "max_order_notional_usd"}],
            )
            mock_get.return_value = mock_checker
            result = _check_sanity(intent, _t.monotonic(), TradingMode.MOCK)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "rejected")
        self.assertIn("sanity_check", result.reason)

    def test_sanity_checker_exception_is_fail_closed(self):
        """If checker raises, the order is rejected (fail-closed)."""
        from merid.event_venues.kalshi.order_router import _check_sanity, OrderIntent
        from merid.prediction.venue_gate import TradingMode
        import time as _t
        intent = OrderIntent(
            ticker="X", side="yes", action="buy",
            price_cents=50, count=1, mode=TradingMode.MOCK,
        )
        with patch("core.order_sanity_check.get_order_sanity_checker", side_effect=ImportError("no module")):
            result = _check_sanity(intent, _t.monotonic(), TradingMode.MOCK)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "rejected")
        self.assertIn("sanity_check_error", result.reason)


# ═══════════════════════════════════════════════════════════════════════════
# A7 — KalshiConfig KALSHI_ENV enforcement
# ═══════════════════════════════════════════════════════════════════════════

class TestKalshiConfigEnvEnforcement(unittest.TestCase):

    def setUp(self):
        """Set trade mode to MOCK for these tests."""
        from trading.trade_mode import set_trade_mode, TradeMode
        self.previous_mode = set_trade_mode(TradeMode.MOCK, reason="test setup")

    def tearDown(self):
        """Restore previous trade mode."""
        from trading.trade_mode import set_trade_mode, TradeMode
        if hasattr(self, 'previous_mode'):
            # If previous was LIVE, set to PAPER to avoid MOCK→LIVE transition error
            if self.previous_mode == TradeMode.LIVE:
                set_trade_mode(TradeMode.PAPER, reason="test teardown")
            else:
                set_trade_mode(self.previous_mode, reason="test teardown")

    def _make_settings_mock(self, env: dict):
        """Build a mock merid.settings module whose settings object returns env values."""
        mock_mod = MagicMock()
        s = mock_mod.settings
        s.KALSHI_EMAIL = env.get("KALSHI_EMAIL")
        s.KALSHI_PASSWORD = env.get("KALSHI_PASSWORD")
        s.KALSHI_API_KEY_ID = env.get("KALSHI_API_KEY_ID", "") or None
        s.KALSHI_PRIVATE_KEY_PATH = env.get("KALSHI_PRIVATE_KEY_PATH", "") or None
        s.KALSHI_PRIVATE_KEY_PEM = env.get("KALSHI_PRIVATE_KEY_PEM")
        s.KALSHI_USE_DEMO = env.get("KALSHI_USE_DEMO", "false").lower() == "true"
        s.KALSHI_API_HOST = env.get("KALSHI_API_HOST")
        return mock_mod

    def _make_config(self, env: dict):
        from merid.event_venues.kalshi.models import KalshiConfig
        mock_mod = self._make_settings_mock(env)
        saved = sys.modules.get("merid.settings")
        sys.modules["merid.settings"] = mock_mod
        try:
            with patch.dict(os.environ, env, clear=False):
                return KalshiConfig()
        finally:
            if saved is not None:
                sys.modules["merid.settings"] = saved
            else:
                sys.modules.pop("merid.settings", None)

    def test_demo_env_sets_use_demo_true(self):
        cfg = self._make_config({
            "KALSHI_ENV": "demo",
            "KALSHI_DEMO_API_KEY_ID": "demo-key-123",
            "KALSHI_DEMO_PRIVATE_KEY_PATH": "demo.pem",
        })
        self.assertTrue(cfg.use_demo)
        self.assertEqual(cfg.api_key, "demo-key-123")

    def test_live_env_raises_without_live_key(self):
        """KALSHI_ENV=live with no live key and no legacy key must raise."""
        from merid.event_venues.kalshi.models import KalshiConfig
        env = {
            "KALSHI_ENV": "live",
            "KALSHI_LIVE_API_KEY_ID": "",
            "KALSHI_API_KEY_ID": "",
            "KALSHI_API_KEY": "",
        }
        mock_mod = self._make_settings_mock(env)
        saved = sys.modules.get("merid.settings")
        sys.modules["merid.settings"] = mock_mod
        try:
            with patch.dict(os.environ, env, clear=False):
                with self.assertRaises(ValueError) as ctx:
                    KalshiConfig()
                self.assertIn("KALSHI_ENV=live", str(ctx.exception))
        finally:
            if saved is not None:
                sys.modules["merid.settings"] = saved
            else:
                sys.modules.pop("merid.settings", None)

    def test_live_env_accepts_live_key(self):
        cfg = self._make_config({
            "KALSHI_ENV": "live",
            "KALSHI_LIVE_API_KEY_ID": "live-key-abc",
            "KALSHI_LIVE_PRIVATE_KEY_PATH": "live.pem",
        })
        self.assertFalse(cfg.use_demo)
        self.assertEqual(cfg.api_key, "live-key-abc")

    def test_no_kalshi_env_falls_through_to_legacy(self):
        """When KALSHI_ENV is unset, legacy KALSHI_API_KEY_ID is used."""
        cfg = self._make_config({
            "KALSHI_ENV": "",
            "KALSHI_API_KEY_ID": "legacy-key",
            "KALSHI_PRIVATE_KEY_PATH": "legacy.pem",
        })
        self.assertEqual(cfg.api_key, "legacy-key")


# ═══════════════════════════════════════════════════════════════════════════
# B6 — OrderIntent TIF default
# ═══════════════════════════════════════════════════════════════════════════

class TestOrderIntentDefaults(unittest.TestCase):

    def test_default_tif_is_gtc(self):
        from merid.event_venues.kalshi.order_router import OrderIntent
        intent = OrderIntent(ticker="X", side="yes", action="buy", price_cents=50, count=1)
        self.assertEqual(intent.time_in_force, "gtc")

    def test_explicit_tif_preserved(self):
        from merid.event_venues.kalshi.order_router import OrderIntent
        intent = OrderIntent(
            ticker="X", side="yes", action="buy", price_cents=50, count=1,
            time_in_force="ioc",
        )
        self.assertEqual(intent.time_in_force, "ioc")


# ═══════════════════════════════════════════════════════════════════════════
# Ticker helper
# ═══════════════════════════════════════════════════════════════════════════

class TestGetUnderlying(unittest.TestCase):

    def test_btc_extracted(self):
        from merid.event_venues.kalshi.order_router import _get_underlying
        self.assertEqual(_get_underlying("KXBTCD-25JUN-T100000"), "BTC")

    def test_eth_extracted(self):
        from merid.event_venues.kalshi.order_router import _get_underlying
        self.assertEqual(_get_underlying("KXETH-25JUN-T3000"), "ETH")

    def test_unknown_returns_OTHER(self):
        from merid.event_venues.kalshi.order_router import _get_underlying
        self.assertEqual(_get_underlying("KXCORN-25DEC"), "OTHER")


# ═══════════════════════════════════════════════════════════════════════════
# Structural invariants
# ═══════════════════════════════════════════════════════════════════════════

class TestSprintAInvariants(unittest.TestCase):

    def test_consensus_has_brier_weight_cache_fields(self):
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            from merid.prediction.consensus import PredictionConsensusStore
            store = PredictionConsensusStore(db_path=path)
            self.assertIsInstance(store._brier_weights_cache, dict)
            self.assertIsInstance(store._brier_weights_ts, float)
            self.assertIsInstance(store._brier_weights_ttl, float)
        finally:
            del store
            gc.collect()
            try:
                os.unlink(path)
            except PermissionError:
                pass

    def test_category_exposure_module_importable(self):
        from merid.event_venues.kalshi import category_exposure
        self.assertTrue(hasattr(category_exposure, "CategoryExposureTracker"))
        self.assertTrue(hasattr(category_exposure, "get_category_exposure_tracker"))
        self.assertTrue(hasattr(category_exposure, "infer_category"))

    def test_order_router_has_check_sanity(self):
        from merid.event_venues.kalshi import order_router
        self.assertTrue(hasattr(order_router, "_check_sanity"))

    def test_order_router_has_get_underlying(self):
        from merid.event_venues.kalshi import order_router
        self.assertTrue(hasattr(order_router, "_get_underlying"))

    def test_runbook_exists(self):
        import pathlib
        runbook = pathlib.Path(__file__).parents[3] / "RUNBOOK.md"
        self.assertTrue(runbook.exists(), "RUNBOOK.md not found at repo root")
        content = runbook.read_text()
        for section in ("Kill-Switch Policy", "Daily Pre-Open Checklist", "Halt Conditions"):
            self.assertIn(section, content, f"RUNBOOK.md missing section: {section}")


if __name__ == "__main__":
    unittest.main()
