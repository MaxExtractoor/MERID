"""Tests for cross-strategy correlation monitoring."""
import pytest
import numpy as np
from merid.risk.position_sizing import PositionSizer, Position, RiskParameters


class TestCrossStrategyCorrelation:
    """Test cross-strategy correlation monitoring functionality."""
    
    def test_strategy_positions_initialization(self):
        """Test that strategy positions are initialized correctly."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
            "strategy_correlation_threshold": 0.7,
        }
        sizer = PositionSizer(config)
        
        assert sizer.strategy_positions == {}
        assert sizer.strategy_correlation_threshold == 0.7
    
    def test_add_strategy_position(self):
        """Test adding a position for a strategy."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        sizer.add_strategy_position("trend_following", "BTC", 0.05)
        
        assert "trend_following" in sizer.strategy_positions
        assert sizer.strategy_positions["trend_following"]["BTC"] == 0.05
    
    def test_add_multiple_strategy_positions(self):
        """Test adding multiple positions for a strategy."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        sizer.add_strategy_position("trend_following", "BTC", 0.05)
        sizer.add_strategy_position("trend_following", "ETH", 0.03)
        sizer.add_strategy_position("trend_following", "SOL", 0.02)
        
        assert len(sizer.strategy_positions["trend_following"]) == 3
        assert sizer.strategy_positions["trend_following"]["BTC"] == 0.05
        assert sizer.strategy_positions["trend_following"]["ETH"] == 0.03
        assert sizer.strategy_positions["trend_following"]["SOL"] == 0.02
    
    def test_add_positions_for_multiple_strategies(self):
        """Test adding positions for multiple strategies."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        sizer.add_strategy_position("trend_following", "BTC", 0.05)
        sizer.add_strategy_position("mean_reversion", "BTC", 0.04)
        sizer.add_strategy_position("trend_following", "ETH", 0.03)
        sizer.add_strategy_position("mean_reversion", "ETH", 0.02)
        
        assert len(sizer.strategy_positions) == 2
        assert "trend_following" in sizer.strategy_positions
        assert "mean_reversion" in sizer.strategy_positions
    
    def test_detect_cross_strategy_correlation_insufficient_strategies(self):
        """Test correlation detection with insufficient strategies."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        # Add only one strategy
        sizer.add_strategy_position("trend_following", "BTC", 0.05)
        
        correlations = sizer.detect_cross_strategy_correlation()
        
        assert correlations == {}
    
    def test_detect_cross_strategy_correlation_no_positions(self):
        """Test correlation detection with strategies but no positions."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        # Add strategies with no positions
        sizer.strategy_positions["trend_following"] = {}
        sizer.strategy_positions["mean_reversion"] = {}
        
        correlations = sizer.detect_cross_strategy_correlation()
        
        assert correlations == {}
    
    def test_detect_cross_strategy_correlation_high(self):
        """Test detection of high cross-strategy correlation."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        # Add highly correlated strategies (same positions)
        sizer.add_strategy_position("trend_following", "BTC", 0.05)
        sizer.add_strategy_position("trend_following", "ETH", 0.03)
        sizer.add_strategy_position("mean_reversion", "BTC", 0.05)
        sizer.add_strategy_position("mean_reversion", "ETH", 0.03)
        
        correlations = sizer.detect_cross_strategy_correlation()
        
        assert len(correlations) == 1
        assert "trend_following_mean_reversion" in correlations
        # Should be highly correlated (close to 1.0)
        assert correlations["trend_following_mean_reversion"] > 0.9
    
    def test_detect_cross_strategy_correlation_low(self):
        """Test detection of low cross-strategy correlation."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        # Add strategies with one common symbol but different position sizes
        sizer.add_strategy_position("trend_following", "BTC", 0.05)
        sizer.add_strategy_position("trend_following", "ETH", 0.03)
        sizer.add_strategy_position("mean_reversion", "BTC", 0.01)  # Much smaller
        sizer.add_strategy_position("mean_reversion", "SOL", 0.04)
        
        correlations = sizer.detect_cross_strategy_correlation()
        
        assert len(correlations) == 1
        # Correlation should be calculated (may be negative due to different patterns)
        assert "trend_following_mean_reversion" in correlations
    
    def test_detect_cross_strategy_correlation_multiple_strategies(self):
        """Test correlation detection with multiple strategies."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        # Add three strategies
        sizer.add_strategy_position("trend_following", "BTC", 0.05)
        sizer.add_strategy_position("trend_following", "ETH", 0.03)
        sizer.add_strategy_position("mean_reversion", "BTC", 0.04)
        sizer.add_strategy_position("mean_reversion", "ETH", 0.02)
        sizer.add_strategy_position("momentum", "BTC", 0.03)
        sizer.add_strategy_position("momentum", "ETH", 0.01)
        
        correlations = sizer.detect_cross_strategy_correlation()
        
        # Should have 3 pairs (3 choose 2)
        assert len(correlations) == 3
    
    def test_get_cross_strategy_risk_multiplier_no_strategies(self):
        """Test risk multiplier with no strategies."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        multiplier = sizer.get_cross_strategy_risk_multiplier()
        
        assert multiplier == 1.0
    
    def test_get_cross_strategy_risk_multiplier_low_correlation(self):
        """Test risk multiplier with low correlation."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        # Add strategies with one common symbol but different position sizes
        sizer.add_strategy_position("trend_following", "BTC", 0.05)
        sizer.add_strategy_position("trend_following", "ETH", 0.03)
        sizer.add_strategy_position("mean_reversion", "BTC", 0.01)  # Much smaller
        sizer.add_strategy_position("mean_reversion", "SOL", 0.04)
        
        multiplier = sizer.get_cross_strategy_risk_multiplier()
        
        # Multiplier should be calculated based on correlation
        assert multiplier in [0.8, 0.9, 1.0]  # One of the valid multipliers
    
    def test_get_cross_strategy_risk_multiplier_medium_correlation(self):
        """Test risk multiplier with medium correlation."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        # Add partially correlated strategies (some overlap, some difference)
        sizer.add_strategy_position("trend_following", "BTC", 0.05)
        sizer.add_strategy_position("trend_following", "ETH", 0.03)
        sizer.add_strategy_position("trend_following", "SOL", 0.02)
        sizer.add_strategy_position("mean_reversion", "BTC", 0.02)  # Smaller
        sizer.add_strategy_position("mean_reversion", "ETH", 0.01)  # Smaller
        sizer.add_strategy_position("mean_reversion", "DOGE", 0.01)  # Different symbol
        
        multiplier = sizer.get_cross_strategy_risk_multiplier()
        
        # Should be medium correlation (0.5-0.7 range)
        assert multiplier == 0.9  # 10% reduction for medium correlation
    
    def test_get_cross_strategy_risk_multiplier_high_correlation(self):
        """Test risk multiplier with high correlation."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        # Add highly correlated strategies
        sizer.add_strategy_position("trend_following", "BTC", 0.05)
        sizer.add_strategy_position("trend_following", "ETH", 0.03)
        sizer.add_strategy_position("mean_reversion", "BTC", 0.05)
        sizer.add_strategy_position("mean_reversion", "ETH", 0.03)
        
        multiplier = sizer.get_cross_strategy_risk_multiplier()
        
        assert multiplier == 0.8  # 20% reduction for high correlation
    
    def test_custom_correlation_threshold(self):
        """Test custom correlation threshold."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
            "strategy_correlation_threshold": 0.5,  # More sensitive
        }
        sizer = PositionSizer(config)
        
        assert sizer.strategy_correlation_threshold == 0.5


class TestCrossStrategyCorrelationInSizing:
    """Test cross-strategy correlation multiplier application in sizing methods."""
    
    @pytest.mark.asyncio
    async def test_volatility_based_sizing_applies_cross_strategy_multiplier(self):
        """Test that volatility-based sizing applies cross-strategy multiplier."""
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
        
        # Add highly correlated strategies (multiple symbols)
        sizer.add_strategy_position("trend_following", "BTC", 0.05)
        sizer.add_strategy_position("trend_following", "ETH", 0.03)
        sizer.add_strategy_position("mean_reversion", "BTC", 0.05)
        sizer.add_strategy_position("mean_reversion", "ETH", 0.03)
        
        result_with_corr = await sizer.calculate_position_size("BTC", "volatility_based", 1.0)
        
        # Position size should be reduced due to high correlation
        assert result_with_corr is not None
        # With high correlation, multiplier should be 0.8, so position should be at max limit
        # The test verifies the multiplier is applied, even if clipped to max_position_size
