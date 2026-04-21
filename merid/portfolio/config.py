"""
Portfolio Optimizer Configuration Module

Provides Pydantic-based configuration validation, YAML loading, and
cross-config consistency checks with MERID global settings.

Usage:
    from merid.portfolio.config import PortfolioOptimizerConfig, load_portfolio_config
    
    # Load and validate
    config = load_portfolio_config("config/portfolio_optimizer.yaml")
    
    # Check consistency with global settings
    from merid.settings import settings
    issues = config.validate_against_global_settings(settings)
    if issues:
        raise ConfigValidationError(f"Config inconsistent: {issues}")
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, field_validator, ValidationError

from utils.logger import get_logger
from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS

logger = get_logger("merid.portfolio.config")


class PortfolioOptimizerConfig(BaseModel):
    """
    Pydantic model for portfolio optimizer configuration.
    
    All fields have defaults matching the YAML config file.
    """
    
    enabled: bool = Field(
        default=True,
        description="Master switch for portfolio optimizer"
    )
    
    assets: List[str] = Field(
        default_factory=lambda: ACTIVE_CRYPTO_ASSETS.copy(),
        description="Asset universe for optimization"
    )
    
    max_concurrent_assets: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Maximum number of concurrent positions (cardinality constraint)"
    )
    
    min_risk_usd_per_trade: float = Field(
        default=1.0,
        ge=0,
        description="Minimum risk allocation per trade in USD"
    )
    
    max_risk_usd_per_trade: float = Field(
        default=3.0,
        ge=0,
        description="Maximum risk allocation per trade in USD"
    )
    
    global_risk_budget: float = Field(
        default=9.0,
        ge=0,
        description="Total portfolio risk budget in USD"
    )
    
    risk_free_rate: float = Field(
        default=0.0,
        description="Annual risk-free rate for Sharpe calculation"
    )
    
    lookback_days: int = Field(
        default=60,
        ge=1,
        le=365,
        description="Historical lookback period in days"
    )
    
    num_frontier_points: int = Field(
        default=50,
        ge=10,
        le=200,
        description="Number of points on efficient frontier"
    )
    
    objective: str = Field(
        default="sharpe",
        pattern="^(sharpe|return|return_per_vol)$",
        description="Optimization objective function"
    )
    
    # Nested config sections
    rebalance: Dict[str, Any] = Field(
        default_factory=lambda: {
            "weight_tolerance": 0.05,
            "check_interval_cycles": 10,
            "min_minutes_between_rebalances": 30
        },
        description="Rebalance behavior settings"
    )
    
    data: Dict[str, Any] = Field(
        default_factory=lambda: {
            "primary_source": "kalshi_cache",
            "fallback_to_synthetic": True,
            "cache_ttl_seconds": 300
        },
        description="Data source configuration"
    )
    
    merid_integration: Dict[str, Any] = Field(
        default_factory=lambda: {
            "gate_trades": True,
            "allowed_assets_only": True,
            "audit_optimizations": True,
            "emit_metrics": True
        },
        description="MERID system integration settings"
    )
    
    @field_validator("assets")
    def validate_assets(cls, v: List[str]) -> List[str]:
        """Ensure all assets are in the allowed crypto universe."""
        invalid = set(v) - set(ACTIVE_CRYPTO_ASSETS)
        if invalid:
            raise ValueError(f"Invalid assets: {invalid}. Must be subset of {ACTIVE_CRYPTO_ASSETS}")
        return v
    
    @field_validator("max_risk_usd_per_trade")
    def validate_risk_range(cls, v: float, info) -> float:
        """Ensure max risk is greater than min risk."""
        # Get min_risk from already validated data
        data = info.data
        min_risk = data.get("min_risk_usd_per_trade", 1.0)
        if v < min_risk:
            raise ValueError(f"max_risk_usd_per_trade ({v}) must be >= min_risk_usd_per_trade ({min_risk})")
        return v
    
    @field_validator("global_risk_budget")
    def validate_budget_consistency(cls, v: float, info) -> float:
        """Ensure budget is consistent with max assets and per-trade caps."""
        data = info.data
        max_assets = data.get("max_concurrent_assets", 3)
        max_risk = data.get("max_risk_usd_per_trade", 3.0)
        min_budget = max_assets * 1.0  # Minimum $1 per asset
        max_budget = max_assets * max_risk
        
        if v < min_budget:
            raise ValueError(f"global_risk_budget ({v}) must be >= {min_budget} (max_assets * $1 minimum)")
        if v > max_budget * 2:  # Allow some headroom but not crazy
            logger.warning(f"global_risk_budget ({v}) is > 2x the theoretical max ({max_budget})")
        return v
    
    def validate_against_global_settings(self, settings: Any) -> List[str]:
        """
        Validate this config against MERID global settings.
        
        Args:
            settings: MERID settings object (from merid.settings)
        
        Returns:
            List of validation issues (empty if valid)
        """
        issues = []
        
        # Check asset universe alignment
        if hasattr(settings, "KALSHI_ACTIVE_CRYPTO_ASSETS"):
            global_assets = set(settings.KALSHI_ACTIVE_CRYPTO_ASSETS)
            local_assets = set(self.assets)
            if not local_assets <= global_assets:
                extra = local_assets - global_assets
                issues.append(f"Optimizer assets {extra} not in global universe")
        
        # Check concurrent asset limit against global
        if hasattr(settings, "MERID_MAX_CONCURRENT_ASSETS"):
            global_max = settings.MERID_MAX_CONCURRENT_ASSETS
            if self.max_concurrent_assets > global_max:
                issues.append(
                    f"max_concurrent_assets ({self.max_concurrent_assets}) > "
                    f"global limit ({global_max})"
                )
        
        # Check risk caps against global
        if hasattr(settings, "MERID_MAX_ORDER_SIZE_USD"):
            global_max_order = settings.MERID_MAX_ORDER_SIZE_USD
            if self.max_risk_usd_per_trade > global_max_order:
                issues.append(
                    f"max_risk_usd_per_trade (${self.max_risk_usd_per_trade}) > "
                    f"global max order (${global_max_order})"
                )
        
        if hasattr(settings, "MERID_MIN_ORDER_SIZE_USD"):
            global_min_order = settings.MERID_MIN_ORDER_SIZE_USD
            if self.min_risk_usd_per_trade < global_min_order:
                issues.append(
                    f"min_risk_usd_per_trade (${self.min_risk_usd_per_trade}) < "
                    f"global min order (${global_min_order})"
                )
        
        # Check global risk budget against daily loss limit
        if hasattr(settings, "MERID_MAX_DAILY_LOSS_USD"):
            daily_loss_limit = settings.MERID_MAX_DAILY_LOSS_USD
            if self.global_risk_budget > daily_loss_limit:
                issues.append(
                    f"global_risk_budget (${self.global_risk_budget}) > "
                    f"daily loss limit (${daily_loss_limit})"
                )
        
        return issues
    
    def compute_effective_risk_caps(self, settings: Any) -> Dict[str, float]:
        """
        Compute effective risk caps by merging with global settings.
        
        This provides a single source of truth when multiple configs
        define overlapping risk parameters.
        
        Args:
            settings: MERID global settings
        
        Returns:
            Dict with effective min/max risk USD per trade
        """
        effective_min = self.min_risk_usd_per_trade
        effective_max = self.max_risk_usd_per_trade
        
        # Apply global constraints if they exist
        if hasattr(settings, "MERID_MIN_ORDER_SIZE_USD"):
            global_min = settings.MERID_MIN_ORDER_SIZE_USD
            effective_min = max(effective_min, global_min)
        
        if hasattr(settings, "MERID_MAX_ORDER_SIZE_USD"):
            global_max = settings.MERID_MAX_ORDER_SIZE_USD
            effective_max = min(effective_max, global_max)
        
        # Ensure min <= max after merging
        if effective_min > effective_max:
            logger.warning(
                f"Effective min ({effective_min}) > max ({effective_max}) after merge, "
                f"using max for both"
            )
            effective_min = effective_max
        
        return {
            "min_risk_usd_per_trade": effective_min,
            "max_risk_usd_per_trade": effective_max,
        }
    
    def to_optimizer_dict(self) -> Dict[str, Any]:
        """Convert to dict suitable for PortfolioOptimizer constructor."""
        return {
            "assets": self.assets.copy(),
            "max_concurrent_assets": self.max_concurrent_assets,
            "min_risk_usd_per_trade": self.min_risk_usd_per_trade,
            "max_risk_usd_per_trade": self.max_risk_usd_per_trade,
            "global_risk_budget": self.global_risk_budget,
            "risk_free_rate": self.risk_free_rate,
            "lookback_days": self.lookback_days,
            "num_frontier_points": self.num_frontier_points,
            "objective": self.objective,
            "_validated": True,  # Runtime invariant marker
        }


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""
    pass


def load_portfolio_config(
    path: Optional[str] = None,
    env: Optional[str] = None
) -> PortfolioOptimizerConfig:
    """
    Load portfolio optimizer config from YAML file.
    
    Args:
        path: Path to YAML file (default: config/portfolio_optimizer.yaml)
        env: Environment profile to apply (default: from MERID_ENV)
    
    Returns:
        Validated PortfolioOptimizerConfig
    
    Raises:
        ConfigValidationError: If YAML is invalid or config fails validation
    """
    import yaml
    
    if path is None:
        # Find relative to this file
        base_dir = Path(__file__).resolve().parent.parent.parent
        path = base_dir / "config" / "portfolio_optimizer.yaml"
    else:
        path = Path(path)
    
    if not path.exists():
        logger.warning(f"Config file not found: {path}, using defaults")
        return PortfolioOptimizerConfig()
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigValidationError(f"Invalid YAML in {path}: {e}")
    except Exception as e:
        raise ConfigValidationError(f"Failed to read {path}: {e}")
    
    if raw_config is None:
        logger.warning(f"Empty config file: {path}, using defaults")
        return PortfolioOptimizerConfig()
    
    # Extract portfolio_optimizer section if present
    if "portfolio_optimizer" in raw_config:
        config_dict = raw_config["portfolio_optimizer"]
    else:
        config_dict = raw_config
    
    # Apply environment profile if specified
    env = env or os.environ.get("MERID_ENV", "development")
    if "profiles" in raw_config and env in raw_config["profiles"]:
        profile = raw_config["profiles"][env].get("portfolio_optimizer", {})
        # Merge profile into base config
        config_dict = {**config_dict, **profile}
        logger.debug(f"Applied {env} profile to portfolio optimizer config")
    
    # Validate and create config
    try:
        config = PortfolioOptimizerConfig(**config_dict)
    except ValidationError as e:
        raise ConfigValidationError(f"Config validation failed: {e}")
    
    logger.info(f"Loaded portfolio optimizer config from {path}")
    return config


def validate_config_consistency(
    portfolio_config: PortfolioOptimizerConfig,
    settings: Any
) -> None:
    """
    Central validation function that runs at startup.
    
    Validates portfolio optimizer config against global MERID settings
    and raises clear exceptions before the event loop starts.
    
    Args:
        portfolio_config: The portfolio optimizer configuration
        settings: MERID global settings
    
    Raises:
        ConfigValidationError: If any validation check fails
    """
    issues = []
    
    # 1. Validate against global settings
    setting_issues = portfolio_config.validate_against_global_settings(settings)
    issues.extend(setting_issues)
    
    # 2. Asset universe alignment
    global_assets = set(ACTIVE_CRYPTO_ASSETS)
    local_assets = set(portfolio_config.assets)
    
    if not local_assets <= global_assets:
        extra = local_assets - global_assets
        issues.append(f"Assets not in global universe: {extra}")
    
    # 3. Cardinality constraints
    if portfolio_config.max_concurrent_assets > len(portfolio_config.assets):
        issues.append(
            f"max_concurrent_assets ({portfolio_config.max_concurrent_assets}) > "
            f"number of assets ({len(portfolio_config.assets)})"
        )
    
    # 4. Risk cap consistency
    if portfolio_config.min_risk_usd_per_trade > portfolio_config.max_risk_usd_per_trade:
        issues.append(
            f"min_risk_usd_per_trade ({portfolio_config.min_risk_usd_per_trade}) > "
            f"max_risk_usd_per_trade ({portfolio_config.max_risk_usd_per_trade})"
        )
    
    # 5. Budget consistency
    theoretical_max = (
        portfolio_config.max_concurrent_assets * 
        portfolio_config.max_risk_usd_per_trade
    )
    if portfolio_config.global_risk_budget < portfolio_config.max_concurrent_assets:
        issues.append(
            f"global_risk_budget ({portfolio_config.global_risk_budget}) < "
            f"max_concurrent_assets ({portfolio_config.max_concurrent_assets})"
        )
    
    # 6. Lookback sanity
    if portfolio_config.lookback_days < 7:
        issues.append(
            f"lookback_days ({portfolio_config.lookback_days}) is very short, "
            f"may produce unstable estimates"
        )
    
    # Raise if any issues
    if issues:
        raise ConfigValidationError(
            f"Portfolio optimizer config validation failed:\n" +
            "\n".join(f"  - {issue}" for issue in issues)
        )
    
    logger.info("Portfolio optimizer config validated successfully")


def get_effective_config(settings: Optional[Any] = None) -> PortfolioOptimizerConfig:
    """
    Get effective portfolio optimizer config with all merging applied.
    
    This is the main entry point for production code.
    
    Args:
        settings: MERID settings (auto-loaded if None)
    
    Returns:
        Validated and merged PortfolioOptimizerConfig
    """
    if settings is None:
        from merid.settings import settings
    
    # Load from YAML
    config = load_portfolio_config()
    
    # Validate consistency
    validate_config_consistency(config, settings)
    
    return config
