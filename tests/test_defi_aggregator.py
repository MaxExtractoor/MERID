"""
Tests for DeFi aggregator route optimization and yield finding.
"""

import pytest
from data.defi_aggregator import DeFiAggregator, DeFiProtocolSnapshot, RouteOption


class TestDeFiAggregator:
    """Test DeFi aggregator functionality."""
    
    def test_record_snapshot(self):
        """Test recording protocol snapshots."""
        aggregator = DeFiAggregator()
        
        snapshot = aggregator.record_snapshot(
            chain="ethereum",
            protocol="aave",
            tvl_usd=5_000_000_000,
            apy=3.5,
            risk_score=0.2
        )
        
        assert snapshot.chain == "ethereum"
        assert snapshot.protocol == "aave"
        assert snapshot.tvl_usd == 5_000_000_000
        assert snapshot.apy == 3.5
        assert snapshot.risk_score == 0.2
    
    def test_find_best_yield(self):
        """Test finding best yield opportunities."""
        aggregator = DeFiAggregator()
        
        aggregator.record_snapshot("ethereum", "aave", 5_000_000_000, 3.5, 0.2)
        aggregator.record_snapshot("ethereum", "compound", 3_000_000_000, 4.2, 0.3)
        aggregator.record_snapshot("arbitrum", "aave", 500_000_000, 5.0, 0.25)
        aggregator.record_snapshot("polygon", "curve", 1_000_000_000, 8.0, 0.6)
        
        routes = aggregator.find_best_yield(
            asset="USDC",
            amount_usd=10_000,
            max_risk_score=0.5,
            min_tvl_usd=1_000_000
        )
        
        assert len(routes) > 0
        assert all(isinstance(r, RouteOption) for r in routes)
        assert all(r.risk_score <= 0.5 for r in routes)
        assert routes[0].net_output >= routes[-1].net_output
    
    def test_optimize_route(self):
        """Test route optimization for swaps."""
        aggregator = DeFiAggregator()
        
        aggregator.record_snapshot("ethereum", "uniswap", 2_000_000_000, 0, 0.1)
        aggregator.record_snapshot("arbitrum", "uniswap", 500_000_000, 0, 0.15)
        aggregator.record_snapshot("polygon", "quickswap", 300_000_000, 0, 0.2)
        
        routes = aggregator.optimize_route(
            from_asset="USDC",
            to_asset="ETH",
            amount=1000,
            max_hops=3
        )
        
        assert len(routes) > 0
        assert all(isinstance(r, RouteOption) for r in routes)
        assert routes[0].net_output >= routes[-1].net_output
    
    def test_compare_protocols(self):
        """Test protocol comparison."""
        aggregator = DeFiAggregator()
        
        aggregator.record_snapshot("ethereum", "aave", 5_000_000_000, 3.5, 0.2)
        aggregator.record_snapshot("ethereum", "compound", 3_000_000_000, 4.2, 0.3)
        
        comparison = aggregator.compare_protocols(
            asset="USDC",
            protocols=["aave", "compound"]
        )
        
        assert "aave" in comparison
        assert "compound" in comparison
        assert comparison["aave"].apy == 3.5
        assert comparison["compound"].apy == 4.2
    
    def test_get_protocol_stats(self):
        """Test protocol statistics aggregation."""
        aggregator = DeFiAggregator()
        
        aggregator.record_snapshot("ethereum", "aave", 5_000_000_000, 3.5, 0.2)
        aggregator.record_snapshot("arbitrum", "aave", 500_000_000, 5.0, 0.25)
        aggregator.record_snapshot("polygon", "aave", 300_000_000, 6.0, 0.3)
        
        stats = aggregator.get_protocol_stats("aave")
        
        assert stats["total_tvl"] == 5_800_000_000
        assert stats["avg_apy"] == pytest.approx((3.5 + 5.0 + 6.0) / 3, abs=0.01)
        assert stats["avg_risk"] == pytest.approx((0.2 + 0.25 + 0.3) / 3, abs=0.01)
        assert stats["chain_count"] == 3
    
    def test_estimate_gas_cost(self):
        """Test gas cost estimation."""
        aggregator = DeFiAggregator()
        
        assert aggregator._estimate_gas_cost("ethereum") == 50.0
        assert aggregator._estimate_gas_cost("arbitrum") == 2.0
        assert aggregator._estimate_gas_cost("polygon") == 0.5
        assert aggregator._estimate_gas_cost("unknown") == 5.0
    
    def test_estimate_slippage(self):
        """Test slippage estimation."""
        aggregator = DeFiAggregator()
        
        assert aggregator._estimate_slippage(100, 1_000_000) == 0.1
        assert aggregator._estimate_slippage(5_000, 1_000_000) == 0.5
        assert aggregator._estimate_slippage(30_000, 1_000_000) == 1.0
        assert aggregator._estimate_slippage(100_000, 1_000_000) >= 5.0
    
    def test_yield_filtering_by_risk(self):
        """Test yield filtering by risk score."""
        aggregator = DeFiAggregator()
        
        aggregator.record_snapshot("ethereum", "safe_protocol", 5_000_000_000, 3.0, 0.1)
        aggregator.record_snapshot("ethereum", "risky_protocol", 2_000_000_000, 15.0, 0.9)
        
        safe_routes = aggregator.find_best_yield(
            asset="USDC",
            amount_usd=10_000,
            max_risk_score=0.3,
            min_tvl_usd=1_000_000
        )
        
        assert all(r.risk_score <= 0.3 for r in safe_routes)
        assert not any(r.protocol == "risky_protocol" for r in safe_routes)
    
    def test_yield_filtering_by_tvl(self):
        """Test yield filtering by minimum TVL."""
        aggregator = DeFiAggregator()
        
        aggregator.record_snapshot("ethereum", "large_protocol", 5_000_000_000, 3.0, 0.2)
        aggregator.record_snapshot("ethereum", "small_protocol", 500_000, 10.0, 0.2)
        
        routes = aggregator.find_best_yield(
            asset="USDC",
            amount_usd=10_000,
            max_risk_score=0.5,
            min_tvl_usd=1_000_000
        )
        
        assert not any(r.protocol == "small_protocol" for r in routes)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
