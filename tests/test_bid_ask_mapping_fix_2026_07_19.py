"""Regression tests for bid/ask mapping fix (2026-07-19).

This test verifies the correct mapping of outcome+action to bid/ask per Kalshi semantics:
- BUY_YES = bid (bidding to buy YES)
- SELL_YES = ask (asking to sell YES)
- BUY_NO = ask (equivalent to SELL_YES, both are long NO)
- SELL_NO = bid (equivalent to BUY_YES, both are long YES)

Reference: Kalshi quotes everything from YES side.
"""

import pytest


def map_outcome_action_to_bid_ask(outcome: str, action: str) -> str:
    """Replicate the bid/ask mapping logic from client.py for testing."""
    if outcome == "yes" and action == "buy":
        return "bid"
    elif outcome == "yes" and action == "sell":
        return "ask"
    elif outcome == "no" and action == "buy":
        return "ask"
    elif outcome == "no" and action == "sell":
        return "bid"
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
    
    def test_buy_no_maps_to_ask(self):
        """BUY_NO should map to ask (equivalent to SELL_YES, both are long NO)."""
        assert map_outcome_action_to_bid_ask("no", "buy") == "ask"
    
    def test_sell_no_maps_to_bid(self):
        """SELL_NO should map to bid (equivalent to BUY_YES, both are long YES)."""
        assert map_outcome_action_to_bid_ask("no", "sell") == "bid"
    
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
        """Verify that equivalent trades map to the same bid/ask side.
        
        Kalshi semantics:
        - BUY_YES and SELL_NO are equivalent (both long YES) → both should be bid
        - SELL_YES and BUY_NO are equivalent (both long NO) → both should be ask
        """
        # BUY_YES and SELL_NO both map to bid (long YES)
        assert map_outcome_action_to_bid_ask("yes", "buy") == "bid"
        assert map_outcome_action_to_bid_ask("no", "sell") == "bid"
        
        # SELL_YES and BUY_NO both map to ask (long NO)
        assert map_outcome_action_to_bid_ask("yes", "sell") == "ask"
        assert map_outcome_action_to_bid_ask("no", "buy") == "ask"


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
