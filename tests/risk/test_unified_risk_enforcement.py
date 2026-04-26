"""
Pass 8 Tests: Unified Risk Enforcement

Verifies that:
- Global risk > 2% is clamped or rejected
- Fixed USD caps are rejected in LIVE/PAPER
- Max concurrent edges limited to 3
- Per-trade caps are sub-caps that aggregate correctly
"""

import pytest
from unittest.mock import patch, MagicMock
import os

from merid.config.unified_risk_enforcement import (
    enforce_unified_risk_model,
    enforce_at_startup,
    RiskConfigViolationError,
    ABSOLUTE_MAX_CYCLE_RISK_PCT,
    ABSOLUTE_MAX_EDGES_PER_CYCLE,
    ABSOLUTE_MAX_RISK_PER_TRADE_PCT,
)


class TestGlobalRiskCapInvariant:
    """Test 2% global risk cap cannot be exceeded."""
    
    def test_global_risk_clamped_to_2pct_in_sim(self):
        """6% config should be clamped to 2% in SIM mode."""
        with patch("merid.config.unified_risk_enforcement._get_current_trade_mode", return_value="sim"):
            configs = [{"max_risk_pct_global": 0.06}]  # 6% - dangerous
            
            result = enforce_unified_risk_model(configs)
            
            assert result.final_config["max_risk_pct_global"] == 0.02
            assert len(result.violations) > 0
            assert any("clamped" in v.lower() for v in result.violations)
    
    def test_global_risk_rejected_in_live(self):
        """6% config should raise exception in LIVE mode."""
        with patch("merid.config.unified_risk_enforcement._get_current_trade_mode", return_value="live"):
            configs = [{"max_risk_pct_global": 0.06}]
            
            with pytest.raises(RiskConfigViolationError) as exc_info:
                enforce_unified_risk_model(configs)
            
            assert "0.06" in str(exc_info.value)
            assert "exceeds" in str(exc_info.value).lower()
    
    def test_global_risk_accepted_if_under_2pct(self):
        """1.5% config should be accepted."""
        with patch("merid.config.unified_risk_enforcement._get_current_trade_mode", return_value="live"):
            configs = [{"max_risk_pct_global": 0.015}]  # 1.5%
            
            result = enforce_unified_risk_model(configs)
            
            assert result.final_config["max_risk_pct_global"] == 0.015
            assert len([v for v in result.violations if "VIOLATION" in v]) == 0
    
    @pytest.mark.parametrize("mode", ["live", "paper", "LIVE", "PAPER"])
    def test_all_live_variants_reject_high_risk(self, mode):
        """All live/paper mode variants reject >2% global risk."""
        with patch("merid.config.unified_risk_enforcement._get_current_trade_mode", return_value=mode):
            configs = [{"max_risk_pct_global": 0.05}]
            
            with pytest.raises(RiskConfigViolationError):
                enforce_unified_risk_model(configs)


class TestFixedUsdCapInvariant:
    """Test fixed USD caps are rejected in LIVE/PAPER."""
    
    def test_fixed_usd_rejected_in_live(self):
        """max_total_notional_usd should raise in LIVE."""
        with patch("merid.config.unified_risk_enforcement._get_current_trade_mode", return_value="live"):
            configs = [{"max_total_notional_usd": 5000}]
            
            with pytest.raises(RiskConfigViolationError) as exc_info:
                enforce_unified_risk_model(configs)
            
            assert "$5000" in str(exc_info.value) or "5000" in str(exc_info.value)
            assert "percentage" in str(exc_info.value).lower()
    
    def test_fixed_usd_allowed_in_sim(self):
        """Fixed USD allowed in SIM for backtesting."""
        with patch("merid.config.unified_risk_enforcement._get_current_trade_mode", return_value="sim"):
            configs = [{"max_total_notional_usd": 5000}]
            
            result = enforce_unified_risk_model(configs)
            
            # Should have violation notice but not error
            assert len(result.violations) > 0
            assert any("SIM" in v for v in result.violations)
    
    def test_fixed_usd_zero_allowed(self):
        """Zero or None USD cap is acceptable."""
        with patch("merid.config.unified_risk_enforcement._get_current_trade_mode", return_value="live"):
            configs = [{"max_total_notional_usd": 0}]
            
            result = enforce_unified_risk_model(configs)
            
            assert result.success  # Should not raise


class TestMaxEdgesInvariant:
    """Test max 3 concurrent edges invariant."""
    
    def test_max_edges_clamped_to_3_in_live(self):
        """Config with 5 edges should be clamped to 3 in LIVE."""
        with patch("merid.config.unified_risk_enforcement._get_current_trade_mode", return_value="live"):
            configs = [{"max_concurrent_assets": 5}]
            
            result = enforce_unified_risk_model(configs)
            
            assert result.final_config["max_concurrent_assets"] == 3
            assert any("clamped" in v.lower() and "3" in v for v in result.violations)
    
    def test_max_edges_accepted_if_under_3(self):
        """Config with 2 edges should be accepted."""
        with patch("merid.config.unified_risk_enforcement._get_current_trade_mode", return_value="live"):
            configs = [{"max_concurrent_assets": 2}]
            
            result = enforce_unified_risk_model(configs)
            
            assert result.final_config["max_concurrent_assets"] == 2
    
    def test_max_edges_exactly_3_accepted(self):
        """Config with exactly 3 edges should be accepted."""
        with patch("merid.config.unified_risk_enforcement._get_current_trade_mode", return_value="live"):
            configs = [{"max_concurrent_assets": 3}]
            
            result = enforce_unified_risk_model(configs)
            
            assert result.final_config["max_concurrent_assets"] == 3


class TestPerTradeCapInvariant:
    """Test per-trade sub-caps aggregate correctly."""
    
    def test_per_trade_clamped_when_over_1pct(self):
        """2% per-trade should be clamped to 1% (sub-cap)."""
        with patch("merid.config.unified_risk_enforcement._get_current_trade_mode", return_value="live"):
            configs = [{"max_risk_pct_per_trade": 0.02}]  # 2% per trade
            
            result = enforce_unified_risk_model(configs)
            
            # Should be clamped to 1%
            assert result.final_config["max_risk_pct_per_trade"] <= 0.01
    
    def test_per_trade_accepted_when_under_1pct(self):
        """0.5% per-trade should be accepted."""
        with patch("merid.config.unified_risk_enforcement._get_current_trade_mode", return_value="live"):
            configs = [{"max_risk_pct_per_trade": 0.005}]
            
            result = enforce_unified_risk_model(configs)
            
            assert result.final_config["max_risk_pct_per_trade"] == 0.005


class TestMultiSourceConfigMerge:
    """Test merging configs from multiple sources."""
    
    def test_highest_risk_from_multiple_sources(self):
        """If one source has 6%, detect and reject/clamp."""
        with patch("merid.config.unified_risk_enforcement._get_current_trade_mode", return_value="live"):
            # Put dangerous config first so it's detected
            configs = [
                {"max_risk_pct_global": 0.06},  # Dangerous - will be checked first
                {"max_risk_pct_global": 0.02},  # Good
            ]
            
            with pytest.raises(RiskConfigViolationError):
                enforce_unified_risk_model(configs)
    
    def test_env_var_takes_precedence(self):
        """Environment variables should be checked."""
        with patch("merid.config.unified_risk_enforcement._get_current_trade_mode", return_value="live"):
            with patch.dict(os.environ, {"MAX_RISK_PCT_GLOBAL": "0.05"}):
                with pytest.raises(RiskConfigViolationError):
                    enforce_unified_risk_model()  # Uses env


class TestStartupEnforcement:
    """Test enforcement at application startup."""
    
    def test_startup_logs_success(self, caplog):
        """Successful enforcement should be logged."""
        import logging
        
        with patch("merid.config.unified_risk_enforcement._get_current_trade_mode", return_value="live"):
            configs = [{"max_risk_pct_global": 0.015}]  # Safe config
            
            with caplog.at_level(logging.INFO):
                enforce_at_startup()
            
            # Should log success
            assert any("enforced successfully" in record.message.lower() or
                       "PASS8" in record.message
                       for record in caplog.records)
    
    def test_startup_fails_on_violation(self):
        """Startup should fail hard on config violation."""
        with patch("merid.config.unified_risk_enforcement._get_current_trade_mode", return_value="live"):
            with patch("merid.config.unified_risk_enforcement._load_default_risk_configs", 
                      return_value=[{"max_risk_pct_global": 0.06}]):
                
                with pytest.raises(RiskConfigViolationError):
                    enforce_at_startup()


class TestEnforcementResultStructure:
    """Test result structure is correct."""
    
    def test_result_has_all_fields(self):
        """Result should have success, violations, clamped_values, final_config."""
        with patch("merid.config.unified_risk_enforcement._get_current_trade_mode", return_value="sim"):
            configs = [{"max_risk_pct_global": 0.06}]
            
            result = enforce_unified_risk_model(configs)
            
            assert hasattr(result, 'success')
            assert hasattr(result, 'violations')
            assert hasattr(result, 'clamped_values')
            assert hasattr(result, 'final_config')
            assert isinstance(result.violations, list)
            assert isinstance(result.clamped_values, dict)
            assert isinstance(result.final_config, dict)
