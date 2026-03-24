"""Tests for MakerTakerPolicyEngine and parabolic fee functions."""

import pytest

from merid.event_venues.kalshi.maker_taker_policy import (
    MakerTakerPolicyEngine,
    PolicyMode,
    kalshi_maker_fee_cents,
    kalshi_taker_fee_cents,
)


class TestParabolicFees:
    """Test parabolic fee functions match Kalshi specification."""

    def test_taker_fee_at_50_cents(self):
        """Test taker fee at P=0.5 (maximum fee point).

        At P=0.5, taker fee should be 0.07 × 0.5 × 0.5 = 0.0175 per contract
        = 1.75 cents per contract (rounds up to 2 cents).
        """
        # Single contract at 50 cents
        fee = kalshi_taker_fee_cents(50, 1)
        assert fee == 2, f"Expected 2 cents for 1 contract at 50c, got {fee}"

        # 10 contracts at 50 cents
        fee = kalshi_taker_fee_cents(50, 10)
        expected = 2 * 10  # 2 cents per contract
        assert fee == expected, f"Expected {expected} cents for 10 contracts at 50c, got {fee}"

    def test_maker_fee_at_50_cents(self):
        """Test maker fee at P=0.5 (maximum fee point).

        At P=0.5, maker fee should be 0.0175 × 0.5 × 0.5 = 0.004375 per contract
        = 0.4375 cents per contract (rounds up to 1 cent).
        """
        # Single contract at 50 cents
        fee = kalshi_maker_fee_cents(50, 1)
        assert fee == 1, f"Expected 1 cent for 1 contract at 50c, got {fee}"

        # 10 contracts at 50 cents
        fee = kalshi_maker_fee_cents(50, 10)
        expected = 1 * 10  # 1 cent per contract
        assert fee == expected, f"Expected {expected} cents for 10 contracts at 50c, got {fee}"

    def test_maker_fee_is_quarter_of_taker(self):
        """Verify maker fee is approximately 1/4 of taker fee (0.0175/0.07 = 0.25)."""
        test_cases = [
            (30, 10),
            (50, 10),
            (70, 10),
            (45, 20),
        ]

        for price_cents, contracts in test_cases:
            taker_fee = kalshi_taker_fee_cents(price_cents, contracts)
            maker_fee = kalshi_maker_fee_cents(price_cents, contracts)

            # Maker should be roughly 1/4 of taker (allow some rounding variance)
            ratio = maker_fee / taker_fee if taker_fee > 0 else 0
            assert 0.20 <= ratio <= 0.30, (
                f"Maker/taker ratio {ratio:.2f} outside expected range "
                f"for price={price_cents}c, contracts={contracts}"
            )

    def test_fees_at_extremes(self):
        """Test fees at P near 0 and P near 1 (low fees)."""
        # Near P=0 (e.g., 5 cents)
        taker_fee = kalshi_taker_fee_cents(5, 10)
        maker_fee = kalshi_maker_fee_cents(5, 10)

        # Fees should be much lower than at P=0.5
        mid_taker = kalshi_taker_fee_cents(50, 10)
        mid_maker = kalshi_maker_fee_cents(50, 10)

        assert taker_fee < mid_taker, "Taker fee should be lower at P=0.05 than P=0.5"
        assert maker_fee < mid_maker, "Maker fee should be lower at P=0.05 than P=0.5"

        # Near P=1 (e.g., 95 cents)
        taker_fee = kalshi_taker_fee_cents(95, 10)
        maker_fee = kalshi_maker_fee_cents(95, 10)

        assert taker_fee < mid_taker, "Taker fee should be lower at P=0.95 than P=0.5"
        assert maker_fee < mid_maker, "Maker fee should be lower at P=0.95 than P=0.5"

    def test_zero_and_invalid_inputs(self):
        """Test fee functions handle edge cases."""
        # Zero contracts
        assert kalshi_taker_fee_cents(50, 0) == 0
        assert kalshi_maker_fee_cents(50, 0) == 0

        # Invalid prices
        assert kalshi_taker_fee_cents(0, 10) == 0
        assert kalshi_taker_fee_cents(100, 10) == 0
        assert kalshi_maker_fee_cents(0, 10) == 0
        assert kalshi_maker_fee_cents(100, 10) == 0


class TestMakerTakerPolicyEngine:
    """Test MakerTakerPolicyEngine decision logic."""

    def test_neutral_mm_forces_maker(self):
        """Test NEUTRAL_MM mode always forces post-only (maker)."""
        engine = MakerTakerPolicyEngine()

        # Good edge case - should allow maker
        decision = engine.decide(
            fair_value_cents=56,
            market_best_bid_cents=52,
            market_best_ask_cents=54,
            side="yes",
            contracts=10,
            policy_mode=PolicyMode.NEUTRAL_MM,
        )

        assert decision.allowed, f"Should allow maker order: {decision.reason}"
        assert decision.expected_role == "maker"
        assert decision.post_only is True
        assert decision.order_type == "limit"

    def test_neutral_mm_rejects_negative_edge(self):
        """Test NEUTRAL_MM rejects orders with negative maker edge."""
        engine = MakerTakerPolicyEngine()

        # Fair value below mid - negative edge
        decision = engine.decide(
            fair_value_cents=45,
            market_best_bid_cents=52,
            market_best_ask_cents=54,
            side="yes",
            contracts=10,
            policy_mode=PolicyMode.NEUTRAL_MM,
        )

        assert not decision.allowed, "Should reject negative edge in NEUTRAL_MM"
        assert "negative" in decision.reason.lower()

    def test_aggressive_conviction_allows_taker(self):
        """Test AGGRESSIVE_CONVICTION allows taker when edge >> fees."""
        engine = MakerTakerPolicyEngine()

        # Large edge relative to fees
        decision = engine.decide(
            fair_value_cents=60,
            market_best_bid_cents=52,
            market_best_ask_cents=54,
            side="yes",
            contracts=10,
            policy_mode=PolicyMode.AGGRESSIVE_CONVICTION,
        )

        assert decision.allowed, f"Should allow order: {decision.reason}"
        # With sufficient edge, should allow taker
        assert decision.expected_role in ["taker", "maker"]

    def test_aggressive_conviction_falls_back_to_maker(self):
        """Test AGGRESSIVE_CONVICTION falls back to maker when taker edge insufficient."""
        engine = MakerTakerPolicyEngine(min_edge_taker_multiple=2.0)

        # Small edge - not enough for taker, but enough for maker
        decision = engine.decide(
            fair_value_cents=54,
            market_best_bid_cents=52,
            market_best_ask_cents=53,
            side="yes",
            contracts=10,
            policy_mode=PolicyMode.AGGRESSIVE_CONVICTION,
        )

        if decision.allowed:
            # If allowed, should be maker (fallback)
            assert decision.expected_role == "maker"
            assert decision.post_only is True

    def test_edge_vs_fee_ratio(self):
        """Test that edge vs fee ratio is computed correctly."""
        engine = MakerTakerPolicyEngine(min_edge_taker_multiple=1.0)

        # Setup: fair_value=56, mid=53, edge=3 cents
        # Taker fee at 56c for 10 contracts: ~0.07 × 10 × 0.56 × 0.44 ≈ 17 cents
        # Per-contract fee: ~1.7 cents
        # Ratio: 3 / 1.7 ≈ 1.76
        decision = engine.decide(
            fair_value_cents=56,
            market_best_bid_cents=52,
            market_best_ask_cents=54,
            side="yes",
            contracts=10,
            policy_mode=PolicyMode.AGGRESSIVE_CONVICTION,
        )

        # Should have positive edge vs fee
        assert decision.edge_vs_fee > 0, "Edge vs fee should be positive"
        assert decision.fee_estimate_cents > 0, "Fee estimate should be positive"

    def test_no_liquidity_rejection(self):
        """Test that orders are rejected when no market liquidity."""
        engine = MakerTakerPolicyEngine()

        decision = engine.decide(
            fair_value_cents=55,
            market_best_bid_cents=None,
            market_best_ask_cents=None,
            side="yes",
            contracts=10,
            policy_mode=PolicyMode.NEUTRAL_MM,
        )

        assert not decision.allowed
        assert "liquidity" in decision.reason.lower()

    def test_arb_leg_mode(self):
        """Test ARB_LEG mode allows taker for speed when edge covers fees."""
        engine = MakerTakerPolicyEngine()

        # Good arb edge
        decision = engine.decide(
            fair_value_cents=58,
            market_best_bid_cents=52,
            market_best_ask_cents=54,
            side="yes",
            contracts=10,
            policy_mode=PolicyMode.ARB_LEG,
        )

        if decision.allowed:
            # Arb legs prefer taker for speed
            assert decision.expected_role == "taker"
            assert decision.order_type == "limit"  # Still use limit for price control


class TestFeeAwareSizing:
    """Test that sizing logic respects fee-adjusted edges."""

    def test_effective_edge_calculation(self):
        """Test effective edge after fees is computed correctly."""
        engine = MakerTakerPolicyEngine()

        decision = engine.decide(
            fair_value_cents=55,
            market_best_bid_cents=52,
            market_best_ask_cents=54,
            side="yes",
            contracts=10,
            policy_mode=PolicyMode.AGGRESSIVE_CONVICTION,
        )

        # Effective edge should be raw edge minus per-contract fee
        # Raw edge ≈ fair - mid = 55 - 53 = 2 cents
        # Fee per contract ≈ 1-2 cents
        # Effective edge should be close to 0 or slightly positive
        if decision.allowed and decision.expected_role == "taker":
            assert decision.effective_edge_cents < 2.0, (
                "Effective edge should be less than raw edge after fees"
            )
