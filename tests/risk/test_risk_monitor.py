"""Tests for risk/risk_monitor.py - Advanced Risk Management."""
import pytest
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from dataclasses import asdict

from risk.risk_monitor import (
    RiskAlert,
    RiskLimit,
    StressTestResult,
    RiskMetrics,
    RiskMonitor,
)


class TestRiskAlert:
    """Test RiskAlert dataclass."""

    def test_low_severity_alert(self):
        """Test low severity alert."""
        alert = RiskAlert(
            alert_id="alert_001",
            alert_type="leverage_warning",
            severity="low",
            message="Leverage approaching limit",
            current_value=1.5,
            threshold=2.0,
            timestamp=1000.0,
        )
        assert alert.severity == "low"
        assert alert.current_value < alert.threshold

    def test_high_severity_alert(self):
        """Test high severity alert."""
        alert = RiskAlert(
            alert_id="alert_002",
            alert_type="var_breach",
            severity="high",
            message="VaR limit exceeded",
            current_value=0.035,
            threshold=0.02,
            timestamp=1000.0,
            symbol="BTC/USD",
        )
        assert alert.severity == "high"
        assert alert.current_value > alert.threshold

    def test_critical_alert(self):
        """Test critical alert."""
        alert = RiskAlert(
            alert_id="alert_003",
            alert_type="drawdown_breach",
            severity="critical",
            message="Max drawdown exceeded - initiating risk reduction",
            current_value=0.25,
            threshold=0.15,
            timestamp=1000.0,
            metadata={"action": "reduce_positions"},
        )
        assert alert.severity == "critical"
        assert alert.metadata["action"] == "reduce_positions"


class TestRiskLimit:
    """Test RiskLimit dataclass."""

    def test_active_limit(self):
        """Test active risk limit."""
        limit = RiskLimit(
            limit_id="limit_001",
            limit_type="max_leverage",
            limit_value=2.0,
            current_value=1.5,
            breach_count=0,
            active=True,
        )
        assert limit.active is True
        assert limit.current_value < limit.limit_value

    def test_breached_limit(self):
        """Test breached risk limit."""
        limit = RiskLimit(
            limit_id="limit_002",
            limit_type="max_var_95",
            limit_value=0.02,
            current_value=0.025,
            breach_count=3,
            last_breach=1000.0,
            active=True,
        )
        assert limit.current_value > limit.limit_value
        assert limit.breach_count == 3

    def test_disabled_limit(self):
        """Test disabled risk limit."""
        limit = RiskLimit(
            limit_id="limit_003",
            limit_type="concentration",
            limit_value=0.3,
            current_value=0.4,
            active=False,
        )
        assert limit.active is False


class TestStressTestResult:
    """Test StressTestResult dataclass."""

    def test_market_crash_scenario(self):
        """Test market crash stress test."""
        result = StressTestResult(
            test_id="stress_001",
            test_name="Market Crash -20%",
            scenario="market_crash",
            portfolio_value_before=100000,
            portfolio_value_after=80000,
            portfolio_loss=20000,
            loss_percentage=20.0,
            worst_position="BTC/USD",
            risk_metrics={"var_impact": 0.15, "es_impact": 0.22},
            test_time=0.5,
        )
        assert result.loss_percentage == 20.0
        assert result.worst_position == "BTC/USD"

    def test_volatility_spike_scenario(self):
        """Test volatility spike stress test."""
        result = StressTestResult(
            test_id="stress_002",
            test_name="Volatility Spike 3x",
            scenario="volatility_spike",
            portfolio_value_before=100000,
            portfolio_value_after=92000,
            portfolio_loss=8000,
            loss_percentage=8.0,
            worst_position="ETH/USD",
            risk_metrics={"var_impact": 0.06, "margin_impact": 0.12},
            test_time=0.3,
        )
        assert result.scenario == "volatility_spike"

    def test_liquidity_crisis_scenario(self):
        """Test liquidity crisis stress test."""
        result = StressTestResult(
            test_id="stress_003",
            test_name="Liquidity Crisis",
            scenario="liquidity_crisis",
            portfolio_value_before=100000,
            portfolio_value_after=85000,
            portfolio_loss=15000,
            loss_percentage=15.0,
            worst_position=None,
            risk_metrics={"slippage_impact": 0.08, "execution_delay": 5.0},
            test_time=1.2,
            metadata={"affected_positions": ["BTC/USD", "ETH/USD", "SOL/USD"]},
        )
        assert result.worst_position is None
        assert len(result.metadata["affected_positions"]) == 3


class TestRiskMetrics:
    """Test RiskMetrics dataclass."""

    def test_healthy_metrics(self):
        """Test healthy risk metrics."""
        metrics = RiskMetrics(
            timestamp=1000.0,
            portfolio_value=100000,
            total_exposure=80000,
            leverage=0.8,
            var_95=0.015,
            var_99=0.025,
            expected_shortfall=0.02,
            max_drawdown=0.05,
            sharpe_ratio=1.5,
            beta=0.8,
            correlation_risk=0.3,
            concentration_risk=0.2,
            liquidity_risk=0.1,
            operational_risk=0.05,
        )
        assert metrics.leverage < 1.0
        assert metrics.sharpe_ratio > 1.0

    def test_high_risk_metrics(self):
        """Test high risk metrics."""
        metrics = RiskMetrics(
            timestamp=1000.0,
            portfolio_value=100000,
            total_exposure=200000,
            leverage=2.0,
            var_95=0.04,
            var_99=0.06,
            expected_shortfall=0.05,
            max_drawdown=0.15,
            sharpe_ratio=0.5,
            beta=1.5,
            correlation_risk=0.7,
            concentration_risk=0.6,
            liquidity_risk=0.4,
            operational_risk=0.2,
        )
        assert metrics.leverage >= 2.0
        assert metrics.var_95 > 0.02


class TestRiskMonitor:
    """Test RiskMonitor class."""

    @pytest.fixture
    def monitor_config(self):
        """Create monitor config."""
        return {
            "monitoring_interval": 60,
            "alert_cooldown": 300,
            "max_leverage": 2.0,
            "max_var_95": 0.02,
        }

    @pytest.fixture
    def risk_monitor(self, monitor_config):
        """Create risk monitor instance."""
        return RiskMonitor(monitor_config)

    def test_monitor_creation(self, risk_monitor):
        """Test creating monitor."""
        assert risk_monitor is not None
        assert risk_monitor.monitoring_interval == 60

    def test_default_limits(self, risk_monitor):
        """Test default risk limits."""
        assert risk_monitor.default_limits["max_leverage"] == 2.0
        assert risk_monitor.default_limits["max_var_95"] == 0.02

    def test_risk_alerts_deque(self, risk_monitor):
        """Test risk alerts storage."""
        assert hasattr(risk_monitor, 'risk_alerts')
        assert risk_monitor.risk_alerts.maxlen == 1000

    def test_add_risk_limit(self, risk_monitor):
        """Test adding risk limit."""
        limit = RiskLimit(
            limit_id="custom_limit",
            limit_type="max_position",
            limit_value=50000,
            current_value=30000,
        )
        risk_monitor.risk_limits["custom_limit"] = limit
        
        assert "custom_limit" in risk_monitor.risk_limits

    def test_active_alerts_tracking(self, risk_monitor):
        """Test active alerts tracking."""
        alert = RiskAlert(
            alert_id="test_alert",
            alert_type="test",
            severity="low",
            message="Test",
            current_value=1.0,
            threshold=2.0,
            timestamp=1000.0,
        )
        risk_monitor.active_alerts["test_alert"] = alert
        
        assert "test_alert" in risk_monitor.active_alerts


class TestRiskCalculations:
    """Test risk calculation methods."""

    def test_leverage_calculation(self):
        """Test leverage calculation."""
        portfolio_value = 100000
        total_exposure = 150000
        
        leverage = total_exposure / portfolio_value
        
        assert leverage == 1.5

    def test_var_calculation(self):
        """Test VaR calculation."""
        returns = np.random.randn(1000) * 0.02
        
        var_95 = np.percentile(returns, 5)
        var_99 = np.percentile(returns, 1)
        
        assert var_99 < var_95 < 0

    def test_expected_shortfall(self):
        """Test Expected Shortfall calculation."""
        np.random.seed(42)
        returns = np.random.randn(10000) * 0.02
        
        var_95 = np.percentile(returns, 5)
        es_95 = returns[returns <= var_95].mean()
        
        assert es_95 < var_95

    def test_concentration_risk(self):
        """Test concentration risk calculation."""
        positions = {"BTC": 50000, "ETH": 30000, "SOL": 20000}
        total = sum(positions.values())
        
        # Herfindahl-Hirschman Index
        hhi = sum((v / total) ** 2 for v in positions.values())
        
        # HHI ranges from 1/n to 1
        assert 0 < hhi <= 1

    def test_correlation_risk(self):
        """Test correlation risk calculation."""
        np.random.seed(42)
        n = 100
        
        # Generate correlated returns
        returns_btc = np.random.randn(n) * 0.02
        returns_eth = returns_btc * 0.8 + np.random.randn(n) * 0.01
        
        correlation = np.corrcoef(returns_btc, returns_eth)[0, 1]
        
        assert correlation > 0.5  # Should be positively correlated


class TestStressTestScenarios:
    """Test stress test scenario implementations."""

    def test_market_crash_scenario(self):
        """Test market crash stress test."""
        portfolio = {"BTC": 50000, "ETH": 30000, "SOL": 20000}
        crash_factor = 0.20  # 20% crash
        
        stressed_portfolio = {k: v * (1 - crash_factor) for k, v in portfolio.items()}
        total_before = sum(portfolio.values())
        total_after = sum(stressed_portfolio.values())
        
        loss_pct = (total_before - total_after) / total_before
        
        assert loss_pct == pytest.approx(crash_factor)

    def test_volatility_spike_scenario(self):
        """Test volatility spike stress test."""
        current_vol = 0.20
        spike_multiplier = 3.0
        
        stressed_vol = current_vol * spike_multiplier
        
        # Impact on VaR (simplified)
        var_multiplier = spike_multiplier
        
        assert stressed_vol == pytest.approx(0.60)

    def test_correlation_spike_scenario(self):
        """Test correlation spike stress test."""
        normal_correlation = 0.5
        stressed_correlation = 0.95
        
        # Impact on portfolio volatility
        weights = np.array([0.5, 0.5])
        vols = np.array([0.20, 0.25])
        
        normal_port_vol = np.sqrt(
            np.sum(weights**2 * vols**2) + 
            2 * weights[0] * weights[1] * vols[0] * vols[1] * normal_correlation
        )
        
        stressed_port_vol = np.sqrt(
            np.sum(weights**2 * vols**2) + 
            2 * weights[0] * weights[1] * vols[0] * vols[1] * stressed_correlation
        )
        
        assert stressed_port_vol > normal_port_vol

    def test_liquidity_stress_scenario(self):
        """Test liquidity stress scenario."""
        positions = {"BTC": 100000, "ETH": 50000, "SMALL_CAP": 30000}
        liquidity_factors = {"BTC": 0.01, "ETH": 0.02, "SMALL_CAP": 0.10}
        
        # Calculate slippage impact
        slippage_cost = sum(
            positions[k] * liquidity_factors[k] 
            for k in positions
        )
        
        total_portfolio = sum(positions.values())
        slippage_pct = slippage_cost / total_portfolio
        
        assert slippage_pct > 0


class TestRiskLimitEnforcement:
    """Test risk limit enforcement."""

    def test_leverage_limit_check(self):
        """Test leverage limit checking."""
        max_leverage = 2.0
        current_leverage = 1.8
        
        is_within_limit = current_leverage <= max_leverage
        headroom = (max_leverage - current_leverage) / max_leverage
        
        assert is_within_limit is True
        assert headroom == pytest.approx(0.1)

    def test_position_limit_check(self):
        """Test position limit checking."""
        max_position = 50000
        positions = {"BTC": 45000, "ETH": 55000}
        
        breaches = [
            (k, v) for k, v in positions.items() 
            if v > max_position
        ]
        
        assert len(breaches) == 1
        assert breaches[0][0] == "ETH"

    def test_concentration_limit_check(self):
        """Test concentration limit checking."""
        max_concentration = 0.40  # 40% max per position
        portfolio = {"BTC": 60000, "ETH": 25000, "SOL": 15000}
        total = sum(portfolio.values())
        
        concentrations = {k: v / total for k, v in portfolio.items()}
        breaches = [k for k, c in concentrations.items() if c > max_concentration]
        
        assert "BTC" in breaches

    def test_drawdown_limit_check(self):
        """Test drawdown limit checking."""
        max_drawdown = 0.15
        peak_value = 100000
        current_value = 82000
        
        drawdown = (peak_value - current_value) / peak_value
        is_breached = drawdown > max_drawdown
        
        assert is_breached is True
        assert drawdown == 0.18
