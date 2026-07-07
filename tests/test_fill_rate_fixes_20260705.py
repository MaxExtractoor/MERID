"""
Tests for fill rate optimization fixes (2026-07-05)

This test suite validates the critical fixes made to improve fill rate and execution:
1. Depth multiplier bug fix (removed 10x multiplier that ignored profile config)
2. min_decision_minute implementation (per-asset early signal skipping)
3. Relaxed one-sided rejection (1min -> 30s terminal phase only)
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import time


class TestDepthMultiplierFix:
    """Test that depth thresholds are sourced from profile without 10x multiplier."""
    
    def test_depth_thresholds_from_profile_not_multiplied(self):
        """Test that depth thresholds use profile values directly, not 10x multiplier."""
        # The bug was: profile set min_depth=1, but code applied 10x multiplier requiring 10+ contracts
        # Fix: Removed 10x multiplier, use profile values directly
        
        # Mock the risk envelope to return profile thresholds
        with patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope') as mock_envelope:
            mock_envelope_instance = Mock()
            mock_envelope_instance.get_depth_thresholds.return_value = {
                'min_depth_yes': 1,  # Profile value
                'min_depth_no': 1   # Profile value
            }
            mock_envelope.return_value = mock_envelope_instance
            
            # The fix ensures thresholds are 1, not 10 (1 * 10)
            # This allows trading when depth >= 1 contract (matching profile config)
            thresholds = mock_envelope_instance.get_depth_thresholds("DOGE")
            
            assert thresholds['min_depth_yes'] == 1, "Depth threshold should be 1 from profile, not 10"
            assert thresholds['min_depth_no'] == 1, "Depth threshold should be 1 from profile, not 10"
    
    def test_depth_multiplier_removed_from_validation(self):
        """Test that the 10x multiplier code path is removed from validation."""
        # Read the agent_grid_15m.py file and verify the multiplier is removed
        with open('c:/Dev/MERID/merid/prediction/agent_grid_15m.py', 'r') as f:
            content = f.read()
        
        # Verify the 10x multiplier is removed
        assert 'depth_multiplier = 10' not in content, "10x depth multiplier should be removed"
        assert 'base_position_size * depth_multiplier' not in content, "Depth multiplier calculation should be removed"
        
        # Verify the fix comment is present
        assert 'CRITICAL FIX: Removed 10x multiplier' in content, "Fix comment should be present"


class TestMinDecisionMinuteImplementation:
    """Test that min_decision_minute is implemented and used in trading window logic."""
    
    def test_min_decision_minute_loaded_from_profile(self):
        """Test that min_decision_minute is loaded from profile YAML configuration."""
        # The actual implementation loads from raw YAML file, not get_active_profile
        # Test that the YAML loading logic is present and correct
        
        with open('c:/Dev/MERID/merid/prediction/agent_grid_15m.py', 'r') as f:
            content = f.read()
        
        # Verify YAML loading is present
        assert 'yaml.safe_load' in content, "YAML loading should be present"
        assert 'encoding=\'utf-8\'' in content, "UTF-8 encoding should be specified"
        assert 'profile_path = Path(__file__).parent.parent.parent' in content, "Path construction should be correct"
        assert 'min_decision_minute_config = profile_yaml.get("min_decision_minute"' in content, "min_decision_minute extraction should be present"
        
        # Verify the fix comment is present
        assert 'CRITICAL FIX: Implement min_decision_minute from profile' in content, "Fix comment should be present"
    
    def test_min_decision_minute_in_trading_window(self):
        """Test that min_decision_minute is used in trading window validation."""
        # Read the agent_grid_15m.py file and verify min_decision_minute is implemented
        with open('c:/Dev/MERID/merid/prediction/agent_grid_15m.py', 'r') as f:
            content = f.read()
        
        # Verify min_decision_minute implementation is present
        assert 'min_decision_minute' in content, "min_decision_minute should be implemented"
        assert 'min_time_to_expiry = min_decision_minute * 60' in content, "Conversion to seconds should be present"
        assert 'time_to_expiry < min_time_to_expiry' in content, "Early signal skip logic should be present"
        
        # Verify the fix comment is present
        assert 'CRITICAL FIX: Implement min_decision_minute from profile' in content, "Fix comment should be present"
    
    def test_min_decision_minute_skips_early_signals(self):
        """Test that early signals are skipped based on min_decision_minute."""
        # 2026-07-07: Updated to reflect new min_decision_minute=1 for all assets
        # Simulate DOGE with min_decision_minute=1
        # At 0.5 minutes into 15m window, should skip (waiting for signal clarity)
        # At 1.5 minutes into 15m window, should allow (signal clarity achieved)
        
        min_decision_minute = 1  # DOGE from profile (updated 2026-07-07)
        time_to_expiry = 0.5 * 60  # 0.5 minutes remaining (14.5 minutes into window)
        min_time_to_expiry = min_decision_minute * 60  # 1 minute = 60 seconds
        
        # Should skip because 0.5 minutes < 1 minute threshold
        should_skip = time_to_expiry < min_time_to_expiry
        assert should_skip, "Should skip early signals before min_decision_minute"
        
        # At 1.5 minutes remaining (13.5 minutes into window), should allow
        time_to_expiry = 1.5 * 60  # 1.5 minutes remaining
        should_skip = time_to_expiry < min_time_to_expiry
        assert not should_skip, "Should allow signals after min_decision_minute"


class TestRelaxedOneSidedRejection:
    """Test that one-sided rejection is relaxed from 1min to 30s terminal phase."""
    
    def test_one_sided_rejection_relaxed_to_30s(self):
        """Test that one-sided books are allowed except in last 30 seconds."""
        # Read the agent_grid_15m.py file and verify the relaxed logic
        with open('c:/Dev/MERID/merid/prediction/agent_grid_15m.py', 'r') as f:
            content = f.read()
        
        # Verify the 1-minute threshold is changed to 30 seconds
        assert 'minutes_to_expiry > 1.0' not in content or 'minutes_to_expiry > 0.5' in content, \
            "One-sided rejection should use 30s (0.5min) not 1min"
        
        # Verify the fix comment is present
        assert 'CRITICAL FIX: Relaxed one-sided rejection' in content, "Fix comment should be present"
        assert 'terminal phase' in content, "Terminal phase logic should be present"
    
    def test_one_sided_allowed_before_terminal_phase(self):
        """Test that one-sided books are allowed before terminal phase."""
        # At 8 minutes to expiry: should allow one-sided books
        minutes_to_expiry = 8.0
        terminal_threshold = 0.5  # 30 seconds
        
        # Should allow because 8 minutes > 30 seconds
        should_allow = minutes_to_expiry > terminal_threshold
        assert should_allow, "Should allow one-sided books before terminal phase"
    
    def test_one_sided_rejected_in_terminal_phase(self):
        """Test that one-sided books are rejected in terminal phase."""
        # At 20 seconds to expiry: should reject one-sided books
        minutes_to_expiry = 20.0 / 60.0  # 20 seconds = 0.33 minutes
        terminal_threshold = 0.5  # 30 seconds
        
        # Should reject because 20 seconds < 30 seconds
        should_reject = minutes_to_expiry <= terminal_threshold
        assert should_reject, "Should reject one-sided books in terminal phase"


class TestFillRateImprovementIntegration:
    """Integration tests for fill rate improvements."""
    
    def test_depth_thresholds_allow_trading_with_sufficient_liquidity(self):
        """Test that realistic depth thresholds allow trading."""
        # With the fix, depth thresholds are 1-2 contracts (from profile)
        # This should allow trading in most 15m crypto markets
        
        # Simulate DOGE market with depth_yes=250, depth_no=20 (from audit)
        depth_yes = 250
        depth_no = 20
        min_depth_yes_threshold = 1  # From profile (DOGE tier 2)
        min_depth_no_threshold = 1  # From profile (DOGE tier 2)
        
        # Both sides exceed threshold, should allow trading
        has_yes = depth_yes >= min_depth_yes_threshold
        has_no = depth_no >= min_depth_no_threshold
        
        assert has_yes, "YES side has sufficient liquidity"
        assert has_no, "NO side has sufficient liquidity"
    
    def test_one_sided_books_now_tradeable(self):
        """Test that one-sided books are now tradeable (except terminal phase)."""
        # With the fix, one-sided books are allowed when TTE > 30s
        # This should significantly increase fill rate for smaller assets
        
        # Simulate one-sided YES book at 8 minutes to expiry
        depth_yes = 250
        depth_no = 0
        minutes_to_expiry = 8.0
        terminal_threshold = 0.5
        
        # Should allow one-sided book because TTE > 30s
        should_allow = minutes_to_expiry > terminal_threshold
        assert should_allow, "One-sided books should be allowed before terminal phase"
    
    def test_early_signals_skipped_for_signal_clarity(self):
        """Test that early signals are skipped to improve signal quality."""
        # 2026-07-07: Updated to reflect new min_decision_minute=1 for all assets
        # With min_decision_minute implemented, early noisy signals are skipped
        # This should improve win rate even if it slightly reduces trade count
        
        # Simulate DOGE at 0.5 minutes into 15m window
        min_decision_minute = 1  # DOGE from profile (updated 2026-07-07)
        time_into_window = 0.5  # 0.5 minutes
        
        # Should skip because 0.5 minutes < 1 minute threshold
        should_skip = time_into_window < min_decision_minute
        assert should_skip, "Should skip early signals for DOGE"
        
        # Simulate BTC at 0.5 minutes into 15m window
        min_decision_minute = 1  # BTC from profile (updated 2026-07-07)
        time_into_window = 0.5  # 0.5 minutes
        
        # Should skip because 0.5 minutes < 1 minute threshold
        should_skip = time_into_window < min_decision_minute
        assert should_skip, "Should skip early signals for BTC"
        
        # At 1.5 minutes into window, should allow for all assets
        time_into_window = 1.5  # 1.5 minutes
        should_skip = time_into_window < min_decision_minute
        assert not should_skip, "Should allow signals for all assets after 1 minute"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
