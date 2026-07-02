"""Test that CryptoHedgeEngine auto-exit loop is started in main_15m_lean.py startup.

This test validates the fix for the bug where the hedge auto-exit loop was never started,
meaning hedge positions would never automatically exit on TP/SL.
"""

import pytest


class TestHedgeAutoExitStartup:
    """Test that hedge auto-exit loop is properly started during server startup."""

    def test_hedge_auto_exit_loop_code_exists_in_startup(self):
        """Test that the hedge auto-exit loop startup code exists in main_15m_lean.py."""
        # Read the main_15m_lean.py file with UTF-8 encoding
        with open("web/main_15m_lean.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # Verify the hedge auto-exit loop startup code exists
        assert "CryptoHedgeEngine auto-exit loop" in source, \
            "CryptoHedgeEngine auto-exit loop startup code not found"
        assert "run_auto_exit_loop" in source, \
            "run_auto_exit_loop call not found"
        assert "hedge_price_provider" in source, \
            "hedge_price_provider function not found"
        assert "hedge_exit_task" in source, \
            "hedge_exit_task variable not found"

    def test_hedge_auto_exit_loop_imports_exist(self):
        """Test that the necessary imports for hedge auto-exit exist."""
        # Read the main_15m_lean.py file with UTF-8 encoding
        with open("web/main_15m_lean.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # Verify the imports exist (they are done inline in the startup function)
        assert "from merid.hedging.engine import get_hedge_engine" in source, \
            "get_hedge_engine import not found"
        assert "from merid.hedging.config import get_hedge_config" in source, \
            "get_hedge_config import not found"

    def test_hedge_auto_exit_loop_enabled_check(self):
        """Test that the code checks if hedge and auto-exit are enabled."""
        # Read the main_15m_lean.py file with UTF-8 encoding
        with open("web/main_15m_lean.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # Verify the enabled check exists
        assert "hedge_config.enabled" in source, \
            "hedge_config.enabled check not found"
        assert "hedge_config.auto_exit.enabled" in source, \
            "hedge_config.auto_exit.enabled check not found"
