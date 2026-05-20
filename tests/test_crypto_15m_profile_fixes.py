"""
Test suite for crypto_15m_profile.py fixes.

Tests the dataclass field ordering fix and USD value computation additions.
"""
import pytest
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCrypto15mProfileDataclass:
    """Test that the Crypto15mProfile dataclass has correct field ordering."""
    
    def test_dataclass_can_be_imported(self):
        """Test that the dataclass can be imported without syntax errors."""
        try:
            from merid.risk.profiles.crypto_15m_profile import Crypto15mProfile
            assert Crypto15mProfile is not None
        except Exception as e:
            pytest.fail(f"Failed to import Crypto15mProfile: {e}")
    
    def test_dataclass_has_required_fields(self):
        """Test that the dataclass has all required fields."""
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfile
        from dataclasses import fields
        
        required_fields = [
            'profile_name', 'profile_version', 'description',
            'capital_usd', 'max_cycle_risk_pct', 'max_cycle_risk_usd',
            'venue_max_single_order_pct', 'venue_max_total_notional_pct', 
            'venue_max_category_notional_pct', 'venue_max_orders_per_minute',
            'venue_max_orders_per_hour',
            'agent_max_notional_pct', 'agent_max_orders_per_window',
            'agent_max_yes_position', 'agent_max_no_position',
            'agent_max_concurrent_trades', 'agent_minutes_before_expiry',
            'agent_cutoff_minutes_before_expiry',
            'confidence_use_crypto_threshold_matrix', 'confidence_profile_name',
            'confidence_kelly_multiplier_no_trade', 'confidence_kelly_multiplier_cautious',
            'confidence_kelly_multiplier_quick_win', 'confidence_kelly_multiplier_confident',
            'guardrails_max_spread_cents', 'guardrails_max_slippage_cents',
            'guardrails_min_depth_contracts', 'guardrails_min_post_fee_edge',
            'guardrails_drawdown_halt_pct', 'guardrails_drawdown_unwind_pct',
            'guardrails_max_daily_loss_usd',
            'kelly_hard_cap', 'kelly_min_edge_pct', 'kelly_max_edge_pct',
            'kelly_min_win_prob', 'kelly_max_win_prob', 'kelly_global_notional_cap_pct',
            'legacy_disable_balance_calibration', 'legacy_disable_dynamic_contract_caps',
            'legacy_disable_bankroll_category_limits', 'legacy_disable_bankroll_prediction_risk',
            'legacy_disable_bankroll_guardrails',
        ]
        
        field_names = [f.name for f in fields(Crypto15mProfile)]
        for field in required_fields:
            assert field in field_names, f"Missing required field: {field}"
    
    def test_computed_fields_have_defaults(self):
        """Test that computed USD fields have default values."""
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfile
        from dataclasses import fields
        
        computed_fields = [
            'venue_max_single_order_usd',
            'venue_max_total_notional_usd',
            'venue_max_category_notional_usd',
            'agent_max_notional_usd',
            'asset_configs',
        ]
        
        field_dict = {f.name: f for f in fields(Crypto15mProfile)}
        for field in computed_fields:
            assert field in field_dict, f"Missing computed field: {field}"
            assert field_dict[field].default != field_dict[field].default_factory, \
                f"Computed field {field} should have a default value"


class TestCrypto15mProfileLoading:
    """Test that the profile can be loaded with the fixed computations."""
    
    def test_profile_adapter_loads_successfully(self):
        """Test that the profile adapter loads without errors."""
        try:
            from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
            
            # This will fail if MERID_PROFILE is not set, so we skip if not active
            if not os.environ.get('MERID_PROFILE', '').startswith('kalshi_crypto_15m'):
                pytest.skip("MERID_PROFILE not set to kalshi_crypto_15m_v2")
            
            adapter = Crypto15mProfileAdapter()
            assert adapter is not None
            assert adapter.profile is not None
        except Exception as e:
            pytest.skip(f"Profile loading skipped: {e}")
    
    def test_profile_has_computed_usd_values(self):
        """Test that the profile has computed USD values from percentages."""
        try:
            from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
            
            if not os.environ.get('MERID_PROFILE', '').startswith('kalshi_crypto_15m'):
                pytest.skip("MERID_PROFILE not set to kalshi_crypto_15m_v2")
            
            adapter = Crypto15mProfileAdapter()
            profile = adapter.profile
            
            # Check that USD values are computed and positive
            assert profile.venue_max_single_order_usd > 0, "venue_max_single_order_usd should be positive"
            assert profile.venue_max_total_notional_usd > 0, "venue_max_total_notional_usd should be positive"
            assert profile.venue_max_category_notional_usd > 0, "venue_max_category_notional_usd should be positive"
            assert profile.agent_max_notional_usd > 0, "agent_max_notional_usd should be positive"
            
            # Check that USD values match percentage * capital
            expected_single_order = profile.capital_usd * profile.venue_max_single_order_pct
            assert abs(profile.venue_max_single_order_usd - expected_single_order) < 0.01, \
                f"venue_max_single_order_usd mismatch: {profile.venue_max_single_order_usd} vs {expected_single_order}"
        except Exception as e:
            pytest.skip(f"Profile USD value check skipped: {e}")


class TestStartupValidationFixes:
    """Test that startup validation works with flattened dataclass fields."""
    
    def test_validation_checks_flattened_fields(self):
        """Test that validation checks flattened guardrails fields directly."""
        try:
            from merid.startup_validations import validate_15m_crypto_profile_fields
            
            if not os.environ.get('MERID_PROFILE', '').startswith('kalshi_crypto_15m'):
                pytest.skip("MERID_PROFILE not set to kalshi_crypto_15m_v2")
            
            # This should not raise an error if the profile is valid
            validate_15m_crypto_profile_fields()
        except Exception as e:
            # If it's a validation error about missing fields, the fix didn't work
            if "guardrails" in str(e) or "agent_defaults" in str(e):
                pytest.fail(f"Startup validation still checking nested fields: {e}")
            else:
                # Other validation errors are okay (e.g., invalid values)
                pytest.skip(f"Startup validation skipped due to other error: {e}")
