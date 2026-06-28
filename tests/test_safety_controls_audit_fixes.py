"""Tests for safety controls audit fixes.

Tests for fixes applied during the safety controls deep audit:
- Environment variable validation
- Bankroll-profile consistency validation (skip scenarios only)
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import os


class TestEnvironmentVariableValidation:
    """Test environment variable validation."""
    
    @patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=True)
    def test_validation_fails_missing_kalshi_vars(self):
        """Test that validation fails when Kalshi-specific vars are missing."""
        from merid.startup_validations import validate_required_environment_variables
        from merid.startup_validations import StartupValidationError
        
        # Clear Kalshi-specific vars
        for var in ['KALSHI_ENV', 'KALSHI_API_KEY_ID', 'KALSHI_PRIVATE_KEY_PATH']:
            os.environ.pop(var, None)
        
        # Should raise StartupValidationError
        with pytest.raises(StartupValidationError, match="Critical environment variables missing"):
            validate_required_environment_variables()
    
    @patch.dict(os.environ, {
        'MERID_PROFILE': 'kalshi_crypto_15m_v2',
        'KALSHI_ENV': 'demo',
        'KALSHI_API_KEY_ID': 'test_key',
        'KALSHI_PRIVATE_KEY_PATH': 'test.pem'
    })
    def test_validation_passes_with_all_required_vars(self):
        """Test that validation passes with all required variables set."""
        from merid.startup_validations import validate_required_environment_variables
        
        # Should not raise
        validate_required_environment_variables()
    
    @patch.dict(os.environ, {'MERID_PROFILE': 'full'})
    def test_validation_passes_for_non_kalshi_profile(self):
        """Test that validation passes for non-Kalshi profiles without Kalshi vars."""
        from merid.startup_validations import validate_required_environment_variables
        
        # Should not raise even without Kalshi vars
        validate_required_environment_variables()


class TestBankrollProfileConsistencyValidation:
    """Test bankroll-profile consistency validation."""
    
    @patch.dict(os.environ, {'MERID_PROFILE': 'full'})
    def test_validation_skips_for_non_15m_profile(self):
        """Test that validation skips for non-15m profiles."""
        from merid.startup_validations import validate_bankroll_profile_consistency
        
        # Should not raise, just skip
        validate_bankroll_profile_consistency()
    
    @patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'})
    @patch('merid.risk.profiles.crypto_15m_profile.get_active_profile')
    @patch('merid.event_venues.kalshi.bankroll_service_v2.get_bankroll_service', new_callable=Mock)
    def test_validation_skips_when_bankroll_service_none(self, mock_get_bankroll, mock_get_profile):
        """Test that validation skips when bankroll service is None."""
        from merid.startup_validations import validate_bankroll_profile_consistency
        
        mock_get_profile.return_value = Mock(profile=Mock())
        mock_get_bankroll.return_value = None
        
        # Should not raise, just skip
        validate_bankroll_profile_consistency()
    
    @patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'})
    @patch('merid.risk.profiles.crypto_15m_profile.get_active_profile')
    @patch('merid.event_venues.kalshi.bankroll_service_v2.get_bankroll_service', new_callable=Mock)
    def test_validation_skips_when_live_bankroll_none(self, mock_get_bankroll, mock_get_profile):
        """Test that validation skips when live bankroll is None."""
        from merid.startup_validations import validate_bankroll_profile_consistency
        
        mock_adapter = Mock()
        mock_adapter.profile = Mock()
        mock_get_profile.return_value = mock_adapter
        
        mock_bankroll_service = Mock()
        mock_bankroll_service.get_live_bankroll = Mock(return_value=None)
        mock_get_bankroll.return_value = mock_bankroll_service
        
        # Should not raise, just skip
        validate_bankroll_profile_consistency()
    
    @patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'})
    @patch('merid.risk.profiles.crypto_15m_profile.get_active_profile')
    @patch('merid.event_venues.kalshi.bankroll_service_v2.get_bankroll_service', new_callable=Mock)
    def test_validation_skips_gracefully_for_async_service(self, mock_get_bankroll, mock_get_profile):
        """Test that validation skips gracefully when bankroll service is async."""
        from merid.startup_validations import validate_bankroll_profile_consistency
        
        mock_get_profile.return_value = Mock(profile=Mock())
        # Force an async coroutine to test the skip path
        import asyncio
        async def async_func():
            return Mock()
        mock_get_bankroll.return_value = async_func()
        
        # Should not raise, just skip with warning
        validate_bankroll_profile_consistency()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
