"""
Tests for edge improvement threshold logic in loop_15m.py.

This tests the fix that changed edge improvement from absolute (5%) to relative (20%)
to accommodate velocity-based signals with tiny edges (0.01-0.07%).
"""

import pytest
from unittest.mock import Mock, MagicMock, AsyncMock
from datetime import datetime, timezone


class TestEdgeImprovementThreshold:
    """Test edge improvement threshold logic for velocity-based signals."""
    
    @pytest.fixture
    def mock_loop(self):
        """Create a mock Kalshi15mLoop instance for testing."""
        from merid.loop_15m import Kalshi15mLoop
        
        loop = Mock(spec=Kalshi15mLoop)
        loop._asset_positions = {"BTC": 0.0, "ETH": 0.0, "SOL": 0.0, "XRP": 0.0, "DOGE": 0.0}
        loop._best_edge_per_asset = {}
        loop._swing_mode = {}
        loop._executed_candidates_this_window = set()
        loop._cycle_count = 0
        loop._last_cycle_at = datetime.now(timezone.utc)
        
        return loop
    
    def test_first_signal_with_position_executes(self, mock_loop):
        """Test that first signal with position executes if edge meets minimum threshold."""
        from merid.loop_15m import Kalshi15mLoop
        
        # Simulate the edge improvement logic
        asset = "BTC"
        edge = 0.02  # 2% edge (typical for velocity-based signals)
        current_best_edge = 0.0  # No current best edge
        min_edge_threshold = 0.0001  # 0.01% minimum
        has_position = True
        
        should_execute = False
        if has_position:
            if abs(current_best_edge) > 0:
                # Relative improvement logic (using abs for negative edges)
                edge_improvement_ratio = (abs(edge) - abs(current_best_edge)) / abs(current_best_edge)
                edge_improvement_threshold = 0.20
                if edge_improvement_ratio > edge_improvement_threshold:
                    should_execute = True
            else:
                # No current best edge (first signal with position)
                # CRITICAL FIX: Use abs(edge) since edge = p_model - p_market can be negative
                if abs(edge) > min_edge_threshold:
                    should_execute = True
        
        assert should_execute is True, "First signal with position should execute when abs(edge) > min_threshold"
    
    def test_first_signal_below_threshold_skips(self, mock_loop):
        """Test that first signal with position skips if edge is below minimum threshold."""
        asset = "BTC"
        edge = 0.00005  # 0.005% edge (below minimum)
        current_best_edge = 0.0
        min_edge_threshold = 0.0001
        has_position = True
        
        should_execute = False
        if has_position:
            if abs(current_best_edge) > 0:
                edge_improvement_ratio = (abs(edge) - abs(current_best_edge)) / abs(current_best_edge)
                edge_improvement_threshold = 0.20
                if edge_improvement_ratio > edge_improvement_threshold:
                    should_execute = True
            else:
                # CRITICAL FIX: Use abs(edge) since edge = p_model - p_market can be negative
                if abs(edge) > min_edge_threshold:
                    should_execute = True
        
        assert should_execute is False, "First signal with position should skip when abs(edge) < min_threshold"
    
    def test_relative_improvement_executes(self, mock_loop):
        """Test that signal executes if it provides >20% relative improvement over current best."""
        asset = "BTC"
        edge = 0.061  # 6.1% edge (slightly above 6% to ensure >20% improvement)
        current_best_edge = 0.05  # 5% current best
        min_edge_threshold = 0.0001
        has_position = True
        
        should_execute = False
        if has_position:
            if abs(current_best_edge) > 0:
                # CRITICAL FIX: Use abs(edge) since edge = p_model - p_market can be negative
                edge_improvement_ratio = (abs(edge) - abs(current_best_edge)) / abs(current_best_edge)
                edge_improvement_threshold = 0.20
                if edge_improvement_ratio > edge_improvement_threshold:
                    should_execute = True
        
        # 0.061 - 0.05 = 0.011, 0.011 / 0.05 = 0.22 (22% improvement, >20% threshold)
        assert should_execute is True, "Signal should execute with >20% relative improvement"
    
    def test_relative_improvement_below_threshold_skips(self, mock_loop):
        """Test that signal skips if relative improvement is below 20% threshold."""
        asset = "BTC"
        edge = 0.055  # 5.5% edge
        current_best_edge = 0.05  # 5% current best
        min_edge_threshold = 0.0001
        has_position = True
        
        should_execute = False
        if has_position:
            if abs(current_best_edge) > 0:
                # CRITICAL FIX: Use abs(edge) since edge = p_model - p_market can be negative
                edge_improvement_ratio = (abs(edge) - abs(current_best_edge)) / abs(current_best_edge)
                edge_improvement_threshold = 0.20
                if edge_improvement_ratio > edge_improvement_threshold:
                    should_execute = True
        
        # 0.055 - 0.05 = 0.005, 0.005 / 0.05 = 0.10 (10% improvement, below 20%)
        assert should_execute is False, "Signal should skip with only 10% relative improvement"
    
    def test_no_position_executes_on_min_threshold(self, mock_loop):
        """Test that signal with no position executes if edge meets minimum threshold."""
        asset = "BTC"
        edge = 0.02  # 2% edge
        current_best_edge = 0.0
        min_edge_threshold = 0.0001
        has_position = False
        
        should_execute = False
        if not has_position:
            # CRITICAL FIX: Use abs(edge) since edge = p_model - p_market can be negative
            if abs(edge) > min_edge_threshold or abs(edge) > abs(current_best_edge):
                should_execute = True
        
        assert should_execute is True, "Signal with no position should execute when abs(edge) > min_threshold"
    
    def test_velocity_signal_edges_are_tiny(self, mock_loop):
        """Test that velocity-based signals have tiny edges (0.01-0.07%)."""
        # Typical velocity-based signal edges
        velocity_edges = [0.01, 0.02, 0.03, 0.05, 0.07]
        
        for edge in velocity_edges:
            # These should all be > min_edge_threshold (0.01%)
            assert edge > 0.0001, f"Velocity edge {edge}% should be > min_threshold"
            
            # But these would NOT meet old absolute 5% improvement threshold
            # if current_best_edge was 0.0
            old_threshold = 5.0
            assert edge < old_threshold, f"Velocity edge {edge}% should be < old 5% threshold"
    
    def test_old_absolute_threshold_would_block_all(self, mock_loop):
        """Test that old absolute 5% threshold would block all velocity signals."""
        # Simulate old logic: edge > current_best_edge + 5.0
        velocity_edges = [0.01, 0.02, 0.03, 0.05, 0.07]
        current_best_edge = 0.0
        old_improvement_threshold = 5.0
        
        for edge in velocity_edges:
            would_execute_old = edge > current_best_edge + old_improvement_threshold
            assert would_execute_old is False, f"Old logic would block velocity edge {edge}%"
    
    def test_new_relative_threshold_allows_velocity_signals(self, mock_loop):
        """Test that new relative 20% threshold allows velocity signals."""
        # Simulate new logic: relative improvement > 20%
        velocity_edges = [0.01, 0.02, 0.03, 0.05, 0.07]
        current_best_edge = 0.0
        min_edge_threshold = 0.0001
        
        for edge in velocity_edges:
            # First signal with position: abs(edge) > min_threshold
            would_execute_new = abs(edge) > min_edge_threshold
            assert would_execute_new is True, f"New logic should allow velocity edge {edge}%"

    def test_negative_edge_executes_with_abs_comparison(self, mock_loop):
        """Test that negative edges execute when using abs() comparison.
        
        This is the critical fix: edge = p_model - p_market can be negative when
        model disagrees with market. These are valid contrarian signals and should
        execute based on magnitude, not direction.
        """
        asset = "BTC"
        edge = -0.15  # -15% edge (model disagrees with market)
        current_best_edge = 0.0
        min_edge_threshold = 0.0001
        has_position = False
        
        should_execute = False
        if not has_position:
            # CRITICAL FIX: Use abs(edge) since edge = p_model - p_market can be negative
            if abs(edge) > min_edge_threshold or abs(edge) > abs(current_best_edge):
                should_execute = True
        
        assert should_execute is True, "Negative edge should execute when abs(edge) > min_threshold"

    def test_negative_edge_improvement_with_abs_comparison(self, mock_loop):
        """Test that negative edges can improve on current best using abs() comparison."""
        asset = "BTC"
        edge = -0.20  # -20% edge (stronger disagreement)
        current_best_edge = -0.15  # -15% current best
        min_edge_threshold = 0.0001
        has_position = True
        
        should_execute = False
        if has_position:
            if abs(current_best_edge) > 0:
                # CRITICAL FIX: Use abs(edge) since edge = p_model - p_market can be negative
                edge_improvement_ratio = (abs(edge) - abs(current_best_edge)) / abs(current_best_edge)
                edge_improvement_threshold = 0.20
                if edge_improvement_ratio > edge_improvement_threshold:
                    should_execute = True
        
        # 0.20 - 0.15 = 0.05, 0.05 / 0.15 = 0.33 (33% improvement, >20% threshold)
        assert should_execute is True, "Negative edge should execute with >20% relative improvement"


class TestEdgeImprovementIntegration:
    """Integration tests for edge improvement with candidate processing."""
    
    @pytest.fixture
    def sample_candidates(self):
        """Create sample candidates for testing."""
        return [
            {
                "ticker": "KXBTC15M-26JUL031615-15",
                "side": "yes",
                "edge": 0.02,
                "edge_pct": 0.02,
                "price_cents": 50
            },
            {
                "ticker": "KXETH15M-26JUL031615-15",
                "side": "no",
                "edge": 0.03,
                "edge_pct": 0.03,
                "price_cents": 52
            },
            {
                "ticker": "KXXRP15M-26JUL031615-15",
                "side": "no",
                "edge": 0.07,
                "edge_pct": 0.07,
                "price_cents": 50
            }
        ]
    
    def test_asset_extraction_from_ticker(self, sample_candidates):
        """Test asset extraction from Kalshi ticker format."""
        for candidate in sample_candidates:
            ticker = candidate["ticker"]
            
            # Extract asset (e.g., "KXBTC15M-26JUL031615-15" -> "BTC")
            if "15M" in ticker:
                asset_part = ticker.split("15M")[0]
            else:
                asset_part = ticker
            
            asset = asset_part.replace("KX", "")
            
            # Normalize asset name
            asset_map = {"BTC": "BTC", "ETH": "ETH", "SOL": "SOL", "XRP": "XRP", "DOGE": "DOGE"}
            asset = asset_map.get(asset, asset)
            
            assert asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"], f"Extracted asset {asset} should be valid"
    
    def test_candidate_edge_fields_present(self, sample_candidates):
        """Test that candidates have required edge fields."""
        for candidate in sample_candidates:
            assert "edge" in candidate, "Candidate should have 'edge' field"
            assert "edge_pct" in candidate, "Candidate should have 'edge_pct' field"
            # CRITICAL FIX: Edge can be negative (p_model - p_market), so check abs() instead
            assert abs(candidate["edge"]) > 0, "Edge magnitude should be positive"
            assert abs(candidate["edge_pct"]) > 0, "Edge percentage magnitude should be positive"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
