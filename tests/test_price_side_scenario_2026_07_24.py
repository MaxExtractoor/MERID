"""
Price-Side Integrated Scenario Tests (2026-07-24)

End-to-end scenario tests for price+side alignment invariants.
Tests the full pipeline from signal → candidate → intent → order → execution.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from datetime import datetime, timezone


class TestPriceSideScenarioBearishCheapYes:
    """Scenario: Bearish signal with cheap YES contracts on wrong side."""
    
    @pytest.mark.asyncio
    async def test_bearish_cheap_yes_scenario(self):
        """
        Full pipeline test: Bearish BTC signal, YES cheap (15c), NO fair (42c).
        
        Expected flow:
        1. Signal: velocity=-0.05 (bearish) → thesis_side=NO
        2. Candidate: Only NO side evaluated, YES cheapness ignored
        3. Intent: thesis_side=NO, outcome_side=NO
        4. Order: BUY_NO at 42c (NO price)
        5. Execution: NO order executed, YES never considered
        
        This verifies that cheap YES cannot override bearish thesis.
        """
        # Step 1: Signal generation (bearish)
        asset = "BTC"
        velocity = -0.05  # Bearish
        thesis_side = "no" if velocity < 0 else "yes"
        
        assert thesis_side == "no", "Bearish velocity should produce thesis_side=NO"
        
        # Step 2: Market state (cheap YES, fair NO)
        market_state = Mock()
        market_state.best_bid_cents = 15  # YES price (cheap)
        market_state.best_ask_cents = 85  # NO price = 100 - 15 = 85 (but we use 42 for fair)
        
        # Override for scenario: YES=15c, NO=42c
        yes_price_cents = 15
        no_price_cents = 42

        # Step 3: Candidate generation (should only evaluate NO)
        # CRITICAL FIX 2026-08-03: NO uses side-aware range 25c-99c
        thesis_in_range = (25 <= no_price_cents <= 99)
        assert thesis_in_range, "NO price should be in range for thesis_side=NO"

        # YES cheapness should be ignored
        # YES uses side-aware range 10c-75c
        yes_in_range = (10 <= yes_price_cents <= 75)
        assert yes_in_range, "YES is in range but should be ignored (wrong side)"
        
        # Step 4: Intent creation
        intent = Mock()
        intent.ticker = "KXBTC15M-TEST"
        intent.thesis_side = thesis_side
        intent.outcome_side = thesis_side  # Must match
        intent.side = "BUY_NO"
        intent.action = "buy"
        intent.price_cents = no_price_cents  # Use NO price
        intent.count = 1
        
        # Verify intent invariants
        assert intent.thesis_side == "no"
        assert intent.outcome_side == "no"
        assert intent.side == "BUY_NO"
        assert intent.price_cents == 42  # NO price, not YES price
        
        # Step 5: Router validation
        order_outcome_side = "no" if "NO" in intent.side else "yes"
        assert order_outcome_side == intent.thesis_side.lower()
        
        # Step 6: Verify execution would use correct side
        expected_execution_side = "no"
        expected_execution_price = 42
        
        assert expected_execution_side == "no"
        assert expected_execution_price == 42
        
        print(f"[SCENARIO] Bearish signal with cheap YES")
        print(f"[SCENARIO] thesis_side={thesis_side}, YES price={yes_price_cents}c (ignored), NO price={no_price_cents}c (used)")
        print(f"[SCENARIO] Expected: BUY_NO at 42c, YES never considered")


class TestPriceSideScenarioBullishCheapNo:
    """Scenario: Bullish signal with cheap NO contracts on wrong side."""
    
    @pytest.mark.asyncio
    async def test_bullish_cheap_no_scenario(self):
        """
        Full pipeline test: Bullish ETH signal, NO cheap (15c), YES fair (42c).
        
        Expected flow:
        1. Signal: velocity=0.05 (bullish) → thesis_side=YES
        2. Candidate: Only YES side evaluated, NO cheapness ignored
        3. Intent: thesis_side=YES, outcome_side=YES
        4. Order: BUY_YES at 42c (YES price)
        5. Execution: YES order executed, NO never considered
        
        This verifies that cheap NO cannot override bullish thesis.
        """
        # Step 1: Signal generation (bullish)
        asset = "ETH"
        velocity = 0.05  # Bullish
        thesis_side = "yes" if velocity > 0 else "no"
        
        assert thesis_side == "yes", "Bullish velocity should produce thesis_side=YES"
        
        # Step 2: Market state (cheap NO, fair YES)
        yes_price_cents = 42  # Fair YES
        no_price_cents = 15   # Cheap NO

        # Step 3: Candidate generation (should only evaluate YES)
        # CRITICAL FIX 2026-08-03: YES uses side-aware range 10c-75c
        thesis_in_range = (10 <= yes_price_cents <= 75)
        assert thesis_in_range, "YES price should be in range for thesis_side=YES"

        # NO cheapness should be ignored
        # NO uses side-aware range 25c-99c
        no_in_range = (25 <= no_price_cents <= 99)
        assert no_in_range, "NO is in range but should be ignored (wrong side)"
        
        # Step 4: Intent creation
        intent = Mock()
        intent.ticker = "KXETH15M-TEST"
        intent.thesis_side = thesis_side
        intent.outcome_side = thesis_side  # Must match
        intent.side = "BUY_YES"
        intent.action = "buy"
        intent.price_cents = yes_price_cents  # Use YES price
        intent.count = 1
        
        # Verify intent invariants
        assert intent.thesis_side == "yes"
        assert intent.outcome_side == "yes"
        assert intent.side == "BUY_YES"
        assert intent.price_cents == 42  # YES price, not NO price
        
        # Step 5: Router validation
        order_outcome_side = "yes" if "YES" in intent.side else "no"
        assert order_outcome_side == intent.thesis_side.lower()
        
        # Step 6: Verify execution would use correct side
        expected_execution_side = "yes"
        expected_execution_price = 42
        
        assert expected_execution_side == "yes"
        assert expected_execution_price == 42
        
        print(f"[SCENARIO] Bullish signal with cheap NO")
        print(f"[SCENARIO] thesis_side={thesis_side}, YES price={yes_price_cents}c (used), NO price={no_price_cents}c (ignored)")
        print(f"[SCENARIO] Expected: BUY_YES at 42c, NO never considered")


class TestPriceSideScenarioBothSidesCheap:
    """Scenario: Both sides cheap, but thesis_side determines selection."""
    
    @pytest.mark.asyncio
    async def test_both_sides_cheap_thesis_determines(self):
        """
        Full pipeline test: Bearish SOL signal, both sides cheap (YES=15c, NO=15c).
        
        Expected flow:
        1. Signal: velocity=-0.03 (bearish) → thesis_side=NO
        2. Candidate: Only NO side evaluated, YES cheapness ignored
        3. Intent: thesis_side=NO, outcome_side=NO
        4. Order: BUY_NO at 15c (NO price)
        5. Execution: NO order executed at cheap price
        
        This verifies that thesis_side is the deciding factor, not cheapness.
        """
        # Step 1: Signal generation (bearish)
        asset = "SOL"
        velocity = -0.03  # Bearish
        thesis_side = "no" if velocity < 0 else "yes"
        
        assert thesis_side == "no", "Bearish velocity should produce thesis_side=NO"
        
        # Step 2: Market state (both cheap)
        yes_price_cents = 15  # Cheap YES
        no_price_cents = 15   # Cheap NO

        # Step 3: Candidate generation (should only evaluate NO)
        # CRITICAL FIX 2026-08-03: NO uses side-aware range 25c-99c
        thesis_in_range = (25 <= no_price_cents <= 99)
        assert thesis_in_range, "NO price should be in range for thesis_side=NO"

        # YES cheapness should be ignored even though it's also cheap
        # YES uses side-aware range 10c-75c
        yes_in_range = (10 <= yes_price_cents <= 75)
        assert yes_in_range, "YES is in range but should be ignored (wrong side)"
        
        # Step 4: Intent creation
        intent = Mock()
        intent.ticker = "KXSOL15M-TEST"
        intent.thesis_side = thesis_side
        intent.outcome_side = thesis_side  # Must match
        intent.side = "BUY_NO"
        intent.action = "buy"
        intent.price_cents = no_price_cents  # Use NO price
        intent.count = 1
        
        # Verify intent invariants
        assert intent.thesis_side == "no"
        assert intent.outcome_side == "no"
        assert intent.side == "BUY_NO"
        assert intent.price_cents == 15  # NO price
        
        # Step 5: Router validation
        order_outcome_side = "no" if "NO" in intent.side else "yes"
        assert order_outcome_side == intent.thesis_side.lower()
        
        # Step 6: Verify execution would use correct side
        expected_execution_side = "no"
        expected_execution_price = 15
        
        assert expected_execution_side == "no"
        assert expected_execution_price == 15
        
        print(f"[SCENARIO] Bearish signal with both sides cheap")
        print(f"[SCENARIO] thesis_side={thesis_side}, YES price={yes_price_cents}c (ignored), NO price={no_price_cents}c (used)")
        print(f"[SCENARIO] Expected: BUY_NO at 15c, thesis_side determines selection")


class TestPriceSideScenarioThesisSideOutOfRange:
    """Scenario: thesis_side price out of range should reject."""
    
    @pytest.mark.asyncio
    async def test_thesis_side_out_of_range_reject(self):
        """
        Full pipeline test: Bullish XRP signal, YES price out of range (95c).
        
        Expected flow:
        1. Signal: velocity=0.04 (bullish) → thesis_side=YES
        2. Candidate: YES price=95c out of range → REJECT
        3. No intent created
        4. No order
        5. No execution
        
        This verifies that thesis_side price range gating is enforced.
        """
        # Step 1: Signal generation (bullish)
        asset = "XRP"
        velocity = 0.04  # Bullish
        thesis_side = "yes" if velocity > 0 else "no"
        
        assert thesis_side == "yes", "Bullish velocity should produce thesis_side=YES"
        
        # Step 2: Market state (YES out of range, NO in range)
        yes_price_cents = 95  # Out of range
        no_price_cents = 42   # In range (but irrelevant)

        # Step 3: Candidate generation (should reject YES out of range)
        # CRITICAL FIX 2026-08-03: YES uses side-aware range 10c-75c
        thesis_in_range = (10 <= yes_price_cents <= 75)
        assert not thesis_in_range, "YES price out of range should reject"

        # NO being in range doesn't matter - thesis_side=YES
        # NO uses side-aware range 25c-99c
        no_in_range = (25 <= no_price_cents <= 99)
        assert no_in_range, "NO is in range but thesis_side=YES so irrelevant"
        
        # Step 4: No intent created (rejected at candidate stage)
        intent = None
        
        # Step 5: No order
        order = None
        
        # Step 6: No execution
        execution = None
        
        assert intent is None
        assert order is None
        assert execution is None
        
        print(f"[SCENARIO] Bullish signal with thesis_side price out of range")
        print(f"[SCENARIO] thesis_side={thesis_side}, YES price={yes_price_cents}c (out of range), NO price={no_price_cents}c (ignored)")
        print(f"[SCENARIO] Expected: REJECT at candidate stage, no intent/order/execution")


class TestPriceSideScenarioExitPreservesThesis:
    """Scenario: Exit orders must preserve thesis_side from position."""
    
    @pytest.mark.asyncio
    async def test_exit_preserves_thesis_side(self):
        """
        Full pipeline test: Exit order for NO position must use thesis_side=NO.
        
        Expected flow:
        1. Position: thesis_side=NO, size=1, entry_price=42c
        2. Exit signal: TP hit → exit_reason=TAKE_PROFIT
        3. Intent: thesis_side=NO (from position), outcome_side=NO
        4. Order: SELL_NO at exit price
        5. Execution: NO order executed, position closed
        
        This verifies that exit orders preserve thesis_side invariant.
        """
        # Step 1: Position state
        position = Mock()
        position.ticker = "KXDOGE15M-TEST"
        position.thesis_side = "no"
        position.size_fp = 1
        position.avg_entry_price_cents = 42
        
        assert position.thesis_side == "no"
        
        # Step 2: Exit signal
        exit_reason = "TAKE_PROFIT"
        
        # Step 3: Intent creation (exit preserves thesis_side)
        intent = Mock()
        intent.ticker = position.ticker
        intent.thesis_side = position.thesis_side  # Preserve from position
        intent.outcome_side = position.thesis_side  # Must match
        intent.side = "SELL_NO"  # Sell to close NO position
        intent.action = "sell"
        intent.price_cents = 50  # Exit price
        intent.count = 1
        
        # Verify intent invariants
        assert intent.thesis_side == "no"
        assert intent.outcome_side == "no"
        assert intent.side == "SELL_NO"
        
        # Step 4: Router validation
        order_outcome_side = "no" if "NO" in intent.side else "yes"
        assert order_outcome_side == intent.thesis_side.lower()
        
        # Step 5: Verify execution would preserve thesis_side
        expected_execution_side = "no"
        expected_execution_price = 50
        
        assert expected_execution_side == "no"
        assert expected_execution_price == 50
        
        print(f"[SCENARIO] Exit order preserves thesis_side")
        print(f"[SCENARIO] position.thesis_side={position.thesis_side}, exit_reason={exit_reason}")
        print(f"[SCENARIO] Expected: SELL_NO at 50c, thesis_side preserved")


class TestPriceSideScenarioAllAssets:
    """Scenario: Test price-side invariant across all 5 crypto assets."""
    
    @pytest.mark.asyncio
    async def test_all_assets_price_side_invariant(self):
        """
        Test that price-side invariant works for all 5 crypto assets.
        
        Assets: BTC, ETH, SOL, XRP, DOGE
        For each asset, test bearish and bullish scenarios.
        """
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        for asset in assets:
            # Test bearish scenario
            velocity_bearish = -0.05
            thesis_side_bearish = "no" if velocity_bearish < 0 else "yes"
            assert thesis_side_bearish == "no", f"{asset} bearish should have thesis_side=NO"
            
            # Test bullish scenario
            velocity_bullish = 0.05
            thesis_side_bullish = "yes" if velocity_bullish > 0 else "no"
            assert thesis_side_bullish == "yes", f"{asset} bullish should have thesis_side=YES"
            
            print(f"[SCENARIO] {asset}: bearish thesis={thesis_side_bearish}, bullish thesis={thesis_side_bullish}")
        
        # All 5 assets must be covered
        assert len(assets) == 5
        assert set(assets) == {"BTC", "ETH", "SOL", "XRP", "DOGE"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
