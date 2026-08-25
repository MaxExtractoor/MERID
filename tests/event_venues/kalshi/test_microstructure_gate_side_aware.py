"""Unit tests for side-aware microstructure gate.

Tests the CRITICAL FIX (2026-07-24) that ensures the microstructure gate
only checks spread for the order's side, not both sides. This prevents
NO-side orders from being rejected due to YES spread being too wide.
"""

import pytest
from merid.event_venues.kalshi.order_router import check_market_microstructure


class TestSideAwareMicrostructureGate:
    """Test side-aware microstructure gate validation."""
    
    def test_yes_side_trade_with_yes_spread_within_threshold(self):
        """YES side trade with YES spread within threshold → ALLOW."""
        # YES spread = 15c (within 20c threshold)
        # NO spread = 53c (exceeds threshold, but should not matter for YES order)
        passes, reason = check_market_microstructure(
            yes_bid_cents=40,
            yes_ask_cents=55,  # YES spread = 15c
            no_bid_cents=20,
            no_ask_cents=73,  # NO spread = 53c (too wide)
            yes_depth=15,
            no_depth=15,  # Total = 30 >= 25
            order_side="yes",
            max_spread_cents=20.0,
            min_depth_usd=0.0,  # Disabled for 15m crypto (uses limit orders)
            min_yes_depth=1,
            min_no_depth=1,
            min_total_depth=25
        )
        
        assert passes is True
        assert reason == "ok"
    
    def test_yes_side_trade_with_yes_spread_too_wide(self):
        """YES side trade with YES spread too wide → REJECT."""
        # YES spread = 53c (exceeds 20c threshold)
        passes, reason = check_market_microstructure(
            yes_bid_cents=20,
            yes_ask_cents=73,  # YES spread = 53c
            no_bid_cents=40,
            no_ask_cents=55,  # NO spread = 15c (OK)
            yes_depth=15,
            no_depth=15,  # Total = 30 >= 25
            order_side="yes",
            max_spread_cents=20.0,
            min_depth_usd=0.0,  # Disabled for 15m crypto (uses limit orders)
            min_yes_depth=1,
            min_no_depth=1,
            min_total_depth=25
        )
        
        assert passes is False
        assert "yes_spread_too_wide" in reason
        assert "53c" in reason
    
    def test_no_side_trade_with_no_spread_ok_yes_spread_wide(self):
        """NO side trade with NO spread OK but YES spread too wide → ALLOW.
        
        This is the critical bug fix scenario from the logs:
        - BUY_NO order was rejected due to "yes_spread_too_wide: 53c > 20c"
        - After fix, NO orders should only check NO spread
        """
        # YES spread = 53c (exceeds threshold)
        # NO spread = 15c (within threshold)
        passes, reason = check_market_microstructure(
            yes_bid_cents=20,
            yes_ask_cents=73,  # YES spread = 53c (too wide)
            no_bid_cents=40,
            no_ask_cents=55,  # NO spread = 15c (OK)
            yes_depth=15,
            no_depth=15,  # Total = 30 >= 25
            order_side="no",  # CRITICAL: Order is on NO side
            max_spread_cents=20.0,
            min_depth_usd=0.0,  # Disabled for 15m crypto (uses limit orders)
            min_yes_depth=1,
            min_no_depth=1,
            min_total_depth=25
        )
        
        # Should PASS because we only check NO spread for NO orders
        assert passes is True
        assert reason == "ok"
    
    def test_no_side_trade_with_no_spread_too_wide(self):
        """NO side trade with NO spread too wide → REJECT."""
        # NO spread = 53c (exceeds 20c threshold)
        passes, reason = check_market_microstructure(
            yes_bid_cents=40,
            yes_ask_cents=55,  # YES spread = 15c (OK)
            no_bid_cents=20,
            no_ask_cents=73,  # NO spread = 53c (too wide)
            yes_depth=15,
            no_depth=15,  # Total = 30 >= 25
            order_side="no",
            max_spread_cents=20.0,
            min_depth_usd=0.0,  # Disabled for 15m crypto (uses limit orders)
            min_yes_depth=1,
            min_no_depth=1,
            min_total_depth=25
        )
        
        assert passes is False
        assert "no_spread_too_wide" in reason
        assert "53c" in reason
    
    def test_one_sided_liquidity_yes_sufficient(self):
        """One-sided liquidity: YES side has sufficient depth but NO side fails min depth → REJECT."""
        passes, reason = check_market_microstructure(
            yes_bid_cents=40,
            yes_ask_cents=55,
            no_bid_cents=0,  # NO side illiquid
            no_ask_cents=0,
            yes_depth=50,  # YES side has depth
            no_depth=0,    # NO side has no depth
            order_side="yes",
            max_spread_cents=20.0,
            min_depth_usd=0.0,  # Disabled for 15m crypto (uses limit orders)
            min_yes_depth=1,
            min_no_depth=1,
            min_total_depth=25
        )
        
        # Should fail NO depth check (min_no_depth=1, but no_depth=0)
        # This is correct - we require minimum depth on both sides for market health
        assert passes is False
        assert "no_depth_too_low" in reason
    
    def test_one_sided_liquidity_no_sufficient(self):
        """One-sided liquidity: NO side has sufficient depth but YES side fails min depth → REJECT."""
        passes, reason = check_market_microstructure(
            yes_bid_cents=40,
            yes_ask_cents=55,
            no_bid_cents=60,
            no_ask_cents=75,
            yes_depth=0,    # YES side has no depth
            no_depth=50,   # NO side has depth
            order_side="no",
            max_spread_cents=20.0,
            min_depth_usd=0.0,  # Disabled for 15m crypto (uses limit orders)
            min_yes_depth=1,
            min_no_depth=1,
            min_total_depth=25
        )
        
        # Should fail YES depth check (min_yes_depth=1, but yes_depth=0)
        # This is correct - we require minimum depth on both sides for market health
        assert passes is False
        assert "yes_depth_too_low" in reason
    
    def test_total_depth_too_low(self):
        """Total depth (yes + no) too low → REJECT regardless of side."""
        passes, reason = check_market_microstructure(
            yes_bid_cents=40,
            yes_ask_cents=55,
            no_bid_cents=60,
            no_ask_cents=75,
            yes_depth=10,
            no_depth=10,  # Total = 20 < 25 threshold
            order_side="yes",
            max_spread_cents=20.0,
            min_depth_usd=0.0,  # Disabled for 15m crypto (uses limit orders)
            min_yes_depth=1,
            min_no_depth=1,
            min_total_depth=25
        )
        
        assert passes is False
        assert "total_depth_too_low" in reason
    
    def test_yes_depth_too_low(self):
        """YES depth too low → REJECT."""
        passes, reason = check_market_microstructure(
            yes_bid_cents=40,
            yes_ask_cents=55,
            no_bid_cents=60,
            no_ask_cents=75,
            yes_depth=0,  # Below min_yes_depth=1
            no_depth=50,
            order_side="yes",
            max_spread_cents=20.0,
            min_depth_usd=0.0,  # Disabled for 15m crypto (uses limit orders)
            min_yes_depth=1,
            min_no_depth=1,
            min_total_depth=25
        )
        
        assert passes is False
        assert "yes_depth_too_low" in reason
    
    def test_no_depth_too_low(self):
        """NO depth too low → REJECT."""
        passes, reason = check_market_microstructure(
            yes_bid_cents=40,
            yes_ask_cents=55,
            no_bid_cents=60,
            no_ask_cents=75,
            yes_depth=50,
            no_depth=0,  # Below min_no_depth=1
            order_side="no",
            max_spread_cents=20.0,
            min_depth_usd=0.0,  # Disabled for 15m crypto (uses limit orders)
            min_yes_depth=1,
            min_no_depth=1,
            min_total_depth=25
        )
        
        assert passes is False
        assert "no_depth_too_low" in reason
    
    def test_invalid_order_side_fallback(self):
        """Invalid order_side triggers fallback to check both spreads."""
        # Both spreads OK
        passes, reason = check_market_microstructure(
            yes_bid_cents=40,
            yes_ask_cents=55,
            no_bid_cents=60,
            no_ask_cents=75,
            yes_depth=15,
            no_depth=15,  # Total = 30 >= 25
            order_side="invalid",  # Invalid side
            max_spread_cents=20.0,
            min_depth_usd=0.0,  # Disabled for 15m crypto (uses limit orders)
            min_yes_depth=1,
            min_no_depth=1,
            min_total_depth=25
        )
        
        # Should still pass (both spreads OK)
        assert passes is True
    
    def test_invalid_order_side_fallback_reject(self):
        """Invalid order_side with YES spread too wide → REJECT via fallback."""
        passes, reason = check_market_microstructure(
            yes_bid_cents=20,
            yes_ask_cents=73,  # YES spread = 53c (too wide)
            no_bid_cents=40,
            no_ask_cents=55,  # NO spread = 15c (OK)
            yes_depth=10,
            no_depth=10,
            order_side="invalid",  # Invalid side
            max_spread_cents=20.0,
            min_depth_usd=0.0,  # Disabled for 15m crypto (uses limit orders)
            min_yes_depth=1,
            min_no_depth=1,
            min_total_depth=25
        )
        
        # Should reject via fallback (checks both spreads)
        assert passes is False
        assert "yes_spread_too_wide" in reason
    
    def test_both_spreads_equal_threshold(self):
        """Spread exactly at threshold should pass."""
        passes, reason = check_market_microstructure(
            yes_bid_cents=40,
            yes_ask_cents=60,  # YES spread = 20c (exactly at threshold)
            no_bid_cents=40,
            no_ask_cents=60,  # NO spread = 20c (exactly at threshold)
            yes_depth=15,
            no_depth=15,  # Total = 30 >= 25
            order_side="yes",
            max_spread_cents=20.0,
            min_depth_usd=0.0,  # Disabled for 15m crypto (uses limit orders)
            min_yes_depth=1,
            min_no_depth=1,
            min_total_depth=25
        )
        
        assert passes is True
        assert reason == "ok"
    
    def test_spread_one_cent_over_threshold(self):
        """Spread one cent over threshold should reject."""
        passes, reason = check_market_microstructure(
            yes_bid_cents=40,
            yes_ask_cents=61,  # YES spread = 21c (1c over threshold)
            no_bid_cents=40,
            no_ask_cents=60,
            yes_depth=10,
            no_depth=10,
            order_side="yes",
            max_spread_cents=20.0,
            min_depth_usd=0.0,  # Disabled for 15m crypto (uses limit orders)
            min_yes_depth=1,
            min_no_depth=1,
            min_total_depth=25
        )
        
        assert passes is False
        assert "yes_spread_too_wide" in reason
        assert "21c" in reason


class TestMicrostructureGateRegression:
    """Regression tests for the bug fix.
    
    These tests ensure the specific bug scenario from the logs is fixed:
    - ticker=KXBTC15M-26JUL241045-45
    - side=BUY_NO
    - Rejected with: yes_spread_too_wide: 53c > 20c
    - Expected: Should PASS if NO spread is within threshold
    """
    
    def test_btc_15m_no_order_bug_scenario(self):
        """Test the exact bug scenario from the logs.
        
        Log snippet:
        2026-07-24 10:34:47 | WARNING | merid.event_venues.kalshi.order_router | 
        [MICROSTRUCTURE-GATE] ticker=KXBTC15M-26JUL241045-45 yes_spread_too_wide: 53c > 20c
        
        This was a BUY_NO order rejected due to YES spread being too wide.
        After the fix, NO orders should only check NO spread.
        """
        # Simulate the market conditions from the log
        # YES spread = 53c (too wide)
        # NO spread = assume it was within threshold (e.g., 15c)
        passes, reason = check_market_microstructure(
            yes_bid_cents=20,
            yes_ask_cents=73,  # YES spread = 53c
            no_bid_cents=40,
            no_ask_cents=55,  # NO spread = 15c (assumed OK)
            yes_depth=15,
            no_depth=15,  # Total = 30 >= 25
            order_side="no",  # BUY_NO order
            max_spread_cents=20.0,
            min_depth_usd=0.0,  # Disabled for 15m crypto (uses limit orders)
            min_yes_depth=1,
            min_no_depth=1,
            min_total_depth=25
        )
        
        # CRITICAL: This should now PASS (was failing before fix)
        assert passes is True, f"Expected PASS for NO order with OK NO spread, got: {reason}"
        assert reason == "ok"
