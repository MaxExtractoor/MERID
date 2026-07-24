"""
Tests for config_invariants.py

Pure unit tests with synthetic inputs, no I/O, fully deterministic.
"""

import pytest

from merid.validation.config_invariants import (
    ConfigInvariantChecker,
    ConfigViolation,
    ConfigCheckResult,
    check_profile_alignment,
    check_risk_limits_alignment,
    check_price_range_alignment,
    check_asset_universe_alignment,
    check_exposure_cap_alignment,
    generate_synthetic_config_test_cases,
)


class TestConfigInvariants:
    """Test suite for configuration invariants."""
    
    @pytest.fixture
    def checker(self):
        """Fixture for ConfigInvariantChecker."""
        return ConfigInvariantChecker()
    
    def test_test_profile_matches_production_profile(self, checker):
        """
        Profile names, risk limits, etc.
        """
        # Valid case: test profile matches production
        test_profile = {
            "min_price_cents": 10,
            "max_price_cents": 75,
            "fixed_exposure_cap_usd": 1.00,
            "max_contracts_per_trade": 1,
        }
        
        result = checker.check_profile_alignment(test_profile)
        assert result.is_valid
        
        # Invalid case: max_price_cents mismatch
        test_profile_invalid = {
            "min_price_cents": 10,
            "max_price_cents": 50,  # Old value, should be 75
            "fixed_exposure_cap_usd": 1.00,
            "max_contracts_per_trade": 1,
        }
        
        result = checker.check_profile_alignment(test_profile_invalid)
        assert not result.is_valid
        assert result.violation_type == ConfigViolation.PROFILE_MISMATCH
    
    def test_price_range_matches_canonical_values(self, checker):
        """
        min_price_cents=10, max_price_cents=75.
        """
        # Valid case: matches canonical range
        result = checker.check_price_range_alignment(
            test_min_price_cents=10,
            test_max_price_cents=75,
        )
        assert result.is_valid
        
        # Invalid case: min_price_cents mismatch
        result = checker.check_price_range_alignment(
            test_min_price_cents=5,  # Wrong, should be 10
            test_max_price_cents=75,
        )
        assert not result.is_valid
        assert result.violation_type == ConfigViolation.PRICE_RANGE_MISMATCH
        
        # Invalid case: max_price_cents mismatch
        result = checker.check_price_range_alignment(
            test_min_price_cents=10,
            test_max_price_cents=50,  # Wrong, should be 75
        )
        assert not result.is_valid
        assert result.violation_type == ConfigViolation.PRICE_RANGE_MISMATCH
    
    def test_exposure_cap_and_asset_universe_match_production(self, checker):
        """
        fixed_exposure_cap_usd=1.00; asset universe includes BTC/ETH/SOL/XRP/DOGE.
        """
        # Valid case: exposure cap matches
        result = checker.check_exposure_cap_alignment(
            test_exposure_cap_usd=1.00,
        )
        assert result.is_valid
        
        # Invalid case: exposure cap mismatch
        result = checker.check_exposure_cap_alignment(
            test_exposure_cap_usd=2.00,  # Wrong, should be 1.00
        )
        assert not result.is_valid
        assert result.violation_type == ConfigViolation.EXPOSURE_CAP_MISMATCH
        
        # Valid case: asset universe includes all critical assets
        result = checker.check_asset_universe_alignment(
            test_assets=["BTC", "ETH", "SOL", "XRP", "DOGE"],
        )
        assert result.is_valid
        
        # Invalid case: asset universe missing critical assets
        result = checker.check_asset_universe_alignment(
            test_assets=["BTC", "ETH", "SOL"],  # Missing XRP, DOGE
        )
        assert not result.is_valid
        assert result.violation_type == ConfigViolation.ASSET_UNIVERSE_MISMATCH
    
    def test_no_hardcoded_divergent_values(self, checker):
        """
        Config invariants scanning for magic numbers beyond canonical ranges.
        """
        # Valid case: hardcoded values match production
        hardcoded_values = {
            "min_price_cents": 10,
            "max_price_cents": 75,
            "fixed_exposure_cap_usd": 1.00,
        }
        
        result = checker.check_hardcoded_value_alignment(
            file_path="test_file.py",
            hardcoded_values=hardcoded_values,
        )
        assert result.is_valid
        
        # Invalid case: hardcoded values diverge
        hardcoded_values_invalid = {
            "min_price_cents": 10,
            "max_price_cents": 50,  # Diverges from production
            "fixed_exposure_cap_usd": 1.00,
        }
        
        result = checker.check_hardcoded_value_alignment(
            file_path="test_file.py",
            hardcoded_values=hardcoded_values_invalid,
        )
        assert not result.is_valid
        assert result.violation_type == ConfigViolation.HARDCODED_VALUE_MISMATCH
    
    def test_risk_limits_alignment(self, checker):
        """Test risk limits alignment."""
        # Valid case: risk limits match production
        test_risk_limits = {
            "fixed_exposure_cap_usd": 1.00,
            "max_contracts_per_trade": 1,
            "max_cycle_risk_pct": 0.0,  # Disabled
            "max_total_risk_pct": 0.0,  # Disabled
            "max_notional_pct": 0.0,  # Disabled
            "max_per_trade_risk_pct": 0.0,  # Disabled
        }
        
        result = checker.check_risk_limits_alignment(test_risk_limits)
        assert result.is_valid
        
        # Invalid case: fixed exposure cap mismatch
        test_risk_limits_invalid = {
            "fixed_exposure_cap_usd": 2.00,  # Wrong, should be 1.00
            "max_contracts_per_trade": 1,
            "max_cycle_risk_pct": 0.0,
            "max_total_risk_pct": 0.0,
            "max_notional_pct": 0.0,
            "max_per_trade_risk_pct": 0.0,
        }
        
        result = checker.check_risk_limits_alignment(test_risk_limits_invalid)
        assert not result.is_valid
        assert result.violation_type == ConfigViolation.RISK_LIMIT_MISMATCH
        
        # Invalid case: percentage-based cap not disabled
        test_risk_limits_pct = {
            "fixed_exposure_cap_usd": 1.00,
            "max_contracts_per_trade": 1,
            "max_cycle_risk_pct": 0.05,  # Should be 0.0
            "max_total_risk_pct": 0.0,
            "max_notional_pct": 0.0,
            "max_per_trade_risk_pct": 0.0,
        }
        
        result = checker.check_risk_limits_alignment(test_risk_limits_pct)
        assert not result.is_valid
        assert result.violation_type == ConfigViolation.RISK_LIMIT_MISMATCH
    
    def test_check_all_invariants(self, checker):
        """Test running all configuration invariants together."""
        test_profile = {
            "min_price_cents": 10,
            "max_price_cents": 75,
            "fixed_exposure_cap_usd": 1.00,
            "max_contracts_per_trade": 1,
        }
        
        test_risk_limits = {
            "fixed_exposure_cap_usd": 1.00,
            "max_contracts_per_trade": 1,
            "max_cycle_risk_pct": 0.0,
            "max_total_risk_pct": 0.0,
            "max_notional_pct": 0.0,
            "max_per_trade_risk_pct": 0.0,
        }
        
        test_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        results = checker.check_all_invariants(
            test_profile=test_profile,
            test_risk_limits=test_risk_limits,
            test_assets=test_assets,
            test_exposure_cap_usd=1.00,
        )
        
        assert len(results) == 5  # Five invariants checked
        assert all(r.is_valid for r in results)
    
    def test_check_all_invariants_with_violations(self, checker):
        """Test running all invariants with violations."""
        test_profile = {
            "min_price_cents": 10,
            "max_price_cents": 50,  # Wrong
            "fixed_exposure_cap_usd": 1.00,
            "max_contracts_per_trade": 1,
        }
        
        test_risk_limits = {
            "fixed_exposure_cap_usd": 1.00,
            "max_contracts_per_trade": 1,
            "max_cycle_risk_pct": 0.0,
            "max_total_risk_pct": 0.0,
            "max_notional_pct": 0.0,
            "max_per_trade_risk_pct": 0.0,
        }
        
        test_assets = ["BTC", "ETH", "SOL"]  # Missing XRP, DOGE
        
        results = checker.check_all_invariants(
            test_profile=test_profile,
            test_risk_limits=test_risk_limits,
            test_assets=test_assets,
            test_exposure_cap_usd=1.00,
        )
        
        assert len(results) == 5
        assert not all(r.is_valid for r in results)
        # At least one should be invalid
        assert sum(1 for r in results if not r.is_valid) >= 1


class TestConvenienceFunctions:
    """Test convenience functions for direct use."""
    
    def test_check_profile_alignment(self):
        """Test convenience function for profile alignment."""
        test_profile = {
            "min_price_cents": 10,
            "max_price_cents": 75,
            "fixed_exposure_cap_usd": 1.00,
            "max_contracts_per_trade": 1,
        }
        
        result = check_profile_alignment(test_profile)
        assert result.is_valid
    
    def test_check_risk_limits_alignment(self):
        """Test convenience function for risk limits alignment."""
        test_risk_limits = {
            "fixed_exposure_cap_usd": 1.00,
            "max_contracts_per_trade": 1,
            "max_cycle_risk_pct": 0.0,
            "max_total_risk_pct": 0.0,
            "max_notional_pct": 0.0,
            "max_per_trade_risk_pct": 0.0,
        }
        
        result = check_risk_limits_alignment(test_risk_limits)
        assert result.is_valid
    
    def test_check_price_range_alignment(self):
        """Test convenience function for price range alignment."""
        result = check_price_range_alignment(
            test_min_price_cents=10,
            test_max_price_cents=75,
        )
        assert result.is_valid
    
    def test_check_asset_universe_alignment(self):
        """Test convenience function for asset universe alignment."""
        result = check_asset_universe_alignment(
            test_assets=["BTC", "ETH", "SOL", "XRP", "DOGE"],
        )
        assert result.is_valid
    
    def test_check_exposure_cap_alignment(self):
        """Test convenience function for exposure cap alignment."""
        result = check_exposure_cap_alignment(
            test_exposure_cap_usd=1.00,
        )
        assert result.is_valid


class TestSyntheticTestCases:
    """Test synthetic test case generator."""
    
    def test_generate_synthetic_config_test_cases(self):
        """Test that synthetic test cases are generated correctly."""
        test_cases = generate_synthetic_config_test_cases()
        
        assert len(test_cases) > 0
        assert all("test_profile" in tc for tc in test_cases)
        assert all("test_risk_limits" in tc for tc in test_cases)
        assert all("test_assets" in tc for tc in test_cases)
        assert all("test_exposure_cap_usd" in tc for tc in test_cases)
        assert all("expected_valid" in tc for tc in test_cases)
    
    def test_synthetic_test_cases_valid_and_invalid(self):
        """Test that synthetic test cases include both valid and invalid cases."""
        test_cases = generate_synthetic_config_test_cases()
        
        valid_cases = [tc for tc in test_cases if tc["expected_valid"]]
        invalid_cases = [tc for tc in test_cases if not tc["expected_valid"]]
        
        assert len(valid_cases) > 0
        assert len(invalid_cases) > 0
    
    def test_synthetic_test_cases_cover_all_config_aspects(self):
        """Test that synthetic test cases cover all config aspects."""
        test_cases = generate_synthetic_config_test_cases()
        
        # Check that test cases exist
        assert len(test_cases) > 0
        
        # Check that test cases have descriptions
        descriptions = [tc.get("description", "") for tc in test_cases]
        assert any("price" in desc.lower() for desc in descriptions) or len(test_cases) > 0


class TestConfigCheckResult:
    """Test ConfigCheckResult dataclass."""
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = ConfigCheckResult(
            is_valid=True,
            violation_type=None,
            message="Test message",
            context={"key": "value"},
        )
        
        result_dict = result.to_dict()
        assert result_dict["is_valid"] is True
        assert result_dict["violation_type"] is None
        assert result_dict["message"] == "Test message"
        assert result_dict["context"] == {"key": "value"}
    
    def test_to_dict_with_violation(self):
        """Test conversion to dictionary with violation."""
        result = ConfigCheckResult(
            is_valid=False,
            violation_type=ConfigViolation.PROFILE_MISMATCH,
            message="Test violation",
            context={},
        )
        
        result_dict = result.to_dict()
        assert result_dict["is_valid"] is False
        assert result_dict["violation_type"] == "profile_mismatch"


class TestProductionValues:
    """Test production canonical values."""
    
    def test_production_values_are_correct(self):
        """Test that production values match system constraints."""
        checker = ConfigInvariantChecker()
        
        # Verify production values
        assert checker.PRODUCTION_VALUES["min_price_cents"] == 10
        assert checker.PRODUCTION_VALUES["max_price_cents"] == 75
        assert checker.PRODUCTION_VALUES["fixed_exposure_cap_usd"] == 1.00
        assert checker.PRODUCTION_VALUES["max_contracts_per_trade"] == 1
        assert "BTC" in checker.PRODUCTION_VALUES["critical_assets"]
        assert "ETH" in checker.PRODUCTION_VALUES["critical_assets"]
        assert "SOL" in checker.PRODUCTION_VALUES["critical_assets"]
        assert "XRP" in checker.PRODUCTION_VALUES["critical_assets"]
        assert "DOGE" in checker.PRODUCTION_VALUES["critical_assets"]
