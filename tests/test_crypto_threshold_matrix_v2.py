"""Tests for crypto_threshold_matrix schema v2 support.

Tests both legacy (v1 rows-based) and modern_tradeable_kalshi_v1 (v2 edge_grid-based) profiles.
Verifies env var overrides work correctly.
"""

import os
import unittest
from decimal import Decimal
from unittest.mock import patch, MagicMock

from merid.prediction.crypto_threshold_matrix import (
    resolve_merged_row,
    get_effective_crypto_config,
    EffectiveCryptoConfig,
    normalize_crypto_timeframe,
    _get_threshold_mode,
    get_crypto_matrix_fingerprint,
    load_matrix_document,
    reload_matrix_document,
    _default_matrix_path,
)


class TestNormalizeCryptoTimeframe(unittest.TestCase):
    """Test timeframe normalization."""

    def test_15m_variants(self):
        """Various 15m labels normalize correctly."""
        for tf in ["15m", "15min", "fifteen_min", "kx15m"]:
            self.assertEqual(normalize_crypto_timeframe(tf), "15m")

    def test_1h_variants(self):
        """Various 1h labels normalize correctly."""
        for tf in ["1h", "1hr", "hourly", "hour", "60m", "60min"]:
            self.assertEqual(normalize_crypto_timeframe(tf), "1h")

    def test_daily_variants(self):
        """Various daily labels normalize correctly."""
        for tf in ["daily", "d1", "day", "1d"]:
            self.assertEqual(normalize_crypto_timeframe(tf), "daily")

    def test_weekly_variants(self):
        """Various weekly labels normalize correctly."""
        for tf in ["weekly", "w1", "week"]:
            self.assertEqual(normalize_crypto_timeframe(tf), "weekly")

    def test_monthly_variants(self):
        """Various monthly labels normalize correctly."""
        for tf in ["monthly", "1m", "month", "mo"]:
            self.assertEqual(normalize_crypto_timeframe(tf), "monthly")

    def test_annual_variants(self):
        """Various annual labels normalize correctly."""
        for tf in ["annual", "yearly", "y1", "year", "kxannual"]:
            self.assertEqual(normalize_crypto_timeframe(tf), "annual")

    def test_default_fallback(self):
        """Unknown timeframes default to 15m."""
        self.assertEqual(normalize_crypto_timeframe("unknown"), "15m")


class TestGetThresholdMode(unittest.TestCase):
    """Test profile selection from env var and runtime."""

    @patch.dict(os.environ, {"MERID_CRYPTO_EDGE_PRODUCTION_PROFILE": "modern_tradeable_kalshi_v1"}, clear=False)
    def test_env_var_priority(self):
        """MERID_CRYPTO_EDGE_PRODUCTION_PROFILE env var is respected."""
        mode = _get_threshold_mode()
        self.assertEqual(mode, "modern_tradeable_kalshi_v1")

    def test_default_returns_something(self):
        """Default returns a valid profile string."""
        # Note: Actual value depends on environment state
        # We just verify it returns a non-empty string
        mode = _get_threshold_mode()
        self.assertIsInstance(mode, str)
        self.assertTrue(len(mode) > 0)


class TestSchemaV2Profile(unittest.TestCase):
    """Test modern_tradeable_kalshi_v1 profile resolution."""

    @classmethod
    def setUpClass(cls):
        """Ensure fresh matrix document load."""
        reload_matrix_document()

    def test_btc_15m_edge(self):
        """BTC 15m edge is 0.011 (1.1%) in v2 profile."""
        row = resolve_merged_row(
            asset="BTC",
            timeframe="15m",
            archetype="directional",
            profile_key="modern_tradeable_kalshi_v1",
        )
        self.assertEqual(row["matrix_schema_version"], 2)
        self.assertEqual(row["matrix_source_profile"], "modern_tradeable_kalshi_v1")
        self.assertEqual(row["matrix_source_type"], "edge_grid_v2")

        edge = Decimal(row["directional_min_edge"])
        self.assertEqual(edge, Decimal("0.011"))

    def test_eth_1h_edge(self):
        """ETH 1h edge is 0.014 in v2 profile."""
        row = resolve_merged_row(
            asset="ETH",
            timeframe="1h",
            archetype="directional",
            profile_key="modern_tradeable_kalshi_v1",
        )
        self.assertEqual(row["matrix_schema_version"], 2)
        edge = Decimal(row["directional_min_edge"])
        self.assertEqual(edge, Decimal("0.014"))

    def test_doge_annual_edge(self):
        """DOGE annual edge is 0.034 (3.4%) in v2 profile."""
        row = resolve_merged_row(
            asset="DOGE",
            timeframe="annual",
            archetype="directional",
            profile_key="modern_tradeable_kalshi_v1",
        )
        self.assertEqual(row["matrix_schema_version"], 2)
        edge = Decimal(row["directional_min_edge"])
        self.assertEqual(edge, Decimal("0.034"))

    def test_v2_includes_confidence_bands(self):
        """V2 profile includes confidence bands in result."""
        row = resolve_merged_row(
            asset="BTC",
            timeframe="15m",
            archetype="directional",
            profile_key="modern_tradeable_kalshi_v1",
        )
        self.assertIn("confidence_bands", row)
        bands = row["confidence_bands"]
        self.assertIsInstance(bands, list)
        self.assertEqual(len(bands), 3)  # no_trade, cautious, confident

        band_names = [b["name"] for b in bands]
        self.assertIn("no_trade", band_names)
        self.assertIn("cautious", band_names)
        self.assertIn("confident", band_names)

    def test_v2_includes_fee_aware_settings(self):
        """V2 profile includes fee-aware settings."""
        row = resolve_merged_row(
            asset="BTC",
            timeframe="15m",
            archetype="directional",
            profile_key="modern_tradeable_kalshi_v1",
        )
        self.assertIn("fee_aware_settings", row)
        fee_settings = row["fee_aware_settings"]
        self.assertIsInstance(fee_settings, dict)

    def test_v2_includes_min_notional(self):
        """V2 profile includes min_notional settings."""
        row = resolve_merged_row(
            asset="BTC",
            timeframe="15m",
            archetype="directional",
            profile_key="modern_tradeable_kalshi_v1",
        )
        self.assertIn("min_notional", row)
        min_notional = row["min_notional"]
        self.assertIsInstance(min_notional, dict)
        self.assertIn("contracts", min_notional)
        self.assertIn("usd", min_notional)

    def test_v2_base_kelly_fraction(self):
        """V2 profile includes base_kelly_fraction."""
        row = resolve_merged_row(
            asset="BTC",
            timeframe="15m",
            archetype="directional",
            profile_key="modern_tradeable_kalshi_v1",
        )
        self.assertIn("base_kelly_fraction", row)
        base_kelly = Decimal(row["base_kelly_fraction"])
        self.assertEqual(base_kelly, Decimal("0.20"))

    def test_v2_max_price_cents_grid(self):
        """V2 profile resolves max_price_cents from grid."""
        row = resolve_merged_row(
            asset="BTC",
            timeframe="15m",
            archetype="directional",
            profile_key="modern_tradeable_kalshi_v1",
        )
        # max_price_cents may be None if not in grid, or a value
        self.assertIn("max_price_cents", row)
        self.assertEqual(row["max_price_cents"], 55)  # BTC 15m cap from config

    def test_v2_quick_win_max_price_cents_grid(self):
        """V2 profile resolves quick_win_max_price_cents for high-probability trades."""
        row = resolve_merged_row(
            asset="BTC",
            timeframe="15m",
            archetype="directional",
            profile_key="modern_tradeable_kalshi_v1",
        )
        # quick_win_max_price_cents should be present for 15m timeframe
        self.assertIn("quick_win_max_price_cents", row)
        self.assertEqual(row["quick_win_max_price_cents"], 48)  # BTC 15m quick_win cap from config

    def test_v2_quick_win_band_in_confidence_bands(self):
        """V2 profile includes quick_win band in confidence_bands."""
        row = resolve_merged_row(
            asset="BTC",
            timeframe="15m",
            archetype="directional",
            profile_key="modern_tradeable_kalshi_v1",
        )
        confidence_bands = row.get("confidence_bands", [])
        self.assertIsInstance(confidence_bands, list)
        quick_win_band = next((b for b in confidence_bands if b.get("name") == "quick_win"), None)
        self.assertIsNotNone(quick_win_band)
        self.assertEqual(quick_win_band["min_conf"], 0.80)
        self.assertEqual(quick_win_band["max_conf"], 0.92)
        self.assertEqual(quick_win_band["kelly_multiplier"], 0.6)


class TestSchemaV1Profiles(unittest.TestCase):
    """Test legacy and modern profiles still work."""

    @classmethod
    def setUpClass(cls):
        """Ensure fresh matrix document load."""
        reload_matrix_document()

    def test_legacy_profile(self):
        """Legacy profile returns v1 schema."""
        row = resolve_merged_row(
            asset="BTC",
            timeframe="15m",
            archetype="directional",
            profile_key="legacy",
        )
        self.assertEqual(row["matrix_schema_version"], 1)
        self.assertEqual(row["matrix_source_profile"], "legacy")
        self.assertEqual(row["matrix_source_type"], "rows_legacy")

    def test_modern_profile(self):
        """Modern profile returns v1 schema."""
        row = resolve_merged_row(
            asset="BTC",
            timeframe="15m",
            archetype="directional",
            profile_key="modern",
        )
        self.assertEqual(row["matrix_schema_version"], 1)
        self.assertEqual(row["matrix_source_profile"], "modern")
        self.assertEqual(row["matrix_source_type"], "rows_legacy")

    def test_legacy_edge_values_unchanged(self):
        """Legacy profile edge values are stable."""
        row = resolve_merged_row(
            asset="BTC",
            timeframe="15m",
            archetype="directional",
            profile_key="legacy",
        )
        edge = Decimal(row["directional_min_edge"])
        # Legacy has 4% edge for 15m
        self.assertEqual(edge, Decimal("0.04"))

    def test_modern_edge_values_unchanged(self):
        """Modern profile edge values are stable."""
        row = resolve_merged_row(
            asset="BTC",
            timeframe="15m",
            archetype="directional",
            profile_key="modern",
        )
        edge = Decimal(row["directional_min_edge"])
        # Modern has 1.1% edge for 15m (from wildcard row: 0.011)
        self.assertEqual(edge, Decimal("0.011"))


class TestEnvVarOverrides(unittest.TestCase):
    """Test environment variable overrides."""

    @patch.dict(os.environ, {"MERID_CRYPTO_EDGE_PRODUCTION_PROFILE": "modern_tradeable_kalshi_v1"}, clear=False)
    def test_env_var_selects_v2_profile(self):
        """MERID_CRYPTO_EDGE_PRODUCTION_PROFILE selects v2 profile."""
        # Reload to pick up env var
        reload_matrix_document()

        row = resolve_merged_row(
            asset="BTC",
            timeframe="15m",
            archetype="directional",
        )
        # Should use env var profile
        self.assertEqual(row["matrix_schema_version"], 2)

    @patch.dict(os.environ, {"MERID_CRYPTO_EDGE_PRODUCTION_PROFILE": "modern"}, clear=False)
    def test_env_var_selects_v1_profile(self):
        """MERID_CRYPTO_EDGE_PRODUCTION_PROFILE can also select v1 profile."""
        reload_matrix_document()

        row = resolve_merged_row(
            asset="BTC",
            timeframe="15m",
            archetype="directional",
        )
        self.assertEqual(row["matrix_schema_version"], 1)
        self.assertEqual(row["matrix_source_profile"], "modern")


class TestCryptoMatrixFingerprint(unittest.TestCase):
    """Test fingerprint generation."""

    def test_fingerprint_generation(self):
        """Fingerprint is generated successfully."""
        fingerprint = get_crypto_matrix_fingerprint()
        self.assertIsInstance(fingerprint, str)
        self.assertEqual(len(fingerprint), 16)  # First 16 chars of SHA256

    def test_fingerprint_changes_with_profile(self):
        """Different profiles produce different fingerprints."""
        # This test relies on env var behavior; we mock it
        with patch("merid.prediction.crypto_threshold_matrix._get_threshold_mode", return_value="legacy"):
            fp_legacy = get_crypto_matrix_fingerprint()

        with patch("merid.prediction.crypto_threshold_matrix._get_threshold_mode", return_value="modern_tradeable_kalshi_v1"):
            fp_v2 = get_crypto_matrix_fingerprint()

        self.assertNotEqual(fp_legacy, fp_v2)


class TestEffectiveCryptoConfigV2(unittest.TestCase):
    """Test EffectiveCryptoConfig dataclass with v2 fields."""

    def test_dataclass_includes_v2_fields(self):
        """EffectiveCryptoConfig includes all v2 fields."""
        config = EffectiveCryptoConfig(
            agent_name="test_agent",
            market_id="KXBTC-15M-250101",
            profile="modern_tradeable_kalshi_v1",
            archetype="directional",
            asset="BTC",
            timeframe="15m",
            directional_min_edge=Decimal("0.011"),
            sentiment_vol_regime_min_edge=Decimal("0.011"),
            contrarian_sentiment_min=75.0,
            contrarian_model_gap_min=0.10,
            mm_max_spread_cents=Decimal("10"),
            pm_risk_max_spread_cents=Decimal("10"),
            tier_min_edge_floor=Decimal("0.011"),
            kelly_fraction=Decimal("0.10"),
            min_order_notional_usd=0.35,
            vol_low_threshold=None,
            vol_high_threshold=None,
            vol_size_mult_low=None,
            vol_size_mult_mid=None,
            vol_size_mult_high=None,
            spot_strike_veto_flag=False,
            matrix_source_path="/config/crypto_threshold_matrix.yaml",
            matrix_schema_version=2,
            matrix_source_profile="modern_tradeable_kalshi_v1",
            matrix_source_type="edge_grid_v2",
            confidence_bands=[
                {"name": "no_trade", "min_conf": 0.0, "max_conf": 0.6, "allow_trades": False},
                {"name": "cautious", "min_conf": 0.6, "max_conf": 0.75, "allow_trades": True, "kelly_multiplier": 0.5},
                {"name": "confident", "min_conf": 0.75, "max_conf": 1.0, "allow_trades": True, "kelly_multiplier": 1.0},
            ],
            fee_aware_settings={"min_edge_cents": 0.35, "avoid_mid_fee_band": True},
            min_notional={"contracts": 1, "usd": 0.35},
            base_kelly_fraction=Decimal("0.20"),
            confidence_tier_multiplier={"no_trade": 0.0, "cautious": 0.5, "confident": 1.0},
        )

        # Verify v2 fields are accessible
        self.assertEqual(config.matrix_schema_version, 2)
        self.assertEqual(config.matrix_source_type, "edge_grid_v2")
        self.assertIsNotNone(config.confidence_bands)
        self.assertEqual(len(config.confidence_bands), 3)

        # Verify to_dict works with v2 fields
        d = config.to_dict()
        self.assertEqual(d["matrix_schema_version"], 2)
        self.assertEqual(d["matrix_source_type"], "edge_grid_v2")
        self.assertIn("confidence_bands", d)


if __name__ == "__main__":
    unittest.main()
