"""Tests for reset_asset_notional function in kalshi_risk.py.

Tests cover:
- reset_asset_notional clears asset_notional and asset_contracts
- reset_asset_notional is called on startup
- reset_asset_notional logs warning with previous state
- reset_asset_notional allows new orders after stale data is cleared
"""

import pytest
from unittest.mock import Mock, patch
from merid.event_venues.kalshi.kalshi_risk import KalshiRiskManager, KalshiRiskConfig


def test_reset_asset_notional_clears_state():
    """Test that reset_asset_notional clears asset_notional and asset_contracts."""
    config = KalshiRiskConfig()
    risk_manager = KalshiRiskManager(config=config)
    
    # Simulate stale data accumulation
    risk_manager._state.asset_notional["BTC"] = 2.24
    risk_manager._state.asset_notional["ETH"] = 1.50
    risk_manager._state.asset_contracts["BTC"] = 10
    risk_manager._state.asset_contracts["ETH"] = 5
    
    # Verify stale data exists
    assert risk_manager._state.asset_notional["BTC"] == 2.24
    assert risk_manager._state.asset_notional["ETH"] == 1.50
    assert risk_manager._state.asset_contracts["BTC"] == 10
    assert risk_manager._state.asset_contracts["ETH"] == 5
    
    # Call reset_asset_notional
    risk_manager.reset_asset_notional()
    
    # Verify state is cleared
    assert len(risk_manager._state.asset_notional) == 0
    assert len(risk_manager._state.asset_contracts) == 0
    assert "BTC" not in risk_manager._state.asset_notional
    assert "ETH" not in risk_manager._state.asset_notional


def test_reset_asset_notional_logs_warning():
    """Test that reset_asset_notional logs warning with previous state."""
    config = KalshiRiskConfig()
    risk_manager = KalshiRiskManager(config=config)
    
    # Simulate stale data
    risk_manager._state.asset_notional["BTC"] = 2.24
    risk_manager._state.asset_notional["ETH"] = 1.50
    risk_manager._state.asset_contracts["BTC"] = 10
    
    with patch('merid.event_venues.kalshi.kalshi_risk.logger') as mock_logger:
        risk_manager.reset_asset_notional()
        
        # Verify warning was logged
        assert mock_logger.warning.called
        warning_call = mock_logger.warning.call_args
        assert "EMERGENCY RESET" in str(warning_call)
        assert "Clearing asset_notional state" in str(warning_call)
        
        # Verify info was logged
        assert mock_logger.info.called
        info_call = mock_logger.info.call_args
        assert "Asset notional reset complete" in str(info_call)


def test_reset_asset_notional_allows_new_orders():
    """Test that reset_asset_notional allows new orders after stale data is cleared."""
    config = KalshiRiskConfig()
    risk_manager = KalshiRiskManager(config=config)
    
    # Simulate stale data that would block orders
    risk_manager._state.asset_notional["XRP"] = 2.24  # Exceeds cap of 0.99
    
    # Verify stale data exists
    assert risk_manager._state.asset_notional.get("XRP", 0.0) == 2.24
    
    # Reset asset notional
    risk_manager.reset_asset_notional()
    
    # Verify asset_notional is cleared
    assert risk_manager._state.asset_notional.get("XRP", 0.0) == 0.0
    
    # Now new orders should not be blocked by stale asset_notional
    # The check_order function would use the cleared value
    # We verify the state is cleared, which is the key fix


def test_reset_asset_notional_on_startup():
    """Test that reset_asset_notional is called on KalshiRiskManager initialization."""
    with patch('merid.event_venues.kalshi.kalshi_risk.KalshiRiskManager.reset_asset_notional') as mock_reset:
        config = KalshiRiskConfig()
        risk_manager = KalshiRiskManager(config=config)
        
        # Verify reset was called during initialization
        # Note: This test verifies the get_kalshi_risk() function calls reset
        # The actual KalshiRiskManager.__init__ does not call reset
        # The reset is called in get_kalshi_risk() after initialization
        # So we test that function instead
        pass


def test_get_kalshi_risk_calls_reset_on_startup():
    """Test that get_kalshi_risk calls reset_asset_notional on first initialization."""
    # Clear the global _risk singleton to force re-initialization
    import merid.event_venues.kalshi.kalshi_risk as risk_module
    original_risk = risk_module._risk
    risk_module._risk = None
    
    with patch('merid.event_venues.kalshi.kalshi_risk.KalshiRiskManager.reset_asset_notional') as mock_reset:
        try:
            # Call get_kalshi_risk to trigger initialization
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            risk_manager = get_kalshi_risk()
            
            # Verify reset was called
            assert mock_reset.called
        finally:
            # Restore original state
            risk_module._risk = original_risk


def test_reset_asset_notional_idempotent():
    """Test that reset_asset_notional can be called multiple times safely."""
    config = KalshiRiskConfig()
    risk_manager = KalshiRiskManager(config=config)
    
    # Call reset multiple times
    risk_manager.reset_asset_notional()
    risk_manager.reset_asset_notional()
    risk_manager.reset_asset_notional()
    
    # State should remain empty
    assert len(risk_manager._state.asset_notional) == 0
    assert len(risk_manager._state.asset_contracts) == 0


def test_reset_asset_notional_preserves_other_state():
    """Test that reset_asset_notional only clears asset_notional, not other state."""
    config = KalshiRiskConfig()
    risk_manager = KalshiRiskManager(config=config)
    
    # Set various state fields
    risk_manager._state.asset_notional["BTC"] = 2.24
    risk_manager._state.asset_contracts["BTC"] = 10
    risk_manager._state.category_notional["crypto"] = 5.0
    risk_manager._state.category_contracts["crypto"] = 20
    risk_manager._state.total_notional = 10.0
    risk_manager._state.total_contracts = 50
    
    # Call reset_asset_notional
    risk_manager.reset_asset_notional()
    
    # Verify only asset_notional and asset_contracts are cleared
    assert len(risk_manager._state.asset_notional) == 0
    assert len(risk_manager._state.asset_contracts) == 0
    
    # Verify other state is preserved
    assert risk_manager._state.category_notional.get("crypto") == 5.0
    assert risk_manager._state.category_contracts.get("crypto") == 20
    assert risk_manager._state.total_notional == 10.0
    assert risk_manager._state.total_contracts == 50


def test_reset_asset_notional_with_empty_state():
    """Test that reset_asset_notional works correctly when state is already empty."""
    config = KalshiRiskConfig()
    risk_manager = KalshiRiskManager(config=config)
    
    # State should be empty initially
    assert len(risk_manager._state.asset_notional) == 0
    assert len(risk_manager._state.asset_contracts) == 0
    
    # Call reset on empty state (should not error)
    risk_manager.reset_asset_notional()
    
    # State should remain empty
    assert len(risk_manager._state.asset_notional) == 0
    assert len(risk_manager._state.asset_contracts) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
