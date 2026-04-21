"""
Tests for Portfolio Optimizer Configuration Module

Covers:
1. Schema & parsing (YAML validation)
2. Integration with other MERID configs
3. Cross-config consistency assertions
4. Runtime wiring
"""

import os
import tempfile
from pathlib import Path
from typing import Dict, Any
from unittest.mock import MagicMock, patch

import pytest
import yaml
from pydantic import ValidationError

from merid.portfolio.config import (
    PortfolioOptimizerConfig,
    ConfigValidationError,
    load_portfolio_config,
    validate_config_consistency,
    get_effective_config,
)
from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS


class TestSchemaAndParsing:
    """Tests for YAML schema validation and parsing."""
    
    def test_default_config_creation(self):
        """Test that default config can be created."""
        config = PortfolioOptimizerConfig()
        
        assert config.enabled is True
        assert config.max_concurrent_assets == 3
        assert config.min_risk_usd_per_trade == 1.0
        assert config.max_risk_usd_per_trade == 3.0
        assert config.global_risk_budget == 9.0
        assert config.lookback_days == 60
        assert config.objective == "sharpe"
    
    def test_custom_config_values(self):
        """Test creating config with custom values."""
        config = PortfolioOptimizerConfig(
            enabled=False,
            assets=["BTC", "ETH"],
            max_concurrent_assets=2,
            min_risk_usd_per_trade=2.0,
            max_risk_usd_per_trade=4.0,
            global_risk_budget=8.0,
            lookback_days=30,
            objective="return"
        )
        
        assert config.enabled is False
        assert config.assets == ["BTC", "ETH"]
        assert config.max_concurrent_assets == 2
        assert config.min_risk_usd_per_trade == 2.0
        assert config.objective == "return"
    
    def test_invalid_asset_raises_validation_error(self):
        """Test that invalid assets are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            PortfolioOptimizerConfig(assets=["BTC", "INVALID"])
        
        assert "INVALID" in str(exc_info.value)
        assert "Invalid assets" in str(exc_info.value)
    
    def test_risk_range_validation(self):
        """Test that min_risk > max_risk is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            PortfolioOptimizerConfig(
                min_risk_usd_per_trade=5.0,
                max_risk_usd_per_trade=3.0
            )
        
        assert "max_risk_usd_per_trade" in str(exc_info.value)
        assert "min_risk_usd_per_trade" in str(exc_info.value)
    
    def test_budget_too_low_validation(self):
        """Test that budget < max_assets is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            PortfolioOptimizerConfig(
                max_concurrent_assets=3,
                global_risk_budget=2.0  # Less than 3 assets * $1 min
            )
        
        assert "global_risk_budget" in str(exc_info.value)
    
    def test_objective_validation(self):
        """Test that invalid objectives are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            PortfolioOptimizerConfig(objective="invalid_objective")
        
        assert "objective" in str(exc_info.value)
    
    def test_load_yaml_file(self, tmp_path):
        """Test loading config from YAML file."""
        yaml_content = """
portfolio_optimizer:
  enabled: true
  assets:
    - BTC
    - ETH
  max_concurrent_assets: 2
  min_risk_usd_per_trade: 1.5
  max_risk_usd_per_trade: 2.5
  global_risk_budget: 5.0
  lookback_days: 45
  objective: sharpe
"""
        config_file = tmp_path / "portfolio_optimizer.yaml"
        config_file.write_text(yaml_content)
        
        config = load_portfolio_config(str(config_file))
        
        assert config.enabled is True
        assert config.assets == ["BTC", "ETH"]
        assert config.max_concurrent_assets == 2
        assert config.min_risk_usd_per_trade == 1.5
        assert config.lookback_days == 45
    
    def test_load_yaml_with_profiles(self, tmp_path):
        """Test loading config with environment profiles."""
        yaml_content = """
portfolio_optimizer:
  enabled: true
  max_concurrent_assets: 3

profiles:
  development:
    portfolio_optimizer:
      enabled: false
      lookback_days: 30
  production:
    portfolio_optimizer:
      max_concurrent_assets: 2
      lookback_days: 90
"""
        config_file = tmp_path / "portfolio_optimizer.yaml"
        config_file.write_text(yaml_content)
        
        # Test development profile
        with patch.dict(os.environ, {"MERID_ENV": "development"}):
            config = load_portfolio_config(str(config_file))
            assert config.enabled is False
            assert config.lookback_days == 30
        
        # Test production profile
        with patch.dict(os.environ, {"MERID_ENV": "production"}):
            config = load_portfolio_config(str(config_file))
            assert config.enabled is True
            assert config.max_concurrent_assets == 2
            assert config.lookback_days == 90
    
    def test_load_nonexistent_file_uses_defaults(self):
        """Test that missing file uses defaults."""
        config = load_portfolio_config("/nonexistent/path.yaml")
        
        assert isinstance(config, PortfolioOptimizerConfig)
        assert config.enabled is True  # Default value
    
    def test_load_invalid_yaml_raises_error(self, tmp_path):
        """Test that invalid YAML raises ConfigValidationError."""
        config_file = tmp_path / "bad.yaml"
        config_file.write_text("invalid: yaml: : : content")
        
        with pytest.raises(ConfigValidationError) as exc_info:
            load_portfolio_config(str(config_file))
        
        assert "Invalid YAML" in str(exc_info.value)
    
    def test_round_trip_dict_conversion(self):
        """Test that config can be converted to dict and back."""
        original = PortfolioOptimizerConfig(
            assets=["BTC", "ETH", "SOL"],
            max_concurrent_assets=2,
            global_risk_budget=6.0
        )
        
        # Convert to dict
        config_dict = original.model_dump()
        
        # Create new config from dict
        restored = PortfolioOptimizerConfig(**config_dict)
        
        assert restored.assets == original.assets
        assert restored.max_concurrent_assets == original.max_concurrent_assets
        assert restored.global_risk_budget == original.global_risk_budget


class SimpleMockSettings:
    """Simple settings mock that doesn't auto-create attributes."""
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    def __getattr__(self, name):
        raise AttributeError(name)


class TestCrossConfigValidation:
    """Tests for cross-config consistency assertions."""
    
    def create_mock_settings(self, **kwargs) -> SimpleMockSettings:
        """Create a mock settings object with specified attributes."""
        return SimpleMockSettings(**kwargs)
    
    def test_asset_universe_subset_validation(self):
        """Test that local assets must be subset of global universe."""
        config = PortfolioOptimizerConfig(assets=["BTC", "ETH"])
        
        # Valid: assets are subset
        settings = self.create_mock_settings(
            KALSHI_ACTIVE_CRYPTO_ASSETS=["BTC", "ETH", "SOL", "XRP", "DOGE"]
        )
        issues = config.validate_against_global_settings(settings)
        assert len(issues) == 0
        
        # Invalid: local has extra asset - caught at Pydantic validation time
        with pytest.raises(ValidationError) as exc_info:
            PortfolioOptimizerConfig(assets=["BTC", "ETH", "INVALID"])
        assert "Invalid assets" in str(exc_info.value)
    
    def test_max_concurrent_assets_validation(self):
        """Test max_concurrent_assets against global limit."""
        config = PortfolioOptimizerConfig(max_concurrent_assets=5)
        
        # Valid: within global limit
        settings = self.create_mock_settings(MERID_MAX_CONCURRENT_ASSETS=5)
        issues = config.validate_against_global_settings(settings)
        assert len(issues) == 0
        
        # Invalid: exceeds global limit
        settings_low = self.create_mock_settings(MERID_MAX_CONCURRENT_ASSETS=3)
        issues = config.validate_against_global_settings(settings_low)
        assert len(issues) == 1
        assert "global limit" in issues[0]
    
    def test_risk_caps_validation(self):
        """Test risk caps against global order limits."""
        config = PortfolioOptimizerConfig(
            min_risk_usd_per_trade=2.0,
            max_risk_usd_per_trade=4.0
        )
        
        # Valid: within global limits
        settings = self.create_mock_settings(
            MERID_MIN_ORDER_SIZE_USD=1.0,
            MERID_MAX_ORDER_SIZE_USD=5.0
        )
        issues = config.validate_against_global_settings(settings)
        assert len(issues) == 0
        
        # Invalid: exceeds global max
        settings_max = self.create_mock_settings(MERID_MAX_ORDER_SIZE_USD=3.0)
        issues = config.validate_against_global_settings(settings_max)
        assert len(issues) == 1
        assert "global max order" in issues[0]
    
    def test_budget_vs_daily_loss_validation(self):
        """Test global budget against daily loss limit."""
        config = PortfolioOptimizerConfig(global_risk_budget=100.0)
        
        # Valid: within limit
        settings = self.create_mock_settings(MERID_MAX_DAILY_LOSS_USD=200.0)
        issues = config.validate_against_global_settings(settings)
        assert len(issues) == 0
        
        # Invalid: exceeds daily loss
        settings_loss = self.create_mock_settings(MERID_MAX_DAILY_LOSS_USD=50.0)
        issues = config.validate_against_global_settings(settings_loss)
        assert len(issues) == 1
        assert "daily loss limit" in issues[0]
    
    def test_effective_risk_caps_computation(self):
        """Test that effective caps merge config with global settings."""
        config = PortfolioOptimizerConfig(
            min_risk_usd_per_trade=1.0,
            max_risk_usd_per_trade=5.0
        )
        
        settings = self.create_mock_settings(
            MERID_MIN_ORDER_SIZE_USD=2.0,
            MERID_MAX_ORDER_SIZE_USD=4.0
        )
        
        effective = config.compute_effective_risk_caps(settings)
        
        # Effective min = max(local, global) = max(1, 2) = 2
        assert effective["min_risk_usd_per_trade"] == 2.0
        # Effective max = min(local, global) = min(5, 4) = 4
        assert effective["max_risk_usd_per_trade"] == 4.0
    
    def test_validate_config_consistency_passes(self):
        """Test that valid config passes consistency check."""
        config = PortfolioOptimizerConfig(
            assets=["BTC", "ETH", "SOL"],
            max_concurrent_assets=2,
            min_risk_usd_per_trade=1.0,
            max_risk_usd_per_trade=3.0,
            global_risk_budget=6.0,
            lookback_days=30
        )
        
        settings = self.create_mock_settings()
        
        # Should not raise
        validate_config_consistency(config, settings)
    
    def test_validate_config_consistency_fails_on_bad_assets(self):
        """Test that bad asset list fails validation at initialization."""
        # Bad assets are caught at Pydantic validation time
        with pytest.raises(ValidationError) as exc_info:
            PortfolioOptimizerConfig(assets=["BTC", "INVALID_ASSET"])
        assert "Invalid assets" in str(exc_info.value) or "INVALID_ASSET" in str(exc_info.value)
    
    def test_validate_config_consistency_fails_on_cardinality(self):
        """Test that cardinality violation fails consistency check."""
        config = PortfolioOptimizerConfig(
            assets=["BTC", "ETH"],
            max_concurrent_assets=5  # More than available assets
        )
        
        settings = self.create_mock_settings()
        
        with pytest.raises(ConfigValidationError) as exc_info:
            validate_config_consistency(config, settings)
        
        assert "number of assets" in str(exc_info.value)
    
    def test_validate_config_consistency_fails_on_risk_range(self):
        """Test that inverted risk range fails at Pydantic validation."""
        # Inverted risk range is caught at Pydantic validation time
        with pytest.raises(ValidationError) as exc_info:
            PortfolioOptimizerConfig(
                min_risk_usd_per_trade=5.0,
                max_risk_usd_per_trade=3.0
            )
        assert "max_risk_usd_per_trade" in str(exc_info.value)
        assert "min_risk_usd_per_trade" in str(exc_info.value)
    
    def test_validate_config_consistency_warns_short_lookback(self):
        """Test that very short lookback generates warning."""
        config = PortfolioOptimizerConfig(lookback_days=5)
        
        settings = self.create_mock_settings()
        
        with pytest.raises(ConfigValidationError) as exc_info:
            validate_config_consistency(config, settings)
        
        assert "lookback_days" in str(exc_info.value)
        assert "unstable" in str(exc_info.value).lower()


class TestRuntimeWiring:
    """Tests for runtime integration and wiring."""
    
    def test_to_optimizer_dict(self):
        """Test conversion to optimizer constructor dict."""
        config = PortfolioOptimizerConfig(
            assets=["BTC", "ETH"],
            max_concurrent_assets=2,
            global_risk_budget=6.0
        )
        
        opt_dict = config.to_optimizer_dict()
        
        assert opt_dict["assets"] == ["BTC", "ETH"]
        assert opt_dict["max_concurrent_assets"] == 2
        assert opt_dict["global_risk_budget"] == 6.0
        assert "rebalance" not in opt_dict  # Should be filtered
    
    def test_disabled_optimizer_bypass(self):
        """Test that disabled optimizer can be detected."""
        config = PortfolioOptimizerConfig(enabled=False)
        
        assert not config.enabled
        
        # When disabled, high-level callers should bypass
        # Check the config object directly
        assert config.enabled is False
    
    def test_config_file_location(self, tmp_path):
        """Test that config file is loaded from expected location."""
        yaml_content = """
portfolio_optimizer:
  enabled: true
  max_concurrent_assets: 2
"""
        config_file = tmp_path / "portfolio_optimizer.yaml"
        config_file.write_text(yaml_content)
        
        config = load_portfolio_config(str(config_file))
        
        assert config.max_concurrent_assets == 2
    
    def test_yaml_lint_portfolio_config(self, tmp_path):
        """Test that portfolio_optimizer.yaml is valid YAML."""
        # Find the actual config directory
        base_dir = Path(__file__).resolve().parent.parent.parent
        config_dir = base_dir / "config"
        
        # Test our own config file
        portfolio_config = config_dir / "portfolio_optimizer.yaml"
        if portfolio_config.exists():
            with open(portfolio_config, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f)
            assert "portfolio_optimizer" in content or "enabled" in content
        else:
            pytest.skip("portfolio_optimizer.yaml not found")


class TestIntegrationWithSettings:
    """Integration tests with actual MERID settings."""
    
    @pytest.mark.skipif(
        not os.path.exists("merid/settings.py"),
        reason="MERID settings not available"
    )
    def test_config_against_real_settings(self):
        """Test loading config against real MERID settings."""
        try:
            from merid.settings import settings
            
            config = load_portfolio_config()
            issues = config.validate_against_global_settings(settings)
            
            # Log issues but don't fail - this is informational
            for issue in issues:
                print(f"Config validation issue: {issue}")
            
            # Should be able to compute effective caps
            effective = config.compute_effective_risk_caps(settings)
            assert "min_risk_usd_per_trade" in effective
            assert "max_risk_usd_per_trade" in effective
            
        except ImportError:
            pytest.skip("Settings import failed")


class TestEdgeCases:
    """Edge case tests."""
    
    def test_empty_assets_list(self):
        """Test that empty assets list is allowed (uses default)."""
        # Empty list is valid - will be treated as empty asset selection
        config = PortfolioOptimizerConfig(assets=[])
        assert config.assets == []  # Empty is allowed, config valid but non-functional
    
    def test_single_asset_config(self):
        """Test config with single asset."""
        config = PortfolioOptimizerConfig(
            assets=["BTC"],
            max_concurrent_assets=1
        )
        
        assert config.assets == ["BTC"]
        assert config.max_concurrent_assets == 1
    
    def test_all_five_assets(self):
        """Test config with all five crypto assets."""
        config = PortfolioOptimizerConfig(assets=ACTIVE_CRYPTO_ASSETS.copy())
        
        assert len(config.assets) == 5
        assert set(config.assets) == set(ACTIVE_CRYPTO_ASSETS)
    
    def test_zero_risk_free_rate(self):
        """Test that zero risk-free rate is allowed."""
        config = PortfolioOptimizerConfig(risk_free_rate=0.0)
        
        assert config.risk_free_rate == 0.0
    
    def test_negative_risk_free_rate(self):
        """Test negative risk-free rate (rare but valid)."""
        config = PortfolioOptimizerConfig(risk_free_rate=-0.01)
        
        assert config.risk_free_rate == -0.01
    
    def test_very_long_lookback(self):
        """Test that long lookback is allowed (up to 365 days)."""
        config = PortfolioOptimizerConfig(lookback_days=365)
        
        assert config.lookback_days == 365
    
    def test_lookback_too_long(self):
        """Test that lookback > 365 is rejected."""
        with pytest.raises(ValidationError):
            PortfolioOptimizerConfig(lookback_days=366)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
