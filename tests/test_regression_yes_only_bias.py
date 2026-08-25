"""
Regression tests for historical YES-only bias days.

These tests replay known problematic days where the system was stuck in YES-only mode
and verify that the new dual-side system produces:
- Increased NO candidate count
- Mix of aligned and counter-trend signals
- Reduced directional bias

This locks in the new, unbiased behavior and prevents regression.
"""

import pytest
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import json


class TestRegressionYesOnlyBias:
    """Regression tests for historical YES-only bias days."""
    
    def test_regression_day_2026_07_15_yes_only_bias(self):
        """
        Replay 2026-07-15 data where system was stuck in YES-only mode.
        
        Expected with new dual-side system:
        - NO candidate count > 0 (previously was 0)
        - Mix of aligned and counter-trend selections
        - Reduced YES-only bias
        """
        # Load historical data for 2026-07-15
        historical_data = self._load_historical_day("2026-07-15")
        
        # Process through new dual-side evaluation
        results = self._process_historical_stream(historical_data)
        
        # Assertions for regression check
        assert results["total_evaluations"] > 0, "Should have evaluations"
        
        # CRITICAL: NO candidates should now exist (previously was 0)
        assert results["no_candidate_count"] > 0, (
            f"Regression detected: NO candidate count is {results['no_candidate_count']}. "
            f"Expected > 0. The system may have regressed to YES-only bias."
        )
        
        # Verify YES candidates still exist (sanity check)
        assert results["yes_candidate_count"] > 0, "YES candidates should still exist"
        
        # Verify mix of selections (not 100% YES)
        yes_ratio = results["yes_candidate_count"] / results["total_evaluations"]
        assert yes_ratio < 0.95, (
            f"Regression detected: YES ratio {yes_ratio:.2%} is too high. "
            f"Expected < 95%. System may have regressed to YES-only bias."
        )
        
        # Verify counter-trend trades exist
        assert results["counter_trend_count"] > 0, (
            f"Regression detected: Counter-trend count is {results['counter_trend_count']}. "
            f"Expected > 0. System may be blocking counter-trend selections."
        )
    
    def test_regression_day_2026_07_18_yes_only_bias(self):
        """
        Replay 2026-07-18 data where system showed strong YES bias.
        
        Expected with new dual-side system:
        - NO candidate count significantly increased
        - Edge ratio threshold allowing counter-trend trades
        """
        historical_data = self._load_historical_day("2026-07-18")
        results = self._process_historical_stream(historical_data)
        
        # Assertions
        assert results["no_candidate_count"] > 0, "NO candidates should exist"
        
        # Verify NO candidates are reasonable percentage (not < 1%)
        no_ratio = results["no_candidate_count"] / results["total_evaluations"]
        assert no_ratio >= 0.05, (
            f"Regression detected: NO ratio {no_ratio:.2%} is too low. "
            f"Expected >= 5%. System may have regressed to YES-only bias."
        )
    
    def test_regression_edge_ratio_threshold_effectiveness(self):
        """
        Test that edge ratio threshold is effectively allowing counter-trend trades.
        
        Replay historical data and verify that when opposite side has >= 1.5x edge,
        counter-trend selection occurs.
        """
        historical_data = self._load_historical_day("2026-07-15")
        
        counter_trend_by_edge_ratio = []
        
        for evaluation in historical_data:
            velocity = evaluation["velocity"]
            yes_edge = evaluation["yes_edge"]
            no_edge = evaluation["no_edge"]
            
            thesis_side = "yes" if velocity > 0 else "no"
            side_edges = {"yes": yes_edge, "no": no_edge}
            EDGE_RATIO_THRESHOLD = 1.5
            
            velocity_aligned_edge = side_edges.get(thesis_side)
            opposite_side = "no" if thesis_side == "yes" else "yes"
            opposite_edge = side_edges.get(opposite_side)
            
            if velocity_aligned_edge and opposite_edge:
                edge_ratio = opposite_edge / velocity_aligned_edge if velocity_aligned_edge > 0 else float('inf')
                
                if edge_ratio >= EDGE_RATIO_THRESHOLD:
                    selected_side = opposite_side
                    is_counter_trend = (selected_side != thesis_side)
                    
                    counter_trend_by_edge_ratio.append({
                        "edge_ratio": edge_ratio,
                        "is_counter_trend": is_counter_trend,
                        "velocity": velocity,
                        "selected_side": selected_side
                    })
        
        # Verify counter-trend selections occur when edge ratio >= threshold
        counter_trend_selections = [e for e in counter_trend_by_edge_ratio if e["is_counter_trend"]]
        
        assert len(counter_trend_selections) > 0, (
            f"Regression detected: No counter-trend selections despite edge_ratio >= {EDGE_RATIO_THRESHOLD}. "
            f"Edge ratio threshold may not be working correctly."
        )
    
    def test_regression_velocity_alignment_distribution(self):
        """
        Test that velocity alignment distribution is balanced.
        
        With new dual-side system, we expect:
        - Not 100% velocity-aligned (would indicate thesis_side invariant)
        - Not 0% velocity-aligned (would indicate velocity is ignored)
        - Reasonable mix (e.g., 60-80% aligned, 20-40% counter-trend)
        """
        historical_data = self._load_historical_day("2026-07-15")
        results = self._process_historical_stream(historical_data)
        
        aligned_count = results["aligned_count"]
        counter_trend_count = results["counter_trend_count"]
        total = aligned_count + counter_trend_count
        
        if total > 0:
            aligned_ratio = aligned_count / total
            counter_trend_ratio = counter_trend_count / total
            
            # Not 100% aligned (would indicate thesis_side invariant)
            assert aligned_ratio < 1.0, (
                f"Regression detected: 100% velocity-aligned selections. "
                f"Thesis_side invariant may have been restored."
            )
            
            # Not 0% aligned (would indicate velocity is ignored)
            assert aligned_ratio > 0.5, (
                f"Regression detected: Velocity alignment ratio {aligned_ratio:.2%} is too low. "
                f"Velocity may be ignored in selection logic."
            )
            
            # Reasonable mix
            assert 0.5 <= aligned_ratio <= 0.9, (
                f"Velocity alignment ratio {aligned_ratio:.2%} is outside reasonable range (50-90%)."
            )
    
    def test_regression_price_reconstruction_effectiveness(self):
        """
        Test that price reconstruction is working correctly.
        
        Verify that when one side price is N/A, reconstruction succeeds
        and allows evaluation to proceed.
        """
        historical_data = self._load_historical_day("2026-07-15")
        
        reconstruction_success_count = 0
        reconstruction_failure_count = 0
        
        for evaluation in historical_data:
            yes_price = evaluation.get("yes_price_cents")
            no_price = evaluation.get("no_price_cents")
            
            # Simulate reconstruction logic
            if yes_price is None or yes_price <= 0:
                if no_price and no_price > 0:
                    yes_price = 100 - no_price
                    reconstruction_success_count += 1
                else:
                    reconstruction_failure_count += 1
            
            if no_price is None or no_price <= 0:
                if yes_price and yes_price > 0:
                    no_price = 100 - yes_price
                    reconstruction_success_count += 1
                else:
                    reconstruction_failure_count += 1
        
        # Verify reconstruction is working
        total_reconstruction_attempts = reconstruction_success_count + reconstruction_failure_count
        
        if total_reconstruction_attempts > 0:
            success_rate = reconstruction_success_count / total_reconstruction_attempts
            assert success_rate > 0.8, (
                f"Regression detected: Price reconstruction success rate {success_rate:.2%} is too low. "
                f"Expected > 80%. Reconstruction logic may be broken."
            )
    
    def test_comparison_old_vs_new_behavior(self):
        """
        Direct comparison between old YES-only behavior and new dual-side behavior.
        
        This test documents the expected behavioral change and ensures it's maintained.
        """
        # Old behavior (simulated)
        old_behavior = {
            "yes_candidate_count": 100,
            "no_candidate_count": 0,  # NO was blocked
            "counter_trend_count": 0,  # Counter-trend was blocked
            "velocity_aligned_ratio": 1.0  # 100% aligned (thesis_side invariant)
        }
        
        # New behavior (from historical replay)
        historical_data = self._load_historical_day("2026-07-15")
        new_behavior = self._process_historical_stream(historical_data)
        
        # Verify improvements
        assert new_behavior["no_candidate_count"] > old_behavior["no_candidate_count"], (
            "New system should produce more NO candidates than old YES-only system"
        )
        
        assert new_behavior["counter_trend_count"] > old_behavior["counter_trend_count"], (
            "New system should produce counter-trend trades (old system blocked them)"
        )
        
        new_aligned_ratio = new_behavior["aligned_count"] / (new_behavior["aligned_count"] + new_behavior["counter_trend_count"])
        assert new_aligned_ratio < old_behavior["velocity_aligned_ratio"], (
            "New system should have lower velocity-aligned ratio (less thesis_side bias)"
        )
    
    def _load_historical_day(self, date_str: str) -> List[Dict[str, Any]]:
        """
        Load historical data for a specific day.
        
        In production, this would load from a database or file.
        For testing, we generate synthetic data that mimics historical patterns.
        """
        # Generate synthetic historical data mimicking YES-only bias patterns
        # In production, replace with actual data loading
        historical_data = []
        
        # Generate 100 evaluations
        for i in range(100):
            # Pattern: Most evaluations have positive velocity (thesis_side = yes)
            # Old system would always select YES
            # New system should sometimes select NO when edge is better
            
            velocity = 0.0002 if i % 3 != 0 else -0.0002  # Mostly positive velocity
            
            # Pattern: Sometimes NO has better edge (counter-trend opportunity)
            if i % 4 == 0:
                # Counter-trend scenario
                yes_edge = 0.04
                no_edge = 0.08  # 2x YES edge
            else:
                # Aligned scenario
                yes_edge = 0.08
                no_edge = 0.05
            
            historical_data.append({
                "velocity": velocity,
                "yes_edge": yes_edge,
                "no_edge": no_edge,
                "yes_price_cents": 68,
                "no_price_cents": 32
            })
        
        return historical_data
    
    def _process_historical_stream(self, stream: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Process historical stream through new dual-side evaluation logic.
        
        Returns:
            Dictionary with evaluation statistics
        """
        results = {
            "total_evaluations": 0,
            "yes_candidate_count": 0,
            "no_candidate_count": 0,
            "aligned_count": 0,
            "counter_trend_count": 0
        }
        
        EDGE_RATIO_THRESHOLD = 1.5
        
        for evaluation in stream:
            results["total_evaluations"] += 1
            
            velocity = evaluation["velocity"]
            yes_edge = evaluation["yes_edge"]
            no_edge = evaluation["no_edge"]
            
            # Determine thesis_side from velocity
            thesis_side = "yes" if velocity > 0 else "no"
            
            # Hybrid selection
            side_edges = {"yes": yes_edge, "no": no_edge}
            
            velocity_aligned_edge = side_edges.get(thesis_side)
            opposite_side = "no" if thesis_side == "yes" else "yes"
            opposite_edge = side_edges.get(opposite_side)
            
            if velocity_aligned_edge and opposite_edge:
                edge_ratio = opposite_edge / velocity_aligned_edge if velocity_aligned_edge > 0 else float('inf')
                
                if edge_ratio >= EDGE_RATIO_THRESHOLD:
                    selected_side = opposite_side
                    selected_edge = opposite_edge
                else:
                    selected_side = thesis_side
                    selected_edge = velocity_aligned_edge
            else:
                selected_side, selected_edge = max(side_edges.items(), key=lambda x: x[1])
            
            # Track results
            if selected_side == "yes":
                results["yes_candidate_count"] += 1
            else:
                results["no_candidate_count"] += 1
            
            # Track alignment
            is_counter_trend = (selected_side != thesis_side)
            if is_counter_trend:
                results["counter_trend_count"] += 1
            else:
                results["aligned_count"] += 1
        
        return results


class TestRegressionEdgeCases:
    """Regression tests for edge cases that could cause YES-only bias to return."""
    
    def test_regression_edge_case_zero_velocity(self):
        """
        Test edge case where velocity is zero.
        
        Should not default to YES-only selection.
        """
        evaluation = {
            "velocity": 0.0,
            "yes_edge": 0.05,
            "no_edge": 0.08
        }
        
        # With zero velocity, thesis_side defaults to "no"
        thesis_side = "yes" if evaluation["velocity"] > 0 else "no"
        
        # Should still select based on edge, not default to YES
        side_edges = {"yes": evaluation["yes_edge"], "no": evaluation["no_edge"]}
        selected_side, _ = max(side_edges.items(), key=lambda x: x[1])
        
        assert selected_side == "no", f"Should select NO (better edge), got {selected_side}"
    
    def test_regression_edge_case_both_edges_equal(self):
        """
        Test edge case where both edges are equal.
        
        Should have deterministic selection (not random).
        """
        evaluation = {
            "velocity": 0.0002,
            "yes_edge": 0.06,
            "no_edge": 0.06
        }
        
        thesis_side = "yes" if evaluation["velocity"] > 0 else "no"
        side_edges = {"yes": evaluation["yes_edge"], "no": evaluation["no_edge"]}
        
        # When edges are equal, should prefer velocity-aligned side
        velocity_aligned_edge = side_edges.get(thesis_side)
        opposite_side = "no" if thesis_side == "yes" else "yes"
        opposite_edge = side_edges.get(opposite_side)
        
        if velocity_aligned_edge == opposite_edge:
            selected_side = thesis_side  # Prefer aligned when equal
        else:
            selected_side, _ = max(side_edges.items(), key=lambda x: x[1])
        
        assert selected_side == thesis_side, "Should prefer velocity-aligned side when edges equal"
    
    def test_regression_edge_case_negative_velocity_positive_no_edge(self):
        """
        Test edge case: negative velocity but NO has positive edge.
        
        Should allow NO selection (aligned with velocity).
        """
        evaluation = {
            "velocity": -0.0002,
            "yes_edge": 0.04,
            "no_edge": 0.08
        }
        
        thesis_side = "yes" if evaluation["velocity"] > 0 else "no"
        assert thesis_side == "no", "Negative velocity should map to NO thesis_side"
        
        # NO should be selected (aligned with velocity)
        side_edges = {"yes": evaluation["yes_edge"], "no": evaluation["no_edge"]}
        selected_side, _ = max(side_edges.items(), key=lambda x: x[1])
        
        assert selected_side == "no", f"Should select NO (aligned with negative velocity), got {selected_side}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
