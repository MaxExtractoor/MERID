"""
Unit tests for coarse filter module.

Tests hierarchical sequential gates for universe reduction.
"""

import pytest
from merid.event_venues.kalshi.coarse_filter import (
    CoarseFilter,
    MarketCandidate,
    reset_coarse_filter
)
from merid.event_venues.kalshi.dynamic_thresholds import reset_dynamic_threshold_manager
from merid.event_venues.kalshi.regime_detector import reset_regime_detector


class TestCoarseFilter:
    """Test suite for CoarseFilter."""
    
    def setup_method(self):
        """Reset singletons before each test."""
        reset_regime_detector()
        reset_dynamic_threshold_manager()
        reset_coarse_filter()
        self.filter = CoarseFilter()
    
    def test_initialization(self):
        """Test filter initialization."""
        assert self.filter is not None
        assert self.filter.threshold_manager is not None
        assert len(self.filter.gates) == 6  # 6 gates
    
    def test_tau_gate(self):
        """Test time to expiry gate."""
        # Valid candidate (within tau range)
        candidate = MarketCandidate(
            ticker="BTC-15m-UP",
            price_cents=30,
            spread_cents=5,
            volume_24h=1000,
            depth_bid=100,
            depth_ask=100,
            time_to_expiry_minutes=10,
            asset="BTC"
        )
        
        assert self.filter._tau_gate(candidate) is True
        
        # Invalid candidate (too close to expiry)
        candidate.time_to_expiry_minutes = 2
        assert self.filter._tau_gate(candidate) is False
        
        # Invalid candidate (too far from expiry)
        candidate.time_to_expiry_minutes = 2000
        assert self.filter._tau_gate(candidate) is False
    
    def test_asset_whitelist_gate(self):
        """Test asset whitelist gate."""
        # Valid candidate (BTC is in whitelist)
        candidate = MarketCandidate(
            ticker="BTC-15m-UP",
            price_cents=30,
            spread_cents=5,
            volume_24h=1000,
            depth_bid=100,
            depth_ask=100,
            time_to_expiry_minutes=10,
            asset="BTC"
        )
        
        assert self.filter._asset_whitelist_gate(candidate) is True
        
        # Invalid candidate (XYZ not in whitelist)
        candidate.asset = "XYZ"
        assert self.filter._asset_whitelist_gate(candidate) is False
    
    def test_price_range_gate(self):
        """Test dynamic price range gate."""
        # Valid candidate (within canonical range 10-75c)
        candidate = MarketCandidate(
            ticker="BTC-15m-UP",
            price_cents=30,
            spread_cents=5,
            volume_24h=1000,
            depth_bid=100,
            depth_ask=100,
            time_to_expiry_minutes=10,
            asset="BTC"
        )
        
        assert self.filter._price_range_gate(candidate) is True
        
        # Invalid candidate (below range)
        candidate.price_cents = 5
        assert self.filter._price_range_gate(candidate) is False
        
        # Invalid candidate (above range)
        candidate.price_cents = 80
        assert self.filter._price_range_gate(candidate) is False
    
    def test_spread_gate(self):
        """Test dynamic spread gate."""
        # Valid candidate (spread within threshold)
        candidate = MarketCandidate(
            ticker="BTC-15m-UP",
            price_cents=30,
            spread_cents=5,
            volume_24h=1000,
            depth_bid=100,
            depth_ask=100,
            time_to_expiry_minutes=10,
            asset="BTC"
        )
        
        assert self.filter._spread_gate(candidate) is True
        
        # Invalid candidate (spread too wide)
        candidate.spread_cents = 50
        assert self.filter._spread_gate(candidate) is False
    
    def test_volume_depth_gate(self):
        """Test volume and depth gate."""
        # Valid candidate (sufficient volume and depth)
        candidate = MarketCandidate(
            ticker="BTC-15m-UP",
            price_cents=30,
            spread_cents=5,
            volume_24h=1000,
            depth_bid=100,
            depth_ask=100,
            time_to_expiry_minutes=10,
            asset="BTC"
        )
        
        assert self.filter._volume_depth_gate(candidate) is True
        
        # Invalid candidate (insufficient volume)
        candidate.volume_24h = 100
        assert self.filter._volume_depth_gate(candidate) is False
        
        # Invalid candidate (insufficient bid depth)
        candidate.volume_24h = 1000
        candidate.depth_bid = 50
        assert self.filter._volume_depth_gate(candidate) is False
        
        # Invalid candidate (insufficient ask depth)
        candidate.depth_bid = 100
        candidate.depth_ask = 50
        assert self.filter._volume_depth_gate(candidate) is False
    
    def test_edge_gate(self):
        """Test edge gate (deferred to agent grid)."""
        candidate = MarketCandidate(
            ticker="BTC-15m-UP",
            price_cents=30,
            spread_cents=5,
            volume_24h=1000,
            depth_bid=100,
            depth_ask=100,
            time_to_expiry_minutes=10,
            asset="BTC"
        )
        
        # Edge gate always returns True (deferred evaluation)
        assert self.filter._edge_gate(candidate) is True
    
    def test_filter_all_gates_pass(self):
        """Test filtering when all gates pass."""
        candidates = [
            MarketCandidate(
                ticker="BTC-15m-UP",
                price_cents=30,
                spread_cents=5,
                volume_24h=1000,
                depth_bid=100,
                depth_ask=100,
                time_to_expiry_minutes=10,
                asset="BTC"
            ),
            MarketCandidate(
                ticker="ETH-15m-UP",
                price_cents=25,
                spread_cents=4,
                volume_24h=800,
                depth_bid=100,
                depth_ask=100,
                time_to_expiry_minutes=8,
                asset="ETH"
            )
        ]
        
        filtered = self.filter.filter(candidates)
        
        assert len(filtered) == 2
    
    def test_filter_tau_gate_rejects(self):
        """Test filtering when tau gate rejects."""
        candidates = [
            MarketCandidate(
                ticker="BTC-15m-UP",
                price_cents=30,
                spread_cents=5,
                volume_24h=1000,
                depth_bid=100,
                depth_ask=100,
                time_to_expiry_minutes=2,  # Too close to expiry
                asset="BTC"
            ),
            MarketCandidate(
                ticker="ETH-15m-UP",
                price_cents=25,
                spread_cents=4,
                volume_24h=800,
                depth_bid=100,
                depth_ask=100,
                time_to_expiry_minutes=8,
                asset="ETH"
            )
        ]
        
        filtered = self.filter.filter(candidates)
        
        assert len(filtered) == 1
        assert filtered[0].ticker == "ETH-15m-UP"
    
    def test_filter_asset_whitelist_rejects(self):
        """Test filtering when asset whitelist rejects."""
        candidates = [
            MarketCandidate(
                ticker="BTC-15m-UP",
                price_cents=30,
                spread_cents=5,
                volume_24h=1000,
                depth_bid=100,
                depth_ask=100,
                time_to_expiry_minutes=10,
                asset="BTC"
            ),
            MarketCandidate(
                ticker="XYZ-15m-UP",
                price_cents=25,
                spread_cents=4,
                volume_24h=800,
                depth_bid=100,
                depth_ask=100,
                time_to_expiry_minutes=8,
                asset="XYZ"  # Not in whitelist
            )
        ]
        
        filtered = self.filter.filter(candidates)
        
        assert len(filtered) == 1
        assert filtered[0].ticker == "BTC-15m-UP"
    
    def test_filter_price_range_rejects(self):
        """Test filtering when price range gate rejects."""
        candidates = [
            MarketCandidate(
                ticker="BTC-15m-UP",
                price_cents=30,
                spread_cents=5,
                volume_24h=1000,
                depth_bid=100,
                depth_ask=100,
                time_to_expiry_minutes=10,
                asset="BTC"
            ),
            MarketCandidate(
                ticker="ETH-15m-UP",
                price_cents=5,  # Below range
                spread_cents=4,
                volume_24h=800,
                depth_bid=100,
                depth_ask=100,
                time_to_expiry_minutes=8,
                asset="ETH"
            )
        ]
        
        filtered = self.filter.filter(candidates)
        
        assert len(filtered) == 1
        assert filtered[0].ticker == "BTC-15m-UP"
    
    def test_filter_spread_rejects(self):
        """Test filtering when spread gate rejects."""
        candidates = [
            MarketCandidate(
                ticker="BTC-15m-UP",
                price_cents=30,
                spread_cents=5,
                volume_24h=1000,
                depth_bid=100,
                depth_ask=100,
                time_to_expiry_minutes=10,
                asset="BTC"
            ),
            MarketCandidate(
                ticker="ETH-15m-UP",
                price_cents=25,
                spread_cents=50,  # Too wide
                volume_24h=800,
                depth_bid=100,
                depth_ask=100,
                time_to_expiry_minutes=8,
                asset="ETH"
            )
        ]
        
        filtered = self.filter.filter(candidates)
        
        assert len(filtered) == 1
        assert filtered[0].ticker == "BTC-15m-UP"
    
    def test_filter_volume_depth_rejects(self):
        """Test filtering when volume/depth gate rejects."""
        candidates = [
            MarketCandidate(
                ticker="BTC-15m-UP",
                price_cents=30,
                spread_cents=5,
                volume_24h=1000,
                depth_bid=100,
                depth_ask=100,
                time_to_expiry_minutes=10,
                asset="BTC"
            ),
            MarketCandidate(
                ticker="ETH-15m-UP",
                price_cents=25,
                spread_cents=4,
                volume_24h=100,  # Insufficient volume
                depth_bid=100,
                depth_ask=100,
                time_to_expiry_minutes=8,
                asset="ETH"
            )
        ]
        
        filtered = self.filter.filter(candidates)
        
        assert len(filtered) == 1
        assert filtered[0].ticker == "BTC-15m-UP"
    
    def test_get_gate_stats(self):
        """Test getting gate statistics."""
        candidates = [
            MarketCandidate(
                ticker="BTC-15m-UP",
                price_cents=30,
                spread_cents=5,
                volume_24h=1000,
                depth_bid=100,
                depth_ask=100,
                time_to_expiry_minutes=10,
                asset="BTC"
            ),
            MarketCandidate(
                ticker="ETH-15m-UP",
                price_cents=5,  # Will fail price range gate
                spread_cents=4,
                volume_24h=800,
                depth_bid=100,
                depth_ask=100,
                time_to_expiry_minutes=8,
                asset="ETH"
            )
        ]
        
        stats = self.filter.get_gate_stats(candidates)
        
        # Gate names are method names with "_gate" suffix removed
        # Method names: _tau_gate, _asset_whitelist_gate, _price_range_gate, etc.
        # After removing "_gate": _tau, _asset_whitelist, _price_range, etc.
        assert "_tau" in stats
        assert "_asset_whitelist" in stats
        assert "_price_range" in stats
        assert "_spread" in stats
        assert "_volume_depth" in stats
        assert "_edge" in stats
        
        # Check that price_range gate filtered one candidate
        assert stats["_price_range"]["before"] == 2
        assert stats["_price_range"]["after"] == 1
        assert stats["_price_range"]["filtered"] == 1
    
    def test_market_candidate_to_dict(self):
        """Test converting MarketCandidate to dictionary."""
        candidate = MarketCandidate(
            ticker="BTC-15m-UP",
            price_cents=30,
            spread_cents=5,
            volume_24h=1000,
            depth_bid=100,
            depth_ask=100,
            time_to_expiry_minutes=10,
            asset="BTC"
        )
        
        candidate_dict = candidate.to_dict()
        
        assert candidate_dict["ticker"] == "BTC-15m-UP"
        assert candidate_dict["price_cents"] == 30
        assert candidate_dict["spread_cents"] == 5
        assert candidate_dict["volume_24h"] == 1000
        assert candidate_dict["depth_bid"] == 100
        assert candidate_dict["depth_ask"] == 100
        assert candidate_dict["time_to_expiry_minutes"] == 10
        assert candidate_dict["asset"] == "BTC"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
