import pytest
import asyncio
import os
from decimal import Decimal
from datetime import datetime, timezone
from merid.prediction.portfolio_risk_agent import PortfolioRiskAgent, PortfolioSnapshot
from merid.prediction.agent_grid_config import PortfolioRiskConfig
from unittest.mock import MagicMock, patch


class TestPortfolioRiskConfigBankrollDriven:
    """Regression tests ensuring portfolio risk limits are bankroll-driven, not hardcoded.
    
    These tests prevent drift back to hardcoded $25K/$2K limits by verifying:
    1. Config derives from settings.KALSHI_PORTFOLIO_* env vars
    2. Math is correct: limit = bankroll * percentage
    3. No hardcoded constants leak through
    """

    def test_config_derives_from_settings_bankroll(self):
        """PortfolioRiskConfig with zero values should derive from settings."""
        # Uses actual default settings (bankroll = $50,000)
        from merid.settings import settings
        
        # Verify settings math with actual defaults
        assert settings.KALSHI_PORTFOLIO_BANKROLL_CENTS == 5_000_000  # $50,000 default
        assert settings.kalshi_portfolio_max_notional_cents == 2_500_000  # 50% of $50K = $25K
        assert settings.kalshi_portfolio_max_daily_loss_cents == 500_000  # 10% of $50K = $5K
        assert settings.kalshi_portfolio_max_per_asset_cents == 800_000  # 16% of $50K = $8K

    def test_portfolio_risk_config_post_init_derives_correctly(self):
        """PortfolioRiskConfig.__post_init__ should compute from settings when zeros passed."""
        # Uses actual default settings (bankroll = $50,000)
        # Create config with zeros (triggers __post_init__ derivation)
        config = PortfolioRiskConfig(
            max_total_notional_usd=Decimal("0"),
            max_daily_loss_usd=Decimal("0"),
            max_notional_per_asset_usd=Decimal("0"),
            max_margin_utilization_pct=Decimal("0"),
            rebalance_check_interval_seconds=0,
        )
        
        # Verify derivation math (bankroll $50K × percentages)
        assert config.max_total_notional_usd == Decimal("25000"), f"Expected $25,000, got ${config.max_total_notional_usd}"  # 50% of $50K
        assert config.max_daily_loss_usd == Decimal("5000"), f"Expected $5,000, got ${config.max_daily_loss_usd}"    # 10% of $50K
        assert config.max_notional_per_asset_usd == Decimal("8000"), f"Expected $8,000, got ${config.max_notional_per_asset_usd}"  # 16% of $50K

    def test_explicit_yaml_values_override_settings(self):
        """Explicit non-zero values should take precedence over settings-derived."""
        # Uses actual settings singleton - explicit values should still be preserved
        # Create config with explicit values (should NOT be overridden)
        config = PortfolioRiskConfig(
            max_total_notional_usd=Decimal("15000"),  # Explicit $15K
            max_daily_loss_usd=Decimal("2000"),       # Explicit $2K
        )
        
        # Verify explicit values preserved
        assert config.max_total_notional_usd == Decimal("15000"), "Explicit max_notional should be preserved"
        assert config.max_daily_loss_usd == Decimal("2000"), "Explicit max_daily_loss should be preserved"

    def test_no_hardcoded_25k_or_2k_defaults(self):
        """Ensure PortfolioRiskConfig has no hardcoded literal defaults - should use zeros to trigger derivation."""
        from dataclasses import fields
        
        # Check that default values are zeros (not hardcoded $25K/$2K literals)
        # This ensures derivation from settings is triggered
        for f in fields(PortfolioRiskConfig):
            if f.name == 'max_total_notional_usd':
                assert f.default == Decimal("0"), \
                    f"Hardcoded {f.default} default detected for max_total_notional_usd - should be Decimal('0')"
            elif f.name == 'max_daily_loss_usd':
                assert f.default == Decimal("0"), \
                    f"Hardcoded {f.default} default detected for max_daily_loss_usd - should be Decimal('0')"
            elif f.name == 'max_notional_per_asset_usd':
                assert f.default == Decimal("0"), \
                    f"Hardcoded {f.default} default detected for max_notional_per_asset_usd - should be Decimal('0')"

    def test_summary_includes_bankroll_and_percentages(self):
        """Agent.summary() should expose bankroll and percentages for UI verification."""
        # Uses actual default settings (bankroll = $50,000)
        from merid.settings import settings
        
        config = PortfolioRiskConfig(max_total_notional_usd=Decimal("0"))
        agent = PortfolioRiskAgent(config)
        
        summary = agent.summary()
        
        # Verify bankroll exposed
        assert "bankroll_cents" in summary["config"], "summary should include bankroll_cents"
        assert summary["config"]["bankroll_cents"] == 5_000_000  # Default $50K
        
        # Verify percentages exposed for UI
        assert "max_total_notional_pct" in summary["config"], "summary should include max_total_notional_pct"
        assert summary["config"]["max_total_notional_pct"] == 0.5  # Default 50%
        assert "max_daily_loss_pct" in summary["config"], "summary should include max_daily_loss_pct"
        assert summary["config"]["max_daily_loss_pct"] == 0.1  # Default 10%


@pytest.mark.asyncio
async def test_portfolio_risk_per_asset_limit():
    """Test per-asset notional limit breach detection."""
    config = PortfolioRiskConfig(
        max_notional_per_asset_usd=Decimal("1000"),
        max_total_notional_usd=Decimal("50000"),
    )
    agent = PortfolioRiskAgent(config)
    
    snapshot = PortfolioSnapshot(timestamp=datetime.now(timezone.utc))
    snapshot.notional_per_asset["BTC"] = Decimal("1500")
    
    breaches = agent._check_limits(snapshot)
    
    assert len(breaches) >= 1
    assert any("BTC notional" in b for b in breaches)

@pytest.mark.asyncio
async def test_portfolio_risk_daily_loss_limit():
    """Test daily loss limit breach detection."""
    config = PortfolioRiskConfig(
        max_daily_loss_usd=Decimal("1000"),
        max_total_notional_usd=Decimal("50000"),
    )
    agent = PortfolioRiskAgent(config)
    
    snapshot = PortfolioSnapshot(timestamp=datetime.now(timezone.utc))
    # Daily PnL of -$1500 exceeds max_daily_loss of $1000
    snapshot.daily_pnl_usd = Decimal("-1500")
    
    breaches = agent._check_limits(snapshot)
    
    assert len(breaches) >= 1
    assert any("Daily loss" in b for b in breaches)
