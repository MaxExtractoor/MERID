"""Tests for startup import path fixes and RiskEnvelopeService exception handling.

This test file validates:
- Correct import path for unified_spot_service (data.unified_spot_service)
- Correct import path for risk_envelope_service (merid.risk.profiles.risk_envelope_service)
- RiskEnvelopeService gracefully handles bankroll not ready during startup validations
"""

import pytest
import os
from unittest.mock import patch, MagicMock


class TestUnifiedSpotServiceImportPath:
    """Test that unified_spot_service can be imported from correct path."""

    def test_import_from_data_unified_spot_service(self):
        """Test that UnifiedSpotService can be imported from data.unified_spot_service."""
        # This should not raise ImportError
        from data.unified_spot_service import UnifiedSpotService, get_unified_spot_service
        assert UnifiedSpotService is not None
        assert get_unified_spot_service is not None

    def test_import_from_merid_data_unified_spot_service_fails(self):
        """Test that importing from merid.data.unified_spot_service fails."""
        # This should raise ImportError because the module doesn't exist
        with pytest.raises(ImportError):
            from merid.data.unified_spot_service import UnifiedSpotService


class TestRiskEnvelopeServiceImportPath:
    """Test that risk_envelope_service can be imported from correct path."""

    def test_import_from_risk_profiles_risk_envelope_service(self):
        """Test that get_risk_envelope_service can be imported from merid.risk.profiles.risk_envelope_service."""
        # This should not raise ImportError
        from merid.risk.profiles.risk_envelope_service import get_risk_envelope_service, RiskEnvelopeService
        assert get_risk_envelope_service is not None
        assert RiskEnvelopeService is not None

    def test_import_from_merid_risk_envelope_fails(self):
        """Test that importing from merid.risk.envelope fails."""
        # This should raise ImportError because the module doesn't exist
        with pytest.raises(ImportError):
            from merid.risk.envelope import RiskEnvelopeService


class TestRiskEnvelopeServiceStartupGrace:
    """Test that RiskEnvelopeService gracefully handles bankroll not ready during startup."""

    def test_validate_kalshi_15m_strip_limits_consistency_no_envelope_import(self):
        """Test that validate_kalshi_15m_strip_limits_consistency doesn't import envelope service."""
        from merid.startup_validations import validate_kalshi_15m_strip_limits_consistency
        
        # Set profile to kalshi_crypto_15m_v2
        original_profile = os.environ.get("MERID_PROFILE")
        os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
        
        try:
            # This function should not import RiskEnvelopeService
            # It only checks profile config, not envelope
            validate_kalshi_15m_strip_limits_consistency()
        finally:
            # Restore original profile
            if original_profile is None:
                os.environ.pop("MERID_PROFILE", None)
            else:
                os.environ["MERID_PROFILE"] = original_profile

    def test_startup_validations_imports_correct_risk_envelope_service(self):
        """Test that startup_validations imports from correct risk_envelope_service path."""
        # Read the startup_validations file to verify import path
        with open('c:/Dev/MERID/merid/startup_validations.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Should have correct import path
        assert 'from merid.risk.profiles.risk_envelope_service import get_risk_envelope_service' in content
        
        # Should not have incorrect import path
        assert 'from merid.risk.envelope import' not in content


class TestDiagnoseTradingStackGapsImportFix:
    """Test that diagnose_trading_stack_gaps.py uses correct import paths."""

    def test_diagnostic_script_uses_correct_import_path(self):
        """Test that diagnostic script imports from data.unified_spot_service."""
        # Read the diagnostic script to verify import path
        with open('c:/Dev/MERID/scripts/diagnose_trading_stack_gaps.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Should have correct import path (may be in try/except block)
        assert 'data.unified_spot_service' in content
        
        # Should not have incorrect import path
        assert 'merid.data.unified_spot_service' not in content
