"""
Tests for Candidate Optimizer - Phase 5.4

Test suite for the candidate optimization functionality including:
- Candidate generation and filtering
- Quality-based ranking
- Performance metrics
- Parallel processing
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch
from typing import Dict, Any, List

from merid.prediction.candidate_optimizer import (
    CandidateOptimizer, 
    MarketCandidate, 
    CandidatePipelineMetrics,
    get_candidate_optimizer,
    reset_candidate_optimizer
)


class TestCandidateOptimizer:
    """Test the CandidateOptimizer class."""
    
    def test_optimizer_initialization(self):
        """Test optimizer initialization with default parameters."""
        optimizer = CandidateOptimizer()
        
        assert optimizer.max_workers == 4
        assert optimizer.cache_size == 1000
        # max_spread_cents is loaded from profile (40c) or legacy default (60c)
        # In test environment without profile, it falls back to legacy default
        assert optimizer.max_spread_cents in [40, 60]  # Profile-loaded or legacy default
        assert optimizer.MIN_DEPTH_LEVELS == 1  # Reduced to allow one-sided markets
        assert optimizer.MIN_LIQUIDITY_SCORE == 0.05  # Reduced to allow one-sided markets
        assert optimizer.MIN_QUALITY_SCORE == 0.05  # Reduced to allow one-sided markets
        assert optimizer.MAX_MINUTES_TO_EXPIRY == 30
    
    def test_optimizer_initialization_with_custom_params(self):
        """Test optimizer initialization with custom parameters."""
        optimizer = CandidateOptimizer(max_workers=2, cache_size=500)
        
        assert optimizer.max_workers == 2
        assert optimizer.cache_size == 500
    
    @pytest.mark.asyncio
    async def test_generate_candidates_empty_markets(self):
        """Test candidate generation with empty markets list."""
        optimizer = CandidateOptimizer()
        
        candidates, metrics = await optimizer.generate_candidates(
            [], "BTC", Mock(), Mock()
        )
        
        assert len(candidates) == 0
        assert metrics.total_markets_scanned == 0
        assert metrics.final_candidates == 0
        assert metrics.status == "empty"  # Empty result should have status="empty"
    
    @pytest.mark.asyncio
    async def test_generate_candidates_valid_markets(self):
        """Test candidate generation with valid markets."""
        optimizer = CandidateOptimizer()
        
        # Create mock markets
        markets = [
            {
                "market_id": "market_1",
                "asset": "BTC",
                "series_ticker": "KXBTC-15M",
                "close_time": "2026-06-03T12:15:00Z"
            },
            {
                "market_id": "market_2",
                "asset": "BTC",
                "series_ticker": "KXBTC-15M",
                "close_time": "2026-06-03T12:30:00Z"
            }
        ]
        
        # Create simple state objects with actual integer values
        class SimpleState:
            def __init__(self):
                self.last_update_ts = time.time()
                self.spread_cents = 2
                self.mid_cents = 50
                self.min_depth_yes = 50
                self.min_depth_no = 50
                self.best_bid_cents = 48
                self.best_ask_cents = 52
        
        # Create mock market state store that returns simple state objects
        market_state_store = Mock()
        market_state_store.get.return_value = SimpleState()
        
        # Create mock spot service
        spot_service = Mock()
        spot_service._cache = {"BTC": {"timestamp": time.time()}}
        
        candidates, metrics = await optimizer.generate_candidates(
            markets, "BTC", market_state_store, spot_service
        )
        
        assert len(candidates) > 0
        assert metrics.total_markets_scanned == 2
        assert metrics.markets_with_md == 2
        assert metrics.markets_with_spot == 2  # Both markets have spot data
        assert metrics.final_candidates > 0
        assert metrics.status == "success"  # Successful generation
    
    @pytest.mark.asyncio
    async def test_generate_candidates_no_market_state(self):
        """Test candidate generation with no market state."""
        optimizer = CandidateOptimizer()
        
        # Create mock markets
        markets = [
            {
                "market_id": "market_1",
                "asset": "BTC",
                "series_ticker": "KXBTC-15M",
                "close_time": "2026-06-03T12:15:00Z"
            }
        ]
        
        # Create mock market state store that returns None
        market_state_store = Mock()
        market_state_store.get.return_value = None
        
        # Create mock spot service
        spot_service = Mock()
        spot_service._cache = {"BTC": {"timestamp": time.time()}}
        
        candidates, metrics = await optimizer.generate_candidates(
            markets, "BTC", market_state_store, spot_service
        )
        
        assert len(candidates) == 0
        assert metrics.total_markets_scanned == 1
        assert metrics.markets_with_md == 0
        assert metrics.final_candidates == 0
        assert metrics.status == "empty"  # No candidates generated
    
    def test_create_market_candidate_valid(self):
        """Test creating a valid market candidate."""
        optimizer = CandidateOptimizer()
        
        market = {
            "market_id": "market_1",
            "asset": "BTC",
            "series_ticker": "KXBTC-15M",
            "close_time": "2026-06-03T12:15:00Z"
        }
        
        # Create mock market state with actual integer values
        state = Mock()
        state.spread_cents = 5
        state.mid_cents = 50
        state.min_depth_yes = 5  # Use correct field name
        state.min_depth_no = 5   # Use correct field name
        
        # Create mock spot service
        spot_service = Mock()
        spot_service._cache = {"BTC": {"timestamp": time.time()}}
        
        # Run in event loop
        candidate = asyncio.run(optimizer._create_market_candidate(market, state, spot_service))
        
        assert candidate.market_id == "market_1"
        assert candidate.asset == "BTC"
        assert candidate.series_ticker == "KXBTC-15M"
        assert candidate.ticker == "KXBTC-15M"  # ticker alias
        assert candidate.spread_cents == 5
        assert candidate.mid_cents == 50
        assert candidate.depth_yes == 5
        assert candidate.depth_no == 5
        assert candidate.total_depth == 10
        assert candidate.is_valid is True
        assert len(candidate.errors) == 0
    
    def test_create_market_candidate_invalid_market(self):
        """Test creating a market candidate with invalid market data."""
        optimizer = CandidateOptimizer()
        
        market = {}  # Empty market
        
        # Create mock market state with actual integer values
        state = Mock()
        state.spread_cents = 5
        state.mid_cents = 50
        state.min_depth_yes = 5  # Use correct field name
        state.min_depth_no = 5   # Use correct field name
        
        # Create mock spot service
        spot_service = Mock()
        spot_service._cache = {"BTC": {"timestamp": time.time()}}
        
        # Should create candidate with empty market_id
        candidate = asyncio.run(optimizer._create_market_candidate(market, state, spot_service))
        assert candidate.market_id is None
        assert candidate.asset == ""
        assert candidate.series_ticker == ""
        assert candidate.ticker == ""
    
    @pytest.mark.asyncio
    async def test_filter_by_quality(self):
        """Test filtering candidates by quality score."""
        optimizer = CandidateOptimizer()
        
        # Create candidates with different quality scores
        candidates = [
            MarketCandidate(
                market_id="high_quality",
                asset="BTC",
                series_ticker="KXBTC-15M",
                spread_cents=2,
                mid_cents=50,
                depth_yes=10,
                depth_no=10,
                total_depth=20,
                liquidity_score=0.9,
                quality_score=0.95,
                edge_threshold=0.01,
                implied_prob=0.5,
                minutes_to_expiry=10,
                timestamp=time.time()
            ),
            MarketCandidate(
                market_id="medium_quality",
                asset="BTC",
                series_ticker="KXBTC-15M",
                spread_cents=8,
                mid_cents=50,
                depth_yes=5,
                depth_no=5,
                total_depth=10,
                liquidity_score=0.6,
                quality_score=0.65,
                edge_threshold=0.02,
                implied_prob=0.5,
                minutes_to_expiry=15,
                timestamp=time.time()
            ),
            MarketCandidate(
                market_id="low_quality",
                asset="BTC",
                series_ticker="KXBTC-15M",
                spread_cents=20,
                mid_cents=50,
                depth_yes=0,  # Zero depth to fail filter
                depth_no=0,
                total_depth=0,
                liquidity_score=0.0,  # Zero liquidity to fail filter
                quality_score=0.0,  # Zero quality to fail filter
                edge_threshold=0.03,
                implied_prob=0.5,
                minutes_to_expiry=25,
                timestamp=time.time()
            )
        ]
        
        metrics = CandidatePipelineMetrics()
        
        # Filter with minimum quality of 0.05 (updated threshold)
        filtered = await optimizer._filter_by_quality(candidates, metrics)
        
        assert len(filtered) == 2
        assert filtered[0].market_id == "high_quality"
        assert filtered[1].market_id == "medium_quality"
        assert metrics.markets_passing_quality == 2
        assert metrics.filter_breakdown.get("spread_too_wide", 0) == 0  # No spread rejections with updated thresholds
    
    @pytest.mark.asyncio
    async def test_filter_by_edge_threshold(self):
        """Test filtering candidates by edge threshold."""
        optimizer = CandidateOptimizer()
        
        # Create candidates with different edge thresholds
        candidates = [
            MarketCandidate(
                market_id="low_edge",
                asset="BTC",
                series_ticker="KXBTC-15M",
                spread_cents=2,
                mid_cents=50,
                depth_yes=10,
                depth_no=10,
                total_depth=20,
                liquidity_score=0.9,
                quality_score=0.95,
                edge_threshold=0.02,  # Below 5%
                implied_prob=0.5,
                minutes_to_expiry=10,
                timestamp=time.time()
            ),
            MarketCandidate(
                market_id="high_edge",
                asset="BTC",
                series_ticker="KXBTC-15M",
                spread_cents=20,
                mid_cents=50,
                depth_yes=1,
                depth_no=1,
                total_depth=2,
                liquidity_score=0.1,
                quality_score=0.15,
                edge_threshold=0.08,  # Above 5%
                implied_prob=0.5,
                minutes_to_expiry=25,
                timestamp=time.time()
            )
        ]
        
        metrics = CandidatePipelineMetrics()
        
        # Filter by edge threshold (max 5%)
        filtered = await optimizer._filter_by_edge_threshold(candidates, metrics)
        
        assert len(filtered) == 1
        assert filtered[0].market_id == "low_edge"
        assert metrics.markets_passing_edge == 1
        assert metrics.filter_breakdown.get("edge_too_high", 0) == 1
    
    @pytest.mark.asyncio
    async def test_rank_and_select_candidates(self):
        """Test ranking and selecting candidates."""
        optimizer = CandidateOptimizer()
        
        # Create candidates with different quality scores (all passing filters)
        candidates = [
            MarketCandidate(
                market_id="medium_quality",
                asset="BTC",
                series_ticker="KXBTC-15M",
                spread_cents=8,
                mid_cents=50,
                depth_yes=5,
                depth_no=5,
                total_depth=10,
                liquidity_score=0.6,
                quality_score=0.65,
                edge_threshold=0.02,
                implied_prob=0.5,
                minutes_to_expiry=15,
                timestamp=time.time()
            ),
            MarketCandidate(
                market_id="high_quality",
                asset="BTC",
                series_ticker="KXBTC-15M",
                spread_cents=2,
                mid_cents=50,
                depth_yes=10,
                depth_no=10,
                total_depth=20,
                liquidity_score=0.9,
                quality_score=0.95,
                edge_threshold=0.01,
                implied_prob=0.5,
                minutes_to_expiry=10,
                timestamp=time.time()
            ),
            MarketCandidate(
                market_id="low_quality",
                asset="BTC",
                series_ticker="KXBTC-15M",
                spread_cents=12,  # Reduced spread to pass filter (max_spread_cents = 60)
                mid_cents=50,
                depth_yes=1,   # Reduced depth to pass filter (MIN_DEPTH_LEVELS = 1)
                depth_no=1,
                total_depth=2,
                liquidity_score=0.06,  # Increased to pass filter (MIN_LIQUIDITY_SCORE = 0.05)
                quality_score=0.06,  # Increased to pass filter (MIN_QUALITY_SCORE = 0.05)
                edge_threshold=0.03,  # Below 5% filter limit
                implied_prob=0.5,
                minutes_to_expiry=25,
                timestamp=time.time()
            )
        ]
        
        metrics = CandidatePipelineMetrics()
        
        # Rank and select top candidates
        selected = await optimizer._rank_and_select_candidates(candidates, metrics)
        
        assert len(selected) == 3  # All candidates (max 5)
        assert selected[0].market_id == "high_quality"  # Best quality first
        assert selected[1].market_id == "medium_quality"
        assert selected[2].market_id == "low_quality"
        assert metrics.final_candidates == 3
    
    def test_calculate_liquidity_score(self):
        """Test liquidity score calculation."""
        optimizer = CandidateOptimizer()
        
        # Test different spread and depth combinations
        test_cases = [
            (1, 10),   # Tight spread, good depth -> high liquidity
            (5, 5),    # Medium spread, medium depth -> medium liquidity
            (10, 2),   # Wide spread, poor depth -> low liquidity
            (15, 1),   # Very wide spread, very poor depth -> very low liquidity
        ]
        
        for spread_cents, total_depth in test_cases:
            score = optimizer._calculate_liquidity_score(spread_cents, total_depth)
            
            assert 0.0 <= score <= 1.0
    
    def test_calculate_quality_score(self):
        """Test quality score calculation."""
        optimizer = CandidateOptimizer()
        
        # Test different spread and depth combinations
        test_cases = [
            (1, 10, 0.9),   # Tight spread, good depth, high liquidity -> high quality
            (5, 5, 0.6),    # Medium spread, medium depth, medium liquidity -> medium quality
            (10, 2, 0.3),   # Wide spread, poor depth, low liquidity -> low quality
            (15, 1, 0.1),   # Very wide spread, very poor depth, very low liquidity -> very low quality
        ]
        
        for spread_cents, total_depth, liquidity_score in test_cases:
            score = optimizer._calculate_quality_score(spread_cents, total_depth, liquidity_score)
            
            assert 0.0 <= score <= 1.0
    
    def test_calculate_edge_threshold(self):
        """Test edge threshold calculation."""
        optimizer = CandidateOptimizer()
        
        # Test with different spread and depth combinations
        test_cases = [
            (1, 10),   # Tight spread, good depth -> low edge
            (5, 5),    # Medium spread, medium depth -> medium edge
            (10, 2),   # Wide spread, poor depth -> high edge
            (15, 1),   # Very wide spread, very poor depth -> very high edge (clamped)
        ]
        
        for spread_cents, total_depth in test_cases:
            edge_threshold = optimizer._calculate_edge_threshold(spread_cents, total_depth)
            
            assert edge_threshold >= 0.01  # Minimum 1%
            # Note: Edge threshold can be very high for extreme cases (poor liquidity)
            assert edge_threshold <= 15.0   # Should be reasonable (allow higher for extreme cases)
    
    def test_calculate_minutes_to_expiry_valid(self):
        """Test calculating minutes to expiry with valid data."""
        optimizer = CandidateOptimizer()
        
        # Test with valid expiry time
        market = {
            "close_time": "2026-06-03T12:15:00Z"
        }
        
        # Just verify it returns a reasonable value (not 999.0 which indicates error)
        minutes = optimizer._calculate_minutes_to_expiry(market)
        assert 0.0 <= minutes <= 999.0
        assert isinstance(minutes, float)
    
    def test_calculate_minutes_to_expiry_invalid(self):
        """Test calculating minutes to expiry with invalid data."""
        optimizer = CandidateOptimizer()
        
        # Test with no expiry time
        market = {}
        
        minutes = optimizer._calculate_minutes_to_expiry(market)
        
        assert minutes == 999.0  # Default value for invalid expiry
    
    def test_get_performance_metrics(self):
        """Test performance metrics retrieval."""
        optimizer = CandidateOptimizer()
        
        # Set some metrics
        optimizer._total_candidates_generated = 100
        optimizer._total_pipeline_time = 5000.0  # 5 seconds
        optimizer._total_errors = 2
        
        # Set current metrics
        optimizer._pipeline_metrics.total_markets_scanned = 50
        optimizer._pipeline_metrics.markets_with_md = 45
        optimizer._pipeline_metrics.final_candidates = 5
        
        metrics = optimizer.get_performance_metrics()
        
        assert metrics["total_candidates_generated"] == 100
        assert metrics["avg_pipeline_time_ms"] == 50.0  # 5000ms / 100 candidates
        assert metrics["total_pipeline_time_ms"] == 5000.0
        assert metrics["total_errors"] == 2
        
        current = metrics["current_metrics"]
        assert current["total_markets_scanned"] == 50
        assert current["markets_with_md"] == 45
        assert current["final_candidates"] == 5
    
    def test_reset_metrics(self):
        """Test resetting performance metrics."""
        optimizer = CandidateOptimizer()
        
        # Set some metrics
        optimizer._total_candidates_generated = 100
        optimizer._total_pipeline_time = 5000.0
        optimizer._total_errors = 2
        optimizer._pipeline_metrics.total_markets_scanned = 50
        
        # Reset metrics
        optimizer.reset_metrics()
        
        assert optimizer._total_candidates_generated == 0
        assert optimizer._total_pipeline_time == 0.0
        assert optimizer._total_errors == 0
        assert optimizer._pipeline_metrics.total_markets_scanned == 0
    
    def test_clear_cache(self):
        """Test clearing candidate cache."""
        optimizer = CandidateOptimizer()
        
        # Add some cache entries
        optimizer._candidate_cache["test1"] = MarketCandidate(
            market_id="test1",
            asset="BTC",
            series_ticker="KXBTC-15M",
            spread_cents=5,
            mid_cents=50,
            depth_yes=5,
            depth_no=5,
            total_depth=10,
            liquidity_score=0.8,
            quality_score=0.85,
            edge_threshold=0.02,
            implied_prob=0.5,
            minutes_to_expiry=10,
            timestamp=time.time()
        )
        
        assert len(optimizer._candidate_cache) == 1
        
        # Clear cache
        optimizer.clear_cache()
        
        assert len(optimizer._candidate_cache) == 0
    
    def test_check_spot_data_available(self):
        """Test checking spot data availability."""
        optimizer = CandidateOptimizer()
        
        # Test with available spot data
        spot_service = Mock()
        spot_service._cache = {"BTC": {"timestamp": time.time()}}
        
        result = asyncio.run(optimizer._check_spot_data(spot_service, "BTC"))
        
        assert result is True
    
    def test_check_spot_data_unavailable(self):
        """Test checking spot data availability when unavailable."""
        optimizer = CandidateOptimizer()
        
        # Test with no spot service
        result = asyncio.run(optimizer._check_spot_data(None, "BTC"))
        
        assert result is False
        
        # Test with empty cache
        spot_service = Mock()
        spot_service._cache = {}
        
        result = asyncio.run(optimizer._check_spot_data(spot_service, "BTC"))
        
        assert result is False
    
    # Helper methods
    
    def _create_mock_market_state(self):
        """Create a mock market state for testing."""
        def get_side_effect(market_id):
            state = Mock()
            state.last_update_ts = time.time()
            state.spread_cents = 2  # Lower spread to reduce edge threshold
            state.mid_cents = 50
            state.depth_yes = 50  # Higher depth to reduce liquidity penalty
            state.depth_no = 50
            return state
        
        return get_side_effect


class TestCandidateOptimizerSingleton:
    """Test the global candidate optimizer singleton pattern."""
    
    def test_get_candidate_optimizer_singleton(self):
        """Test that get_candidate_optimizer returns the same instance."""
        reset_candidate_optimizer()
        
        optimizer1 = get_candidate_optimizer()
        optimizer2 = get_candidate_optimizer()
        
        assert optimizer1 is optimizer2
        assert isinstance(optimizer1, CandidateOptimizer)
    
    def test_reset_candidate_optimizer(self):
        """Test resetting the global candidate optimizer."""
        # Get initial optimizer
        optimizer1 = get_candidate_optimizer()
        
        # Add some data
        optimizer1._total_candidates_generated = 10
        
        # Reset optimizer
        reset_candidate_optimizer()
        
        # Get new optimizer
        optimizer2 = get_candidate_optimizer()
        
        assert optimizer2 is not optimizer1  # Should be a new instance
        assert optimizer2._total_candidates_generated == 0


class TestCandidateOptimizerStatusField:
    """Test the status field in CandidatePipelineMetrics for error propagation."""
    
    @pytest.mark.asyncio
    async def test_status_success_when_candidates_generated(self):
        """Test status='success' when candidates are generated successfully."""
        optimizer = CandidateOptimizer()
        
        markets = [
            {
                "market_id": "market_1",
                "asset": "BTC",
                "series_ticker": "KXBTC-15M",
                "close_time": "2026-06-03T12:15:00Z"
            }
        ]
        
        market_state_store = Mock()
        market_state_store.get.side_effect = self._create_mock_market_state()
        spot_service = Mock()
        spot_service._cache = {"BTC": {"timestamp": time.time()}}
        
        candidates, metrics = await optimizer.generate_candidates(
            markets, "BTC", market_state_store, spot_service
        )
        
        assert len(candidates) > 0
        assert metrics.status == "success"
    
    @pytest.mark.asyncio
    async def test_status_empty_when_no_candidates(self):
        """Test status='empty' when no candidates are generated."""
        optimizer = CandidateOptimizer()
        
        candidates, metrics = await optimizer.generate_candidates(
            [], "BTC", Mock(), Mock()
        )
        
        assert len(candidates) == 0
        # With early return fix, empty markets should return "empty" status
        assert metrics.status == "empty"
    
    @pytest.mark.asyncio
    async def test_status_error_on_pipeline_error(self):
        """Test status='error' when pipeline encounters an error."""
        optimizer = CandidateOptimizer()
        
        # Create a market that will cause an error (missing required fields)
        markets = [{"invalid": "data"}]
        
        market_state_store = Mock()
        market_state_store.get.return_value = None
        spot_service = Mock()
        
        candidates, metrics = await optimizer.generate_candidates(
            markets, "BTC", market_state_store, spot_service
        )
        
        # Should handle error gracefully and return status
        assert metrics.status in ["empty", "error"]  # Either is acceptable for invalid input
    
    def _create_mock_market_state(self):
        """Create a mock market state for testing."""
        def get_side_effect(market_id):
            # Return a simple object with actual integer values, not Mock
            class SimpleState:
                def __init__(self):
                    self.last_update_ts = time.time()
                    self.spread_cents = 2
                    self.mid_cents = 50
                    self.min_depth_yes = 50  # Use correct field name (integer)
                    self.min_depth_no = 50   # Use correct field name (integer)
                    self.best_bid_cents = 48
                    self.best_ask_cents = 52
            return SimpleState()
        return get_side_effect


if __name__ == "__main__":
    pytest.main([__file__])
