"""Tests for MakerTakerPolicyEngine and parabolic fee functions."""

import pytest

from merid.event_venues.kalshi.maker_taker_policy import (
    MakerTakerPolicyEngine,
    PolicyMode,
    PolicyDecision,
    kalshi_taker_fee_cents_parabolic,
    kalshi_maker_fee_cents,
    get_maker_taker_policy_engine,
)


# ══════════════════════════════════════════════════════════════════════════════
# Parabolic Fee Function Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestParabolicFees:
    """Test parabolic fee calculations."""

    def test_taker_fee_at_50_cents(self):
        """Taker fee is maximal at 50¢ price."""
        # At P=0.5: 0.07 × 10 × 0.5 × 0.5 = 0.175 dollars = 18 cents
        assert kalshi_taker_fee_cents_parabolic(50, 10) == 18

    def test_taker_fee_at_55_cents(self):
        """Taker fee at 55¢ price."""
        # At P=0.55: 0.07 × 10 × 0.55 × 0.45 = 0.17325 dollars = 18 cents (ceil)
        assert kalshi_taker_fee_cents_parabolic(55, 10) == 18

    def test_taker_fee_at_extreme_prices(self):
        """Taker fees decrease toward extreme prices."""
        # At P=0.90: 0.07 × 10 × 0.90 × 0.10 = 0.063 dollars = 7 cents
        assert kalshi_taker_fee_cents_parabolic(90, 10) == 7
        # At P=0.10: 0.07 × 10 × 0.10 × 0.90 = 0.063 dollars = 7 cents
        assert kalshi_taker_fee_cents_parabolic(10, 10) == 7

    def test_taker_fee_scales_with_contracts(self):
        """Taker fee scales proportionally with contract count."""
        # At P=0.50: 0.07 × C × 0.5 × 0.5 = 0.0175 × C dollars
        assert kalshi_taker_fee_cents_parabolic(50, 1) == 2  # ceil(0.0175) = 2
        assert kalshi_taker_fee_cents_parabolic(50, 10) == 18  # ceil(0.175) = 18
        assert kalshi_taker_fee_cents_parabolic(50, 100) == 175  # ceil(1.75) = 175

    def test_maker_fee_at_50_cents(self):
        """Maker fee is 1/4 of taker fee."""
        # At P=0.5: 0.0175 × 10 × 0.5 × 0.5 = 0.04375 dollars = 5 cents
        assert kalshi_maker_fee_cents(50, 10) == 5

    def test_maker_fee_at_55_cents(self):
        """Maker fee at 55¢ price."""
        # At P=0.55: 0.0175 × 10 × 0.55 × 0.45 = 0.0433125 dollars = 5 cents (ceil)
        assert kalshi_maker_fee_cents(55, 10) == 5

    def test_maker_fee_is_quarter_of_taker(self):
        """Maker fees are approximately 1/4 of taker fees."""
        for price_cents in [20, 30, 40, 50, 60, 70, 80]:
            for contracts in [1, 10, 50, 100]:
                taker_fee = kalshi_taker_fee_cents_parabolic(price_cents, contracts)
                maker_fee = kalshi_maker_fee_cents(price_cents, contracts)
                # Maker should be roughly 1/4 of taker (within rounding)
                assert maker_fee <= taker_fee / 4 + 1  # Allow 1 cent for rounding

    def test_fee_edge_cases(self):
        """Test edge cases for fee calculation."""
        # Zero contracts
        assert kalshi_taker_fee_cents_parabolic(50, 0) == 0
        assert kalshi_maker_fee_cents(50, 0) == 0

        # Invalid price (0 or 100)
        assert kalshi_taker_fee_cents_parabolic(0, 10) == 0
        assert kalshi_taker_fee_cents_parabolic(100, 10) == 0
        assert kalshi_maker_fee_cents(0, 10) == 0
        assert kalshi_maker_fee_cents(100, 10) == 0

        # Negative inputs
        assert kalshi_taker_fee_cents_parabolic(-10, 10) == 0
        assert kalshi_taker_fee_cents_parabolic(50, -10) == 0


# ══════════════════════════════════════════════════════════════════════════════
# Policy Engine Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestPolicyEngine:
    """Test MakerTakerPolicyEngine decision logic."""

    def setup_method(self):
        """Create a fresh policy engine for each test."""
        self.engine = MakerTakerPolicyEngine()

    def test_neutral_mm_always_maker(self):
        """NEUTRAL_MM mode always chooses maker."""
        decision = self.engine.decide(
            mode=PolicyMode.NEUTRAL_MM,
            edge_pct=5.0,
            price_cents=55,
            contracts=10,
        )

        assert decision.role == "maker"
        assert decision.post_only is True
        assert "neutral_mm" in decision.reason

    def test_neutral_mm_with_high_edge(self):
        """NEUTRAL_MM stays maker even with high edge."""
        decision = self.engine.decide(
            mode=PolicyMode.NEUTRAL_MM,
            edge_pct=20.0,  # Very high edge
            price_cents=55,
            contracts=10,
        )

        assert decision.role == "maker"
        assert decision.post_only is True

    def test_arb_leg_always_taker(self):
        """ARB_LEG mode always chooses taker."""
        decision = self.engine.decide(
            mode=PolicyMode.ARB_LEG,
            edge_pct=5.0,
            price_cents=55,
            contracts=10,
        )

        assert decision.role == "taker"
        assert decision.post_only is False
        assert "arb_leg" in decision.reason

    def test_arb_leg_with_low_edge(self):
        """ARB_LEG takes even with low edge (speed priority)."""
        decision = self.engine.decide(
            mode=PolicyMode.ARB_LEG,
            edge_pct=0.5,  # Very low edge
            price_cents=55,
            contracts=10,
        )

        assert decision.role == "taker"
        assert decision.post_only is False

    def test_aggressive_conviction_low_edge_makes(self):
        """AGGRESSIVE_CONVICTION makes when edge is low."""
        decision = self.engine.decide(
            mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=0.5,  # Low edge
            price_cents=55,
            contracts=10,
        )

        assert decision.role == "maker"
        assert decision.post_only is True

    def test_aggressive_conviction_high_edge_takes(self):
        """AGGRESSIVE_CONVICTION takes when edge >> fees."""
        # At 55¢, 10 contracts:
        # Taker fee ≈ 18 cents = 0.3% of notional (55 × 10 = 550)
        # Edge 5% >> 0.3%, so should take
        decision = self.engine.decide(
            mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=5.0,
            price_cents=55,
            contracts=10,
        )

        assert decision.role == "taker"
        assert decision.post_only is False
        assert "exceeds" in decision.reason

    def test_aggressive_conviction_marginal_edge(self):
        """AGGRESSIVE_CONVICTION with edge near threshold."""
        # Edge = 2.0%, taker fee ≈ 0.3% → ratio ≈ 6.7x
        # Default multiplier is 2.0x, so should take
        decision = self.engine.decide(
            mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=2.0,
            price_cents=55,
            contracts=10,
        )

        # With edge 2% and fee ~0.3%, ratio > 2x threshold
        assert decision.role == "taker"

    def test_aggressive_conviction_below_min_edge(self):
        """AGGRESSIVE_CONVICTION makes when below min take threshold."""
        # Default min_take_edge_pct is 1.0%
        decision = self.engine.decide(
            mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=0.8,  # Below 1% threshold
            price_cents=55,
            contracts=10,
        )

        assert decision.role == "maker"
        assert "below_min" in decision.reason

    def test_decision_includes_fees(self):
        """Decision includes both maker and taker fees."""
        decision = self.engine.decide(
            mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=3.0,
            price_cents=55,
            contracts=10,
        )

        assert decision.taker_fee_cents > 0
        assert decision.maker_fee_cents > 0
        assert decision.taker_fee_cents > decision.maker_fee_cents
        assert decision.edge_pct == 3.0
        assert decision.fee_edge_ratio > 0

    def test_decision_with_spread_data(self):
        """Decision accepts spread data for future enhancements."""
        decision = self.engine.decide(
            mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=3.0,
            price_cents=55,
            contracts=10,
            bid_cents=54,
            ask_cents=56,
            spread_bps=200,
        )

        # Spread data doesn't affect current logic but should not error
        assert decision.role in ("maker", "taker")

    def test_custom_multiplier(self):
        """Engine accepts custom aggressive_edge_multiplier."""
        strict_engine = MakerTakerPolicyEngine(aggressive_edge_multiplier=5.0)

        # With 5x multiplier, need edge 5x larger than fees to take
        # Edge 3%, fee ~0.3% → ratio ~10x, which exceeds 5x
        decision = strict_engine.decide(
            mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=3.0,
            price_cents=55,
            contracts=10,
        )
        assert decision.role == "taker"

        # Edge 1.5%, fee ~0.3% → ratio ~5x, which meets 5x threshold
        decision = strict_engine.decide(
            mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=1.5,
            price_cents=55,
            contracts=10,
        )
        assert decision.role == "taker"

        # Edge 1.2%, fee ~0.3% → ratio ~4x, which is below 5x threshold
        decision = strict_engine.decide(
            mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=1.2,
            price_cents=55,
            contracts=10,
        )
        assert decision.role == "maker"


class TestPolicySingleton:
    """Test singleton pattern for policy engine."""

    def test_singleton_returns_same_instance(self):
        """get_maker_taker_policy_engine returns singleton."""
        engine1 = get_maker_taker_policy_engine()
        engine2 = get_maker_taker_policy_engine()
        assert engine1 is engine2


# ══════════════════════════════════════════════════════════════════════════════
# Integration Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestPolicyIntegration:
    """Integration tests combining fees and policy decisions."""

    def test_fee_aware_decision_at_different_sizes(self):
        """Policy considers fees correctly at different contract sizes."""
        engine = MakerTakerPolicyEngine()

        # Small size: fees relatively larger as % of notional
        small_decision = engine.decide(
            mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=2.0,
            price_cents=50,
            contracts=1,
        )

        # Large size: fees relatively smaller as % of notional
        large_decision = engine.decide(
            mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=2.0,
            price_cents=50,
            contracts=100,
        )

        # Both should make same decision based on edge/fee ratio
        # (parabolic fees scale linearly with contracts)
        assert small_decision.role == large_decision.role

    def test_fee_aware_decision_at_different_prices(self):
        """Policy considers fees correctly at different price points."""
        engine = MakerTakerPolicyEngine()

        # At 50¢: fees are maximal (P × (1-P) is maximal at 0.5)
        mid_decision = engine.decide(
            mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=2.0,
            price_cents=50,
            contracts=10,
        )

        # At 90¢: fees are lower (P × (1-P) is smaller at extremes)
        extreme_decision = engine.decide(
            mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=2.0,
            price_cents=90,
            contracts=10,
        )

        # Both should take with 2% edge since edge >> fees
        assert mid_decision.role == "taker"
        assert extreme_decision.role == "taker"

        # Fee at 50¢ should be higher than at 90¢
        assert mid_decision.taker_fee_cents > extreme_decision.taker_fee_cents
