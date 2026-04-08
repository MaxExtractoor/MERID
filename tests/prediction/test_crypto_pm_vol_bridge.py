"""Tests for crypto vol-band/size-multiplier wiring and PM vol bridge logic."""

from decimal import Decimal

import pytest

from merid.prediction.crypto_thresholds import (
    CryptoThresholds,
    VolBand,
    classify_vol_band,
    vol_band_size_multiplier,
    get_crypto_thresholds,
    apply_crypto_strategy_thresholds_to_config,
    is_crypto_agent,
    get_active_profile,
)
from merid.prediction.strategy import StrategyConfig


class TestIsCorrectAgent:
    """Test is_crypto_agent detection."""

    def test_btc_name_detected(self):
        assert is_crypto_agent(agent_name="BTC_15M") is True

    def test_eth_name_detected(self):
        assert is_crypto_agent(agent_name="ETH_1H") is True

    def test_crypto_15m_mm_detected(self):
        assert is_crypto_agent(agent_name="CRYPTO_15M_MM") is True

    def test_crypto_lower_case_detected(self):
        assert is_crypto_agent(agent_name="sol_daily") is True

    def test_non_crypto_name(self):
        assert is_crypto_agent(agent_name="MACRO_DIRECTIONAL") is False

    def test_asset_list_detection(self):
        assert is_crypto_agent(agent_name="generic", assets=["BTC"]) is True

    def test_empty_asset_list_no_match(self):
        assert is_crypto_agent(agent_name="generic", assets=[]) is False

    def test_none_inputs_return_false(self):
        assert is_crypto_agent() is False


class TestGetCryptoThresholds:
    """Test get_crypto_thresholds returns correct values per profile."""

    def test_modern_profile(self):
        t = get_crypto_thresholds("modern")
        assert isinstance(t, CryptoThresholds)
        assert t.min_edge_early < Decimal("0.05")  # more lenient than strict
        assert t.edge_floor_profile == "medium"

    def test_legacy_profile(self):
        t = get_crypto_thresholds("legacy")
        assert isinstance(t, CryptoThresholds)
        assert t.min_edge_early == Decimal("0.05")
        assert t.edge_floor_profile == "strict"

    def test_unknown_profile_falls_back_to_modern(self):
        t = get_crypto_thresholds("nonexistent_profile")
        t_modern = get_crypto_thresholds("modern")
        assert t == t_modern

    def test_none_profile_uses_env_default(self, monkeypatch):
        monkeypatch.delenv("MERID_CRYPTO_EDGE_PRODUCTION_PROFILE", raising=False)
        t = get_crypto_thresholds(None)
        t_modern = get_crypto_thresholds("modern")
        assert t == t_modern


class TestApplyCryptoThresholds:
    """Test apply_crypto_strategy_thresholds_to_config."""

    def test_applies_to_crypto_agent(self):
        config = StrategyConfig()
        original_early = config.min_edge_early
        result = apply_crypto_strategy_thresholds_to_config(
            config, agent_name="BTC_15M", profile="modern"
        )
        assert result is True
        # Modern profile has more lenient threshold than strict default
        assert config.min_edge_early < original_early

    def test_skips_non_crypto_agent(self):
        config = StrategyConfig()
        original_early = config.min_edge_early
        result = apply_crypto_strategy_thresholds_to_config(
            config, agent_name="MACRO_DIRECTIONAL"
        )
        assert result is False
        assert config.min_edge_early == original_early

    def test_applies_kelly_fraction(self):
        config = StrategyConfig()
        apply_crypto_strategy_thresholds_to_config(config, agent_name="BTC_15M", profile="modern")
        t = get_crypto_thresholds("modern")
        assert config.kelly_fraction == t.kelly_fraction

    def test_applies_edge_floor_profile(self):
        config = StrategyConfig()
        apply_crypto_strategy_thresholds_to_config(config, agent_name="ETH_1H", profile="modern")
        assert config.edge_floor_profile == "medium"

    def test_legacy_profile_sets_strict_floor(self):
        config = StrategyConfig()
        apply_crypto_strategy_thresholds_to_config(config, agent_name="BTC_15M", profile="legacy")
        assert config.edge_floor_profile == "strict"

    def test_crypto_15m_mm_name_matches(self):
        """CRYPTO_15M_MM should be detected as crypto."""
        config = StrategyConfig()
        result = apply_crypto_strategy_thresholds_to_config(
            config, agent_name="CRYPTO_15M_MM", profile="modern"
        )
        assert result is True

    def test_asset_list_triggers_application(self):
        config = StrategyConfig()
        result = apply_crypto_strategy_thresholds_to_config(
            config, agent_name="generic_mm", assets=["SOL"], profile="modern"
        )
        assert result is True


class TestVolBandClassification:
    """Test vol band classification and size multipliers."""

    def _modern_thresholds(self) -> CryptoThresholds:
        return get_crypto_thresholds("modern")

    def test_low_vol_band(self):
        t = self._modern_thresholds()
        band = classify_vol_band(t.vol_low_threshold - 0.001, thresholds=t)
        assert band == VolBand.LOW

    def test_mid_vol_band(self):
        t = self._modern_thresholds()
        mid_vol = (t.vol_low_threshold + t.vol_high_threshold) / 2
        band = classify_vol_band(mid_vol, thresholds=t)
        assert band == VolBand.MID

    def test_high_vol_band(self):
        t = self._modern_thresholds()
        band = classify_vol_band(t.vol_high_threshold + 0.001, thresholds=t)
        assert band == VolBand.HIGH

    def test_exact_low_threshold_is_mid(self):
        t = self._modern_thresholds()
        # Exactly at low threshold → MID (not below → not LOW)
        band = classify_vol_band(t.vol_low_threshold, thresholds=t)
        assert band == VolBand.MID

    def test_size_mult_low_band(self):
        t = self._modern_thresholds()
        mult = vol_band_size_multiplier(VolBand.LOW, thresholds=t)
        assert mult == t.size_mult_low
        assert mult < 1.0

    def test_size_mult_mid_band_is_one(self):
        t = self._modern_thresholds()
        mult = vol_band_size_multiplier(VolBand.MID, thresholds=t)
        assert mult == 1.0

    def test_size_mult_high_band(self):
        t = self._modern_thresholds()
        mult = vol_band_size_multiplier(VolBand.HIGH, thresholds=t)
        assert mult == t.size_mult_high
        assert mult < 1.0

    def test_vol_band_values_are_string_enum(self):
        """VolBand values should be plain strings."""
        assert VolBand.LOW.value == "low"
        assert VolBand.MID.value == "mid"
        assert VolBand.HIGH.value == "high"

    def test_legacy_thresholds_different_from_modern(self):
        modern = get_crypto_thresholds("modern")
        legacy = get_crypto_thresholds("legacy")
        # Legacy has wider vol bands than modern
        assert legacy.vol_low_threshold >= modern.vol_low_threshold

    def test_zero_vol_is_low_band(self):
        """Zero volatility should map to LOW."""
        band = classify_vol_band(0.0)
        assert band == VolBand.LOW

    def test_extreme_vol_is_high_band(self):
        """Extremely high volatility should map to HIGH."""
        band = classify_vol_band(1.0)
        assert band == VolBand.HIGH


class TestEnvProfileSelector:
    """Test MERID_CRYPTO_EDGE_PRODUCTION_PROFILE env var selection."""

    def test_modern_env_returns_modern(self, monkeypatch):
        monkeypatch.setenv("MERID_CRYPTO_EDGE_PRODUCTION_PROFILE", "modern")
        assert get_active_profile() == "modern"

    def test_legacy_env_returns_legacy(self, monkeypatch):
        monkeypatch.setenv("MERID_CRYPTO_EDGE_PRODUCTION_PROFILE", "legacy")
        assert get_active_profile() == "legacy"

    def test_invalid_env_falls_back_to_modern(self, monkeypatch):
        monkeypatch.setenv("MERID_CRYPTO_EDGE_PRODUCTION_PROFILE", "bogus_value")
        assert get_active_profile() == "modern"

    def test_uppercase_env_normalized(self, monkeypatch):
        monkeypatch.setenv("MERID_CRYPTO_EDGE_PRODUCTION_PROFILE", "MODERN")
        assert get_active_profile() == "modern"
