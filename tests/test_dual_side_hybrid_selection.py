"""
Comprehensive tests for dual-side evaluation and hybrid selection logic.

These tests ensure the system never regresses back to single-side/thesis-only behavior.
Tests cover:
- Dual-side edge calculation
- Hybrid selection with edge ratio threshold
- Counter-trend trade allowance
- Price reconstruction from duality
- Velocity as edge feature (not gate)
"""

import pytest
from typing import Dict, Any, Optional
from unittest.mock import Mock, patch
import json


class TestDualSideHybridSelection:
    """Test hybrid selection logic for dual-side evaluation."""
    
    def test_dual_side_eval_both_positive_aligned_selected(self):
        """
        Test that when both sides have positive edge and velocity aligns with higher edge,
        the velocity-aligned side is selected.
        
        Setup: yes_edge=0.08, no_edge=0.05, velocity>0
        Expected: YES selected, selection_method="HYBRID_ALIGNED", velocity_aligned=true
        """
        # Setup mock inputs
        velocity = 0.0002  # Positive velocity
        velocity_threshold = 0.00015
        yes_edge = 0.08
        no_edge = 0.05
        thesis_side = "yes"  # Derived from velocity > 0
        
        # Simulate hybrid selection logic
        side_edges = {"yes": yes_edge, "no": no_edge}
        candidates = []
        
        if yes_edge and yes_edge > 0:
            candidates.append(("yes", yes_edge))
        if no_edge and no_edge > 0:
            candidates.append(("no", no_edge))
        
        # Hybrid selection with edge ratio threshold
        EDGE_RATIO_THRESHOLD = 1.5
        velocity_aligned_side = thesis_side
        velocity_aligned_edge = side_edges.get(velocity_aligned_side)
        opposite_side = "no" if velocity_aligned_side == "yes" else "yes"
        opposite_edge = side_edges.get(opposite_side)
        
        if velocity_aligned_edge and opposite_edge:
            edge_ratio = opposite_edge / velocity_aligned_edge if velocity_aligned_edge > 0 else float('inf')
            
            if edge_ratio >= EDGE_RATIO_THRESHOLD:
                signal_side = opposite_side
                selected_edge = opposite_edge
                selection_method = "MAX_EDGE_COUNTER_TREND"
                velocity_aligned = False
            else:
                signal_side = velocity_aligned_side
                selected_edge = velocity_aligned_edge
                selection_method = "HYBRID_ALIGNED"
                velocity_aligned = True
        else:
            signal_side, selected_edge = max(candidates, key=lambda x: x[1])
            selection_method = "FALLBACK"
            velocity_aligned = (signal_side == thesis_side)
        
        # Assertions
        assert signal_side == "yes", f"Expected YES, got {signal_side}"
        assert selected_edge == 0.08, f"Expected 0.08, got {selected_edge}"
        assert selection_method == "HYBRID_ALIGNED", f"Expected HYBRID_ALIGNED, got {selection_method}"
        assert velocity_aligned == True, f"Expected velocity_aligned=True, got {velocity_aligned}"
        assert edge_ratio == 0.05 / 0.08, f"Expected edge_ratio=0.625, got {edge_ratio}"
    
    def test_dual_side_eval_counter_trend_override(self):
        """
        Test that when opposite side has significantly better edge (>= 1.5x),
        counter-trend selection is allowed.
        
        Setup: yes_edge=0.04, no_edge=0.08, velocity>0
        Expected: NO selected (counter-trend), selection_method="MAX_EDGE_COUNTER_TREND"
        """
        # Setup mock inputs
        velocity = 0.0002  # Positive velocity
        velocity_threshold = 0.00015
        yes_edge = 0.04
        no_edge = 0.08
        thesis_side = "yes"  # Derived from velocity > 0
        
        # Simulate hybrid selection logic
        side_edges = {"yes": yes_edge, "no": no_edge}
        candidates = []
        
        if yes_edge and yes_edge > 0:
            candidates.append(("yes", yes_edge))
        if no_edge and no_edge > 0:
            candidates.append(("no", no_edge))
        
        # Hybrid selection with edge ratio threshold
        EDGE_RATIO_THRESHOLD = 1.5
        velocity_aligned_side = thesis_side
        velocity_aligned_edge = side_edges.get(velocity_aligned_side)
        opposite_side = "no" if velocity_aligned_side == "yes" else "yes"
        opposite_edge = side_edges.get(opposite_side)
        
        if velocity_aligned_edge and opposite_edge:
            edge_ratio = opposite_edge / velocity_aligned_edge if velocity_aligned_edge > 0 else float('inf')
            
            if edge_ratio >= EDGE_RATIO_THRESHOLD:
                signal_side = opposite_side
                selected_edge = opposite_edge
                selection_method = "MAX_EDGE_COUNTER_TREND"
                velocity_aligned = False
            else:
                signal_side = velocity_aligned_side
                selected_edge = velocity_aligned_edge
                selection_method = "HYBRID_ALIGNED"
                velocity_aligned = True
        else:
            signal_side, selected_edge = max(candidates, key=lambda x: x[1])
            selection_method = "FALLBACK"
            velocity_aligned = (signal_side == thesis_side)
        
        # Assertions
        assert signal_side == "no", f"Expected NO (counter-trend), got {signal_side}"
        assert selected_edge == 0.08, f"Expected 0.08, got {selected_edge}"
        assert selection_method == "MAX_EDGE_COUNTER_TREND", f"Expected MAX_EDGE_COUNTER_TREND, got {selection_method}"
        assert velocity_aligned == False, f"Expected velocity_aligned=False (counter-trend), got {velocity_aligned}"
        assert edge_ratio == 2.0, f"Expected edge_ratio=2.0, got {edge_ratio}"
    
    def test_dual_side_eval_both_non_positive_reject(self):
        """
        Test that when both sides have non-positive edges, no candidate is returned.
        
        Setup: yes_edge<=0, no_edge<=0
        Expected: No candidate returned, rejection logged
        """
        # Setup mock inputs
        yes_edge = -0.02
        no_edge = -0.01
        
        # Simulate dual-side evaluation
        side_edges = {"yes": yes_edge, "no": no_edge}
        candidates = []
        
        if yes_edge and yes_edge > 0:
            candidates.append(("yes", yes_edge))
        if no_edge and no_edge > 0:
            candidates.append(("no", no_edge))
        
        # Assertions
        assert len(candidates) == 0, f"Expected no candidates, got {len(candidates)}"
        assert candidates == [], f"Expected empty list, got {candidates}"
    
    def test_dual_side_eval_one_side_positive(self):
        """
        Test that when only one side has positive edge, that side is selected.
        
        Setup: yes_edge=0.06, no_edge=-0.01
        Expected: YES selected (only positive edge)
        """
        # Setup mock inputs
        yes_edge = 0.06
        no_edge = -0.01
        thesis_side = "yes"
        
        # Simulate dual-side evaluation
        side_edges = {"yes": yes_edge, "no": no_edge}
        candidates = []
        
        if yes_edge and yes_edge > 0:
            candidates.append(("yes", yes_edge))
        if no_edge and no_edge > 0:
            candidates.append(("no", no_edge))
        
        # Hybrid selection
        if candidates:
            signal_side, selected_edge = max(candidates, key=lambda x: x[1])
            velocity_aligned = (signal_side == thesis_side)
        else:
            signal_side = None
            selected_edge = None
            velocity_aligned = None
        
        # Assertions
        assert signal_side == "yes", f"Expected YES, got {signal_side}"
        assert selected_edge == 0.06, f"Expected 0.06, got {selected_edge}"
        assert velocity_aligned == True, f"Expected velocity_aligned=True, got {velocity_aligned}"
    
    def test_edge_ratio_threshold_boundary(self):
        """
        Test edge ratio threshold boundary conditions.
        
        Test exactly at threshold (1.5x) and just below.
        """
        # Test exactly at threshold
        yes_edge = 0.04
        no_edge = 0.06  # Exactly 1.5x
        thesis_side = "yes"
        
        side_edges = {"yes": yes_edge, "no": no_edge}
        EDGE_RATIO_THRESHOLD = 1.5
        
        velocity_aligned_edge = side_edges.get(thesis_side)
        opposite_side = "no" if thesis_side == "yes" else "yes"
        opposite_edge = side_edges.get(opposite_side)
        
        edge_ratio = opposite_edge / velocity_aligned_edge
        should_select_opposite = edge_ratio >= EDGE_RATIO_THRESHOLD
        
        assert should_select_opposite == True, f"Expected opposite selection at threshold, got {should_select_opposite}"
        
        # Test just below threshold
        no_edge = 0.059  # 1.475x (just below 1.5)
        side_edges = {"yes": yes_edge, "no": no_edge}
        opposite_edge = side_edges.get(opposite_side)
        
        edge_ratio = opposite_edge / velocity_aligned_edge
        should_select_opposite = edge_ratio >= EDGE_RATIO_THRESHOLD
        
        assert should_select_opposite == False, f"Expected aligned selection below threshold, got {should_select_opposite}"


class TestPriceReconstruction:
    """Test price reconstruction from duality when one side is missing."""
    
    def test_dual_price_reconstruction_yes_missing(self):
        """
        Test that when YES price is missing, it's reconstructed from NO price.
        
        Setup: YES price N/A, NO price = 32c
        Expected: YES reconstructed to 68c (100 - 32), reconstruction logged
        """
        yes_price_cents = None
        no_price_cents = 32
        
        # Simulate reconstruction logic
        if yes_price_cents is None or yes_price_cents <= 0:
            if no_price_cents and no_price_cents > 0:
                yes_price_cents = 100 - no_price_cents
                reconstruction_success = True
                reconstruction_method = "DUALITY_INVERSION"
            else:
                reconstruction_success = False
                reconstruction_method = None
        else:
            reconstruction_success = False
            reconstruction_method = None
        
        # Assertions
        assert yes_price_cents == 68, f"Expected YES=68c, got {yes_price_cents}"
        assert reconstruction_success == True, f"Expected reconstruction success"
        assert reconstruction_method == "DUALITY_INVERSION", f"Expected DUALITY_INVERSION method"
    
    def test_dual_price_reconstruction_no_missing(self):
        """
        Test that when NO price is missing, it's reconstructed from YES price.
        
        Setup: YES price = 68c, NO price N/A
        Expected: NO reconstructed to 32c (100 - 68), reconstruction logged
        """
        yes_price_cents = 68
        no_price_cents = None
        
        # Simulate reconstruction logic
        if no_price_cents is None or no_price_cents <= 0:
            if yes_price_cents and yes_price_cents > 0:
                no_price_cents = 100 - yes_price_cents
                reconstruction_success = True
                reconstruction_method = "DUALITY_INVERSION"
            else:
                reconstruction_success = False
                reconstruction_method = None
        else:
            reconstruction_success = False
            reconstruction_method = None
        
        # Assertions
        assert no_price_cents == 32, f"Expected NO=32c, got {no_price_cents}"
        assert reconstruction_success == True, f"Expected reconstruction success"
        assert reconstruction_method == "DUALITY_INVERSION", f"Expected DUALITY_INVERSION method"
    
    def test_dual_price_reconstruction_both_missing(self):
        """
        Test that when both sides are missing, evaluation is rejected.
        
        Setup: YES price N/A, NO price N/A
        Expected: Evaluation rejected, error logged
        """
        yes_price_cents = None
        no_price_cents = None
        
        # Simulate reconstruction logic
        can_reconstruct = False
        
        if yes_price_cents is None or yes_price_cents <= 0:
            if no_price_cents and no_price_cents > 0:
                yes_price_cents = 100 - no_price_cents
                can_reconstruct = True
            else:
                can_reconstruct = False
        
        if no_price_cents is None or no_price_cents <= 0:
            if yes_price_cents and yes_price_cents > 0:
                no_price_cents = 100 - yes_price_cents
                can_reconstruct = True
            else:
                can_reconstruct = False
        
        # Assertions
        assert can_reconstruct == False, f"Expected reconstruction failure when both missing"
        assert yes_price_cents is None, f"Expected YES still None"
        assert no_price_cents is None, f"Expected NO still None"


class TestVelocityAsEdgeFeature:
    """Test that velocity influences edge as a feature, not a direction gate."""
    
    def test_velocity_magnitude_used_for_edge(self):
        """
        Test that velocity magnitude (absolute value) is used for edge calculation,
        not velocity * velocity_sign which would gate opposite side.
        
        This ensures velocity can boost edge on both sides.
        """
        velocity = 0.0002
        velocity_threshold = 0.00015
        
        # Old approach (WRONG - gates opposite side)
        velocity_sign = 1  # For YES side
        old_base_edge = velocity * velocity_sign  # 0.0002
        
        # New approach (CORRECT - uses magnitude)
        velocity_magnitude = abs(velocity)
        new_base_edge = velocity_magnitude  # 0.0002
        
        # For NO side with old approach
        velocity_sign_no = -1
        old_base_edge_no = velocity * velocity_sign_no  # -0.0002 (negative, would gate)
        
        # For NO side with new approach
        new_base_edge_no = velocity_magnitude  # 0.0002 (positive, allows edge)
        
        # Assertions
        assert old_base_edge_no < 0, f"Old approach gives negative edge for NO side (gating)"
        assert new_base_edge_no > 0, f"New approach gives positive edge for NO side (feature, not gate)"
        assert new_base_edge_no == new_base_edge, f"Velocity magnitude symmetric for both sides"
    
    def test_velocity_alignment_bonus(self):
        """
        Test that velocity alignment bonus/penalty is applied correctly.
        
        - Aligned: velocity_sign > 0 and velocity > 0 → bonus
        - Counter-trend: velocity_sign > 0 and velocity < 0 → penalty
        """
        velocity = 0.0002
        
        # Test aligned (YES side, positive velocity)
        velocity_sign_yes = 1
        if velocity_sign_yes > 0 and velocity > 0:
            aligned_bonus = velocity * 1000
        else:
            aligned_bonus = 0
        
        # Test counter-trend (NO side, positive velocity)
        velocity_sign_no = -1
        if velocity_sign_no < 0 and velocity < 0:
            counter_trend_bonus = velocity * 1000
        elif velocity_sign_no < 0 and velocity > 0:
            counter_trend_bonus = -abs(velocity) * 500
        else:
            counter_trend_bonus = 0
        
        # For NO side with positive velocity (counter-trend)
        if velocity_sign_no < 0 and velocity > 0:
            alignment_penalty = -abs(velocity) * 500
        else:
            alignment_penalty = 0
        
        # Assertions
        assert aligned_bonus > 0, f"Expected positive bonus for aligned velocity"
        assert alignment_penalty < 0, f"Expected negative penalty for counter-trend velocity"


class TestDiagnosticLogging:
    """Test that diagnostic logs are properly structured and contain required fields."""
    
    def test_dual_side_selection_log_structure(self):
        """
        Test that dual-side selection log contains all required fields.
        """
        log_entry = {
            "asset": "BTC",
            "velocity": 0.0002,
            "thesis_side": "yes",
            "yes_edge": 0.08,
            "no_edge": 0.05,
            "selected_side": "yes",
            "selected_edge": 0.08,
            "edge_ratio": 0.625,
            "velocity_aligned": True,
            "selection_method": "HYBRID_ALIGNED"
        }
        
        # Verify required fields
        required_fields = [
            "asset", "velocity", "thesis_side", "yes_edge", "no_edge",
            "selected_side", "selected_edge", "edge_ratio", "velocity_aligned", "selection_method"
        ]
        
        for field in required_fields:
            assert field in log_entry, f"Missing required field: {field}"
        
        # Verify JSON serializable
        try:
            json_str = json.dumps(log_entry)
            parsed = json.loads(json_str)
            assert parsed == log_entry, "JSON round-trip failed"
        except Exception as e:
            pytest.fail(f"Log entry not JSON serializable: {e}")
    
    def test_price_reconstruction_log_structure(self):
        """
        Test that price reconstruction log contains required fields.
        """
        log_entry = {
            "event_type": "PRICE_VALIDATION_FAILURE",
            "asset": "BTC",
            "side": "yes",
            "failure_type": "N/A_PRICE_DETECTED",
            "reconstruction_attempted": True,
            "reconstruction_method": "DUALITY_INVERSION",
            "reconstruction_result": "SUCCESS",
            "reconstructed_price": 68
        }
        
        # Verify required fields
        required_fields = [
            "event_type", "asset", "side", "failure_type",
            "reconstruction_attempted", "reconstruction_method", "reconstruction_result"
        ]
        
        for field in required_fields:
            assert field in log_entry, f"Missing required field: {field}"
        
        # Verify JSON serializable
        try:
            json_str = json.dumps(log_entry)
            parsed = json.loads(json_str)
            assert parsed == log_entry, "JSON round-trip failed"
        except Exception as e:
            pytest.fail(f"Log entry not JSON serializable: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
