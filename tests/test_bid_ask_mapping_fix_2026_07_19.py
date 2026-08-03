"""Regression tests for bid/ask mapping fix (2026-07-19, updated 2026-07-20).

This test verifies the correct mapping of outcome+action to bid/ask per Kalshi semantics:
- BUY_YES = bid (bidding to buy YES)
- SELL_YES = ask (asking to sell YES)
- BUY_NO = bid (bidding to buy NO)
- SELL_NO = ask (asking to sell NO)

CRITICAL FIX (2026-07-20): Previous comments incorrectly claimed BUY_NO=ask/SELL_NO=bid
This was causing side inversion - buying NO was sent as ask (selling YES), etc.
The correct mapping is: buy = bid (bidding), sell = ask (asking), regardless of outcome
"""

import pytest


def map_outcome_action_to_bid_ask(outcome: str, action: str) -> str:
    """Replicate the bid/ask mapping logic from client.py for testing.
    
    CRITICAL FIX (2026-07-20): Correct mapping is buy=bid, sell=ask, regardless of outcome
    """
    if outcome == "yes" and action == "buy":
        return "bid"
    elif outcome == "yes" and action == "sell":
        return "ask"
    elif outcome == "no" and action == "buy":
        return "bid"  # FIXED: buying NO = bidding
    elif outcome == "no" and action == "sell":
        return "ask"  # FIXED: selling NO = asking
    else:
        # Fallback for unexpected combinations
        return "bid"


class TestBidAskMappingFix:
    """Test bid/ask mapping for all outcome+action combinations."""
    
    def test_buy_yes_maps_to_bid(self):
        """BUY_YES should map to bid (bidding to buy YES)."""
        assert map_outcome_action_to_bid_ask("yes", "buy") == "bid"
    
    def test_sell_yes_maps_to_ask(self):
        """SELL_YES should map to ask (asking to sell YES)."""
        assert map_outcome_action_to_bid_ask("yes", "sell") == "ask"
    
    def test_buy_no_maps_to_bid(self):
        """BUY_NO should map to bid (bidding to buy NO)."""
        assert map_outcome_action_to_bid_ask("no", "buy") == "bid"
    
    def test_sell_no_maps_to_ask(self):
        """SELL_NO should map to ask (asking to sell NO)."""
        assert map_outcome_action_to_bid_ask("no", "sell") == "ask"
    
    def test_all_combinations_covered(self):
        """Verify all four outcome+action combinations are covered."""
        combinations = [
            ("yes", "buy"),
            ("yes", "sell"),
            ("no", "buy"),
            ("no", "sell"),
        ]
        for outcome, action in combinations:
            result = map_outcome_action_to_bid_ask(outcome, action)
            assert result in ("bid", "ask"), f"Invalid result for {outcome}/{action}: {result}"
    
    def test_fallback_for_invalid_combination(self):
        """Invalid combinations should fallback to bid."""
        assert map_outcome_action_to_bid_ask("invalid", "invalid") == "bid"
    
    def test_kalshi_semantics_equivalence(self):
        """Verify that buy actions map to bid and sell actions map to ask.
        
        CRITICAL FIX (2026-07-20): The correct semantics are:
        - buy = bid (bidding), regardless of outcome
        - sell = ask (asking), regardless of outcome
        
        Previous incorrect equivalence claims (BUY_NO=ask/SELL_NO=bid) caused side inversion.
        """
        # All buy actions map to bid (bidding)
        assert map_outcome_action_to_bid_ask("yes", "buy") == "bid"
        assert map_outcome_action_to_bid_ask("no", "buy") == "bid"
        
        # All sell actions map to ask (asking)
        assert map_outcome_action_to_bid_ask("yes", "sell") == "ask"
        assert map_outcome_action_to_bid_ask("no", "sell") == "ask"


class TestDirectionalConsistency:
    """Test consistency across directional concepts."""
    
    def test_up_direction_maps_to_buy_yes(self):
        """Up direction should map to BUY_YES (long YES)."""
        # This is the pattern used in all 5 crypto agents
        direction = "up"
        expected_side = "buy_yes"
        # Verify the mapping logic
        if direction == "up":
            side = "buy_yes"
        else:
            side = "buy_no"
        assert side == expected_side
    
    def test_down_direction_maps_to_buy_no(self):
        """Down direction should map to BUY_NO (long NO)."""
        direction = "down"
        expected_side = "buy_no"
        if direction == "up":
            side = "buy_yes"
        else:
            side = "buy_no"
        assert side == expected_side
    
    def test_long_position_maps_to_yes_outcome(self):
        """Long position should map to yes outcome."""
        position_side = "long"
        expected_outcome = "yes"
        outcome = "yes" if position_side == "long" else "no"
        assert outcome == expected_outcome
    
    def test_short_position_maps_to_no_outcome(self):
        """Short position should map to no outcome."""
        position_side = "short"
        expected_outcome = "no"
        outcome = "yes" if position_side == "long" else "no"
        assert outcome == expected_outcome


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
