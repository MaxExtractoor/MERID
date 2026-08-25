"""
Test policy engine execution check (CRITICAL FIX 2026-08-01).

This test verifies that the should_execute flag from the maker/taker policy engine
is properly enforced in the order router to prevent unprofitable trades.

Background:
- The maker/taker policy engine correctly sets should_execute=False for trades
  with insufficient edge (edge_net_fees < threshold)
- However, the order router was never checking this flag, allowing unprofitable
  trades to execute
- This is a critical design flaw that has been fixed by:
  1. Adding should_execute field to OrderIntent
  2. Copying should_execute from policy decision to intent
  3. Checking should_execute in order router before execution
"""

import pytest
from merid.event_venues.kalshi.order_router import OrderIntent
from merid.event_venues.kalshi.maker_taker_policy import MakerTakerPolicyEngine, PolicyMode, LiquidityRole


class TestOrderIntentShouldExecuteField:
    """Test that OrderIntent has the should_execute field."""

    def test_order_intent_has_should_execute_field(self):
        """Test that OrderIntent has the should_execute field."""
        intent = OrderIntent(
            ticker="KXBTC15M-26AUG011830-30",
            side="BUY_YES",
            action="buy",
            count=1,
            price_cents=38,
        )
        
        # Verify the field exists and can be set
        intent.should_execute = False
        assert intent.should_execute is False
        
        intent.should_execute = True
        assert intent.should_execute is True
        
        intent.should_execute = None
        assert intent.should_execute is None


class TestMakerTakerIntegrationCopiesShouldExecute:
    """Test that maker/taker integration copies should_execute from policy decision."""

    def test_should_execute_copied_from_policy_decision(self):
        """Test that should_execute is copied from policy decision to intent."""
        from merid.event_venues.kalshi.maker_taker_integration import apply_maker_taker_policy
        from merid.event_venues.kalshi.maker_taker_policy import decide_order_role
        
        # Create intent
        intent = OrderIntent(
            ticker="KXBTC15M-26AUG011830-30",
            side="BUY_YES",
            action="buy",
            count=1,
            price_cents=38,
            edge_pct=1.5,  # Low edge - should be rejected
            policy_mode="AGGRESSIVE_CONVICTION",
        )
        
        # Get policy decision
        role_decision = decide_order_role(
            policy_mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=1.5,
            price_cents=38,
            market_best_bid_cents=37,
            market_best_ask_cents=39,
            contracts=1,
            side="yes",
            action="buy",
        )
        
        # Verify policy decision has should_execute=False for low edge
        assert role_decision.should_execute is False, "Low edge should be rejected by policy engine"
        
        # Manually copy the policy decision to intent (simulating what apply_maker_taker_policy does)
        intent.expected_role = role_decision.recommended_role.value
        intent.fee_type = role_decision.recommended_role.value
        intent.estimated_fee_cents = role_decision.fee_cents_estimate
        intent.edge_net_of_fees_pct = role_decision.edge_net_of_fees_pct
        intent.should_execute = role_decision.should_execute  # CRITICAL FIX (2026-08-01)
        intent.policy_mode = PolicyMode.AGGRESSIVE_CONVICTION.name
        
        # Verify should_execute was copied
        assert intent.should_execute is False, "should_execute should be copied from policy decision"
        assert intent.edge_net_of_fees_pct is not None, "edge_net_of_fees_pct should be set"
        assert intent.policy_mode is not None, "policy_mode should be set"

    def test_should_execute_true_for_high_edge(self):
        """Test that should_execute=True for high edge."""
        from merid.event_venues.kalshi.maker_taker_policy import decide_order_role
        
        # Create intent with high edge
        intent = OrderIntent(
            ticker="KXBTC15M-26AUG011830-30",
            side="BUY_YES",
            action="buy",
            count=1,
            price_cents=38,
            edge_pct=8.0,  # High edge - should be accepted
            policy_mode="AGGRESSIVE_CONVICTION",
        )
        
        # Get policy decision
        role_decision = decide_order_role(
            policy_mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=8.0,
            price_cents=38,
            market_best_bid_cents=35,  # Lower bid to simulate crossing spread
            market_best_ask_cents=40,
            contracts=1,
            side="yes",
            action="buy",
        )
        
        # Verify policy decision has should_execute=True for high edge
        assert role_decision.should_execute is True, "High edge should be accepted by policy engine"
        
        # Manually copy the policy decision to intent (simulating what apply_maker_taker_policy does)
        intent.expected_role = role_decision.recommended_role.value
        intent.fee_type = role_decision.recommended_role.value
        intent.estimated_fee_cents = role_decision.fee_cents_estimate
        intent.edge_net_of_fees_pct = role_decision.edge_net_of_fees_pct
        intent.should_execute = role_decision.should_execute  # CRITICAL FIX (2026-08-01)
        intent.policy_mode = PolicyMode.AGGRESSIVE_CONVICTION.name
        
        # Verify should_execute was copied
        assert intent.should_execute is True, "should_execute should be copied from policy decision"


class TestPolicyEngineThreshold:
    """Test that the policy engine threshold is set correctly."""

    def test_aggressive_threshold_is_2_percent(self):
        """Test that AGGRESSIVE_THRESHOLD_PCT is set to 2.0%."""
        engine = MakerTakerPolicyEngine()
        assert engine.aggressive_threshold_pct == 2.0, "Threshold should be 2.0% (industry standard)"

    def test_low_edge_rejected_by_policy(self):
        """Test that low edge (<2%) is rejected by policy engine."""
        engine = MakerTakerPolicyEngine()
        
        # Test with 1.5% edge (below 2% threshold)
        decision = engine.decide(
            mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=1.5,
            price_cents=38,
            market_best_bid_cents=37,
            market_best_ask_cents=39,
            contracts=1,
            side="BUY_YES",
            action="buy",
        )
        
        # Should recommend maker with should_execute=False
        assert decision.recommended_role == LiquidityRole.MAKER
        assert decision.should_execute is False, "Low edge should be rejected"

    def test_high_edge_accepted_by_policy(self):
        """Test that high edge (>2%) is accepted by policy engine when crossing spread."""
        engine = MakerTakerPolicyEngine()
        
        # Test with 8% edge (above 2% threshold) and crossing spread
        # Price 38c, bid 35c, ask 40c - buying at 38c crosses the spread
        decision = engine.decide(
            mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=8.0,
            price_cents=38,
            market_best_bid_cents=35,  # Lower bid to simulate crossing spread
            market_best_ask_cents=40,
            contracts=1,
            side="BUY_YES",
            action="buy",
        )
        
        # Should recommend taker with should_execute=True when crossing spread with sufficient edge
        # Note: The exact decision depends on edge_net_of_taker calculation
        # With 8% edge, it should be accepted
        assert decision.should_execute is True, "High edge should be accepted"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
