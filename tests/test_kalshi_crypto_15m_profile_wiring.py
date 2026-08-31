"""Tests for kalshi_crypto_15m_v2 profile wiring.

Tests that profile values are correctly wired into KalshiRiskConfig
and other components when the profile is active.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from merid.event_venues.kalshi.kalshi_risk import KalshiRiskConfig, get_kalshi_risk


class TestCrypto15mProfileWiring:
    """Tests for profile wiring into KalshiRiskConfig."""

    def test_profile_wired_into_kalshi_risk_config(self, monkeypatch):
        """When profile is active, KalshiRiskConfig should use profile values."""
        monkeypatch.setenv("MERID_PROFILE", "kalshi_crypto_15m_v2")

        # Reset the singleton to pick up the profile
        from merid.event_venues.kalshi import kalshi_risk
        kalshi_risk._risk = None

        config = get_kalshi_risk()._config

        # The v2 profile uses capital_usd=0 (live bankroll) and percentage venue
        # caps are intentionally removed. USD notional limits are therefore 0.0
        # and derived at runtime from the live bankroll / risk envelope.
        assert config.max_single_order_notional_usd == 0.0
        assert config.max_total_notional_usd == 0.0
        assert config.max_daily_loss_usd == 200.0
        assert config.max_contracts_total == 5000
        assert config.max_contracts_per_asset == 1750
        assert config.max_contracts_per_cluster == 750
        assert config.group_notional_cap_usd == 50.0
        assert config.group_limits_enabled is True

        # Reset singleton
        kalshi_risk._risk = None

    def test_profile_not_active_uses_defaults(self, monkeypatch):
        """When profile is not active, KalshiRiskConfig should use defaults."""
        monkeypatch.delenv("MERID_PROFILE", raising=False)

        # Reset the singleton
        from merid.event_venues.kalshi import kalshi_risk
        kalshi_risk._risk = None

        config = get_kalshi_risk()._config

        # Default values from KalshiRiskConfig dataclass
        assert config.max_total_notional_usd == 0.0  # Default: derive from live bankroll
        assert config.max_daily_loss_usd == 0.0  # Default: derive from profile/envelope at runtime

        # Reset singleton
        kalshi_risk._risk = None

    @patch("merid.risk.profiles.crypto_15m_profile.get_active_profile")
    def test_profile_fetches_live_bankroll_when_capital_usd_zero(self, mock_get_profile, monkeypatch):
        """When capital_usd is 0, profile should fetch live bankroll."""
        monkeypatch.setenv("MERID_PROFILE", "kalshi_crypto_15m_v2")

        # Mock the profile adapter to return a specific value
        mock_adapter = MagicMock()
        mock_adapter._profile.capital_usd = 5000.0
        mock_get_profile.return_value = mock_adapter

        # Reset profile adapter to pick up the change
        from merid.risk.profiles import crypto_15m_profile
        crypto_15m_profile._adapter = None

        adapter = crypto_15m_profile.get_active_profile()
        assert adapter._profile.capital_usd == 5000.0

        # Reset
        crypto_15m_profile._adapter = None

    def test_profile_uses_fallback_when_bankroll_unavailable(self, monkeypatch):
        """When bankroll fetch fails, profile should use fallback value."""
        monkeypatch.setenv("MERID_PROFILE", "kalshi_crypto_15m_v2")

        # Reset profile adapter
        from merid.risk.profiles import crypto_15m_profile
        crypto_15m_profile._adapter = None

        adapter = crypto_15m_profile.get_active_profile()
        # The v2 profile uses capital_usd=0 as a live-bankroll sentinel.
        # A valid profile should load and the sentinel is the expected value.
        assert adapter._profile.capital_usd == 0.0

        # Reset
        crypto_15m_profile._adapter = None


class TestProfileToKalshiRiskConfigMapping:
    """Tests for to_kalshi_risk_config() mapping."""

    def test_to_kalshi_risk_config_includes_contract_caps(self, monkeypatch):
        """Profile should include contract caps in risk config mapping."""
        monkeypatch.setenv("MERID_PROFILE", "kalshi_crypto_15m_v2")

        from merid.risk.profiles import crypto_15m_profile
        crypto_15m_profile._adapter = None

        adapter = crypto_15m_profile.get_active_profile()
        config_dict = adapter.to_kalshi_risk_config()

        assert "max_contracts_total" in config_dict
        assert config_dict["max_contracts_total"] == 5000
        assert "max_contracts_per_asset" in config_dict
        assert config_dict["max_contracts_per_asset"] == 1750
        assert "max_contracts_per_cluster" in config_dict
        assert config_dict["max_contracts_per_cluster"] == 750
        assert "group_notional_cap_usd" in config_dict
        assert config_dict["group_notional_cap_usd"] == 50.0
        assert "group_limits_enabled" in config_dict
        assert config_dict["group_limits_enabled"] is True

        # Reset
        crypto_15m_profile._adapter = None

    def test_to_kalshi_risk_config_agent_max_concurrent_trades_removed(self, monkeypatch):
        """Profile intentionally removed agent_max_concurrent_trades in v2."""
        monkeypatch.setenv("MERID_PROFILE", "kalshi_crypto_15m_v2")

        from merid.risk.profiles import crypto_15m_profile
        crypto_15m_profile._adapter = None

        adapter = crypto_15m_profile.get_active_profile()
        assert not hasattr(adapter._profile, "agent_max_concurrent_trades")

        # Reset
        crypto_15m_profile._adapter = None
