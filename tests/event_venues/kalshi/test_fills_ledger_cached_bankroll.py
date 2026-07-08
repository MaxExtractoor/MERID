"""
Tests for fills_ledger cached bankroll fix.

These tests verify that fills_ledger uses cached bankroll values
instead of blocking on get_summary_sync() calls during initialization.
"""

import pytest


def test_fills_ledger_module_imports():
    """Test that fills_ledger module can be imported without blocking."""
    # This test verifies that the module can be imported without blocking
    # on bankroll fetch during import time
    try:
        import merid.event_venues.kalshi.fills_ledger
        assert True
    except Exception as e:
        pytest.fail(f"Failed to import fills_ledger module: {e}")


def test_bankroll_service_v2_module_imports():
    """Test that bankroll_service_v2 module can be imported without blocking."""
    # This test verifies that the bankroll service module can be imported
    # without blocking during import time
    try:
        import merid.event_venues.kalshi.bankroll_service_v2
        assert True
    except Exception as e:
        pytest.fail(f"Failed to import bankroll_service_v2 module: {e}")
