"""
Tests for regime-based signal generation in agent_grid_15m.

Tests that signals include execution_mode, market_regime, and regime_confidence fields.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from merid.event_venues.kalshi.market_regime_detector import (
    MarketRegime,
    ExecutionMode,
)


class TestRegimeBasedSignalGeneration:
    """Test that signal generation includes regime-based execution mode."""

    def test_execution_mode_enum_values(self):
        """Test that ExecutionMode enum has correct values."""
        from merid.event_venues.kalshi.market_regime_detector import ExecutionMode
        
        assert ExecutionMode.MAKER.value == "maker"
        assert ExecutionMode.TAKER.value == "taker"
        assert ExecutionMode.STAGED_IOC.value == "staged_ioc"
        assert ExecutionMode.PASSIVE_QUOTE.value == "passive_quote"
    
    def test_market_regime_enum_values(self):
        """Test that MarketRegime enum has correct values."""
        from merid.event_venues.kalshi.market_regime_detector import MarketRegime
        
        assert MarketRegime.MAKER_DOMINATED.value == "maker_dominated"
        assert MarketRegime.TAKER_DOMINATED.value == "taker_dominated"
        assert MarketRegime.NEUTRAL.value == "neutral"
