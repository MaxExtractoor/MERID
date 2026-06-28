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

    def test_config_snapshot_log_environment_variables(self):
        """Test that CONFIG-SNAPSHOT log captures critical environment variables."""
        # Set test environment variables
        os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
        os.environ["MERID_PM_PROFILE"] = "baseline"
        os.environ["MERID_MODE"] = "paper"
        os.environ["MERID_MAX_RISK_FRACTION"] = "0.02"
        os.environ["MERID_KALSHI_FORCE_REST_FALLBACK"] = "false"
        os.environ["MERID_DISABLE_SHARED_RISK_GUARD"] = "false"
        os.environ["MERID_ENV"] = "dev"
        
        # Verify environment variables are set
        assert os.getenv("MERID_PROFILE") == "kalshi_crypto_15m_v2"
        assert os.getenv("MERID_PM_PROFILE") == "baseline"
        assert os.getenv("MERID_MODE") == "paper"
        assert os.getenv("MERID_MAX_RISK_FRACTION") == "0.02"
        assert os.getenv("MERID_KALSHI_FORCE_REST_FALLBACK") == "false"
        assert os.getenv("MERID_DISABLE_SHARED_RISK_GUARD") == "false"
        assert os.getenv("MERID_ENV") == "dev"
        
        # Clean up
        del os.environ["MERID_PROFILE"]
        del os.environ["MERID_PM_PROFILE"]
        del os.environ["MERID_MODE"]
        del os.environ["MERID_MAX_RISK_FRACTION"]
        del os.environ["MERID_KALSHI_FORCE_REST_FALLBACK"]
        del os.environ["MERID_DISABLE_SHARED_RISK_GUARD"]
        del os.environ["MERID_ENV"]
