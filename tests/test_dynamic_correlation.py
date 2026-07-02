"""Tests for dynamic correlation matrix updates."""
import pytest
import numpy as np
from collections import deque
from merid.risk.position_sizing import PositionSizer, Position, RiskParameters


class TestDynamicCorrelationMatrix:
    """Test dynamic correlation matrix calculation and updates."""
    
    def test_price_history_initialization(self):
        """Test that price history is initialized correctly."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
            "correlation_window": 30,
        }
        sizer = PositionSizer(config)
        
        assert sizer.price_history == {}
        assert sizer.correlation_window == 30
    
    def test_update_price_creates_history(self):
        """Test that updating price creates history for new symbol."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        sizer.update_price("BTC", 50000.0)
        
        assert "BTC" in sizer.price_history
        assert len(sizer.price_history["BTC"]) == 1
        assert sizer.price_history["BTC"][0] == 50000.0
    
    def test_update_price_appends_to_history(self):
        """Test that updating price appends to existing history."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        sizer.update_price("BTC", 50000.0)
        sizer.update_price("BTC", 50100.0)
        sizer.update_price("BTC", 50200.0)
        
        assert len(sizer.price_history["BTC"]) == 3
        assert list(sizer.price_history["BTC"]) == [50000.0, 50100.0, 50200.0]
    
    def test_price_history_maxlen(self):
        """Test that price history respects maxlen."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
            "correlation_window": 5,
        }
        sizer = PositionSizer(config)
        
        # Add more prices than window size
        for i in range(10):
            sizer.update_price("BTC", 50000.0 + i)
        
        # Should only keep last 5
        assert len(sizer.price_history["BTC"]) == 5
        assert list(sizer.price_history["BTC"]) == [50005.0, 50006.0, 50007.0, 50008.0, 50009.0]
    
    def test_calculate_dynamic_correlation_insufficient_positions(self):
        """Test that correlation calculation returns None with insufficient positions."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        # Add only one position
        position = Position(
            symbol="BTC",
            current_price=50000.0,
            volatility=0.02,
            max_position_size=0.1,
            min_position_size=0.01
        )
        sizer.add_position(position)
        
        result = sizer.calculate_dynamic_correlation_matrix()
        
        assert result is None
    
    def test_calculate_dynamic_correlation_insufficient_history(self):
        """Test that correlation calculation returns None with insufficient price history."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        # Add two positions
        btc = Position(symbol="BTC", current_price=50000.0, volatility=0.02, max_position_size=0.1, min_position_size=0.01)
        eth = Position(symbol="ETH", current_price=3000.0, volatility=0.03, max_position_size=0.1, min_position_size=0.01)
        sizer.add_position(btc)
        sizer.add_position(eth)
        
        # Add insufficient price history (less than 10 points)
        for i in range(5):
            sizer.update_price("BTC", 50000.0 + i)
            sizer.update_price("ETH", 3000.0 + i * 0.1)
        
        result = sizer.calculate_dynamic_correlation_matrix()
        
        assert result is None
    
    def test_calculate_dynamic_correlation_success(self):
        """Test successful dynamic correlation calculation."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        # Add two positions
        btc = Position(symbol="BTC", current_price=50000.0, volatility=0.02, max_position_size=0.1, min_position_size=0.01)
        eth = Position(symbol="ETH", current_price=3000.0, volatility=0.03, max_position_size=0.1, min_position_size=0.01)
        sizer.add_position(btc)
        sizer.add_position(eth)
        
        # Add sufficient price history with correlation
        for i in range(20):
            # BTC and ETH move together (high correlation)
            btc_price = 50000.0 + i * 100
            eth_price = 3000.0 + i * 6  # Scaled to BTC movement
            sizer.update_price("BTC", btc_price)
            sizer.update_price("ETH", eth_price)
        
        result = sizer.calculate_dynamic_correlation_matrix()
        
        assert result is not None
        assert result.shape == (2, 2)
        assert np.allclose(np.diag(result), 1.0)  # Diagonal should be 1.0
        # Off-diagonal should be high (correlated)
        assert result[0, 1] > 0.9
        assert result[1, 0] > 0.9
    
    def test_calculate_dynamic_correlation_multiple_positions(self):
        """Test correlation calculation with multiple positions."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        # Add three positions
        btc = Position(symbol="BTC", current_price=50000.0, volatility=0.02, max_position_size=0.1, min_position_size=0.01)
        eth = Position(symbol="ETH", current_price=3000.0, volatility=0.03, max_position_size=0.1, min_position_size=0.01)
        sol = Position(symbol="SOL", current_price=100.0, volatility=0.04, max_position_size=0.1, min_position_size=0.01)
        sizer.add_position(btc)
        sizer.add_position(eth)
        sizer.add_position(sol)
        
        # Add price history
        for i in range(20):
            sizer.update_price("BTC", 50000.0 + i * 100)
            sizer.update_price("ETH", 3000.0 + i * 6)
            sizer.update_price("SOL", 100.0 + i * 0.2)
        
        result = sizer.calculate_dynamic_correlation_matrix()
        
        assert result is not None
        assert result.shape == (3, 3)
        assert np.allclose(np.diag(result), 1.0)
    
    def test_calculate_dynamic_correlation_uncorrelated(self):
        """Test correlation calculation with uncorrelated assets."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        # Add two positions
        btc = Position(symbol="BTC", current_price=50000.0, volatility=0.02, max_position_size=0.1, min_position_size=0.01)
        eth = Position(symbol="ETH", current_price=3000.0, volatility=0.03, max_position_size=0.1, min_position_size=0.01)
        sizer.add_position(btc)
        sizer.add_position(eth)
        
        # Add price history with random movements (uncorrelated)
        import random
        random.seed(42)
        for i in range(20):
            btc_price = 50000.0 + random.uniform(-500, 500)
            eth_price = 3000.0 + random.uniform(-100, 100)
            sizer.update_price("BTC", btc_price)
            sizer.update_price("ETH", eth_price)
        
        result = sizer.calculate_dynamic_correlation_matrix()
        
        assert result is not None
        assert result.shape == (2, 2)
        # Off-diagonal should be low (uncorrelated)
        assert abs(result[0, 1]) < 0.5
    
    def test_correlation_matrix_updates_sizer_matrix(self):
        """Test that dynamic calculation updates sizer's correlation matrix."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
        }
        sizer = PositionSizer(config)
        
        # Add positions
        btc = Position(symbol="BTC", current_price=50000.0, volatility=0.02, max_position_size=0.1, min_position_size=0.01)
        eth = Position(symbol="ETH", current_price=3000.0, volatility=0.03, max_position_size=0.1, min_position_size=0.01)
        sizer.add_position(btc)
        sizer.add_position(eth)
        
        # Add price history
        for i in range(20):
            sizer.update_price("BTC", 50000.0 + i * 100)
            sizer.update_price("ETH", 3000.0 + i * 6)
        
        # Calculate dynamic correlation
        result = sizer.calculate_dynamic_correlation_matrix()
        
        # Check that sizer's matrix was updated
        assert sizer.correlation_matrix is not None
        assert np.array_equal(sizer.correlation_matrix, result)
    
    def test_correlation_matrix_handles_nan(self):
        """Test that correlation matrix handles NaN values (zero variance)."""
        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning)
            
            config = {
                "portfolio_value": 1000000.0,
                "risk_parameters": {
                    "max_portfolio_risk": 0.02,
                    "max_position_risk": 0.01,
                },
            }
            sizer = PositionSizer(config)
            
            # Add positions
            btc = Position(symbol="BTC", current_price=50000.0, volatility=0.02, max_position_size=0.1, min_position_size=0.01)
            eth = Position(symbol="ETH", current_price=3000.0, volatility=0.03, max_position_size=0.1, min_position_size=0.01)
            sizer.add_position(btc)
            sizer.add_position(eth)
            
            # Add price history with zero variance for one asset
            for i in range(20):
                sizer.update_price("BTC", 50000.0)  # Constant price (zero variance)
                sizer.update_price("ETH", 3000.0 + i * 6)
            
            result = sizer.calculate_dynamic_correlation_matrix()
            
            assert result is not None
            assert not np.any(np.isnan(result))  # No NaN values
            assert np.allclose(np.diag(result), 1.0)  # Diagonal still 1.0
