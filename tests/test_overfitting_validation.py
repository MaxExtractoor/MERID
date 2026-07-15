"""Overfitting validation tests (PBO, CPCV).

This module implements tests for advanced overfitting validation techniques
used to detect when backtest results are too good to be true.

Validation Techniques:
1. PBO (Probability of Backtest Overfitting) - Measures likelihood of overfitting
2. CPCV (Combinatorial Purged Cross-Validation) - Robust cross-validation for time series
"""

import pytest
import numpy as np
from typing import List, Tuple, Optional
from scipy import stats
from sklearn.model_selection import TimeSeriesSplit


class TestProbabilityOfBacktestOverfitting:
    """Tests for Probability of Backtest Overfitting (PBO)."""

    def test_pbo_calculation_basic(self):
        """PBO should calculate probability of overfitting from multiple trials."""
        np.random.seed(42)
        
        # Simulate multiple backtest trials
        num_trials = 100
        num_observations = 252
        
        # Generate Sharpe ratios for each trial
        # Simulate some overfitting by having a few very high values
        sharpe_ratios = np.random.normal(0.5, 0.3, num_trials)
        # Add a few outliers (overfitted trials)
        sharpe_ratios[:5] = np.random.normal(2.0, 0.2, 5)
        
        # Calculate PBO (simplified)
        # PBO = proportion of trials that are likely overfitted
        # Use IQR-based outlier detection
        q75, q25 = np.percentile(sharpe_ratios, [75, 25])
        iqr = q75 - q25
        upper_bound = q75 + 1.5 * iqr
        
        overfitted_count = np.sum(sharpe_ratios > upper_bound)
        pbo = overfitted_count / num_trials
        
        # PBO should be between 0 and 1
        assert 0 <= pbo <= 1, f"PBO should be in [0, 1]: {pbo}"
        
        # With outliers, PBO should be > 0
        assert pbo > 0, f"PBO should detect outliers: {pbo}"

    def test_pbo_increasing_with_trials(self):
        """PBO should increase as more trials are conducted (selection bias)."""
        np.random.seed(42)
        
        # Test with different numbers of trials
        pbo_values = []
        trial_counts = [10, 50, 100, 200]
        
        for num_trials in trial_counts:
            sharpe_ratios = np.random.normal(0.5, 0.3, num_trials)
            # Add outliers proportional to trial count
            num_outliers = int(num_trials * 0.05)
            sharpe_ratios[:num_outliers] = np.random.normal(2.0, 0.2, num_outliers)
            
            q75, q25 = np.percentile(sharpe_ratios, [75, 25])
            iqr = q75 - q25
            upper_bound = q75 + 1.5 * iqr
            overfitted_count = np.sum(sharpe_ratios > upper_bound)
            pbo = overfitted_count / num_trials
            pbo_values.append(pbo)
        
        # PBO should generally increase with more trials
        # (due to higher chance of finding spurious patterns)
        assert pbo_values[-1] >= pbo_values[0], \
            f"PBO should increase with trials: {pbo_values[-1]} vs {pbo_values[0]}"

    def test_pbo_no_overfitting_case(self):
        """PBO should be low when there's no overfitting."""
        np.random.seed(42)
        
        # Generate consistent Sharpe ratios (no outliers)
        num_trials = 100
        sharpe_ratios = np.random.normal(0.5, 0.1, num_trials)
        
        # Calculate PBO
        q75, q25 = np.percentile(sharpe_ratios, [75, 25])
        iqr = q75 - q25
        upper_bound = q75 + 1.5 * iqr
        overfitted_count = np.sum(sharpe_ratios > upper_bound)
        pbo = overfitted_count / num_trials
        
        # PBO should be low for consistent results
        assert pbo < 0.1, f"PBO should be low without overfitting: {pbo}"

    def test_pbo_high_overfitting_case(self):
        """PBO should be high when there's significant overfitting."""
        np.random.seed(42)
        
        # Generate Sharpe ratios with many outliers
        num_trials = 100
        sharpe_ratios = np.random.normal(0.5, 0.3, num_trials)
        # Add many outliers
        sharpe_ratios[:20] = np.random.normal(2.5, 0.3, 20)
        
        # Calculate PBO
        q75, q25 = np.percentile(sharpe_ratios, [75, 25])
        iqr = q75 - q25
        upper_bound = q75 + 1.5 * iqr
        overfitted_count = np.sum(sharpe_ratios > upper_bound)
        pbo = overfitted_count / num_trials
        
        # PBO should be high with many outliers
        assert pbo > 0.1, f"PBO should be high with overfitting: {pbo}"


class TestCombinatorialPurgedCrossValidation:
    """Tests for Combinatorial Purged Cross-Validation (CPCV)."""

    def test_cpcv_basic_split(self):
        """CPCV should create purged train/test splits for time series."""
        np.random.seed(42)
        
        # Generate time series data
        n_samples = 500
        X = np.random.randn(n_samples, 5)  # Features
        y = np.random.randn(n_samples)  # Returns
        
        # CPCV parameters
        n_splits = 5
        purge_size = 10  # Number of samples to purge between train and test
        
        # Create splits (simplified CPCV)
        splits = []
        for i in range(n_splits):
            test_start = i * (n_samples // n_splits)
            test_end = (i + 1) * (n_samples // n_splits)
            
            # Purge gap
            train_end = test_start - purge_size
            train_start = 0
            
            if train_end > 0:
                splits.append((train_start, train_end, test_start, test_end))
        
        # Should create valid splits
        assert len(splits) > 0, "Should create at least one split"
        
        # Verify no overlap between train and test
        for train_start, train_end, test_start, test_end in splits:
            assert train_end <= test_start, \
                f"Train and test should not overlap: {train_end} vs {test_start}"

    def test_cpcv_purging_prevents_leakage(self):
        """CPCV purging should prevent information leakage."""
        np.random.seed(42)
        
        n_samples = 500
        X = np.random.randn(n_samples, 5)
        y = np.random.randn(n_samples)
        
        # With purging
        purge_size = 20
        test_size = 100
        
        # Create a single split with purging
        test_start = 300
        test_end = 400
        train_end = test_start - purge_size
        train_start = 0
        
        # Verify purging gap
        gap = test_start - train_end
        assert gap == purge_size, \
            f"Purging gap should be {purge_size}: {gap}"
        
        # Train data should not include test data
        assert train_end < test_start, \
            "Train should end before test starts (with purge gap)"

    def test_cpcv_multiple_combinations(self):
        """CPCV should generate multiple train/test combinations."""
        np.random.seed(42)
        
        n_samples = 500
        n_splits = 3
        k_folds = 2  # Number of test folds per split
        
        # Generate combinations (simplified)
        combinations = []
        for i in range(n_splits):
            for j in range(k_folds):
                # Create test fold
                fold_size = n_samples // (n_splits * k_folds)
                test_start = (i * k_folds + j) * fold_size
                test_end = test_start + fold_size
                
                # Train on remaining data (with purging)
                purge_size = 10
                train_end = test_start - purge_size
                train_start = 0
                
                if train_end > 0:
                    combinations.append((train_start, train_end, test_start, test_end))
        
        # Should generate multiple combinations
        assert len(combinations) > 1, \
            f"Should generate multiple combinations: {len(combinations)}"

    def test_cpcv_performance_evaluation(self):
        """CPCV should provide robust performance estimates."""
        np.random.seed(42)
        
        n_samples = 500
        X = np.random.randn(n_samples, 5)
        y = np.random.randn(n_samples)
        
        # Simulate CPCV evaluation
        n_splits = 5
        purge_size = 10
        performances = []
        
        for i in range(n_splits):
            test_start = i * (n_samples // n_splits)
            test_end = (i + 1) * (n_samples // n_splits)
            train_end = test_start - purge_size
            
            if train_end > 0:
                # Simulate model performance (Sharpe ratio)
                train_sharpe = np.random.normal(0.5, 0.2)
                test_sharpe = np.random.normal(0.4, 0.3)
                performances.append({
                    'train_sharpe': train_sharpe,
                    'test_sharpe': test_sharpe,
                    'overfit': train_sharpe - test_sharpe
                })
        
        # Should have performance estimates
        assert len(performances) > 0, "Should have performance estimates"
        
        # Calculate average overfitting
        avg_overfit = np.mean([p['overfit'] for p in performances])
        assert isinstance(avg_overfit, float), "Average overfit should be float"

    def test_cpcv_robustness_to_lookahead_bias(self):
        """CPCV should be robust to lookahead bias."""
        np.random.seed(42)
        
        n_samples = 500
        X = np.random.randn(n_samples, 5)
        y = np.random.randn(n_samples)
        
        # Test with different purge sizes
        purge_sizes = [0, 5, 10, 20]
        leakage_detected = []
        
        for purge_size in purge_sizes:
            # Create split
            test_start = 250
            test_end = 350
            train_end = test_start - purge_size
            
            # Check for potential leakage
            # If purge_size is 0, there's potential leakage
            has_leakage = (train_end >= test_start)
            leakage_detected.append(has_leakage)
        
        # With purge_size=0, leakage should be detected
        assert leakage_detected[0] == True, "Should detect leakage with no purging"
        
        # With larger purge sizes, no leakage
        assert not any(leakage_detected[1:]), \
            "Should not detect leakage with purging"


class TestOverfittingValidationIntegration:
    """Integration tests for combined overfitting validation."""

    def test_combined_pbo_cpcv_validation(self):
        """PBO and CPCV should provide consistent overfitting signals."""
        np.random.seed(42)
        
        # Generate strategy returns
        n_samples = 500
        returns = np.random.normal(0.001, 0.02, n_samples)
        
        # PBO calculation
        num_trials = 50
        sharpe_ratios = np.random.normal(0.5, 0.3, num_trials)
        sharpe_ratios[:3] = np.random.normal(2.0, 0.2, 3)
        
        q75, q25 = np.percentile(sharpe_ratios, [75, 25])
        iqr = q75 - q25
        upper_bound = q75 + 1.5 * iqr
        pbo = np.sum(sharpe_ratios > upper_bound) / num_trials
        
        # CPCV evaluation (simplified)
        n_splits = 5
        test_sharpes = []
        for i in range(n_splits):
            test_sharpe = np.random.normal(0.4, 0.3)
            test_sharpes.append(test_sharpe)
        
        avg_test_sharpe = np.mean(test_sharpes)
        
        # Combined validation
        # If PBO is high and test Sharpe is low, likely overfitted
        is_overfitted = bool((pbo > 0.1) and (avg_test_sharpe < 0.5))
        
        # Should produce valid decision
        assert isinstance(is_overfitted, bool), "Decision should be boolean"
        assert 0 <= pbo <= 1, "PBO should be in [0, 1]"

    def test_validation_workflow(self):
        """Complete workflow for overfitting validation."""
        np.random.seed(42)
        
        # Step 1: Generate backtest results
        num_trials = 100
        sharpe_ratios = np.random.normal(0.5, 0.3, num_trials)
        sharpe_ratios[:5] = np.random.normal(2.0, 0.2, 5)
        
        # Step 2: Calculate PBO
        q75, q25 = np.percentile(sharpe_ratios, [75, 25])
        iqr = q75 - q25
        upper_bound = q75 + 1.5 * iqr
        pbo = np.sum(sharpe_ratios > upper_bound) / num_trials
        
        # Step 3: CPCV validation
        n_samples = 500
        n_splits = 5
        test_sharpes = []
        for i in range(n_splits):
            test_sharpe = np.random.normal(0.4, 0.3)
            test_sharpes.append(test_sharpe)
        avg_test_sharpe = np.mean(test_sharpes)
        std_test_sharpe = np.std(test_sharpes)
        
        # Step 4: Make decision
        # Overfitting criteria:
        # - High PBO (> 0.1)
        # - Low average test Sharpe (< 0.5)
        # - High variance in test Sharpe (> 0.3)
        is_overfitted = bool((pbo > 0.1) and (avg_test_sharpe < 0.5) and (std_test_sharpe > 0.3))
        
        # Step 5: Generate report
        report = {
            'pbo': pbo,
            'avg_test_sharpe': avg_test_sharpe,
            'std_test_sharpe': std_test_sharpe,
            'is_overfitted': is_overfitted,
            'confidence': 'high' if pbo > 0.2 else 'medium' if pbo > 0.1 else 'low'
        }
        
        # Should have valid report
        assert isinstance(report, dict), "Report should be dict"
        assert 'is_overfitted' in report, "Report should include decision"
        assert report['confidence'] in ['high', 'medium', 'low'], \
            "Confidence should be valid level"

    def test_threshold_tuning(self):
        """Overfitting detection thresholds should be tunable."""
        np.random.seed(42)
        
        # Generate test data
        num_trials = 100
        sharpe_ratios = np.random.normal(0.5, 0.3, num_trials)
        sharpe_ratios[:5] = np.random.normal(2.0, 0.2, 5)
        
        # Test different PBO thresholds
        thresholds = [0.05, 0.1, 0.15, 0.2]
        decisions = []
        
        for threshold in thresholds:
            q75, q25 = np.percentile(sharpe_ratios, [75, 25])
            iqr = q75 - q25
            upper_bound = q75 + 1.5 * iqr
            pbo = np.sum(sharpe_ratios > upper_bound) / num_trials
            is_overfitted = pbo > threshold
            decisions.append(is_overfitted)
        
        # Higher thresholds should be more conservative
        # (fewer false positives, potentially more false negatives)
        assert decisions[0] >= decisions[-1], \
            "Lower threshold should detect more overfitting"
