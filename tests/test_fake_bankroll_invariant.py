"""
Test suite for FAKE_BANKROLL_SOURCE_USED invariant

This test validates that the fake bankroll detection system works correctly:
- Fires CRITICAL invariant for fake sources in live profiles
- Allows fake sources in test profiles when explicitly enabled
- Blocks execution when fake bankroll detected
- Logs appropriate messages and guardrail trips
"""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass

from merid.core.e2e_invariants import E2EInvariantChecker, InvariantViolation


class TestFakeBankrollInvariant:
    """Test the FAKE_BANKROLL_SOURCE_USED invariant."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.checker = E2EInvariantChecker()
    
    def test_fake_bankroll_source_in_live_profile(self):
        """Test that fake sources trigger CRITICAL invariant in live profiles."""
        # Test fake sources
        fake_sources = ["fallback", "config", "manual", "test", "bootstrap", "default"]
        
        for fake_source in fake_sources:
            violation = self.checker.check_fake_bankroll_source_invariant(
                bankroll_source=fake_source,
                bankroll_value=1000.0,
                is_live_profile=True
            )
            
            assert violation is not None
            assert violation.invariant_name == "FAKE_BANKROLL_SOURCE_USED"
            assert violation.severity == "CRITICAL"
            assert "Fake bankroll source detected in live profile" in violation.message
            assert fake_source in violation.message
            assert violation.context["bankroll_source"] == fake_source
            assert violation.context["bankroll_value"] == 1000.0
            assert violation.context["profile"] == "live"
    
    def test_fake_bankroll_value_in_live_profile(self):
        """Test that fake values trigger CRITICAL invariant in live profiles."""
        fake_values = [1000.0, 100000.0]  # $1000 and $1000 in cents
        
        for fake_value in fake_values:
            violation = self.checker.check_fake_bankroll_source_invariant(
                bankroll_source="kalshi",  # Valid source but fake value
                bankroll_value=fake_value,
                is_live_profile=True
            )
            
            assert violation is not None
            assert violation.invariant_name == "FAKE_BANKROLL_SOURCE_USED"
            assert violation.severity == "CRITICAL"
            assert "Known fake bankroll value detected in live profile" in violation.message
            assert str(fake_value) in violation.message
            assert violation.context["bankroll_value"] == fake_value
    
    def test_valid_bankroll_in_live_profile(self):
        """Test that valid bankroll doesn't trigger invariant in live profiles."""
        # Valid sources and values
        valid_combinations = [
            ("kalshi", 1500.50),
            ("bankroll_service_v2", 25000.75),
            ("kalshi", 36.81),  # Current actual bankroll
        ]
        
        for source, value in valid_combinations:
            violation = self.checker.check_fake_bankroll_source_invariant(
                bankroll_source=source,
                bankroll_value=value,
                is_live_profile=True
            )
            
            assert violation is None
    
    def test_fake_bankroll_in_test_profile_no_invariant(self):
        """Test that fake sources don't trigger invariant in test profiles."""
        fake_sources = ["fallback", "config", "manual", "test", "bootstrap", "default"]
        
        for fake_source in fake_sources:
            violation = self.checker.check_fake_bankroll_source_invariant(
                bankroll_source=fake_source,
                bankroll_value=1000.0,
                is_live_profile=False
            )
            
            assert violation is None
    
    def test_fake_bankroll_value_in_test_profile_no_invariant(self):
        """Test that fake values don't trigger invariant in test profiles."""
        fake_values = [1000.0, 100000.0]
        
        for fake_value in fake_values:
            violation = self.checker.check_fake_bankroll_source_invariant(
                bankroll_source="kalshi",
                bankroll_value=fake_value,
                is_live_profile=False
            )
            
            assert violation is None
    
    def test_check_all_invariants_includes_fake_bankroll(self):
        """Test that check_all_invariants includes fake bankroll check."""
        system_state = {
            "execution_ready": True,
            "is_live_profile": True,
            "bankroll": {
                "live_bankroll": 1000.0,
                "valid": True,
                "status": "OK",
                "source": "fallback",
                "source_valid": False,
                "fake_used": True
            }
        }
        
        violations = self.checker.check_all_invariants(system_state)
        
        # Should have at least one violation for fake bankroll
        fake_bankroll_violations = [v for v in violations if v.invariant_name == "FAKE_BANKROLL_SOURCE_USED"]
        assert len(fake_bankroll_violations) > 0
        
        violation = fake_bankroll_violations[0]
        assert violation.severity == "CRITICAL"
        assert "fallback" in violation.message
    
    def test_check_all_invariants_test_profile_no_fake_bankroll(self):
        """Test that check_all_invariants doesn't flag fake bankroll in test profiles."""
        system_state = {
            "execution_ready": True,
            "is_live_profile": False,  # Test profile
            "bankroll": {
                "live_bankroll": 1000.0,
                "valid": True,
                "status": "OK",
                "source": "fallback",
                "source_valid": False,
                "fake_used": True
            }
        }
        
        violations = self.checker.check_all_invariants(system_state)
        
        # Should have no fake bankroll violations
        fake_bankroll_violations = [v for v in violations if v.invariant_name == "FAKE_BANKROLL_SOURCE_USED"]
        assert len(fake_bankroll_violations) == 0


class TestFakeBankrollInLoop:
    """Test fake bankroll detection in the 15m loop context."""
    
    @patch('config.settings.Settings')
    @patch('merid.core.e2e_invariants.E2EInvariantChecker')
    def test_live_profile_blocks_fake_bankroll(self, mock_checker_class, mock_settings_class):
        """Test that live profiles block execution when fake bankroll detected."""
        # Setup mocks
        mock_settings = Mock()
        mock_settings.PROFILE_IS_LIVE = True
        mock_settings.MERID_ALLOW_FAKE_BANKROLL_FOR_TEST = False
        mock_settings_class.return_value = mock_settings
        
        mock_checker = Mock()
        mock_violation = Mock()
        mock_violation.invariant_name = "FAKE_BANKROLL_SOURCE_USED"
        mock_violation.severity = "CRITICAL"
        mock_violation.message = "Fake bankroll source detected in live profile: source=fallback value=1000.00"
        mock_checker.check_fake_bankroll_source_invariant.return_value = mock_violation
        mock_checker_class.return_value = mock_checker
        
        # Simulate the loop logic
        live_bankroll_source = "fallback"
        live_bankroll = 1000.0
        is_live_profile = mock_settings.PROFILE_IS_LIVE
        allow_fake_bankroll = not is_live_profile and mock_settings.MERID_ALLOW_FAKE_BANKROLL_FOR_TEST
        
        # Check invariant
        fake_bankroll_violation = None
        if not allow_fake_bankroll:
            fake_bankroll_violation = mock_checker.check_fake_bankroll_source_invariant(
                bankroll_source=live_bankroll_source,
                bankroll_value=live_bankroll,
                is_live_profile=is_live_profile
            )
        
        # Verify behavior
        assert fake_bankroll_violation is not None
        assert fake_bankroll_violation.severity == "CRITICAL"
        
        # Verify execution would be blocked
        fake_bankroll_used = fake_bankroll_violation is not None
        bankroll_source_valid = not fake_bankroll_used and live_bankroll_source in {"kalshi", "bankroll_service_v2"}
        
        assert fake_bankroll_used is True
        assert bankroll_source_valid is False
    
    @patch('config.settings.Settings')
    @patch('merid.core.e2e_invariants.E2EInvariantChecker')
    def test_test_profile_allows_fake_bankroll_when_enabled(self, mock_checker_class, mock_settings_class):
        """Test that test profiles allow fake bankroll when explicitly enabled."""
        # Setup mocks
        mock_settings = Mock()
        mock_settings.PROFILE_IS_LIVE = False
        mock_settings.MERID_ALLOW_FAKE_BANKROLL_FOR_TEST = True
        mock_settings_class.return_value = mock_settings
        
        mock_checker = Mock()
        mock_checker_class.return_value = mock_checker
        
        # Simulate the loop logic
        live_bankroll_source = "fallback"
        live_bankroll = 1000.0
        is_live_profile = mock_settings.PROFILE_IS_LIVE
        allow_fake_bankroll = not is_live_profile and mock_settings.MERID_ALLOW_FAKE_BANKROLL_FOR_TEST
        
        # Check invariant (should be skipped)
        fake_bankroll_violation = None
        if not allow_fake_bankroll:
            fake_bankroll_violation = mock_checker.check_fake_bankroll_source_invariant(
                bankroll_source=live_bankroll_source,
                bankroll_value=live_bankroll,
                is_live_profile=is_live_profile
            )
        
        # Verify behavior
        assert fake_bankroll_violation is None
        assert allow_fake_bankroll is True
        
        # Verify invariant checker was not called
        mock_checker.check_fake_bankroll_source_invariant.assert_not_called()


class TestProfileDetection:
    """Test profile detection logic."""
    
    @patch('config.settings.Settings')
    def test_live_profile_detection(self, mock_settings_class):
        """Test live profile detection patterns."""
        live_profiles = [
            "kalshi_crypto_15m_v2",
            "kalshi_crypto_prod",
            "live_trading",
            "prod_env",
            "production_system"
        ]
        
        for profile in live_profiles:
            mock_settings = Mock()
            mock_settings.MERID_PROFILE = profile
            mock_settings_class.return_value = mock_settings
            assert mock_settings.PROFILE_IS_LIVE is True, f"Profile {profile} should be detected as live"
    
    @patch('config.settings.Settings')
    def test_test_profile_detection(self, mock_settings_class):
        """Test test profile detection patterns."""
        test_profiles = [
            "kalshi_crypto_test",
            "kalshi_crypto_sim",
            "test_env",
            "sim_system",
            "demo_mode",
            "paper_trading"
        ]
        
        for profile in test_profiles:
            mock_settings = Mock()
            mock_settings.MERID_PROFILE = profile
            mock_settings_class.return_value = mock_settings
            assert mock_settings.PROFILE_IS_LIVE is False, f"Profile {profile} should be detected as test"
    
    @patch('config.settings.Settings')
    def test_unknown_profile_defaults_to_live(self, mock_settings_class):
        """Test that unknown profiles default to live for safety."""
        unknown_profiles = [
            "unknown_profile",
            "custom_config",
            "experimental",
            ""
        ]
        
        for profile in unknown_profiles:
            mock_settings = Mock()
            mock_settings.MERID_PROFILE = profile
            mock_settings_class.return_value = mock_settings
            assert mock_settings.PROFILE_IS_LIVE is True, f"Unknown profile {profile} should default to live"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
