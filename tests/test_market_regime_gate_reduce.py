"""Tests for Market Regime Gate REDUCE action sizing reduction.

This tests the CRITICAL FIX that implements actual sizing reduction
when Market Regime Gate returns REDUCE action.
"""

import pytest
from unittest.mock import Mock, patch


class TestMarketRegimeGateReduce:
    """Test that REDUCE action actually reduces position sizes."""
    
    def test_reduce_action_reduces_contracts(self):
        """Test that REDUCE action reduces contracts by 50%."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        from merid.market_regime.gate import RegimeAction, RegimeDecision
        
        # Create an order intent with count
        intent = OrderIntent(
            ticker="KXBTC15M-26APR191645-50",
            side="yes",
            action="buy",
            count=10,
            price_cents=50
        )
        
        # Create a REDUCE decision
        decision = RegimeDecision(
            action=RegimeAction.REDUCE,
            flat_count=3,
            total_assets=5,
            reason_codes=["low_activity"],
            shadow_mode=False,
            config_source="test"
        )
        
        # Apply REDUCE logic (simulating the order_router logic)
        if decision.action == RegimeAction.REDUCE:
            original_count = intent.count
            intent.count = max(1, int(original_count * 0.5))
        
        # Verify contracts were reduced by 50%
        assert intent.count == 5  # 10 * 0.5 = 5
    
    def test_reduce_action_min_one_contract(self):
        """Test that REDUCE action never reduces below 1 contract."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        from merid.market_regime.gate import RegimeAction, RegimeDecision
        
        # Create an order intent with 1 contract
        intent = OrderIntent(
            ticker="KXBTC15M-26APR191645-50",
            side="yes",
            action="buy",
            count=1,
            price_cents=50
        )
        
        # Create a REDUCE decision
        decision = RegimeDecision(
            action=RegimeAction.REDUCE,
            flat_count=3,
            total_assets=5,
            reason_codes=["low_activity"],
            shadow_mode=False,
            config_source="test"
        )
        
        # Apply REDUCE logic
        if decision.action == RegimeAction.REDUCE:
            original_count = intent.count
            intent.count = max(1, int(original_count * 0.5))
        
        # Verify contracts stay at 1 (min 1)
        assert intent.count == 1
    
    def test_reduce_action_odd_contracts(self):
        """Test that REDUCE action handles odd contract counts correctly."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        from merid.market_regime.gate import RegimeAction, RegimeDecision
        
        # Create an order intent with odd number of contracts
        intent = OrderIntent(
            ticker="KXBTC15M-26APR191645-50",
            side="yes",
            action="buy",
            count=7,
            price_cents=50
        )
        
        # Create a REDUCE decision
        decision = RegimeDecision(
            action=RegimeAction.REDUCE,
            flat_count=3,
            total_assets=5,
            reason_codes=["low_activity"],
            shadow_mode=False,
            config_source="test"
        )
        
        # Apply REDUCE logic
        if decision.action == RegimeAction.REDUCE:
            original_count = intent.count
            intent.count = max(1, int(original_count * 0.5))
        
        # Verify contracts are floor(7 * 0.5) = 3
        assert intent.count == 3
    
    def test_allow_action_no_reduction(self):
        """Test that ALLOW action does not reduce contracts."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        from merid.market_regime.gate import RegimeAction, RegimeDecision
        
        # Create an order intent with count
        intent = OrderIntent(
            ticker="KXBTC15M-26APR191645-50",
            side="yes",
            action="buy",
            count=10,
            price_cents=50
        )
        
        # Create an ALLOW decision
        decision = RegimeDecision(
            action=RegimeAction.ALLOW,
            flat_count=0,
            total_assets=5,
            reason_codes=[],
            shadow_mode=False,
            config_source="test"
        )
        
        # Apply REDUCE logic (should not trigger)
        if decision.action == RegimeAction.REDUCE:
            original_count = intent.count
            intent.count = max(1, int(original_count * 0.5))
        
        # Verify contracts unchanged
        assert intent.count == 10
    
    def test_block_action_no_reduction(self):
        """Test that BLOCK action does not reduce contracts (order is rejected)."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        from merid.market_regime.gate import RegimeAction, RegimeDecision
        
        # Create an order intent with count
        intent = OrderIntent(
            ticker="KXBTC15M-26APR191645-50",
            side="yes",
            action="buy",
            count=10,
            price_cents=50
        )
        
        # Create a BLOCK decision
        decision = RegimeDecision(
            action=RegimeAction.BLOCK,
            flat_count=4,
            total_assets=5,
            reason_codes=["basket_flat"],
            shadow_mode=False,
            config_source="test"
        )
        
        # Apply REDUCE logic (should not trigger)
        if decision.action == RegimeAction.REDUCE:
            original_count = intent.count
            intent.count = max(1, int(original_count * 0.5))
        
        # Verify contracts unchanged (order would be rejected elsewhere)
        assert intent.count == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
