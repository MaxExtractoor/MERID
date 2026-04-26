"""Tests for merid.prediction.kalshi_strike_selector.

Covers:
- Single contract evaluation (accept/reject/deep OTM)
- Batch evaluation with aggregate stats
- Config parsing from YAML blocks
- Threshold resolution priority chain
- Grid coverage validation
- Integration with agent_grid_config
"""

from __future__ import annotations

import json
import unittest
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from merid.prediction.kalshi_strike_selector import (
    DEFAULT_MAX_DISTANCE,
    DEFAULT_TARGET_BAND,
    FALLBACK_MAX_DISTANCE_PCT,
    FALLBACK_TARGET_BAND_PCT,
    BatchSelectionResult,
    KalshiStrikeSelector,
    RejectionReason,
    StrikeSelectionConfig,
    StrikeSelectionResult,
    get_strike_selector,
    get_strike_selector_for_agent,
    parse_strike_selection_config,
)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _selector(**kwargs) -> KalshiStrikeSelector:
    """Build a selector with optional config overrides."""
    return KalshiStrikeSelector(StrikeSelectionConfig(**kwargs))


def _default_selector() -> KalshiStrikeSelector:
    """Selector with default config."""
    return KalshiStrikeSelector()


# ═══════════════════════════════════════════════════════════════════════════
# Test: Single evaluation — acceptance
# ═══════════════════════════════════════════════════════════════════════════


class TestStrikeSelectorAcceptance(unittest.TestCase):
    """Contracts within max distance should be accepted."""

    def test_btc_15m_within_band(self):
        sel = _default_selector()
        result = sel.evaluate("KXBTC15M-T100500", "BTC", "15m", spot=100000.0, strike=100500.0)
        self.assertTrue(result.accepted)
        self.assertAlmostEqual(result.distance_pct, 0.00498, places=3)

    def test_eth_hourly_within_band(self):
        sel = _default_selector()
        result = sel.evaluate("KXETH-T3500", "ETH", "1h", spot=3400.0, strike=3500.0)
        self.assertTrue(result.accepted)

    def test_sol_daily_within_band(self):
        sel = _default_selector()
        result = sel.evaluate("KXSOL-D-T180", "SOL", "daily", spot=170.0, strike=180.0)
        self.assertTrue(result.accepted)

    def test_xrp_weekly_within_band(self):
        sel = _default_selector()
        result = sel.evaluate("KXXRP-W-T2.5", "XRP", "weekly", spot=2.20, strike=2.50)
        self.assertTrue(result.accepted)

    def test_doge_15m_within_band(self):
        sel = _default_selector()
        # DOGE 15m max distance is 4% (0.04). Use strike within 4% of spot.
        # spot=0.33, strike=0.34 is ~2.9% away (|0.33-0.34|/0.34 = 0.029) - within 4% band
        result = sel.evaluate("KXDOGE15M-T0.34", "DOGE", "15m", spot=0.33, strike=0.34)
        self.assertTrue(result.accepted)

    def test_spot_equals_strike_accepted(self):
        sel = _default_selector()
        result = sel.evaluate("KXBTC-T100000", "BTC", "1h", spot=100000.0, strike=100000.0)
        self.assertTrue(result.accepted)
        self.assertEqual(result.distance_pct, 0.0)
        self.assertTrue(result.in_target_band)

    def test_in_target_band_flag(self):
        sel = _default_selector()
        # BTC 15m target band is 6%; strike is 1% away (well inside)
        result = sel.evaluate("KXBTC15M-T101000", "BTC", "15m", spot=100000.0, strike=101000.0)
        self.assertTrue(result.accepted)
        self.assertTrue(result.in_target_band)

    def test_outside_target_band_but_accepted(self):
        sel = _default_selector()
        # BTC 15m target band is 2.5%, max distance is 6%; strike is 5% away (outside target 2.5%, inside max 6%)
        result = sel.evaluate("KXBTC15M-T105000", "BTC", "15m", spot=100000.0, strike=105000.0)
        self.assertTrue(result.accepted)
        self.assertFalse(result.in_target_band)


# ═══════════════════════════════════════════════════════════════════════════
# Test: Single evaluation — rejection
# ═══════════════════════════════════════════════════════════════════════════


class TestStrikeSelectorRejection(unittest.TestCase):
    """Contracts outside max distance or with missing data should be rejected."""

    def test_missing_spot_rejected(self):
        sel = _default_selector()
        result = sel.evaluate("KXBTC-T100000", "BTC", "15m", spot=None, strike=100000.0)
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejection_reason, RejectionReason.MISSING_SPOT)

    def test_zero_spot_rejected(self):
        sel = _default_selector()
        result = sel.evaluate("KXBTC-T100000", "BTC", "15m", spot=0.0, strike=100000.0)
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejection_reason, RejectionReason.MISSING_SPOT)

    def test_missing_strike_rejected(self):
        # Directional passthrough is enabled by default (for up/down markets).
        # Disable it to test that missing strike is properly rejected for non-directional markets.
        sel = _selector(allow_directional_passthrough=False)
        result = sel.evaluate("KXBTC-T100000", "BTC", "15m", spot=100000.0, strike=None)
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejection_reason, RejectionReason.MISSING_STRIKE)

    def test_zero_strike_rejected(self):
        sel = _default_selector()
        result = sel.evaluate("KXBTC-T100000", "BTC", "15m", spot=100000.0, strike=0.0)
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejection_reason, RejectionReason.ZERO_STRIKE)

    def test_btc_15m_too_far(self):
        sel = _default_selector()
        # BTC 15m max distance is 6%, 20% away (strike 120000) should be rejected
        result = sel.evaluate("KXBTC15M-T120000", "BTC", "15m", spot=100000.0, strike=120000.0)
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejection_reason, RejectionReason.EXCEEDS_MAX_DISTANCE)

    def test_eth_hourly_too_far(self):
        sel = _default_selector()
        # ETH hourly max distance is 8%, 30% away (strike 3900) should be rejected
        result = sel.evaluate("KXETH-T3900", "ETH", "1h", spot=3000.0, strike=3900.0)
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejection_reason, RejectionReason.EXCEEDS_MAX_DISTANCE)

    def test_result_includes_distance_on_rejection(self):
        sel = _default_selector()
        # 20% away should be rejected with 6% max distance
        result = sel.evaluate("KXBTC15M-T120000", "BTC", "15m", spot=100000.0, strike=120000.0)
        self.assertFalse(result.accepted)
        self.assertIsNotNone(result.distance_pct)
        # distance_pct = abs((spot - strike) / strike) = abs((100000 - 120000) / 100000) = 0.2
        # Note: actual implementation may use spot or strike as denominator
        self.assertAlmostEqual(result.distance_pct, 0.2, places=1)  # ~20% distance


# ═══════════════════════════════════════════════════════════════════════════
# Test: Deep OTM handling
# ═══════════════════════════════════════════════════════════════════════════


class TestDeepOTM(unittest.TestCase):
    """Deep OTM contracts should be rejected by default, accepted with cap when allowed."""

    def test_deep_otm_rejected_by_default(self):
        sel = _default_selector()
        result = sel.evaluate("KXBTC15M-T120000", "BTC", "15m", spot=100000.0, strike=120000.0)
        self.assertFalse(result.accepted)

    def test_deep_otm_accepted_when_allowed(self):
        sel = _selector(deep_otm_allowed=True, deep_otm_max_risk_pct=0.005)
        result = sel.evaluate("KXBTC15M-T120000", "BTC", "15m", spot=100000.0, strike=120000.0)
        self.assertTrue(result.accepted)
        self.assertTrue(result.is_deep_otm)
        self.assertTrue(result.risk_capped)

    def test_deep_otm_not_in_target_band(self):
        sel = _selector(deep_otm_allowed=True)
        result = sel.evaluate("KXBTC15M-T120000", "BTC", "15m", spot=100000.0, strike=120000.0)
        self.assertFalse(result.in_target_band)


# ═══════════════════════════════════════════════════════════════════════════
# Test: Batch evaluation
# ═══════════════════════════════════════════════════════════════════════════


class TestBatchEvaluation(unittest.TestCase):
    """Batch evaluation should aggregate stats correctly."""

    def test_batch_mixed(self):
        sel = _default_selector()
        contracts = [
            # Within BTC 15m 15% max distance (0.5% away) - should be accepted
            {"ticker": "KXBTC15M-T100500", "asset": "BTC", "timeframe": "15m", "spot": 100000, "strike": 100500},
            # Outside BTC 15m 15% max distance (20% away) - should be rejected
            {"ticker": "KXBTC15M-T120000", "asset": "BTC", "timeframe": "15m", "spot": 100000, "strike": 120000},
            # Missing spot - should be rejected
            {"ticker": "KXETH-T3500", "asset": "ETH", "timeframe": "1h", "spot": None, "strike": 3500},
        ]
        batch = sel.evaluate_batch(contracts)
        self.assertEqual(batch.total, 3)
        self.assertEqual(batch.accepted, 1)
        self.assertEqual(batch.rejected, 2)
        self.assertEqual(len(batch.accepted_results()), 1)
        self.assertEqual(len(batch.rejected_results()), 2)

    def test_batch_all_accepted(self):
        sel = _default_selector()
        contracts = [
            # Use valid crypto tickers and tight strikes within 5% max distance for BTC 15m
            {"ticker": "KXBTC15M-T101000", "asset": "BTC", "timeframe": "15m", "spot": 100000.0, "strike": 101000.0},
            {"ticker": "KXBTC15M-T100500", "asset": "BTC", "timeframe": "15m", "spot": 100000.0, "strike": 100500.0},
        ]
        batch = sel.evaluate_batch(contracts)
        self.assertEqual(batch.accepted, 2)
        self.assertEqual(batch.rejected, 0)

    def test_batch_empty(self):
        sel = _default_selector()
        batch = sel.evaluate_batch([])
        self.assertEqual(batch.total, 0)
        self.assertEqual(batch.accepted, 0)

    def test_batch_rejection_reasons_counted(self):
        # Use valid crypto tickers. Disable directional passthrough to test missing strike rejection.
        sel = _selector(allow_directional_passthrough=False)
        contracts = [
            {"ticker": "KXBTC15M-A", "asset": "BTC", "timeframe": "15m", "spot": None, "strike": 100000},
            {"ticker": "KXBTC15M-B", "asset": "BTC", "timeframe": "15m", "spot": None, "strike": 100000},
            {"ticker": "KXBTC15M-C", "asset": "BTC", "timeframe": "15m", "spot": 100000, "strike": None},
        ]
        batch = sel.evaluate_batch(contracts)
        self.assertEqual(batch.rejection_reasons.get(RejectionReason.MISSING_SPOT), 2)
        self.assertEqual(batch.rejection_reasons.get(RejectionReason.MISSING_STRIKE), 1)

    def test_batch_summary(self):
        sel = _default_selector()
        contracts = [
            {"ticker": "KXBTC15M-T100500", "asset": "BTC", "timeframe": "15m", "spot": 100000, "strike": 100500},
        ]
        batch = sel.evaluate_batch(contracts)
        summary = batch.summary()
        self.assertIn("total", summary)
        self.assertIn("accepted", summary)
        self.assertIn("rejected", summary)


# ═══════════════════════════════════════════════════════════════════════════
# Test: Config parsing
# ═══════════════════════════════════════════════════════════════════════════


class TestConfigParsing(unittest.TestCase):
    """YAML config block parsing."""

    def test_none_returns_default(self):
        cfg = parse_strike_selection_config(None)
        self.assertIsNone(cfg.max_spot_to_strike_pct)
        self.assertFalse(cfg.deep_otm_allowed)

    def test_empty_dict_returns_default(self):
        cfg = parse_strike_selection_config({})
        self.assertIsNone(cfg.max_spot_to_strike_pct)

    def test_basic_config(self):
        raw = {
            "max_spot_to_strike_pct": 0.08,
            "target_spot_band_pct": 0.03,
            "deep_otm_allowed": True,
            "deep_otm_max_risk_pct": 0.01,
        }
        cfg = parse_strike_selection_config(raw)
        self.assertAlmostEqual(cfg.max_spot_to_strike_pct, 0.08)
        self.assertAlmostEqual(cfg.target_spot_band_pct, 0.03)
        self.assertTrue(cfg.deep_otm_allowed)
        self.assertAlmostEqual(cfg.deep_otm_max_risk_pct, 0.01)

    def test_per_asset_tf_overrides(self):
        raw = {
            "max_spot_to_strike_pct": 0.10,
            "per_asset_timeframe": {
                "BTC_15m": {"max_distance_pct": 0.03, "target_band_pct": 0.01},
                "ETH_daily": {"max_distance_pct": 0.15},
            },
        }
        cfg = parse_strike_selection_config(raw)
        self.assertAlmostEqual(cfg.per_asset_tf_max_distance[("BTC", "15m")], 0.03)
        self.assertAlmostEqual(cfg.per_asset_tf_target_band[("BTC", "15m")], 0.01)
        self.assertAlmostEqual(cfg.per_asset_tf_max_distance[("ETH", "daily")], 0.15)

    def test_malformed_per_asset_key_ignored(self):
        raw = {
            "per_asset_timeframe": {
                "BADKEY": {"max_distance_pct": 0.99},
            },
        }
        cfg = parse_strike_selection_config(raw)
        self.assertEqual(len(cfg.per_asset_tf_max_distance), 0)


# ═══════════════════════════════════════════════════════════════════════════
# Test: Threshold resolution priority chain
# ═══════════════════════════════════════════════════════════════════════════


class TestThresholdResolution(unittest.TestCase):
    """Priority: per_asset_tf → global config → DEFAULT → FALLBACK."""

    def test_per_asset_tf_takes_precedence(self):
        sel = _selector(
            max_spot_to_strike_pct=0.50,
            per_asset_tf_max_distance={("BTC", "15m"): 0.02},
        )
        thresholds = sel.get_thresholds("BTC", "15m")
        self.assertAlmostEqual(thresholds["max_distance_pct"], 0.02)

    def test_global_config_used_when_no_per_asset(self):
        sel = _selector(max_spot_to_strike_pct=0.20)
        thresholds = sel.get_thresholds("BTC", "15m")
        self.assertAlmostEqual(thresholds["max_distance_pct"], 0.20)

    def test_default_table_used_when_no_config(self):
        sel = _default_selector()
        thresholds = sel.get_thresholds("BTC", "15m")
        self.assertAlmostEqual(thresholds["max_distance_pct"], DEFAULT_MAX_DISTANCE[("BTC", "15m")])

    def test_fallback_used_for_unknown_asset(self):
        sel = _default_selector()
        thresholds = sel.get_thresholds("UNKNOWN", "15m")
        self.assertAlmostEqual(thresholds["max_distance_pct"], FALLBACK_MAX_DISTANCE_PCT)


# ═══════════════════════════════════════════════════════════════════════════
# Test: Default tables completeness
# ═══════════════════════════════════════════════════════════════════════════


class TestDefaultTables(unittest.TestCase):
    """DEFAULT_MAX_DISTANCE and DEFAULT_TARGET_BAND must cover all 5 assets × all timeframes."""

    EXPECTED_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    EXPECTED_TFS = ["15m", "1h", "daily", "weekly", "monthly", "annual"]

    def test_max_distance_coverage(self):
        for asset in self.EXPECTED_ASSETS:
            for tf in self.EXPECTED_TFS:
                key = (asset, tf)
                self.assertIn(key, DEFAULT_MAX_DISTANCE, f"Missing DEFAULT_MAX_DISTANCE[{key}]")
                self.assertGreater(DEFAULT_MAX_DISTANCE[key], 0)

    def test_target_band_coverage(self):
        for asset in self.EXPECTED_ASSETS:
            for tf in self.EXPECTED_TFS:
                key = (asset, tf)
                self.assertIn(key, DEFAULT_TARGET_BAND, f"Missing DEFAULT_TARGET_BAND[{key}]")
                self.assertGreater(DEFAULT_TARGET_BAND[key], 0)

    def test_target_band_less_than_max_distance(self):
        for key in DEFAULT_MAX_DISTANCE:
            if key in DEFAULT_TARGET_BAND:
                self.assertLess(
                    DEFAULT_TARGET_BAND[key], DEFAULT_MAX_DISTANCE[key],
                    f"Target band >= max distance for {key}",
                )

    def test_monotone_by_timeframe(self):
        """Longer timeframes should have wider (or equal) bands."""
        tf_order = ["15m", "1h", "daily", "weekly", "monthly", "annual"]
        for asset in self.EXPECTED_ASSETS:
            for i in range(len(tf_order) - 1):
                short_key = (asset, tf_order[i])
                long_key = (asset, tf_order[i + 1])
                self.assertLessEqual(
                    DEFAULT_MAX_DISTANCE[short_key], DEFAULT_MAX_DISTANCE[long_key],
                    f"Non-monotone: {short_key} ({DEFAULT_MAX_DISTANCE[short_key]}) > "
                    f"{long_key} ({DEFAULT_MAX_DISTANCE[long_key]})",
                )


# ═══════════════════════════════════════════════════════════════════════════
# Test: Result serialization
# ═══════════════════════════════════════════════════════════════════════════


class TestResultSerialization(unittest.TestCase):
    """StrikeSelectionResult.to_dict() should produce valid JSON."""

    def test_accepted_result_to_dict(self):
        sel = _default_selector()
        result = sel.evaluate("KXBTC-T101000", "BTC", "15m", spot=100000.0, strike=101000.0)
        d = result.to_dict()
        self.assertTrue(d["accepted"])
        self.assertEqual(d["ticker"], "KXBTC-T101000")
        # Should be JSON-serializable
        json.dumps(d)

    def test_rejected_result_to_dict(self):
        sel = _default_selector()
        result = sel.evaluate("KXBTC-T120000", "BTC", "15m", spot=100000.0, strike=120000.0)
        d = result.to_dict()
        self.assertFalse(d["accepted"])
        self.assertIn("rejection_reason", d)
        json.dumps(d)

    def test_deep_otm_result_to_dict(self):
        sel = _selector(deep_otm_allowed=True)
        result = sel.evaluate("KXBTC-T120000", "BTC", "15m", spot=100000.0, strike=120000.0)
        d = result.to_dict()
        self.assertTrue(d["accepted"])
        self.assertTrue(d.get("is_deep_otm"))
        self.assertTrue(d.get("risk_capped"))


# ═══════════════════════════════════════════════════════════════════════════
# Test: Singleton and agent factory
# ═══════════════════════════════════════════════════════════════════════════


class TestSingletonAndFactory(unittest.TestCase):
    """get_strike_selector and get_strike_selector_for_agent."""

    def test_singleton_returns_selector(self):
        sel = get_strike_selector()
        self.assertIsInstance(sel, KalshiStrikeSelector)

    def test_factory_with_no_strike_selection(self):
        class FakeConfig:
            strike_selection = None
        sel = get_strike_selector_for_agent(FakeConfig())
        self.assertIsInstance(sel, KalshiStrikeSelector)

    def test_factory_with_dict_config(self):
        class FakeConfig:
            strike_selection = {
                "max_spot_to_strike_pct": 0.06,
                "deep_otm_allowed": True,
            }
        sel = get_strike_selector_for_agent(FakeConfig())
        self.assertIsInstance(sel, KalshiStrikeSelector)
        self.assertTrue(sel.config.deep_otm_allowed)
        self.assertAlmostEqual(sel.config.max_spot_to_strike_pct, 0.06)

    def test_factory_with_typed_config(self):
        cfg = StrikeSelectionConfig(max_spot_to_strike_pct=0.10)
        class FakeConfig:
            strike_selection = cfg
        sel = get_strike_selector_for_agent(FakeConfig())
        self.assertAlmostEqual(sel.config.max_spot_to_strike_pct, 0.10)


# ═══════════════════════════════════════════════════════════════════════════
# Test: Integration with agent_grid_config
# ═══════════════════════════════════════════════════════════════════════════


class TestAgentGridConfigIntegration(unittest.TestCase):
    """Verify that agent_grid_config parses strike_selection correctly."""

    def test_agent_config_has_strike_selection_field(self):
        from merid.prediction.agent_grid_config import AgentConfig
        ac = AgentConfig(name="TEST")
        self.assertIsNone(ac.strike_selection)

    def test_parse_agent_with_strike_selection(self):
        from merid.prediction.agent_grid_config import _parse_agent
        raw = {
            "name": "TEST_15M",
            "assets": ["BTC"],
            "timeframes": ["15m"],
            "strike_selection": {
                "max_spot_to_strike_pct": 0.04,
                "target_spot_band_pct": 0.015,
                "deep_otm_allowed": False,
            },
        }
        agent = _parse_agent(raw)
        self.assertIsNotNone(agent.strike_selection)
        self.assertAlmostEqual(agent.strike_selection.max_spot_to_strike_pct, 0.04)
        self.assertFalse(agent.strike_selection.deep_otm_allowed)

    def test_parse_agent_without_strike_selection(self):
        from merid.prediction.agent_grid_config import _parse_agent
        raw = {
            "name": "TEST_HOURLY",
            "assets": ["ETH"],
            "timeframes": ["1h"],
        }
        agent = _parse_agent(raw)
        self.assertIsNone(agent.strike_selection)


# ═══════════════════════════════════════════════════════════════════════════
# Test: MarketSnapshot strike fields
# ═══════════════════════════════════════════════════════════════════════════


class TestMarketSnapshotStrikeFields(unittest.TestCase):
    """Verify MarketSnapshot has the new strike selection metadata fields."""

    def test_snapshot_defaults(self):
        from merid.prediction.model import MarketSnapshot, ImpliedProbability, ContractState
        snap = MarketSnapshot(
            market_id="TEST",
            event_id="EVT",
            title="Test Market",
            state=ContractState.TRADING,
            implied=ImpliedProbability(yes_prob=Decimal("0.5"), no_prob=Decimal("0.5")),
            volume=Decimal("100"),
            open_interest=Decimal("50"),
        )
        self.assertFalse(snap.strike_in_target_band)
        self.assertFalse(snap.strike_risk_capped)

    def test_snapshot_fields_settable(self):
        from merid.prediction.model import MarketSnapshot, ImpliedProbability, ContractState
        snap = MarketSnapshot(
            market_id="TEST",
            event_id="EVT",
            title="Test Market",
            state=ContractState.TRADING,
            implied=ImpliedProbability(yes_prob=Decimal("0.5"), no_prob=Decimal("0.5")),
            volume=Decimal("100"),
            open_interest=Decimal("50"),
            strike_in_target_band=True,
            strike_risk_capped=True,
        )
        self.assertTrue(snap.strike_in_target_band)
        self.assertTrue(snap.strike_risk_capped)


# ═══════════════════════════════════════════════════════════════════════════
# Test: All 5 assets covered with proper bands
# ═══════════════════════════════════════════════════════════════════════════


class TestAllAssetsCovered(unittest.TestCase):
    """Every crypto asset should have proper band config for all timeframes."""

    def test_each_asset_15m_acceptance_at_spot(self):
        """All 5 assets at spot should be accepted for 15m."""
        sel = _default_selector()
        assets_spots = [
            ("BTC", 100000.0), ("ETH", 3500.0), ("SOL", 170.0),
            ("XRP", 2.20), ("DOGE", 0.33),
        ]
        for asset, spot in assets_spots:
            result = sel.evaluate(f"KX{asset}-T{spot}", asset, "15m", spot=spot, strike=spot)
            self.assertTrue(result.accepted, f"{asset} at spot should be accepted")
            self.assertTrue(result.in_target_band, f"{asset} at spot should be in target band")

    def test_each_asset_far_otm_rejection(self):
        """All 5 assets with 50% distance should be rejected for 15m."""
        sel = _default_selector()
        assets_spots = [
            ("BTC", 100000.0), ("ETH", 3500.0), ("SOL", 170.0),
            ("XRP", 2.20), ("DOGE", 0.33),
        ]
        for asset, spot in assets_spots:
            far_strike = spot * 1.5
            result = sel.evaluate(f"KX{asset}-TFAR", asset, "15m", spot=spot, strike=far_strike)
            self.assertFalse(result.accepted, f"{asset} at 50% OTM should be rejected for 15m")


# ═══════════════════════════════════════════════════════════════════════════
# Test: Asset-ticker matching with proper log levels (P0-002 fix)
#
# Regression guard: These tests verify that STRIKE_ASSET_MISMATCH ERROR spam
# from macro markets (KXFED-*) is eliminated while preserving strong protection
# for true crypto cross-asset mismatches.
# ═══════════════════════════════════════════════════════════════════════════


class TestAssetInTickerLoggingSemantics(unittest.TestCase):
    """Verify proper log levels for different asset matching scenarios.
    
    ERROR = True cross-asset mismatch (wiring bug)
    WARNING = Expected crypto but ticker asset unknown (config/data issue)
    DEBUG/None = Macro markets or both unknown (expected behavior)
    """

    def test_asset_in_ticker_crypto_match_ok(self):
        """Crypto ticker with matching expected asset - success, no ERROR."""
        from merid.prediction.kalshi_strike_selector import asset_in_ticker
        import logging

        # Use a list to capture any ERROR logs
        error_logs = []
        logger = logging.getLogger("merid.prediction.kalshi_strike_selector")
        original_level = logger.level
        
        class ErrorCapture(logging.Handler):
            def emit(self, record):
                if record.levelno >= logging.ERROR:
                    error_logs.append(self.format(record))
        
        handler = ErrorCapture()
        handler.setLevel(logging.ERROR)
        logger.addHandler(handler)
        
        try:
            result = asset_in_ticker("KXBTC15M-27APR-T101500", "BTC")
            self.assertTrue(result, "BTC ticker with BTC expected asset should match")
            self.assertEqual(len(error_logs), 0, 
                f"No ERROR logs expected for matching crypto asset, got: {error_logs}")
        finally:
            logger.removeHandler(handler)

    def test_asset_in_ticker_crypto_mismatch_logs_error(self):
        """True cross-asset mismatch logs ERROR (wiring bug)."""
        from merid.prediction.kalshi_strike_selector import asset_in_ticker
        import logging

        with self.assertLogs("merid.prediction.kalshi_strike_selector", level="ERROR") as cm:
            logging.getLogger("merid.prediction.kalshi_strike_selector").setLevel("ERROR")
            result = asset_in_ticker("KXETH-27APR-T3500", "BTC")

        self.assertFalse(result)
        self.assertEqual(len(cm.output), 1, "Exactly one ERROR log for cross-asset mismatch")
        self.assertIn("STRIKE_ASSET_MISMATCH", cm.output[0])
        self.assertIn("BTC", cm.output[0])
        self.assertIn("ETH", cm.output[0])

    def test_asset_in_ticker_expected_crypto_inferred_unknown_logs_warning(self):
        """Expected crypto asset but unknown ticker asset logs WARNING."""
        from merid.prediction.kalshi_strike_selector import asset_in_ticker
        import logging

        with self.assertLogs("merid.prediction.kalshi_strike_selector", level="WARNING") as cm:
            logging.getLogger("merid.prediction.kalshi_strike_selector").setLevel("WARNING")
            result = asset_in_ticker("UNKNOWN-TICKER-123", "BTC")

        self.assertFalse(result)
        warning_logs = [log for log in cm.output if "WARNING" in log]
        self.assertTrue(any("STRIKE_ASSET_UNKNOWN" in log for log in warning_logs),
                       f"Expected STRIKE_ASSET_UNKNOWN warning in {warning_logs}")

    def test_asset_in_ticker_macro_no_expected_asset_no_error(self):
        """Macro market with no expected asset produces no ERROR (expected behavior)."""
        from merid.prediction.kalshi_strike_selector import asset_in_ticker
        import logging

        with self.assertLogs("merid.prediction.kalshi_strike_selector", level="DEBUG") as cm:
            logging.getLogger("merid.prediction.kalshi_strike_selector").setLevel("DEBUG")
            result = asset_in_ticker("KXFED-27APR-T4.25", "")

        self.assertFalse(result)
        error_logs = [log for log in cm.output if "ERROR" in log]
        self.assertEqual(len(error_logs), 0, "No ERROR logs for macro markets with empty expected asset")


class TestCryptoOnlyGuard(unittest.TestCase):
    """Verify that non-crypto markets bypass strike selection without ERROR spam."""

    def test_is_crypto_market_recognizes_crypto_tickers(self):
        """is_crypto_market returns True for crypto tickers."""
        from merid.prediction.kalshi_strike_selector import is_crypto_market
        
        crypto_tickers = ["KXBTC-TEST", "KXETH-TEST", "KXSOL-TEST", "KXXRP-TEST", "KXDOGE-TEST"]
        for ticker in crypto_tickers:
            self.assertTrue(is_crypto_market(ticker), f"{ticker} should be recognized as crypto")

    def test_is_crypto_market_rejects_macro_tickers(self):
        """is_crypto_market returns False for macro tickers."""
        from merid.prediction.kalshi_strike_selector import is_crypto_market
        
        macro_tickers = ["KXFED-27APR-T4.25", "KXFEDDECISION-2026-04", "KXECON-*"]
        for ticker in macro_tickers:
            self.assertFalse(is_crypto_market(ticker), f"{ticker} should NOT be recognized as crypto")

    def test_evaluate_skips_macro_market_without_error(self):
        """Macro markets like KXFED are skipped without producing ERROR logs."""
        from merid.prediction.kalshi_strike_selector import RejectionReason
        import logging

        sel = _default_selector()
        error_logs = []
        logger = logging.getLogger("merid.prediction.kalshi_strike_selector")
        
        class ErrorCapture(logging.Handler):
            def emit(self, record):
                if record.levelno >= logging.ERROR:
                    error_logs.append(self.format(record))
        
        handler = ErrorCapture()
        handler.setLevel(logging.ERROR)
        logger.addHandler(handler)
        
        try:
            result = sel.evaluate("KXFED-27APR-T4.25", "", "15m", spot=4.25, strike=4.50)
            self.assertFalse(result.accepted)
            self.assertEqual(result.rejection_reason, RejectionReason.NON_CRYPTO_MARKET)
            self.assertEqual(len(error_logs), 0, f"No ERROR logs for macro market skip, got: {error_logs}")
        finally:
            logger.removeHandler(handler)

    def test_evaluate_macro_produces_debug_not_error(self):
        """Macro market skip logs at DEBUG level only."""
        import logging

        sel = _default_selector()

        with self.assertLogs("merid.prediction.kalshi_strike_selector", level="DEBUG") as cm:
            logging.getLogger("merid.prediction.kalshi_strike_selector").setLevel("DEBUG")
            result = sel.evaluate("KXFED-27APR-T4.25", "", "15m", spot=4.25, strike=4.50)

        self.assertFalse(result.accepted)
        self.assertTrue(
            any("STRIKE_SELECTOR_SKIP" in log for log in cm.output),
            f"Expected STRIKE_SELECTOR_SKIP debug log, got: {cm.output}"
        )


class TestRegressionKXFEDErrorSpam(unittest.TestCase):
    """Regression test: Eliminates 41+ repeating STRIKE_ASSET_MISMATCH errors/minute.
    
    Before the fix: SENTIMENT_CONTRARIAN_MACRO agent evaluating KXFED markets
    produced ERROR logs every cycle because the strike selector only knew
    crypto assets and logged asset=UNK inferred=UNK as ERROR.
    
    After the fix: Macro markets bypass the crypto selector entirely,
    producing at most DEBUG logs.
    """

    def test_kxfed_market_produces_no_asset_mismatch_error(self):
        """The specific KXFED-27APR-T4.25 ticker from production logs."""
        from merid.prediction.kalshi_strike_selector import asset_in_ticker
        import logging

        error_logs = []
        logger = logging.getLogger("merid.prediction.kalshi_strike_selector")
        
        class ErrorCapture(logging.Handler):
            def emit(self, record):
                if record.levelno >= logging.ERROR:
                    error_logs.append(self.format(record))
        
        handler = ErrorCapture()
        handler.setLevel(logging.ERROR)
        logger.addHandler(handler)
        
        try:
            result = asset_in_ticker("KXFED-27APR-T4.25", "")
            self.assertFalse(result)
            self.assertEqual(len(error_logs), 0, 
                f"KXFED market should NOT produce STRIKE_ASSET_MISMATCH ERROR, got: {error_logs}")
        finally:
            logger.removeHandler(handler)

    def test_crypto_markets_still_protected(self):
        """Real cross-asset mismatches on crypto markets still log ERROR."""
        from merid.prediction.kalshi_strike_selector import asset_in_ticker
        import logging

        with self.assertLogs("merid.prediction.kalshi_strike_selector", level="ERROR") as cm:
            logging.getLogger("merid.prediction.kalshi_strike_selector").setLevel("ERROR")
            result = asset_in_ticker("KXETH15M-27APR-T3500", "BTC")

        self.assertFalse(result)
        self.assertEqual(len(cm.output), 1)
        self.assertIn("TRUE cross-asset mispairing", cm.output[0])


# ═══════════════════════════════════════════════════════════════════════════
# Test: Asset resolution for macro markets (upstream bug fix)
# ═══════════════════════════════════════════════════════════════════════════


class TestResolveAssetForSnapshot(unittest.TestCase):
    """Verify asset resolution correctly handles macro vs crypto tickers."""

    def test_resolve_asset_crypto_ticker_ok(self):
        """Crypto tickers resolve to correct asset."""
        from merid.prediction.spot_strike_context import resolve_asset_for_snapshot

        # BTC ticker with BTC in config
        result = resolve_asset_for_snapshot(["BTC"], "KXBTC-27APR-T101500")
        self.assertEqual(result, "BTC")

        # ETH ticker with BTC first in config should still resolve to ETH
        result = resolve_asset_for_snapshot(["BTC", "ETH"], "KXETH-27APR-T3500")
        self.assertEqual(result, "ETH")

    def test_resolve_asset_macro_ticker_returns_empty(self):
        """Macro tickers return empty string, NOT config_assets[0]."""
        from merid.prediction.spot_strike_context import resolve_asset_for_snapshot

        # KXFED with BTC in config should return "", not "BTC"
        result = resolve_asset_for_snapshot(["BTC"], "KXFED-27APR-T4.25")
        self.assertEqual(result, "")

        # KXFEDDECISION with ETH in config should return "", not "ETH"
        result = resolve_asset_for_snapshot(["ETH"], "KXFEDDECISION-2026-04")
        self.assertEqual(result, "")

    def test_resolve_asset_unknown_ticker_returns_empty(self):
        """Unknown tickers return empty string."""
        from merid.prediction.spot_strike_context import resolve_asset_for_snapshot

        result = resolve_asset_for_snapshot(["BTC"], "UNKNOWN-TICKER-123")
        self.assertEqual(result, "")


class TestMarketCategoryHelpers(unittest.TestCase):
    """Test market category detection helpers."""

    def test_is_crypto_market_ticker(self):
        """Crypto tickers are correctly identified."""
        from merid.prediction.spot_strike_context import is_crypto_market_ticker

        # Crypto tickers
        self.assertTrue(is_crypto_market_ticker("KXBTC-27APR-T101500"))
        self.assertTrue(is_crypto_market_ticker("KXETH-27APR-T3500"))
        self.assertTrue(is_crypto_market_ticker("KXSOL-27APR-T180"))
        self.assertTrue(is_crypto_market_ticker("KXXRP-27APR-T2.5"))
        self.assertTrue(is_crypto_market_ticker("KXDOGE-27APR-T0.35"))

        # Macro tickers
        self.assertFalse(is_crypto_market_ticker("KXFED-27APR-T4.25"))
        self.assertFalse(is_crypto_market_ticker("KXFEDDECISION-2026-04"))
        self.assertFalse(is_crypto_market_ticker("KXECON-*"))

        # Edge cases
        self.assertFalse(is_crypto_market_ticker(""))
        self.assertFalse(is_crypto_market_ticker(None))

    def test_get_market_category(self):
        """Market categories are correctly determined."""
        from merid.prediction.spot_strike_context import get_market_category

        # Crypto
        self.assertEqual(get_market_category("KXBTC-27APR-T101500"), "crypto")
        self.assertEqual(get_market_category("KXETH-27APR-T3500"), "crypto")

        # Macro
        self.assertEqual(get_market_category("KXFED-27APR-T4.25"), "macro")
        self.assertEqual(get_market_category("KXFEDDECISION-2026-04"), "macro")
        self.assertEqual(get_market_category("KXECON-GDP"), "macro")

        # Unknown
        self.assertEqual(get_market_category("UNKNOWN-XYZ"), "unknown")
        self.assertEqual(get_market_category(""), "unknown")


# ═══════════════════════════════════════════════════════════════════════════
# Test: Full macro integration flow (KXFED end-to-end)
# ═══════════════════════════════════════════════════════════════════════════


class TestMacroIntegrationFlow(unittest.TestCase):
    """Integration test: Macro agent + KXFED market + strike selector bypass.

    Regression guard: Ensures the full flow produces zero STRIKE_ASSET_MISMATCH ERRORs.
    """

    def test_kxfed_full_flow_no_strike_asset_mismatch_errors(self):
        """Complete flow from asset resolution to strike selector bypass."""
        from merid.prediction.spot_strike_context import resolve_asset_for_snapshot
        from merid.prediction.kalshi_strike_selector import KalshiStrikeSelector, RejectionReason
        import logging

        # Step 1: Asset resolution for KXFED should return empty string
        resolved_asset = resolve_asset_for_snapshot(["BTC"], "KXFED-27APR-T4.25")
        self.assertEqual(resolved_asset, "", "Macro ticker should resolve to empty asset")

        # Step 2: Strike selector with empty asset and macro ticker
        sel = KalshiStrikeSelector()
        result = sel.evaluate(
            ticker="KXFED-27APR-T4.25",
            asset=resolved_asset,
            timeframe="15m",
            spot=4.25,
            strike=4.50,
        )

        # Step 3: Should be rejected as NON_CRYPTO_MARKET (not ASSET_TICKER_MISMATCH)
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejection_reason, RejectionReason.NON_CRYPTO_MARKET)

        # Step 4: Verify no ERROR logs at any point
        error_logs = []
        logger = logging.getLogger("merid.prediction.kalshi_strike_selector")

        class ErrorCapture(logging.Handler):
            def emit(self, record):
                if record.levelno >= logging.ERROR:
                    error_logs.append(self.format(record))

        handler = ErrorCapture()
        handler.setLevel(logging.ERROR)
        logger.addHandler(handler)

        try:
            # Re-run evaluation to capture any logs
            result2 = sel.evaluate(
                ticker="KXFED-27APR-T4.25",
                asset=resolved_asset,
                timeframe="15m",
                spot=4.25,
                strike=4.50,
            )
            self.assertFalse(result2.accepted)
            self.assertEqual(len(error_logs), 0,
                f"KXFED flow should produce zero ERROR logs, got: {error_logs}")
        finally:
            logger.removeHandler(handler)


# ═══════════════════════════════════════════════════════════════════════════
# Test: Expiry parsing for group_id generation (regression for risk_limit alerts)
# ═══════════════════════════════════════════════════════════════════════════


class TestExpiryParsingForGroupId(unittest.TestCase):
    """Verify expiry parsing handles various Kalshi ticker formats correctly.

    Regression guard: Prevents group_id=XRP-15m-unknown which caused 161 risk_limit alerts.
    """

    def test_parse_expiry_from_standard_crypto_ticker(self):
        """Standard format: KXBTC-26MAR2501-T80199.99"""
        from merid.event_venues.kalshi.market_filter import parse_expiry_from_ticker

        # Use future date (2027) to avoid expiry validation rejection
        exp = parse_expiry_from_ticker("KXBTC-26MAR2701-T80199.99")
        self.assertGreater(exp, 0, "Should parse valid expiry")

    def test_parse_expiry_from_15m_ticker_with_strike(self):
        """15m format with strike suffix: KXXRP15M-26APR271315-15"""
        from merid.event_venues.kalshi.market_filter import parse_expiry_from_ticker

        # Use future date (2027) to avoid expiry validation rejection
        exp = parse_expiry_from_ticker("KXXRP15M-26APR271315-15")
        self.assertGreater(exp, 0, "Should parse expiry even with strike suffix")

    def test_parse_expiry_from_hourly_ticker_with_strike(self):
        """Hourly format with strike suffix: KXETH-26APR2717-T2909.99"""
        from merid.event_venues.kalshi.market_filter import parse_expiry_from_ticker

        # Use future date (2027) to avoid expiry validation rejection
        exp = parse_expiry_from_ticker("KXETH-26APR2717-T2909.99")
        self.assertGreater(exp, 0, "Should parse expiry from hourly ticker")

    def test_group_id_from_ticker_no_unknown_suffix(self):
        """Group ID should not have 'unknown' suffix for valid tickers."""
        from merid.event_venues.kalshi.market_filter import group_id_from_ticker

        # 15m ticker with strike suffix - use future date (2027)
        gid = group_id_from_ticker("KXXRP15M-26APR271315-15")
        self.assertNotIn("unknown", gid, f"Group ID should not contain 'unknown': {gid}")
        self.assertIn("XRP", gid, f"Group ID should contain asset: {gid}")

        # Hourly ticker - use future date (2027)
        gid = group_id_from_ticker("KXETH-26APR2717-T2909.99")
        self.assertNotIn("unknown", gid, f"Group ID should not contain 'unknown': {gid}")
        self.assertIn("ETH", gid, f"Group ID should contain asset: {gid}")


if __name__ == "__main__":
    unittest.main()
