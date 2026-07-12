"""
Test profile validation for 15m_live mode.

This test ensures that the profile validation re-enabled in main_15m_lean.py
works correctly and validates the kalshi_crypto_15m_v2 profile.
"""
import sys
import os
from pathlib import Path
import pytest

# Add repo root to sys.path
repo_root = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, repo_root)


class TestProfileValidation:
    """Test profile validation for 15m_live mode."""
    
    def test_profile_resolver_import(self):
        """Test that profile_resolver can be imported."""
        from merid.validation.profile_resolver import (
            validate_15m_profile,
            validate_required_config_files,
            check_deprecated_modules_imported,
        )
        
        assert validate_15m_profile is not None
        assert validate_required_config_files is not None
        assert check_deprecated_modules_imported is not None
    
    def test_validate_15m_profile_valid(self):
        """Test that valid profile passes validation."""
        from merid.validation.profile_resolver import validate_15m_profile
        
        # Valid profile for 15m_live mode
        validate_15m_profile("kalshi_crypto_15m_v2", "15m_live")
    
    def test_validate_15m_profile_invalid(self):
        """Test that invalid profile raises ValueError."""
        from merid.validation.profile_resolver import validate_15m_profile
        
        # Invalid profile should raise ValueError
        with pytest.raises(ValueError):
            validate_15m_profile("invalid_profile", "15m_live")
    
    def test_validate_required_config_files(self):
        """Test that required config files exist."""
        from merid.validation.profile_resolver import validate_required_config_files
        
        base_path = str(Path(__file__).resolve().parents[1])
        
        # Should not raise if all required files exist
        validate_required_config_files(base_path)
    
    def test_allowed_profiles_constant(self):
        """Test that ALLOWED_15M_PROFILES includes kalshi_crypto_15m_v2."""
        from merid.validation.profile_resolver import ALLOWED_15M_PROFILES
        
        assert "kalshi_crypto_15m_v2" in ALLOWED_15M_PROFILES
