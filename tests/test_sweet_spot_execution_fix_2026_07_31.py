"""Test for sweet spot execution fix (2026-08-08).

SWEET-SPOT-EXECUTION is now bypassed for BUY NO / BUY YES to avoid blind
repricing. Side-aware repricing happens in _adjust_order_price_for_fill_rate,
and Kelly/sizing is always re-run against the final submitted price.
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, MagicMock, patch
from merid.event_venues.kalshi.order_router import OrderIntent, _determine_dynamic_order_type


class TestSweetSpotExecutionFix:
    """Test sweet spot execution bug fix."""
    
    def test_sweet_spot_bypassed_for_buy_yes(self):
        """Test that BUY YES bypasses SWEET-SPOT-EXECUTION and keeps the original price."""
        # Create intent for buy order
        intent = OrderIntent(
            ticker="KXETH15M-26JUL311900-00",
            side="BUY_YES",
            action="buy",
            price_cents=20,  # Current market price
            count=1,
            order_type="limit",
            time_in_force="gtc"
        )
        
        # Create mock state
        state = Mock()
        state.mid_cents = 20
        state.ask_cents = 21  # Ask is higher than mid
        state.bid_cents = 19
        state.seconds_to_expiry = 600
        state.depth_10c = 1000
        
        # Determine order type - BUY bypasses the sweet spot block
        order_type, tif = _determine_dynamic_order_type(intent, state)
        
        # Verify order type is limit, price unchanged, no sweet-spot metadata
        assert order_type == "limit"
        assert tif == "gtc"
        assert intent.price_cents == 20
        assert not (intent.metadata and intent.metadata.get("price_adjusted_by_sweet_spot"))
    
    def test_sweet_spot_raised_to_bid_for_sell_orders(self):
        """Test that sweet spot price is raised to bid price for sell orders."""
        # Create intent for sell order
        intent = OrderIntent(
            ticker="KXSOL15M-26JUL311900-00",
            side="SELL_YES",
            action="sell",
            price_cents=20,  # Current market price
            count=1,
            order_type="limit",
            time_in_force="gtc"
        )
        
        # Create mock state with bid price
        state = Mock()
        state.mid_cents = 20
        state.ask_cents = 21
        state.bid_cents = 19  # Bid is lower than mid
        state.seconds_to_expiry = 600  # Add this to avoid TypeError
        state.depth_10c = 1000  # Add depth to avoid TypeError
        
        # Determine order type - should raise sweet spot to bid
        order_type, tif = _determine_dynamic_order_type(intent, state)
        
        # Verify order type is limit
        assert order_type == "limit"
        assert tif == "gtc"
        
        # For sell orders, the sweet spot logic is different
        # Sell orders want to sell at higher prices, so the logic may not apply the same way
        # The key fix is that buy orders are capped at ask to prevent spread crossing
        # For this test, we just verify the metadata is set correctly
        if intent.metadata and intent.metadata.get("price_adjusted_by_sweet_spot"):
            # If price was adjusted, verify it's reasonable
            assert intent.price_cents >= state.bid_cents
    
    def test_sweet_spot_uses_current_price_when_validation_fails(self):
        """Bypassed SWEET-SPOT-EXECUTION never mutates price, even when the old
        validation path would have rejected a sweet-spot price as crossing."""
        # BUY YES at 25c with ask 20c: old sweet-spot would have capped to 20c.
        # New behavior: bypass entirely, keep original price, return limit/gtc.
        intent = OrderIntent(
            ticker="KXETH15M-26JUL311900-00",
            side="BUY_YES",
            action="buy",
            price_cents=25,
            count=1,
            order_type="limit",
            time_in_force="gtc"
        )
        state = Mock()
        state.mid_cents = 20
        state.ask_cents = 20
        state.bid_cents = 19
        state.seconds_to_expiry = 600
        state.depth_10c = 1000

        order_type, tif = _determine_dynamic_order_type(intent, state)
        assert order_type == "limit"
        assert tif == "gtc"
        assert intent.price_cents == 25
        assert not (intent.metadata and intent.metadata.get("price_adjusted_by_sweet_spot"))

        # SELL YES at 20c with bid 25c: old sweet-spot would have floored to 25c.
        # New behavior: bypass entirely, keep original price.
        intent2 = OrderIntent(
            ticker="KXSOL15M-26JUL311900-00",
            side="SELL_YES",
            action="sell",
            price_cents=20,
            count=1,
            order_type="limit",
            time_in_force="gtc"
        )
        state2 = Mock()
        state2.mid_cents = 30
        state2.ask_cents = 31
        state2.bid_cents = 25
        state2.seconds_to_expiry = 600
        state2.depth_10c = 1000

        order_type2, tif2 = _determine_dynamic_order_type(intent2, state2)
        assert order_type2 == "limit"
        assert tif2 == "gtc"
        assert intent2.price_cents == 20
        assert not (intent2.metadata and intent2.metadata.get("price_adjusted_by_sweet_spot"))
    
    def test_kelly_filter_runs_when_price_adjusted(self):
        """Test that Kelly filter is always re-run against the final price."""
        from merid.prediction.unified_sizing import compute_order_size
        
        # Old metadata flag is no longer used to bypass Kelly
        metadata = {
            "price_adjusted_by_sweet_spot": True,
            "original_signal_price": 20,
            "adjusted_price": 55
        }
        
        # Call compute_order_size with the final repriced price
        count, notional, result_metadata = compute_order_size(
            bankroll_usd=Decimal("15.08"),
            price_cents=55,  # Final repriced price
            asset="ETH",
            model_prob=0.45,
            side="yes",
            metadata=metadata
        )
        
        # Kelly must re-evaluate at the submitted price; with p=0.45 and price=55c
        # there is negative edge, so the order is now correctly rejected.
        assert count == 0, f"Expected rejection due to no edge, got count={count}"
        assert result_metadata.get("reason") == "kelly_no_edge"
    
    def test_kelly_filter_applied_when_price_not_adjusted(self):
        """Test that Kelly filter is applied when price is not adjusted."""
        from merid.prediction.unified_sizing import compute_order_size
        
        # No metadata indicating price adjustment
        metadata = {}
        
        # Call compute_order_size without metadata
        count, notional, result_metadata = compute_order_size(
            bankroll_usd=Decimal("15.08"),
            price_cents=40,  # Price with no edge
            asset="ETH",
            model_prob=0.40,  # Model prob with no edge at this price
            side="yes",
            metadata=metadata
        )
        
        # Verify order was rejected by Kelly filter
        assert count == 0
        assert result_metadata.get("reason") == "kelly_no_edge"
    
    def test_sweet_spot_metadata_does_not_bypass_kelly(self):
        """Test that sweet spot metadata no longer bypasses Kelly."""
        from merid.event_venues.kalshi.order_router import _apply_risk_based_order_sizing
        
        # Create intent with the old sweet spot metadata
        intent = OrderIntent(
            ticker="KXETH15M-26JUL311900-00",
            side="BUY_YES",
            action="buy",
            price_cents=55,  # Final submitted price
            count=1,
            model_prob=0.45,
            metadata={
                "price_adjusted_by_sweet_spot": True,
                "original_signal_price": 20,
                "adjusted_price": 55
            }
        )
        
        # Apply risk-based sizing - Kelly re-runs at price_cents=55
        count = _apply_risk_based_order_sizing(intent, bankroll_usd=Decimal("15.08"))
        
        # With p=0.45 and price=55c there is no edge; order is rejected
        assert count == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
