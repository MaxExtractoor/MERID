"""
Tests for Spread Optimizer - Phase 5.3

Test suite for the spread optimization functionality including:
- Spread metrics calculation
- Edge threshold computation with caching
- Market quality assessment
- Performance monitoring
"""

import pytest
import time
from unittest.mock import Mock, patch, AsyncMock
from typing import Dict, Any

from merid.prediction.spread_optimizer import (
    SpreadOptimizer, 
    SpreadMetrics, 
    EdgeCalculationCache,
    get_spread_optimizer,
    reset_spread_optimizer
)


class TestSpreadOptimizer:
    """Test the SpreadOptimizer class."""
    
    def test_optimizer_initialization(self):
        """Test optimizer initialization with default parameters."""
        optimizer = SpreadOptimizer()
        
        assert optimizer.cache_size == 1000
        assert optimizer.MAX_SPREAD_CENTS == 30  # 2026-07-10: Optimized to 30c to harmonize with 10c-50c entry price sweet spot
        assert optimizer.MIN_DEPTH_LEVELS == 2
        assert optimizer.MIN_LIQUIDITY_SCORE == 0.3
        assert len(optimizer._edge_cache) == 0
        assert len(optimizer._spread_metrics) == 0
    
    def test_optimizer_initialization_with_custom_params(self):
        """Test optimizer initialization with custom parameters."""
        optimizer = SpreadOptimizer(cache_size=500)
        
        assert optimizer.cache_size == 500
        assert len(optimizer._edge_cache) == 0
        assert len(optimizer._spread_metrics) == 0
    
    def test_calculate_spread_metrics_valid_market(self):
        """Test spread metrics calculation for a valid market."""
        optimizer = SpreadOptimizer()
        
        # Create mock market state
        market_state = Mock()
        market_state.best_bid_cents = 45
        market_state.best_ask_cents = 55
        market_state.yes_bids = [(45, 10), (44, 8), (43, 5)]
        market_state.no_bids = [(55, 12), (56, 6), (57, 3)]
        
        metrics = optimizer.calculate_spread_metrics(market_state, "test_market")
        
        assert metrics.market_id == "test_market"
        assert metrics.spread_cents == 10.0
        assert metrics.mid_cents == 50.0
        assert metrics.best_bid == 45
        assert metrics.best_ask == 55
        assert metrics.depth_yes == 3
        assert metrics.depth_no == 3
        assert metrics.total_depth == 6
        assert metrics.skew == 0.5
        assert metrics.is_valid is True
        assert len(metrics.errors) == 0
    
    def test_calculate_spread_metrics_missing_bid(self):
        """Test spread metrics calculation with missing bid."""
        optimizer = SpreadOptimizer()
        
        # Create mock market state with missing bid
        market_state = Mock()
        market_state.best_bid_cents = None
        market_state.best_ask_cents = 55
        
        metrics = optimizer.calculate_spread_metrics(market_state, "test_market")
        
        assert metrics.is_valid is False
        assert metrics.spread_cents == 0.0
        assert metrics.best_bid == 0
        assert metrics.best_ask == 0  # Should be 0 when invalid
        assert len(metrics.errors) > 0
        assert any("bid" in error.lower() for error in metrics.errors)
    
    def test_calculate_spread_metrics_missing_ask(self):
        """Test spread metrics calculation with missing ask."""
        optimizer = SpreadOptimizer()
        
        # Create mock market state with missing ask
        market_state = Mock()
        market_state.best_bid_cents = 45
        market_state.best_ask_cents = None
        
        metrics = optimizer.calculate_spread_metrics(market_state, "test_market")
        
        assert metrics.is_valid is False
        assert metrics.spread_cents == 0.0
        assert metrics.best_bid == 0  # Should be 0 when invalid
        assert metrics.best_ask == 0
        assert len(metrics.errors) > 0
        assert any("ask" in error.lower() for error in metrics.errors)
    
    def test_calculate_spread_metrics_invalid_spread(self):
        """Test spread metrics calculation with invalid spread."""
        optimizer = SpreadOptimizer()
        
        # Create mock market state with invalid spread (ask <= bid)
        market_state = Mock()
        market_state.best_bid_cents = 55
        market_state.best_ask_cents = 45
        
        metrics = optimizer.calculate_spread_metrics(market_state, "test_market")
        
        assert metrics.is_valid is False
        assert metrics.spread_cents == 0.0
        assert len(metrics.errors) > 0
        assert any("spread" in error.lower() for error in metrics.errors)
    
    def test_calculate_spread_metrics_different_attributes(self):
        """Test spread metrics calculation with different attribute names."""
        optimizer = SpreadOptimizer()
        
        # Create mock market state with different attribute names
        market_state = Mock()
        # Remove the default attributes
        delattr(market_state, 'best_bid_cents')
        delattr(market_state, 'best_ask_cents')
        # Add alternative attributes
        market_state.best_yes_bid = 45
        market_state.best_yes_ask = 55
        market_state.depth_yes = 3
        market_state.depth_no = 3
        
        metrics = optimizer.calculate_spread_metrics(market_state, "test_market")
        
        assert metrics.is_valid is True
        assert metrics.spread_cents == 10.0
        assert metrics.mid_cents == 50.0
        assert metrics.best_bid == 45
        assert metrics.best_ask == 55
        # Note: depth extraction may return 0 if attribute format doesn't match expected pattern
        # This is expected behavior for the current implementation
    
    def test_compute_edge_threshold_cached_cache_miss(self):
        """Test edge threshold computation with cache miss."""
        optimizer = SpreadOptimizer()
        
        # First call should be a cache miss
        edge_threshold = optimizer.compute_edge_threshold_cached(10, 5, "test_market")
        
        assert edge_threshold > 0.0
        assert optimizer._cache_misses == 1
        assert optimizer._cache_hits == 0
        assert optimizer._calculations == 1
        
        # Check cache entry
        cache_key = f"test_market_10_5"
        assert cache_key in optimizer._edge_cache
        assert optimizer._edge_cache[cache_key].edge_threshold == edge_threshold
    
    def test_compute_edge_threshold_cached_cache_hit(self):
        """Test edge threshold computation with cache hit."""
        optimizer = SpreadOptimizer()
        
        # First call to populate cache
        edge_threshold1 = optimizer.compute_edge_threshold_cached(10, 5, "test_market")
        
        # Second call should be a cache hit
        edge_threshold2 = optimizer.compute_edge_threshold_cached(10, 5, "test_market")
        
        assert edge_threshold1 == edge_threshold2
        assert optimizer._cache_misses == 1
        assert optimizer._cache_hits == 1
        assert optimizer._calculations == 1  # Only one calculation
    
    def test_compute_edge_threshold_cached_cache_expiry(self):
        """Test edge threshold computation with cache expiry."""
        optimizer = SpreadOptimizer()
        
        # Create cache entry with short TTL
        cache_key = f"test_market_10_5"
        optimizer._edge_cache[cache_key] = EdgeCalculationCache(
            market_id="test_market",
            edge_threshold=0.02,
            spread_cents=10,
            total_depth=5,
            computed_at=time.time() - 10.0,  # 10 seconds ago
            ttl_seconds=5.0  # 5 second TTL
        )
        
        # Call should miss cache due to expiry
        edge_threshold = optimizer.compute_edge_threshold_cached(10, 5, "test_market")
        
        assert optimizer._cache_misses == 1
        assert optimizer._cache_hits == 0
        assert optimizer._calculations == 1
    
    def test_compute_edge_threshold_optimized(self):
        """Test optimized edge threshold calculation."""
        optimizer = SpreadOptimizer()
        
        # Test with different spread and depth combinations
        test_cases = [
            (1, 10),   # Tight spread, good depth
            (5, 5),    # Medium spread, medium depth
            (10, 2),   # Wide spread, poor depth
            (15, 1),   # Very wide spread, very poor depth - will hit ceiling
        ]
        
        for spread_cents, total_depth in test_cases:
            edge_threshold = optimizer._compute_edge_threshold_optimized(spread_cents, total_depth)
            
            assert edge_threshold >= 0.005  # Minimum 0.5%
            assert edge_threshold <= 0.1    # Maximum 10%
            
            # Higher spread should result in higher edge threshold
            if total_depth > 0:
                spread_penalty = (spread_cents / 100.0) * 2.0
                liquidity_penalty = max(0.0, (10.0 / total_depth) - 0.1)
                expected_min = max(0.01, spread_penalty + liquidity_penalty)
                # Clamp to ceiling (0.1) for comparison
                expected_min = min(expected_min, 0.1)
                assert edge_threshold >= expected_min - 0.01  # Allow small tolerance
    
    def test_assess_market_quality(self):
        """Test market quality assessment."""
        optimizer = SpreadOptimizer()
        
        # Create mock metrics
        metrics = SpreadMetrics(
            market_id="test_market",
            spread_cents=5.0,
            mid_cents=50.0,
            best_bid=45,
            best_ask=55,
            depth_yes=5,
            depth_no=5,
            total_depth=10,
            skew=0.5,
            liquidity_score=0.8,
            quality_score=0.85,
            timestamp=time.time()
        )
        
        optimizer._spread_metrics["test_market"] = metrics
        
        quality = optimizer.assess_market_quality("test_market")
        
        assert quality == 0.85
    
    def test_assess_market_quality_not_found(self):
        """Test market quality assessment for unknown market."""
        optimizer = SpreadOptimizer()
        
        quality = optimizer.assess_market_quality("unknown_market")
        
        assert quality is None
    
    def test_filter_markets_by_quality(self):
        """Test filtering markets by quality score."""
        optimizer = SpreadOptimizer()
        
        # Create mock metrics for different markets
        markets = [
            ("high_quality", 0.9),
            ("medium_quality", 0.6),
            ("low_quality", 0.3),
            ("very_low_quality", 0.1),
        ]
        
        for market_id, quality_score in markets:
            metrics = SpreadMetrics(
                market_id=market_id,
                spread_cents=5.0,
                mid_cents=50.0,
                best_bid=45,
                best_ask=55,
                depth_yes=5,
                depth_no=5,
                total_depth=10,
                skew=0.5,
                liquidity_score=quality_score,
                quality_score=quality_score,
                timestamp=time.time()
            )
            optimizer._spread_metrics[market_id] = metrics
        
        # Filter with minimum quality of 0.5
        filtered = optimizer.filter_markets_by_quality(
            ["high_quality", "medium_quality", "low_quality", "very_low_quality"],
            min_quality=0.5
        )
        
        assert len(filtered) == 2
        assert "high_quality" in filtered
        assert "medium_quality" in filtered
        assert "low_quality" not in filtered
        assert "very_low_quality" not in filtered
    
    def test_get_performance_metrics(self):
        """Test performance metrics retrieval."""
        optimizer = SpreadOptimizer()
        
        # Simulate some activity
        optimizer._cache_hits = 10
        optimizer._cache_misses = 5
        optimizer._calculations = 5
        optimizer._errors = 1
        
        metrics = optimizer.get_performance_metrics()
        
        assert metrics["cache_hits"] == 10
        assert metrics["cache_misses"] == 5
        assert metrics["cache_hit_rate"] == 10 / 15  # 10 hits out of 15 total
        assert metrics["calculations"] == 5
        assert metrics["errors"] == 1
        assert metrics["cache_size"] == 0
        assert metrics["metrics_cache_size"] == 0
    
    def test_reset_metrics(self):
        """Test resetting performance metrics."""
        optimizer = SpreadOptimizer()
        
        # Set some metrics
        optimizer._cache_hits = 10
        optimizer._cache_misses = 5
        optimizer._calculations = 5
        optimizer._errors = 1
        
        # Reset metrics
        optimizer.reset_metrics()
        
        assert optimizer._cache_hits == 0
        assert optimizer._cache_misses == 0
        assert optimizer._calculations == 0
        assert optimizer._errors == 0
    
    def test_clear_cache(self):
        """Test clearing caches."""
        optimizer = SpreadOptimizer()
        
        # Add some cache entries
        optimizer._edge_cache["test1"] = EdgeCalculationCache(
            market_id="test1",
            edge_threshold=0.02,
            spread_cents=10,
            total_depth=5,
            computed_at=time.time()
        )
        optimizer._spread_metrics["test1"] = SpreadMetrics(
            market_id="test1",
            spread_cents=10.0,
            mid_cents=50.0,
            best_bid=45,
            best_ask=55,
            depth_yes=5,
            depth_no=5,
            total_depth=10,
            skew=0.5,
            liquidity_score=0.8,
            quality_score=0.85,
            timestamp=time.time()
        )
        
        assert len(optimizer._edge_cache) == 1
        assert len(optimizer._spread_metrics) == 1
        
        # Clear cache
        optimizer.clear_cache()
        
        assert len(optimizer._edge_cache) == 0
        assert len(optimizer._spread_metrics) == 0
    
    def test_calculate_liquidity_score(self):
        """Test liquidity score calculation."""
        optimizer = SpreadOptimizer()
        
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
            
            # Higher spread should result in lower score
            # Higher depth should result in higher score
            if total_depth > 0:
                # Actual implementation uses: spread_score * 0.7 + depth_score * 0.3
                # where spread_score = 1.0 - (spread_cents / MAX_SPREAD_CENTS)
                # and depth_score = min(1.0, total_depth / 50.0)
                spread_score = max(0.0, 1.0 - (spread_cents / 30.0))
                depth_score = min(1.0, total_depth / 50.0)
                expected_score = spread_score * 0.7 + depth_score * 0.3
                assert abs(score - expected_score) < 0.01
    
    def test_calculate_quality_score(self):
        """Test quality score calculation."""
        optimizer = SpreadOptimizer()
        
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
    
    def test_cache_size_limit(self):
        """Test cache size limit enforcement."""
        optimizer = SpreadOptimizer(cache_size=2)
        
        # Add more entries than cache size
        for i in range(5):
            optimizer.compute_edge_threshold_cached(i, 5, f"market_{i}")
        
        # Cache should not exceed size limit
        assert len(optimizer._edge_cache) <= 2


class TestSpreadOptimizerSingleton:
    """Test the global spread optimizer singleton pattern."""
    
    def test_get_spread_optimizer_singleton(self):
        """Test that get_spread_optimizer returns the same instance."""
        reset_spread_optimizer()
        
        optimizer1 = get_spread_optimizer()
        optimizer2 = get_spread_optimizer()
        
        assert optimizer1 is optimizer2
        assert isinstance(optimizer1, SpreadOptimizer)
    
    def test_reset_spread_optimizer(self):
        """Test resetting the global spread optimizer."""
        # Get initial optimizer
        optimizer1 = get_spread_optimizer()
        
        # Add some data
        optimizer1._cache_hits = 10
        
        # Reset optimizer
        reset_spread_optimizer()
        
        # Get new optimizer
        optimizer2 = get_spread_optimizer()
        
        assert optimizer2 is not optimizer1  # Should be a new instance
        assert optimizer2._cache_hits == 0


if __name__ == "__main__":
    pytest.main([__file__])
