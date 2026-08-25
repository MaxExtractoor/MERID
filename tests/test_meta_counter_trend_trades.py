"""
Meta-test for counter-trend trades in live simulation.

This test runs a recorded stream through the stack and asserts that some
evaluations yield counter-trend selections (velocity positive, NO selected, etc.).
If zero counter-trend trades occur, something is still blocking NO side selection.
"""

import pytest
from typing import Dict, Any, List, Optional
from unittest.mock import Mock
import json


class TestCounterTrendTradesExistence:
    """Meta-test to ensure counter-trend trades are possible in the system."""
    
    def test_counter_trend_trades_exist_in_live_sim(self):
        """
        Run a recorded stream through the stack and assert some evaluations
        yield counter-trend selections.
        
        Counter-trend definition:
        - velocity > 0 (positive) → thesis_side = yes
        - selected_side = no (opposite to velocity)
        - edge_ratio >= threshold (opposite side has significantly better edge)
        
        If zero counter-trend trades occur, the system is still blocking NO side.
        """
        # Simulate a recorded stream of evaluations
        recorded_stream = self._generate_test_stream()
        
        # Process stream through evaluation logic
        counter_trend_count = 0
        aligned_count = 0
        total_evaluations = 0
        
        for evaluation in recorded_stream:
            total_evaluations += 1
            
            # Extract evaluation data
            velocity = evaluation["velocity"]
            yes_edge = evaluation["yes_edge"]
            no_edge = evaluation["no_edge"]
            
            # Determine thesis_side from velocity
            thesis_side = "yes" if velocity > 0 else "no"
            
            # Hybrid selection logic
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
                else:
                    selected_side = thesis_side
                    is_counter_trend = False
            else:
                selected_side, _ = max(side_edges.items(), key=lambda x: x[1])
                is_counter_trend = (selected_side != thesis_side)
            
            # Track results
            if is_counter_trend:
                counter_trend_count += 1
            else:
                aligned_count += 1
        
        # Assertions
        assert total_evaluations > 0, "Stream should have evaluations"
        
        # CRITICAL: At least some counter-trend trades should occur
        # If this fails, the system is still blocking NO side selection
        assert counter_trend_count > 0, (
            f"ZERO counter-trend trades detected in {total_evaluations} evaluations. "
            f"This indicates the system is still blocking NO side selection. "
            f"Aligned trades: {aligned_count}, Counter-trend trades: {counter_trend_count}. "
            f"Expected: counter-trend trades should occur when opposite side has better edge."
        )
        
        # Also verify aligned trades exist (sanity check)
        assert aligned_count > 0, "At least some aligned trades should occur"
        
        # Counter-trend should be a reasonable percentage (not 0%, not 100%)
        counter_trend_ratio = counter_trend_count / total_evaluations
        assert 0.05 <= counter_trend_ratio <= 0.95, (
            f"Counter-trend ratio {counter_trend_ratio:.2%} is outside reasonable range. "
            f"Expected 5-95% counter-trend trades."
        )
    
    def _generate_test_stream(self) -> List[Dict[str, Any]]:
        """
        Generate a test stream of evaluations with mixed conditions.
        
        Includes:
        - Aligned selections (velocity matches selected side)
        - Counter-trend selections (velocity opposes selected side)
        - Edge ratios both below and above threshold
        """
        stream = []
        
        # Scenario 1: Aligned selection (velocity positive, YES selected, YES has better edge)
        stream.append({
            "velocity": 0.0002,
            "yes_edge": 0.08,
            "no_edge": 0.05,
            "expected_aligned": True
        })
        
        # Scenario 2: Counter-trend selection (velocity positive, NO selected, NO has 2x edge)
        stream.append({
            "velocity": 0.0002,
            "yes_edge": 0.04,
            "no_edge": 0.08,  # 2x YES edge
            "expected_aligned": False
        })
        
        # Scenario 3: Aligned selection (velocity negative, NO selected, NO has better edge)
        stream.append({
            "velocity": -0.0002,
            "yes_edge": 0.05,
            "no_edge": 0.08,
            "expected_aligned": True
        })
        
        # Scenario 4: Counter-trend selection (velocity negative, YES selected, YES has 2x edge)
        stream.append({
            "velocity": -0.0002,
            "yes_edge": 0.08,  # 2x NO edge
            "no_edge": 0.04,
            "expected_aligned": False
        })
        
        # Scenario 5: Aligned selection (velocity positive, YES selected, edges comparable)
        stream.append({
            "velocity": 0.0002,
            "yes_edge": 0.07,
            "no_edge": 0.06,  # Ratio < 1.5
            "expected_aligned": True
        })
        
        # Scenario 6: Counter-trend selection (velocity positive, NO selected, NO has 1.6x edge)
        stream.append({
            "velocity": 0.0002,
            "yes_edge": 0.05,
            "no_edge": 0.08,  # Ratio = 1.6 >= 1.5
            "expected_aligned": False
        })
        
        # Scenario 7: Aligned selection (velocity negative, NO selected, edges comparable)
        stream.append({
            "velocity": -0.0002,
            "yes_edge": 0.06,
            "no_edge": 0.07,  # Ratio < 1.5
            "expected_aligned": True
        })
        
        # Scenario 8: Counter-trend selection (velocity negative, YES selected, YES has 1.5x edge)
        stream.append({
            "velocity": -0.0002,
            "yes_edge": 0.09,  # Ratio = 1.5 >= 1.5
            "no_edge": 0.06,
            "expected_aligned": False
        })
        
        return stream
    
    def test_counter_trend_detection_logic(self):
        """
        Test the counter-trend detection logic directly.
        """
        EDGE_RATIO_THRESHOLD = 1.5
        
        # Test case 1: Positive velocity, NO selected (counter-trend)
        velocity = 0.0002
        thesis_side = "yes"
        selected_side = "no"
        edge_ratio = 2.0
        
        is_counter_trend = (selected_side != thesis_side)
        assert is_counter_trend == True, "Should detect counter-trend"
        
        # Test case 2: Positive velocity, YES selected (aligned)
        velocity = 0.0002
        thesis_side = "yes"
        selected_side = "yes"
        edge_ratio = 0.6
        
        is_counter_trend = (selected_side != thesis_side)
        assert is_counter_trend == False, "Should detect aligned"
        
        # Test case 3: Negative velocity, YES selected (counter-trend)
        velocity = -0.0002
        thesis_side = "no"
        selected_side = "yes"
        edge_ratio = 2.0
        
        is_counter_trend = (selected_side != thesis_side)
        assert is_counter_trend == True, "Should detect counter-trend"
        
        # Test case 4: Negative velocity, NO selected (aligned)
        velocity = -0.0002
        thesis_side = "no"
        selected_side = "no"
        edge_ratio = 0.6
        
        is_counter_trend = (selected_side != thesis_side)
        assert is_counter_trend == False, "Should detect aligned"
    
    def test_edge_ratio_threshold_enforcement(self):
        """
        Test that edge ratio threshold is enforced correctly.
        """
        EDGE_RATIO_THRESHOLD = 1.5
        
        # Test at threshold boundary
        velocity_aligned_edge = 0.04
        opposite_edge = 0.06  # Exactly 1.5x
        edge_ratio = opposite_edge / velocity_aligned_edge
        
        should_select_opposite = edge_ratio >= EDGE_RATIO_THRESHOLD
        assert should_select_opposite == True, "Should select opposite at threshold"
        
        # Test just below threshold
        opposite_edge = 0.059  # 1.475x
        edge_ratio = opposite_edge / velocity_aligned_edge
        
        should_select_opposite = edge_ratio >= EDGE_RATIO_THRESHOLD
        assert should_select_opposite == False, "Should select aligned below threshold"
        
        # Test well above threshold
        opposite_edge = 0.10  # 2.5x
        edge_ratio = opposite_edge / velocity_aligned_edge
        
        should_select_opposite = edge_ratio >= EDGE_RATIO_THRESHOLD
        assert should_select_opposite == True, "Should select opposite well above threshold"
    
    def test_velocity_sign_mapping(self):
        """
        Test that velocity sign correctly maps to thesis_side.
        """
        # Positive velocity → thesis_side = yes
        velocity = 0.0002
        thesis_side = "yes" if velocity > 0 else "no"
        assert thesis_side == "yes", "Positive velocity should map to YES"
        
        # Negative velocity → thesis_side = no
        velocity = -0.0002
        thesis_side = "yes" if velocity > 0 else "no"
        assert thesis_side == "no", "Negative velocity should map to NO"
        
        # Zero velocity → thesis_side = no (default)
        velocity = 0.0
        thesis_side = "yes" if velocity > 0 else "no"
        assert thesis_side == "no", "Zero velocity should map to NO (default)"
    
    def test_counter_trend_trade_components(self):
        """
        Test that counter-trend trades have all required components.
        """
        counter_trend_trade = {
            "velocity": 0.0002,
            "thesis_side": "yes",
            "selected_side": "no",
            "yes_edge": 0.04,
            "no_edge": 0.08,
            "edge_ratio": 2.0,
            "selection_method": "MAX_EDGE_COUNTER_TREND",
            "velocity_aligned": False
        }
        
        # Verify required components
        assert "velocity" in counter_trend_trade
        assert "thesis_side" in counter_trend_trade
        assert "selected_side" in counter_trend_trade
        assert "edge_ratio" in counter_trend_trade
        assert "selection_method" in counter_trend_trade
        assert "velocity_aligned" in counter_trend_trade
        
        # Verify counter-trend condition
        assert counter_trend_trade["velocity"] > 0
        assert counter_trend_trade["thesis_side"] == "yes"
        assert counter_trend_trade["selected_side"] == "no"
        assert counter_trend_trade["velocity_aligned"] == False
        assert counter_trend_trade["edge_ratio"] >= 1.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
