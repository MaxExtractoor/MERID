"""Statistical Significance Testing for Backtest Results.

Provides statistical tests (t-tests, bootstrap) to determine if backtest
results are statistically significant and not due to random chance.

Key Features:
- T-tests for comparing strategy returns vs benchmark
- Bootstrap confidence intervals for key metrics
- p-value calculation for significance testing
- Sample size adequacy assessment
- Effect size calculation

Usage:
    from backtesting.statistical_tests import StatisticalTester
    
    tester = StatisticalTester()
    
    # Test backtest results
    results = tester.test_backtest_results(
        returns=returns,
        benchmark_returns=benchmark_returns,
        confidence_level=0.95
    )
    
    # Get bootstrap confidence intervals
    ci = tester.bootstrap_confidence_interval(
        metric_values=sharpe_ratios,
        confidence_level=0.95,
        n_bootstrap=10000
    )
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum

from utils.logger import get_logger

logger = get_logger("backtesting.statistical_tests")


class SignificanceLevel(str, Enum):
    """Statistical significance levels."""
    HIGHLY_SIGNIFICANT = "highly_significant"  # p < 0.01
    SIGNIFICANT = "significant"  # p < 0.05
    MARGINALLY_SIGNIFICANT = "marginally_significant"  # p < 0.1
    NOT_SIGNIFICANT = "not_significant"  # p >= 0.1


@dataclass
class TTestResult:
    """Result of a t-test."""
    t_statistic: float
    p_value: float
    significance_level: SignificanceLevel
    confidence_interval: Tuple[float, float]
    effect_size: float  # Cohen's d
    is_significant: bool
    degrees_of_freedom: int


@dataclass
class BootstrapResult:
    """Result of bootstrap analysis."""
    metric_name: str
    mean: float
    std: float
    confidence_interval: Tuple[float, float]
    confidence_level: float
    n_bootstrap: int
    percentile_5: float
    percentile_95: float


@dataclass
class StatisticalTestResults:
    """Comprehensive statistical test results."""
    # T-test results
    t_test: Optional[TTestResult] = None
    
    # Bootstrap results
    bootstrap_sharpe: Optional[BootstrapResult] = None
    bootstrap_return: Optional[BootstrapResult] = None
    bootstrap_max_drawdown: Optional[BootstrapResult] = None
    
    # Sample adequacy
    sample_size_adequate: bool = False
    recommended_sample_size: int = 0
    
    # Overall assessment
    overall_significance: SignificanceLevel = SignificanceLevel.NOT_SIGNIFICANT
    confidence_score: float = 0.0  # 0-1 score


class StatisticalTester:
    """Statistical significance tester for backtest results.
    
    Provides statistical tests to determine if backtest results are
    statistically significant and not due to random chance.
    """
    
    def __init__(self):
        """Initialize the statistical tester."""
        self._default_confidence_level = 0.95
        self._default_n_bootstrap = 10000
        logger.info("StatisticalTester initialized")
    
    def test_backtest_results(
        self,
        returns: List[float],
        benchmark_returns: Optional[List[float]] = None,
        confidence_level: float = 0.95,
        n_bootstrap: int = 10000
    ) -> StatisticalTestResults:
        """Run comprehensive statistical tests on backtest results.
        
        Args:
            returns: Strategy returns
            benchmark_returns: Benchmark returns for comparison (optional)
            confidence_level: Confidence level for tests (0-1)
            n_bootstrap: Number of bootstrap iterations
            
        Returns:
            StatisticalTestResults with all test results
        """
        results = StatisticalTestResults()
        
        if not returns or len(returns) < 30:
            logger.warning(f"Insufficient sample size: {len(returns)} < 30")
            results.sample_size_adequate = False
            results.recommended_sample_size = 100
            return results
        
        results.sample_size_adequate = len(returns) >= 100
        results.recommended_sample_size = 100 if len(returns) < 100 else len(returns)
        
        # Run t-test against benchmark if provided
        if benchmark_returns and len(benchmark_returns) == len(returns):
            results.t_test = self._run_t_test(returns, benchmark_returns, confidence_level)
        
        # Run bootstrap analysis for key metrics
        if len(returns) >= 30:
            # Bootstrap Sharpe ratio
            sharpe_ratios = self._calculate_rolling_sharpe(returns, window=20)
            if len(sharpe_ratios) >= 10:
                results.bootstrap_sharpe = self._bootstrap_confidence_interval(
                    sharpe_ratios, "sharpe_ratio", confidence_level, n_bootstrap
                )
            
            # Bootstrap returns
            results.bootstrap_return = self._bootstrap_confidence_interval(
                returns, "return", confidence_level, n_bootstrap
            )
            
            # Bootstrap max drawdown
            drawdowns = self._calculate_rolling_drawdown(returns, window=20)
            if len(drawdowns) >= 10:
                results.bootstrap_max_drawdown = self._bootstrap_confidence_interval(
                    drawdowns, "max_drawdown", confidence_level, n_bootstrap
                )
        
        # Calculate overall significance
        results.overall_significance = self._calculate_overall_significance(results)
        results.confidence_score = self._calculate_confidence_score(results)
        
        return results
    
    def _run_t_test(
        self,
        returns: List[float],
        benchmark_returns: List[float],
        confidence_level: float
    ) -> TTestResult:
        """Run t-test comparing strategy returns to benchmark.
        
        Args:
            returns: Strategy returns
            benchmark_returns: Benchmark returns
            confidence_level: Confidence level (0-1)
            
        Returns:
            TTestResult
        """
        # Calculate excess returns
        excess_returns = np.array(returns) - np.array(benchmark_returns)
        
        # Calculate t-statistic
        mean_excess = np.mean(excess_returns)
        std_excess = np.std(excess_returns, ddof=1)
        n = len(excess_returns)
        
        if std_excess == 0:
            t_statistic = 0
        else:
            t_statistic = mean_excess / (std_excess / np.sqrt(n))
        
        # Calculate p-value (two-tailed)
        from scipy import stats
        p_value = 2 * (1 - stats.t.cdf(abs(t_statistic), df=n-1))
        
        # Determine significance level
        if p_value < 0.01:
            significance_level = SignificanceLevel.HIGHLY_SIGNIFICANT
        elif p_value < 0.05:
            significance_level = SignificanceLevel.SIGNIFICANT
        elif p_value < 0.1:
            significance_level = SignificanceLevel.MARGINALLY_SIGNIFICANT
        else:
            significance_level = SignificanceLevel.NOT_SIGNIFICANT
        
        # Calculate confidence interval
        alpha = 1 - confidence_level
        t_critical = stats.t.ppf(1 - alpha/2, df=n-1)
        margin_of_error = t_critical * (std_excess / np.sqrt(n))
        confidence_interval = (
            mean_excess - margin_of_error,
            mean_excess + margin_of_error
        )
        
        # Calculate effect size (Cohen's d)
        effect_size = mean_excess / std_excess if std_excess > 0 else 0
        
        return TTestResult(
            t_statistic=t_statistic,
            p_value=p_value,
            significance_level=significance_level,
            confidence_interval=confidence_interval,
            effect_size=effect_size,
            is_significant=p_value < 0.05,
            degrees_of_freedom=n-1
        )
    
    def _bootstrap_confidence_interval(
        self,
        values: List[float],
        metric_name: str,
        confidence_level: float,
        n_bootstrap: int = 10000
    ) -> BootstrapResult:
        """Calculate bootstrap confidence interval for a metric.
        
        Args:
            values: Metric values to bootstrap
            metric_name: Name of the metric
            confidence_level: Confidence level (0-1)
            n_bootstrap: Number of bootstrap iterations
            
        Returns:
            BootstrapResult
        """
        if not values:
            return BootstrapResult(
                metric_name=metric_name,
                mean=0,
                std=0,
                confidence_interval=(0, 0),
                confidence_level=confidence_level,
                n_bootstrap=n_bootstrap,
                percentile_5=0,
                percentile_95=0
            )
        
        values_array = np.array(values)
        bootstrap_means = []
        
        for _ in range(n_bootstrap):
            # Resample with replacement
            resampled = np.random.choice(values_array, size=len(values_array), replace=True)
            bootstrap_means.append(np.mean(resampled))
        
        bootstrap_means = np.array(bootstrap_means)
        
        # Calculate statistics
        mean = np.mean(bootstrap_means)
        std = np.std(bootstrap_means)
        
        # Calculate confidence interval
        alpha = 1 - confidence_level
        lower_percentile = (alpha / 2) * 100
        upper_percentile = (1 - alpha / 2) * 100
        
        ci_lower = np.percentile(bootstrap_means, lower_percentile)
        ci_upper = np.percentile(bootstrap_means, upper_percentile)
        
        # Calculate 5th and 95th percentiles
        percentile_5 = np.percentile(bootstrap_means, 5)
        percentile_95 = np.percentile(bootstrap_means, 95)
        
        return BootstrapResult(
            metric_name=metric_name,
            mean=mean,
            std=std,
            confidence_interval=(ci_lower, ci_upper),
            confidence_level=confidence_level,
            n_bootstrap=n_bootstrap,
            percentile_5=percentile_5,
            percentile_95=percentile_95
        )
    
    def _calculate_rolling_sharpe(self, returns: List[float], window: int = 20) -> List[float]:
        """Calculate rolling Sharpe ratio.
        
        Args:
            returns: Returns
            window: Rolling window size
            
        Returns:
            List of rolling Sharpe ratios
        """
        sharpe_ratios = []
        returns_array = np.array(returns)
        
        for i in range(window, len(returns_array)):
            window_returns = returns_array[i-window:i]
            if len(window_returns) > 1 and np.std(window_returns) > 0:
                sharpe = np.mean(window_returns) / np.std(window_returns) * np.sqrt(252)
                sharpe_ratios.append(sharpe)
        
        return sharpe_ratios
    
    def _calculate_rolling_drawdown(self, returns: List[float], window: int = 20) -> List[float]:
        """Calculate rolling max drawdown.
        
        Args:
            returns: Returns
            window: Rolling window size
            
        Returns:
            List of rolling max drawdowns
        """
        drawdowns = []
        returns_array = np.array(returns)
        cumulative_returns = np.cumprod(1 + returns_array)
        
        for i in range(window, len(cumulative_returns)):
            window_cumulative = cumulative_returns[i-window:i]
            peak = np.maximum.accumulate(window_cumulative)
            drawdown = (peak - window_cumulative) / peak
            max_drawdown = np.max(drawdown)
            drawdowns.append(max_drawdown)
        
        return drawdowns
    
    def _calculate_overall_significance(self, results: StatisticalTestResults) -> SignificanceLevel:
        """Calculate overall significance level.
        
        Args:
            results: Statistical test results
            
        Returns:
            Overall significance level
        """
        # If t-test is significant, that's strong evidence
        if results.t_test and results.t_test.is_significant:
            if results.t_test.p_value < 0.01:
                return SignificanceLevel.HIGHLY_SIGNIFICANT
            return SignificanceLevel.SIGNIFICANT
        
        # If bootstrap intervals are tight and exclude zero, that's evidence
        if results.bootstrap_return:
            ci = results.bootstrap_return.confidence_interval
            if ci[0] > 0 or ci[1] < 0:
                return SignificanceLevel.SIGNIFICANT
        
        return SignificanceLevel.NOT_SIGNIFICANT
    
    def _calculate_confidence_score(self, results: StatisticalTestResults) -> float:
        """Calculate overall confidence score (0-1).
        
        Args:
            results: Statistical test results
            
        Returns:
            Confidence score between 0 and 1
        """
        score = 0.0
        
        # T-test contribution
        if results.t_test:
            if results.t_test.is_significant:
                score += 0.4
                if results.t_test.p_value < 0.01:
                    score += 0.2  # Extra for highly significant
            score += min(abs(results.t_test.effect_size), 1.0) * 0.1
        
        # Bootstrap contribution
        if results.bootstrap_sharpe:
            ci_width = results.bootstrap_sharpe.confidence_interval[1] - results.bootstrap_sharpe.confidence_interval[0]
            # Tighter confidence interval = higher confidence
            score += max(0, 1 - ci_width) * 0.2
        
        # Sample size contribution
        if results.sample_size_adequate:
            score += 0.1
        
        return min(score, 1.0)
    
    def get_summary(self, results: StatisticalTestResults) -> Dict[str, Any]:
        """Get a summary of statistical test results.
        
        Args:
            results: Statistical test results
            
        Returns:
            Summary dictionary
        """
        summary = {
            "sample_size_adequate": results.sample_size_adequate,
            "recommended_sample_size": results.recommended_sample_size,
            "overall_significance": results.overall_significance.value,
            "confidence_score": results.confidence_score
        }
        
        if results.t_test:
            summary["t_test"] = {
                "t_statistic": results.t_test.t_statistic,
                "p_value": results.t_test.p_value,
                "significance_level": results.t_test.significance_level.value,
                "is_significant": results.t_test.is_significant,
                "effect_size": results.t_test.effect_size
            }
        
        if results.bootstrap_sharpe:
            summary["bootstrap_sharpe"] = {
                "mean": results.bootstrap_sharpe.mean,
                "confidence_interval": results.bootstrap_sharpe.confidence_interval,
                "percentile_5": results.bootstrap_sharpe.percentile_5,
                "percentile_95": results.bootstrap_sharpe.percentile_95
            }
        
        if results.bootstrap_return:
            summary["bootstrap_return"] = {
                "mean": results.bootstrap_return.mean,
                "confidence_interval": results.bootstrap_return.confidence_interval,
                "percentile_5": results.bootstrap_return.percentile_5,
                "percentile_95": results.bootstrap_return.percentile_95
            }
        
        return summary


# Singleton accessor
_statistical_tester: Optional[StatisticalTester] = None


def get_statistical_tester() -> StatisticalTester:
    """Get the singleton StatisticalTester instance."""
    global _statistical_tester
    if _statistical_tester is None:
        _statistical_tester = StatisticalTester()
    return _statistical_tester
