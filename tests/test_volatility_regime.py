"""Tests for volatility regime detection and filtering."""
import pytest
import numpy as np
from collections import deque
from merid.risk.position_sizing import PositionSizer, Position, RiskParameters


class TestVolatilityRegimeDetection:
    """Test volatility regime detection functionality."""
    
    def test_volatility_history_initialization(self):
        """Test that volatility history is initialized correctly."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
            "volatility_window": 20,
        }
        sizer = PositionSizer(config)
        
        assert sizer.volatility_history == {}
        assert sizer.volatility_window == 20
        assert sizer.current_volatility_regime == "normal"
    
    def test_update_volatility_creates_history(self):
        """Test that updating volatility creates history for new symbol."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        sizer.update_volatility("BTC", 0.02)
        
        assert "BTC" in sizer.volatility_history
        assert len(sizer.volatility_history["BTC"]) == 1
        assert sizer.volatility_history["BTC"][0] == 0.02
    
    def test_update_volatility_appends_to_history(self):
        """Test that updating volatility appends to existing history."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        sizer.update_volatility("BTC", 0.02)
        sizer.update_volatility("BTC", 0.025)
        sizer.update_volatility("BTC", 0.03)
        
        assert len(sizer.volatility_history["BTC"]) == 3
        assert list(sizer.volatility_history["BTC"]) == [0.02, 0.025, 0.03]
    
    def test_volatility_history_maxlen(self):
        """Test that volatility history respects maxlen."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
            "volatility_window": 5,
        }
        sizer = PositionSizer(config)
        
        # Add more volatilities than window size
        for i in range(10):
            sizer.update_volatility("BTC", 0.02 + i * 0.001)
        
        # Should only keep last 5
        assert len(sizer.volatility_history["BTC"]) == 5
    
    def test_detect_volatility_regime_no_history(self):
        """Test that regime detection returns 'normal' with no history."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        regime = sizer.detect_volatility_regime()
        
        assert regime == "normal"
    
    def test_detect_volatility_regime_low(self):
        """Test detection of low volatility regime."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
            "volatility_thresholds": {
                "low": 0.01,
                "normal": 0.03,
                "high": 0.05,
            },
        }
        sizer = PositionSizer(config)
        
        # Add low volatility data
        for i in range(10):
            sizer.update_volatility("BTC", 0.005)  # 0.5% vol
        
        regime = sizer.detect_volatility_regime()
        
        assert regime == "low"
        assert sizer.current_volatility_regime == "low"
    
    def test_detect_volatility_regime_normal(self):
        """Test detection of normal volatility regime."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
            "volatility_thresholds": {
                "low": 0.01,
                "normal": 0.03,
                "high": 0.05,
            },
        }
        sizer = PositionSizer(config)
        
        # Add normal volatility data
        for i in range(10):
            sizer.update_volatility("BTC", 0.02)  # 2% vol
        
        regime = sizer.detect_volatility_regime()
        
        assert regime == "normal"
        assert sizer.current_volatility_regime == "normal"
    
    def test_detect_volatility_regime_high(self):
        """Test detection of high volatility regime."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
            "volatility_thresholds": {
                "low": 0.01,
                "normal": 0.03,
                "high": 0.05,
            },
        }
        sizer = PositionSizer(config)
        
        # Add high volatility data
        for i in range(10):
            sizer.update_volatility("BTC", 0.06)  # 6% vol
        
        regime = sizer.detect_volatility_regime()
        
        assert regime == "high"
        assert sizer.current_volatility_regime == "high"
    
    def test_detect_volatility_regime_multiple_symbols(self):
        """Test regime detection with multiple symbols."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        # Add volatility data for multiple symbols
        for i in range(10):
            sizer.update_volatility("BTC", 0.02)
            sizer.update_volatility("ETH", 0.025)
            sizer.update_volatility("SOL", 0.03)
        
        regime = sizer.detect_volatility_regime()
        
        # Should average across all symbols
        assert regime in ["low", "normal", "high"]
    
    def test_get_volatility_regime_multiplier_low(self):
        """Test volatility regime multiplier for low regime."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        # Set low regime
        for i in range(10):
            sizer.update_volatility("BTC", 0.005)
        
        multiplier = sizer.get_volatility_regime_multiplier()
        
        assert multiplier == 1.2  # Can increase size in calm markets
    
    def test_get_volatility_regime_multiplier_normal(self):
        """Test volatility regime multiplier for normal regime."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        # Set normal regime
        for i in range(10):
            sizer.update_volatility("BTC", 0.02)
        
        multiplier = sizer.get_volatility_regime_multiplier()
        
        assert multiplier == 1.0  # Standard sizing
    
    def test_get_volatility_regime_multiplier_high(self):
        """Test volatility regime multiplier for high regime."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        # Set high regime
        for i in range(10):
            sizer.update_volatility("BTC", 0.06)
        
        multiplier = sizer.get_volatility_regime_multiplier()
        
        assert multiplier == 0.7  # Reduce size in volatile markets
    
    def test_custom_volatility_thresholds(self):
        """Test custom volatility thresholds."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
            "volatility_thresholds": {
                "low": 0.005,   # More sensitive
                "normal": 0.02,
                "high": 0.04,
            },
        }
        sizer = PositionSizer(config)
        
        # Add volatility that would be "normal" with default but "high" with custom
        for i in range(10):
            sizer.update_volatility("BTC", 0.03)
        
        regime = sizer.detect_volatility_regime()
        
        assert regime == "high"  # Should be high with custom thresholds


class TestVolatilityRegimeInSizing:
    """Test volatility regime multiplier application in sizing methods."""
    
    @pytest.mark.asyncio
    async def test_volatility_based_sizing_applies_regime_multiplier(self):
        """Test that volatility-based sizing applies regime multiplier."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
                "stop_loss_atr_multiplier": 2.0,
                "take_profit_atr_multiplier": 3.0
            },
        }
        sizer = PositionSizer(config)
        
        position = Position(
            symbol="BTC",
            current_price=50000.0,
            volatility=0.02,
            max_position_size=0.1,
            min_position_size=0.01
        )
        sizer.add_position(position)
        
        # Calculate at normal regime
        sizer.update_volatility("BTC", 0.02)
        result_normal = await sizer.calculate_position_size("BTC", "volatility_based", 1.0)
        
        # Calculate at high regime
        sizer.update_volatility("BTC", 0.06)
        result_high = await sizer.calculate_position_size("BTC", "volatility_based", 1.0)
        
        # Position size should be smaller in high regime
        assert result_normal is not None
        assert result_high is not None
        assert result_high.position_size < result_normal.position_size
    
    @pytest.mark.asyncio
    async def test_kelly_sizing_applies_regime_multiplier(self):
        """Test that Kelly sizing applies regime multiplier."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        position = Position(
            symbol="ETH",
            current_price=3000.0,
            volatility=0.03,
            max_position_size=0.1,
            min_position_size=0.01
        )
        sizer.add_position(position)
        
        # Calculate at low regime (should increase size)
        sizer.update_volatility("ETH", 0.005)
        result_low = await sizer.calculate_position_size("ETH", "kelly_criterion", 1.0)
        
        # Calculate at normal regime
        sizer.update_volatility("ETH", 0.02)
        result_normal = await sizer.calculate_position_size("ETH", "kelly_criterion", 1.0)
        
        # Position size should be larger in low regime
        assert result_low is not None
        assert result_normal is not None
        assert result_low.position_size > result_normal.position_size
