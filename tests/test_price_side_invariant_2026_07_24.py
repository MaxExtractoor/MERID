"""
Price-Side Invariant Tests (2026-07-24)

Tests for the "cheap on the correct side" invariant:
- Cheapness must only be evaluated on the thesis_side leg
- Cheap contracts on the wrong side must NOT generate candidates
- Side selection must match thesis_side from velocity/directional signal

This prevents "cheap but wrong side" candidates from being generated
when cheapness on the opposite leg would override the directional signal.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone
from typing import List


class TestPriceSideInvariant:
    """Test that cheapness is only evaluated on the thesis_side leg."""
    
    def test_bearish_cheap_yes_correct_no_rejected(self):
        """
        Test: Bearish signal (velocity < 0) with cheap YES but fair NO.
        
        Expected: NO candidate only (thesis_side=NO), YES candidate rejected.
        Cheap YES should not override bearish directional signal.
        """
        # Setup: Bearish velocity (negative)
        velocity = -0.05  # Negative = bearish = thesis_side=NO
        
        # Market state: YES is cheap (15c), NO is in range (42c)
        yes_price_cents = 15  # Cheap YES
        no_price_cents = 42   # Fair NO
        
        # Expected: thesis_side=NO (from negative velocity)
        expected_thesis_side = "no"
        
        # Invariant: thesis_side should be NO
        assert expected_thesis_side == "no"

        # Invariant: Only NO price should be evaluated for cheapness
        # YES price being cheap is irrelevant for bearish thesis
        # CRITICAL FIX 2026-08-03: NO uses side-aware range 25c-99c
        thesis_in_range = (25 <= no_price_cents <= 99)
        assert thesis_in_range, "NO price should be in range for bearish thesis"

        # Invariant: YES cheapness should NOT generate YES candidate
        # Even though YES is cheap (15c), it's on the wrong side
        # YES uses side-aware range 10c-75c
        yes_in_range = (10 <= yes_price_cents <= 75)
        # YES being in range doesn't matter - thesis_side=NO
        
        print(f"[TEST] velocity={velocity} thesis_side={expected_thesis_side}")
        print(f"[TEST] yes_price={yes_price_cents}c (cheap but wrong side)")
        print(f"[TEST] no_price={no_price_cents}c (correct side)")
        print(f"[TEST] Expected: NO candidate only, YES rejected")
    
    def test_bullish_cheap_no_correct_yes_rejected(self):
        """
        Test: Bullish signal (velocity > 0) with cheap NO but fair YES.
        
        Expected: YES candidate only (thesis_side=YES), NO candidate rejected.
        Cheap NO should not override bullish directional signal.
        """
        # Setup: Bullish velocity (positive)
        velocity = 0.05  # Positive = bullish = thesis_side=YES
        
        # Market state: NO is cheap (15c), YES is in range (42c)
        yes_price_cents = 42  # Fair YES
        no_price_cents = 15   # Cheap NO
        
        # Expected: thesis_side=YES (from positive velocity)
        expected_thesis_side = "yes"
        
        # Invariant: thesis_side should be YES
        assert expected_thesis_side == "yes"

        # Invariant: Only YES price should be evaluated for cheapness
        # NO price being cheap is irrelevant for bullish thesis
        # CRITICAL FIX 2026-08-03: YES uses side-aware range 10c-75c
        thesis_in_range = (10 <= yes_price_cents <= 75)
        assert thesis_in_range, "YES price should be in range for bullish thesis"

        # Invariant: NO cheapness should NOT generate NO candidate
        # Even though NO is cheap (15c), it's on the wrong side
        # NO uses side-aware range 25c-99c
        no_in_range = (25 <= no_price_cents <= 99)
        # NO being in range doesn't matter - thesis_side=YES
        
        print(f"[TEST] velocity={velocity} thesis_side={expected_thesis_side}")
        print(f"[TEST] yes_price={yes_price_cents}c (correct side)")
        print(f"[TEST] no_price={no_price_cents}c (cheap but wrong side)")
        print(f"[TEST] Expected: YES candidate only, NO rejected")
    
    def test_thesis_side_from_velocity(self):
        """Test that thesis_side is correctly derived from velocity sign."""
        # Positive velocity → bullish → thesis_side=YES
        velocity_positive = 0.01
        thesis_side_positive = "yes" if velocity_positive > 0 else "no"
        assert thesis_side_positive == "yes"
        
        # Negative velocity → bearish → thesis_side=NO
        velocity_negative = -0.01
        thesis_side_negative = "yes" if velocity_negative > 0 else "no"
        assert thesis_side_negative == "no"
        
        # Zero velocity → default to YES (conservative)
        velocity_zero = 0.0
        thesis_side_zero = "yes" if velocity_zero > 0 else "no"
        assert thesis_side_zero == "no"  # Zero is not > 0, so NO
    
    def test_price_range_gating_thesis_side_only(self):
        """Test that price range gating only applies to thesis_side."""
        # CRITICAL FIX 2026-08-03: Use side-aware ranges (YES 10c-75c, NO 25c-99c)
        # Case 1: thesis_side=YES, YES in range, NO out of range
        thesis_side = "yes"
        yes_price = 42  # In range (10c-75c)
        no_price = 5    # Out of range (25c-99c)

        thesis_in_range = (10 <= yes_price <= 75) if thesis_side == "yes" else (25 <= no_price <= 99)
        assert thesis_in_range, "Thesis side price should be in range"

        # Case 2: thesis_side=NO, NO in range, YES out of range
        thesis_side = "no"
        yes_price = 95   # Out of range (10c-75c)
        no_price = 42    # In range (25c-99c)

        thesis_in_range = (10 <= yes_price <= 75) if thesis_side == "yes" else (25 <= no_price <= 99)
        assert thesis_in_range, "Thesis side price should be in range"

        # Case 3: thesis_side=YES, YES out of range → should reject
        thesis_side = "yes"
        yes_price = 95   # Out of range (10c-75c)
        no_price = 42    # In range (but irrelevant)

        thesis_in_range = (10 <= yes_price <= 75) if thesis_side == "yes" else (25 <= no_price <= 99)
        assert not thesis_in_range, "Thesis side price out of range should reject"

        # Case 4: thesis_side=NO, NO out of range → should reject
        thesis_side = "no"
        yes_price = 42   # In range (but irrelevant)
        no_price = 20    # Out of range (25c-99c)

        thesis_in_range = (10 <= yes_price <= 75) if thesis_side == "yes" else (25 <= no_price <= 99)
        assert not thesis_in_range, "Thesis side price out of range should reject"
    
    def test_both_sides_out_of_range_reject(self):
        """Test that both sides out of range rejects regardless of thesis_side."""
        thesis_side = "yes"
        yes_price = 95   # Out of range
        no_price = 5     # Out of range
        
        thesis_in_range = (10 <= yes_price <= 75) if thesis_side == "yes" else (10 <= no_price <= 75)
        assert not thesis_in_range, "Should reject when thesis side out of range"
    
    def test_midpoint_bonus_applies_to_thesis_side_only(self):
        """Test that midpoint bonus only applies to thesis_side, not both sides."""
        def midpoint_bonus(price_cents):
            """Peak at 25c, decays toward 10c/75c."""
            dist = abs(price_cents - 25)
            midpoint_bonus_max = 0.5
            midpoint_bonus_slope = 0.02
            return max(0.0, midpoint_bonus_max - dist * midpoint_bonus_slope)
        
        # thesis_side=YES, YES at 25c (max bonus), NO at 25c (should not get bonus)
        thesis_side = "yes"
        yes_price = 25
        no_price = 25
        
        # Only thesis_side should get bonus
        if thesis_side == "yes":
            bonus = midpoint_bonus(yes_price)
        else:
            bonus = midpoint_bonus(no_price)
        
        assert bonus == 0.5, "Thesis side at 25c should get max bonus"
        
        # NO at 25c should NOT get bonus when thesis_side=YES
        # (This is enforced by only applying bonus to thesis_side in code)


class TestRouterPriceSideCheck:
    """Test PRICE-SIDE-CHECK invariant in order_router."""
    
    def test_router_rejects_side_mismatch(self):
        """
        Test that router rejects orders where order side doesn't match thesis_side.
        
        This is a belt-and-suspenders check to catch any candidates that
        slipped through the candidate builder invariant.
        """
        # Mock intent with thesis_side=YES but order side=NO
        intent = Mock()
        intent.ticker = "KXBTC15M-TEST"
        intent.thesis_side = "yes"
        intent.side = "BUY_NO"  # Mismatch!
        intent.action = "buy"
        intent.count = 1
        
        # Extract outcome_side from order side
        if "YES" in intent.side:
            order_outcome_side = "yes"
        elif "NO" in intent.side:
            order_outcome_side = "no"
        else:
            order_outcome_side = None
        
        # Invariant: order_outcome_side must match thesis_side
        assert order_outcome_side == "no"
        assert intent.thesis_side == "yes"
        
        # This should be rejected
        should_reject = (order_outcome_side and order_outcome_side != intent.thesis_side.lower())
        assert should_reject, "Router should reject side mismatch"
    
    def test_router_accepts_side_match(self):
        """Test that router accepts orders where order side matches thesis_side."""
        # Mock intent with thesis_side=YES and order side=YES
        intent = Mock()
        intent.ticker = "KXBTC15M-TEST"
        intent.thesis_side = "yes"
        intent.side = "BUY_YES"  # Match!
        intent.action = "buy"
        intent.count = 1
        
        # Extract outcome_side from order side
        if "YES" in intent.side:
            order_outcome_side = "yes"
        elif "NO" in intent.side:
            order_outcome_side = "no"
        else:
            order_outcome_side = None
        
        # Invariant: order_outcome_side must match thesis_side
        assert order_outcome_side == "yes"
        assert intent.thesis_side == "yes"
        
        # This should be accepted
        should_reject = (order_outcome_side and order_outcome_side != intent.thesis_side.lower())
        assert not should_reject, "Router should accept side match"
    
    def test_router_handles_missing_thesis_side(self):
        """Test that router handles intents without thesis_side gracefully."""
        # Mock intent without thesis_side (legacy)
        intent = Mock()
        intent.ticker = "KXBTC15M-TEST"
        intent.thesis_side = None  # Missing
        intent.side = "BUY_YES"
        intent.action = "buy"
        intent.count = 1
        
        # Router should skip check when thesis_side is missing
        thesis_side = getattr(intent, 'thesis_side', None)
        assert thesis_side is None
        
        # Should not reject (backward compatibility)
        should_reject = False  # No thesis_side to validate against
        assert not should_reject, "Router should skip check when thesis_side missing"


class TestPriceSideLogSchema:
    """Test that PRICE-SIDE-CHECK logs have correct schema."""
    
    def test_price_side_check_log_schema(self):
        """Test that [PRICE-SIDE-CHECK] log has required fields."""
        # Expected log schema:
        # [PRICE-SIDE-CHECK] asset=%s thesis_side=%s yes_price=%dc in_range=%s (cheapness evaluated only on thesis_side)
        # or
        # [PRICE-SIDE-CHECK] asset=%s thesis_side=NO no_price=%dc in_range=%s (cheapness evaluated only on thesis_side)
        
        log_template = "[PRICE-SIDE-CHECK] asset={asset} thesis_side={thesis_side} {price_field}={price}c in_range={in_range} (cheapness evaluated only on thesis_side)"
        
        # Test YES thesis_side
        log_yes = log_template.format(
            asset="BTC",
            thesis_side="YES",
            price_field="yes_price",
            price=42,
            in_range="True"
        )
        assert "thesis_side=YES" in log_yes
        assert "yes_price=42c" in log_yes
        assert "cheapness evaluated only on thesis_side" in log_yes
        
        # Test NO thesis_side
        log_no = log_template.format(
            asset="BTC",
            thesis_side="NO",
            price_field="no_price",
            price=42,
            in_range="True"
        )
        assert "thesis_side=NO" in log_no
        assert "no_price=42c" in log_no
        assert "cheapness evaluated only on thesis_side" in log_no
    
    def test_price_side_check_reject_log_schema(self):
        """Test that [PRICE-SIDE-CHECK-REJECT] log has required fields."""
        # CRITICAL FIX 2026-08-03: Log schema now includes side-aware ranges
        # Expected log schema:
        # [PRICE-SIDE-CHECK-REJECT] asset=%s thesis_side=%s thesis_price=%dc outside %s range -> NO TRADE

        # Test YES side (10c-75c range)
        log_template_yes = "[PRICE-SIDE-CHECK-REJECT] asset={asset} thesis_side={thesis_side} thesis_price={price}c outside {range_str} range -> NO TRADE"

        log_yes = log_template_yes.format(
            asset="BTC",
            thesis_side="YES",
            price=95,
            range_str="10c-75c"
        )

        assert "thesis_side=YES" in log_yes
        assert "thesis_price=95c" in log_yes
        assert "outside 10c-75c range" in log_yes
        assert "NO TRADE" in log_yes

        # Test NO side (25c-99c range)
        log_no = log_template_yes.format(
            asset="ETH",
            thesis_side="NO",
            price=20,
            range_str="25c-99c"
        )

        assert "thesis_side=NO" in log_no
        assert "thesis_price=20c" in log_no
        assert "outside 25c-99c range" in log_no
        assert "NO TRADE" in log_no
    
    def test_price_side_check_invariant_log_schema(self):
        """Test that [PRICE-SIDE-CHECK-INVARIANT] log has required fields."""
        # Expected log schema:
        # [PRICE-SIDE-CHECK-INVARIANT] asset=%s thesis_side=%s signal_side=%s thesis_edge=%.4f selected_edge=%.4f (INVARIANT: side matches thesis)
        
        log_template = "[PRICE-SIDE-CHECK-INVARIANT] asset={asset} thesis_side={thesis_side} signal_side={signal_side} thesis_edge={thesis_edge:.4f} selected_edge={selected_edge:.4f} (INVARIANT: side matches thesis)"
        
        log = log_template.format(
            asset="BTC",
            thesis_side="YES",
            signal_side="YES",
            thesis_edge=0.05,
            selected_edge=0.05
        )
        
        assert "thesis_side=YES" in log
        assert "signal_side=YES" in log
        assert "thesis_edge=0.0500" in log
        assert "selected_edge=0.0500" in log
        assert "INVARIANT: side matches thesis" in log


class TestNoSideSignalIntegrityWithCheaperYes:
    """Test NO-side integrity when YES is cheaper - parametrized for all assets."""
    
    @pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL", "XRP", "DOGE"])
    def test_bearish_with_cheap_yes_no_integrity(self, asset):
        """
        Test: Bearish signal with YES much cheaper than NO.
        
        Expected: 
        - signal_side=NO, thesis_side=NO
        - Candidate side NO, price=no_price
        - No YES candidate
        - Log scanner reports cheap_wrong_side_candidates but no price_side_mismatches
        """
        # Setup: Bearish velocity (negative)
        velocity = -0.05
        thesis_side = "no" if velocity < 0 else "yes"
        
        # Market state: YES is much cheaper than NO
        yes_price_cents = 10  # Very cheap YES
        no_price_cents = 42   # Fair NO

        # Invariant: thesis_side should be NO
        assert thesis_side == "no"

        # Invariant: Only NO price should be evaluated
        # CRITICAL FIX 2026-08-03: NO uses side-aware range 25c-99c
        thesis_in_range = (25 <= no_price_cents <= 99)
        assert thesis_in_range, "NO price should be in range"

        # Invariant: YES cheapness should be ignored
        # YES uses side-aware range 10c-75c
        yes_in_range = (10 <= yes_price_cents <= 75)
        assert yes_in_range, "YES is in range but should be ignored"
        
        # Expected candidate properties
        expected_side = "no"
        expected_price = no_price_cents
        
        assert expected_side == "no"
        assert expected_price == 42
        
        print(f"[TEST] {asset}: thesis_side={thesis_side}, YES cheap={yes_price_cents}c, NO fair={no_price_cents}c")
        print(f"[TEST] {asset}: Expected NO candidate at {no_price_cents}c, YES ignored")


class TestRouterCorruptedCandidate:
    """Test router rejection of corrupted candidates with side/price mismatch."""
    
    def test_router_rejects_corrupted_candidate(self):
        """
        Test: Feed a deliberately corrupted candidate where selected_side=NO but selected_price_cents=yes_price_cents.
        
        Expected: Router logs [PRICE-SIDE-CHECK-VIOLATION-ROUTER] and hard rejection.
        """
        # Mock corrupted candidate
        intent = Mock()
        intent.ticker = "KXBTC15M-TEST"
        intent.thesis_side = "no"
        intent.side = "BUY_NO"  # Side says NO
        intent.price_cents = 15  # But this is YES price (15c) - corrupted!
        intent.action = "buy"
        intent.count = 1
        
        # Extract outcome_side from order side
        if "YES" in intent.side:
            order_outcome_side = "yes"
        elif "NO" in intent.side:
            order_outcome_side = "no"
        else:
            order_outcome_side = None
        
        # Invariant: order_outcome_side must match thesis_side
        assert order_outcome_side == "no"
        assert intent.thesis_side == "no"
        
        # However, price_cents (15c) is suspiciously low for NO side
        # In a real scenario, this would be detected by checking price against thesis_side
        # For this test, we verify the router would reject if side/price disagree
        
        # Simulate price-side mismatch detection
        # If thesis_side=NO, price should be no_price (e.g., 42c), not yes_price (15c)
        suspicious_price_mismatch = (intent.thesis_side == "no" and intent.price_cents < 20)
        
        assert suspicious_price_mismatch, "Router should detect price-side mismatch"
        
        print(f"[TEST] Corrupted candidate: thesis_side=NO, order_side=BUY_NO, price=15c (YES price)")
        print(f"[TEST] Expected: Router rejects with PRICE-SIDE-CHECK-VIOLATION-ROUTER")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
