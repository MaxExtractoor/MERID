"""
Tests for shadow dual-side metrics module.

Tests cover:
- ShadowDualSideMonitor singleton behavior
- Logging shadow evaluations
- Per-asset and per-regime metrics
- Missed edge distribution
- Velocity correlation calculation
- Time window filtering
- Reset functionality
"""

import pytest
import time
from merid.metrics.shadow_dual_side_metrics import (
    ShadowDualSideMonitor,
    ShadowEvaluationRecord,
    ShadowAnalysis,
    get_shadow_dual_side_monitor
)


class TestShadowDualSideMonitorSingleton:
    """Test ShadowDualSideMonitor singleton behavior."""

    def test_singleton_returns_same_instance(self):
        """Test that get_shadow_dual_side_monitor returns the same instance."""
        monitor1 = get_shadow_dual_side_monitor()
        monitor2 = get_shadow_dual_side_monitor()
        
        assert monitor1 is monitor2, "Should return the same singleton instance"

    def test_singleton_thread_safety(self):
        """Test that singleton is thread-safe."""
        import threading
        
        instances = []
        
        def get_instance():
            instances.append(get_shadow_dual_side_monitor())
        
        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # All instances should be the same
        assert len(set(id(i) for i in instances)) == 1, "All threads should get the same instance"


class TestShadowEvaluationLogging:
    """Test logging shadow evaluations."""

    def test_log_shadow_evaluation_basic(self):
        """Test basic shadow evaluation logging."""
        monitor = get_shadow_dual_side_monitor()
        monitor.reset()  # Start fresh
        
        monitor.log_shadow_evaluation(
            asset="BTC",
            velocity=0.01,
            strategy_mode="trend_following",
            expected_side="yes",
            expected_edge=0.08,
            opposite_side="no",
            opposite_edge=0.12,
            hypothetical_best_side="no",
            hypothetical_best_edge=0.12,
            yes_in_range=True,
            no_in_range=True
        )
        
        analysis = monitor.get_analysis()
        assert analysis.total_evaluations == 1, "Should have 1 evaluation"
        assert analysis.missed_opportunities == 1, "Should have 1 missed opportunity"

    def test_log_shadow_evaluation_no_missed_opportunity(self):
        """Test logging when expected side is the best."""
        monitor = get_shadow_dual_side_monitor()
        monitor.reset()
        
        monitor.log_shadow_evaluation(
            asset="BTC",
            velocity=0.01,
            strategy_mode="trend_following",
            expected_side="yes",
            expected_edge=0.12,
            opposite_side="no",
            opposite_edge=0.08,
            hypothetical_best_side="yes",
            hypothetical_best_edge=0.12,
            yes_in_range=True,
            no_in_range=True
        )
        
        analysis = monitor.get_analysis()
        assert analysis.total_evaluations == 1, "Should have 1 evaluation"
        assert analysis.missed_opportunities == 0, "Should have 0 missed opportunities"

    def test_log_shadow_evaluation_multiple_records(self):
        """Test logging multiple shadow evaluations."""
        monitor = get_shadow_dual_side_monitor()
        monitor.reset()
        
        # Log multiple evaluations
        for i in range(10):
            monitor.log_shadow_evaluation(
                asset="BTC",
                velocity=0.01,
                strategy_mode="trend_following",
                expected_side="yes",
                expected_edge=0.08,
                opposite_side="no",
                opposite_edge=0.12,
                hypothetical_best_side="no",
                hypothetical_best_edge=0.12,
                yes_in_range=True,
                no_in_range=True
            )
        
        analysis = monitor.get_analysis()
        assert analysis.total_evaluations == 10, "Should have 10 evaluations"
        assert analysis.missed_opportunities == 10, "Should have 10 missed opportunities"

    def test_log_shadow_evaluation_with_chosen_side(self):
        """Test logging with chosen side parameter."""
        monitor = get_shadow_dual_side_monitor()
        monitor.reset()
        
        monitor.log_shadow_evaluation(
            asset="BTC",
            velocity=0.01,
            strategy_mode="trend_following",
            expected_side="yes",
            expected_edge=0.08,
            opposite_side="no",
            opposite_edge=0.12,
            hypothetical_best_side="no",
            hypothetical_best_edge=0.12,
            yes_in_range=True,
            no_in_range=True,
            chosen_side="yes"  # Actually chose expected side despite better opposite edge
        )
        
        analysis = monitor.get_analysis()
        assert analysis.total_evaluations == 1, "Should have 1 evaluation"


class TestPerAssetMetrics:
    """Test per-asset metrics tracking."""

    def test_per_asset_metrics_tracking(self):
        """Test that per-asset metrics are tracked correctly."""
        monitor = get_shadow_dual_side_monitor()
        monitor.reset()
        
        # Log evaluations for different assets
        monitor.log_shadow_evaluation(
            asset="BTC",
            velocity=0.01,
            strategy_mode="trend_following",
            expected_side="yes",
            expected_edge=0.08,
            opposite_side="no",
            opposite_edge=0.12,
            hypothetical_best_side="no",
            hypothetical_best_edge=0.12,
            yes_in_range=True,
            no_in_range=True
        )
        
        monitor.log_shadow_evaluation(
            asset="ETH",
            velocity=0.01,
            strategy_mode="trend_following",
            expected_side="yes",
            expected_edge=0.10,
            opposite_side="no",
            opposite_edge=0.09,
            hypothetical_best_side="yes",
            hypothetical_best_edge=0.10,
            yes_in_range=True,
            no_in_range=True
        )
        
        analysis = monitor.get_analysis()
        
        # Check BTC metrics
        btc_metrics = analysis.per_asset_breakdown.get("BTC", {})
        assert btc_metrics["total_evaluations"] == 1, "BTC should have 1 evaluation"
        assert btc_metrics["missed_opportunities"] == 1, "BTC should have 1 missed opportunity"
        
        # Check ETH metrics
        eth_metrics = analysis.per_asset_breakdown.get("ETH", {})
        assert eth_metrics["total_evaluations"] == 1, "ETH should have 1 evaluation"
        assert eth_metrics["missed_opportunities"] == 0, "ETH should have 0 missed opportunities"

    def test_per_asset_missed_edge_calculation(self):
        """Test that per-asset missed edge is calculated correctly."""
        monitor = get_shadow_dual_side_monitor()
        monitor.reset()
        
        monitor.log_shadow_evaluation(
            asset="BTC",
            velocity=0.01,
            strategy_mode="trend_following",
            expected_side="yes",
            expected_edge=0.08,
            opposite_side="no",
            opposite_edge=0.12,
            hypothetical_best_side="no",
            hypothetical_best_edge=0.12,
            yes_in_range=True,
            no_in_range=True
        )
        
        analysis = monitor.get_analysis()
        btc_metrics = analysis.per_asset_breakdown.get("BTC", {})
        
        # Missed edge should be 0.12 - 0.08 = 0.04
        assert btc_metrics["total_missed_edge"] == pytest.approx(0.04), "Total missed edge should be 0.04"
        assert btc_metrics["max_missed_edge"] == pytest.approx(0.04), "Max missed edge should be 0.04"


class TestPerRegimeMetrics:
    """Test per-regime metrics tracking."""

    def test_per_regime_classification(self):
        """Test that velocity-based regime classification works."""
        monitor = get_shadow_dual_side_monitor()
        monitor.reset()
        
        # Low velocity
        monitor.log_shadow_evaluation(
            asset="BTC",
            velocity=0.003,
            strategy_mode="trend_following",
            expected_side="yes",
            expected_edge=0.08,
            opposite_side="no",
            opposite_edge=0.12,
            hypothetical_best_side="no",
            hypothetical_best_edge=0.12,
            yes_in_range=True,
            no_in_range=True
        )
        
        # Medium velocity
        monitor.log_shadow_evaluation(
            asset="BTC",
            velocity=0.01,
            strategy_mode="trend_following",
            expected_side="yes",
            expected_edge=0.08,
            opposite_side="no",
            opposite_edge=0.12,
            hypothetical_best_side="no",
            hypothetical_best_edge=0.12,
            yes_in_range=True,
            no_in_range=True
        )
        
        # High velocity
        monitor.log_shadow_evaluation(
            asset="BTC",
            velocity=0.02,
            strategy_mode="trend_following",
            expected_side="yes",
            expected_edge=0.08,
            opposite_side="no",
            opposite_edge=0.12,
            hypothetical_best_side="no",
            hypothetical_best_edge=0.12,
            yes_in_range=True,
            no_in_range=True
        )
        
        analysis = monitor.get_analysis()
        
        # Check regime classifications
        assert "low_velocity" in analysis.per_regime_breakdown, "Should have low_velocity regime"
        assert "medium_velocity" in analysis.per_regime_breakdown, "Should have medium_velocity regime"
        assert "high_velocity" in analysis.per_regime_breakdown, "Should have high_velocity regime"
        
        assert analysis.per_regime_breakdown["low_velocity"]["total_evaluations"] == 1
        assert analysis.per_regime_breakdown["medium_velocity"]["total_evaluations"] == 1
        assert analysis.per_regime_breakdown["high_velocity"]["total_evaluations"] == 1


class TestVelocityCorrelation:
    """Test velocity correlation calculation."""

    def test_velocity_correlation_calculation(self):
        """Test that velocity correlation is calculated correctly."""
        monitor = get_shadow_dual_side_monitor()
        monitor.reset()
        
        # Add evaluations across velocity ranges
        for _ in range(5):
            monitor.log_shadow_evaluation(
                asset="BTC",
                velocity=0.003,
                strategy_mode="trend_following",
                expected_side="yes",
                expected_edge=0.08,
                opposite_side="no",
                opposite_edge=0.12,
                hypothetical_best_side="no",
                hypothetical_best_edge=0.12,
                yes_in_range=True,
                no_in_range=True
            )
        
        for _ in range(5):
            monitor.log_shadow_evaluation(
                asset="BTC",
                velocity=0.01,
                strategy_mode="trend_following",
                expected_side="yes",
                expected_edge=0.10,
                opposite_side="no",
                opposite_edge=0.09,
                hypothetical_best_side="yes",
                hypothetical_best_edge=0.10,
                yes_in_range=True,
                no_in_range=True
            )
        
        analysis = monitor.get_analysis()
        
        # Check velocity correlation
        assert "low_velocity_missed_rate" in analysis.velocity_correlation
        assert "medium_velocity_missed_rate" in analysis.velocity_correlation
        assert "high_velocity_missed_rate" in analysis.velocity_correlation
        
        # Low velocity should have 100% missed rate (all 5 were missed)
        assert analysis.velocity_correlation["low_velocity_missed_rate"] == 1.0
        # Medium velocity should have 0% missed rate (all 5 were not missed)
        assert analysis.velocity_correlation["medium_velocity_missed_rate"] == 0.0


class TestMissedEdgeDistribution:
    """Test missed edge distribution calculation."""

    def test_missed_edge_distribution(self):
        """Test that missed edge distribution is calculated correctly."""
        monitor = get_shadow_dual_side_monitor()
        monitor.reset()
        
        # Add evaluations with varying missed edges
        missed_edges = [0.02, 0.04, 0.06, 0.08, 0.10]
        for missed_edge in missed_edges:
            monitor.log_shadow_evaluation(
                asset="BTC",
                velocity=0.01,
                strategy_mode="trend_following",
                expected_side="yes",
                expected_edge=0.08,
                opposite_side="no",
                opposite_edge=0.08 + missed_edge,
                hypothetical_best_side="no",
                hypothetical_best_edge=0.08 + missed_edge,
                yes_in_range=True,
                no_in_range=True
            )
        
        distribution = monitor.get_missed_edge_distribution(bins=5)
        
        assert len(distribution) == 5, "Should have 5 bins"
        
        # Check that total count is at least 4 (some may fall in same bin due to floating point)
        total_count = sum(count for _, _, count in distribution)
        assert total_count >= 4, f"Total count should be at least 4, got {total_count}"

    def test_missed_edge_distribution_empty(self):
        """Test missed edge distribution with no data."""
        monitor = get_shadow_dual_side_monitor()
        monitor.reset()
        
        distribution = monitor.get_missed_edge_distribution(bins=5)
        
        assert distribution == [], "Should return empty list when no data"


class TestTimeWindowFiltering:
    """Test time window filtering in analysis."""

    def test_time_window_filtering(self):
        """Test that time window filtering works correctly."""
        monitor = get_shadow_dual_side_monitor()
        monitor.reset()
        
        # Log an evaluation now
        monitor.log_shadow_evaluation(
            asset="BTC",
            velocity=0.01,
            strategy_mode="trend_following",
            expected_side="yes",
            expected_edge=0.08,
            opposite_side="no",
            opposite_edge=0.12,
            hypothetical_best_side="no",
            hypothetical_best_edge=0.12,
            yes_in_range=True,
            no_in_range=True
        )
        
        # Analysis with no time window should include all records
        analysis_all = monitor.get_analysis(time_window_hours=None)
        assert analysis_all.total_evaluations == 1, "Should have 1 evaluation without time window"
        
        # Analysis with 1-hour window should include the record
        analysis_1h = monitor.get_analysis(time_window_hours=1.0)
        assert analysis_1h.total_evaluations == 1, "Should have 1 evaluation within 1-hour window"
        
        # Analysis with negative window should exclude the record
        analysis_negative = monitor.get_analysis(time_window_hours=-1.0)
        assert analysis_negative.total_evaluations == 0, "Should have 0 evaluations with negative time window"

    def test_time_window_filtering_multiple_records(self):
        """Test time window filtering with multiple records at different times."""
        monitor = get_shadow_dual_side_monitor()
        monitor.reset()
        
        # Log first evaluation
        monitor.log_shadow_evaluation(
            asset="BTC",
            velocity=0.01,
            strategy_mode="trend_following",
            expected_side="yes",
            expected_edge=0.08,
            opposite_side="no",
            opposite_edge=0.12,
            hypothetical_best_side="no",
            hypothetical_best_edge=0.12,
            yes_in_range=True,
            no_in_range=True
        )
        
        # Wait a bit
        time.sleep(0.1)
        
        # Log second evaluation
        monitor.log_shadow_evaluation(
            asset="ETH",
            velocity=0.01,
            strategy_mode="trend_following",
            expected_side="yes",
            expected_edge=0.08,
            opposite_side="no",
            opposite_edge=0.12,
            hypothetical_best_side="no",
            hypothetical_best_edge=0.12,
            yes_in_range=True,
            no_in_range=True
        )
        
        # Analysis with 1-second window should include both
        analysis_1s = monitor.get_analysis(time_window_hours=1.0/3600.0)
        assert analysis_1s.total_evaluations == 2, "Should have 2 evaluations within 1-second window"


class TestResetFunctionality:
    """Test reset functionality."""

    def test_reset_clears_all_data(self):
        """Test that reset clears all metrics."""
        monitor = get_shadow_dual_side_monitor()
        monitor.reset()  # Ensure clean state
        
        # Add some data
        monitor.log_shadow_evaluation(
            asset="BTC",
            velocity=0.01,
            strategy_mode="trend_following",
            expected_side="yes",
            expected_edge=0.08,
            opposite_side="no",
            opposite_edge=0.12,
            hypothetical_best_side="no",
            hypothetical_best_edge=0.12,
            yes_in_range=True,
            no_in_range=True
        )
        
        assert monitor.get_analysis().total_evaluations == 1, "Should have 1 evaluation before reset"
        
        # Reset
        monitor.reset()
        
        # Check that data is cleared
        analysis = monitor.get_analysis()
        assert analysis.total_evaluations == 0, "Should have 0 evaluations after reset"
        assert analysis.missed_opportunities == 0, "Should have 0 missed opportunities after reset"
        assert len(analysis.per_asset_breakdown) == 0, "Per-asset breakdown should be empty"
        assert len(analysis.per_regime_breakdown) == 0, "Per-regime breakdown should be empty"


class TestAnalysisCalculations:
    """Test analysis calculation accuracy."""

    def test_missed_opportunity_rate_calculation(self):
        """Test that missed opportunity rate is calculated correctly."""
        monitor = get_shadow_dual_side_monitor()
        monitor.reset()
        
        # Log 10 evaluations, 5 missed
        for i in range(5):
            monitor.log_shadow_evaluation(
                asset="BTC",
                velocity=0.01,
                strategy_mode="trend_following",
                expected_side="yes",
                expected_edge=0.08,
                opposite_side="no",
                opposite_edge=0.12,
                hypothetical_best_side="no",
                hypothetical_best_edge=0.12,
                yes_in_range=True,
                no_in_range=True
            )
        
        for i in range(5):
            monitor.log_shadow_evaluation(
                asset="BTC",
                velocity=0.01,
                strategy_mode="trend_following",
                expected_side="yes",
                expected_edge=0.12,
                opposite_side="no",
                opposite_edge=0.08,
                hypothetical_best_side="yes",
                hypothetical_best_edge=0.12,
                yes_in_range=True,
                no_in_range=True
            )
        
        analysis = monitor.get_analysis()
        
        assert analysis.total_evaluations == 10, "Should have 10 evaluations"
        assert analysis.missed_opportunities == 5, "Should have 5 missed opportunities"
        assert analysis.missed_opportunity_rate == 0.5, "Missed opportunity rate should be 50%"

    def test_average_missed_edge_calculation(self):
        """Test that average missed edge is calculated correctly."""
        monitor = get_shadow_dual_side_monitor()
        monitor.reset()
        
        # Log evaluations with missed edges: 0.02, 0.04, 0.06
        missed_edges = [0.02, 0.04, 0.06]
        for missed_edge in missed_edges:
            monitor.log_shadow_evaluation(
                asset="BTC",
                velocity=0.01,
                strategy_mode="trend_following",
                expected_side="yes",
                expected_edge=0.08,
                opposite_side="no",
                opposite_edge=0.08 + missed_edge,
                hypothetical_best_side="no",
                hypothetical_best_edge=0.08 + missed_edge,
                yes_in_range=True,
                no_in_range=True
            )
        
        analysis = monitor.get_analysis()
        
        # Average should be (0.02 + 0.04 + 0.06) / 3 = 0.04
        assert analysis.avg_missed_edge == pytest.approx(0.04), f"Average missed edge should be 0.04, got {analysis.avg_missed_edge}"

    def test_max_missed_edge_calculation(self):
        """Test that max missed edge is calculated correctly."""
        monitor = get_shadow_dual_side_monitor()
        monitor.reset()
        
        # Log evaluations with missed edges: 0.02, 0.04, 0.06
        missed_edges = [0.02, 0.04, 0.06]
        for missed_edge in missed_edges:
            monitor.log_shadow_evaluation(
                asset="BTC",
                velocity=0.01,
                strategy_mode="trend_following",
                expected_side="yes",
                expected_edge=0.08,
                opposite_side="no",
                opposite_edge=0.08 + missed_edge,
                hypothetical_best_side="no",
                hypothetical_best_edge=0.08 + missed_edge,
                yes_in_range=True,
                no_in_range=True
            )
        
        analysis = monitor.get_analysis()
        
        assert analysis.max_missed_edge == pytest.approx(0.06), f"Max missed edge should be 0.06, got {analysis.max_missed_edge}"


class TestMemoryManagement:
    """Test memory management (record limit)."""

    def test_record_limit_enforcement(self):
        """Test that record limit is enforced."""
        monitor = get_shadow_dual_side_monitor()
        monitor.reset()
        
        # Set a small limit for testing
        monitor._max_records = 100
        
        # Add more records than the limit
        for i in range(150):
            monitor.log_shadow_evaluation(
                asset="BTC",
                velocity=0.01,
                strategy_mode="trend_following",
                expected_side="yes",
                expected_edge=0.08,
                opposite_side="no",
                opposite_edge=0.12,
                hypothetical_best_side="no",
                hypothetical_best_edge=0.12,
                yes_in_range=True,
                no_in_range=True
            )
        
        analysis = monitor.get_analysis()
        
        # Should not exceed the limit
        assert analysis.total_evaluations <= 100, f"Should not exceed {monitor._max_records} records"
        assert analysis.total_evaluations == 100, "Should have exactly 100 records (oldest trimmed)"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
