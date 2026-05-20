"""Tests for execution-path import guards for kalshi_crypto_15m_v2 profile.

Verifies that forbidden modules are not imported when running in kalshi_crypto_15m_v2 profile.
"""

import os
import sys
import pytest
from merid.startup_validations import check_kalshi_15m_isolation, StartupValidationError


@pytest.mark.kalshi_15m
class TestImportIsolation:
    """Test import isolation check for kalshi_crypto_15m_v2 profile."""

    def test_skip_for_other_profiles(self):
        """Test check_kalshi_15m_isolation() skips for non-kalshi_crypto_15m_v2 profiles."""
        # Set profile to full
        os.environ["MERID_PROFILE"] = "full"
        
        # Should not raise
        check_kalshi_15m_isolation()
        
        # Reset
        os.environ["MERID_PROFILE"] = ""

    def test_skip_for_empty_profile(self):
        """Test check_kalshi_15m_isolation() skips when profile is empty."""
        # Set profile to empty
        os.environ["MERID_PROFILE"] = ""
        
        # Should not raise
        check_kalshi_15m_isolation()

    def test_no_forbidden_modules_passes(self):
        """Test check passes when no forbidden modules are imported."""
        # Set profile to kalshi_crypto_15m_v2
        os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
        
        # Ensure no forbidden modules are in sys.modules
        forbidden_prefixes = [
            "agents.swarm",
            "agents.sentiment",
            "agents.debate",
            "agents.governance",
            "agents.reflection",
            "agents.reality",
            "agents.intelligence",
            "merid.sentiment",
            "merid.governance",
            "merid.swarm",
            "merid.reflection",
            "merid.reality",
            "merid.intelligence",
            "merid.sniping",
            "merid.arbitrage",
            "merid.offline",
            "merid.social",
            "db.neo4j",
            "core.orchestrator",
            "core.kalshi_orchestrator",
        ]
        
        # Remove any forbidden modules from sys.modules for this test
        removed_modules = {}
        for module_name in list(sys.modules.keys()):
            for prefix in forbidden_prefixes:
                if module_name and module_name.startswith(prefix):
                    removed_modules[module_name] = sys.modules.pop(module_name)
                    break
        
        try:
            # Should not raise
            check_kalshi_15m_isolation()
        finally:
            # Restore removed modules
            for module_name, module in removed_modules.items():
                sys.modules[module_name] = module
            os.environ["MERID_PROFILE"] = ""

    def test_forbidden_module_raises_error(self):
        """Test check raises error when forbidden module is imported."""
        # Set profile to kalshi_crypto_15m_v2
        os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
        
        # Mock a forbidden module in sys.modules
        forbidden_module = "agents.swarm.agent"
        sys.modules[forbidden_module] = type('module', (), {})()
        
        try:
            # Should raise
            with pytest.raises(StartupValidationError) as exc_info:
                check_kalshi_15m_isolation()
            
            assert "IMPORT-ISOLATION" in str(exc_info.value)
            assert "forbidden" in str(exc_info.value).lower()
            assert "swarm" in str(exc_info.value).lower()
        finally:
            # Clean up
            if forbidden_module in sys.modules:
                del sys.modules[forbidden_module]
            os.environ["MERID_PROFILE"] = ""

    def test_multiple_forbidden_modules_all_reported(self):
        """Test all forbidden modules are reported in error message."""
        # Set profile to kalshi_crypto_15m_v2
        os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
        
        # Mock multiple forbidden modules
        forbidden_modules = [
            "agents.swarm.agent",
            "agents.sentiment.pipeline",
            "merid.governance.voting",
        ]
        
        for module_name in forbidden_modules:
            sys.modules[module_name] = type('module', (), {})()
        
        try:
            # Should raise
            with pytest.raises(StartupValidationError) as exc_info:
                check_kalshi_15m_isolation()
            
            error_msg = str(exc_info.value)
            # Check that all forbidden modules are mentioned
            for module_name in forbidden_modules:
                assert module_name in error_msg
        finally:
            # Clean up
            for module_name in forbidden_modules:
                if module_name in sys.modules:
                    del sys.modules[module_name]
            os.environ["MERID_PROFILE"] = ""

    def test_allowed_modules_do_not_trigger_error(self):
        """Test allowed modules do not trigger import isolation error."""
        # Set profile to kalshi_crypto_15m_v2
        os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
        
        # Check if forbidden modules are already imported (test isolation issue)
        forbidden_prefixes = ["merid.sentiment", "merid.swarm", "agents.reflection"]
        has_forbidden = any(
            any(module_name.startswith(prefix) for prefix in forbidden_prefixes)
            for module_name in sys.modules.keys()
        )
        
        if has_forbidden:
            # Skip test if forbidden modules already imported by other tests
            pytest.skip("Forbidden modules already imported by previous tests (test isolation)")
        
        # Mock allowed modules (should not trigger error)
        allowed_modules = [
            "merid.event_venues.kalshi",
            "merid.prediction.trading_agent",
            "merid.risk.profiles.kalshi_crypto_15m_risk_envelope",
            "config.kalshi_15m_crypto_config",
            "web.main",
        ]
        
        for module_name in allowed_modules:
            sys.modules[module_name] = type('module', (), {})()
        
        try:
            # Should not raise
            check_kalshi_15m_isolation()
        finally:
            # Clean up
            for module_name in allowed_modules:
                if module_name in sys.modules:
                    del sys.modules[module_name]
            os.environ["MERID_PROFILE"] = ""

    def test_submodule_of_forbidden_prefix_triggers_error(self):
        """Test that submodules of forbidden prefixes trigger error."""
        # Set profile to kalshi_crypto_15m_v2
        os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
        
        # Mock a submodule of a forbidden prefix
        forbidden_submodule = "merid.sentiment.pipeline.analyzer"
        sys.modules[forbidden_submodule] = type('module', (), {})()
        
        try:
            # Should raise
            with pytest.raises(StartupValidationError) as exc_info:
                check_kalshi_15m_isolation()
            
            assert "sentiment" in str(exc_info.value).lower()
        finally:
            # Clean up
            if forbidden_submodule in sys.modules:
                del sys.modules[forbidden_submodule]
            os.environ["MERID_PROFILE"] = ""
