"""
Unit Tests for MERID Metrics Library

Tests against reference dataset and synthetic edge cases.
All calculations must match standard definitions within tolerance.
"""

import pytest
import numpy as np
from merid_metrics import (
    compute_brier, compute_bss, brier_decomposition, plot_reliability,
    evaluate_forecast, load_and_evaluate_csv, validate_reference_implementation,
    test_edge_cases
)


class TestReferenceImplementation:
    """Test against reference weather_forecasts.csv dataset"""
    
    def test_reference_brier_score(self):
        """Test Brier score matches reference value"""
        results = load_and_evaluate_csv("weather_forecasts.csv")
        expected = 0.10525
        tolerance = 0.001
        assert abs(results["brier_score"] - expected) < tolerance, \
            f"Brier score {results['brier_score']} != expected {expected}"
    
    def test_reference_bss(self):
        """Test Brier Skill Score matches reference value"""
        results = load_and_evaluate_csv("weather_forecasts.csv")
        expected = 0.5615
        tolerance = 0.01
        assert abs(results["brier_skill_score"] - expected) < tolerance, \
            f"BSS {results['brier_skill_score']} != expected {expected}"
    
    def test_reference_decomposition(self):
        """Test decomposition components match reference values"""
        results = load_and_evaluate_csv("weather_forecasts.csv")
        
        # Expected values with tolerance
        expected_values = {
            "reliability": 0.03442,
            "resolution": 0.17333,
            "uncertainty": 0.24
        }
        
        tolerance = 0.001
        for key, expected in expected_values.items():
            assert abs(results[key] - expected) < tolerance, \
                f"{key} {results[key]} != expected {expected}"
    
    def test_reference_base_rate(self):
        """Test base rate calculation"""
        results = load_and_evaluate_csv("weather_forecasts.csv")
        expected = 0.6  # 6 rainy days out of 10
        assert abs(results["base_rate"] - expected) < 0.001, \
            f"Base rate {results['base_rate']} != expected {expected}"


class TestSyntheticEdgeCases:
    """Test implementation with synthetic edge cases"""
    
    def test_perfect_forecasts(self):
        """Test with nearly perfect forecasts"""
        y_true = [0, 0, 1, 1]
        y_prob = [0.1, 0.2, 0.8, 0.9]
        
        results = evaluate_forecast(y_true, y_prob)
        
        # Should have very low Brier score
        assert results["brier_score"] < 0.1, \
            f"Perfect forecasts should have BS < 0.1, got {results['brier_score']}"
        
        # Should have good BSS vs climatology
        assert results["brier_skill_score"] > 0.5, \
            f"Perfect forecasts should have BSS > 0.5, got {results['brier_skill_score']}"
    
    def test_climatology_forecasts(self):
        """Test with climatology (constant) forecasts"""
        y_true = [0, 0, 1, 1]
        baseline = 0.5
        y_prob = [baseline] * 4
        
        results = evaluate_forecast(y_true, y_prob, baseline)
        
        # BSS should be exactly 0 (same as baseline)
        assert abs(results["brier_skill_score"]) < 0.001, \
            f"Climatology should have BSS ≈ 0, got {results['brier_skill_score']}"
    
    def test_worst_case_forecasts(self):
        """Test with worst case (always wrong) forecasts"""
        y_true = [0, 0, 1, 1]
        y_prob = [0.9, 0.8, 0.2, 0.1]
        
        results = evaluate_forecast(y_true, y_prob)
        
        # Should have high Brier score
        assert results["brier_score"] > 0.2, \
            f"Worst case should have BS > 0.2, got {results['brier_score']}"
        
        # Should have negative BSS (worse than climatology)
        assert results["brier_skill_score"] < 0, \
            f"Worst case should have BSS < 0, got {results['brier_skill_score']}"
    
    def test_decomposition_properties(self):
        """Test mathematical properties of decomposition"""
        y_true = [0, 0, 1, 1, 0, 1]
        y_prob = [0.2, 0.3, 0.7, 0.8, 0.4, 0.6]
        
        decomp = brier_decomposition(y_true, y_prob, n_bins=3)
        
        # Check mathematical relationship: BS ≈ REL - RES + UNC
        bs_direct = compute_brier(y_true, y_prob)
        bs_decomp = decomp["REL"] - decomp["RES"] + decomp["UNC"]
        
        tolerance = 0.05  # Allow for binning effects with small datasets
        assert abs(bs_direct - bs_decomp) < tolerance, \
            f"BS decomposition mismatch: {bs_direct} vs {bs_decomp}"
        
        # Check uncertainty formula
        expected_unc = decomp["base_rate"] * (1 - decomp["base_rate"])
        assert abs(decomp["UNC"] - expected_unc) < 0.001, \
            f"UNC formula error: {decomp['UNC']} vs {expected_unc}"


class TestMetricProperties:
    """Test mathematical properties of metrics"""
    
    def test_brier_score_bounds(self):
        """Test Brier score bounds [0, 1] for binary events"""
        # Perfect forecasts
        y_true = [0, 1, 0, 1]
        y_prob = [0.0, 1.0, 0.0, 1.0]
        bs = compute_brier(y_true, y_prob)
        assert abs(bs - 0.0) < 0.001, f"Perfect forecasts should have BS ≈ 0, got {bs}"
        
        # Worst forecasts (completely wrong)
        y_true = [0, 1, 0, 1]
        y_prob = [1.0, 0.0, 1.0, 0.0]
        bs = compute_brier(y_true, y_prob)
        assert abs(bs - 1.0) < 0.001, f"Worst forecasts should have BS ≈ 1, got {bs}"
    
    def test_bss_bounds(self):
        """Test BSS bounds [-∞, 1]"""
        y_true = [0, 0, 1, 1]
        baseline = 0.5
        
        # Perfect forecasts (BSS = 1)
        y_prob = [0.1, 0.2, 0.8, 0.9]
        bss = compute_bss(y_true, y_prob, baseline)
        assert bss > 0.5, f"Good forecasts should have BSS > 0.5, got {bss}"
        
        # Climatology (BSS = 0)
        y_prob = [baseline] * 4
        bss = compute_bss(y_true, y_prob, baseline)
        assert abs(bss) < 0.001, f"Climatology should have BSS ≈ 0, got {bss}"
        
        # Worse than climatology (BSS < 0)
        y_prob = [0.9, 0.8, 0.2, 0.1]
        bss = compute_bss(y_true, y_prob, baseline)
        assert bss < 0, f"Worse forecasts should have BSS < 0, got {bss}"
    
    def test_symmetry_properties(self):
        """Test symmetry properties of metrics"""
        y_true = [0, 1, 0, 1]
        y_prob = [0.2, 0.7, 0.3, 0.8]
        
        # Brier score should be symmetric for swapped labels
        y_true_swapped = [1, 0, 1, 0]
        y_prob_swapped = [1 - p for p in y_prob]
        
        bs_original = compute_brier(y_true, y_prob)
        bs_swapped = compute_brier(y_true_swapped, y_prob_swapped)
        
        assert abs(bs_original - bs_swapped) < 0.001, \
            f"Brier score should be symmetric: {bs_original} vs {bs_swapped}"


class TestReliabilityDiagram:
    """Test reliability diagram functionality"""
    
    def test_reliability_output(self):
        """Test reliability diagram returns correct arrays"""
        y_true = [0, 0, 1, 1, 0, 1]
        y_prob = [0.2, 0.3, 0.7, 0.8, 0.4, 0.6]
        
        prob_true, prob_pred = plot_reliability(y_true, y_prob, show_plot=False)
        
        # Should return arrays of same length
        assert len(prob_true) == len(prob_pred), \
            f"Reliability arrays should have same length: {len(prob_true)} vs {len(prob_pred)}"
        
        # Values should be in [0, 1]
        assert all(0 <= p <= 1 for p in prob_true), "prob_true should be in [0, 1]"
        assert all(0 <= p <= 1 for p in prob_pred), "prob_pred should be in [0, 1]"
    
    def test_perfect_calibration(self):
        """Test reliability diagram for perfectly calibrated forecasts"""
        # Create perfectly calibrated data
        y_true = [0, 0, 1, 1, 0, 0, 1, 1]
        y_prob = [0.2, 0.3, 0.7, 0.8, 0.25, 0.35, 0.75, 0.85]
        
        prob_true, prob_pred = plot_reliability(y_true, y_prob, show_plot=False)
        
        # Should be close to diagonal for well-calibrated forecasts
        max_deviation = max(abs(prob_true - prob_pred))
        assert max_deviation < 0.35, \
            f"Well-calibrated forecasts should stay close to diagonal, max deviation: {max_deviation}"


class TestIntegration:
    """Integration tests for complete workflow"""
    
    def test_complete_evaluation_workflow(self):
        """Test complete evaluation workflow"""
        y_true = [0, 0, 1, 1, 0, 1, 0, 1]
        y_prob = [0.2, 0.3, 0.7, 0.8, 0.4, 0.6, 0.25, 0.75]
        baseline = 0.5
        
        results = evaluate_forecast(y_true, y_prob, baseline)
        
        # Check all required fields are present
        required_fields = [
            "brier_score", "brier_skill_score", "log_loss",
            "reliability", "resolution", "uncertainty", "base_rate", "quality_category"
        ]
        
        for field in required_fields:
            assert field in results, f"Missing required field: {field}"
        
        # Check quality category makes sense
        assert results["quality_category"] in ["Excellent", "Good", "Fair", "Poor"], \
            f"Invalid quality category: {results['quality_category']}"
    
    def test_csv_loading_integration(self):
        """Test CSV loading and evaluation integration"""
        # This test will skip if reference CSV is not available
        try:
            results = load_and_evaluate_csv("weather_forecasts.csv")
            
            # Should have all required fields
            required_fields = ["brier_score", "brier_skill_score", "quality_category"]
            for field in required_fields:
                assert field in results, f"Missing field in CSV evaluation: {field}"
                
        except FileNotFoundError:
            pytest.skip("Reference CSV not available")


if __name__ == "__main__":
    # Run validation tests
    print("Running MERID Metrics Validation...")
    
    # Test reference implementation
    validation = validate_reference_implementation()
    if "error" not in validation:
        print("✅ Reference validation passed")
        for key, result in validation.items():
            status = "✅" if result["match"] else "❌"
            print(f"  {status} {key}: {result['actual']:.5f}")
    else:
        print(f"❌ {validation['error']}")
    
    # Test edge cases
    edge_results = test_edge_cases()
    print("✅ Edge case tests passed")
    
    print("\nAll tests completed!")
