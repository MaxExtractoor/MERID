"""Tests for ai_signals/signal_validation.py - Signal Validation & Backtesting."""
import pytest
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from dataclasses import asdict

from ai_signals.signal_validation import (
    ValidationRule,
    BacktestPeriod,
    PerformanceMetric,
    ValidationRuleConfig,
    ValidationResult,
    BacktestConfig,
    BacktestResult,
)


class TestValidationRule:
    """Test ValidationRule enum."""

    def test_confidence_threshold(self):
        """Test confidence threshold rule."""
        assert ValidationRule.CONFIDENCE_THRESHOLD.value == "confidence_threshold"

    def test_risk_limit(self):
        """Test risk limit rule."""
        assert ValidationRule.RISK_LIMIT.value == "risk_limit"

    def test_liquidity_check(self):
        """Test liquidity check rule."""
        assert ValidationRule.LIQUIDITY_CHECK.value == "liquidity_check"

    def test_volatility_check(self):
        """Test volatility check rule."""
        assert ValidationRule.VOLATILITY_CHECK.value == "volatility_check"


class TestBacktestPeriod:
    """Test BacktestPeriod enum."""

    def test_daily_period(self):
        """Test daily period."""
        assert BacktestPeriod.DAILY.value == "daily"

    def test_weekly_period(self):
        """Test weekly period."""
        assert BacktestPeriod.WEEKLY.value == "weekly"

    def test_monthly_period(self):
        """Test monthly period."""
        assert BacktestPeriod.MONTHLY.value == "monthly"


class TestPerformanceMetric:
    """Test PerformanceMetric enum."""

    def test_sharpe_ratio(self):
        """Test Sharpe ratio metric."""
        assert PerformanceMetric.SHARPE_RATIO.value == "sharpe_ratio"

    def test_max_drawdown(self):
        """Test max drawdown metric."""
        assert PerformanceMetric.MAX_DRAWDOWN.value == "max_drawdown"

    def test_win_rate(self):
        """Test win rate metric."""
        assert PerformanceMetric.WIN_RATE.value == "win_rate"


class TestValidationRuleConfig:
    """Test ValidationRuleConfig dataclass."""

    def test_confidence_rule(self):
        """Test confidence threshold rule config."""
        rule = ValidationRuleConfig(
            rule_id="rule_001",
            rule_name="Min Confidence",
            rule_type=ValidationRule.CONFIDENCE_THRESHOLD,
            parameters={"min_confidence": 0.6},
            enabled=True,
            severity="error",
            description="Minimum confidence threshold",
        )
        assert rule.enabled is True
        assert rule.parameters["min_confidence"] == 0.6

    def test_risk_limit_rule(self):
        """Test risk limit rule config."""
        rule = ValidationRuleConfig(
            rule_id="rule_002",
            rule_name="Max Risk",
            rule_type=ValidationRule.RISK_LIMIT,
            parameters={"max_risk": 0.02, "max_position": 0.1},
            enabled=True,
            severity="critical",
            description="Maximum risk per trade",
        )
        assert rule.severity == "critical"


class TestValidationResult:
    """Test ValidationResult dataclass."""

    def test_passed_validation(self):
        """Test passed validation result."""
        result = ValidationResult(
            signal_id="sig_001",
            validation_id="val_001",
            passed=True,
            failed_rules=[],
            warnings=[],
            errors=[],
            critical_issues=[],
            validation_score=1.0,
            timestamp=datetime.now(),
        )
        assert result.passed is True
        assert result.validation_score == 1.0

    def test_failed_validation(self):
        """Test failed validation result."""
        result = ValidationResult(
            signal_id="sig_002",
            validation_id="val_002",
            passed=False,
            failed_rules=["risk_limit", "volatility_check"],
            warnings=["high_correlation"],
            errors=["exceeds_max_risk"],
            critical_issues=[],
            validation_score=0.4,
            timestamp=datetime.now(),
        )
        assert result.passed is False
        assert len(result.failed_rules) == 2

    def test_critical_failure(self):
        """Test critical failure validation."""
        result = ValidationResult(
            signal_id="sig_003",
            validation_id="val_003",
            passed=False,
            failed_rules=["position_size"],
            warnings=[],
            errors=[],
            critical_issues=["exceeds_portfolio_limit"],
            validation_score=0.0,
            timestamp=datetime.now(),
        )
        assert len(result.critical_issues) == 1


class TestBacktestConfig:
    """Test BacktestConfig dataclass."""

    def test_basic_config(self):
        """Test basic backtest config."""
        config = BacktestConfig(
            backtest_id="bt_001",
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 12, 31),
            initial_capital=100000.0,
            commission=0.001,
            slippage=0.0005,
            position_sizing="fixed_fraction",
            risk_management={"max_drawdown": 0.15, "stop_loss": 0.05},
            benchmark="SPY",
        )
        assert config.initial_capital == 100000.0
        assert config.benchmark == "SPY"

    def test_aggressive_config(self):
        """Test aggressive backtest config."""
        config = BacktestConfig(
            backtest_id="bt_002",
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 6, 30),
            initial_capital=50000.0,
            commission=0.0005,
            slippage=0.001,
            position_sizing="kelly",
            risk_management={"max_drawdown": 0.25},
            benchmark=None,
        )
        assert config.position_sizing == "kelly"


class TestBacktestResult:
    """Test BacktestResult dataclass."""

    def test_profitable_backtest(self):
        """Test profitable backtest result."""
        result = BacktestResult(
            backtest_id="bt_001",
            period_start=datetime(2023, 1, 1),
            period_end=datetime(2023, 12, 31),
            total_return=0.25,
            annualized_return=0.25,
            volatility=0.15,
            sharpe_ratio=1.67,
            sortino_ratio=2.1,
            max_drawdown=0.08,
            calmar_ratio=3.12,
            win_rate=0.58,
            profit_factor=1.8,
            total_trades=150,
            winning_trades=87,
            losing_trades=63,
            average_win=0.025,
            average_loss=0.015,
            largest_win=0.12,
            largest_loss=0.08,
            equity_curve=[(datetime(2023, 1, 1), 100000), (datetime(2023, 12, 31), 125000)],
            benchmark_return=0.10,
            alpha=0.15,
            beta=0.85,
        )
        assert result.total_return > 0
        assert result.sharpe_ratio > 1
        assert result.win_rate > 0.5

    def test_losing_backtest(self):
        """Test losing backtest result."""
        result = BacktestResult(
            backtest_id="bt_002",
            period_start=datetime(2023, 1, 1),
            period_end=datetime(2023, 6, 30),
            total_return=-0.10,
            annualized_return=-0.20,
            volatility=0.25,
            sharpe_ratio=-0.80,
            sortino_ratio=-0.60,
            max_drawdown=0.18,
            calmar_ratio=-1.11,
            win_rate=0.42,
            profit_factor=0.75,
            total_trades=80,
            winning_trades=34,
            losing_trades=46,
            average_win=0.02,
            average_loss=0.025,
            largest_win=0.08,
            largest_loss=0.12,
            equity_curve=[(datetime(2023, 1, 1), 100000), (datetime(2023, 6, 30), 90000)],
            benchmark_return=0.05,
            alpha=-0.15,
            beta=1.2,
        )
        assert result.total_return < 0
        assert result.profit_factor < 1


class TestPerformanceCalculations:
    """Test performance metric calculations."""

    def test_sharpe_ratio(self):
        """Test Sharpe ratio calculation."""
        returns = np.array([0.01, 0.02, -0.01, 0.015, 0.025, -0.005])
        risk_free_rate = 0.02 / 252  # Daily risk-free rate
        
        excess_returns = returns - risk_free_rate
        sharpe = np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252)
        
        assert isinstance(sharpe, float)

    def test_sortino_ratio(self):
        """Test Sortino ratio calculation."""
        returns = np.array([0.01, 0.02, -0.01, 0.015, 0.025, -0.005])
        target_return = 0
        
        excess_returns = returns - target_return
        downside_returns = returns[returns < target_return]
        downside_std = np.std(downside_returns) if len(downside_returns) > 0 else 0.01
        
        sortino = np.mean(excess_returns) / downside_std * np.sqrt(252)
        
        assert isinstance(sortino, float)

    def test_max_drawdown(self):
        """Test max drawdown calculation."""
        equity_curve = np.array([100, 105, 103, 110, 95, 100, 108, 102])
        
        peak = np.maximum.accumulate(equity_curve)
        drawdown = (peak - equity_curve) / peak
        max_dd = np.max(drawdown)
        
        assert max_dd > 0
        assert max_dd < 1

    def test_calmar_ratio(self):
        """Test Calmar ratio calculation."""
        annualized_return = 0.20
        max_drawdown = 0.10
        
        calmar = annualized_return / max_drawdown
        
        assert calmar == 2.0

    def test_profit_factor(self):
        """Test profit factor calculation."""
        gross_profit = 5000
        gross_loss = 3000
        
        profit_factor = gross_profit / gross_loss
        
        assert profit_factor == pytest.approx(1.67, rel=0.01)

    def test_win_rate(self):
        """Test win rate calculation."""
        winning_trades = 58
        total_trades = 100
        
        win_rate = winning_trades / total_trades
        
        assert win_rate == 0.58


class TestValidationLogic:
    """Test validation logic."""

    def test_confidence_validation(self):
        """Test confidence threshold validation."""
        min_confidence = 0.6
        signal_confidence = 0.75
        
        passes = signal_confidence >= min_confidence
        
        assert passes is True

    def test_risk_limit_validation(self):
        """Test risk limit validation."""
        max_risk = 0.02
        signal_risk = 0.015
        
        passes = signal_risk <= max_risk
        
        assert passes is True

    def test_position_size_validation(self):
        """Test position size validation."""
        max_position = 0.10  # 10% of portfolio
        signal_position = 0.08
        
        passes = signal_position <= max_position
        
        assert passes is True

    def test_volatility_validation(self):
        """Test volatility validation."""
        max_volatility = 0.50
        current_volatility = 0.35
        
        passes = current_volatility <= max_volatility
        
        assert passes is True

    def test_combined_validation(self):
        """Test combined validation rules."""
        rules = {
            "confidence": {"value": 0.75, "min": 0.6},
            "risk": {"value": 0.015, "max": 0.02},
            "position": {"value": 0.08, "max": 0.10},
        }
        
        all_pass = all(
            rules[r]["value"] >= rules[r].get("min", 0) and 
            rules[r]["value"] <= rules[r].get("max", 1)
            for r in rules
        )
        
        assert all_pass is True


class TestBacktestEngine:
    """Test backtest engine logic."""

    def test_equity_curve_calculation(self):
        """Test equity curve calculation."""
        initial_capital = 100000
        returns = np.array([0.01, -0.005, 0.02, 0.015, -0.01])
        
        equity = initial_capital * np.cumprod(1 + returns)
        
        assert equity[-1] != initial_capital

    def test_trade_pnl_calculation(self):
        """Test trade P&L calculation."""
        entry_price = 100
        exit_price = 105
        position_size = 10
        commission = 0.001
        
        gross_pnl = (exit_price - entry_price) * position_size
        commission_cost = (entry_price + exit_price) * position_size * commission
        net_pnl = gross_pnl - commission_cost
        
        assert net_pnl < gross_pnl

    def test_slippage_impact(self):
        """Test slippage impact."""
        intended_price = 100
        slippage = 0.001
        
        actual_buy_price = intended_price * (1 + slippage)
        actual_sell_price = intended_price * (1 - slippage)
        
        assert actual_buy_price > intended_price
        assert actual_sell_price < intended_price
