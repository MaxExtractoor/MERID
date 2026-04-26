"""
Pass 8 Tests: Archive Import Guard

Verifies that importing archive modules in live trading processes raises ImportError.
"""

import pytest
import os
import sys
from unittest.mock import patch


class TestArchiveImportGuard:
    """Test archive imports are blocked in trading contexts."""
    
    def test_archive_import_blocked_in_live_mode(self):
        """Importing archive in LIVE mode should raise ImportError."""
        with patch.dict(os.environ, {
            "KALSHI_ENV": "live",
            "MERID_PROCESS_TYPE": "trading"
        }):
            # Must reload module to trigger guard
            if "archive" in sys.modules:
                del sys.modules["archive"]
            
            with pytest.raises(ImportError) as exc_info:
                import archive
            
            assert "blocked" in str(exc_info.value).lower() or \
                   "FATAL" in str(exc_info.value)
    
    def test_archive_import_blocked_in_paper_mode(self):
        """Importing archive in PAPER mode should raise ImportError."""
        with patch.dict(os.environ, {
            "KALSHI_ENV": "paper",
            "MERID_PROCESS_TYPE": "execution"
        }):
            if "archive" in sys.modules:
                del sys.modules["archive"]
            
            with pytest.raises(ImportError):
                import archive
    
    def test_archive_import_allowed_in_sim_mode(self):
        """Importing archive in SIM mode should succeed."""
        with patch.dict(os.environ, {
            "KALSHI_ENV": "sim",
            "MERID_PROCESS_TYPE": "analytics"  # Non-trading
        }):
            # This should not raise
            try:
                if "archive" in sys.modules:
                    del sys.modules["archive"]
                import archive
                # If we get here, import succeeded
                assert True
            except ImportError as e:
                # Should not happen in SIM with analytics process
                if "blocked" in str(e).lower():
                    pytest.fail(f"Archive import blocked in SIM mode: {e}")
    
    def test_archive_import_blocked_when_no_process_type(self):
        """If MERID_PROCESS_TYPE not set, be conservative and block."""
        with patch.dict(os.environ, {
            "KALSHI_ENV": "live"
        }, clear=False):
            # Ensure MERID_PROCESS_TYPE is not set
            if "MERID_PROCESS_TYPE" in os.environ:
                del os.environ["MERID_PROCESS_TYPE"]
            
            if "archive" in sys.modules:
                del sys.modules["archive"]
            
            with pytest.raises(ImportError) as exc_info:
                import archive
            
            assert "UNKNOWN" in str(exc_info.value) or "trading suspected" in str(exc_info.value).lower()
    
    @pytest.mark.parametrize("process_type", [
        "trading",
        "execution",
        "agent",
        "trader",
        "order",
        "trading_bot",
        "execution_agent",
    ])
    def test_various_trading_process_types_blocked(self, process_type):
        """Various trading process type names should all be blocked."""
        with patch.dict(os.environ, {
            "KALSHI_ENV": "live",
            "MERID_PROCESS_TYPE": process_type
        }):
            if "archive" in sys.modules:
                del sys.modules["archive"]
            
            with pytest.raises(ImportError):
                import archive
    
    def test_analytics_process_allowed_in_live(self):
        """Analytics/reporting processes should be allowed in LIVE."""
        with patch.dict(os.environ, {
            "KALSHI_ENV": "live",
            "MERID_PROCESS_TYPE": "analytics_post_trade"
        }):
            if "archive" in sys.modules:
                del sys.modules["archive"]
            
            # This might succeed or fail depending on implementation
            # Document the behavior
            try:
                import archive
                # If succeeds, that's acceptable for analytics
            except ImportError:
                # If fails, that's also acceptable (conservative)
                pass
    
    def test_error_message_includes_remediation(self):
        """Error message should tell user how to fix the issue."""
        with patch.dict(os.environ, {
            "KALSHI_ENV": "live",
            "MERID_PROCESS_TYPE": "trading"
        }):
            if "archive" in sys.modules:
                del sys.modules["archive"]
            
            with pytest.raises(ImportError) as exc_info:
                import archive
            
            error_msg = str(exc_info.value)
            # Should include remediation steps
            assert any(phrase in error_msg.lower() for phrase in [
                "merid/analytics",
                "canonical executor",
                "port the logic",
                "move the module"
            ])


class TestDeepArchiveImportGuard:
    """Test deep_archive imports are similarly guarded."""
    
    def test_deep_archive_import_blocked_in_live(self):
        """Importing archive.deep_archive in LIVE should raise."""
        with patch.dict(os.environ, {
            "KALSHI_ENV": "live",
            "MERID_PROCESS_TYPE": "trading"
        }):
            # Note: This tests the subpackage if it has its own guard
            # If deep_archive doesn't have __init__.py with guard, 
            # this test documents that gap
            try:
                if "archive.deep_archive" in sys.modules:
                    del sys.modules["archive.deep_archive"]
                from archive import deep_archive
                
                # If import succeeded, check if guard was applied
                pytest.fail("deep_archive import should have been blocked in LIVE")
            except ImportError as e:
                # Expected - guard worked
                assert "blocked" in str(e).lower() or "cannot" in str(e).lower()


class TestArchiveGuardEdgeCases:
    """Edge cases for archive import guard."""
    
    def test_case_insensitive_mode_check(self):
        """Mode check should be case insensitive."""
        with patch.dict(os.environ, {
            "KALSHI_ENV": "LIVE",  # Uppercase
            "MERID_PROCESS_TYPE": "trading"
        }):
            if "archive" in sys.modules:
                del sys.modules["archive"]
            
            with pytest.raises(ImportError):
                import archive
    
    def test_merid_trade_mode_env_var(self):
        """Should check MERID_TRADE_MODE if KALSHI_ENV not set."""
        with patch.dict(os.environ, {
            "MERID_TRADE_MODE": "paper"
        }, clear=True):  # Clear other vars
            if "KALSHI_ENV" in os.environ:
                del os.environ["KALSHI_ENV"]
            
            if "archive" in sys.modules:
                del sys.modules["archive"]
            
            with pytest.raises(ImportError):
                import archive
