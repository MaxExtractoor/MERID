"""Tests for capabilities.py profile integration.

Tests that max_concurrent_trades is correctly wired from the profile
when the profile is active.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from merid.guardrails.capabilities import _compute_kalshi_max_notional_from_config


class TestCapabilitiesProfileIntegration:
    """Tests for capabilities.py profile integration."""

    def test_max_concurrent_trades_default_when_no_profile(self, monkeypatch):
        """When profile is not active, max_concurrent_trades should use default."""
        monkeypatch.delenv("MERID_PROFILE", raising=False)

        with patch("merid.risk.profiles.crypto_15m_profile.is_profile_active", return_value=False):
            # Reset the risk manager singleton
            from merid.event_venues.kalshi import kalshi_risk
            kalshi_risk._risk = None

            max_notional = _compute_kalshi_max_notional_from_config()

            # With capital_usd=50.0, max_single_order=2.5 (5% of 50), max_concurrent_trades=3
            # max_notional should be 3 * 2.5 = 7.5
            assert max_notional == 7.5

            # Reset
            kalshi_risk._risk = None

    def test_max_concurrent_trades_profile_error_fallback(self, monkeypatch):
        """When profile read fails, max_concurrent_trades should use default."""
        monkeypatch.setenv("MERID_PROFILE", "kalshi_crypto_15m_v2")

        with patch("merid.risk.profiles.crypto_15m_profile.is_profile_active", return_value=True):
            with patch("merid.risk.profiles.crypto_15m_profile.get_active_profile", side_effect=Exception("Profile error")):
                # Reset the risk manager singleton
                from merid.event_venues.kalshi import kalshi_risk
                kalshi_risk._risk = None

                max_notional = _compute_kalshi_max_notional_from_config()

                # With capital_usd=50.0, max_single_order=2.5 (5% of 50), max_concurrent_trades=3
                # max_notional should be 3 * 2.5 = 7.5 even on profile error (envelope still computes)
                assert max_notional == 7.5

                # Reset
                kalshi_risk._risk = None
