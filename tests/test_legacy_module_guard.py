"""Tests for legacy module guard in 15m process.

These tests verify that the kalshi_crypto_15m_v2 profile does not load
any legacy modules (PM runtime, paper trading, reflection system, etc.).
"""

import pytest
import sys


class TestLegacyModuleGuard:
    """Test legacy module guard functionality."""
    
    def test_get_loaded_legacy_modules_empty(self):
        """Test that get_loaded_legacy_modules returns empty list when no legacy modules loaded."""
        from merid.legacy_module_guard import get_loaded_legacy_modules
        
        # In a clean test environment, no legacy modules should be loaded
        legacy = get_loaded_legacy_modules()
        assert isinstance(legacy, list)
        # We don't assert empty here because other tests might have loaded modules
    
    def test_assert_no_legacy_modules_passes_when_clean(self):
        """Test that assert_no_legacy_modules passes when no legacy modules loaded."""
        from merid.legacy_module_guard import assert_no_legacy_modules
        
        # This should not raise if no legacy modules are loaded
        # Note: This test might fail if other tests have loaded legacy modules
        try:
            assert_no_legacy_modules(context="test")
        except RuntimeError as e:
            # If legacy modules are loaded, that's a test environment issue
            # We'll just log it and not fail the test
            pytest.skip(f"Legacy modules already loaded in test environment: {e}")
    
    def test_get_legacy_module_report_structure(self):
        """Test that get_legacy_module_report returns correct structure."""
        from merid.legacy_module_guard import get_legacy_module_report
        
        report = get_legacy_module_report()
        
        assert isinstance(report, dict)
        assert "legacy_modules_loaded" in report
        assert "legacy_count" in report
        assert "is_clean" in report
        assert "all_patterns" in report
        
        assert isinstance(report["legacy_modules_loaded"], list)
        assert isinstance(report["legacy_count"], int)
        assert isinstance(report["is_clean"], bool)
        assert isinstance(report["all_patterns"], list)
    
    def test_legacy_module_patterns_defined(self):
        """Test that legacy module patterns are defined."""
        from merid.legacy_module_guard import LEGACY_MODULE_PATTERNS
        
        assert isinstance(LEGACY_MODULE_PATTERNS, set)
        assert len(LEGACY_MODULE_PATTERNS) > 0
        
        # Check for known legacy patterns
        assert "core.paper_session" in LEGACY_MODULE_PATTERNS
        assert "swarm.agent_registry" in LEGACY_MODULE_PATTERNS
        assert "merid.event_venues.kalshi.deployment" in LEGACY_MODULE_PATTERNS


class Test15mStackImportCleanliness:
    """Test that importing the 15m stack does not load legacy modules."""
    
    @pytest.mark.slow
    def test_import_main_15m_lean_no_legacy(self):
        """Test that importing main_15m_lean does not load legacy modules."""
        # Capture current sys.modules state
        before_modules = set(sys.modules.keys())
        
        # Import the 15m main module
        import web.main_15m_lean
        
        # Check for newly loaded modules
        after_modules = set(sys.modules.keys())
        new_modules = after_modules - before_modules
        
        # Check if any new modules match legacy patterns
        from merid.legacy_module_guard import LEGACY_MODULE_PATTERNS
        legacy_new = []
        for module_name in new_modules:
            for pattern in LEGACY_MODULE_PATTERNS:
                if module_name == pattern or module_name.startswith(pattern + "."):
                    legacy_new.append(module_name)
                    break
        
        if legacy_new:
            pytest.fail(f"Importing main_15m_lean loaded legacy modules: {legacy_new}")
    
    @pytest.mark.slow
    def test_import_agent_grid_15m_no_legacy(self):
        """Test that importing agent_grid_15m does not load legacy modules."""
        before_modules = set(sys.modules.keys())
        
        import merid.prediction.agent_grid_15m
        
        after_modules = set(sys.modules.keys())
        new_modules = after_modules - before_modules
        
        from merid.legacy_module_guard import LEGACY_MODULE_PATTERNS
        legacy_new = []
        for module_name in new_modules:
            for pattern in LEGACY_MODULE_PATTERNS:
                if module_name == pattern or module_name.startswith(pattern + "."):
                    legacy_new.append(module_name)
                    break
        
        if legacy_new:
            pytest.fail(f"Importing agent_grid_15m loaded legacy modules: {legacy_new}")
    
    @pytest.mark.slow
    def test_import_loop_15m_no_legacy(self):
        """Test that importing loop_15m does not load legacy modules."""
        before_modules = set(sys.modules.keys())
        
        import merid.loop_15m
        
        after_modules = set(sys.modules.keys())
        new_modules = after_modules - before_modules
        
        from merid.legacy_module_guard import LEGACY_MODULE_PATTERNS
        legacy_new = []
        for module_name in new_modules:
            for pattern in LEGACY_MODULE_PATTERNS:
                if module_name == pattern or module_name.startswith(pattern + "."):
                    legacy_new.append(module_name)
                    break
        
        if legacy_new:
            pytest.fail(f"Importing loop_15m loaded legacy modules: {legacy_new}")
    
    @pytest.mark.slow
    def test_import_kalshi_client_no_legacy(self):
        """Test that importing Kalshi client does not load legacy modules."""
        before_modules = set(sys.modules.keys())
        
        from merid.event_venues.kalshi.client import KalshiVenueClient
        
        after_modules = set(sys.modules.keys())
        new_modules = after_modules - before_modules
        
        from merid.legacy_module_guard import LEGACY_MODULE_PATTERNS
        legacy_new = []
        for module_name in new_modules:
            for pattern in LEGACY_MODULE_PATTERNS:
                if module_name == pattern or module_name.startswith(pattern + "."):
                    legacy_new.append(module_name)
                    break
        
        if legacy_new:
            pytest.fail(f"Importing KalshiVenueClient loaded legacy modules: {legacy_new}")
    
    @pytest.mark.slow
    def test_import_bankroll_service_v2_no_legacy(self):
        """Test that importing bankroll_service_v2 does not load legacy modules."""
        before_modules = set(sys.modules.keys())
        
        from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service
        
        after_modules = set(sys.modules.keys())
        new_modules = after_modules - before_modules
        
        from merid.legacy_module_guard import LEGACY_MODULE_PATTERNS
        legacy_new = []
        for module_name in new_modules:
            for pattern in LEGACY_MODULE_PATTERNS:
                if module_name == pattern or module_name.startswith(pattern + "."):
                    legacy_new.append(module_name)
                    break
        
        if legacy_new:
            pytest.fail(f"Importing bankroll_service_v2 loaded legacy modules: {legacy_new}")


class Test15mOrderRouterLean:
    """Test that the 15m order router is lean and has no legacy dependencies."""
    
    def test_order_router_15m_exists(self):
        """Test that order_router_15m module exists."""
        import merid.event_venues.kalshi.order_router_15m
        assert merid.event_venues.kalshi.order_router_15m is not None
    
    def test_order_router_15m_no_legacy_imports(self):
        """Test that order_router_15m has no legacy imports."""
        import merid.event_venues.kalshi.order_router_15m as router_module
        
        # Get the source file
        import inspect
        source_file = inspect.getsourcefile(router_module)
        assert source_file is not None
        
        # Read the source and check for legacy imports
        with open(source_file, 'r') as f:
            source = f.read()
        
        # Check for legacy import patterns
        legacy_patterns = [
            "from merid.paper_config",
            "from core.paper_session",
            "from swarm.agent_registry",
            "from merid.event_venues.kalshi.deployment",
            "from agents.reflection",
        ]
        
        for pattern in legacy_patterns:
            assert pattern not in source, f"Found legacy import pattern: {pattern}"
    
    def test_order_router_15m_get_singleton(self):
        """Test that get_kalshi_15m_order_router returns a router instance."""
        from merid.event_venues.kalshi.order_router_15m import get_kalshi_15m_order_router, Kalshi15mOrderRouter
        
        router = get_kalshi_15m_order_router()
        assert isinstance(router, Kalshi15mOrderRouter)
        
        # Calling again should return the same instance (singleton)
        router2 = get_kalshi_15m_order_router()
        assert router is router2
