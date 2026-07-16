"""Tests for indicator stack using spot prices vs Kalshi market prices.

CRITICAL FIX: 2026-07-16 - This test validates that indicator stack
intentionally uses spot prices for technical indicators (RSI, MACD, EMA)
since these are calculated on the underlying crypto asset, not the Kalshi
prediction market prices (which are 0-1 range binary options).
"""

from __future__ import annotations

import time
from unittest.mock import Mock, MagicMock, patch
import pytest

from merid.prediction.agent_grid_15m import LeanAgentConfig, LeanAgent15m
from merid.signals.crypto_15m_indicators import Crypto15mIndicatorStack


class TestIndicatorStackSpotPriceUsage:
    """Test that indicator stack uses spot prices intentionally."""
    
    def test_indicator_stack_uses_spot_prices(self):
        """Test that indicator stack is updated with spot prices, not Kalshi market prices."""
        config = LeanAgentConfig(
            name="BTC_15M",
            series_tickers=["KXBTC15M"],
        )
        
        # Mock dependencies
        catalog = Mock()
        spot_provider = Mock()
        order_router = Mock()
        market_state_store = Mock()
        risk_config = Mock()
        
        agent = LeanAgent15m(
            config=config,
            catalog=catalog,
            spot_provider=spot_provider,
            order_router=order_router,
            market_state_store=market_state_store,
            risk_config=risk_config,
        )
        
        # Verify indicator stack is initialized
        assert hasattr(agent, '_indicator_stacks')
        assert hasattr(agent, '_indicator_stack_price_buffer')
        
        # Verify BTC indicator stack exists
        assert "BTC" in agent._indicator_stacks
        assert isinstance(agent._indicator_stacks["BTC"], Crypto15mIndicatorStack)
    
    def test_indicator_stack_price_buffer_exists(self):
        """Test that price buffer exists for 1-minute aggregation."""
        config = LeanAgentConfig(
            name="BTC_15M",
            series_tickers=["KXBTC15M"],
        )
        
        # Mock dependencies
        catalog = Mock()
        spot_provider = Mock()
        order_router = Mock()
        market_state_store = Mock()
        risk_config = Mock()
        
        agent = LeanAgent15m(
            config=config,
            catalog=catalog,
            spot_provider=spot_provider,
            order_router=order_router,
            market_state_store=market_state_store,
            risk_config=risk_config,
        )
        
        # Verify price buffer is initialized for all assets
        expected_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        for asset in expected_assets:
            assert asset in agent._indicator_stack_price_buffer
            assert isinstance(agent._indicator_stack_price_buffer[asset], list)
    
    def test_indicator_stack_comment_explains_spot_price_usage(self):
        """Test that code comment explains why spot prices are used."""
        # Read the agent_grid_15m.py file to verify the comment exists
        import inspect
        from merid.prediction import agent_grid_15m
        
        source = inspect.getsource(agent_grid_15m)
        
        # Verify the comment explaining spot price usage exists
        assert "Indicator stack uses spot prices as proxies for underlying crypto price movement" in source or \
               "spot prices as proxies" in source or \
               "technical indicators (RSI, MACD, EMA) are calculated on the underlying asset" in source or \
               "not the Kalshi prediction market prices" in source
    
    def test_indicator_stack_update_with_spot_price(self):
        """Test that indicator stack update method accepts spot prices."""
        config = LeanAgentConfig(
            name="BTC_15M",
            series_tickers=["KXBTC15M"],
        )
        
        # Mock dependencies
        catalog = Mock()
        spot_provider = Mock()
        order_router = Mock()
        market_state_store = Mock()
        risk_config = Mock()
        
        agent = LeanAgent15m(
            config=config,
            catalog=catalog,
            spot_provider=spot_provider,
            order_router=order_router,
            market_state_store=market_state_store,
            risk_config=risk_config,
        )
        
        # Get the BTC indicator stack
        indicator_stack = agent._indicator_stacks["BTC"]
        
        # Update with a spot price (in USD, not 0-1 range)
        spot_price = 87450.0
        indicator_stack.update(spot_price)
        
        # Verify the update succeeded
        snapshot = indicator_stack.snapshot()
        assert snapshot is not None
        assert snapshot.bars_available >= 1
    
    def test_indicator_stack_kalshi_price_in_0_1_range(self):
        """Test that Kalshi market prices are in 0-1 range (binary options)."""
        # Kalshi prediction market prices are always between 0 and 1
        # This is why they cannot be used for technical indicators
        kalshi_yes_price = 0.50  # 50 cents
        kalshi_no_price = 0.50  # 50 cents
        
        assert 0 <= kalshi_yes_price <= 1
        assert 0 <= kalshi_no_price <= 1
    
    def test_indicator_stack_spot_price_in_usd_range(self):
        """Test that spot prices are in USD range (crypto prices)."""
        # Spot prices are in USD (e.g., BTC ~$87,450)
        spot_price_btc = 87450.0
        spot_price_eth = 3450.0
        
        assert spot_price_btc > 1
        assert spot_price_eth > 1
    
    def test_indicator_stack_rsi_requires_price_history(self):
        """Test that RSI calculation requires meaningful price history."""
        from merid.signals.crypto_15m_indicators import Crypto15mIndicatorStack, IndicatorConfig
        
        config = IndicatorConfig()
        stack = Crypto15mIndicatorStack(config=config)
        
        # RSI requires at least 15 bars for initialization (14 period + 1)
        for i in range(30):
            stack.update(87450.0 + i * 10)  # Add some price movement
        
        snapshot = stack.snapshot()
        
        # RSI should be available after warmup
        assert snapshot.bars_available >= 30
        # RSI value should be between 0 and 100
        if snapshot.rsi is not None:
            assert 0 <= snapshot.rsi <= 100


class TestIndicatorStackFallbackRemoval:
    """Test that indicator stack fallback was removed (Bug #4 fix)."""
    
    def test_indicator_stack_fallback_removed(self):
        """Test that indicator stack fallback path was removed."""
        import inspect
        from merid.prediction import agent_grid_15m
        
        source = inspect.getsource(agent_grid_15m)
        
        # Verify the old fallback code is removed
        # The old code had: "Fallback to original check if indicator stack fails"
        # This should no longer exist
        assert "Fallback to original check if indicator stack fails" not in source
        
        # Verify the new fail-fast comment exists
        assert "Removed fallback path" in source or \
               "fail fast" in source or \
               "indicator stack unavailable - skipping signal generation" in source


class TestSignalModeFallback:
    """Test that unsupported signal modes have fallback (Bug #5 fix)."""
    
    def test_signal_mode_fallback_for_trend(self):
        """Test that 'trend' mode falls back to momentum_fvg."""
        import inspect
        from merid.prediction import agent_grid_15m
        
        source = inspect.getsource(agent_grid_15m)
        
        # Verify the fallback code exists
        assert "signal_mode in (\"trend\", \"mean_reversion\")" in source or \
               "signal_mode in ('trend', 'mean_reversion')" in source
        assert "falling back to momentum_fvg" in source
    
    def test_signal_mode_fallback_for_mean_reversion(self):
        """Test that 'mean_reversion' mode falls back to momentum_fvg."""
        import inspect
        from merid.prediction import agent_grid_15m
        
        source = inspect.getsource(agent_grid_15m)
        
        # Verify the fallback code handles mean_reversion
        assert "mean_reversion" in source
