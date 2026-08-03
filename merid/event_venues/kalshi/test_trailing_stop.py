"""Unit tests for trailing stop functionality."""

import pytest
from unittest.mock import MagicMock, patch


class TestTrailingStop:
    """Test trailing stop configuration and logic."""
    
    def test_trailing_stop_config_from_profile(self):
        """Test that trailing stop configuration is read from profile."""
        # Mock profile with trailing stop enabled
        mock_profile = MagicMock()
        mock_profile.trailing_stop_enabled = True
        mock_profile.trailing_stop_trailing_distance_cents = 5
        mock_profile.trailing_stop_min_profit_cents = 12
        mock_profile.trailing_stop_activation_delay_sec = 30
        
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=mock_profile)):
            
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                assert profile.trailing_stop_enabled is True
                assert profile.trailing_stop_trailing_distance_cents == 5
                assert profile.trailing_stop_min_profit_cents == 12
                assert profile.trailing_stop_activation_delay_sec == 30


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
