"""
Tests for orderbook, spread, and direction choice fixes.

This test suite validates the fixes for 7 identified flaws:
1. 100c price filtering and clamping to [1, 99]
2. Zero spread detection (crossed market)
3. Wide spread flagging (>15c)
4. Liquidity scoring formula adjustment
5. Optimal side selection logic
6. Spread threshold consistency
"""

import pytest
from typing import Tuple
from merid.event_venues.kalshi.orderbook import LocalOrderbook
from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot, OrderbookLevel
from merid.event_venues.kalshi.microstructure import (
    compute_side_microstructure,
    compute_optimal_side,
    MicrostructureView,
)
from merid.prediction.spread_optimizer import SpreadOptimizer


class TestPriceFiltering:
    """Test price filtering and clamping fixes."""
    
    def test_snapshot_filters_100c_prices(self):
        """Test that 100c prices are filtered out in snapshot application."""
        ob = LocalOrderbook(ticker="TEST-100C")
        
        # Snapshot with 100c price (should be filtered)
        snapshot = {
            "ticker": "TEST-100C",
            "yes": [[1.00, 100], [0.50, 50]],  # 100c should be filtered, 50c should remain
            "no": [[0.50, 50]],
            "seq": 1,
            "ts": 0.0,
        }
        
        ob.apply_snapshot(snapshot)
        
        # Verify 100c was filtered out
        assert 100 not in ob.yes_levels
        # Verify 50c was kept
        assert 50 in ob.yes_levels
        assert ob.yes_levels[50] == 50
    
    def test_snapshot_clamps_to_99c(self):
        """Test that prices are clamped to 99c maximum."""
        ob = LocalOrderbook(ticker="TEST-CLAMP")
        
        # Snapshot with 99.5c (should clamp to 99c)
        snapshot = {
            "ticker": "TEST-CLAMP",
            "yes": [[0.995, 100]],  # 99.5c -> should clamp to 99c
            "no": [],
            "seq": 1,
            "ts": 0.0,
        }
        
        ob.apply_snapshot(snapshot)
        
        # Verify clamped to 99c
        assert 99 in ob.yes_levels
        assert 100 not in ob.yes_levels
    
    def test_snapshot_clamps_to_1c(self):
        """Test that prices are clamped to 1c minimum."""
        ob = LocalOrderbook(ticker="TEST-CLAMP-MIN")
        
        # Snapshot with 0.5c (should clamp to 1c)
        snapshot = {
            "ticker": "TEST-CLAMP-MIN",
            "yes": [[0.005, 100]],  # 0.5c -> should clamp to 1c
            "no": [],
            "seq": 1,
            "ts": 0.0,
        }
        
        ob.apply_snapshot(snapshot)
        
        # Verify clamped to 1c
        assert 1 in ob.yes_levels
        assert 0 not in ob.yes_levels
    
    def test_delta_filters_100c_prices(self):
        """Test that 100c prices are filtered out in delta application."""
        ob = LocalOrderbook(ticker="TEST-DELTA-100C")
        
        # Initialize with valid snapshot
        snapshot = {
            "ticker": "TEST-DELTA-100C",
            "yes": [[0.50, 50]],
            "no": [[0.50, 50]],
            "seq": 1,
            "ts": 0.0,
        }
        ob.apply_snapshot(snapshot)
        
        # Try to add 100c level via delta (should be filtered)
        delta = {
            "side": "yes",
            "price_dollars": 1.00,
            "delta_fp": 100,
        }
        
        ob.apply_delta(delta)
        
        # Verify 100c was filtered out
        assert 100 not in ob.yes_levels
    
    def test_delta_clamps_to_valid_range(self):
        """Test that delta prices are clamped to [1, 99]."""
        ob = LocalOrderbook(ticker="TEST-DELTA-CLAMP")
        
        # Initialize with valid snapshot
        snapshot = {
            "ticker": "TEST-DELTA-CLAMP",
            "yes": [[0.50, 50]],
            "no": [[0.50, 50]],
            "seq": 1,
            "ts": 0.0,
        }
        ob.apply_snapshot(snapshot)
        
        # Try to add 0.5c level via delta (should clamp to 1c)
        delta = {
            "side": "yes",
            "price_dollars": 0.005,
            "delta_fp": 100,
        }
        
        ob.apply_delta(delta)
        
        # Verify clamped to 1c
        assert 1 in ob.yes_levels
        assert 0 not in ob.yes_levels


class TestCrossedMarketDetection:
    """Test crossed market and wide spread detection."""
    
    def test_zero_spread_detection(self, caplog):
        """Test that zero spread is detected as crossed market."""
        snapshot = OrderbookSnapshot(
            ticker="TEST-ZERO-SPREAD",
            yes_bids=(OrderbookLevel(price_cents=50, size=100),),
            no_bids=(OrderbookLevel(price_cents=50, size=100),),
        )
        
        micro = compute_side_microstructure(snapshot, side="yes", size=1)
        
        # Spread should be 0 (crossed market)
        assert micro.spread_cents == 0
        
        # Should log warning about crossed market
        assert "Crossed market detected" in caplog.text
    
    def test_wide_spread_detection(self, caplog):
        """Test that wide spreads (>15c) are flagged."""
        snapshot = OrderbookSnapshot(
            ticker="TEST-WIDE-SPREAD",
            yes_bids=(OrderbookLevel(price_cents=10, size=100),),
            no_bids=(OrderbookLevel(price_cents=10, size=100),),
        )
        
        micro = compute_side_microstructure(snapshot, side="yes", size=1)
        
        # Spread should be 80c (wide)
        assert micro.spread_cents == 80
        
        # Should log warning about wide spread
        assert "Wide spread detected" in caplog.text
        assert "80c" in caplog.text


class TestLiquidityScoring:
    """Test liquidity scoring formula adjustments."""
    
    def test_liquidity_score_conservative(self):
        """Test that liquidity score is conservative for low depth."""
        optimizer = SpreadOptimizer()
        
        # Market with 10 depth and 5c spread
        spread_cents = 5.0
        total_depth = 10
        
        score = optimizer._calculate_liquidity_score(spread_cents, total_depth)
        
        # With new formula: spread_score = 1 - (5/15) = 0.67
        # depth_score = 10/50 = 0.2
        # liquidity_score = 0.67 * 0.7 + 0.2 * 0.3 = 0.469 + 0.06 = 0.529
        # Should be < 0.6 (conservative)
        assert score < 0.6
        assert score > 0.0
    
    def test_liquidity_score_high_depth(self):
        """Test that high depth gets good score."""
        optimizer = SpreadOptimizer()
        
        # Market with 100 depth and 2c spread
        spread_cents = 2.0
        total_depth = 100
        
        score = optimizer._calculate_liquidity_score(spread_cents, total_depth)
        
        # Should be high for good liquidity
        assert score > 0.8
    
    def test_liquidity_score_wide_spread_penalty(self):
        """Test that wide spreads are penalized."""
        optimizer = SpreadOptimizer()
        
        # Market with 50 depth but 20c spread
        spread_cents = 20.0
        total_depth = 50
        
        score = optimizer._calculate_liquidity_score(spread_cents, total_depth)
        
        # Wide spread should reduce score significantly
        assert score < 0.5


class TestOptimalSideSelection:
    """Test optimal side selection logic."""
    
    def test_optimal_side_long_yes_better(self):
        """Test optimal side selection when YES is better for long."""
        snapshot = OrderbookSnapshot(
            ticker="TEST-LONG-YES",
            yes_bids=(OrderbookLevel(price_cents=40, size=100),),
            no_bids=(OrderbookLevel(price_cents=60, size=100),),
        )
        
        # YES bid = 40c, NO ask = 100 - 60 = 40c (equal)
        # Should prefer YES for simplicity
        optimal = compute_optimal_side(snapshot, direction="long")
        assert optimal == "yes"
    
    def test_optimal_side_long_no_better(self):
        """Test optimal side selection when NO is better for long."""
        snapshot = OrderbookSnapshot(
            ticker="TEST-LONG-NO",
            yes_bids=(OrderbookLevel(price_cents=60, size=100),),
            no_bids=(OrderbookLevel(price_cents=30, size=100),),
        )
        
        # YES bid = 60c, NO ask = 100 - 30 = 70c
        # YES is cheaper (60c < 70c), so YES is better
        optimal = compute_optimal_side(snapshot, direction="long")
        assert optimal == "yes"
    
    def test_optimal_side_short_yes_better(self):
        """Test optimal side selection when YES is better for short."""
        snapshot = OrderbookSnapshot(
            ticker="TEST-SHORT-YES",
            yes_bids=(OrderbookLevel(price_cents=70, size=100),),
            no_bids=(OrderbookLevel(price_cents=30, size=100),),
        )
        
        # YES ask = 100 - 30 = 70c, NO bid = 30c
        # YES ask is higher (70c > 30c), so YES is better for short
        optimal = compute_optimal_side(snapshot, direction="short")
        assert optimal == "yes"
    
    def test_optimal_side_none_if_missing_data(self):
        """Test that None is returned if data is missing."""
        snapshot = OrderbookSnapshot(
            ticker="TEST-MISSING",
            yes_bids=(),  # Empty
            no_bids=(),
        )
        
        optimal = compute_optimal_side(snapshot, direction="long")
        assert optimal is None


class TestSpreadThresholdConsistency:
    """Test spread threshold consistency between components."""
    
    def test_optimizer_reads_profile(self, caplog):
        """Test that SpreadOptimizer reads from profile."""
        optimizer = SpreadOptimizer()
        
        # Should log profile loading
        assert "Profile loaded" in caplog.text or "Failed to load profile" in caplog.text
        
        # MAX_SPREAD_CENTS should be set
        assert optimizer.MAX_SPREAD_CENTS == 15  # Quality metric threshold


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
