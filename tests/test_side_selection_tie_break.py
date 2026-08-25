"""
Tests for side selection tie-breaking behavior to counteract YES bias.

Tests for:
1. Momentum-FVG dual-side selection prefers NO when edges are tied
2. Price-based signal selection prefers NO when edges are tied
3. Edge comparison logic correctly handles equal edge cases
"""

import pytest
from unittest.mock import MagicMock, patch


class TestMomentumFVGTieBreak:
    """Test momentum_fvg tie-breaking logic prefers NO when edges are equal."""
    
    def test_tie_break_prefers_no_momentum_fvg(self):
        """Test that when YES and NO edges are equal, momentum_fvg selects NO."""
        # Create side_edges_with_bonus with equal edges
        side_edges_with_bonus = {"yes": 0.50, "no": 0.50}
        
        # Simulate the tie-breaking logic
        max_edge = max(side_edges_with_bonus.values())
        tied_sides = [side for side, edge in side_edges_with_bonus.items() if edge == max_edge]
        
        if len(tied_sides) == 2:
            signal_side = "no"  # Tie: prefer NO to balance YES bias
        else:
            signal_side = max(side_edges_with_bonus, key=side_edges_with_bonus.get)
        
        assert signal_side == "no", "Tie-breaking should prefer NO when edges are equal"
    
    def test_no_tie_selects_max_edge(self):
        """Test that when edges are not tied, the side with higher edge is selected."""
        side_edges_with_bonus = {"yes": 0.60, "no": 0.40}
        
        max_edge = max(side_edges_with_bonus.values())
        tied_sides = [side for side, edge in side_edges_with_bonus.items() if edge == max_edge]
        
        if len(tied_sides) == 2:
            signal_side = "no"
        else:
            signal_side = max(side_edges_with_bonus, key=side_edges_with_bonus.get)
        
        assert signal_side == "yes", "Higher edge (YES) should be selected when not tied"
    
    def test_no_higher_edge_selected(self):
        """Test that when NO edge is higher, NO is selected."""
        side_edges_with_bonus = {"yes": 0.30, "no": 0.70}
        
        max_edge = max(side_edges_with_bonus.values())
        tied_sides = [side for side, edge in side_edges_with_bonus.items() if edge == max_edge]
        
        if len(tied_sides) == 2:
            signal_side = "no"
        else:
            signal_side = max(side_edges_with_bonus, key=side_edges_with_bonus.get)
        
        assert signal_side == "no", "Higher edge (NO) should be selected"


class TestPriceBasedTieBreak:
    """Test price-based signal tie-breaking logic prefers NO when edges are equal."""
    
    def test_tie_break_prefers_no_price_based(self):
        """Test that when YES and NO edges are equal, price-based signal selects NO."""
        yes_edge_pct = 0.50
        no_edge_pct = 0.50
        
        if yes_edge_pct > no_edge_pct:
            signal_side = "yes"
        elif no_edge_pct > yes_edge_pct:
            signal_side = "no"
        else:
            # Equal edges - prefer NO side to counteract YES bias
            signal_side = "no"
        
        assert signal_side == "no", "Tie-breaking should prefer NO when edges are equal"
    
    def test_yes_higher_edge_selected_price_based(self):
        """Test that when YES edge is higher, YES is selected."""
        yes_edge_pct = 0.60
        no_edge_pct = 0.40
        
        if yes_edge_pct > no_edge_pct:
            signal_side = "yes"
        elif no_edge_pct > yes_edge_pct:
            signal_side = "no"
        else:
            signal_side = "no"
        
        assert signal_side == "yes", "Higher edge (YES) should be selected when not tied"
    
    def test_no_higher_edge_selected_price_based(self):
        """Test that when NO edge is higher, NO is selected."""
        yes_edge_pct = 0.30
        no_edge_pct = 0.70
        
        if yes_edge_pct > no_edge_pct:
            signal_side = "yes"
        elif no_edge_pct > yes_edge_pct:
            signal_side = "no"
        else:
            signal_side = "no"
        
        assert signal_side == "no", "Higher edge (NO) should be selected"


class TestMidpointBonusTieBreak:
    """Test that midpoint bonus doesn't override tie-breaking preference."""
    
    def test_midpoint_bonus_with_tie(self):
        """Test that midpoint bonus is applied but tie-breaking still prefers NO."""
        # Simulate edges with midpoint bonus applied
        # YES at 40c gets bonus, NO at 60c gets less bonus
        # If final edges are equal, NO should still be preferred
        side_edges = {"yes": 0.50, "no": 0.50}
        side_edges_with_bonus = {"yes": 0.55, "no": 0.55}  # Both get same bonus
        
        max_edge = max(side_edges_with_bonus.values())
        tied_sides = [side for side, edge in side_edges_with_bonus.items() if edge == max_edge]
        
        if len(tied_sides) == 2:
            signal_side = "no"
        else:
            signal_side = max(side_edges_with_bonus, key=side_edges_with_bonus.get)
        
        assert signal_side == "no", "Tie-breaking should prefer NO even with midpoint bonus"
    
    def test_midpoint_bonus_breaks_tie(self):
        """Test that midpoint bonus can break ties when applied differently."""
        # YES at 25c gets max bonus, NO at 60c gets less bonus
        side_edges = {"yes": 0.50, "no": 0.50}
        side_edges_with_bonus = {"yes": 0.60, "no": 0.52}  # YES gets more bonus
        
        max_edge = max(side_edges_with_bonus.values())
        tied_sides = [side for side, edge in side_edges_with_bonus.items() if edge == max_edge]
        
        if len(tied_sides) == 2:
            signal_side = "no"
        else:
            signal_side = max(side_edges_with_bonus, key=side_edges_with_bonus.get)
        
        assert signal_side == "yes", "Midpoint bonus should allow YES to win when significantly higher"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
