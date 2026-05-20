"""Tests for Statistical Significance Tests."""

import pytest
import numpy as np
from backtesting.statistical_tests import (
    StatisticalTester,
    get_statistical_tester,
    StatisticalTestResults,
    TTestResult,
    BootstrapResult,
    SignificanceLevel
)


class TestStatisticalTester:
    """Test suite for StatisticalTester."""
    
    def test_singleton(self):
        """Test that StatisticalTester is a singleton."""
        tester1 = get_statistical_tester()
        tester2 = get_statistical_tester()
        assert tester1 is tester2
    
    def test_initialization(self):
        """Test tester initialization."""
        tester = get_statistical_tester()
        assert tester is not None
    
    def test_t_test(self):
        """Test t-test calculation."""
        tester = get_statistical_tester()
        returns = [0.01, 0.02, -0.01, 0.03, 0.01, 0.02, -0.02, 0.01, 0.02, 0.01]
        benchmark = [0.005, 0.01, -0.005, 0.015, 0.005, 0.01, -0.01, 0.005, 0.01, 0.005]
        
        result = tester._run_t_test(returns, benchmark, 0.95)
        assert isinstance(result, TTestResult)
        assert isinstance(result.t_statistic, float)
        assert isinstance(result.p_value, float)
        assert isinstance(result.significance_level, SignificanceLevel)
    
    def test_bootstrap_confidence_interval(self):
        """Test bootstrap confidence interval."""
        tester = get_statistical_tester()
        values = [0.01, 0.02, -0.01, 0.03, 0.01, 0.02, -0.02, 0.01, 0.02, 0.01]
        
        result = tester._bootstrap_confidence_interval(
            values, "test_metric", 0.95, 1000
        )
        assert isinstance(result, BootstrapResult)
        assert result.metric_name == "test_metric"
        assert result.mean > 0
        assert len(result.confidence_interval) == 2
        assert result.confidence_interval[0] < result.confidence_interval[1]
    
    def test_test_backtest_results_insufficient_data(self):
        """Test with insufficient sample size."""
        tester = get_statistical_tester()
        returns = [0.01, 0.02]  # Only 2 observations
        
        result = tester.test_backtest_results(returns)
        assert isinstance(result, StatisticalTestResults)
        assert result.sample_size_adequate is False
    
    def test_test_backtest_results_sufficient_data(self):
        """Test with sufficient sample size."""
        tester = get_statistical_tester()
        returns = [0.01 * i for i in range(50)]  # 50 observations
        
        result = tester.test_backtest_results(returns)
        assert isinstance(result, StatisticalTestResults)
        # May or may not be adequate depending on threshold
        assert result.recommended_sample_size > 0
    
    def test_calculate_rolling_sharpe(self):
        """Test rolling Sharpe calculation."""
        tester = get_statistical_tester()
        returns = [0.01 * i for i in range(30)]
        
        sharpe_ratios = tester._calculate_rolling_sharpe(returns, window=10)
        assert isinstance(sharpe_ratios, list)
        assert len(sharpe_ratios) > 0
    
    def test_calculate_rolling_drawdown(self):
        """Test rolling drawdown calculation."""
        tester = get_statistical_tester()
        returns = [0.01, -0.02, 0.03, -0.01, 0.02, -0.03, 0.01, -0.02, 0.03, -0.01]
        
        drawdowns = tester._calculate_rolling_drawdown(returns, window=5)
        assert isinstance(drawdowns, list)
        assert len(drawdowns) > 0
        assert all(d >= 0 for d in drawdowns)  # Drawdowns should be non-negative
    
    def test_calculate_confidence_score(self):
        """Test confidence score calculation."""
        tester = get_statistical_tester()
        results = StatisticalTestResults(
            t_test=None,
            bootstrap_sharpe=None,
            bootstrap_return=None,
            bootstrap_max_drawdown=None,
            sample_size_adequate=True,
            recommended_sample_size=100,
            overall_significance=SignificanceLevel.SIGNIFICANT,
            confidence_score=0.0
        )
        
        score = tester._calculate_confidence_score(results)
        assert 0 <= score <= 1
    
    def test_get_summary(self):
        """Test summary generation."""
        tester = get_statistical_tester()
        returns = [0.01 * i for i in range(50)]
        result = tester.test_backtest_results(returns)
        
        summary = tester.get_summary(result)
        assert "sample_size_adequate" in summary
        assert "recommended_sample_size" in summary
        assert "overall_significance" in summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
