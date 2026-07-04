"""
Unit tests for PreTradeRiskChecker.

Tests risk check logic: size limits, exposure limits, frequency limits, daily loss caps.
"""

import pytest
from merid.pipelines.feature_bundle import TradeDecision
from merid.pipelines.pre_trade_risk import PreTradeRiskChecker, RiskCheckResult


class TestPreTradeRiskChecker:
    """Test PreTradeRiskChecker functionality."""
    
    def test_checker_initialization(self):
        """Test checker initialization with custom limits."""
        checker = PreTradeRiskChecker(
            max_size_pct=0.03,
            max_asset_exposure_pct=0.15,
            max_daily_trades=25,
            max_daily_loss_pct=0.08,
        )
        
        assert checker.max_size_pct == 0.03
        assert checker.max_asset_exposure_pct == 0.15
        assert checker.max_daily_trades == 25
        assert checker.max_daily_loss_pct == 0.08
    
    def test_check_decision_pass_all(self):
        """Test decision passes all risk checks."""
        checker = PreTradeRiskChecker()
        
        decision = TradeDecision(
            asset="BTC",
            timeframe="15m",
            side="yes",
            confidence=0.8,
            edge_estimate=0.05,
            size_pct=0.01,  # Within 2% limit
            market_id="KXBTC-15M-2024-01-01",
            pipeline_id="btc_15m_pipeline",
            decision_agent="BTC_15M",
        )
        
        account_state = {
            "asset_exposure": {"BTC": 0.05},  # 5% exposure, under 10% limit
            "daily_trade_count": {"BTC": 5},  # 5 trades, under 20 limit
            "daily_pnl": 0.01,  # 1% profit, over -5% loss cap
        }
        
        result = checker.check_decision(decision, account_state)
        
        assert result.passed is True
        assert result.adjusted_size_pct == decision.size_pct
        assert result.reason == ""
    
    def test_check_max_size_clip(self):
        """Test size is clipped when exceeding max."""
        checker = PreTradeRiskChecker(max_size_pct=0.02)
        
        decision = TradeDecision(
            asset="BTC",
            timeframe="15m",
            side="yes",
            confidence=0.8,
            edge_estimate=0.05,
            size_pct=0.05,  # 5%, exceeds 2% limit
            market_id="KXBTC-15M-2024-01-01",
            pipeline_id="btc_15m_pipeline",
            decision_agent="BTC_15M",
        )
        
        account_state = {}
        
        result = checker.check_decision(decision, account_state)
        
        assert result.passed is False
        assert result.adjusted_size_pct == 0.02  # Clipped to max
        assert "exceeds max" in result.reason
        assert result.check_name == "max_size"
    
    def test_check_asset_exposure_clip(self):
        """Test size is clipped when exposure would exceed limit."""
        checker = PreTradeRiskChecker(max_size_pct=0.10, max_asset_exposure_pct=0.10)
        
        decision = TradeDecision(
            asset="BTC",
            timeframe="15m",
            side="yes",
            confidence=0.8,
            edge_estimate=0.05,
            size_pct=0.08,  # 8% trade
            market_id="KXBTC-15M-2024-01-01",
            pipeline_id="btc_15m_pipeline",
            decision_agent="BTC_15M",
        )
        
        account_state = {
            "asset_exposure": {"BTC": 0.05},  # Already 5% exposed
            # 5% + 8% = 13%, exceeds 10% limit
        }
        
        result = checker.check_decision(decision, account_state)
        
        assert result.passed is False
        assert result.adjusted_size_pct == 0.05  # Clipped to remaining capacity
        assert "exposure" in result.reason.lower()
        assert result.check_name == "asset_exposure"
    
    def test_check_asset_exposure_pass(self):
        """Test passes when exposure within limit."""
        checker = PreTradeRiskChecker(max_size_pct=0.10, max_asset_exposure_pct=0.10)
        
        decision = TradeDecision(
            asset="BTC",
            timeframe="15m",
            side="yes",
            confidence=0.8,
            edge_estimate=0.05,
            size_pct=0.03,
            market_id="KXBTC-15M-2024-01-01",
            pipeline_id="btc_15m_pipeline",
            decision_agent="BTC_15M",
        )
        
        account_state = {
            "asset_exposure": {"BTC": 0.05},
            # 5% + 3% = 8%, under 10% limit
        }
        
        result = checker.check_decision(decision, account_state)
        
        assert result.passed is True
        assert result.check_name == "daily_loss_cap"  # Last check in the list
    
    def test_check_frequency_limit_veto(self):
        """Test veto when daily trade limit exceeded."""
        checker = PreTradeRiskChecker(max_daily_trades=20)
        
        decision = TradeDecision(
            asset="BTC",
            timeframe="15m",
            side="yes",
            confidence=0.8,
            edge_estimate=0.05,
            size_pct=0.01,
            market_id="KXBTC-15M-2024-01-01",
            pipeline_id="btc_15m_pipeline",
            decision_agent="BTC_15M",
        )
        
        account_state = {
            "daily_trade_count": {"BTC": 20},  # At limit
        }
        
        result = checker.check_decision(decision, account_state)
        
        assert result.passed is False
        assert result.adjusted_size_pct is None  # Veto, no adjustment
        assert "limit reached" in result.reason.lower()
        assert result.check_name == "frequency_limit"
    
    def test_check_frequency_limit_pass(self):
        """Test passes when under daily trade limit."""
        checker = PreTradeRiskChecker(max_daily_trades=20)
        
        decision = TradeDecision(
            asset="BTC",
            timeframe="15m",
            side="yes",
            confidence=0.8,
            edge_estimate=0.05,
            size_pct=0.01,
            market_id="KXBTC-15M-2024-01-01",
            pipeline_id="btc_15m_pipeline",
            decision_agent="BTC_15M",
        )
        
        account_state = {
            "daily_trade_count": {"BTC": 10},  # Under limit
        }
        
        result = checker.check_decision(decision, account_state)
        
        assert result.passed is True
        assert result.check_name == "daily_loss_cap"  # Last check in the list
    
    def test_check_daily_loss_cap_veto(self):
        """Test veto when daily loss cap exceeded."""
        checker = PreTradeRiskChecker(max_daily_loss_pct=0.20)  # CRITICAL FIX: 20% aligned with drawdown halt
        
        decision = TradeDecision(
            asset="BTC",
            timeframe="15m",
            side="yes",
            confidence=0.8,
            edge_estimate=0.05,
            size_pct=0.01,
            market_id="KXBTC-15M-2024-01-01",
            pipeline_id="btc_15m_pipeline",
            decision_agent="BTC_15M",
        )
        
        account_state = {
            "daily_pnl": -0.06,  # -6%, exceeds -5% loss cap
        }
        
        result = checker.check_decision(decision, account_state)
        
        assert result.passed is False
        assert result.adjusted_size_pct is None  # Veto
        assert "loss cap reached" in result.reason.lower()
        assert result.check_name == "daily_loss_cap"
    
    def test_check_daily_loss_cap_pass(self):
        """Test passes when under daily loss cap."""
        checker = PreTradeRiskChecker(max_daily_loss_pct=0.20)  # CRITICAL FIX: 20% aligned with drawdown halt
        
        decision = TradeDecision(
            asset="BTC",
            timeframe="15m",
            side="yes",
            confidence=0.8,
            edge_estimate=0.05,
            size_pct=0.01,
            market_id="KXBTC-15M-2024-01-01",
            pipeline_id="btc_15m_pipeline",
            decision_agent="BTC_15M",
        )
        
        account_state = {
            "daily_pnl": -0.03,  # -3%, under -5% loss cap
        }
        
        result = checker.check_decision(decision, account_state)
        
        assert result.passed is True
        assert result.check_name == "daily_loss_cap"
    
    def test_update_account_state(self):
        """Test updating internal state from account state."""
        checker = PreTradeRiskChecker()
        
        account_state = {
            "asset_exposure": {"BTC": 0.05, "ETH": 0.03},
            "daily_trade_count": {"BTC": 10, "ETH": 5},
            "daily_pnl": 0.02,
        }
        
        checker.update_account_state(account_state)
        
        assert checker.current_exposure == {"BTC": 0.05, "ETH": 0.03}
        assert checker.daily_trade_count == {"BTC": 10, "ETH": 5}
        assert checker.daily_pnl == 0.02
    
    def test_risk_check_result_fields(self):
        """Test RiskCheckResult dataclass fields."""
        result = RiskCheckResult(
            passed=True,
            adjusted_size_pct=0.02,
            reason="All checks passed",
            check_name="max_size",
        )
        
        assert result.passed is True
        assert result.adjusted_size_pct == 0.02
        assert result.reason == "All checks passed"
        assert result.check_name == "max_size"
    
    def test_multiple_checks_sequential(self):
        """Test running multiple risk checks sequentially."""
        checker = PreTradeRiskChecker()
        
        decision = TradeDecision(
            asset="BTC",
            timeframe="15m",
            side="yes",
            confidence=0.8,
            edge_estimate=0.05,
            size_pct=0.01,
            market_id="KXBTC-15M-2024-01-01",
            pipeline_id="btc_15m_pipeline",
            decision_agent="BTC_15M",
        )
        
        account_state = {
            "asset_exposure": {"BTC": 0.05},
            "daily_trade_count": {"BTC": 5},
            "daily_pnl": 0.01,
        }
        
        # Run check multiple times
        result1 = checker.check_decision(decision, account_state)
        result2 = checker.check_decision(decision, account_state)
        
        assert result1.passed is True
        assert result2.passed is True
