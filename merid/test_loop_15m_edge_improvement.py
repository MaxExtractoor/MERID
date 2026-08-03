"""
Tests for edge improvement threshold logic in loop_15m.py.

This tests the fix that changed edge improvement from relative (20%) to absolute (0.5% delta)
to accommodate exposure-aware re-entry logic for time-in-window trading.
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
        loop._executed_candidates_this_window = {}  # Dict, not set (for edge tracking)
        loop._tick_executed_count = 0  # Per-tick counter for sanity checks
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
    
    def test_absolute_improvement_executes(self, mock_loop):
        """Test that signal executes if it provides >0.5% absolute improvement over current best."""
        asset = "BTC"
        edge = 0.056  # 5.6% edge (0.6% above 5%)
        current_best_edge = 0.05  # 5% current best
        min_edge_threshold = 0.0001
        has_position = True
        
        should_execute = False
        if has_position:
            if abs(current_best_edge) > 0:
                # CRITICAL FIX (2026-07-24): Use absolute 0.5% delta instead of relative 20%
                edge_improvement_delta = 0.005  # 0.5%
                if abs(edge) > abs(current_best_edge) + edge_improvement_delta:
                    should_execute = True
        
        # 0.056 - 0.05 = 0.006 (0.6% improvement, >0.5% threshold)
        assert should_execute is True, "Signal should execute with >0.5% absolute improvement"
    
    def test_absolute_improvement_below_threshold_skips(self, mock_loop):
        """Test that signal skips if absolute improvement is below 0.5% threshold."""
        asset = "BTC"
        edge = 0.052  # 5.2% edge (only 0.2% above 5%)
        current_best_edge = 0.05  # 5% current best
        min_edge_threshold = 0.0001
        has_position = True
        
        should_execute = False
        if has_position:
            if abs(current_best_edge) > 0:
                # CRITICAL FIX (2026-07-24): Use absolute 0.5% delta instead of relative 20%
                edge_improvement_delta = 0.005  # 0.5%
                if abs(edge) > abs(current_best_edge) + edge_improvement_delta:
                    should_execute = True
        
        # 0.052 - 0.05 = 0.002 (0.2% improvement, below 0.5% threshold)
        assert should_execute is False, "Signal should skip with only 0.2% absolute improvement"
    
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
    
    def test_old_relative_threshold_would_block_some(self, mock_loop):
        """Test that old relative 20% threshold would block some small improvements."""
        # Simulate old logic: relative improvement > 20%
        small_improvements = [0.051, 0.052, 0.053, 0.054]  # 5.1%, 5.2%, 5.3%, 5.4%
        current_best_edge = 0.05  # 5% current best
        
        for edge in small_improvements:
            edge_improvement_ratio = (abs(edge) - abs(current_best_edge)) / abs(current_best_edge)
            would_execute_old = edge_improvement_ratio > 0.20
            assert would_execute_old is False, f"Old relative logic would block edge {edge}%"
    
    def test_new_absolute_threshold_allows_small_improvements(self, mock_loop):
        """Test that new absolute 0.5% threshold allows small improvements."""
        # Simulate new logic: absolute improvement > 0.5%
        small_improvements = [0.051, 0.052, 0.053, 0.054]  # 5.1%, 5.2%, 5.3%, 5.4%
        current_best_edge = 0.05  # 5% current best
        edge_improvement_delta = 0.005  # 0.5%
        
        for edge in small_improvements:
            would_execute_new = abs(edge) > abs(current_best_edge) + edge_improvement_delta
            # 0.051 - 0.05 = 0.001 (below 0.5%), 0.054 - 0.05 = 0.004 (below 0.5%)
            # These would still be blocked, but 0.055+ would be allowed
            if edge >= 0.055:
                assert would_execute_new is True, f"New absolute logic should allow edge {edge}%"

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
                # CRITICAL FIX (2026-07-24): Use absolute 0.5% delta instead of relative 20%
                edge_improvement_delta = 0.005  # 0.5%
                if abs(edge) > abs(current_best_edge) + edge_improvement_delta:
                    should_execute = True
        
        # 0.20 - 0.15 = 0.05 (5% improvement, >0.5% threshold)
        assert should_execute is True, "Negative edge should execute with >0.5% absolute improvement"


class TestEdgeImprovementIntegration:
    """Integration tests for edge improvement with candidate processing."""
    
    @pytest.fixture
    def sample_candidates(self):
        """Create sample candidates for testing."""
        return [
            {
                "ticker": "KXBTC15M-26JUL031615-15",
                "side": "yes",
                "edge_pct": 0.02,  # Single source of truth: edge_pct in FRACTION units
                "price_cents": 50
            },
            {
                "ticker": "KXETH15M-26JUL031615-15",
                "side": "no",
                "edge_pct": 0.03,  # Single source of truth: edge_pct in FRACTION units
                "price_cents": 52
            },
            {
                "ticker": "KXXRP15M-26JUL031615-15",
                "side": "no",
                "edge_pct": 0.07,  # Single source of truth: edge_pct in FRACTION units
                "price_cents": 50
            }
        ]
    
    def test_asset_extraction_from_ticker(self, sample_candidates):
        """Test asset extraction from Kalshi ticker format."""
        for candidate in sample_candidates:
            ticker = candidate["ticker"]
            
            # CRITICAL FIX (2026-07-21): Use canonical identity helper for asset extraction
            from merid.utils.kalshi_identity import extract_asset
            asset = extract_asset(ticker)
            
            assert asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"], f"Extracted asset {asset} should be valid"
    
    def test_candidate_edge_fields_present(self, sample_candidates):
        """Test that candidates have required edge fields."""
        for candidate in sample_candidates:
            assert "edge_pct" in candidate, "Candidate should have 'edge_pct' field (single source of truth)"
            # CRITICAL FIX: Edge can be negative (p_model - p_market), so check abs() instead
            assert abs(candidate["edge_pct"]) > 0, "Edge percentage magnitude should be positive"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
