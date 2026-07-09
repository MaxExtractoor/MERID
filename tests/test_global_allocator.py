"""
Tests for global allocator - edge-based allocation under venue cap
"""

import pytest
from merid.risk.profiles.global_allocator import GlobalAllocator, OrderCandidate


class TestGlobalAllocator:
    """Test suite for GlobalAllocator functionality."""
    
    def test_basic_allocation(self):
        """Test basic edge-based allocation under venue cap."""
        allocator = GlobalAllocator(venue_cap_usd=1.00)
        
        candidates = [
            OrderCandidate(
                asset="BTC",
                ticker="KXBTC15M-TEST",
                side="yes",
                action="buy",
                price_cents=40,
                count=1,
                edge_pct=18.0,
                confidence=0.8,
                model_prob=0.6,
                agent_name="BTC_15M"
            ),
            OrderCandidate(
                asset="ETH",
                ticker="KXETH15M-TEST",
                side="yes",
                action="buy",
                price_cents=30,
                count=1,
                edge_pct=15.0,
                confidence=0.7,
                model_prob=0.55,
                agent_name="ETH_15M"
            ),
            OrderCandidate(
                asset="SOL",
                ticker="KXSOL15M-TEST",
                side="yes",
                action="buy",
                price_cents=20,
                count=1,
                edge_pct=11.0,
                confidence=0.6,
                model_prob=0.5,
                agent_name="SOL_15M"
            ),
        ]
        
        chosen = allocator.allocate(candidates)
        
        # All three should fit under $1 cap ($0.40 + $0.30 + $0.20 = $0.90)
        assert len(chosen) == 3
        assert sum(c.notional_usd for c in chosen) <= 1.00
        
        # Should be sorted by edge (BTC first, then ETH, then SOL)
        assert chosen[0].asset == "BTC"
        assert chosen[1].asset == "ETH"
        assert chosen[2].asset == "SOL"
    
    def test_venue_cap_enforcement(self):
        """Test that venue cap is enforced."""
        allocator = GlobalAllocator(venue_cap_usd=1.00)
        
        candidates = [
            OrderCandidate(
                asset="BTC",
                ticker="KXBTC15M-TEST",
                side="yes",
                action="buy",
                price_cents=50,
                count=1,
                edge_pct=20.0,
                confidence=0.9,
                model_prob=0.7,
                agent_name="BTC_15M"
            ),
            OrderCandidate(
                asset="ETH",
                ticker="KXETH15M-TEST",
                side="yes",
                action="buy",
                price_cents=50,
                count=1,
                edge_pct=18.0,
                confidence=0.8,
                model_prob=0.6,
                agent_name="ETH_15M"
            ),
            OrderCandidate(
                asset="SOL",
                ticker="KXSOL15M-TEST",
                side="yes",
                action="buy",
                price_cents=50,
                count=1,
                edge_pct=15.0,
                confidence=0.7,
                model_prob=0.5,
                agent_name="SOL_15M"
            ),
        ]
        
        chosen = allocator.allocate(candidates)
        
        # Only first two should fit ($0.50 + $0.50 = $1.00)
        assert len(chosen) == 2
        assert sum(c.notional_usd for c in chosen) <= 1.00
        assert chosen[0].asset == "BTC"
        assert chosen[1].asset == "ETH"
    
    def test_min_edge_filter(self):
        """Test that candidates below minimum edge are filtered out."""
        allocator = GlobalAllocator(venue_cap_usd=1.00, min_edge_pct=5.0)
        
        candidates = [
            OrderCandidate(
                asset="BTC",
                ticker="KXBTC15M-TEST",
                side="yes",
                action="buy",
                price_cents=40,
                count=1,
                edge_pct=10.0,
                confidence=0.8,
                model_prob=0.6,
                agent_name="BTC_15M"
            ),
            OrderCandidate(
                asset="ETH",
                ticker="KXETH15M-TEST",
                side="yes",
                action="buy",
                price_cents=30,
                count=1,
                edge_pct=3.0,  # Below min edge
                confidence=0.7,
                model_prob=0.55,
                agent_name="ETH_15M"
            ),
        ]
        
        chosen = allocator.allocate(candidates)
        
        # Only BTC should be chosen (ETH filtered out)
        assert len(chosen) == 1
        assert chosen[0].asset == "BTC"
    
    def test_per_asset_concentration_limit(self):
        """Test that per-asset concentration limit is enforced."""
        allocator = GlobalAllocator(venue_cap_usd=1.00, max_single_asset_fraction=0.70)
        
        candidates = [
            OrderCandidate(
                asset="BTC",
                ticker="KXBTC15M-TEST",
                side="yes",
                action="buy",
                price_cents=80,
                count=1,
                edge_pct=25.0,
                confidence=0.9,
                model_prob=0.7,
                agent_name="BTC_15M"
            ),
            OrderCandidate(
                asset="ETH",
                ticker="KXETH15M-TEST",
                side="yes",
                action="buy",
                price_cents=20,
                count=1,
                edge_pct=15.0,
                confidence=0.7,
                model_prob=0.5,
                agent_name="ETH_15M"
            ),
        ]
        
        chosen = allocator.allocate(candidates)
        
        # BTC at $0.80 exceeds 70% cap ($0.70), so it should be skipped
        # ETH at $0.20 should be chosen
        assert len(chosen) == 1
        assert chosen[0].asset == "ETH"
    
    def test_allocation_summary(self):
        """Test allocation summary generation."""
        allocator = GlobalAllocator(venue_cap_usd=1.00)
        
        candidates = [
            OrderCandidate(
                asset="BTC",
                ticker="KXBTC15M-TEST",
                side="yes",
                action="buy",
                price_cents=40,
                count=1,
                edge_pct=18.0,
                confidence=0.8,
                model_prob=0.6,
                agent_name="BTC_15M"
            ),
            OrderCandidate(
                asset="ETH",
                ticker="KXETH15M-TEST",
                side="yes",
                action="buy",
                price_cents=30,
                count=1,
                edge_pct=15.0,
                confidence=0.7,
                model_prob=0.55,
                agent_name="ETH_15M"
            ),
        ]
        
        chosen = allocator.allocate(candidates)
        summary = allocator.get_allocation_summary(chosen)
        
        assert summary['total_orders'] == 2
        assert summary['total_notional'] == 0.70
        assert summary['utilization_pct'] == 70.0
        assert summary['avg_edge'] == 16.5
        assert 'BTC' in summary['asset_breakdown']
        assert 'ETH' in summary['asset_breakdown']
    
    def test_empty_candidates(self):
        """Test allocation with no candidates."""
        allocator = GlobalAllocator(venue_cap_usd=1.00)
        
        chosen = allocator.allocate([])
        summary = allocator.get_allocation_summary(chosen)
        
        assert len(chosen) == 0
        assert summary['total_orders'] == 0
        assert summary['total_notional'] == 0.0
    
    def test_all_below_min_edge(self):
        """Test when all candidates are below minimum edge."""
        allocator = GlobalAllocator(venue_cap_usd=1.00, min_edge_pct=10.0)
        
        candidates = [
            OrderCandidate(
                asset="BTC",
                ticker="KXBTC15M-TEST",
                side="yes",
                action="buy",
                price_cents=40,
                count=1,
                edge_pct=5.0,
                confidence=0.8,
                model_prob=0.6,
                agent_name="BTC_15M"
            ),
            OrderCandidate(
                asset="ETH",
                ticker="KXETH15M-TEST",
                side="yes",
                action="buy",
                price_cents=30,
                count=1,
                edge_pct=3.0,
                confidence=0.7,
                model_prob=0.55,
                agent_name="ETH_15M"
            ),
        ]
        
        chosen = allocator.allocate(candidates)
        
        assert len(chosen) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
