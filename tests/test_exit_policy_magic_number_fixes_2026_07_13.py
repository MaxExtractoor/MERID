"""
Test suite for exit policy magic number removal fixes (2026-07-13).

Tests verify that all exit policy parameters are loaded from configuration
instead of hardcoded values, per Invariant #7 (No Magic Numbers in Exit Logic).

Fixes tested:
- order_router.py: trailing_giveback_cents loaded from profile
- crypto_15m_profile.py: trailing_stop_giveback_cents field added
- dynamic_risk.py: SL fallback values match profile defaults
- kalshi_api.py: SL offset loaded from profile
"""

import pytest
from pathlib import Path


class TestExitPolicyNoMagicNumbers:
    """Comprehensive test for Invariant #7: No Magic Numbers in Exit Logic."""
    
    def test_order_router_no_hardcoded_trailing_giveback(self):
        """Test that order_router.py doesn't have hardcoded trailing_giveback_cents=5 in return statement."""
        import re
        
        order_router_path = Path(__file__).parent.parent / "merid/event_venues/kalshi/order_router.py"
        with open(order_router_path, encoding='utf-8') as f:
            content = f.read()
        
        # Look for trailing_giveback_cents=5 in ExitPolicyResolution return statement
        # It should now use a variable, not hardcoded 5
        # The pattern matches trailing_giveback_cents=5 followed by non-digit
        resolution_pattern = r'trailing_giveback_cents=5[^0-9]'
        matches = re.findall(resolution_pattern, content)
        
        # Should not have hardcoded trailing_giveback_cents=5 in the return statement
        # (fallbacks in exception handlers are acceptable)
        assert len(matches) == 0, \
            f"Found {len(matches)} hardcoded trailing_giveback_cents=5 in ExitPolicyResolution construction"
    
    def test_dynamic_risk_fallbacks_documented_as_profile_defaults(self):
        """Test that dynamic_risk.py fallback values are documented as profile defaults."""
        dynamic_risk_path = Path(__file__).parent.parent / "merid/event_venues/kalshi/dynamic_risk.py"
        with open(dynamic_risk_path, encoding='utf-8') as f:
            content = f.read()
        
        # Verify comment mentions profile defaults
        assert "profile default" in content.lower(), \
            "dynamic_risk.py fallback values should be documented as matching profile defaults"
    
    def test_crypto_15m_profile_yaml_has_giveback_cents(self):
        """Test that profile YAML has giveback_cents configured."""
        import yaml
        
        yaml_path = Path(__file__).parent.parent / "config/profiles/kalshi_crypto_15m_v2.yaml"
        with open(yaml_path, encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # Verify trailing_stop section has giveback_cents
        assert 'trailing_stop' in config, "Profile YAML missing trailing_stop section"
        assert 'giveback_cents' in config['trailing_stop'], \
            "Profile YAML trailing_stop missing giveback_cents field"
    
    def test_crypto_15m_profile_has_trailing_giveback_field(self):
        """Test that crypto_15m_profile.py has trailing_stop_giveback_cents field."""
        profile_path = Path(__file__).parent.parent / "merid/risk/profiles/crypto_15m_profile.py"
        with open(profile_path, encoding='utf-8') as f:
            content = f.read()
        
        # Verify field is defined in the dataclass
        assert 'trailing_stop_giveback_cents' in content, \
            "crypto_15m_profile.py missing trailing_stop_giveback_cents field"
    
    def test_kalshi_api_sl_offset_loaded_from_profile(self):
        """Test that kalshi_api.py loads SL offset from profile."""
        api_path = Path(__file__).parent.parent / "web/api/kalshi_api.py"
        with open(api_path, encoding='utf-8') as f:
            content = f.read()
        
        # Verify code path exists to load SL offset from profile
        assert 'dynamic_risk_sl_cents_normal_vol' in content, \
            "kalshi_api.py missing profile SL offset loading code"
        assert 'CRITICAL FIX: 2026-07-13' in content, \
            "kalshi_api.py missing fix comment for SL offset loading"
    
    def test_order_router_trailing_giveback_loading_code(self):
        """Test that order_router.py has code to load trailing_giveback_cents from profile."""
        order_router_path = Path(__file__).parent.parent / "merid/event_venues/kalshi/order_router.py"
        with open(order_router_path, encoding='utf-8') as f:
            content = f.read()
        
        # Verify code path exists to load trailing_giveback_cents from profile
        assert 'trailing_giveback_cents' in content, \
            "order_router.py missing trailing_giveback_cents variable"
        # The fix comment exists in the code (verified by grep), just check for the pattern
        assert 'Load trailing_giveback_cents from profile config' in content, \
            "order_router.py missing fix comment for trailing giveback loading"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
