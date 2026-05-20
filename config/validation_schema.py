"""Configuration validation schema for MERID.

Provides schema validation for profile-based configuration using Pydantic.
Ensures configuration files are valid before loading.

Usage::
    from config.validation_schema import validate_profile_config, ValidationError
    
    try:
        config = validate_profile_config("config/profiles/kalshi_crypto_15m.yaml")
        print("Configuration is valid")
    except ValidationError as e:
        print(f"Configuration errors: {e}")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class TradingModeConfig(BaseModel):
    """Trading mode configuration."""
    mode: str = Field(..., description="Trading mode: paper or live")
    allow_live_trades: bool = Field(default=False, description="Allow live trades")
    
    @field_validator('mode')
    @classmethod
    def validate_mode(cls, v):
        valid_modes = ['paper', 'live', 'backtest']
        if v not in valid_modes:
            raise ValueError(f"mode must be one of {valid_modes}, got '{v}'")
        return v


class RiskLimitsConfig(BaseModel):
    """Risk limits configuration."""
    max_cycle_risk_pct: float = Field(default=0.03, ge=0, le=1, description="Max cycle risk as percentage of equity")
    max_total_risk_pct: float = Field(default=0.08, ge=0, le=1, description="Max total risk as percentage of equity")
    max_daily_loss_cents: int = Field(default=5000, ge=0, description="Max daily loss in cents")
    max_weekly_loss_cents: int = Field(default=15000, ge=0, description="Max weekly loss in cents")
    max_drawdown_pct: float = Field(default=0.12, ge=0, le=1, description="Max drawdown as percentage")
    
    @field_validator('max_cycle_risk_pct', 'max_total_risk_pct')
    @classmethod
    def validate_risk_percentages(cls, v):
        if v <= 0 or v > 1:
            raise ValueError(f"Risk percentage must be between 0 and 1, got {v}")
        return v


class AgentConfig(BaseModel):
    """Agent configuration."""
    enabled: bool = Field(default=True, description="Whether agent is enabled")
    agent_id: str = Field(..., description="Agent identifier")
    agent_name: str = Field(..., description="Human-readable agent name")
    category: str = Field(..., description="Agent category")
    timeframe: str = Field(..., description="Agent timeframe")
    asset: str = Field(..., description="Asset class")
    
    @field_validator('timeframe')
    @classmethod
    def validate_timeframe(cls, v):
        valid_timeframes = ['15m', '1h', '1d', '1w', '4h']
        if v not in valid_timeframes:
            raise ValueError(f"timeframe must be one of {valid_timeframes}, got '{v}'")
        return v


class ProfileConfig(BaseModel):
    """Profile configuration schema."""
    profile_name: str = Field(..., description="Profile name")
    profile_version: str = Field(default="1.0.0", description="Profile version")
    
    trading_mode: TradingModeConfig = Field(..., description="Trading mode configuration")
    risk_limits: RiskLimitsConfig = Field(..., description="Risk limits configuration")
    agents: List[AgentConfig] = Field(default_factory=list, description="Agent configurations")
    
    @field_validator('profile_name')
    @classmethod
    def validate_profile_name(cls, v):
        if not v or not v.strip():
            raise ValueError("profile_name cannot be empty")
        return v.strip()


def validate_profile_config(config_path: str | Path) -> ProfileConfig:
    """Validate a profile configuration file.
    
    Args:
        config_path: Path to YAML configuration file
        
    Returns:
        Validated ProfileConfig object
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        ValidationError: If configuration is invalid
        ValueError: If YAML parsing fails
    """
    import yaml
    
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    
    try:
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse YAML: {e}")
    
    try:
        return ProfileConfig(**config_data)
    except Exception as e:
        from pydantic import ValidationError as PydanticValidationError
        if isinstance(e, PydanticValidationError):
            raise ValidationError(f"Configuration validation failed: {e}")
        raise


def validate_agent_config(config_path: str | Path) -> AgentConfig:
    """Validate an agent configuration file.
    
    Args:
        config_path: Path to YAML configuration file
        
    Returns:
        Validated AgentConfig object
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        ValidationError: If configuration is invalid
        ValueError: If YAML parsing fails
    """
    import yaml
    
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    
    try:
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse YAML: {e}")
    
    try:
        return AgentConfig(**config_data)
    except Exception as e:
        from pydantic import ValidationError as PydanticValidationError
        if isinstance(e, PydanticValidationError):
            raise ValidationError(f"Configuration validation failed: {e}")
        raise


class ValidationError(Exception):
    """Configuration validation error."""
    pass


def validate_all_profiles(profiles_dir: str | Path) -> Dict[str, ProfileConfig]:
    """Validate all profile configurations in a directory.
    
    Args:
        profiles_dir: Directory containing profile YAML files
        
    Returns:
        Dictionary mapping profile names to validated configs
        
    Raises:
        ValidationError: If any profile is invalid
    """
    profiles_dir = Path(profiles_dir)
    if not profiles_dir.exists():
        raise FileNotFoundError(f"Profiles directory not found: {profiles_dir}")
    
    configs = {}
    errors = []
    
    for profile_file in profiles_dir.glob("*.yaml"):
        try:
            config = validate_profile_config(profile_file)
            configs[config.profile_name] = config
        except ValidationError as e:
            errors.append(f"{profile_file.name}: {e}")
    
    if errors:
        raise ValidationError(f"Profile validation errors:\n" + "\n".join(errors))
    
    return configs


# ── Validation Helpers ───────────────────────────────────────────────────────

def check_profile_consistency(config: ProfileConfig) -> List[str]:
    """Check consistency of a profile configuration.
    
    Returns list of warnings (not errors).
    """
    warnings = []
    
    # Check if risk limits are reasonable
    if config.risk_limits.max_cycle_risk_pct > config.risk_limits.max_total_risk_pct:
        warnings.append(
            f"max_cycle_risk_pct ({config.risk_limits.max_cycle_risk_pct}) "
            f"should not exceed max_total_risk_pct ({config.risk_limits.max_total_risk_pct})"
        )
    
    # Check if daily loss is reasonable relative to equity
    # (This is a heuristic check, assumes equity ~$35 for paper mode)
    if config.risk_limits.max_daily_loss_cents > 10000:  # $100
        warnings.append(
            f"max_daily_loss_cents ({config.risk_limits.max_daily_loss_cents}) "
            f"seems high for typical equity"
        )
    
    # Check if any agents are disabled
    disabled_agents = [a for a in config.agents if not a.enabled]
    if disabled_agents:
        warnings.append(
            f"{len(disabled_agents)} agents are disabled: "
            f"{', '.join(a.agent_id for a in disabled_agents)}"
        )
    
    return warnings


def validate_and_report(config_path: str | Path) -> None:
    """Validate configuration and print a report.
    
    Args:
        config_path: Path to configuration file
    """
    try:
        config = validate_profile_config(config_path)
        print(f"✓ Configuration valid: {config.profile_name} v{config.profile_version}")
        
        warnings = check_profile_consistency(config)
        if warnings:
            print("\nWarnings:")
            for warning in warnings:
                print(f"  - {warning}")
        else:
            print("\nNo consistency warnings")
            
    except ValidationError as e:
        print(f"✗ Configuration invalid: {e}")
    except FileNotFoundError as e:
        print(f"✗ File not found: {e}")
