"""Unit tests for canonical edge boundary cases.

This module tests the epsilon-based threshold comparison in select_winner_side
to ensure boundary conditions are handled correctly without false rejections.

CRITICAL FIX: 2026-08-02 - Tests for edge == min_edge, edge == -min_edge, and
values one tick above/below the threshold to prevent false parity vetoes.
"""

import pytest
from merid.prediction.canonical_edge import select_winner_side


class TestSelectWinnerSideBoundaryCases:
    """Test select_winner_side with boundary conditions."""
    
    def test_edge_exactly_at_min_edge(self):
        """Test edge exactly at min_edge threshold (boundary condition)."""
        min_edge = 0.015  # 1.5%
        
        # YES edge exactly at threshold, NO edge below
        result = select_winner_side(edge_yes=0.015, edge_no=0.010, min_edge=min_edge)
        # With epsilon-based comparison, this should return "yes"
        assert result == "yes", f"Expected 'yes' for edge_yes={0.015} >= min_edge={min_edge}, got {result}"
        
        # NO edge exactly at threshold, YES edge below
        result = select_winner_side(edge_yes=0.010, edge_no=0.015, min_edge=min_edge)
        assert result == "no", f"Expected 'no' for edge_no={0.015} >= min_edge={min_edge}, got {result}"
    
    def test_edge_one_epsilon_above_min_edge(self):
        """Test edge one epsilon above min_edge threshold."""
        min_edge = 0.015
        epsilon = 1e-6
        
        # YES edge one epsilon above threshold
        result = select_winner_side(edge_yes=0.015 + epsilon, edge_no=0.010, min_edge=min_edge)
        assert result == "yes", f"Expected 'yes' for edge_yes={0.015 + epsilon} > min_edge={min_edge}, got {result}"
        
        # NO edge one epsilon above threshold
        result = select_winner_side(edge_yes=0.010, edge_no=0.015 + epsilon, min_edge=min_edge)
        assert result == "no", f"Expected 'no' for edge_no={0.015 + epsilon} > min_edge={min_edge}, got {result}"
    
    def test_edge_one_epsilon_below_min_edge(self):
        """Test edge one epsilon below min_edge threshold."""
        min_edge = 0.015
        epsilon = 1e-6
        
        # YES edge one epsilon below threshold
        result = select_winner_side(edge_yes=0.015 - epsilon, edge_no=0.010, min_edge=min_edge)
        # With epsilon-based comparison (edge >= min_edge - epsilon), this should still return "yes"
        assert result == "yes", f"Expected 'yes' for edge_yes={0.015 - epsilon} >= min_edge-epsilon={min_edge - epsilon}, got {result}"
        
        # NO edge one epsilon below threshold
        result = select_winner_side(edge_yes=0.010, edge_no=0.015 - epsilon, min_edge=min_edge)
        assert result == "no", f"Expected 'no' for edge_no={0.015 - epsilon} >= min_edge-epsilon={min_edge - epsilon}, got {result}"
    
    def test_negative_edge_at_negative_min_edge(self):
        """Test negative edge at -min_edge (boundary condition)."""
        min_edge = 0.015
        
        # YES edge at -min_edge, NO edge positive
        result = select_winner_side(edge_yes=-0.015, edge_no=0.015, min_edge=min_edge)
        # NO should win since it's positive and above threshold
        assert result == "no", f"Expected 'no' for edge_no={0.015} >= min_edge={min_edge}, got {result}"
        
        # NO edge at -min_edge, YES edge positive
        result = select_winner_side(edge_yes=0.015, edge_no=-0.015, min_edge=min_edge)
        # YES should win since it's positive and above threshold
        assert result == "yes", f"Expected 'yes' for edge_yes={0.015} >= min_edge={min_edge}, got {result}"
    
    def test_both_edges_negative(self):
        """Test both edges negative (should return 'none')."""
        min_edge = 0.015
        
        result = select_winner_side(edge_yes=-0.015, edge_no=-0.010, min_edge=min_edge)
        assert result == "none", f"Expected 'none' for both negative edges, got {result}"
        
        result = select_winner_side(edge_yes=-0.010, edge_no=-0.015, min_edge=min_edge)
        assert result == "none", f"Expected 'none' for both negative edges, got {result}"
    
    def test_both_edges_below_threshold(self):
        """Test both edges below min_edge but positive (should return 'none')."""
        min_edge = 0.015
        
        result = select_winner_side(edge_yes=0.010, edge_no=0.012, min_edge=min_edge)
        assert result == "none", f"Expected 'none' for both edges below threshold, got {result}"
        
        result = select_winner_side(edge_yes=0.012, edge_no=0.010, min_edge=min_edge)
        assert result == "none", f"Expected 'none' for both edges below threshold, got {result}"
    
    def test_edges_within_epsilon(self):
        """Test edges within epsilon of each other (tie, should return 'none')."""
        min_edge = 0.015
        epsilon = 1e-6
        
        # Edges very close, both above threshold
        result = select_winner_side(edge_yes=0.016, edge_no=0.016 + epsilon/2, min_edge=min_edge)
        assert result == "none", f"Expected 'none' for edges within epsilon, got {result}"
        
        result = select_winner_side(edge_yes=0.016 + epsilon/2, edge_no=0.016, min_edge=min_edge)
        assert result == "none", f"Expected 'none' for edges within epsilon, got {result}"
    
    def test_yes_wins_clearly(self):
        """Test YES wins clearly above threshold."""
        min_edge = 0.015
        
        result = select_winner_side(edge_yes=0.020, edge_no=0.010, min_edge=min_edge)
        assert result == "yes", f"Expected 'yes' for clear YES win, got {result}"
    
    def test_no_wins_clearly(self):
        """Test NO wins clearly above threshold."""
        min_edge = 0.015
        
        result = select_winner_side(edge_yes=0.010, edge_no=0.020, min_edge=min_edge)
        assert result == "no", f"Expected 'no' for clear NO win, got {result}"
    
    def test_original_bug_case(self):
        """Test the original bug case from logs: edge_yes=-0.0150, edge_no=0.0150."""
        min_edge = 0.015
        
        # This was the bug: both at threshold, but one negative, one positive
        # With the fix, NO should win since it's positive and above threshold
        result = select_winner_side(edge_yes=-0.0150, edge_no=0.0150, min_edge=min_edge)
        assert result == "no", f"Expected 'no' for edge_no=0.0150 >= min_edge={min_edge}, got {result}"
    
    def test_floating_point_precision(self):
        """Test floating point precision edge cases."""
        min_edge = 0.015
        
        # Test with floating point arithmetic that might introduce precision errors
        result = select_winner_side(edge_yes=0.0150000001, edge_no=0.010, min_edge=min_edge)
        assert result == "yes", f"Expected 'yes' for edge_yes slightly above threshold, got {result}"
        
        result = select_winner_side(edge_yes=0.0149999999, edge_no=0.010, min_edge=min_edge)
        # With epsilon-based comparison (>=), this should still return "yes"
        assert result == "yes", f"Expected 'yes' for edge_yes slightly below threshold (within epsilon), got {result}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
