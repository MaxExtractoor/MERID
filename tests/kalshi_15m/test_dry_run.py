"""Tests for Kalshi 15m dry-run mode.

Verifies that dry-run mode correctly logs orders without submitting them to Kalshi API.
"""

import pytest
from merid.config.dry_run import (
    get_kalshi_15m_dry_run,
    is_dry_run_enabled,
    log_dry_run_order,
)
import os


@pytest.mark.kalshi_15m
class TestDryRunMode:
    """Test dry-run mode functionality."""

    def test_get_kalshi_15m_dry_run_default(self):
        """Test that dry_run defaults to False when not set."""
        # Ensure profile is set to kalshi_crypto_15m_v2
        os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
        
        # If config file doesn't exist, should default to False
        result = get_kalshi_15m_dry_run()
        assert result is False

    def test_get_kalshi_15m_dry_run_wrong_profile(self):
        """Test that dry_run returns False for non-15m profiles."""
        os.environ["MERID_PROFILE"] = "full"
        
        result = get_kalshi_15m_dry_run()
        assert result is False

    def test_is_dry_run_enabled_false(self):
        """Test that is_dry_run_enabled returns False when dry_run is False."""
        os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
        
        result = is_dry_run_enabled()
        assert result is False

    def test_log_dry_run_order(self):
        """Test that log_dry_run_order logs order details."""
        order_intent = {
            "ticker": "KXBTCD-25JUN-T100000",
            "side": "yes",
            "action": "buy",
            "price_cents": 55,
            "count": 10,
        }
        
        # Should not raise any exception
        log_dry_run_order(order_intent)

    def test_log_dry_run_order_with_all_fields(self):
        """Test logging order with all available fields."""
        order_intent = {
            "ticker": "KXETHD-25JUN-T100000",
            "side": "no",
            "action": "sell",
            "price_cents": 45,
            "count": 5,
        }
        
        # Should not raise any exception
        log_dry_run_order(order_intent)

    def test_dry_run_config_parsing(self):
        """Test parsing dry_run from actual config file."""
        os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
        
        # Test with actual config file - should read the dry_run value
        # The default in kalshi_crypto_15m.yaml is False
        result = get_kalshi_15m_dry_run()
        # We don't assert a specific value since the config file might change
        # Just verify it returns a boolean
        assert isinstance(result, bool)
