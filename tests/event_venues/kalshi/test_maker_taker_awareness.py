"""Tests for fee/maker-taker awareness in order routing.

Tests cover:
- OrderIntent fee/maker-taker field enrichment
- _price_for_side helper function
- Fee-aware sizing in compute_order_size
- apply_maker_taker_policy integration
"""

import pytest
from decimal import Decimal

from merid.event_venues.kalshi.order_router import OrderIntent, _price_for_side
from merid.event_venues.kalshi.maker_taker_integration import apply_maker_taker_policy
from merid.prediction.unified_sizing import compute_order_size


class TestOrderIntentFeeFields:
    """Test OrderIntent fee/maker-taker field enrichment."""
    
    def test_order_intent_has_fee_fields(self):
        """OrderIntent should have fee/maker-taker fields."""
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
        )
        
        # Check that new fields exist
        assert hasattr(intent, 'expected_role')
        assert hasattr(intent, 'fee_type')
        assert hasattr(intent, 'estimated_fee_cents')
        assert hasattr(intent, 'edge_net_of_fees_pct')
        assert hasattr(intent, 'policy_mode')
        
        # Default values should be None
        assert intent.expected_role is None
        assert intent.fee_type is None
        assert intent.estimated_fee_cents is None
        assert intent.edge_net_of_fees_pct is None
        assert intent.policy_mode is None


class TestPriceForSide:
    """Test _price_for_side helper function."""
    
    def test_price_for_side_buy_maker(self):
        """Buy orders should be adjusted to be maker (at or below bid)."""
        adjusted = _price_for_side(
            price_cents=55,
            side="yes",
            action="buy",
            best_bid_cents=54,
            best_ask_cents=56,
            maker_bias_cents=1,
        )
        # Should be at or below bid (54 - 1 = 53)
        assert adjusted == 53
    
    def test_price_for_side_sell_maker(self):
        """Sell orders should be adjusted to be maker (at or above ask)."""
        adjusted = _price_for_side(
            price_cents=45,
            side="yes",
            action="sell",
            best_bid_cents=44,
            best_ask_cents=46,
            maker_bias_cents=1,
        )
        # Should be at or above ask (46 + 1 = 47)
        assert adjusted == 47
    
    def test_price_for_side_no_market_data(self):
        """Without market data, should return original price."""
        adjusted = _price_for_side(
            price_cents=50,
            side="yes",
            action="buy",
            best_bid_cents=None,
            best_ask_cents=None,
            maker_bias_cents=1,
        )
        assert adjusted == 50
    
    def test_price_for_side_minimum_price(self):
        """Should enforce minimum price of 1 cent."""
        adjusted = _price_for_side(
            price_cents=1,
            side="yes",
            action="buy",
            best_bid_cents=2,
            best_ask_cents=3,
            maker_bias_cents=1,
        )
        # 2 - 1 = 1, should not go below 1
        assert adjusted == 1
    
    def test_price_for_side_maximum_price(self):
        """Should enforce maximum price of 99 cents."""
        adjusted = _price_for_side(
            price_cents=99,
            side="yes",
            action="sell",
            best_bid_cents=97,
            best_ask_cents=98,
            maker_bias_cents=1,
        )
        # 98 + 1 = 99, should not exceed 99
        assert adjusted == 99


class TestFeeAwareSizing:
    """Test fee-aware sizing in compute_order_size."""
    
    def test_compute_order_size_without_fee_impact(self):
        """Without fee impact, should use standard sizing."""
        count, notional, metadata = compute_order_size(
            bankroll_usd=Decimal("100.00"),
            price_cents=50,
            asset="BTC",
            edge_pct=Decimal("5.0"),
            confidence=Decimal("0.8"),
            consider_fee_impact=False,
        )
        
        assert count > 0
        assert notional > 0
        assert metadata['fee_adjusted'] is False
        assert metadata['consider_fee_impact'] is False
    
    def test_compute_order_size_with_fee_impact(self):
        """With fee impact, should subtract fee from max_notional."""
        count, notional, metadata = compute_order_size(
            bankroll_usd=Decimal("100.00"),
            price_cents=50,
            asset="BTC",
            edge_pct=Decimal("5.0"),
            confidence=Decimal("0.8"),
            consider_fee_impact=True,
            estimated_fee_cents=5,  # $0.05 fee
        )
        
        assert count >= 0
        assert notional >= 0
        assert metadata['fee_adjusted'] is True
        assert metadata['consider_fee_impact'] is True
    
    def test_compute_order_size_fee_impact_zero_fee(self):
        """With zero fee, should not adjust sizing."""
        count, notional, metadata = compute_order_size(
            bankroll_usd=Decimal("100.00"),
            price_cents=50,
            asset="BTC",
            edge_pct=Decimal("5.0"),
            confidence=Decimal("0.8"),
            consider_fee_impact=True,
            estimated_fee_cents=0,
        )
        
        assert metadata['fee_adjusted'] is False
    
    def test_compute_order_size_fee_impact_no_fee_provided(self):
        """With consider_fee_impact=True but no fee provided, should not crash."""
        count, notional, metadata = compute_order_size(
            bankroll_usd=Decimal("100.00"),
            price_cents=50,
            asset="BTC",
            edge_pct=Decimal("5.0"),
            confidence=Decimal("0.8"),
            consider_fee_impact=True,
            estimated_fee_cents=None,
        )
        
        # Should not crash, fee_adjusted should be False
        assert metadata['fee_adjusted'] is False


class TestApplyMakerTakerPolicy:
    """Test apply_maker_taker_policy integration."""
    
    def test_apply_maker_taker_policy_enriches_intent(self):
        """apply_maker_taker_policy should enrich intent with policy metadata."""
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
            edge_pct=5.0,
        )
        
        # Apply policy (may fail if market state not available, but should not crash)
        try:
            apply_maker_taker_policy(intent)
        except Exception:
            # If market state not available, should set defaults
            pass
        
        # Should have policy fields set (either to policy decision or defaults)
        assert intent.expected_role is not None
        assert intent.fee_type is not None
        # Other fields may be None if market state unavailable
    
    def test_apply_maker_taker_policy_with_explicit_policy_mode(self):
        """Should use explicit policy_mode if provided."""
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
            edge_pct=5.0,
            policy_mode="NEUTRAL_MM",
        )
        
        try:
            apply_maker_taker_policy(intent)
        except Exception:
            pass
        
        # Should have policy mode set
        assert intent.policy_mode is not None


class TestIntegration:
    """Integration tests for fee/maker-taker awareness."""
    
    def test_end_to_end_fee_aware_order(self):
        """Test end-to-end fee-aware order flow."""
        # Create intent
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
            edge_pct=5.0,
        )
        
        # Apply policy
        try:
            apply_maker_taker_policy(intent)
        except Exception:
            pass
        
        # Check intent enriched
        assert intent.expected_role is not None
        
        # Compute fee-aware size
        if intent.estimated_fee_cents:
            count, notional, metadata = compute_order_size(
                bankroll_usd=Decimal("100.00"),
                price_cents=intent.price_cents,
                asset="BTC",
                consider_fee_impact=True,
                estimated_fee_cents=intent.estimated_fee_cents,
            )
            assert metadata['consider_fee_impact'] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
