"""Test profile-aware singleton patterns for FillsPoller and KalshiFillsLedger.

This test suite ensures that the profile-aware singleton pattern correctly
separates instances between different profiles to prevent legacy/production
stack contamination.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock
import threading
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestProfileAwareFillsPoller(unittest.TestCase):
    """Test profile-aware FillsPoller singleton pattern."""

    def setUp(self):
        """Reset singleton state before each test."""
        from merid.event_venues.kalshi import fills_poller
        fills_poller._pollers = {}
        fills_poller._poller_lock = threading.Lock()

    def test_different_profiles_get_different_instances(self):
        """Test that different profiles get separate FillsPoller instances."""
        from merid.event_venues.kalshi.fills_poller import get_fills_poller
        
        # Get instances for different profiles
        poller_prod = get_fills_poller("kalshi_crypto_15m_v2")
        poller_legacy = get_fills_poller("legacy")
        poller_default = get_fills_poller("default")
        
        # Verify they are different instances
        self.assertIsNot(poller_prod, poller_legacy)
        self.assertIsNot(poller_prod, poller_default)
        self.assertIsNot(poller_legacy, poller_default)
        
    def test_same_profile_returns_same_instance(self):
        """Test that same profile returns same FillsPoller instance (singleton)."""
        from merid.event_venues.kalshi.fills_poller import get_fills_poller
        
        # Get instance twice for same profile
        poller1 = get_fills_poller("kalshi_crypto_15m_v2")
        poller2 = get_fills_poller("kalshi_crypto_15m_v2")
        
        # Verify they are the same instance
        self.assertIs(poller1, poller2)
        
    def test_profile_uses_env_var_when_none(self):
        """Test that profile parameter uses MERID_PROFILE env var when None."""
        from merid.event_venues.kalshi.fills_poller import get_fills_poller
        
        # Set environment variable
        with patch.dict(os.environ, {'MERID_PROFILE': 'test_profile'}):
            poller1 = get_fills_poller(None)
            poller2 = get_fills_poller('test_profile')
            
            # Should return same instance
            self.assertIs(poller1, poller2)
            
    def test_thread_safety_of_singleton(self):
        """Test that singleton pattern is thread-safe."""
        from merid.event_venues.kalshi.fills_poller import get_fills_poller
        
        instances = []
        def get_instance():
            instances.append(get_fills_poller("test_thread"))
        
        # Create multiple threads
        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # All should be the same instance
        first = instances[0]
        for inst in instances[1:]:
            self.assertIs(inst, first)
            
    def test_isolation_between_profiles(self):
        """Test that state changes in one profile don't affect another."""
        from merid.event_venues.kalshi.fills_poller import get_fills_poller
        
        # Get instances for different profiles
        poller_prod = get_fills_poller("production")
        poller_test = get_fills_poller("test")
        
        # Modify state in production instance
        poller_prod._running = True
        
        # Verify test instance is not affected
        self.assertFalse(getattr(poller_test, '_running', False))


class TestProfileAwareKalshiFillsLedger(unittest.TestCase):
    """Test profile-aware KalshiFillsLedger singleton pattern."""

    def setUp(self):
        """Reset singleton state before each test."""
        from merid.event_venues.kalshi import fills_ledger
        fills_ledger._ledgers = {}
        fills_ledger._ledger_lock = threading.Lock()

    def test_different_profiles_get_different_instances(self):
        """Test that different profiles get separate KalshiFillsLedger instances."""
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        
        # Get instances for different profiles
        ledger_prod = get_fills_ledger("kalshi_crypto_15m_v2")
        ledger_legacy = get_fills_ledger("legacy")
        ledger_default = get_fills_ledger("default")
        
        # Verify they are different instances
        self.assertIsNot(ledger_prod, ledger_legacy)
        self.assertIsNot(ledger_prod, ledger_default)
        self.assertIsNot(ledger_legacy, ledger_default)
        
    def test_same_profile_returns_same_instance(self):
        """Test that same profile returns same KalshiFillsLedger instance (singleton)."""
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        
        # Get instance twice for same profile
        ledger1 = get_fills_ledger("kalshi_crypto_15m_v2")
        ledger2 = get_fills_ledger("kalshi_crypto_15m_v2")
        
        # Verify they are the same instance
        self.assertIs(ledger1, ledger2)
        
    def test_profile_uses_env_var_when_none(self):
        """Test that profile parameter uses MERID_PROFILE env var when None."""
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        
        # Set environment variable
        with patch.dict(os.environ, {'MERID_PROFILE': 'test_profile'}):
            ledger1 = get_fills_ledger(None)
            ledger2 = get_fills_ledger('test_profile')
            
            # Should return same instance
            self.assertIs(ledger1, ledger2)
            
    def test_thread_safety_of_singleton(self):
        """Test that singleton pattern is thread-safe."""
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        
        instances = []
        def get_instance():
            instances.append(get_fills_ledger("test_thread"))
        
        # Create multiple threads
        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # All should be the same instance
        first = instances[0]
        for inst in instances[1:]:
            self.assertIs(inst, first)
            
    def test_isolation_between_profiles(self):
        """Test that state changes in one profile don't affect another."""
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        
        # Get instances for different profiles
        ledger_prod = get_fills_ledger("production")
        ledger_test = get_fills_ledger("test")
        
        # Verify they are different instances
        self.assertIsNot(ledger_prod, ledger_test)


class TestLegacyProductionIsolation(unittest.TestCase):
    """Test that legacy and production stacks are properly isolated."""

    def setUp(self):
        """Reset singleton state before each test."""
        from merid.event_venues.kalshi import fills_poller, fills_ledger
        fills_poller._pollers = {}
        fills_ledger._ledgers = {}
        
    def test_legacy_and_production_use_different_fills_pollers(self):
        """Test that legacy and production profiles get different FillsPollers."""
        from merid.event_venues.kalshi.fills_poller import get_fills_poller
        
        poller_legacy = get_fills_poller("legacy")
        poller_production = get_fills_poller("kalshi_crypto_15m_v2")
        
        self.assertIsNot(poller_legacy, poller_production)
        
    def test_legacy_and_production_use_different_fills_ledgers(self):
        """Test that legacy and production profiles get different KalshiFillsLedgers."""
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        
        ledger_legacy = get_fills_ledger("legacy")
        ledger_production = get_fills_ledger("kalshi_crypto_15m_v2")
        
        self.assertIsNot(ledger_legacy, ledger_production)
        
    def test_no_cross_profile_state_leakage(self):
        """Test that state doesn't leak between legacy and production profiles."""
        from merid.event_venues.kalshi.fills_poller import get_fills_poller
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        
        # Get instances for both profiles
        poller_legacy = get_fills_poller("legacy")
        poller_prod = get_fills_poller("kalshi_crypto_15m_v2")
        ledger_legacy = get_fills_ledger("legacy")
        ledger_prod = get_fills_ledger("kalshi_crypto_15m_v2")
        
        # Verify all are different instances
        self.assertIsNot(poller_legacy, poller_prod)
        self.assertIsNot(ledger_legacy, ledger_prod)
        self.assertIsNot(poller_legacy, ledger_legacy)  # Different types
        self.assertIsNot(poller_prod, ledger_prod)  # Different types


if __name__ == '__main__':
    unittest.main()
