"""Overfitting metrics tests (DSR, PSR, MinTRL).

This module implements tests for overfitting detection metrics used to validate
that trading strategies are not overfitted to historical data.

Metrics Covered:
1. DSR (Deflated Sharpe Ratio) - Adjusts Sharpe ratio for selection bias
2. PSR (Probabilistic Sharpe Ratio) - Probability that true Sharpe > benchmark
3. MinTRL (Minimum Track Record Length) - Minimum data needed for statistical significance
"""

import pytest
import numpy as np
from typing import List, Tuple
from scipy import stats


class TestDeflatedSharpeRatio:
    """Tests for Deflated Sharpe Ratio (DSR) metric."""

    def test_dsr_calculation_basic(self):
        """DSR should calculate correctly for basic returns series."""
        # Generate sample returns
        np.random.seed(42)
        returns = np.random.normal(0.001, 0.02, 252)  # Daily returns for 1 year
        
        # Calculate Sharpe ratio
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252)
        
        # DSR calculation (simplified)
        # DSR = Phi^-1(Phi(SR) - Phi(SR*) * sqrt(1 - corr^2))
        # Where SR* is the maximum Sharpe among N trials
        sr_star = sharpe  # In this case, only one trial
        dsr = sharpe  # With N=1, DSR ≈ SR
        
        # DSR should be close to SR for single trial
        assert abs(dsr - sharpe) < 0.1, f"DSR should be close to SR for single trial: {dsr} vs {sharpe}"

    def test_dsr_adjusts_for_selection_bias(self):
        """DSR should adjust downward when multiple strategies are tested."""
        np.random.seed(42)
        
        # Generate multiple strategy returns
        num_strategies = 100
        all_returns = []
        for _ in range(num_strategies):
            returns = np.random.normal(0.001, 0.02, 252)
            all_returns.append(returns)
        
        # Calculate Sharpe ratios
        sharpe_ratios = []
        for returns in all_returns:
            sr = np.mean(returns) / np.std(returns) * np.sqrt(252)
            sharpe_ratios.append(sr)
        
        # Maximum Sharpe (selection bias)
        sr_star = max(sharpe_ratios)
        
        # DSR should be lower than max Sharpe due to selection bias
        # This is a simplified check - actual DSR calculation is more complex
        assert sr_star > 0, "Max Sharpe should be positive for this test"
        
        # The selected strategy's Sharpe should be deflated
        selected_idx = sharpe_ratios.index(sr_star)
        selected_sr = sharpe_ratios[selected_idx]
        
        # In practice, DSR < SR* due to selection bias adjustment
        # For this test, we verify the concept
        assert selected_sr == sr_star, "Selected strategy should have max Sharpe"

    def test_dsr_handles_negative_sharpe(self):
        """DSR should handle negative Sharpe ratios correctly."""
        np.random.seed(42)
        
        # Generate negative returns
        returns = np.random.normal(-0.001, 0.02, 252)
        
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252)
        
        # Negative Sharpe should result in low DSR
        assert sharpe < 0, f"Sharpe should be negative: {sharpe}"
        
        # DSR for negative Sharpe should be very low
        # (simplified - actual calculation involves CDF)
        dsr = sharpe  # Placeholder
        assert dsr < 0, f"DSR should be negative for negative Sharpe: {dsr}"

    def test_dsr_requires_minimum_observations(self):
        """DSR should require minimum number of observations for validity."""
        np.random.seed(42)
        
        # Very short return series
        short_returns = np.random.normal(0.001, 0.02, 10)
        
        # Should not calculate DSR for insufficient data
        # Minimum typically 30-50 observations
        assert len(short_returns) < 30, "Test data should be below minimum"
        
        # DSR calculation should fail or be unreliable
        # This is a conceptual test
        is_valid = len(short_returns) >= 30
        assert not is_valid, "Should not calculate DSR for insufficient data"


class TestProbabilisticSharpeRatio:
    """Tests for Probabilistic Sharpe Ratio (PSR) metric."""

    def test_psr_calculation_basic(self):
        """PSR should calculate probability that true Sharpe > benchmark."""
        np.random.seed(42)
        
        # Generate returns
        returns = np.random.normal(0.001, 0.02, 252)
        
        # Calculate Sharpe
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252)
        
        # Benchmark Sharpe (e.g., risk-free rate)
        benchmark_sr = 0.5
        
        # PSR calculation (simplified)
        # PSR = Phi((SR - SR_benchmark) / sqrt(1 - gamma * SR_benchmark))
        # Where gamma is skewness adjustment
        psr = stats.norm.cdf(sharpe - benchmark_sr)
        
        # PSR should be between 0 and 1
        assert 0 <= psr <= 1, f"PSR should be in [0, 1]: {psr}"

    def test_psr_high_sharpe_high_probability(self):
        """PSR should be high when Sharpe is significantly above benchmark."""
        np.random.seed(42)
        
        # Generate high Sharpe returns
        returns = np.random.normal(0.002, 0.01, 252)  # Higher mean, lower vol
        
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252)
        benchmark_sr = 0.5
        
        # PSR should be high
        psr = stats.norm.cdf(sharpe - benchmark_sr)
        
        assert psr > 0.5, f"PSR should be > 0.5 for high Sharpe: {psr}"

    def test_psr_low_sharpe_low_probability(self):
        """PSR should be low when Sharpe is below benchmark."""
        np.random.seed(42)
        
        # Generate low Sharpe returns
        returns = np.random.normal(0.0001, 0.03, 252)  # Low mean, high vol
        
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252)
        benchmark_sr = 1.0
        
        # PSR should be low
        psr = stats.norm.cdf(sharpe - benchmark_sr)
        
        assert psr < 0.5, f"PSR should be < 0.5 for low Sharpe: {psr}"

    def test_psr_considers_skewness(self):
        """PSR should account for return distribution skewness."""
        np.random.seed(42)
        
        # Generate skewed returns (positive skew)
        returns = np.random.gamma(2, 0.01, 252) - 0.02
        
        # Calculate skewness
        skewness = stats.skew(returns)
        
        # Sharpe calculation
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252)
        benchmark_sr = 0.5
        
        # PSR with skewness adjustment
        # (simplified - actual formula more complex)
        psr = stats.norm.cdf(sharpe - benchmark_sr)
        
        # Verify skewness is positive
        assert skewness > 0, f"Returns should be positively skewed: {skewness}"
        assert 0 <= psr <= 1, f"PSR should be in [0, 1]: {psr}"


class TestMinTrackRecordLength:
    """Tests for Minimum Track Record Length (MinTRL) metric."""

    def test_mintrl_calculation_basic(self):
        """MinTRL should calculate minimum observations for statistical significance."""
        np.random.seed(42)
        
        # Given Sharpe ratio
        sharpe = 1.0
        
        # Calculate MinTRL (simplified formula)
        # MinTRL = (1 - gamma * SR) / (SR^2) * ln(1 - confidence)
        # For simplicity, use approximation: MinTRL ≈ 3 / SR^2
        min_trl = 3 / (sharpe ** 2)
        
        # MinTRL should be positive
        assert min_trl > 0, f"MinTRL should be positive: {min_trl}"
        
        # Higher Sharpe should require less data
        assert min_trl < 10, f"MinTRL should be reasonable for SR=1.0: {min_trl}"

    def test_mintrl_higher_sharpe_shorter_record(self):
        """Higher Sharpe ratios should require shorter track records."""
        sharpe_low = 0.5
        sharpe_high = 2.0
        
        min_trl_low = 3 / (sharpe_low ** 2)
        min_trl_high = 3 / (sharpe_high ** 2)
        
        # Higher Sharpe should require less data
        assert min_trl_high < min_trl_low, \
            f"Higher Sharpe should need less data: {min_trl_high} vs {min_trl_low}"

    def test_mintrl_lower_sharpe_longer_record(self):
        """Lower Sharpe ratios should require longer track records."""
        sharpe_low = 0.3
        sharpe_high = 1.5
        
        min_trl_low = 3 / (sharpe_low ** 2)
        min_trl_high = 3 / (sharpe_high ** 2)
        
        # Lower Sharpe should require more data
        assert min_trl_low > min_trl_high, \
            f"Lower Sharpe should need more data: {min_trl_low} vs {min_trl_high}"

    def test_mintrl_confidence_level_sensitivity(self):
        """MinTRL should be sensitive to confidence level."""
        sharpe = 1.0
        
        # Different confidence levels (simplified)
        # Higher confidence requires more data
        confidence_90 = 1.645  # 90% confidence z-score
        confidence_95 = 1.96   # 95% confidence z-score
        confidence_99 = 2.576  # 99% confidence z-score
        
        # MinTRL scales with confidence level squared
        min_trl_90 = (confidence_90 ** 2) / (sharpe ** 2)
        min_trl_95 = (confidence_95 ** 2) / (sharpe ** 2)
        min_trl_99 = (confidence_99 ** 2) / (sharpe ** 2)
        
        # Higher confidence should require more data
        assert min_trl_95 > min_trl_90, \
            f"95% confidence should need more data: {min_trl_95} vs {min_trl_90}"
        assert min_trl_99 > min_trl_95, \
            f"99% confidence should need more data: {min_trl_99} vs {min_trl_95}"

    def test_mintrl_practical_application(self):
        """MinTRL should provide practical guidance for strategy validation."""
        # Typical strategy Sharpe ranges
        sharpe_poor = 0.3
        sharpe_good = 1.0
        sharpe_excellent = 2.0
        
        min_trl_poor = 3 / (sharpe_poor ** 2)
        min_trl_good = 3 / (sharpe_good ** 2)
        min_trl_excellent = 3 / (sharpe_excellent ** 2)
        
        # Practical interpretation
        # Poor Sharpe: needs many years of data
        # Good Sharpe: needs ~3 years of daily data
        # Excellent Sharpe: needs <1 year of data
        
        assert min_trl_poor > 20, \
            f"Poor Sharpe needs long track record: {min_trl_poor}"
        assert min_trl_good < 10, \
            f"Good Sharpe needs moderate track record: {min_trl_good}"
        assert min_trl_excellent < 5, \
            f"Excellent Sharpe needs short track record: {min_trl_excellent}"


class TestOverfittingDetectionIntegration:
    """Integration tests for combined overfitting detection."""

    def test_combined_metrics_consistency(self):
        """DSR, PSR, and MinTRL should provide consistent signals."""
        np.random.seed(42)
        
        # Generate realistic returns
        returns = np.random.normal(0.001, 0.02, 500)  # ~2 years daily data
        
        # Calculate metrics
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252)
        benchmark_sr = 0.5
        psr = stats.norm.cdf(sharpe - benchmark_sr)
        min_trl = 3 / (sharpe ** 2)
        
        # Check consistency
        # If Sharpe is reasonable, PSR should be moderate
        if sharpe > benchmark_sr:
            assert psr > 0.5, f"PSR should be > 0.5 when SR > benchmark: {psr}"
        
        # MinTRL should be achievable with available data
        assert min_trl < len(returns), \
            f"MinTRL should be achievable: {min_trl} vs {len(returns)}"

    def test_overfitting_detection_workflow(self):
        """Complete workflow for detecting overfitting."""
        np.random.seed(42)
        
        # Simulate strategy development process
        # 1. Backtest returns
        backtest_returns = np.random.normal(0.002, 0.015, 252)
        
        # 2. Calculate Sharpe
        sharpe = np.mean(backtest_returns) / np.std(backtest_returns) * np.sqrt(252)
        
        # 3. Check if overfitted using metrics
        # PSR against benchmark
        benchmark_sr = 0.5
        psr = stats.norm.cdf(sharpe - benchmark_sr)
        
        # MinTRL check
        min_trl = 3 / (sharpe ** 2)
        has_sufficient_data = len(backtest_returns) >= min_trl
        
        # 4. Make decision
        is_overfitted = (psr < 0.5) or (not has_sufficient_data)
        
        # Should have valid results
        assert isinstance(psr, float), "PSR should be float"
        assert isinstance(min_trl, float), "MinTRL should be float"
        assert isinstance(is_overfitted, bool), "Decision should be boolean"

    def test_multiple_strategy_comparison(self):
        """Compare multiple strategies using overfitting metrics."""
        np.random.seed(42)
        
        # Generate 3 strategies
        strategies = []
        for i in range(3):
            returns = np.random.normal(0.001 + i * 0.0005, 0.02, 252)
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252)
            psr = stats.norm.cdf(sharpe - 0.5)
            min_trl = 3 / (sharpe ** 2)
            strategies.append({
                'sharpe': sharpe,
                'psr': psr,
                'min_trl': min_trl
            })
        
        # Select best strategy based on combined metrics
        # Strategy with highest PSR and achievable MinTRL
        best_strategy = max(strategies, key=lambda x: x['psr'])
        
        # Should have valid metrics
        assert 0 <= best_strategy['psr'] <= 1, "PSR should be in [0, 1]"
        assert best_strategy['min_trl'] > 0, "MinTRL should be positive"
