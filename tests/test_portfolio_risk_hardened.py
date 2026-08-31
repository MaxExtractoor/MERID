import pytest
import asyncio
import os
from decimal import Decimal
from datetime import datetime, timezone
from merid.prediction.portfolio_risk_agent import PortfolioRiskAgent, PortfolioSnapshot
from merid.prediction.agent_grid_config import PortfolioRiskConfig
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def _seed_portfolio_bankroll():
    """Provide a $50k settings-derived bankroll for these regression tests.

    The live bankroll service is not available in unit tests, so we seed the
    settings-derived fallback that the portfolio-risk summary uses.
    """
    from merid.settings import settings
    original = settings.KALSHI_PORTFOLIO_BANKROLL_CENTS
    settings.KALSHI_PORTFOLIO_BANKROLL_CENTS = 5_000_000
    yield
    settings.KALSHI_PORTFOLIO_BANKROLL_CENTS = original


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
        assert settings.kalshi_portfolio_max_daily_loss_cents == 1_000_000  # 20% of $50K = $10K
        assert settings.kalshi_portfolio_max_per_asset_cents == 800_000  # 16% of $50K = $8K

    @patch("merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync")
    def test_portfolio_risk_config_post_init_derives_correctly(self, mock_get_equity):
        """PortfolioRiskConfig.__post_init__ should compute from live bankroll when zeros passed."""
        # Uses a $50,000 live-equity fixture so the bankroll path is exercised.
        mock_get_equity.return_value = 50000.0

        # Create config with zeros (triggers __post_init__ derivation)
        config = PortfolioRiskConfig(
            max_total_notional_usd=Decimal("0"),
            max_daily_loss_usd=Decimal("0"),
            max_notional_per_asset_usd=Decimal("0"),
            max_margin_utilization_pct=Decimal("0"),
            rebalance_check_interval_seconds=0,
        )

        # Verify derivation math (bankroll $50K × unified core.settings percentages)
        # MAX_TOTAL_RISK_PCT=15% ($7.5K), DAILY_LOSS_CAP_PCT=20% ($10K), MAX_CYCLE_RISK_PCT=2% ($1K)
        assert config.max_total_notional_usd == Decimal("7500"), f"Expected $7,500, got ${config.max_total_notional_usd}"
        assert config.max_daily_loss_usd == Decimal("10000"), f"Expected $10,000, got ${config.max_daily_loss_usd}"
        assert config.max_notional_per_asset_usd == Decimal("1000"), f"Expected $1,000, got ${config.max_notional_per_asset_usd}"

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

    @patch("merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync")
    def test_summary_includes_bankroll_and_percentages(self, mock_get_equity):
        """Agent.summary() should expose bankroll and percentages for UI verification."""
        # Uses a $50,000 live-equity fixture so the bankroll path is exercised.
        mock_get_equity.return_value = 50000.0

        config = PortfolioRiskConfig(max_total_notional_usd=Decimal("0"))
        agent = PortfolioRiskAgent(config)

        summary = agent.summary()

        # Verify bankroll exposed
        assert "bankroll_cents" in summary["config"], "summary should include bankroll_cents"
        assert summary["config"]["bankroll_cents"] == 5_000_000  # $50K live bankroll

        # Verify percentages exposed for UI (unified core.settings canonical values)
        assert "max_total_notional_pct" in summary["config"], "summary should include max_total_notional_pct"
        assert summary["config"]["max_total_notional_pct"] == 0.15  # MAX_TOTAL_RISK_PCT
        assert "max_daily_loss_pct" in summary["config"], "summary should include max_daily_loss_pct"
        assert summary["config"]["max_daily_loss_pct"] == 0.20  # DAILY_LOSS_CAP_PCT


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
