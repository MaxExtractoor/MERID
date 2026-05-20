"""Tests for kalshi_crypto_configurator.py environment variable backing.

Tests that verify strike width bounds respect environment variable overrides.
"""

import os
import pytest


class TestKalshiCryptoConfiguratorEnvBacking:
    """Test kalshi_crypto_configurator.py respects environment variable overrides."""

    def test_kalshi_strike_width_env_overrides(self, monkeypatch):
        """Set KALSHI_STRIKE_WIDTH_MIN/MAX and verify configurator uses them."""
        monkeypatch.setenv("KALSHI_STRIKE_WIDTH_MIN", "0.02")
        monkeypatch.setenv("KALSHI_STRIKE_WIDTH_MAX", "0.10")
        
        # Re-import to pick up env vars
        import importlib
        import merid.trading.kalshi_crypto_configurator
        importlib.reload(merid.trading.kalshi_crypto_configurator)
        
        from merid.trading.kalshi_crypto_configurator import WIDTH_MIN, WIDTH_MAX
        
        assert WIDTH_MIN == 0.02
        assert WIDTH_MAX == 0.10
