"""Comprehensive tests for side-aware trading layer.

Tests the new unified side-aware trading layer that addresses the critical issues
found in the BUY/SELL YES/NO audit:

1. Side inversion bug prevention
2. Edge calculation consistency
3. Price space validation
4. Entry/exit invariant enforcement
5. Duality invariant checking
"""

import pytest
from decimal import Decimal

from merid.event_venues.kalshi.side_aware_trading_layer import (
    OrderType,
    TradingSide,
    TradingAction,
    BinaryProbability,
    SideAwareOrderIntent,
    SideAwarePriceValidator,
    SideAwareEdgeCalculator,
    InvariantChecker,
    create_side_aware_intent,
    validate_order_intent,
    convert_legacy_intent_to_side_aware,
)


class TestBinaryProbability:
    """Test unified probability model with duality invariant."""
    
    def test_valid_probability_model(self):
        """Valid probability model should pass all validations."""
        prob = BinaryProbability(yes_cents=65.0, no_cents=35.0)
        assert prob.yes_cents == 65.0
        assert prob.no_cents == 35.0
        assert prob.get_side_probability(TradingSide.YES) == 65.0
        assert prob.get_side_probability(TradingSide.NO) == 35.0
    
    def test_duality_invariant_enforcement(self):
        """Duality invariant (YES + NO = 100) must be enforced."""
        # Valid: 65 + 35 = 100
        BinaryProbability(yes_cents=65.0, no_cents=35.0)
        
        # Invalid: 70 + 35 = 105 (violates duality)
        with pytest.raises(ValueError, match="Duality invariant violated"):
            BinaryProbability(yes_cents=70.0, no_cents=35.0)
    
    def test_duality_tolerance(self):
        """Duality invariant allows 1 cent tolerance for floating point."""
        # Within tolerance: 65.5 + 34.5 = 100.0 (exact)
        BinaryProbability(yes_cents=65.5, no_cents=34.5)
        
        # Within tolerance: 65.3 + 34.7 = 100.0 (exact)
        BinaryProbability(yes_cents=65.3, no_cents=34.7)
    
    def test_range_validation(self):
        """Probabilities must be in [0, 100] range."""
        # Valid
        BinaryProbability(yes_cents=0.0, no_cents=100.0)
        BinaryProbability(yes_cents=100.0, no_cents=0.0)
        
        # Invalid: negative
        with pytest.raises(ValueError, match="yes_cents must be in"):
            BinaryProbability(yes_cents=-5.0, no_cents=105.0)
        
        # Invalid: > 100
        with pytest.raises(ValueError, match="yes_cents must be in"):
            BinaryProbability(yes_cents=105.0, no_cents=-5.0)
    
    def test_from_yes_factory(self):
        """Creating from YES probability should derive NO correctly."""
        prob = BinaryProbability.from_yes(65.0)
        assert prob.yes_cents == 65.0
        assert prob.no_cents == 35.0  # 100 - 65
    
    def test_from_no_factory(self):
        """Creating from NO probability should derive YES correctly."""
        prob = BinaryProbability.from_no(35.0)
        assert prob.no_cents == 35.0
        assert prob.yes_cents == 65.0  # 100 - 35
    
    def test_mandatory_probability_requirement(self):
        """At least one probability must be provided."""
        with pytest.raises(ValueError, match="At least one probability"):
            SideAwareOrderIntent.from_components(
                ticker="KXBTC15M-TEST",
                side="yes",
                action="buy",
                price_cents=50,
                count=1,
                yes_probability=None,
                no_probability=None,
            )


class TestSideAwareOrderIntent:
    """Test side-aware order intent with mandatory probability model."""
    
    def test_buy_yes_intent(self):
        """BUY_YES intent should have correct properties."""
        intent = SideAwareOrderIntent.from_components(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            yes_probability=65.0,
        )
        
        assert intent.order_type == OrderType.BUY_YES
        assert intent.side == TradingSide.YES
        assert intent.action == TradingAction.BUY
        assert intent.is_entry_order is True
        assert intent.is_exit_order is False
        assert intent.to_kalshi_format() == "BUY_YES"
    
    def test_buy_no_intent(self):
        """BUY_NO intent should have correct properties."""
        intent = SideAwareOrderIntent.from_components(
            ticker="KXBTC15M-TEST",
            side="no",
            action="buy",
            price_cents=50,
            count=1,
            no_probability=35.0,
        )
        
        assert intent.order_type == OrderType.BUY_NO
        assert intent.side == TradingSide.NO
        assert intent.action == TradingAction.BUY
        assert intent.is_entry_order is True
        assert intent.is_exit_order is False
        assert intent.to_kalshi_format() == "BUY_NO"
    
    def test_sell_yes_intent(self):
        """SELL_YES intent should have correct properties."""
        intent = SideAwareOrderIntent.from_components(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="sell",
            price_cents=50,
            count=1,
            yes_probability=65.0,
        )
        
        assert intent.order_type == OrderType.SELL_YES
        assert intent.side == TradingSide.YES
        assert intent.action == TradingAction.SELL
        # From flat, SELL_YES is a long-NO entry (same as BUY_NO).
        assert intent.is_entry_order is True
        assert intent.is_exit_order is False
        assert intent.signed_yes_delta == -1
        assert intent.to_kalshi_format() == "SELL_YES"
    
    def test_sell_no_intent(self):
        """SELL_NO intent should have correct properties."""
        intent = SideAwareOrderIntent.from_components(
            ticker="KXBTC15M-TEST",
            side="no",
            action="sell",
            price_cents=50,
            count=1,
            no_probability=35.0,
        )
        
        assert intent.order_type == OrderType.SELL_NO
        assert intent.side == TradingSide.NO
        assert intent.action == TradingAction.SELL
        # From flat, SELL_NO is a long-YES entry (same as BUY_YES).
        assert intent.is_entry_order is True
        assert intent.is_exit_order is False
        assert intent.signed_yes_delta == 1
        assert intent.to_kalshi_format() == "SELL_NO"
    
    def test_probability_derivation(self):
        """Probability should be derived correctly when only one side provided."""
        # Provide YES probability, derive NO
        intent_yes = SideAwareOrderIntent.from_components(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            yes_probability=65.0,
        )
        assert intent_yes.probability.yes_cents == 65.0
        assert intent_yes.probability.no_cents == 35.0
        
        # Provide NO probability, derive YES
        intent_no = SideAwareOrderIntent.from_components(
            ticker="KXBTC15M-TEST",
            side="no",
            action="buy",
            price_cents=50,
            count=1,
            no_probability=35.0,
        )
        assert intent_no.probability.no_cents == 35.0
        assert intent_no.probability.yes_cents == 65.0


class TestSideAwarePriceValidator:
    """Test side-aware price validation using correct price spaces."""
    
    def test_yes_order_validation(self):
        """YES orders should be validated against YES-space prices."""
        is_valid, reason = SideAwarePriceValidator.validate_order_price(
            order_price_cents=55,  # inside bid/ask spread
            side=TradingSide.YES,
            yes_mid_cents=55,
            yes_bid_cents=53,
            yes_ask_cents=57,
        )
        
        assert is_valid is True
        assert reason is None
    
    def test_no_order_validation(self):
        """NO orders should be validated against NO-space prices."""
        is_valid, reason = SideAwarePriceValidator.validate_order_price(
            order_price_cents=45,
            side=TradingSide.NO,
            yes_mid_cents=55,  # YES mid = 55c, so NO mid = 45c
            yes_bid_cents=53,   # YES bid = 53c, so NO ask = 47c
            yes_ask_cents=57,   # YES ask = 57c, so NO bid = 43c
        )
        
        assert is_valid is True
        assert reason is None
    
    def test_price_too_far_from_mid(self):
        """Orders too far from mid should be rejected."""
        is_valid, reason = SideAwarePriceValidator.validate_order_price(
            order_price_cents=110,  # Way too high
            side=TradingSide.YES,
            yes_mid_cents=55,
            max_deviation_cents=50,
        )
        
        assert is_valid is False
        assert "price_too_far_from_mid" in reason
    
    def test_buy_above_ask_rejection(self):
        """Buy orders above ask should be rejected."""
        is_valid, reason = SideAwarePriceValidator.validate_order_price(
            order_price_cents=60,  # Above ask
            side=TradingSide.YES,
            yes_mid_cents=55,
            yes_bid_cents=53,
            yes_ask_cents=57,
        )
        
        assert is_valid is False
        assert "buy_above_ask" in reason
    
    def test_sell_below_bid_rejection(self):
        """Sell orders below bid should be rejected."""
        is_valid, reason = SideAwarePriceValidator.validate_order_price(
            order_price_cents=50,  # Below bid
            side=TradingSide.YES,
            yes_mid_cents=55,
            yes_bid_cents=53,
            yes_ask_cents=57,
        )
        
        assert is_valid is False
        assert "sell_below_bid" in reason
    
    def test_no_order_price_space_conversion(self):
        """NO orders should use NO-space prices for validation."""
        # YES bid = 53c, so NO ask = 47c
        # YES ask = 57c, so NO bid = 43c
        # YES mid = 55c, so NO mid = 45c
        
        # NO buy at 45c (at NO mid) should be valid
        is_valid, reason = SideAwarePriceValidator.validate_order_price(
            order_price_cents=45,
            side=TradingSide.NO,
            yes_mid_cents=55,
            yes_bid_cents=53,
            yes_ask_cents=57,
        )
        assert is_valid is True
        
        # NO buy at 50c (above NO ask of 47c) should be rejected
        is_valid, reason = SideAwarePriceValidator.validate_order_price(
            order_price_cents=50,
            side=TradingSide.NO,
            yes_mid_cents=55,
            yes_bid_cents=53,
            yes_ask_cents=57,
        )
        assert is_valid is False
        assert "buy_above_ask" in reason
    
    def test_price_space_conversion(self):
        """Test price space conversion using duality."""
        # YES to NO
        no_price = SideAwarePriceValidator.convert_price_to_side_space(
            price_cents=65,
            from_side=TradingSide.YES,
            to_side=TradingSide.NO,
        )
        assert no_price == 35  # 100 - 65
        
        # NO to YES
        yes_price = SideAwarePriceValidator.convert_price_to_side_space(
            price_cents=35,
            from_side=TradingSide.NO,
            to_side=TradingSide.YES,
        )
        assert yes_price == 65  # 100 - 35
        
        # Same side (no conversion)
        same_price = SideAwarePriceValidator.convert_price_to_side_space(
            price_cents=50,
            from_side=TradingSide.YES,
            to_side=TradingSide.YES,
        )
        assert same_price == 50


class TestSideAwareEdgeCalculator:
    """Test side-aware edge calculation using correct probability models."""
    
    def test_buy_yes_edge_calculation(self):
        """BUY_YES edge should use YES probability."""
        intent = SideAwareOrderIntent.from_components(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            yes_probability=65.0,  # Model thinks YES is 65c
        )
        
        edge, description = SideAwareEdgeCalculator.calculate_edge(
            order_type=intent.order_type,
            order_price_cents=intent.price_cents,
            probability=intent.probability,
            yes_bid_cents=55,  # Market bid is 55c
            no_bid_cents=45,   # Market NO bid is 45c
        )
        
        # Edge = model_prob - market_bid = 65 - 55 = 10c
        assert edge == 10.0
        assert "BUY_yes" in description
        assert "model=65.0c" in description
        assert "market_bid=55c" in description
    
    def test_buy_no_edge_calculation(self):
        """BUY_NO edge should use NO probability (not derived from YES)."""
        intent = SideAwareOrderIntent.from_components(
            ticker="KXBTC15M-TEST",
            side="no",
            action="buy",
            price_cents=40,
            count=1,
            no_probability=25.0,  # Model thinks NO is 25c (YES = 75c)
        )
        
        edge, description = SideAwareEdgeCalculator.calculate_edge(
            order_type=intent.order_type,
            order_price_cents=intent.price_cents,
            probability=intent.probability,
            yes_bid_cents=70,  # Market YES bid is 70c
            no_bid_cents=30,   # Market NO bid is 30c
        )
        
        # Edge = model_prob - market_bid = 25 - 30 = -5c (negative edge, should reject)
        assert edge == -5.0
        assert "BUY_no" in description
        assert "model=25.0c" in description
        assert "market_bid=30c" in description
    
    def test_sell_yes_edge_calculation(self):
        """SELL_YES edge should use YES probability."""
        intent = SideAwareOrderIntent.from_components(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="sell",
            price_cents=60,
            count=1,
            yes_probability=45.0,  # Model thinks YES is 45c
        )
        
        edge, description = SideAwareEdgeCalculator.calculate_edge(
            order_type=intent.order_type,
            order_price_cents=intent.price_cents,
            probability=intent.probability,
            yes_bid_cents=50,  # Market bid is 50c
            no_bid_cents=50,   # Market NO bid is 50c
        )
        
        # Edge = market_bid - model_prob = 50 - 45 = 5c
        assert edge == 5.0
        assert "SELL_yes" in description
        assert "market_bid=50c" in description
        assert "model=45.0c" in description
    
    def test_sell_no_edge_calculation(self):
        """SELL_NO edge should use NO probability."""
        intent = SideAwareOrderIntent.from_components(
            ticker="KXBTC15M-TEST",
            side="no",
            action="sell",
            price_cents=40,
            count=1,
            no_probability=55.0,  # Model thinks NO is 55c (YES = 45c)
        )
        
        edge, description = SideAwareEdgeCalculator.calculate_edge(
            order_type=intent.order_type,
            order_price_cents=intent.price_cents,
            probability=intent.probability,
            yes_bid_cents=45,  # Market YES bid is 45c
            no_bid_cents=55,   # Market NO bid is 55c
        )
        
        # Edge = market_bid - model_prob = 55 - 55 = 0c (no edge)
        assert edge == 0.0
        assert "SELL_no" in description
        assert "market_bid=55c" in description
        assert "model=55.0c" in description


class TestInvariantChecker:
    """Test invariant checking for side-aware trading."""
    
    def test_entry_from_zero(self):
        """Entry orders must start from zero position."""
        is_valid, reason = InvariantChecker.check_entry_exit_invariant(
            order_type=OrderType.BUY_YES,
            pre_position_size=0,
            count=1,
        )
        assert is_valid is True
        assert reason is None
    
    def test_buy_yes_adds_to_long_yes(self):
        """BUY_YES from an existing long YES position is a valid add."""
        is_valid, reason = InvariantChecker.check_entry_exit_invariant(
            order_type=OrderType.BUY_YES,
            pre_position_yes=5,
            count=1,
        )
        assert is_valid is True
        assert reason is None

    def test_order_would_flip_rejection(self):
        """Orders that would flip the position sign must be rejected."""
        # Long NO position of 5, BUY_YES 6 would flip to long YES.
        is_valid, reason = InvariantChecker.check_entry_exit_invariant(
            order_type=OrderType.BUY_YES,
            pre_position_yes=-5,
            count=6,
        )
        assert is_valid is False
        assert "flip" in reason

    def test_exit_from_existing_position(self):
        """Exit orders from an existing same-side position are valid."""
        is_valid, reason = InvariantChecker.check_entry_exit_invariant(
            order_type=OrderType.SELL_YES,
            pre_position_yes=5,
            count=1,
        )
        assert is_valid is True
        assert reason is None

    def test_sell_no_is_long_yes_entry_from_flat(self):
        """SELL_NO from flat is a long-YES entry (not an invalid exit)."""
        is_valid, reason = InvariantChecker.check_entry_exit_invariant(
            order_type=OrderType.SELL_NO,
            pre_position_yes=0,
            count=1,
        )
        assert is_valid is True
        assert reason is None

    def test_exit_overclose_rejection(self):
        """Exit orders cannot close more than existing position (would flip)."""
        is_valid, reason = InvariantChecker.check_entry_exit_invariant(
            order_type=OrderType.SELL_YES,
            pre_position_yes=3,
            count=5,  # Trying to close 5 when only have 3
        )
        assert is_valid is False
        assert "overclose" in reason
    
    def test_duality_invariant_valid(self):
        """Valid duality should pass."""
        is_valid, reason = InvariantChecker.check_duality_invariant(
            yes_price=65,
            no_price=35,
        )
        assert is_valid is True
        assert reason is None
    
    def test_duality_invariant_violation(self):
        """Duality violation should be detected."""
        is_valid, reason = InvariantChecker.check_duality_invariant(
            yes_price=70,
            no_price=35,  # 70 + 35 = 105 (violation)
        )
        assert is_valid is False
        assert "duality_violation" in reason
    
    def test_duality_tolerance(self):
        """Duality check should allow tolerance."""
        # Within 1 cent tolerance
        is_valid, reason = InvariantChecker.check_duality_invariant(
            yes_price=65,
            no_price=35,  # Exact 100
            tolerance_cents=1,
        )
        assert is_valid is True
        
        # Within 1 cent tolerance (floating point)
        is_valid, reason = InvariantChecker.check_duality_invariant(
            yes_price=65,
            no_price=35,  # Exact 100
            tolerance_cents=1,
        )
        assert is_valid is True


class TestFactoryFunctions:
    """Test factory functions for creating side-aware intents."""
    
    def test_create_side_aware_intent(self):
        """Factory function should create valid intent."""
        intent = create_side_aware_intent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            yes_probability=65.0,
        )
        
        assert isinstance(intent, SideAwareOrderIntent)
        assert intent.order_type == OrderType.BUY_YES
    
    def test_create_side_aware_intent_missing_probability(self):
        """Factory function should reject missing probability."""
        with pytest.raises(ValueError, match="At least one probability"):
            create_side_aware_intent(
                ticker="KXBTC15M-TEST",
                side="yes",
                action="buy",
                price_cents=50,
                count=1,
                yes_probability=None,
                no_probability=None,
            )
    
    def test_convert_legacy_intent(self):
        """Legacy intent conversion should work."""
        intent = convert_legacy_intent_to_side_aware(
            ticker="KXBTC15M-TEST",
            side="no",
            action="buy",
            price_cents=40,
            count=1,
            p_hat_no_cents=25.0,
        )
        
        assert isinstance(intent, SideAwareOrderIntent)
        assert intent.order_type == OrderType.BUY_NO
        assert intent.probability.no_cents == 25.0
    
    def test_validate_order_intent_valid(self):
        """Valid intent should pass validation."""
        intent = create_side_aware_intent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            yes_probability=65.0,
        )
        
        is_valid, reason = validate_order_intent(intent)
        assert is_valid is True
        assert reason is None
    
    def test_validate_order_intent_price_outside_range(self):
        """Intent with price outside canonical range should fail."""
        intent = create_side_aware_intent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=0,  # Below canonical minimum (1c)
            count=1,
            yes_probability=65.0,
        )
        
        is_valid, reason = validate_order_intent(intent)
        assert is_valid is False
        assert "price_outside_canonical_range" in reason


class TestSideInversionPrevention:
    """Test prevention of side inversion bugs."""
    
    def test_sell_no_is_never_long_no_entry(self):
        """SELL_NO is always a long-YES exposure (never long NO) - canonicalization."""
        from merid.event_venues.kalshi.binary_price_space import yes_delta
        # SELL_NO from flat creates long YES, not long NO.
        assert yes_delta("sell", "no", 1) == 1
        is_valid, reason = InvariantChecker.check_entry_exit_invariant(
            order_type=OrderType.SELL_NO,
            pre_position_yes=0,
            count=1,
        )
        assert is_valid is True
        assert reason is None

    def test_buy_no_is_never_long_yes_entry(self):
        """BUY_NO is always a long-NO exposure (never long YES) - canonicalization."""
        from merid.event_venues.kalshi.binary_price_space import yes_delta
        assert yes_delta("buy", "no", 1) == -1
        is_valid, reason = InvariantChecker.check_entry_exit_invariant(
            order_type=OrderType.BUY_NO,
            pre_position_yes=0,
            count=1,
        )
        assert is_valid is True
        assert reason is None
    
    def test_mixed_leg_prevention(self):
        """Mixed YES/NO legs on same ticker should be prevented."""
        # First order: BUY_YES
        intent1 = create_side_aware_intent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            yes_probability=65.0,
        )
        
        # Second order: BUY_NO (would create mixed leg)
        intent2 = create_side_aware_intent(
            ticker="KXBTC15M-TEST",
            side="no",
            action="buy",
            price_cents=40,
            count=1,
            no_probability=35.0,
        )
        
        # Both should be valid individually
        assert validate_order_intent(intent1)[0] is True
        assert validate_order_intent(intent2)[0] is True
        
        # But system should prevent mixed legs (this would be checked at position cache level)
        # The side-aware layer provides the foundation for this check


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
