"""Tests for trading_agent.py canonical config import.

Tests that ALLOWED_ASSETS and EXECUTION_TIMEFRAMES are correctly
wired from kalshi_15m_crypto_config.py canonical lists.
"""
from __future__ import annotations

import pytest

from merid.prediction.trading_agent import ALLOWED_ASSETS, EXECUTION_TIMEFRAMES


class TestTradingAgentCanonicalConfig:
    """Tests for trading_agent.py canonical config import."""

    def test_allowed_assets_from_canonical_config(self):
        """ALLOWED_ASSETS should match canonical KALSHI_15M_CRYPTO_ASSETS."""
        # Expected canonical values from kalshi_15m_crypto_config.py
        expected_assets = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
        
        assert ALLOWED_ASSETS == expected_assets, (
            f"ALLOWED_ASSETS should be {expected_assets}, got {ALLOWED_ASSETS}"
        )

    def test_execution_timeframes_from_canonical_config(self):
        """EXECUTION_TIMEFRAMES should match canonical KALSHI_15M_TIMEFRAME."""
        # Expected canonical value from kalshi_15m_crypto_config.py
        expected_timeframes = {"15m"}
        
        assert EXECUTION_TIMEFRAMES == expected_timeframes, (
            f"EXECUTION_TIMEFRAMES should be {expected_timeframes}, got {EXECUTION_TIMEFRAMES}"
        )

    def test_allowed_assets_is_set(self):
        """ALLOWED_ASSETS should be a set for O(1) lookups."""
        assert isinstance(ALLOWED_ASSETS, set), "ALLOWED_ASSETS should be a set"

    def test_execution_timeframes_is_set(self):
        """EXECUTION_TIMEFRAMES should be a set for O(1) lookups."""
        assert isinstance(EXECUTION_TIMEFRAMES, set), "EXECUTION_TIMEFRAMES should be a set"

    def test_allowed_assets_not_empty(self):
        """ALLOWED_ASSETS should not be empty."""
        assert len(ALLOWED_ASSETS) > 0, "ALLOWED_ASSETS should not be empty"

    def test_execution_timeframes_not_empty(self):
        """EXECUTION_TIMEFRAMES should not be empty."""
        assert len(EXECUTION_TIMEFRAMES) > 0, "EXECUTION_TIMEFRAMES should not be empty"
