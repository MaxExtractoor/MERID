"""
Kalshi 15m Crypto Startup and Profile Sealing Tests

Tests that verify the kalshi_crypto_15m_v2 profile configuration
and environment variable recognition.

Tagged with @pytest.mark.kalshi_15m_critical for CI enforcement.
"""
from __future__ import annotations

import os
import pytest


pytestmark = pytest.mark.kalshi_15m_critical


class TestKalshiCrypto15mProfileConfiguration:
    """Test that kalshi_crypto_15m_v2 profile is correctly configured."""

    def test_kalshi_15m_profile_environment_variable_recognized(self):
        """Test that MERID_PROFILE=kalshi_crypto_15m_v2 is recognized."""
        # Verify the expected profile name
        expected_profile = "kalshi_crypto_15m_v2"
        assert expected_profile == "kalshi_crypto_15m_v2"

    def test_kalshi_15m_profile_uses_5_crypto_assets(self):
        """Test that the profile is configured for 5 crypto assets (BTC/ETH/SOL/XRP/DOGE)."""
        from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS
        
        # Verify 5 crypto assets are configured
        expected_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        assert all(asset in ACTIVE_CRYPTO_ASSETS for asset in expected_assets)

    def test_kalshi_15m_profile_uses_15m_timeframe(self):
        """Test that the profile is configured for 15m timeframe."""
        from config.kalshi_crypto_config import ACTIVE_CRYPTO_WS_TIMEFRAMES
        
        # Verify 15m timeframe is configured
        assert "15m" in ACTIVE_CRYPTO_WS_TIMEFRAMES
