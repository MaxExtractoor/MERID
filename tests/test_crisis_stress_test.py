"""Tests for historical crisis stress testing suite."""
import pytest
from merid.backtesting.crisis_stress_test import (
    CrisisScenario,
    CrisisStressTester,
    StressTestResult,
    CRISIS_SCENARIOS,
    stress_test_position_sizer,
)
from merid.risk.position_sizing import PositionSizer


class TestCrisisScenarios:
    """Test crisis scenario definitions."""
    
    def test_crisis_scenarios_defined(self):
        """Test that all crisis scenarios are properly defined."""
        assert len(CRISIS_SCENARIOS) > 0
        assert "2008_financial_crisis" in CRISIS_SCENARIOS
        assert "2020_covid_crash" in CRISIS_SCENARIOS
        assert "2010_flash_crash" in CRISIS_SCENARIOS
        assert "2022_crypto_winter" in CRISIS_SCENARIOS
        assert "extreme_tail_risk" in CRISIS_SCENARIOS
    
    def test_scenario_attributes(self):
        """Test that crisis scenarios have required attributes."""
        scenario = CRISIS_SCENARIOS["2008_financial_crisis"]
        assert scenario.name == "2008 Financial Crisis"
        assert scenario.volatility_multiplier > 0
        assert 0 < scenario.drawdown_target < 1
        assert scenario.duration_days > 0
        assert 0 <= scenario.gap_down_pct < 1
        assert scenario.recovery_days > 0
        assert 0 <= scenario.correlation_spike <= 1
    
    def test_scenario_severity_ordering(self):
        """Test that scenarios are ordered by severity (tail risk most severe)."""
        tail_risk = CRISIS_SCENARIOS["extreme_tail_risk"]
        covid = CRISIS_SCENARIOS["2020_covid_crash"]
        financial = CRISIS_SCENARIOS["2008_financial_crisis"]
        
        assert tail_risk.volatility_multiplier > covid.volatility_multiplier
        assert tail_risk.drawdown_target > covid.drawdown_target
        assert covid.volatility_multiplier > financial.volatility_multiplier


class TestCrisisStressTester:
    """Test the crisis stress testing engine."""
    
    def test_initialization(self):
        """Test that CrisisStressTester initializes correctly."""
        tester = CrisisStressTester(initial_capital=1000000.0)
        assert tester.initial_capital == 1000000.0
    
    def test_generate_crisis_data(self):
        """Test crisis data generation."""
        tester = CrisisStressTester()
        scenario = CRISIS_SCENARIOS["2020_covid_crash"]
        
        candles = tester.generate_crisis_data(scenario, base_price=50000.0)
        
        assert len(candles) > 0
        assert all("o" in c for c in candles)
        assert all("h" in c for c in candles)
        assert all("l" in c for c in candles)
        assert all("c" in c for c in candles)
        assert all("v" in c for c in candles)
        assert all("t" in c for c in candles)
        
        # Check gap down is applied
        first_close = candles[0]["c"]
        first_open = candles[0]["o"]
        assert first_close < first_open  # Gap down
    
    def test_generate_crisis_data_length(self):
        """Test that generated data matches scenario duration."""
        tester = CrisisStressTester()
        scenario = CRISIS_SCENARIOS["2010_flash_crash"]  # 1 day = 24 hours
        
        candles = tester.generate_crisis_data(scenario)
        assert len(candles) == 24  # 24 hours
    
    def test_run_stress_test_basic(self):
        """Test basic stress test execution."""
        tester = CrisisStressTester()
        scenario = CRISIS_SCENARIOS["2020_covid_crash"]
        
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
            "drawdown_thresholds": {
                "warning": 0.05,
                "critical": 0.10,
                "severe": 0.15,
            },
        }
        sizer = PositionSizer(config)
        
        result = tester.run_stress_test(scenario, sizer)
        
        assert isinstance(result, StressTestResult)
        assert result.scenario_name == scenario.name
        assert result.max_drawdown >= 0
        assert result.final_equity >= 0
        assert result.peak_equity >= result.final_equity
        assert len(result.position_sizes) > 0
    
    def test_stress_test_drawdown_tracking(self):
        """Test that stress test properly tracks drawdown."""
        tester = CrisisStressTester()
        scenario = CRISIS_SCENARIOS["extreme_tail_risk"]  # Severe scenario
        
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
            "drawdown_thresholds": {
                "warning": 0.05,
                "critical": 0.10,
                "severe": 0.15,
            },
        }
        sizer = PositionSizer(config)
        
        result = tester.run_stress_test(scenario, sizer)
        
        # Extreme tail risk should cause significant drawdown
        # Kill switch triggers at 25%, so we expect at least 20% drawdown
        assert result.max_drawdown > 0.2  # At least 20% drawdown
    
    def test_stress_test_kill_switch_trigger(self):
        """Test that kill switch triggers on severe drawdown."""
        tester = CrisisStressTester()
        scenario = CRISIS_SCENARIOS["extreme_tail_risk"]
        
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
            "drawdown_thresholds": {
                "warning": 0.05,
                "critical": 0.10,
                "severe": 0.15,
            },
        }
        sizer = PositionSizer(config)
        
        result = tester.run_stress_test(scenario, sizer)
        
        # Extreme scenario should trigger kill switch
        assert result.kill_switch_triggered
    
    def test_run_all_scenarios(self):
        """Test running all crisis scenarios."""
        tester = CrisisStressTester()
        
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
            "drawdown_thresholds": {
                "warning": 0.05,
                "critical": 0.10,
                "severe": 0.15,
            },
        }
        sizer = PositionSizer(config)
        
        results = tester.run_all_scenarios(sizer)
        
        assert len(results) == len(CRISIS_SCENARIOS)
        assert all(isinstance(r, StressTestResult) for r in results.values())
    
    def test_generate_report(self):
        """Test report generation."""
        tester = CrisisStressTester()
        
        # Create mock results
        results = {
            "test_scenario": StressTestResult(
                scenario_name="Test Scenario",
                passed=True,
                max_drawdown=0.10,
                final_equity=900000.0,
                peak_equity=1000000.0,
                trades_executed=100,
                position_sizes=[0.5, 0.6, 0.4],
                risk_limit_breaches=[],
                kill_switch_triggered=False,
                recovery_time_days=30,
                details={"test": "data"},
            )
        }
        
        report = tester.generate_report(results)
        
        assert "HISTORICAL CRISIS STRESS TEST REPORT" in report
        assert "Test Scenario" in report
        assert "PASSED" in report
        assert "Max Drawdown" in report


class TestDrawdownAdjustedSizingInCrisis:
    """Test drawdown-adjusted sizing during crisis scenarios."""
    
    def test_position_sizing_reduces_during_crisis(self):
        """Test that position sizes reduce during crisis drawdown."""
        tester = CrisisStressTester()
        scenario = CRISIS_SCENARIOS["2008_financial_crisis"]
        
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
            "drawdown_thresholds": {
                "warning": 0.05,
                "critical": 0.10,
                "severe": 0.15,
            },
        }
        sizer = PositionSizer(config)
        
        result = tester.run_stress_test(scenario, sizer)
        
        # Position sizes should decrease during crisis
        # Check that minimum position size is significantly less than maximum
        if len(result.position_sizes) > 10:
            max_size = max(result.position_sizes)
            min_size = min(result.position_sizes)
            # During crisis, sizing should reduce by at least 20%
            assert min_size < max_size * 0.8
    
    def test_drawdown_multiplier_applied(self):
        """Test that drawdown multiplier is correctly applied."""
        tester = CrisisStressTester()
        scenario = CRISIS_SCENARIOS["2020_covid_crash"]
        
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
            "drawdown_thresholds": {
                "warning": 0.05,
                "critical": 0.10,
                "severe": 0.15,
            },
        }
        sizer = PositionSizer(config)
        
        result = tester.run_stress_test(scenario, sizer)
        
        # With drawdown-adjusted sizing, position sizes should reflect drawdown
        # Average position size should be less than 1.0 (full size)
        if result.position_sizes:
            avg_size = sum(result.position_sizes) / len(result.position_sizes)
            assert avg_size < 1.0


class TestConvenienceFunction:
    """Test the convenience stress testing function."""
    
    @pytest.mark.asyncio
    async def test_stress_test_position_sizer(self):
        """Test the convenience function for stress testing."""
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
            },
            "drawdown_thresholds": {
                "warning": 0.05,
                "critical": 0.10,
                "severe": 0.15,
            },
        }
        sizer = PositionSizer(config)
        
        results = await stress_test_position_sizer(sizer, initial_capital=1000000.0)
        
        assert isinstance(results, dict)
        assert len(results) == len(CRISIS_SCENARIOS)
        assert all(isinstance(r, StressTestResult) for r in results.values())
