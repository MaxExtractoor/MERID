"""Tests for drawdown-adjusted position sizing."""
import pytest
from merid.risk.position_sizing import PositionSizer, Position, RiskParameters


class TestDrawdownAdjustedSizing:
    """Test drawdown-adjusted position sizing functionality."""

    def test_initial_peak_value_tracking(self):
        """Test that peak portfolio value is initialized correctly."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
                "max_correlation_exposure": 0.5,
                "stop_loss_atr_multiplier": 2.0,
                "take_profit_atr_multiplier": 3.0,
                "max_leverage": 2.0,
                "risk_free_rate": 0.02,
                "confidence_level": 0.95
            },
            "drawdown_thresholds": {
                "warning": 0.05,
                "critical": 0.10,
                "severe": 0.15
            }
        }
        sizer = PositionSizer(config)
        
        assert sizer.portfolio_value == 1000000.0
        assert sizer.peak_portfolio_value == 1000000.0

    def test_peak_value_updates_on_increase(self):
        """Test that peak value updates when portfolio value increases."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
                "max_correlation_exposure": 0.5,
                "stop_loss_atr_multiplier": 2.0,
                "take_profit_atr_multiplier": 3.0,
                "max_leverage": 2.0,
                "risk_free_rate": 0.02,
                "confidence_level": 0.95
            },
            "drawdown_thresholds": {
                "warning": 0.05,
                "critical": 0.10,
                "severe": 0.15
            }
        }
        sizer = PositionSizer(config)
        
        # Verify initial state
        assert sizer.portfolio_value == 1000000.0
        assert sizer.peak_portfolio_value == 1000000.0
        
        # Update to higher value
        sizer.update_portfolio_value(1100000.0)
        
        assert sizer.portfolio_value == 1100000.0
        # Peak should update to new higher value
        assert sizer.peak_portfolio_value == 1100000.0

    def test_peak_value_does_not_decrease(self):
        """Test that peak value does not decrease when portfolio value drops."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
                "max_correlation_exposure": 0.5,
                "stop_loss_atr_multiplier": 2.0,
                "take_profit_atr_multiplier": 3.0,
                "max_leverage": 2.0,
                "risk_free_rate": 0.02,
                "confidence_level": 0.95
            },
            "drawdown_thresholds": {
                "warning": 0.05,
                "critical": 0.10,
                "severe": 0.15
            }
        }
        sizer = PositionSizer(config)
        
        sizer.update_portfolio_value(1100000.0)  # Peak increases
        sizer.update_portfolio_value(950000.0)   # Portfolio drops
        
        assert sizer.portfolio_value == 950000.0
        assert sizer.peak_portfolio_value == 1100000.0  # Peak stays at 1.1M

    def test_drawdown_calculation_no_drawdown(self):
        """Test drawdown calculation when at peak."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
                "max_correlation_exposure": 0.5,
                "stop_loss_atr_multiplier": 2.0,
                "take_profit_atr_multiplier": 3.0,
                "max_leverage": 2.0,
                "risk_free_rate": 0.02,
                "confidence_level": 0.95
            },
            "drawdown_thresholds": {
                "warning": 0.05,
                "critical": 0.10,
                "severe": 0.15
            }
        }
        sizer = PositionSizer(config)
        
        drawdown = sizer.get_current_drawdown()
        
        assert drawdown == 0.0

    def test_drawdown_calculation_with_loss(self):
        """Test drawdown calculation when portfolio is below peak."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
                "max_correlation_exposure": 0.5,
                "stop_loss_atr_multiplier": 2.0,
                "take_profit_atr_multiplier": 3.0,
                "max_leverage": 2.0,
                "risk_free_rate": 0.02,
                "confidence_level": 0.95
            },
            "drawdown_thresholds": {
                "warning": 0.05,
                "critical": 0.10,
                "severe": 0.15
            }
        }
        sizer = PositionSizer(config)
        
        sizer.update_portfolio_value(950000.0)  # 5% loss
        
        drawdown = sizer.get_current_drawdown()
        
        assert drawdown == 0.05

    def test_drawdown_multiplier_no_drawdown(self):
        """Test size multiplier when no drawdown."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
                "max_correlation_exposure": 0.5,
                "stop_loss_atr_multiplier": 2.0,
                "take_profit_atr_multiplier": 3.0,
                "max_leverage": 2.0,
                "risk_free_rate": 0.02,
                "confidence_level": 0.95
            },
            "drawdown_thresholds": {
                "warning": 0.05,
                "critical": 0.10,
                "severe": 0.15
            }
        }
        sizer = PositionSizer(config)
        
        multiplier = sizer.get_drawdown_size_multiplier()
        
        assert multiplier == 1.0  # Full size

    def test_drawdown_multiplier_warning_level(self):
        """Test size multiplier at warning drawdown level (5%)."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {},
            "drawdown_thresholds": {
                "warning": 0.05,
                "critical": 0.10,
                "severe": 0.15
            }
        }
        sizer = PositionSizer(config)
        
        sizer.update_portfolio_value(950000.0)  # 5% drawdown
        
        multiplier = sizer.get_drawdown_size_multiplier()
        
        assert multiplier == 0.8  # 80% size

    def test_drawdown_multiplier_critical_level(self):
        """Test size multiplier at critical drawdown level (10%)."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
                "max_correlation_exposure": 0.5,
                "stop_loss_atr_multiplier": 2.0,
                "take_profit_atr_multiplier": 3.0,
                "max_leverage": 2.0,
                "risk_free_rate": 0.02,
                "confidence_level": 0.95
            },
            "drawdown_thresholds": {
                "warning": 0.05,
                "critical": 0.10,
                "severe": 0.15
            }
        }
        sizer = PositionSizer(config)
        
        sizer.update_portfolio_value(900000.0)  # 10% drawdown
        
        multiplier = sizer.get_drawdown_size_multiplier()
        
        assert multiplier == 0.5  # 50% size

    def test_drawdown_multiplier_severe_level(self):
        """Test size multiplier at severe drawdown level (15%)."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
                "max_correlation_exposure": 0.5,
                "stop_loss_atr_multiplier": 2.0,
                "take_profit_atr_multiplier": 3.0,
                "max_leverage": 2.0,
                "risk_free_rate": 0.02,
                "confidence_level": 0.95
            },
            "drawdown_thresholds": {
                "warning": 0.05,
                "critical": 0.10,
                "severe": 0.15
            }
        }
        sizer = PositionSizer(config)
        
        sizer.update_portfolio_value(850000.0)  # 15% drawdown
        
        multiplier = sizer.get_drawdown_size_multiplier()
        
        assert multiplier == 0.25  # 25% size

    def test_drawdown_multiplier_extreme_level(self):
        """Test size multiplier at extreme drawdown (>15%)."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
                "max_correlation_exposure": 0.5,
                "stop_loss_atr_multiplier": 2.0,
                "take_profit_atr_multiplier": 3.0,
                "max_leverage": 2.0,
                "risk_free_rate": 0.02,
                "confidence_level": 0.95
            },
            "drawdown_thresholds": {
                "warning": 0.05,
                "critical": 0.10,
                "severe": 0.15
            }
        }
        sizer = PositionSizer(config)
        
        sizer.update_portfolio_value(700000.0)  # 30% drawdown
        
        multiplier = sizer.get_drawdown_size_multiplier()
        
        assert multiplier == 0.25  # Still 25% size (floor)

    def test_custom_drawdown_thresholds(self):
        """Test custom drawdown thresholds."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
                "max_correlation_exposure": 0.5,
                "stop_loss_atr_multiplier": 2.0,
                "take_profit_atr_multiplier": 3.0,
                "max_leverage": 2.0,
                "risk_free_rate": 0.02,
                "confidence_level": 0.95
            },
            "drawdown_thresholds": {
                "warning": 0.03,    # 3%
                "critical": 0.07,   # 7%
                "severe": 0.12      # 12%
            }
        }
        sizer = PositionSizer(config)
        
        # At 4% drawdown (between warning and critical)
        sizer.update_portfolio_value(960000.0)
        multiplier = sizer.get_drawdown_size_multiplier()
        assert multiplier == 0.8  # Should be in warning band
        
        # At 8% drawdown (between critical and severe)
        sizer.update_portfolio_value(920000.0)
        multiplier = sizer.get_drawdown_size_multiplier()
        assert multiplier == 0.5  # Should be in critical band

    @pytest.mark.asyncio
    async def test_volatility_sizing_applies_drawdown_multiplier(self):
        """Test that volatility-based sizing applies drawdown multiplier."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_position_risk": 0.01,
                "stop_loss_atr_multiplier": 2.0,
                "take_profit_atr_multiplier": 3.0
            },
            "drawdown_thresholds": {
                "warning": 0.05,
                "critical": 0.10,
                "severe": 0.15
            }
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
        
        # Calculate at no drawdown
        result_no_dd = await sizer.calculate_position_size("BTC", "volatility_based", 1.0)
        
        # Apply 10% drawdown (critical level)
        sizer.update_portfolio_value(900000.0)
        result_with_dd = await sizer.calculate_position_size("BTC", "volatility_based", 1.0)
        
        # Position size should be 50% of original
        assert result_with_dd is not None
        assert result_no_dd is not None
        assert result_with_dd.position_size == result_no_dd.position_size * 0.5

    @pytest.mark.asyncio
    async def test_kelly_sizing_applies_drawdown_multiplier(self):
        """Test that Kelly criterion sizing applies drawdown multiplier."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_position_risk": 0.01,
                "stop_loss_atr_multiplier": 2.0,
                "take_profit_atr_multiplier": 3.0
            },
            "drawdown_thresholds": {
                "warning": 0.05,
                "critical": 0.10,
                "severe": 0.15
            }
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
        
        # Calculate at no drawdown
        result_no_dd = await sizer.calculate_position_size("ETH", "kelly_criterion", 1.0)
        
        # Apply 5% drawdown (warning level)
        sizer.update_portfolio_value(950000.0)
        result_with_dd = await sizer.calculate_position_size("ETH", "kelly_criterion", 1.0)
        
        # Position size should be 80% of original
        assert result_with_dd is not None
        assert result_no_dd is not None
        assert result_with_dd.position_size == result_no_dd.position_size * 0.8

    @pytest.mark.asyncio
    async def test_fixed_fractional_sizing_applies_drawdown_multiplier(self):
        """Test that fixed fractional sizing applies drawdown multiplier."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_position_risk": 0.01,
                "stop_loss_atr_multiplier": 2.0,
                "take_profit_atr_multiplier": 3.0
            },
            "drawdown_thresholds": {
                "warning": 0.05,
                "critical": 0.10,
                "severe": 0.15
            }
        }
        sizer = PositionSizer(config)
        
        position = Position(
            symbol="SOL",
            current_price=100.0,
            volatility=0.04,
            max_position_size=0.1,
            min_position_size=0.01
        )
        sizer.add_position(position)
        
        # Calculate at no drawdown
        result_no_dd = await sizer.calculate_position_size("SOL", "fixed_fractional", 1.0)
        
        # Apply 15% drawdown (severe level)
        sizer.update_portfolio_value(850000.0)
        result_with_dd = await sizer.calculate_position_size("SOL", "fixed_fractional", 1.0)
        
        # Position size should be 25% of original
        assert result_with_dd is not None
        assert result_no_dd is not None
        assert result_with_dd.position_size == result_no_dd.position_size * 0.25

    @pytest.mark.asyncio
    async def test_risk_parity_sizing_applies_drawdown_multiplier(self):
        """Test that risk parity sizing applies drawdown multiplier."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "stop_loss_atr_multiplier": 2.0,
                "take_profit_atr_multiplier": 3.0
            },
            "drawdown_thresholds": {
                "warning": 0.05,
                "critical": 0.10,
                "severe": 0.15
            }
        }
        sizer = PositionSizer(config)
        
        position = Position(
            symbol="XRP",
            current_price=0.5,
            volatility=0.05,
            max_position_size=0.1,
            min_position_size=0.01
        )
        sizer.add_position(position)
        
        # Calculate at no drawdown
        result_no_dd = await sizer.calculate_position_size("XRP", "risk_parity", 1.0)
        
        # Apply 12% drawdown (between critical and severe - should be 50%)
        sizer.update_portfolio_value(880000.0)
        result_with_dd = await sizer.calculate_position_size("XRP", "risk_parity", 1.0)
        
        # Position size should be 50% of original (critical band)
        assert result_with_dd is not None
        assert result_no_dd is not None
        assert result_with_dd.position_size == result_no_dd.position_size * 0.5
