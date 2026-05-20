"""Configuration validation tests."""

import pytest
from pathlib import Path

from config.validation_schema import (
    AgentConfig,
    ProfileConfig,
    RiskLimitsConfig,
    TradingModeConfig,
    ValidationError,
    validate_profile_config,
    validate_agent_config,
    check_profile_consistency,
)


class TestTradingModeConfig:
    """Test TradingModeConfig validation."""
    
    def test_valid_mode(self):
        """Test valid trading mode."""
        config = TradingModeConfig(mode="paper")
        assert config.mode == "paper"
        assert config.allow_live_trades is False
    
    def test_invalid_mode(self):
        """Test invalid trading mode raises error."""
        from pydantic import ValidationError as PydanticValidationError
        with pytest.raises(PydanticValidationError, match="mode must be one of"):
            TradingModeConfig(mode="invalid")
    
    def test_live_mode_with_trades(self):
        """Test live mode with trades enabled."""
        config = TradingModeConfig(mode="live", allow_live_trades=True)
        assert config.mode == "live"
        assert config.allow_live_trades is True


class TestRiskLimitsConfig:
    """Test RiskLimitsConfig validation."""
    
    def test_default_values(self):
        """Test default risk limits."""
        config = RiskLimitsConfig()
        assert config.max_cycle_risk_pct == 0.03
        assert config.max_total_risk_pct == 0.08
        assert config.max_daily_loss_cents == 5000
        assert config.max_weekly_loss_cents == 15000
        assert config.max_drawdown_pct == 0.12
    
    def test_custom_values(self):
        """Test custom risk limits."""
        config = RiskLimitsConfig(
            max_cycle_risk_pct=0.02,
            max_total_risk_pct=0.05,
            max_daily_loss_cents=10000,
        )
        assert config.max_cycle_risk_pct == 0.02
        assert config.max_total_risk_pct == 0.05
        assert config.max_daily_loss_cents == 10000
    
    def test_invalid_percentage(self):
        """Test invalid percentage raises error."""
        from pydantic import ValidationError as PydanticValidationError
        # Pydantic's built-in validation with ge=0, le=1 runs before custom validator
        with pytest.raises(PydanticValidationError, match="Input should be less than or equal to 1"):
            RiskLimitsConfig(max_cycle_risk_pct=1.5)
        
        with pytest.raises(PydanticValidationError, match="Input should be greater than or equal to 0"):
            RiskLimitsConfig(max_cycle_risk_pct=-0.1)


class TestAgentConfig:
    """Test AgentConfig validation."""
    
    def test_valid_config(self):
        """Test valid agent configuration."""
        config = AgentConfig(
            agent_id="kalshi-btc_15m",
            agent_name="BTC 15m Agent",
            category="crypto",
            timeframe="15m",
            asset="BTC",
        )
        assert config.agent_id == "kalshi-btc_15m"
        assert config.enabled is True
        assert config.timeframe == "15m"
    
    def test_disabled_agent(self):
        """Test disabled agent configuration."""
        config = AgentConfig(
            agent_id="kalshi-btc_15m",
            agent_name="BTC 15m Agent",
            category="crypto",
            timeframe="15m",
            asset="BTC",
            enabled=False,
        )
        assert config.enabled is False
    
    def test_invalid_timeframe(self):
        """Test invalid timeframe raises error."""
        with pytest.raises(ValueError, match="timeframe must be one of"):
            AgentConfig(
                agent_id="kalshi-btc_15m",
                agent_name="BTC 15m Agent",
                category="crypto",
                timeframe="invalid",
                asset="BTC",
            )


class TestProfileConfig:
    """Test ProfileConfig validation."""
    
    def test_minimal_config(self):
        """Test minimal profile configuration."""
        config = ProfileConfig(
            profile_name="test_profile",
            trading_mode=TradingModeConfig(mode="paper"),
            risk_limits=RiskLimitsConfig(),
        )
        assert config.profile_name == "test_profile"
        assert config.profile_version == "1.0.0"
        assert len(config.agents) == 0
    
    def test_config_with_agents(self):
        """Test profile configuration with agents."""
        config = ProfileConfig(
            profile_name="test_profile",
            trading_mode=TradingModeConfig(mode="paper"),
            risk_limits=RiskLimitsConfig(),
            agents=[
                AgentConfig(
                    agent_id="kalshi-btc_15m",
                    agent_name="BTC 15m Agent",
                    category="crypto",
                    timeframe="15m",
                    asset="BTC",
                ),
                AgentConfig(
                    agent_id="kalshi-eth_15m",
                    agent_name="ETH 15m Agent",
                    category="crypto",
                    timeframe="15m",
                    asset="ETH",
                ),
            ],
        )
        assert len(config.agents) == 2
    
    def test_empty_profile_name(self):
        """Test empty profile name raises error."""
        from pydantic import ValidationError as PydanticValidationError
        with pytest.raises(PydanticValidationError, match="profile_name cannot be empty"):
            ProfileConfig(
                profile_name="",
                trading_mode=TradingModeConfig(mode="paper"),
                risk_limits=RiskLimitsConfig(),
            )


class TestValidateProfileConfig:
    """Test profile configuration file validation."""
    
    def test_nonexistent_file(self):
        """Test nonexistent file raises error."""
        with pytest.raises(FileNotFoundError):
            validate_profile_config("nonexistent.yaml")
    
    def test_invalid_yaml(self):
        """Test invalid YAML raises error."""
        # Create temporary invalid YAML file
        import tempfile
        import yaml
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("invalid: yaml: content: [unclosed")
            temp_path = f.name
        
        try:
            with pytest.raises(ValueError, match="Failed to parse YAML"):
                validate_profile_config(temp_path)
        finally:
            Path(temp_path).unlink()
    
    def test_invalid_schema(self):
        """Test invalid schema raises error."""
        import tempfile
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("profile_name: test\ntrading_mode:\n  mode: invalid\n")
            temp_path = f.name
        
        try:
            with pytest.raises(ValidationError, match="Configuration validation failed"):
                validate_profile_config(temp_path)
        finally:
            Path(temp_path).unlink()


class TestCheckProfileConsistency:
    """Test profile consistency checks."""
    
    def test_cycle_exceeds_total(self):
        """Test warning when cycle risk exceeds total risk."""
        config = ProfileConfig(
            profile_name="test_profile",
            trading_mode=TradingModeConfig(mode="paper"),
            risk_limits=RiskLimitsConfig(
                max_cycle_risk_pct=0.10,
                max_total_risk_pct=0.05,
            ),
        )
        warnings = check_profile_consistency(config)
        assert len(warnings) == 1
        assert "max_cycle_risk_pct" in warnings[0]
    
    def test_high_daily_loss(self):
        """Test warning for high daily loss."""
        config = ProfileConfig(
            profile_name="test_profile",
            trading_mode=TradingModeConfig(mode="paper"),
            risk_limits=RiskLimitsConfig(
                max_daily_loss_cents=15000,  # $150
            ),
        )
        warnings = check_profile_consistency(config)
        assert len(warnings) == 1
        assert "max_daily_loss_cents" in warnings[0]
    
    def test_disabled_agents_warning(self):
        """Test warning for disabled agents."""
        config = ProfileConfig(
            profile_name="test_profile",
            trading_mode=TradingModeConfig(mode="paper"),
            risk_limits=RiskLimitsConfig(),
            agents=[
                AgentConfig(
                    agent_id="kalshi-btc_15m",
                    agent_name="BTC 15m Agent",
                    category="crypto",
                    timeframe="15m",
                    asset="BTC",
                    enabled=False,
                ),
            ],
        )
        warnings = check_profile_consistency(config)
        assert len(warnings) == 1
        assert "agents are disabled" in warnings[0]
    
    def test_no_warnings(self):
        """Test no warnings for valid configuration."""
        config = ProfileConfig(
            profile_name="test_profile",
            trading_mode=TradingModeConfig(mode="paper"),
            risk_limits=RiskLimitsConfig(),
            agents=[
                AgentConfig(
                    agent_id="kalshi-btc_15m",
                    agent_name="BTC 15m Agent",
                    category="crypto",
                    timeframe="15m",
                    asset="BTC",
                    enabled=True,
                ),
            ],
        )
        warnings = check_profile_consistency(config)
        assert len(warnings) == 0
