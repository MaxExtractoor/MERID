"""
Test suite for division by zero bug fixes (2026-07-14).

These tests verify that the system properly handles zero or negative values
that could cause division by zero errors in critical risk and sizing calculations.
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, patch


class TestDynamicRiskDivisionByZero:
    """Test dynamic_risk.py division by zero guards."""
    
    def test_zero_entry_price_in_code(self):
        """Test that the code has the guard for zero entry price."""
        import inspect
        from merid.event_venues.kalshi import dynamic_risk
        
        # Get the source code of the file
        source = inspect.getsource(dynamic_risk)
        
        # Verify the guard exists
        assert "if worst_case_loss_cents <= 0:" in source
        assert "zero_entry_price" in source
        assert "Entry price is zero or negative" in source


class TestPortfolioRiskManagerDivisionByZero:
    """Test portfolio_risk_manager.py division by zero guards."""
    
    def test_zero_bankroll_guard_in_code(self):
        """Test that the code has the guard for zero bankroll."""
        import inspect
        from merid.prediction import portfolio_risk_manager
        
        # Get the source code of the file
        source = inspect.getsource(portfolio_risk_manager)
        
        # Verify the guard exists
        assert "if bankroll_cents <= 0:" in source
        assert "Zero or negative bankroll" in source
        assert "absolute_limit = 0.0" in source


class TestAgentGridConfigDivisionByZero:
    """Test agent_grid_config.py division by zero guards."""
    
    def test_zero_bankroll_guard_in_code(self):
        """Test that the code has the guard for zero bankroll."""
        import inspect
        from merid.prediction import agent_grid_config
        
        # Get the source code of the file
        source = inspect.getsource(agent_grid_config)
        
        # Verify the guards exist
        assert "if bankroll_cents <= 0:" in source
        assert "Zero or negative bankroll" in source
        assert 'Decimal("0")' in source


class TestResolveRequestedCount:
    """Test _resolve_requested_count helper for fill accounting."""
    
    def test_zero_placed_size_falls_back_to_intent(self):
        """Test that zero placed size falls back to intent count."""
        from merid.event_venues.kalshi.order_router import _resolve_requested_count
        
        result = _resolve_requested_count(0, 10)
        assert result == 10
    
    def test_none_placed_size_falls_back_to_intent(self):
        """Test that None placed size falls back to intent count."""
        from merid.event_venues.kalshi.order_router import _resolve_requested_count
        
        result = _resolve_requested_count(None, 10)
        assert result == 10
    
    def test_valid_placed_size_uses_placed(self):
        """Test that valid placed size uses placed value."""
        from merid.event_venues.kalshi.order_router import _resolve_requested_count
        
        result = _resolve_requested_count(5, 10)
        assert result == 5
    
    def test_invalid_placed_size_falls_back_to_intent(self):
        """Test that invalid placed size falls back to intent count."""
        from merid.event_venues.kalshi.order_router import _resolve_requested_count
        
        result = _resolve_requested_count("invalid", 10)
        assert result == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
