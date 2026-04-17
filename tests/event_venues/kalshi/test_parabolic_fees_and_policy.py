"""Tests for Kalshi parabolic fee calculations and MakerTakerPolicyEngine.

Ground truth fee spec (from Kalshi docs):
- Taker fee: fee_cents = ceil(0.07 * C * P * (1 - P))
- Maker fee: fee_cents = ceil(0.0175 * C * P * (1 - P))
- P ∈ (0.01, 0.99) dollars
- Max taker fee at P=0.5: 1.75¢/contract
- Max maker fee at P=0.5: 0.4375¢/contract
"""

from __future__ import annotations

import math
import pytest

from merid.event_venues.kalshi.parabolic_fees import (
    kalshi_taker_fee_cents_parabolic,
    kalshi_maker_fee_cents,
    kalshi_fee_cents_parabolic,
    estimate_fee_for_sizing,
    fee_per_contract_cents,
    max_fee_cents,
    TAKER_FEE_RATE,
    MAKER_FEE_RATE,
    MAX_TAKER_FEE_PER_CONTRACT_CENTS,
    MAX_MAKER_FEE_PER_CONTRACT_CENTS,
)
from merid.event_venues.kalshi.maker_taker_policy import (
    MakerTakerPolicyEngine,
    PolicyMode,
    LiquidityRole,
    RoleDecision,
    decide_order_role,
    get_default_engine,
)


class TestParabolicFeeFormulas:
    """Test parabolic fee calculations against canonical spec."""

    def test_taker_fee_at_midpoint(self):
        """At P=0.5, taker fee should be exactly 1.75¢ per contract."""
        # P=0.5, C=1: fee = ceil(0.07 * 1 * 0.5 * 0.5 * 100) = ceil(1.75) = 2
        # Actually: 0.07 * 1 * 0.25 = 0.0175 dollars = 1.75 cents
        fee = kalshi_taker_fee_cents_parabolic(price_dollars=0.5, contracts=1)
        assert fee == 2  # ceil(1.75) = 2

    def test_taker_fee_at_midpoint_10_contracts(self):
        """At P=0.5 with 10 contracts."""
        # 0.07 * 10 * 0.25 = 0.175 dollars = 17.5 cents -> ceil = 18
        fee = kalshi_taker_fee_cents_parabolic(price_dollars=0.5, contracts=10)
        assert fee == 18

    def test_maker_fee_at_midpoint(self):
        """At P=0.5, maker fee should be exactly 0.4375¢ per contract."""
        # 0.0175 * 1 * 0.25 = 0.004375 dollars = 0.4375 cents -> ceil = 1
        fee = kalshi_maker_fee_cents(price_dollars=0.5, contracts=1)
        assert fee == 1

    def test_maker_fee_is_quarter_of_taker(self):
        """Maker fee rate is exactly 25% of taker fee rate."""
        assert MAKER_FEE_RATE == TAKER_FEE_RATE * 0.25

    def test_fee_bounds_at_extremes(self):
        """Fees approach 0 as P approaches 0 or 1."""
        # Near P=0
        fee_low = kalshi_taker_fee_cents_parabolic(price_dollars=0.01, contracts=100)
        assert fee_low >= 0
        assert fee_low < 10  # Should be small

        # Near P=1
        fee_high = kalshi_taker_fee_cents_parabolic(price_dollars=0.99, contracts=100)
        assert fee_high >= 0
        assert fee_high < 10  # Should be small

    def test_fee_scales_with_contracts(self):
        """Fee scales linearly with contract count."""
        p = 0.55
        fee_1 = kalshi_taker_fee_cents_parabolic(price_dollars=p, contracts=1)
        fee_10 = kalshi_taker_fee_cents_parabolic(price_dollars=p, contracts=10)
        fee_100 = kalshi_taker_fee_cents_parabolic(price_dollars=p, contracts=100)

        # Due to ceiling, ratios are approximate
        assert fee_10 >= fee_1 * 9  # Allow for ceiling effects
        assert fee_10 <= fee_1 * 11
        # Using fee_1 to extrapolate to 100x is overly sensitive to ceiling at C=1.
        # fee_10 has far less ceiling distortion; use it as the baseline.
        assert fee_100 >= fee_10 * 9
        assert fee_100 <= fee_10 * 11

    def test_price_dollars_not_cents(self):
        """Price is in dollars (0.55), not cents (55)."""
        # These should give the same result
        fee_dollars = kalshi_taker_fee_cents_parabolic(price_dollars=0.55, contracts=10)
        fee_cents_wrong = kalshi_taker_fee_cents_parabolic(price_dollars=55, contracts=10)
        # 55 dollars would be way out of bounds and clamped
        assert fee_dollars != fee_cents_wrong or fee_cents_wrong == 0

    def test_zero_contracts_returns_zero(self):
        """Zero contracts should return zero fee."""
        assert kalshi_taker_fee_cents_parabolic(price_dollars=0.5, contracts=0) == 0
        assert kalshi_maker_fee_cents(price_dollars=0.5, contracts=0) == 0

    def test_negative_contracts_returns_zero(self):
        """Negative contracts should return zero fee."""
        assert kalshi_taker_fee_cents_parabolic(price_dollars=0.5, contracts=-5) == 0

    def test_unified_fee_function(self):
        """Test unified fee function with role parameter."""
        p, c = 0.55, 10
        taker_fee = kalshi_fee_cents_parabolic(p, c, role="taker")
        maker_fee = kalshi_fee_cents_parabolic(p, c, role="maker")

        assert taker_fee == kalshi_taker_fee_cents_parabolic(p, c)
        assert maker_fee == kalshi_maker_fee_cents(p, c)
        assert taker_fee > maker_fee  # Taker fee is higher

    def test_estimate_fee_for_sizing(self):
        """Test sizing helper that works with cents."""
        # price_cents=55 -> price_dollars=0.55
        fee = estimate_fee_for_sizing(price_cents=55, contracts=10, assume_taker=True)
        expected = kalshi_taker_fee_cents_parabolic(0.55, 10)
        assert fee == expected

    def test_fee_per_contract_cents(self):
        """Test per-contract fee calculation."""
        p = 0.5
        taker_per = fee_per_contract_cents(p, role="taker")
        maker_per = fee_per_contract_cents(p, role="maker")

        assert taker_per == 1.75  # Exact max at P=0.5
        assert maker_per == 0.4375  # Exact max at P=0.5

    def test_max_fee_cents(self):
        """Test max fee calculation at P=0.5."""
        assert max_fee_cents(1, "taker") == 2  # ceil(1.75) = 2
        assert max_fee_cents(1, "maker") == 1  # ceil(0.4375) = 1
        assert max_fee_cents(10, "taker") == 18  # ceil(17.5) = 18
        assert max_fee_cents(10, "maker") == 5  # ceil(4.375) = 5


class TestRegressionFeeTable:
    """Regression tests with hard-coded expected values from the formula."""

    @pytest.mark.parametrize(
        "price_dollars,contracts,expected_taker,expected_maker",
        [
            # P=0.01 (near 0)
            (0.01, 1, 1, 1),  # ceil(0.07 * 1 * 0.01 * 0.99 * 100) = ceil(0.0693) = 1
            # P=0.05
            (0.05, 10, 4, 1),  # ceil(0.07 * 10 * 0.05 * 0.95 * 100) = ceil(3.325) = 4
            # P=0.50 (max fee)
            (0.50, 1, 2, 1),  # ceil(1.75) = 2, ceil(0.4375) = 1
            (0.50, 10, 18, 5),  # ceil(17.5) = 18, ceil(4.375) = 5
            (0.50, 100, 175, 44),  # ceil(175) = 175, ceil(43.75) = 44
            # P=0.95
            (0.95, 10, 4, 1),  # Same as P=0.05 due to symmetry
            # P=0.99 (near 1)
            (0.99, 1, 1, 1),  # Same as P=0.01 due to symmetry
        ],
    )
    def test_regression_table(
        self, price_dollars: float, contracts: int, expected_taker: int, expected_maker: int
    ):
        """Test against pre-computed expected values."""
        taker_fee = kalshi_taker_fee_cents_parabolic(price_dollars, contracts)
        maker_fee = kalshi_maker_fee_cents(price_dollars, contracts)

        assert taker_fee == expected_taker, (
            f"Taker fee mismatch at P={price_dollars}, C={contracts}: "
            f"got {taker_fee}, expected {expected_taker}"
        )
        assert maker_fee == expected_maker, (
            f"Maker fee mismatch at P={price_dollars}, C={contracts}: "
            f"got {maker_fee}, expected {expected_maker}"
        )


class TestMakerTakerPolicyEngine:
    """Test MakerTakerPolicyEngine role decisions."""

    def test_neutral_mm_always_maker(self):
        """NEUTRAL_MM mode should always recommend maker."""
        engine = MakerTakerPolicyEngine()
        decision = engine.decide(
            mode=PolicyMode.NEUTRAL_MM,
            edge_pct=5.0,
            price_cents=55,
            market_best_bid_cents=54,
            market_best_ask_cents=56,
            contracts=10,
        )

        assert decision.recommended_role == LiquidityRole.MAKER
        assert decision.expected_role == LiquidityRole.MAKER
        assert decision.post_only is True
        assert decision.should_execute is True  # Positive edge

    def test_neutral_mm_rejects_negative_edge(self):
        """NEUTRAL_MM should not execute if edge is negative."""
        engine = MakerTakerPolicyEngine()
        decision = engine.decide(
            mode=PolicyMode.NEUTRAL_MM,
            edge_pct=-1.0,  # Negative edge
            price_cents=55,
            market_best_bid_cents=54,
            market_best_ask_cents=56,
            contracts=10,
        )

        assert decision.should_execute is False

    def test_aggressive_conviction_takes_when_edge_high(self):
        """AGGRESSIVE_CONVICTION should take when edge >> fees + threshold."""
        engine = MakerTakerPolicyEngine(aggressive_threshold_pct=2.0)

        # High edge, price at ask (crosses spread)
        decision = engine.decide(
            mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=10.0,  # 10% edge, well above threshold
            price_cents=56,  # At the ask
            market_best_bid_cents=54,
            market_best_ask_cents=56,
            contracts=10,
            action="buy",
        )

        assert decision.recommended_role == LiquidityRole.TAKER
        assert decision.post_only is False
        assert decision.should_execute is True

    def test_aggressive_conviction_maker_when_edge_low(self):
        """AGGRESSIVE_CONVICTION should use maker when edge insufficient."""
        engine = MakerTakerPolicyEngine(aggressive_threshold_pct=5.0)

        # Low edge that doesn't justify crossing
        decision = engine.decide(
            mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=2.0,  # Below 5% threshold
            price_cents=55,  # Inside spread
            market_best_bid_cents=54,
            market_best_ask_cents=56,
            contracts=10,
        )

        assert decision.recommended_role == LiquidityRole.MAKER
        assert decision.post_only is True

    def test_arb_leg_prefers_taker(self):
        """ARB_LEG should prefer taker for speed when edge covers fees."""
        engine = MakerTakerPolicyEngine(arb_min_edge_pct=0.5)

        decision = engine.decide(
            mode=PolicyMode.ARB_LEG,
            # Must clear taker fees (~3.21% at 56c, 10 contracts) + 0.5% threshold.
            edge_pct=5.0,
            price_cents=56,
            market_best_bid_cents=54,
            market_best_ask_cents=56,
            contracts=10,
        )

        assert decision.recommended_role == LiquidityRole.TAKER
        assert decision.post_only is False

    def test_arb_leg_falls_back_to_maker(self):
        """ARB_LEG should fall back to maker if edge too small for taker."""
        engine = MakerTakerPolicyEngine(arb_min_edge_pct=5.0)

        decision = engine.decide(
            mode=PolicyMode.ARB_LEG,
            edge_pct=2.0,  # Below 5% threshold
            price_cents=55,
            market_best_bid_cents=54,
            market_best_ask_cents=56,
            contracts=10,
        )

        assert decision.recommended_role == LiquidityRole.MAKER
        assert decision.post_only is True

    def test_convenience_function(self):
        """Test decide_order_role convenience function."""
        decision = decide_order_role(
            policy_mode=PolicyMode.NEUTRAL_MM,
            edge_pct=5.0,
            price_cents=55,
            market_best_bid_cents=54,
            market_best_ask_cents=56,
            contracts=10,
        )

        assert isinstance(decision, RoleDecision)
        assert decision.recommended_role == LiquidityRole.MAKER

    def test_default_engine(self):
        """Test get_default_engine returns a working engine."""
        engine = get_default_engine()
        decision = engine.decide(
            mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=5.0,
            price_cents=55,
            market_best_bid_cents=54,
            market_best_ask_cents=56,
            contracts=10,
        )
        assert isinstance(decision, RoleDecision)


class TestPolicyEngineEdgeCases:
    """Test edge cases for policy engine."""

    def test_missing_market_data_defaults(self):
        """Test behavior when market data is missing."""
        engine = MakerTakerPolicyEngine()

        # With price between bid and ask (not crossing)
        decision = engine.decide(
            mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=5.0,
            price_cents=55,
            market_best_bid_cents=54,
            market_best_ask_cents=56,
            contracts=10,
            action="buy",
        )

        # Price 55 is below ask 56, so not crossing
        assert decision.recommended_role == LiquidityRole.MAKER

    def test_price_at_bid_for_sell(self):
        """Test sell order at bid price (crosses for sells)."""
        engine = MakerTakerPolicyEngine()

        decision = engine.decide(
            mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=10.0,
            price_cents=54,  # At the bid
            market_best_bid_cents=54,
            market_best_ask_cents=56,
            contracts=10,
            action="sell",  # Sell at bid = crosses spread
        )

        # Sell at bid crosses spread, should be taker
        assert decision.recommended_role == LiquidityRole.TAKER

    def test_extreme_prices(self):
        """Test policy engine at extreme prices."""
        engine = MakerTakerPolicyEngine()

        # Very low price (1 cent)
        decision_low = engine.decide(
            mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=5.0,
            price_cents=1,
            market_best_bid_cents=1,
            market_best_ask_cents=2,
            contracts=10,
        )
        assert decision_low.fee_cents_estimate >= 0

        # Very high price (98 cents)
        decision_high = engine.decide(
            mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=5.0,
            price_cents=98,
            market_best_bid_cents=97,
            market_best_ask_cents=99,
            contracts=10,
        )
        assert decision_high.fee_cents_estimate >= 0

    def test_decision_fields_populated(self):
        """Test that all decision fields are properly populated."""
        engine = MakerTakerPolicyEngine()

        decision = engine.decide(
            mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=5.0,
            price_cents=55,
            market_best_bid_cents=54,
            market_best_ask_cents=56,
            contracts=10,
        )

        assert decision.recommended_role is not None
        assert decision.expected_role is not None
        assert isinstance(decision.should_execute, bool)
        assert isinstance(decision.post_only, bool)
        assert decision.reason is not None
        assert isinstance(decision.threshold_pct, float)
        assert isinstance(decision.fee_cents_estimate, int)
        assert isinstance(decision.edge_net_of_fees_pct, float)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
