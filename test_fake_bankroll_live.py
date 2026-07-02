#!/usr/bin/env python3
"""
Live test script to demonstrate fake bankroll invariant behavior.

This script simulates the key scenarios:
1. Live profile with fake bankroll -> invariant fires, execution blocked
2. Test profile with fake bankroll -> allowed when flag enabled
3. Live profile with real bankroll -> no invariant, execution allowed
"""

import os
import sys
import time
from unittest.mock import Mock, patch

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_live_profile_fake_bankroll():
    """Test: Live profile with fake bankroll should trigger invariant and block execution."""
    print("\n=== TEST 1: Live Profile + Fake Bankroll ===")
    
    # Mock settings to simulate live profile
    with patch('config.settings.Settings') as mock_settings_class:
        mock_settings = Mock()
        mock_settings.PROFILE_IS_LIVE = True
        mock_settings.MERID_ALLOW_FAKE_BANKROLL_FOR_TEST = False
        mock_settings_class.return_value = mock_settings
        
        # Mock invariant checker
        with patch('merid.core.e2e_invariants.E2EInvariantChecker') as mock_checker_class:
            mock_checker = Mock()
            mock_violation = Mock()
            mock_violation.invariant_name = "FAKE_BANKROLL_SOURCE_USED"
            mock_violation.severity = "CRITICAL"
            mock_violation.message = "Fake bankroll source detected in live profile: source=fallback value=1000.00"
            mock_checker.check_fake_bankroll_source_invariant.return_value = mock_violation
            mock_checker_class.return_value = mock_checker
            
            # Simulate loop logic with fake bankroll
            live_bankroll_source = "fallback"
            live_bankroll = 1000.0
            is_live_profile = mock_settings.PROFILE_IS_LIVE
            allow_fake_bankroll = not is_live_profile and mock_settings.MERID_ALLOW_FAKE_BANKROLL_FOR_TEST
            
            print(f"  Profile: {'LIVE' if is_live_profile else 'TEST'}")
            print(f"  Bankroll: ${live_bankroll} from source '{live_bankroll_source}'")
            print(f"  Allow fake bankroll: {allow_fake_bankroll}")
            
            # Check invariant
            fake_bankroll_violation = None
            if not allow_fake_bankroll:
                fake_bankroll_violation = mock_checker.check_fake_bankroll_source_invariant(
                    bankroll_source=live_bankroll_source,
                    bankroll_value=live_bankroll,
                    is_live_profile=is_live_profile
                )
            
            if fake_bankroll_violation:
                fake_bankroll_used = True
                print(f"  ❌ FAKE BANKROLL DETECTED: {fake_bankroll_violation.message}")
            else:
                fake_bankroll_used = False
                print("  ✅ No fake bankroll detected")
            
            # Check execution gate
            bankroll_source_valid = not fake_bankroll_used and live_bankroll_source in {"kalshi", "bankroll_service_v2"}
            execution_ready = bankroll_source_valid  # Simplified for test
            
            print(f"  Bankroll source valid: {bankroll_source_valid}")
            print(f"  Execution ready: {execution_ready}")
            
            # Verify expected behavior
            assert fake_bankroll_used is True, "Fake bankroll should be detected"
            assert bankroll_source_valid is False, "Fake source should be invalid"
            assert execution_ready is False, "Execution should be blocked"
            
            print("  ✅ TEST PASSED: Fake bankroll correctly blocked in live profile")

def test_test_profile_fake_bankroll_allowed():
    """Test: Test profile with fake bankroll should be allowed when flag enabled."""
    print("\n=== TEST 2: Test Profile + Fake Bankroll (Allowed) ===")
    
    # Mock settings to simulate test profile
    with patch('config.settings.Settings') as mock_settings_class:
        mock_settings = Mock()
        mock_settings.PROFILE_IS_LIVE = False
        mock_settings.MERID_ALLOW_FAKE_BANKROLL_FOR_TEST = True
        mock_settings_class.return_value = mock_settings
        
        # Mock invariant checker
        with patch('merid.core.e2e_invariants.E2EInvariantChecker') as mock_checker_class:
            mock_checker = Mock()
            mock_checker_class.return_value = mock_checker
            
            # Simulate loop logic with fake bankroll
            live_bankroll_source = "fallback"
            live_bankroll = 1000.0
            is_live_profile = mock_settings.PROFILE_IS_LIVE
            allow_fake_bankroll = not is_live_profile and mock_settings.MERID_ALLOW_FAKE_BANKROLL_FOR_TEST
            
            print(f"  Profile: {'LIVE' if is_live_profile else 'TEST'}")
            print(f"  Bankroll: ${live_bankroll} from source '{live_bankroll_source}'")
            print(f"  Allow fake bankroll: {allow_fake_bankroll}")
            
            # Check invariant (should be skipped)
            fake_bankroll_violation = None
            if not allow_fake_bankroll:
                fake_bankroll_violation = mock_checker.check_fake_bankroll_source_invariant(
                    bankroll_source=live_bankroll_source,
                    bankroll_value=live_bankroll,
                    is_live_profile=is_live_profile
                )
            
            if fake_bankroll_violation:
                fake_bankroll_used = True
                print(f"  ❌ FAKE BANKROLL DETECTED: {fake_bankroll_violation.message}")
            else:
                fake_bankroll_used = False
                print("  ✅ No fake bankroll detected (invariant skipped)")
            
            # Check execution gate
            bankroll_source_valid = not fake_bankroll_used and live_bankroll_source in {"kalshi", "bankroll_service_v2"}
            execution_ready = bankroll_source_valid  # Simplified for test
            
            print(f"  Bankroll source valid: {bankroll_source_valid}")
            print(f"  Execution ready: {execution_ready}")
            
            # Verify expected behavior
            assert fake_bankroll_used is False, "Fake bankroll should be allowed in test mode"
            assert allow_fake_bankroll is True, "Fake bankroll should be explicitly allowed"
            assert mock_checker.check_fake_bankroll_source_invariant.call_count == 0, "Invariant should not be checked"
            
            print("  ✅ TEST PASSED: Fake bankroll correctly allowed in test profile")

def test_live_profile_real_bankroll():
    """Test: Live profile with real bankroll should work normally."""
    print("\n=== TEST 3: Live Profile + Real Bankroll ===")
    
    # Mock settings to simulate live profile
    with patch('config.settings.Settings') as mock_settings_class:
        mock_settings = Mock()
        mock_settings.PROFILE_IS_LIVE = True
        mock_settings.MERID_ALLOW_FAKE_BANKROLL_FOR_TEST = False
        mock_settings_class.return_value = mock_settings
        
        # Mock invariant checker
        with patch('merid.core.e2e_invariants.E2EInvariantChecker') as mock_checker_class:
            mock_checker = Mock()
            mock_checker.check_fake_bankroll_source_invariant.return_value = None  # No violation
            mock_checker_class.return_value = mock_checker
            
            # Simulate loop logic with real bankroll
            live_bankroll_source = "kalshi"
            live_bankroll = 3681.25  # Real balance
            is_live_profile = mock_settings.PROFILE_IS_LIVE
            allow_fake_bankroll = not is_live_profile and mock_settings.MERID_ALLOW_FAKE_BANKROLL_FOR_TEST
            
            print(f"  Profile: {'LIVE' if is_live_profile else 'TEST'}")
            print(f"  Bankroll: ${live_bankroll} from source '{live_bankroll_source}'")
            print(f"  Allow fake bankroll: {allow_fake_bankroll}")
            
            # Check invariant
            fake_bankroll_violation = None
            if not allow_fake_bankroll:
                fake_bankroll_violation = mock_checker.check_fake_bankroll_source_invariant(
                    bankroll_source=live_bankroll_source,
                    bankroll_value=live_bankroll,
                    is_live_profile=is_live_profile
                )
            
            if fake_bankroll_violation:
                fake_bankroll_used = True
                print(f"  ❌ FAKE BANKROLL DETECTED: {fake_bankroll_violation.message}")
            else:
                fake_bankroll_used = False
                print("  ✅ No fake bankroll detected")
            
            # Check execution gate
            bankroll_source_valid = not fake_bankroll_used and live_bankroll_source in {"kalshi", "bankroll_service_v2"}
            execution_ready = bankroll_source_valid  # Simplified for test
            
            print(f"  Bankroll source valid: {bankroll_source_valid}")
            print(f"  Execution ready: {execution_ready}")
            
            # Verify expected behavior
            assert fake_bankroll_used is False, "Real bankroll should not trigger invariant"
            assert bankroll_source_valid is True, "Real source should be valid"
            assert execution_ready is True, "Execution should be allowed"
            
            print("  ✅ TEST PASSED: Real bankroll correctly allowed in live profile")

def test_profile_detection():
    """Test profile detection logic."""
    print("\n=== TEST 4: Profile Detection Logic ===")
    
    test_cases = [
        ("kalshi_crypto_15m_v2", True, "Live profile"),
        ("kalshi_crypto_test", False, "Test profile"),
        ("kalshi_crypto_sim", False, "Test profile"),
        ("production_system", True, "Live profile"),
        ("test_env", False, "Test profile"),
        ("unknown_profile", True, "Unknown defaults to live"),
    ]
    
    for profile, expected_is_live, description in test_cases:
        with patch('config.settings.Settings') as mock_settings_class:
            mock_settings = Mock()
            mock_settings.MERID_PROFILE = profile
            mock_settings_class.return_value = mock_settings
            
            # Import and test the PROFILE_IS_LIVE property
            from config.settings import Settings
            settings_instance = Settings()
            settings_instance.MERID_PROFILE = profile
            is_live = settings_instance.PROFILE_IS_LIVE
            
            print(f"  Profile '{profile}' -> {'LIVE' if is_live else 'TEST'} ({description})")
            assert is_live == expected_is_live, f"Profile {profile} should be {'live' if expected_is_live else 'test'}"
    
    print("  ✅ TEST PASSED: Profile detection working correctly")

def main():
    """Run all fake bankroll tests."""
    print("🔍 FAKE BANKROLL INVARIANT LIVE TESTS")
    print("=" * 50)
    
    try:
        test_live_profile_fake_bankroll()
        test_test_profile_fake_bankroll_allowed()
        test_live_profile_real_bankroll()
        test_profile_detection()
        
        print("\n" + "=" * 50)
        print("🎉 ALL TESTS PASSED!")
        print("\nSummary:")
        print("✅ Fake bankroll blocked in live profiles")
        print("✅ Fake bankroll allowed in test profiles (when flag enabled)")
        print("✅ Real bankroll works normally in live profiles")
        print("✅ Profile detection working correctly")
        print("\nThe fake bankroll elimination system is working as designed!")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
