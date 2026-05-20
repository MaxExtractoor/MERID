"""
Tests for 15-Minute Bollinger Band Strategy
===========================================

Unit tests for:
- BandStrategyEngine indicator calculations
- Regime filter (50 EMA + ADX)
- Entry/exit logic for mean-reversion
- Per-asset configuration
- BandStrategyAgent wrapper
"""

import pytest
import math
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from merid.strategies.band_strategy_15m import (
    BandStrategyEngine,
    BandStrategyConfig,
    BandSnapshot,
    TradeSetup,
    get_band_strategy_config,
    ASSET_CONFIGS,
)
from merid.prediction.band_strategy_agent import (
    BandStrategyAgent,
    BandAgentState,
    get_band_agent,
)


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def sample_ohlc_data():
    """Generate sample 15m OHLC data for testing."""
    np.random.seed(42)
    n_bars = 200
    
    # Generate price series with some volatility
    base_price = 50000.0
    returns = np.random.normal(0, 0.002, n_bars)
    prices = base_price * (1 + returns).cumprod()
    
    # Add some trend
    trend = np.linspace(0, 0.05, n_bars)
    prices = prices * (1 + trend)
    
    # Create OHLC
    high = prices * (1 + np.abs(np.random.normal(0, 0.001, n_bars)))
    low = prices * (1 - np.abs(np.random.normal(0, 0.001, n_bars)))
    close = prices.copy()
    
    df = pd.DataFrame({
        "high": high,
        "low": low,
        "close": close,
    })
    
    return df


@pytest.fixture
def btc_config():
    """Get BTC configuration."""
    return get_band_strategy_config("BTC")


@pytest.fixture
def eth_config():
    """Get ETH configuration."""
    return get_band_strategy_config("ETH")


@pytest.fixture
def sol_config():
    """Get SOL configuration."""
    return get_band_strategy_config("SOL")


@pytest.fixture
def doge_config():
    """Get DOGE configuration."""
    return get_band_strategy_config("DOGE")


# ═══════════════════════════════════════════════════════════════════════════
# Configuration Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestBandStrategyConfig:
    """Tests for BandStrategyConfig and per-asset overrides."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = BandStrategyConfig()
        assert config.asset == "BTC"
        assert config.bb_period == 20
        assert config.bb_sd_multiplier == 2.1  # BTC default
        assert config.trend_ema_period == 50
        assert config.adx_period == 14
        assert config.rsi_period == 14
    
    def test_btc_config(self, btc_config):
        """Test BTC-specific configuration."""
        assert btc_config.asset == "BTC"
        assert btc_config.bb_sd_multiplier == 2.1  # 2.0-2.2 range
        assert btc_config.sl_atr_multiplier == 1.5  # Tighter SL
    
    def test_eth_config(self, eth_config):
        """Test ETH-specific configuration."""
        assert eth_config.asset == "ETH"
        assert eth_config.bb_sd_multiplier == 2.1  # Same as BTC
        assert eth_config.sl_atr_multiplier == 1.5
    
    def test_sol_config(self, sol_config):
        """Test SOL-specific configuration."""
        assert sol_config.asset == "SOL"
        assert 2.2 <= sol_config.bb_sd_multiplier <= 2.4  # Wider bands
        assert sol_config.sl_atr_multiplier == 1.8  # Wider SL
    
    def test_doge_config(self, doge_config):
        """Test DOGE-specific configuration."""
        assert doge_config.asset == "DOGE"
        assert 2.3 <= doge_config.bb_sd_multiplier <= 2.5  # Widest bands
        assert doge_config.sl_atr_multiplier == 2.0  # Widest SL
    
    def test_asset_configs_dict(self):
        """Test ASSET_CONFIGS dictionary."""
        assert "BTC" in ASSET_CONFIGS
        assert "ETH" in ASSET_CONFIGS
        assert "SOL" in ASSET_CONFIGS
        assert "XRP" in ASSET_CONFIGS
        assert "DOGE" in ASSET_CONFIGS
        
        # Verify each is a BandStrategyConfig
        for asset, config in ASSET_CONFIGS.items():
            assert isinstance(config, BandStrategyConfig)
            assert config.asset == asset
    
    def test_config_post_init_case_insensitive(self):
        """Test that asset parameter is case-insensitive."""
        config_lower = BandStrategyConfig(asset="btc")
        config_upper = BandStrategyConfig(asset="BTC")
        
        assert config_lower.bb_sd_multiplier == config_upper.bb_sd_multiplier


# ═══════════════════════════════════════════════════════════════════════════
# Indicator Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestBandStrategyEngine:
    """Tests for BandStrategyEngine indicator calculations."""
    
    def test_engine_initialization(self, btc_config):
        """Test engine initialization with config."""
        engine = BandStrategyEngine(btc_config)
        assert engine.cfg == btc_config
        assert len(engine._prices) == 0
        assert not engine._bb_initialized
    
    def test_update_with_valid_data(self, btc_config, sample_ohlc_data):
        """Test updating engine with valid OHLC data."""
        engine = BandStrategyEngine(btc_config)
        
        # Update with first bar
        row = sample_ohlc_data.iloc[0]
        engine.update(row["high"], row["low"], row["close"])
        
        assert len(engine._prices) == 1
        assert engine._prices[-1] == row["close"]
    
    def test_update_with_invalid_data(self, btc_config):
        """Test that invalid data is rejected."""
        engine = BandStrategyEngine(btc_config)
        
        # Negative prices
        engine.update(-100.0, -110.0, -105.0)
        assert len(engine._prices) == 0
        
        # NaN
        engine.update(float('nan'), 100.0, 100.0)
        assert len(engine._prices) == 0
        
        # Invalid OHLC (high < low)
        engine.update(100.0, 110.0, 105.0)
        assert len(engine._prices) == 0
    
    def test_bollinger_bands_calculation(self, btc_config, sample_ohlc_data):
        """Test Bollinger Bands calculation after sufficient data."""
        engine = BandStrategyEngine(btc_config)
        
        # Feed enough data for BB calculation
        for _, row in sample_ohlc_data.head(30).iterrows():
            engine.update(row["high"], row["low"], row["close"])
        
        snap = engine.snapshot()
        
        assert snap.bb_sma > 0
        assert snap.bb_upper > snap.bb_sma
        assert snap.bb_lower < snap.bb_sma
        assert snap.bb_width > 0
        assert 0 <= snap.bb_position <= 1
    
    def test_keltner_channels_calculation(self, btc_config, sample_ohlc_data):
        """Test Keltner Channels calculation."""
        engine = BandStrategyEngine(btc_config)
        
        # Feed enough data for KC calculation
        for _, row in sample_ohlc_data.head(40).iterrows():
            engine.update(row["high"], row["low"], row["close"])
        
        snap = engine.snapshot()
        
        assert snap.kc_ema > 0
        assert snap.kc_upper > snap.kc_ema
        assert snap.kc_lower < snap.kc_ema
        assert snap.kc_atr > 0
    
    def test_trend_ema_calculation(self, btc_config, sample_ohlc_data):
        """Test 50 EMA trend calculation."""
        engine = BandStrategyEngine(btc_config)
        
        # Feed enough data for 50 EMA
        for _, row in sample_ohlc_data.head(60).iterrows():
            engine.update(row["high"], row["low"], row["close"])
        
        snap = engine.snapshot()
        
        assert snap.trend_ema > 0
        assert isinstance(snap.price_above_trend_ema, bool)
    
    def test_rsi_calculation(self, btc_config, sample_ohlc_data):
        """Test RSI calculation."""
        engine = BandStrategyEngine(btc_config)
        
        # Feed enough data for RSI
        for _, row in sample_ohlc_data.head(30).iterrows():
            engine.update(row["high"], row["low"], row["close"])
        
        snap = engine.snapshot()
        
        assert 0 <= snap.rsi <= 100
        assert snap.rsi_zone in ["overbought", "oversold", "neutral"]
    
    def test_adx_calculation(self, btc_config, sample_ohlc_data):
        """Test ADX calculation for regime classification."""
        engine = BandStrategyEngine(btc_config)
        
        # Feed enough data for ADX
        for _, row in sample_ohlc_data.head(30).iterrows():
            engine.update(row["high"], row["low"], row["close"])
        
        snap = engine.snapshot()
        
        assert snap.adx >= 0
        assert snap.regime in ["trend", "range"]
        assert snap.adx_trend_strength in ["weak", "moderate", "strong"]


# ═══════════════════════════════════════════════════════════════════════════
# Regime Filter Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestRegimeFilter:
    """Tests for regime filter (50 EMA + ADX)."""
    
    def test_regime_classification(self, btc_config, sample_ohlc_data):
        """Test regime classification based on ADX threshold."""
        engine = BandStrategyEngine(btc_config)
        
        for _, row in sample_ohlc_data.head(30).iterrows():
            engine.update(row["high"], row["low"], row["close"])
        
        snap = engine.snapshot()
        
        # ADX < 20 should be range, >= 20 should be trend
        if snap.adx < btc_config.adx_trend_threshold:
            assert snap.regime == "range"
        else:
            assert snap.regime == "trend"
    
    def test_trend_ema_position(self, btc_config, sample_ohlc_data):
        """Test price position relative to 50 EMA."""
        engine = BandStrategyEngine(btc_config)
        
        for _, row in sample_ohlc_data.head(60).iterrows():
            engine.update(row["high"], row["low"], row["close"])
        
        snap = engine.snapshot()
        
        # Should correctly identify if price is above or below trend EMA
        if snap.price > snap.trend_ema:
            assert snap.price_above_trend_ema is True
        else:
            assert snap.price_above_trend_ema is False
    
    def test_adx_strength_classification(self, btc_config, sample_ohlc_data):
        """Test ADX strength classification."""
        engine = BandStrategyEngine(btc_config)
        
        for _, row in sample_ohlc_data.head(30).iterrows():
            engine.update(row["high"], row["low"], row["close"])
        
        snap = engine.snapshot()
        
        if snap.adx >= btc_config.adx_strong_trend:
            assert snap.adx_trend_strength == "strong"
        elif snap.adx >= btc_config.adx_trend_threshold:
            assert snap.adx_trend_strength == "moderate"
        else:
            assert snap.adx_trend_strength == "weak"


# ═══════════════════════════════════════════════════════════════════════════
# Entry/Exit Logic Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestEntryExitLogic:
    """Tests for entry/exit logic for mean-reversion band touches."""
    
    def test_no_signal_without_enough_data(self, btc_config):
        """Test that no signal is generated without sufficient data."""
        engine = BandStrategyEngine(btc_config)
        
        # Only 10 bars - not enough
        for i in range(10):
            engine.update(50000 + i, 49990 + i, 50000 + i)
        
        snap = engine.snapshot()
        setup = engine._generate_signal(snap)
        
        assert setup.side == "neutral"
    
    def test_signal_generation_requires_range_regime(self, btc_config, sample_ohlc_data):
        """Test that signals are only generated in range regime."""
        engine = BandStrategyEngine(btc_config)
        
        for _, row in sample_ohlc_data.head(60).iterrows():
            engine.update(row["high"], row["low"], row["close"])
        
        snap = engine.snapshot()
        setup = engine._generate_signal(snap)
        
        # If in trend regime, should be neutral
        if snap.regime == "trend":
            assert setup.side == "neutral"
            assert "Regime filter" in setup.reason
    
    def test_signal_structure(self, btc_config, sample_ohlc_data):
        """Test that signal has all required fields."""
        engine = BandStrategyEngine(btc_config)
        
        for _, row in sample_ohlc_data.head(60).iterrows():
            engine.update(row["high"], row["low"], row["close"])
        
        snap = engine.snapshot()
        setup = engine._generate_signal(snap)
        
        # Check all required fields exist
        assert hasattr(setup, "side")
        assert hasattr(setup, "entry_price")
        assert hasattr(setup, "tp_price")
        assert hasattr(setup, "sl_price")
        assert hasattr(setup, "r_multiple")
        assert hasattr(setup, "regime")
        assert hasattr(setup, "reason")
    
    def test_r_multiple_calculation(self, btc_config):
        """Test R:R calculation for signals."""
        engine = BandStrategyEngine(btc_config)
        
        # Generate a scenario with known bands
        for i in range(60):
            price = 50000 + math.sin(i / 10) * 500  # Oscillating price
            engine.update(price + 10, price - 10, price)
        
        snap = engine.snapshot()
        setup = engine._generate_signal(snap)
        
        if setup.side != "neutral":
            assert setup.r_multiple >= 0
            assert setup.tp_price > 0
            assert setup.sl_price > 0


# ═══════════════════════════════════════════════════════════════════════════
# BandStrategyAgent Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestBandStrategyAgent:
    """Tests for BandStrategyAgent wrapper."""
    
    def test_agent_initialization(self):
        """Test agent initialization with default assets."""
        agent = BandStrategyAgent()
        
        assert len(agent.assets) == 5  # BTC, ETH, SOL, XRP, DOGE
        assert "BTC" in agent.states
        assert "ETH" in agent.states
        assert "SOL" in agent.states
        assert "XRP" in agent.states
        assert "DOGE" in agent.states
    
    def test_agent_custom_assets(self):
        """Test agent initialization with custom asset list."""
        agent = BandStrategyAgent(assets=["BTC", "ETH"])
        
        assert len(agent.assets) == 2
        assert "BTC" in agent.states
        assert "ETH" in agent.states
        assert "SOL" not in agent.states
    
    def test_update_asset(self):
        """Test updating a single asset."""
        agent = BandStrategyAgent(assets=["BTC"])
        
        agent.update_asset("BTC", 50100.0, 49900.0, 50000.0)
        
        state = agent.states["BTC"]
        assert state.last_update is not None
        assert len(state.engine._prices) == 1
    
    def test_get_signal(self):
        """Test getting signal for an asset."""
        agent = BandStrategyAgent(assets=["BTC"])
        
        # Update with some data
        for i in range(60):
            price = 50000 + math.sin(i / 10) * 500
            agent.update_asset("BTC", price + 10, price - 10, price)
        
        signal = agent.get_signal("BTC")
        
        # Signal may be neutral or have a direction
        assert signal is not None
        assert signal.side in ["long", "short", "neutral"]
    
    def test_get_snapshot(self):
        """Test getting snapshot for an asset."""
        agent = BandStrategyAgent(assets=["BTC"])
        
        agent.update_asset("BTC", 50100.0, 49900.0, 50000.0)
        
        snapshot = agent.get_snapshot("BTC")
        
        assert snapshot is not None
        assert snapshot.price == 50000.0
    
    def test_get_all_states(self):
        """Test getting states for all assets."""
        agent = BandStrategyAgent(assets=["BTC", "ETH"])
        
        agent.update_asset("BTC", 50100.0, 49900.0, 50000.0)
        agent.update_asset("ETH", 3100.0, 2900.0, 3000.0)
        
        states = agent.get_all_states()
        
        assert "BTC" in states
        assert "ETH" in states
        assert len(states) == 2
    
    def test_get_aggregate_summary(self):
        """Test getting aggregate summary."""
        agent = BandStrategyAgent(assets=["BTC", "ETH"])
        
        agent.update_asset("BTC", 50100.0, 49900.0, 50000.0)
        agent.update_asset("ETH", 3100.0, 2900.0, 3000.0)
        
        summary = agent.get_aggregate_summary()
        
        assert "assets_tracked" in summary
        assert "total_signals" in summary
        assert "regime_distribution" in summary
        assert "active_signals" in summary


class TestBandAgentSingleton:
    """Tests for get_band_agent singleton pattern."""
    
    def test_singleton_returns_same_instance(self):
        """Test that get_band_agent returns the same instance."""
        agent1 = get_band_agent()
        agent2 = get_band_agent()
        
        assert agent1 is agent2
    
    def test_singleton_with_custom_assets(self):
        """Test singleton with custom asset list (first call wins)."""
        # First call with custom assets
        agent1 = get_band_agent(assets=["BTC"])
        
        # Second call should return same instance
        agent2 = get_band_agent(assets=["ETH"])
        
        assert agent1 is agent2
        assert len(agent1.assets) == 1  # Still BTC from first call


# ═══════════════════════════════════════════════════════════════════════════
# Integration Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestBandStrategyIntegration:
    """Integration tests for the full band strategy stack."""
    
    def test_full_signal_flow(self):
        """Test complete flow from OHLC update to signal generation."""
        agent = BandStrategyAgent(assets=["BTC"])
        
        # Feed enough data for all indicators to initialize
        for i in range(100):
            price = 50000 + math.sin(i / 10) * 1000 + i * 10  # Trending up with oscillation
            agent.update_asset("BTC", price + 50, price - 50, price)
        
        # Get snapshot
        snapshot = agent.get_snapshot("BTC")
        assert snapshot is not None
        assert snapshot.bars_available >= 100
        
        # Check indicators are calculated
        assert snapshot.bb_sma > 0
        assert snapshot.trend_ema > 0
        assert 0 <= snapshot.rsi <= 100
        assert snapshot.adx >= 0
    
    def test_per_asset_different_params(self):
        """Test that different assets use different parameters."""
        agent = BandStrategyAgent(assets=["BTC", "DOGE"])
        
        # Update both with same price data
        for i in range(60):
            price = 50000 + i * 10
            agent.update_asset("BTC", price + 50, price - 50, price)
            agent.update_asset("DOGE", price / 1000 + 0.05, price / 1000 - 0.05, price / 1000)
        
        btc_snap = agent.get_snapshot("BTC")
        doge_snap = agent.get_snapshot("DOGE")
        
        # Should have different SD multipliers
        assert btc_snap.bb_sd_multiplier != doge_snap.bb_sd_multiplier
        assert btc_snap.bb_sd_multiplier < doge_snap.bb_sd_multiplier  # DOGE wider
    
    def test_signal_strength_bounds(self):
        """Test that signal strength is always in [0, 1]."""
        agent = BandStrategyAgent(assets=["BTC"])
        
        for i in range(100):
            price = 50000 + math.sin(i / 5) * 2000  # Large oscillations
            agent.update_asset("BTC", price + 100, price - 100, price)
        
        signal = agent.get_signal("BTC")
        
        if signal and signal.side != "neutral":
            assert 0 <= signal.signal_strength <= 1
