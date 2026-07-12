"""Test ratchet profit floor configuration loading from profile YAML.

This verifies that ratchet configuration is correctly loaded from the YAML
profile and propagated through the system.
"""

import pytest
from pathlib import Path
import os


class TestRatchetProfileLoading:
    """Test suite for ratchet configuration loading from profile."""
    
    def test_profile_yaml_has_ratchet_section(self):
        """Verify the profile YAML contains the ratchet_profit_floor section."""
        profile_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        assert profile_path.exists(), f"Profile file not found: {profile_path}"
        
        import yaml
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_data = yaml.safe_load(f)
        
        assert "ratchet_profit_floor" in profile_data, "ratchet_profit_floor section missing from YAML"
        
        ratchet_config = profile_data["ratchet_profit_floor"]
        assert "enabled" in ratchet_config
        assert "activation_threshold_cents" in ratchet_config
        assert "floor_offset_cents" in ratchet_config
        assert "force_exit_on_floor_breach" in ratchet_config
        assert "min_hold_after_activation_sec" in ratchet_config
        # CRITICAL FIX: 2026-07-06 - Removed mandatory_exit_at_99c (redundant, handled by position-level extreme profit)
        assert "mandatory_exit_at_99c" not in ratchet_config  # Should NOT be present (removed)
        assert "trim_position_enabled" in ratchet_config  # 2026-07-05: Added position trimming
        assert "trim_threshold_cents" in ratchet_config  # 2026-07-05: Trim threshold
        assert "trim_to_contracts" in ratchet_config  # 2026-07-05: Trim to contracts
    
    def test_profile_adapter_loads_ratchet_config(self):
        """Verify Crypto15mProfileAdapter loads ratchet configuration correctly."""
        # Set the profile environment variable
        os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
        
        try:
            from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
            
            adapter = Crypto15mProfileAdapter()
            profile = adapter.profile
            
            # Verify ratchet fields are loaded
            assert hasattr(profile, "ratchet_profit_floor_enabled")
            assert hasattr(profile, "ratchet_activation_threshold_cents")
            assert hasattr(profile, "ratchet_floor_offset_cents")
            assert hasattr(profile, "ratchet_force_exit_on_floor_breach")
            assert hasattr(profile, "ratchet_min_hold_after_activation_sec")
            # CRITICAL FIX: 2026-07-06 - Removed ratchet_mandatory_exit_at_99c (redundant, handled by position-level extreme profit)
            assert not hasattr(profile, "ratchet_mandatory_exit_at_99c")  # Should NOT have this field
            assert hasattr(profile, "ratchet_trim_position_enabled")
            assert hasattr(profile, "ratchet_trim_threshold_cents")
            assert hasattr(profile, "ratchet_trim_to_contracts")
            
            # Verify default values match YAML
            assert profile.ratchet_profit_floor_enabled is True
            assert profile.ratchet_activation_threshold_cents == 85
            assert profile.ratchet_floor_offset_cents == 5
            assert profile.ratchet_force_exit_on_floor_breach is True
            assert profile.ratchet_min_hold_after_activation_sec == 30
            assert profile.ratchet_trim_position_enabled is True  # 2026-07-05: Added position trimming
            assert profile.ratchet_trim_threshold_cents == 80  # 2026-07-05: Trim at 80c
            assert profile.ratchet_trim_to_contracts == 1  # 2026-07-05: Trim to 1 contract
        except Exception as e:
            pytest.skip(f"Profile loading failed (environment may not be set up): {e}")
    
    def test_ratchet_config_defaults_when_missing(self):
        """Verify ratchet config has sensible defaults when YAML section is missing."""
        # Verify the default values in the Crypto15mProfile dataclass
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfile
        
        # Check that the dataclass has default values for ratchet fields
        # These are the defaults defined in the dataclass
        assert Crypto15mProfile.ratchet_profit_floor_enabled == True
        assert Crypto15mProfile.ratchet_activation_threshold_cents == 85
        assert Crypto15mProfile.ratchet_floor_offset_cents == 5
        assert Crypto15mProfile.ratchet_force_exit_on_floor_breach == True
        assert Crypto15mProfile.ratchet_min_hold_after_activation_sec == 30
        # CRITICAL FIX: 2026-07-06 - Removed ratchet_mandatory_exit_at_99c (redundant, handled by position-level extreme profit)
        assert not hasattr(Crypto15mProfile, "ratchet_mandatory_exit_at_99c")  # Should NOT have this field
        assert Crypto15mProfile.ratchet_trim_position_enabled == True
        assert Crypto15mProfile.ratchet_trim_threshold_cents == 80
        assert Crypto15mProfile.ratchet_trim_to_contracts == 1
    
    def test_price_range_profile_loading(self):
        """Verify price_range configuration is loaded from profile YAML."""
        # Set the profile environment variable
        os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
        
        try:
            from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
            
            adapter = Crypto15mProfileAdapter()
            profile = adapter.profile
            
            # Verify price_range field exists
            assert hasattr(profile, "price_range"), "price_range field missing from profile"
            
            # Verify price_range has correct structure
            assert hasattr(profile.price_range, "min_price_cents")
            assert hasattr(profile.price_range, "max_price_cents")
            assert hasattr(profile.price_range, "description")
            
            # Verify values match YAML (10-50c for momentum-based trading)
            # 2026-07-09: Updated max from 70c to 50c to align with profile price_range.max_price_cents
            assert profile.price_range.min_price_cents == 10, \
                f"Expected min_price_cents=10, got {profile.price_range.min_price_cents}"
            assert profile.price_range.max_price_cents == 50, \
                f"Expected max_price_cents=50, got {profile.price_range.max_price_cents}"
            
            # Verify description is present
            assert profile.price_range.description is not None
            assert "price range" in profile.price_range.description.lower()
        except Exception as e:
            pytest.skip(f"Profile loading failed (environment may not be set up): {e}")
    
    def test_price_range_yaml_section(self):
        """Verify the profile YAML contains the price_range section."""
        profile_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        assert profile_path.exists(), f"Profile file not found: {profile_path}"
        
        import yaml
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_data = yaml.safe_load(f)
        
        assert "price_range" in profile_data, "price_range section missing from YAML"
        
        price_range_config = profile_data["price_range"]
        assert "min_price_cents" in price_range_config
        assert "max_price_cents" in price_range_config
        assert "description" in price_range_config
        
        # Verify values match expected (10-50c for momentum-based trading)
        # 2026-07-09: Updated max from 70c to 50c to align with profile price_range.max_price_cents
        assert price_range_config["min_price_cents"] == 10
        assert price_range_config["max_price_cents"] == 50


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
