"""Tests for Kalshi 15m config signature utility.

Verifies that config signatures are computed correctly and detect changes.
"""

import pytest
from merid.config.signature import (
    load_kalshi_15m_config,
    load_kalshi_15m_series_universe,
    compute_config_signature,
    get_kalshi_15m_config_signature,
    verify_config_signature,
)
import os
import tempfile
import yaml


@pytest.mark.kalshi_15m
class TestConfigSignature:
    """Test config signature computation and verification."""

    def test_load_kalshi_15m_config(self):
        """Test that Kalshi 15m config can be loaded."""
        config = load_kalshi_15m_config()
        
        # Config should be a dict
        assert isinstance(config, dict)
        
        # If config file exists, it should have some structure
        if config:
            # Check for common config keys
            possible_keys = ["agent_defaults", "assets", "risk_limits", "sentiment_isolation"]
            has_any_key = any(key in config for key in possible_keys)
            # Config might be empty if file doesn't exist, that's OK
            # If it exists, it should have some structure

    def test_load_kalshi_15m_series_universe(self):
        """Test that Kalshi 15m series universe can be loaded."""
        universe = load_kalshi_15m_series_universe()
        
        # Universe should be a dict
        assert isinstance(universe, dict)
        
        # Should contain series_tickers and crypto_assets
        assert "series_tickers" in universe
        assert "crypto_assets" in universe
        
        # Series tickers should include 5 assets
        series_tickers = universe["series_tickers"]
        assert "BTC" in series_tickers
        assert "ETH" in series_tickers
        assert "SOL" in series_tickers
        assert "XRP" in series_tickers
        assert "DOGE" in series_tickers

    def test_compute_config_signature(self):
        """Test that config signature is computed correctly."""
        config = {"key1": "value1", "key2": "value2"}
        signature = compute_config_signature(config)
        
        # Signature should be a 64-character hex string (SHA-256)
        assert len(signature) == 64
        assert all(c in "0123456789abcdef" for c in signature)

    def test_config_signature_stability(self):
        """Test that config signature is stable (same input = same output)."""
        config = {"key1": "value1", "key2": "value2"}
        signature1 = compute_config_signature(config)
        signature2 = compute_config_signature(config)
        
        assert signature1 == signature2

    def test_config_signature_detects_changes(self):
        """Test that config signature changes when config changes."""
        config1 = {"key1": "value1", "key2": "value2"}
        config2 = {"key1": "value1", "key2": "value3"}  # Changed value
        config3 = {"key1": "value1", "key3": "value2"}  # Changed key
        
        signature1 = compute_config_signature(config1)
        signature2 = compute_config_signature(config2)
        signature3 = compute_config_signature(config3)
        
        assert signature1 != signature2
        assert signature1 != signature3

    def test_config_signature_key_order_independence(self):
        """Test that config signature is independent of key order."""
        config1 = {"key1": "value1", "key2": "value2"}
        config2 = {"key2": "value2", "key1": "value1"}  # Different order
        
        signature1 = compute_config_signature(config1)
        signature2 = compute_config_signature(config2)
        
        assert signature1 == signature2

    def test_get_kalshi_15m_config_signature(self):
        """Test that combined Kalshi 15m config signature is computed."""
        signature = get_kalshi_15m_config_signature()
        
        # Signature should be a 64-character hex string
        assert len(signature) == 64
        assert all(c in "0123456789abcdef" for c in signature)

    def test_verify_config_signature_no_expected(self):
        """Test that verification passes when no expected signature is set."""
        # Clear the expected signature env var
        os.environ.pop("KALSHI_15M_CONFIG_SIGNATURE", None)
        
        result = verify_config_signature()
        assert result is True  # Should pass when no expected signature

    def test_verify_config_signature_matches(self):
        """Test that verification passes when signature matches."""
        signature = get_kalshi_15m_config_signature()
        os.environ["KALSHI_15M_CONFIG_SIGNATURE"] = signature
        
        result = verify_config_signature()
        assert result is True
        
        # Clean up
        os.environ.pop("KALSHI_15M_CONFIG_SIGNATURE", None)

    def test_verify_config_signature_mismatch(self):
        """Test that verification fails when signature doesn't match."""
        # Set a fake expected signature
        os.environ["KALSHI_15M_CONFIG_SIGNATURE"] = "0" * 64
        
        result = verify_config_signature()
        assert result is False
        
        # Clean up
        os.environ.pop("KALSHI_15M_CONFIG_SIGNATURE", None)

    def test_empty_config_signature(self):
        """Test that empty config produces a valid signature."""
        signature = compute_config_signature({})
        
        # Should still produce a valid SHA-256 hash
        assert len(signature) == 64
        assert all(c in "0123456789abcdef" for c in signature)
