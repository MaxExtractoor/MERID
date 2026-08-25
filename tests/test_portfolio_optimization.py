"""Tests for portfolio-level optimization in global_slot_allocator."""

import pytest
from merid.risk.global_slot_allocator import (
    get_global_slot_allocator,
    AllocationRequest
)


class TestPortfolioOptimization:
    """Test portfolio-level allocation optimization."""
    
    def test_optimize_portfolio_allocation_empty(self):
        """Test optimization with no opportunities."""
        allocator = get_global_slot_allocator()
        allocator.reset_all()
        
        opportunities = []
        optimal = allocator.optimize_portfolio_allocation(opportunities)
        
        assert optimal == {}
    
    def test_optimize_portfolio_allocation_single(self):
        """Test optimization with single opportunity."""
        allocator = get_global_slot_allocator()
        allocator.reset_all()
        
        opportunities = [
            {
                "asset": "BTC",
                "entry_price_cents": 50,
                "edge_pct": 0.05,
                "confidence": 0.8
            }
        ]
        
        optimal = allocator.optimize_portfolio_allocation(opportunities)
        
        assert "BTC" in optimal
        # With full $1 available, should allocate up to entry price
        assert optimal["BTC"] <= 0.50  # Entry price in USD
    
    def test_optimize_portfolio_allocation_multiple(self):
        """Test optimization with multiple opportunities."""
        allocator = get_global_slot_allocator()
        allocator.reset_all()
        
        opportunities = [
            {
                "asset": "BTC",
                "entry_price_cents": 50,
                "edge_pct": 0.05,
                "confidence": 0.8
            },
            {
                "asset": "ETH",
                "entry_price_cents": 30,
                "edge_pct": 0.04,
                "confidence": 0.7
            },
            {
                "asset": "DOGE",
                "entry_price_cents": 20,
                "edge_pct": 0.03,
                "confidence": 0.6
            }
        ]
        
        optimal = allocator.optimize_portfolio_allocation(opportunities)
        
        # Should allocate to all assets
        assert len(optimal) == 3
        assert "BTC" in optimal
        assert "ETH" in optimal
        assert "DOGE" in optimal
        
        # Each allocation should be <= entry price
        assert optimal["BTC"] <= 0.50
        assert optimal["ETH"] <= 0.30
        assert optimal["DOGE"] <= 0.20
        
        # Total should not exceed available capital ($1.00)
        total = sum(optimal.values())
        assert total <= 1.00
    
    def test_optimize_portfolio_with_existing_positions(self):
        """Test optimization with existing positions consuming capital."""
        allocator = get_global_slot_allocator()
        allocator.reset_all()
        
        # Allocate a position first
        req = AllocationRequest("BTC_15M", "BTC", "KXBTC15M-1", 40, 2.0, 5, 0.5, False)
        allocated, _, slot_id = allocator.request_allocation(req)
        assert allocated
        
        # Now optimize with remaining capital
        opportunities = [
            {
                "asset": "ETH",
                "entry_price_cents": 30,
                "edge_pct": 0.04,
                "confidence": 0.7
            },
            {
                "asset": "DOGE",
                "entry_price_cents": 20,
                "edge_pct": 0.03,
                "confidence": 0.6
            }
        ]
        
        optimal = allocator.optimize_portfolio_allocation(opportunities)
        
        # Should allocate based on remaining capital ($0.60)
        total = sum(optimal.values())
        assert total <= 0.60  # Available after BTC position
    
    def test_suggest_allocations_empty(self):
        """Test allocation suggestions with no opportunities."""
        allocator = get_global_slot_allocator()
        allocator.reset_all()
        
        opportunities = []
        suggestions = allocator.suggest_allocations(opportunities)
        
        assert suggestions == []
    
    def test_suggest_allocations_priority_sorting(self):
        """Test that suggestions are sorted by priority."""
        allocator = get_global_slot_allocator()
        allocator.reset_all()
        
        opportunities = [
            {
                "asset": "BTC",
                "entry_price_cents": 50,
                "edge_pct": 0.05,
                "confidence": 0.8  # Priority: 0.04
            },
            {
                "asset": "ETH",
                "entry_price_cents": 30,
                "edge_pct": 0.06,
                "confidence": 0.9  # Priority: 0.054 (highest)
            },
            {
                "asset": "DOGE",
                "entry_price_cents": 20,
                "edge_pct": 0.03,
                "confidence": 0.5  # Priority: 0.015 (lowest)
            }
        ]
        
        suggestions = allocator.suggest_allocations(opportunities)
        
        # Should return suggestions for assets that meet the threshold
        # DOGE may be filtered out if its suggested exposure is too low
        assert len(suggestions) >= 2  # At least BTC and ETH
        
        # First should be ETH (highest priority)
        assert suggestions[0][0] == "ETH"
    
    def test_suggest_allocations_reason_format(self):
        """Test that suggestion reasons are properly formatted."""
        allocator = get_global_slot_allocator()
        allocator.reset_all()
        
        opportunities = [
            {
                "asset": "BTC",
                "entry_price_cents": 50,
                "edge_pct": 0.05,
                "confidence": 0.8
            }
        ]
        
        suggestions = allocator.suggest_allocations(opportunities)
        
        assert len(suggestions) == 1
        asset, exposure, reason = suggestions[0]
        
        assert asset == "BTC"
        assert "edge=" in reason
        assert "conf=" in reason
    
    def test_optimize_with_custom_correlation_matrix(self):
        """Test optimization with custom correlation matrix."""
        allocator = get_global_slot_allocator()
        allocator.reset_all()
        
        opportunities = [
            {
                "asset": "BTC",
                "entry_price_cents": 50,
                "edge_pct": 0.05,
                "confidence": 0.8
            },
            {
                "asset": "ETH",
                "entry_price_cents": 30,
                "edge_pct": 0.04,
                "confidence": 0.7
            }
        ]
        
        # Custom correlation matrix (high correlation)
        custom_corr = {
            "BTC": {"BTC": 1.0, "ETH": 0.9},
            "ETH": {"BTC": 0.9, "ETH": 1.0}
        }
        
        optimal = allocator.optimize_portfolio_allocation(opportunities, custom_corr)
        
        # Should still allocate to both
        assert len(optimal) == 2
        assert "BTC" in optimal
        assert "ETH" in optimal


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x", "-s"])
