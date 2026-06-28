"""
Unit tests for dynamic risk routing module.
"""

import pytest

from merid.prediction.dynamic_risk_routing import (
    DynamicRiskRouter,
    Opportunity,
    RiskAllocation,
)


class TestOpportunity:
    """Test Opportunity dataclass."""
    
    def test_opportunity_creation(self):
        """Test creating an Opportunity."""
        opp = Opportunity(
            asset="BTC",
            market_id="KXBTC15M-26APR141315-30",
            edge_r=1.5,
            marginal_risk_per_contract=10.0,
        )
        assert opp.asset == "BTC"
        assert opp.market_id == "KXBTC15M-26APR141315-30"
        assert opp.edge_r == 1.5
        assert opp.marginal_risk_per_contract == 10.0


class TestRiskAllocation:
    """Test RiskAllocation dataclass."""
    
    def test_risk_allocation_creation(self):
        """Test creating a RiskAllocation."""
        alloc = RiskAllocation(
            asset="BTC",
            market_id="KXBTC15M-26APR141315-30",
            contracts=5,
            risk_usd=50.0,
            edge_r=1.5,
            reason="Highest edge_R in ranked list",
        )
        assert alloc.asset == "BTC"
        assert alloc.market_id == "KXBTC15M-26APR141315-30"
        assert alloc.contracts == 5
        assert alloc.risk_usd == 50.0
        assert alloc.edge_r == 1.5
        assert alloc.reason == "Highest edge_R in ranked list"


class TestDynamicRiskRouter:
    """Test DynamicRiskRouter."""
    
    def test_initialization(self):
        """Test initializing DynamicRiskRouter."""
        router = DynamicRiskRouter(total_risk_budget_usd=300.0)
        assert router.total_risk_budget_usd == 300.0
        assert len(router.per_asset_caps) > 0
        assert len(router.correlation_groups) > 0
    
    def test_check_per_asset_cap(self):
        """Test checking per-asset cap."""
        router = DynamicRiskRouter(total_risk_budget_usd=300.0)
        
        # Within cap
        assert router.check_per_asset_cap("BTC", 40.0, 10.0) is True
        
        # At cap
        assert router.check_per_asset_cap("BTC", 50.0, 0.0) is True
        
        # Over cap
        assert router.check_per_asset_cap("BTC", 50.0, 1.0) is False
    
    def test_check_group_cap(self):
        """Test checking correlation group cap."""
        router = DynamicRiskRouter(total_risk_budget_usd=300.0)
        
        # Within group cap
        group_utilizations = {"crypto": 50.0}
        assert router.check_group_cap("BTC", group_utilizations, 10.0) is True
        
        # At group cap
        group_utilizations = {"crypto": 100.0}
        assert router.check_group_cap("BTC", group_utilizations, 0.0) is True
        
        # Over group cap
        group_utilizations = {"crypto": 100.0}
        assert router.check_group_cap("BTC", group_utilizations, 1.0) is False
    
    def test_rank_opportunities(self):
        """Test ranking opportunities by edge_R."""
        router = DynamicRiskRouter(total_risk_budget_usd=300.0)
        
        opportunities = [
            Opportunity("BTC", "market1", 1.0, 10.0),
            Opportunity("ETH", "market2", 2.0, 10.0),
            Opportunity("SOL", "market3", 1.5, 10.0),
        ]
        
        ranked = router.rank_opportunities(opportunities)
        
        assert len(ranked) == 3
        assert ranked[0].asset == "ETH"  # Highest edge_R
        assert ranked[1].asset == "SOL"
        assert ranked[2].asset == "BTC"
    
    def test_allocate_risk(self):
        """Test allocating risk to opportunities."""
        router = DynamicRiskRouter(total_risk_budget_usd=300.0)
        
        opportunities = [
            Opportunity("BTC", "market1", 1.5, 10.0),
            Opportunity("ETH", "market2", 2.0, 10.0),
            Opportunity("SOL", "market3", 1.0, 10.0),
        ]
        
        current_exposures = {"BTC": 0.0, "ETH": 0.0, "SOL": 0.0}
        group_utilizations = {"crypto": 0.0}
        remaining_budget = 300.0
        
        allocations = router.allocate_risk(
            opportunities, current_exposures, group_utilizations, remaining_budget
        )
        
        assert len(allocations) == 3
        # Should allocate to all opportunities (within caps)
        total_allocated = sum(a.risk_usd for a in allocations)
        assert total_allocated <= 300.0
    
    def test_allocate_risk_budget_exhausted(self):
        """Test allocation when budget is exhausted."""
        router = DynamicRiskRouter(total_risk_budget_usd=30.0)
        
        opportunities = [
            Opportunity("BTC", "market1", 1.5, 10.0),
            Opportunity("ETH", "market2", 2.0, 10.0),
            Opportunity("SOL", "market3", 1.0, 10.0),
        ]
        
        current_exposures = {"BTC": 0.0, "ETH": 0.0, "SOL": 0.0}
        group_utilizations = {"crypto": 0.0}
        remaining_budget = 30.0  # Only enough for 3 contracts
        
        allocations = router.allocate_risk(
            opportunities, current_exposures, group_utilizations, remaining_budget
        )
        
        # Should allocate to 3 opportunities (10 each)
        assert len(allocations) == 3
        total_allocated = sum(a.risk_usd for a in allocations)
        assert total_allocated == 30.0
    
    def test_allocate_risk_per_asset_cap(self):
        """Test allocation with per-asset cap."""
        router = DynamicRiskRouter(total_risk_budget_usd=300.0)
        
        opportunities = [
            Opportunity("BTC", "market1", 1.5, 10.0),
            Opportunity("BTC", "market2", 2.0, 10.0),
            Opportunity("BTC", "market3", 1.0, 10.0),
        ]
        
        current_exposures = {"BTC": 45.0}  # Near cap (50)
        group_utilizations = {"crypto": 45.0}
        remaining_budget = 300.0
        
        allocations = router.allocate_risk(
            opportunities, current_exposures, group_utilizations, remaining_budget
        )
        
        # Should allocate to 1 opportunity (to reach cap)
        assert len(allocations) <= 1
    
    def test_allocate_risk_group_cap(self):
        """Test allocation with group cap."""
        router = DynamicRiskRouter(total_risk_budget_usd=300.0)
        
        opportunities = [
            Opportunity("BTC", "market1", 1.5, 10.0),
            Opportunity("ETH", "market2", 2.0, 10.0),
            Opportunity("SOL", "market3", 1.0, 10.0),
        ]
        
        current_exposures = {"BTC": 0.0, "ETH": 0.0, "SOL": 0.0}
        group_utilizations = {"crypto": 95.0}  # Near group cap (100)
        remaining_budget = 300.0
        
        allocations = router.allocate_risk(
            opportunities, current_exposures, group_utilizations, remaining_budget
        )
        
        # Should allocate to 1 opportunity (to reach group cap)
        assert len(allocations) <= 1
    
    def test_log_routing_summary(self):
        """Test logging routing summary."""
        router = DynamicRiskRouter(total_risk_budget_usd=300.0)
        
        allocations = [
            RiskAllocation("BTC", "market1", 5, 50.0, 1.5, "reason1"),
            RiskAllocation("ETH", "market2", 3, 30.0, 2.0, "reason2"),
        ]
        
        remaining_budget = 220.0
        
        # Should not raise exception
        router.log_routing_summary(allocations, remaining_budget)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
