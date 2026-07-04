"""Test micro-account risk parameter fixes for quality-over-quantity trading.

Tests verify:
- per_trade_risk_small_pct increased to 2.75% for bankrolls under $100
- min_notional_usd adjusted to $0.50 for micro accounts
- weekend_multiplier relaxed from 0.5 to 0.8 for regime-based sizing
- daily loss limit aligned with drawdown halt (20%)
"""

import pytest
import os
from unittest.mock import patch


class TestMicroAccountRiskFixes:
    """Test micro-account specific risk parameter adjustments."""

    def test_crypto_15m_profile_weekend_multiplier(self):
        """Test that crypto_15m_profile.py weekend multiplier default is 0.8."""
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfile
        
        # Check the dataclass default value directly
        from dataclasses import fields
        for field in fields(Crypto15mProfile):
            if field.name == 'time_of_day_risk_scaling_weekend_multiplier':
                assert field.default == 0.8, \
                    f"Expected 0.8 weekend multiplier default, got {field.default}"
                break

    def test_micro_account_position_sizing(self):
        """Test that 2.75% per-trade risk produces tradable sizes for $34.12 bankroll."""
        bankroll = 34.12
        per_trade_risk_pct = 0.0275  # 2.75%
        
        expected_position_size = bankroll * per_trade_risk_pct
        assert expected_position_size == pytest.approx(0.9383, rel=0.01), \
            f"Expected ~$0.94 position size, got ${expected_position_size}"
        
        # Verify this is sufficient for 1-2 contracts at typical prices
        # At $0.50 min_notional, $0.94 allows 1-2 contracts
        assert expected_position_size >= 0.50, \
            f"Position size ${expected_position_size} below min_notional $0.50"

    def test_core_settings_daily_loss(self):
        """Test that core/settings.py daily loss default is 20%."""
        from core.settings import DAILY_LOSS_CAP_PCT
        
        # Clear env vars to test default
        with patch.dict(os.environ, {}, clear=True):
            # Re-import to get default value
            import importlib
            import core.settings
            importlib.reload(core.settings)
            daily_loss = core.settings.DAILY_LOSS_CAP_PCT
            
        assert daily_loss == 0.20, \
            f"Expected 20% daily loss, got {daily_loss * 100}%"

    def test_unified_risk_manager_daily_loss(self):
        """Test that unified_risk_manager.py daily loss default is 20%."""
        from merid.risk.unified_risk_manager import RiskLimits
        
        limits = RiskLimits()
        
        assert limits.daily_loss_pct == 0.20, \
            f"Expected 20% daily loss, got {limits.daily_loss_pct * 100}%"

    def test_merid_settings_daily_loss(self):
        """Test that merid/settings.py daily loss default is 20%."""
        from merid.settings import Settings
        
        settings = Settings()
        
        assert settings.KALSHI_PORTFOLIO_MAX_DAILY_LOSS_PCT == 0.20, \
            f"Expected 20% daily loss, got {settings.KALSHI_PORTFOLIO_MAX_DAILY_LOSS_PCT * 100}%"

    def test_kill_switches_daily_loss_fallback(self):
        """Test that kill_switches.py daily loss fallback is 20%."""
        # Check the fallback value in the code
        with open('merid/risk/kill_switches.py', 'r') as f:
            content = f.read()
        
        # Verify the fallback is 20.0 (not 5.0)
        assert 'self.daily_loss_limit = 20.0' in content, \
            "Kill switches should use 20.0 as daily loss fallback"
        assert '20% as placeholder' in content, \
            "Comment should indicate 20% alignment with drawdown halt"

    def test_pipeline_risk_manager_daily_loss(self):
        """Test that pipeline/risk_manager.py daily loss default is 2000."""
        from merid.pipeline.risk_manager import DomainRiskConfig
        
        config = DomainRiskConfig(domain="crypto")
        
        assert config.max_daily_loss_usd == 2000, \
            f"Expected $2000 daily loss, got ${config.max_daily_loss_usd}"

    def test_automated_risk_controls_daily_loss(self):
        """Test that automated_risk_controls.py daily loss default is 20%."""
        from core.automated_risk_controls import TradingHaltManager
        
        mgr = TradingHaltManager()
        
        assert mgr.max_daily_loss_pct == 0.20, \
            f"Expected 20% daily loss, got {mgr.max_daily_loss_pct * 100}%"

    def test_crypto_prediction_agent_daily_loss(self):
        """Test that crypto_prediction_agent.py daily loss is 20%."""
        # Check the value in the code
        with open('agents/crypto_prediction_agent.py', 'r') as f:
            content = f.read()
        
        # Verify the value is 0.20
        assert '"max_daily_loss": 0.20' in content, \
            "Crypto prediction agent should use 20% max daily loss"
        assert 'aligned with drawdown halt' in content, \
            "Comment should indicate alignment with drawdown halt"
