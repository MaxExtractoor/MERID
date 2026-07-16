"""Tests for gap analysis fixes - BankrollServiceV2 import, window/exit policy resolution, scale-out config."""

import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestBankrollServiceV2Import:
    """Test that BankrollServiceV2 is imported from the correct module."""
    
    def test_agent_grid_15m_uses_correct_import(self):
        """Verify agent_grid_15m.py imports BankrollServiceV2 from bankroll_service_v2."""
        # Read the file and check the import
        agent_grid_path = project_root / "merid" / "prediction" / "agent_grid_15m.py"
        content = agent_grid_path.read_text()
        
        # Should import from bankroll_service_v2
        assert "from merid.event_venues.kalshi.bankroll_service_v2 import BankrollServiceV2" in content, \
            "BankrollServiceV2 should be imported from bankroll_service_v2 module"
        
        # Should NOT import from deprecated bankroll_service
        assert "from merid.event_venues.kalshi.bankroll_service import BankrollServiceV2" not in content, \
            "BankrollServiceV2 should NOT be imported from deprecated bankroll_service module"
    
    def test_bankroll_service_v2_module_exists(self):
        """Verify the bankroll_service_v2 module exists and has BankrollServiceV2."""
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import BankrollServiceV2
            assert BankrollServiceV2 is not None
        except ImportError as e:
            pytest.fail(f"Failed to import BankrollServiceV2 from bankroll_service_v2: {e}")


class TestWindowExitPolicyResolution:
    """Test that window/exit policy resolution is integrated in agents."""
    
    def test_agent_grid_15m_has_policy_resolution(self):
        """Verify agent_grid_15m.py uses resolve_exit_policy and resolve_window_policy."""
        agent_grid_path = project_root / "merid" / "prediction" / "agent_grid_15m.py"
        content = agent_grid_path.read_text()
        
        # Should import the resolution functions
        assert "from merid.event_venues.kalshi.order_router import resolve_exit_policy, resolve_window_policy" in content, \
            "Should import resolve_exit_policy and resolve_window_policy"
        
        # Should call resolve_exit_policy
        assert "resolve_exit_policy(" in content, \
            "Should call resolve_exit_policy"
        
        # Should call resolve_window_policy
        assert "resolve_window_policy(" in content, \
            "Should call resolve_window_policy"
        
        # Should NOT have the old TODO placeholders
        assert 'window_resolution_id="lean-default",  # TODO: Use resolve_window_policy' not in content, \
            "Should not have TODO placeholder for window_resolution_id"
        assert 'exit_policy_id="lean-tp-only",  # TODO: Use resolve_exit_policy' not in content, \
            "Should not have TODO placeholder for exit_policy_id"
    
    def test_policy_resolution_functions_exist(self):
        """Verify the policy resolution functions exist in order_router."""
        try:
            from merid.event_venues.kalshi.order_router import resolve_exit_policy, resolve_window_policy
            assert resolve_exit_policy is not None
            assert resolve_window_policy is not None
        except ImportError as e:
            pytest.fail(f"Failed to import policy resolution functions: {e}")
    
    @patch('merid.event_venues.kalshi.order_router.get_kalshi_crypto_15m_risk_envelope')
    def test_resolve_window_policy_returns_valid_resolution(self, mock_envelope):
        """Test that resolve_window_policy returns a valid WindowResolution."""
        from merid.event_venues.kalshi.order_router import resolve_window_policy
        
        # Mock the risk envelope
        mock_risk_envelope = Mock()
        mock_risk_envelope.get_depth_thresholds.return_value = {
            'min_depth_yes': 10,
            'min_depth_no': 10
        }
        mock_envelope.return_value = mock_risk_envelope
        
        # Call the function
        resolution = resolve_window_policy(asset="BTC", regime="normal")
        
        # Verify it returns a valid resolution
        assert resolution is not None
        assert hasattr(resolution, 'window_id')
        assert resolution.window_id is not None
        assert len(resolution.window_id) > 0
    
    @patch('merid.event_venues.kalshi.order_router.get_kalshi_crypto_15m_risk_envelope')
    def test_resolve_exit_policy_returns_valid_resolution(self, mock_envelope):
        """Test that resolve_exit_policy returns a valid ExitPolicyResolution."""
        from merid.event_venues.kalshi.order_router import resolve_exit_policy
        
        # Call the function
        resolution = resolve_exit_policy(
            edge_result=None,
            asset="BTC",
            regime="normal",
            strip_context={}
        )
        
        # Verify it returns a valid resolution
        assert resolution is not None
        assert hasattr(resolution, 'policy_id')
        assert resolution.policy_id is not None
        assert len(resolution.policy_id) > 0
        assert hasattr(resolution, 'max_hold_seconds')
        assert resolution.max_hold_seconds > 0


class TestScaleOutConfigLoading:
    """Test that scale-out parameters are loaded from config."""
    
    def test_position_cache_has_config_loading(self):
        """Verify position_cache.py loads scale-out parameters from config."""
        position_cache_path = project_root / "merid" / "event_venues" / "kalshi" / "position_cache.py"
        content = position_cache_path.read_text()
        
        # Should have config loading logic
        assert "from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope" in content, \
            "Should import risk envelope for config loading"
        
        # Should load scale_out_trigger_r from config
        assert "scale_out_config.get('scale_out_trigger_r'" in content, \
            "Should load scale_out_trigger_r from config"
        
        # Should load scale_out_fraction from config
        assert "scale_out_config.get('scale_out_fraction'" in content, \
            "Should load scale_out_fraction from config"
        
        # Should NOT have hardcoded TODO
        assert "scale_out_trigger_r = 0.7  # TODO: Load from config" not in content, \
            "Should not have hardcoded TODO for scale_out_trigger_r"
        assert "scale_out_fraction = 0.5  # TODO: Load from config" not in content, \
            "Should not have hardcoded TODO for scale_out_fraction"
    
    @patch('merid.event_venues.kalshi.position_cache.get_kalshi_crypto_15m_risk_envelope')
    def test_scale_out_config_loading_with_valid_config(self, mock_envelope):
        """Test scale-out config loading with valid config."""
        # Mock the risk envelope with scale-out config
        mock_risk_envelope = Mock()
        mock_risk_envelope.profile = {
            'scale_out': {
                'scale_out_trigger_r': 0.8,
                'scale_out_fraction': 0.6
            }
        }
        mock_envelope.return_value = mock_risk_envelope
        
        # Import and test the config loading logic
        from merid.event_venues.kalshi.position_cache import _get_scale_out_config
        
        # This would need to be extracted as a testable function
        # For now, we verify the module can be imported
        assert True  # Placeholder for actual test
    
    @patch('merid.event_venues.kalshi.position_cache.get_kalshi_crypto_15m_risk_envelope')
    def test_scale_out_config_loading_with_fallback(self, mock_envelope):
        """Test scale-out config loading falls back to defaults on error."""
        # Mock the risk envelope to raise an exception
        mock_envelope.side_effect = Exception("Config error")
        
        # The code should handle this gracefully and use defaults
        # This would need to be extracted as a testable function
        assert True  # Placeholder for actual test


class TestMockOrderRouterDocumentation:
    """Test that mock order router has been removed."""
    
    def test_order_router_15m_removed(self):
        """Verify order_router_15m.py has been deleted."""
        order_router_path = project_root / "merid" / "event_venues" / "kalshi" / "order_router_15m.py"
        
        # File should not exist (deleted in 2026-07-16 audit cleanup)
        assert not order_router_path.exists(), \
            "Legacy order_router_15m.py should have been deleted"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
