"""
Configuration Invariants: Test-Production Alignment

This module enforces invariants to ensure test configurations match production
configurations, preventing drift between test and live environments.

Key Invariants:
- Test profile configuration must match production profile configuration
- Risk limits in tests must match production risk limits
- Price ranges in tests must match production canonical range (10-75c)
- Asset universe in tests must include all critical assets (BTC, ETH, SOL, XRP, DOGE)
- Fixed exposure cap in tests must match production ($1.00)
- No hardcoded values that diverge from production config

Usage::

    from merid.validation.config_invariants import (
        ConfigInvariantChecker,
        check_profile_alignment,
        check_risk_limits_alignment,
        check_price_range_alignment,
        check_asset_universe_alignment
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from pathlib import Path
import yaml
from utils.logger import get_logger

logger = get_logger("merid.validation.config_invariants")


class ConfigViolation(str, Enum):
    """Types of configuration violations."""
    PROFILE_MISMATCH = "profile_mismatch"
    RISK_LIMIT_MISMATCH = "risk_limit_mismatch"
    PRICE_RANGE_MISMATCH = "price_range_mismatch"
    ASSET_UNIVERSE_MISMATCH = "asset_universe_mismatch"
    EXPOSURE_CAP_MISMATCH = "exposure_cap_mismatch"
    HARDCODED_VALUE_MISMATCH = "hardcoded_value_mismatch"


@dataclass
class ConfigCheckResult:
    """Result of configuration check."""
    is_valid: bool
    violation_type: Optional[ConfigViolation]
    message: str
    context: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "violation_type": self.violation_type.value if self.violation_type else None,
            "message": self.message,
            "context": self.context,
        }


class ConfigInvariantChecker:
    """Checks configuration invariants for test-production alignment."""
    
    # Production canonical values (from memories and codebase)
    PRODUCTION_VALUES = {
        "min_price_cents": 10,
        "max_price_cents": 75,
        "fixed_exposure_cap_usd": 1.00,
        "max_contracts_per_trade": 1,
        "critical_assets": ["BTC", "ETH", "SOL", "XRP", "DOGE"],
        "min_edge_threshold": 0.01,
        "max_spread_cents": 30,
        "min_volume": 10,
    }
    
    def __init__(self, production_config_path: Optional[str] = None):
        self.production_config_path = production_config_path
        self.production_config = {}
        
        if production_config_path:
            self._load_production_config()
    
    def _load_production_config(self):
        """Load production configuration from YAML file."""
        try:
            with open(self.production_config_path, 'r') as f:
                self.production_config = yaml.safe_load(f)
        except Exception as e:
            logger.warning(f"Failed to load production config from {self.production_config_path}: {e}")
    
    def check_profile_alignment(
        self,
        test_profile: Dict[str, Any],
        production_profile: Optional[Dict[str, Any]] = None,
    ) -> ConfigCheckResult:
        """INVARIANT: Test profile configuration must match production profile.
        
        Critical fields that must match:
        - min_price_cents
        - max_price_cents
        - fixed_exposure_cap_usd
        - max_contracts_per_trade
        """
        if production_profile is None:
            production_profile = self.production_config
        
        context = {
            "test_profile_keys": list(test_profile.keys()),
            "production_profile_keys": list(production_profile.keys()) if production_profile else [],
        }
        
        critical_fields = [
            "min_price_cents",
            "max_price_cents",
            "fixed_exposure_cap_usd",
            "max_contracts_per_trade",
        ]
        
        for field in critical_fields:
            test_value = test_profile.get(field)
            prod_value = production_profile.get(field) if production_profile else self.PRODUCTION_VALUES.get(field)
            
            if test_value != prod_value:
                context[f"{field}_test"] = test_value
                context[f"{field}_production"] = prod_value
                
                return ConfigCheckResult(
                    is_valid=False,
                    violation_type=ConfigViolation.PROFILE_MISMATCH,
                    message=f"Profile field {field} mismatch: test={test_value}, production={prod_value}",
                    context=context,
                )
        
        return ConfigCheckResult(
            is_valid=True,
            violation_type=None,
            message="Profile configuration aligned with production",
            context=context,
        )
    
    def check_risk_limits_alignment(
        self,
        test_risk_limits: Dict[str, Any],
        production_risk_limits: Optional[Dict[str, Any]] = None,
    ) -> ConfigCheckResult:
        """INVARIANT: Risk limits in tests must match production risk limits.
        
        Critical fields that must match:
        - fixed_exposure_cap_usd ($1.00)
        - max_contracts_per_trade (1)
        - Percentage-based caps should be 0.0 (disabled, using fixed cap)
        """
        if production_risk_limits is None:
            production_risk_limits = self.production_config.get("risk_limits", {})
        
        context = {
            "test_risk_limits_keys": list(test_risk_limits.keys()),
            "production_risk_limits_keys": list(production_risk_limits.keys()) if production_risk_limits else [],
        }
        
        # Check fixed exposure cap
        test_cap = test_risk_limits.get("fixed_exposure_cap_usd")
        prod_cap = production_risk_limits.get("fixed_exposure_cap_usd") if production_risk_limits else self.PRODUCTION_VALUES["fixed_exposure_cap_usd"]
        
        if test_cap != prod_cap:
            context["fixed_exposure_cap_usd_test"] = test_cap
            context["fixed_exposure_cap_usd_production"] = prod_cap
            
            return ConfigCheckResult(
                is_valid=False,
                violation_type=ConfigViolation.RISK_LIMIT_MISMATCH,
                message=f"Fixed exposure cap mismatch: test=${test_cap}, production=${prod_cap}",
                context=context,
            )
        
        # Check max contracts
        test_max_contracts = test_risk_limits.get("max_contracts_per_trade")
        prod_max_contracts = production_risk_limits.get("max_contracts_per_trade") if production_risk_limits else self.PRODUCTION_VALUES["max_contracts_per_trade"]
        
        if test_max_contracts != prod_max_contracts:
            context["max_contracts_per_trade_test"] = test_max_contracts
            context["max_contracts_per_trade_production"] = prod_max_contracts
            
            return ConfigCheckResult(
                is_valid=False,
                violation_type=ConfigViolation.RISK_LIMIT_MISMATCH,
                message=f"Max contracts mismatch: test={test_max_contracts}, production={prod_max_contracts}",
                context=context,
            )
        
        # Check percentage-based caps are disabled (0.0)
        percentage_fields = [
            "max_cycle_risk_pct",
            "max_total_risk_pct",
            "max_notional_pct",
            "max_per_trade_risk_pct",
        ]
        
        for field in percentage_fields:
            test_pct = test_risk_limits.get(field)
            if test_pct is not None and test_pct != 0.0:
                context[f"{field}_test"] = test_pct
                
                return ConfigCheckResult(
                    is_valid=False,
                    violation_type=ConfigViolation.RISK_LIMIT_MISMATCH,
                    message=f"Percentage-based cap {field} should be 0.0 (disabled), got {test_pct}",
                    context=context,
                )
        
        return ConfigCheckResult(
            is_valid=True,
            violation_type=None,
            message="Risk limits aligned with production",
            context=context,
        )
    
    def check_price_range_alignment(
        self,
        test_min_price_cents: int,
        test_max_price_cents: int,
    ) -> ConfigCheckResult:
        """INVARIANT: Price ranges in tests must match production canonical range (10-75c).
        
        This ensures tests are using the correct price range for the 15m Kalshi system.
        """
        context = {
            "test_min_price_cents": test_min_price_cents,
            "test_max_price_cents": test_max_price_cents,
            "production_min_price_cents": self.PRODUCTION_VALUES["min_price_cents"],
            "production_max_price_cents": self.PRODUCTION_VALUES["max_price_cents"],
        }
        
        if test_min_price_cents != self.PRODUCTION_VALUES["min_price_cents"]:
            return ConfigCheckResult(
                is_valid=False,
                violation_type=ConfigViolation.PRICE_RANGE_MISMATCH,
                message=f"Min price cents mismatch: test={test_min_price_cents}, production={self.PRODUCTION_VALUES['min_price_cents']}",
                context=context,
            )
        
        if test_max_price_cents != self.PRODUCTION_VALUES["max_price_cents"]:
            return ConfigCheckResult(
                is_valid=False,
                violation_type=ConfigViolation.PRICE_RANGE_MISMATCH,
                message=f"Max price cents mismatch: test={test_max_price_cents}, production={self.PRODUCTION_VALUES['max_price_cents']}",
                context=context,
            )
        
        return ConfigCheckResult(
            is_valid=True,
            violation_type=None,
            message="Price range aligned with production (10-75c)",
            context=context,
        )
    
    def check_asset_universe_alignment(
        self,
        test_assets: List[str],
    ) -> ConfigCheckResult:
        """INVARIANT: Asset universe in tests must include all critical assets.
        
        All critical assets (BTC, ETH, SOL, XRP, DOGE) must be present in test asset lists.
        """
        context = {
            "test_assets": test_assets,
            "critical_assets": self.PRODUCTION_VALUES["critical_assets"],
        }
        
        missing_assets = []
        for asset in self.PRODUCTION_VALUES["critical_assets"]:
            if asset not in test_assets:
                missing_assets.append(asset)
        
        if missing_assets:
            context["missing_assets"] = missing_assets
            
            return ConfigCheckResult(
                is_valid=False,
                violation_type=ConfigViolation.ASSET_UNIVERSE_MISMATCH,
                message=f"Test asset universe missing critical assets: {missing_assets}",
                context=context,
            )
        
        return ConfigCheckResult(
            is_valid=True,
            violation_type=None,
            message="Asset universe includes all critical assets",
            context=context,
        )
    
    def check_exposure_cap_alignment(
        self,
        test_exposure_cap_usd: float,
    ) -> ConfigCheckResult:
        """INVARIANT: Fixed exposure cap in tests must match production ($1.00).
        
        The $1 global risk exposure cap must NEVER be changed.
        """
        context = {
            "test_exposure_cap_usd": test_exposure_cap_usd,
            "production_exposure_cap_usd": self.PRODUCTION_VALUES["fixed_exposure_cap_usd"],
        }
        
        if test_exposure_cap_usd != self.PRODUCTION_VALUES["fixed_exposure_cap_usd"]:
            return ConfigCheckResult(
                is_valid=False,
                violation_type=ConfigViolation.EXPOSURE_CAP_MISMATCH,
                message=f"Exposure cap mismatch: test=${test_exposure_cap_usd}, production=${self.PRODUCTION_VALUES['fixed_exposure_cap_usd']}",
                context=context,
            )
        
        return ConfigCheckResult(
            is_valid=True,
            violation_type=None,
            message="Exposure cap aligned with production ($1.00)",
            context=context,
        )
    
    def check_hardcoded_value_alignment(
        self,
        file_path: str,
        hardcoded_values: Dict[str, Any],
    ) -> ConfigCheckResult:
        """INVARIANT: No hardcoded values that diverge from production config.
        
        Checks for hardcoded values in test files that should use production config.
        """
        context = {
            "file_path": file_path,
            "hardcoded_values": hardcoded_values,
        }
        
        violations = []
        
        for key, value in hardcoded_values.items():
            if key in self.PRODUCTION_VALUES:
                if value != self.PRODUCTION_VALUES[key]:
                    violations.append(f"{key}: hardcoded={value}, production={self.PRODUCTION_VALUES[key]}")
        
        if violations:
            context["violations"] = violations
            
            return ConfigCheckResult(
                is_valid=False,
                violation_type=ConfigViolation.HARDCODED_VALUE_MISMATCH,
                message=f"Hardcoded values diverge from production: {violations}",
                context=context,
            )
        
        return ConfigCheckResult(
            is_valid=True,
            violation_type=None,
            message="Hardcoded values aligned with production",
            context=context,
        )
    
    def check_all_invariants(
        self,
        test_profile: Dict[str, Any],
        test_risk_limits: Dict[str, Any],
        test_assets: List[str],
        test_exposure_cap_usd: float,
    ) -> List[ConfigCheckResult]:
        """Run all configuration invariants."""
        results = []
        
        # Check profile alignment
        result = self.check_profile_alignment(test_profile)
        results.append(result)
        
        # Check risk limits alignment
        result = self.check_risk_limits_alignment(test_risk_limits)
        results.append(result)
        
        # Check price range alignment
        min_price = test_profile.get("min_price_cents", 10)
        max_price = test_profile.get("max_price_cents", 75)
        result = self.check_price_range_alignment(min_price, max_price)
        results.append(result)
        
        # Check asset universe alignment
        result = self.check_asset_universe_alignment(test_assets)
        results.append(result)
        
        # Check exposure cap alignment
        result = self.check_exposure_cap_alignment(test_exposure_cap_usd)
        results.append(result)
        
        return results


# Convenience functions for direct use

def check_profile_alignment(
    test_profile: Dict[str, Any],
    production_profile: Optional[Dict[str, Any]] = None,
) -> ConfigCheckResult:
    """Check profile alignment invariant."""
    checker = ConfigInvariantChecker()
    return checker.check_profile_alignment(test_profile, production_profile)


def check_risk_limits_alignment(
    test_risk_limits: Dict[str, Any],
    production_risk_limits: Optional[Dict[str, Any]] = None,
) -> ConfigCheckResult:
    """Check risk limits alignment invariant."""
    checker = ConfigInvariantChecker()
    return checker.check_risk_limits_alignment(test_risk_limits, production_risk_limits)


def check_price_range_alignment(
    test_min_price_cents: int,
    test_max_price_cents: int,
) -> ConfigCheckResult:
    """Check price range alignment invariant."""
    checker = ConfigInvariantChecker()
    return checker.check_price_range_alignment(test_min_price_cents, test_max_price_cents)


def check_asset_universe_alignment(
    test_assets: List[str],
) -> ConfigCheckResult:
    """Check asset universe alignment invariant."""
    checker = ConfigInvariantChecker()
    return checker.check_asset_universe_alignment(test_assets)


def check_exposure_cap_alignment(
    test_exposure_cap_usd: float,
) -> ConfigCheckResult:
    """Check exposure cap alignment invariant."""
    checker = ConfigInvariantChecker()
    return checker.check_exposure_cap_alignment(test_exposure_cap_usd)


# Synthetic test data generator for invariant testing

def generate_synthetic_config_test_cases() -> List[Dict[str, Any]]:
    """Generate synthetic test cases for configuration invariants.
    
    Returns:
        List of test case dictionaries with controlled config data.
    """
    test_cases = []
    
    # Valid case: all configs match production
    test_profile_valid = {
        "min_price_cents": 10,
        "max_price_cents": 75,
        "fixed_exposure_cap_usd": 1.00,
        "max_contracts_per_trade": 1,
    }
    
    test_risk_limits_valid = {
        "fixed_exposure_cap_usd": 1.00,
        "max_contracts_per_trade": 1,
        "max_cycle_risk_pct": 0.0,
        "max_total_risk_pct": 0.0,
        "max_notional_pct": 0.0,
        "max_per_trade_risk_pct": 0.0,
    }
    
    test_assets_valid = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    
    test_cases.append({
        "test_profile": test_profile_valid,
        "test_risk_limits": test_risk_limits_valid,
        "test_assets": test_assets_valid,
        "test_exposure_cap_usd": 1.00,
        "expected_valid": True,
        "description": "All configurations match production - valid",
    })
    
    # Invalid case: price range mismatch
    test_profile_invalid_price = {
        "min_price_cents": 10,
        "max_price_cents": 50,  # Old value, should be 75
        "fixed_exposure_cap_usd": 1.00,
        "max_contracts_per_trade": 1,
    }
    
    test_cases.append({
        "test_profile": test_profile_invalid_price,
        "test_risk_limits": test_risk_limits_valid,
        "test_assets": test_assets_valid,
        "test_exposure_cap_usd": 1.00,
        "expected_valid": False,
        "description": "Max price cents is 50 instead of 75 - violation",
    })
    
    # Invalid case: missing critical asset
    test_assets_missing = ["BTC", "ETH", "SOL"]  # Missing XRP, DOGE
    
    test_cases.append({
        "test_profile": test_profile_valid,
        "test_risk_limits": test_risk_limits_valid,
        "test_assets": test_assets_missing,
        "test_exposure_cap_usd": 1.00,
        "expected_valid": False,
        "description": "Asset universe missing XRP and DOGE - violation",
    })
    
    # Invalid case: exposure cap mismatch
    test_cases.append({
        "test_profile": test_profile_valid,
        "test_risk_limits": test_risk_limits_valid,
        "test_assets": test_assets_valid,
        "test_exposure_cap_usd": 2.00,  # Should be 1.00
        "expected_valid": False,
        "description": "Exposure cap is $2.00 instead of $1.00 - violation",
    })
    
    # Invalid case: percentage-based cap not disabled
    test_risk_limits_pct = {
        "fixed_exposure_cap_usd": 1.00,
        "max_contracts_per_trade": 1,
        "max_cycle_risk_pct": 0.05,  # Should be 0.0
        "max_total_risk_pct": 0.0,
        "max_notional_pct": 0.0,
        "max_per_trade_risk_pct": 0.0,
    }
    
    test_cases.append({
        "test_profile": test_profile_valid,
        "test_risk_limits": test_risk_limits_pct,
        "test_assets": test_assets_valid,
        "test_exposure_cap_usd": 1.00,
        "expected_valid": False,
        "description": "max_cycle_risk_pct is 0.05 instead of 0.0 - violation",
    })
    
    return test_cases
