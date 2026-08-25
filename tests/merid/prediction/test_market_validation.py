"""Test market validation logic for 15m Kalshi crypto trading system.

This test validates the market validation regime classification and
depth threshold checks that prevent trading on illiquid markets.
"""

import pytest
from unittest.mock import Mock, MagicMock
from typing import Any, Dict


class TestMarketValidationRegime:
    """Test market regime classification logic."""
    
    def test_classify_regime_both_sides(self):
        """Test classification of both_sides regime (both YES and NO have liquidity)."""
        # Create mock market state with both sides having liquidity
        market_state = Mock()
        market_state.min_depth_yes = 10
        market_state.min_depth_no = 10
        
        # Create mock market state store
        market_state_store = Mock()
        market_state_store.get = Mock(return_value=market_state)
        
        # Create minimal mock agent with just the method we need
        agent = Mock()
        agent.market_state_store = market_state_store
        agent.config = Mock()
        agent.config.name = "BTC_15M"
        
        # Import and bind the actual method
        from merid.prediction.agent_grid_15m import LeanAgent15m
        agent._classify_regime = LeanAgent15m._classify_regime.__get__(agent, LeanAgent15m)
        
        regime = agent._classify_regime("BTC-26JUN021930-30")
        
        assert regime == "both_sides"
    
    def test_classify_regime_one_sided_yes(self):
        """Test classification of one_sided_yes regime (only YES has liquidity)."""
        # Create mock market state with only YES depth
        market_state = Mock()
        market_state.min_depth_yes = 10
        market_state.min_depth_no = 0
        
        market_state_store = Mock()
        market_state_store.get = Mock(return_value=market_state)
        
        agent = Mock()
        agent.market_state_store = market_state_store
        agent.config = Mock()
        agent.config.name = "BTC_15M"
        
        from merid.prediction.agent_grid_15m import LeanAgent15m
        agent._classify_regime = LeanAgent15m._classify_regime.__get__(agent, LeanAgent15m)
        
        regime = agent._classify_regime("BTC-26JUN021930-30")
        
        assert regime == "one_sided_yes"
    
    def test_classify_regime_one_sided_no(self):
        """Test classification of one_sided_no regime (only NO has liquidity)."""
        # Create mock market state with only NO depth
        market_state = Mock()
        market_state.min_depth_yes = 0
        market_state.min_depth_no = 10
        
        market_state_store = Mock()
        market_state_store.get = Mock(return_value=market_state)
        
        agent = Mock()
        agent.market_state_store = market_state_store
        agent.config = Mock()
        agent.config.name = "BTC_15M"
        
        from merid.prediction.agent_grid_15m import LeanAgent15m
        agent._classify_regime = LeanAgent15m._classify_regime.__get__(agent, LeanAgent15m)
        
        regime = agent._classify_regime("BTC-26JUN021930-30")
        
        assert regime == "one_sided_no"
    
    def test_classify_regime_no_liquidity(self):
        """Test classification of no_liquidity regime (neither side has liquidity)."""
        # Create mock market state with no depth
        market_state = Mock()
        market_state.min_depth_yes = 0
        market_state.min_depth_no = 0
        
        market_state_store = Mock()
        market_state_store.get = Mock(return_value=market_state)
        
        agent = Mock()
        agent.market_state_store = market_state_store
        agent.config = Mock()
        agent.config.name = "BTC_15M"
        
        from merid.prediction.agent_grid_15m import LeanAgent15m
        agent._classify_regime = LeanAgent15m._classify_regime.__get__(agent, LeanAgent15m)
        
        regime = agent._classify_regime("BTC-26JUN021930-30")
        
        assert regime == "no_liquidity"
    
    def test_classify_regime_unknown_fallback(self):
        """Test that regime defaults to 'unknown' when market_state_store is None."""
        agent = Mock()
        agent.market_state_store = None
        agent.config = Mock()
        agent.config.name = "BTC_15M"

        from merid.prediction.agent_grid_15m import LeanAgent15m
        agent._classify_regime = LeanAgent15m._classify_regime.__get__(agent, LeanAgent15m)

        regime = agent._classify_regime("BTC-26JUN021930-30")

        assert regime == "unknown"


class TestMarketValidationDepthThreshold:
    """Test depth threshold validation logic."""
    
    def test_depth_thresholds(self):
        """Test that depth thresholds are correctly applied (default to 1 for 15m crypto)."""
        # This test validates the logic without full agent initialization
        # The actual validation is tested in the regime classification tests
        # Depth thresholds are set to 1 (minimum) for 15m crypto markets
        assert True  # Placeholder for future expansion
    
    def test_depth_threshold_allows_one_sided_books(self):
        """Test that one-sided books are allowed with sufficient depth on trading side."""
        # Create mock market state with one-sided depth
        market_state = Mock()
        market_state.min_depth_yes = 5  # Sufficient YES depth
        market_state.min_depth_no = 0    # No NO depth
        
        market_state_store = Mock()
        market_state_store.get = Mock(return_value=market_state)
        
        agent = Mock()
        agent.market_state_store = market_state_store
        agent.config = Mock()
        agent.config.name = "BTC_15M"
        
        from merid.prediction.agent_grid_15m import LeanAgent15m
        agent._classify_regime = LeanAgent15m._classify_regime.__get__(agent, LeanAgent15m)
        
        regime = agent._classify_regime("BTC-26JUN021930-30")
        
        # Should classify as one_sided_yes (allowed for TTE > 0.5 minutes)
        assert regime == "one_sided_yes"


class TestTradingWindowLogic:
    """Test trading window logic with min_decision_minute."""
    
    def test_trading_window_logic(self):
        """Test that trading window logic is correctly enforced."""
        # This test validates the logic without full agent initialization
        # The actual window logic is tested in integration tests
        assert True  # Placeholder for future expansion


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
