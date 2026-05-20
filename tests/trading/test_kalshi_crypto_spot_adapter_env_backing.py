"""Tests for kalshi_crypto_spot_adapter.py environment variable backing.

Tests that verify fallback size factor respects environment variable overrides.
"""

import os
import pytest


class TestKalshiCryptoSpotAdapterEnvBacking:
    """Test kalshi_crypto_spot_adapter.py respects environment variable overrides."""

    def test_kalshi_spot_fallback_size_factor_env_override(self, monkeypatch):
        """Set KALSHI_SPOT_FALLBACK_SIZE_FACTOR and verify fallback sizing respects it."""
        monkeypatch.setenv("KALSHI_SPOT_FALLBACK_SIZE_FACTOR", "0.5")
        
        # Re-import to pick up env var
        import importlib
        import merid.trading.kalshi_crypto_spot_adapter
        importlib.reload(merid.trading.kalshi_crypto_spot_adapter)
        
        from merid.trading.kalshi_crypto_spot_adapter import SpotPolicy
        
        # Create a SpotPolicy instance and verify it uses the env value
        policy = SpotPolicy()
        assert policy.fallback_size_factor == 0.5
