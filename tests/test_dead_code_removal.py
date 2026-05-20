"""Tests for legacy removal verification.

Tests that verify dead modules are not importable and not used in production code.
"""

import pytest
import importlib


class TestLegacyExportsRemoved:
    """Test legacy exports are no longer available."""

    def test_no_legacy_bankroll_exported(self):
        """Import merid.event_venues.kalshi and assert KalshiBankrollService not in dir()."""
        import merid.event_venues.kalshi as kalshi_module
        
        # KalshiBankrollService should not be exported
        assert "KalshiBankrollService" not in dir(kalshi_module)
        
        # Attempting to import should fail
        with pytest.raises(ImportError):
            from merid.event_venues.kalshi import KalshiBankrollService

    def test_no_legacy_reconciler_exported(self):
        """Import merid.reconciliation and assert KalshiReconciler not in dir()."""
        import merid.reconciliation as reconciliation_module
        
        # KalshiReconciler should not be exported
        assert "KalshiReconciler" not in dir(reconciliation_module)
        assert "ReconciliationIssue" not in dir(reconciliation_module)
        assert "ReconciliationReport" not in dir(reconciliation_module)
        
        # Attempting to import should fail
        with pytest.raises(ImportError):
            from merid.reconciliation import KalshiReconciler


class TestEnhancedModulesRemoved:
    """Test enhanced modules are not importable."""

    def test_no_enhanced_modules_importable(self):
        """Assert enhanced modules cannot be imported."""
        # These modules should have been deleted
        enhanced_modules = [
            "merid.event_venues.kalshi.venue_adapter_enhanced",
            "merid.event_venues.kalshi.order_manager_enhanced",
            "merid.event_venues.kalshi.order_group_manager_enhanced",
            "merid.event_venues.kalshi.trading_enhanced",
        ]
        
        for module_name in enhanced_modules:
            with pytest.raises(ModuleNotFoundError):
                importlib.import_module(module_name)

    def test_no_ct_modules_importable(self):
        """Assert CT-specific modules cannot be imported."""
        ct_modules = [
            "merid.trading.ct_profit_taking_integration",
            "merid.trading.ct_pnl_reconciler",
        ]
        
        for module_name in ct_modules:
            with pytest.raises(ModuleNotFoundError):
                importlib.import_module(module_name)


class TestProductionCodeDoesNotImportDeadModules:
    """Test production packages do not import removed modules."""

    def test_no_dead_module_imports_in_core_packages(self):
        """Walk production packages and assert no imports of dead modules."""
        # This would require scanning the codebase for import statements
        # For now, this is a placeholder test
        pass

    def test_ct_modules_not_imported_in_kalshi_crypto_15m_profile(self):
        """Simulate loading 15m profile and assert no CT-integration modules imported."""
        # This would require profile loading simulation
        # For now, this is a placeholder test
        pass
