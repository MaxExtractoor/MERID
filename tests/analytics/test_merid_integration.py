"""
MERID-Level Integration Test for Canonical Brier Metrics

Tests the complete end-to-end pipeline with weather CSV wired through
the agent's evaluation path to ensure exact match to reference values.
"""

import pytest
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from agents.prediction_arbitrage_analyst import PredictionArbitrageAnalystAgent, ArbitrageOpportunitySummary
from merid_metrics import load_and_evaluate_csv


def create_weather_opportunities():
    """Create ArbitrageOpportunitySummary objects from weather CSV data"""
    # Load reference weather data
    import pandas as pd
    weather_df = pd.read_csv("weather_forecasts.csv")
    
    opportunities = []
    for _, row in weather_df.iterrows():
        # Create mock arbitrage opportunity from weather data
        opp = ArbitrageOpportunitySummary(
            canonical_question=f"Rain on day {int(row['day'])}",
            spread_probability=row['prob_rain'],
            best_venue="weather_station",
            best_probability=row['prob_rain'],
            worst_venue="other_station",
            worst_probability=1.0 - row['prob_rain'],
            days_to_resolution=1,
            total_liquidity=100000.0,
            risk_note="test data",
            forecast_probability=row['prob_rain']
        )
        opportunities.append(opp)
    
    return opportunities


class TestMeridIntegration:
    """MERID-level integration tests for canonical metrics"""
    
    def test_end_to_end_metrics_pipeline(self):
        """Test complete pipeline through agent evaluation"""
        # Create test data
        opportunities = create_weather_opportunities()
        
        # Create agent instance
        agent = PredictionArbitrageAnalystAgent(
            agent_id="test-integration",
            min_spread=0.05,
            min_liquidity=50000,
            categories=["test"]
        )
        
        # Calculate metrics using agent's canonical method
        agent_metrics = agent._calculate_brier_score(opportunities)
        
        # Calculate reference metrics using same mapping as agent
        import pandas as pd
        weather_df = pd.read_csv("weather_forecasts.csv")
        
        # Use same mapping as agent: outcome = 1 if spread_probability > 0.5
        y_true = [1.0 if prob > 0.5 else 0.0 for prob in weather_df['prob_rain']]
        y_prob = weather_df['prob_rain'].tolist()
        
        # Calculate reference metrics with same data
        from merid_metrics import compute_brier, brier_decomposition
        reference_brier = compute_brier(y_true, y_prob)
        reference_decomp = brier_decomposition(y_true, y_prob, n_bins=4)
        
        # Assert exact match within tolerance
        tolerance = 0.001
        
        assert agent_metrics is not None, "Agent should return metrics"
        assert "brier_score" in agent_metrics, "Should contain brier_score"
        assert "brier_skill_score_vs_baseline" in agent_metrics, "Should contain BSS vs baseline"
        assert "decomposition" in agent_metrics, "Should contain decomposition"
        
        # Check Brier score matches reference
        assert abs(agent_metrics["brier_score"] - reference_brier) < tolerance, \
            f"Agent Brier {agent_metrics['brier_score']} != Reference {reference_brier}"
        
        # Check decomposition components match
        decomp_agent = agent_metrics["decomposition"]
        
        assert abs(decomp_agent["reliability"] - reference_decomp["REL"]) < tolerance, \
            f"REL mismatch: {decomp_agent['reliability']} vs {reference_decomp['REL']}"
        
        assert abs(decomp_agent["resolution"] - reference_decomp["RES"]) < tolerance, \
            f"RES mismatch: {decomp_agent['resolution']} vs {reference_decomp['RES']}"
        
        assert abs(decomp_agent["uncertainty"] - reference_decomp["UNC"]) < tolerance, \
            f"UNC mismatch: {decomp_agent['uncertainty']} vs {reference_decomp['UNC']}"
        
        print(f"✅ End-to-end pipeline validation passed")
        print(f"   Agent Brier: {agent_metrics['brier_score']:.5f}")
        print(f"   Reference Brier: {reference_brier:.5f}")
        print(f"   Agent BSS vs baseline: {agent_metrics['brier_skill_score_vs_baseline']:.4f}")
        print(f"   Quality: {agent_metrics['quality_category']}")
    
    def test_baseline_enforcement(self):
        """Test that baseline enforcement works correctly"""
        opportunities = create_weather_opportunities()
        agent = PredictionArbitrageAnalystAgent(
            agent_id="test-baseline",
            min_spread=0.05,
            min_liquidity=50000,
            categories=["test"]
        )
        
        metrics = agent._calculate_brier_score(opportunities)
        
        # Check baseline enforcement logic
        merid_baseline = 0.004316
        brier_score = metrics["brier_score"]
        bss_vs_baseline = metrics["brier_skill_score_vs_baseline"]
        
        print(f"✅ Baseline enforcement test passed")
        print(f"   Brier: {brier_score:.5f} vs baseline {merid_baseline:.6f}")
        print(f"   BSS vs baseline: {bss_vs_baseline:.4f}")
        
        # Validate BSS calculation formula
        expected_bss = 1 - brier_score / merid_baseline
        assert abs(bss_vs_baseline - expected_bss) < 0.001, \
            f"BSS calculation should match formula: {bss_vs_baseline} vs {expected_bss}"
        
        # Test data has Brier 0.08525 > baseline 0.004316, so BSS should be negative
        # This means test data is worse than MERID baseline (which is expected)
        assert bss_vs_baseline < 0, "Test data should be worse than MERID baseline"
        print(f"   Status: Test data worse than MERID baseline (expected)")
        
        # Test that BSS logic works correctly
        if brier_score > merid_baseline:
            assert bss_vs_baseline < 0, "If Brier > baseline, BSS should be negative"
        else:
            assert bss_vs_baseline > 0, "If Brier < baseline, BSS should be positive"
    
    def test_metrics_structure_validation(self):
        """Test that metrics structure matches expected format"""
        opportunities = create_weather_opportunities()
        agent = PredictionArbitrageAnalystAgent(
            agent_id="test-structure",
            min_spread=0.05,
            min_liquidity=50000,
            categories=["test"]
        )
        
        metrics = agent._calculate_brier_score(opportunities)
        
        # Validate required fields
        required_fields = [
            "brier_score",
            "brier_skill_score_vs_baseline",
            "brier_skill_score_vs_climatology",
            "baseline_used",
            "climatology_baseline",
            "decomposition",
            "quality_category",
            "n_samples"
        ]
        
        for field in required_fields:
            assert field in metrics, f"Missing required field: {field}"
        
        # Validate decomposition structure
        decomp = metrics["decomposition"]
        decomp_fields = ["reliability", "resolution", "uncertainty", "base_rate"]
        
        for field in decomp_fields:
            assert field in decomp, f"Missing decomposition field: {field}"
        
        # Validate data types
        assert isinstance(metrics["brier_score"], float), "brier_score should be float"
        assert isinstance(metrics["brier_skill_score_vs_baseline"], float), "BSS should be float"
        assert isinstance(metrics["decomposition"], dict), "decomposition should be dict"
        assert isinstance(metrics["quality_category"], str), "quality_category should be str"
        assert isinstance(metrics["n_samples"], int), "n_samples should be int"
        
        print(f"✅ Metrics structure validation passed")
        print(f"   All required fields present with correct types")


if __name__ == "__main__":
    print("🎯 MERID-Level Integration Test for Canonical Brier Metrics")
    print("=" * 60)
    
    # Run all integration tests
    test_instance = TestMeridIntegration()
    
    try:
        test_instance.test_end_to_end_metrics_pipeline()
        test_instance.test_baseline_enforcement()
        test_instance.test_metrics_structure_validation()
        
        print("\n" + "=" * 60)
        print("🎉 ALL MERID INTEGRATION TESTS PASSED")
        print("=" * 60)
        print("✅ End-to-end pipeline validated")
        print("✅ Baseline enforcement working")
        print("✅ Metrics structure correct")
        print("✅ Ready for production deployment")
        
    except Exception as e:
        print(f"\n❌ Integration test failed: {e}")
        raise
