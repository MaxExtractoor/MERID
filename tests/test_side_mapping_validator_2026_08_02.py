"""Unit tests for side_mapping_validator.py

Tests for side mapping validation addressing bugs #3, #4.
"""

import pytest
from merid.event_venues.kalshi.side_mapping_validator import (
    validate_side_action_combination,
    validate_kalshi_format_conversion,
    validate_api_side_mapping,
    validate_intent_consistency,
    validate_price_space_consistency,
    validate_fill_side_consistency,
    pre_execution_validation,
    post_execution_validation,
)


class TestValidateSideActionCombination:
    """Test validation of side/action combinations."""
    
    def test_valid_yes_buy(self):
        """Test valid YES buy combination."""
        is_valid, error = validate_side_action_combination("yes", "buy")
        assert is_valid
        assert error is None
    
    def test_valid_yes_sell(self):
        """Test valid YES sell combination."""
        is_valid, error = validate_side_action_combination("yes", "sell")
        assert is_valid
        assert error is None
    
    def test_valid_no_buy(self):
        """Test valid NO buy combination."""
        is_valid, error = validate_side_action_combination("no", "buy")
        assert is_valid
        assert error is None
    
    def test_valid_no_sell(self):
        """Test valid NO sell combination."""
        is_valid, error = validate_side_action_combination("no", "sell")
        assert is_valid
        assert error is None
    
    def test_invalid_side(self):
        """Test invalid side."""
        is_valid, error = validate_side_action_combination("invalid", "buy")
        assert not is_valid
        assert error is not None
        assert "Invalid side" in error
    
    def test_invalid_action(self):
        """Test invalid action."""
        is_valid, error = validate_side_action_combination("yes", "invalid")
        assert not is_valid
        assert error is not None
        assert "Invalid action" in error
    
    def test_case_insensitive(self):
        """Test case-insensitive validation."""
        is_valid, error = validate_side_action_combination("YES", "BUY")
        assert is_valid
        assert error is None
    
    def test_mixed_case(self):
        """Test mixed case validation."""
        is_valid, error = validate_side_action_combination("Yes", "Buy")
        assert is_valid
        assert error is None


class TestValidateKalshiFormatConversion:
    """Test validation of Kalshi format conversion."""
    
    def test_buy_yes_conversion(self):
        """Test BUY_YES conversion."""
        is_valid, error = validate_kalshi_format_conversion("yes", "buy", "BUY_YES")
        assert is_valid
        assert error is None
    
    def test_sell_yes_conversion(self):
        """Test SELL_YES conversion."""
        is_valid, error = validate_kalshi_format_conversion("yes", "sell", "SELL_YES")
        assert is_valid
        assert error is None
    
    def test_buy_no_conversion(self):
        """Test BUY_NO conversion."""
        is_valid, error = validate_kalshi_format_conversion("no", "buy", "BUY_NO")
        assert is_valid
        assert error is None
    
    def test_sell_no_conversion(self):
        """Test SELL_NO conversion."""
        is_valid, error = validate_kalshi_format_conversion("no", "sell", "SELL_NO")
        assert is_valid
        assert error is None
    
    def test_incorrect_conversion(self):
        """Test incorrect Kalshi format."""
        is_valid, error = validate_kalshi_format_conversion("yes", "buy", "BUY_NO")
        assert not is_valid
        assert error is not None
        assert "Side mapping error" in error
    
    def test_invalid_side_in_conversion(self):
        """Test invalid side in conversion."""
        is_valid, error = validate_kalshi_format_conversion("invalid", "buy", "BUY_YES")
        assert not is_valid
        assert error is not None


class TestValidateApiSideMapping:
    """Test validation of Kalshi V2 book-side mapping (Bug #3).

    V2 has a single YES-space book.  The book side is determined by the
    *held outcome* produced by the order, not by the action alone:

        BUY_YES  -> long YES -> bid
        SELL_NO  -> long YES -> bid
        BUY_NO   -> long NO  -> ask
        SELL_YES -> long NO  -> ask
    """

    def test_buy_yes_bid_mapping(self):
        """Test BUY_YES -> bid mapping."""
        is_valid, error = validate_api_side_mapping("yes", "buy", "bid")
        assert is_valid
        assert error is None

    def test_sell_yes_ask_mapping(self):
        """Test SELL_YES -> ask mapping."""
        is_valid, error = validate_api_side_mapping("yes", "sell", "ask")
        assert is_valid
        assert error is None

    def test_buy_no_ask_mapping(self):
        """Test BUY_NO -> ask mapping (Bug #3 fix)."""
        is_valid, error = validate_api_side_mapping("no", "buy", "ask")
        assert is_valid
        assert error is None

    def test_sell_no_bid_mapping(self):
        """Test SELL_NO -> bid mapping (Bug #3 fix)."""
        is_valid, error = validate_api_side_mapping("no", "sell", "bid")
        assert is_valid
        assert error is None

    def test_incorrect_buy_yes_mapping(self):
        """Test incorrect BUY_YES mapping (would cause side inversion)."""
        is_valid, error = validate_api_side_mapping("yes", "buy", "ask")
        assert not is_valid
        assert error is not None
        assert "API side mapping error" in error

    def test_incorrect_buy_no_mapping(self):
        """Test incorrect BUY_NO mapping (would cause side inversion)."""
        is_valid, error = validate_api_side_mapping("no", "buy", "bid")
        assert not is_valid
        assert error is not None
        assert "API side mapping error" in error

    def test_incorrect_sell_no_mapping(self):
        """Test incorrect SELL_NO mapping (would cause side inversion)."""
        is_valid, error = validate_api_side_mapping("no", "sell", "ask")
        assert not is_valid
        assert error is not None
        assert "API side mapping error" in error

    def test_invalid_kalshi_side(self):
        """Test invalid Kalshi API side."""
        is_valid, error = validate_api_side_mapping("yes", "buy", "invalid")
        assert not is_valid
        assert error is not None
        assert "Invalid kalshi_side" in error


class TestValidateIntentConsistency:
    """Test validation of intent consistency."""
    
    def test_consistent_buy_yes_intent(self):
        """Test consistent BUY_YES intent."""
        is_valid, error = validate_intent_consistency("yes", "buy", "BUY_YES")
        assert is_valid
        assert error is None
    
    def test_consistent_buy_no_intent(self):
        """Test consistent BUY_NO intent."""
        is_valid, error = validate_intent_consistency("no", "buy", "BUY_NO")
        assert is_valid
        assert error is None
    
    def test_inconsistent_intent_side(self):
        """Test inconsistent intent side."""
        is_valid, error = validate_intent_consistency("yes", "buy", "BUY_NO")
        assert not is_valid
        assert error is not None
        assert "Intent consistency error" in error
    
    def test_inconsistent_intent_action(self):
        """Test inconsistent intent action."""
        is_valid, error = validate_intent_consistency("yes", "buy", "SELL_YES")
        assert not is_valid
        assert error is not None
        assert "Intent consistency error" in error
    
    def test_invalid_kalshi_format(self):
        """Test invalid Kalshi format."""
        is_valid, error = validate_intent_consistency("yes", "buy", "INVALID")
        assert not is_valid
        assert error is not None
        assert "Invalid Kalshi format" in error


class TestValidatePriceSpaceConsistency:
    """Test validation of price space consistency (duality invariant)."""
    
    def test_valid_duality(self):
        """Test valid duality (YES + NO = 100)."""
        is_valid, error = validate_price_space_consistency(65, 35)
        assert is_valid
        assert error is None
    
    def test_valid_duality_with_tolerance(self):
        """Test valid duality within tolerance."""
        is_valid, error = validate_price_space_consistency(65, 35, tolerance_cents=2)
        assert is_valid
        assert error is None
    
    def test_duality_violation(self):
        """Test duality violation."""
        is_valid, error = validate_price_space_consistency(80, 50)
        assert not is_valid
        assert error is not None
        assert "Duality violation" in error
    
    def test_duality_violation_within_tolerance(self):
        """Test duality violation within tolerance."""
        is_valid, error = validate_price_space_consistency(65, 36, tolerance_cents=2)
        assert is_valid
        assert error is None
    
    def test_duality_violation_outside_tolerance(self):
        """Test duality violation outside tolerance."""
        is_valid, error = validate_price_space_consistency(65, 36, tolerance_cents=0)
        assert not is_valid
        assert error is not None


class TestValidateFillSideConsistency:
    """Test validation of fill side consistency (Bug #4)."""
    
    def test_consistent_yes_fill(self):
        """Test consistent YES fill."""
        is_valid, error = validate_fill_side_consistency("yes", "yes", "fill_123", "client_456")
        assert is_valid
        assert error is None
    
    def test_consistent_no_fill(self):
        """Test consistent NO fill."""
        is_valid, error = validate_fill_side_consistency("no", "no", "fill_123", "client_456")
        assert is_valid
        assert error is None
    
    def test_inconsistent_fill_side(self):
        """Test inconsistent fill side (Bug #4)."""
        is_valid, error = validate_fill_side_consistency("yes", "no", "fill_123", "client_456")
        assert not is_valid
        assert error is not None
        assert "Fill side inconsistency" in error
    
    def test_case_insensitive(self):
        """Test case-insensitive validation."""
        is_valid, error = validate_fill_side_consistency("YES", "yes", "fill_123", "client_456")
        assert is_valid
        assert error is None


class TestPreExecutionValidation:
    """Test comprehensive pre-execution validation."""
    
    def test_valid_intent(self):
        """Test valid intent passes validation."""
        intent = {
            "ticker": "TEST_TICKER",
            "side": "yes",
            "action": "buy",
            "kalshi_side": "BUY_YES"
        }
        is_valid, error = pre_execution_validation(intent)
        assert is_valid
        assert error is None
    
    def test_invalid_side_action(self):
        """Test invalid side/action combination."""
        intent = {
            "ticker": "TEST_TICKER",
            "side": "invalid",
            "action": "buy"
        }
        is_valid, error = pre_execution_validation(intent)
        assert not is_valid
        assert error is not None
    
    def test_intent_with_prices(self):
        """Test intent with price space validation."""
        intent = {
            "ticker": "TEST_TICKER",
            "side": "yes",
            "action": "buy",
            "yes_bid_cents": 65,
            "no_bid_cents": 35
        }
        is_valid, error = pre_execution_validation(intent)
        assert is_valid
        assert error is None
    
    def test_intent_with_price_violation(self):
        """Test intent with price space violation."""
        intent = {
            "ticker": "TEST_TICKER",
            "side": "yes",
            "action": "buy",
            "yes_bid_cents": 80,
            "no_bid_cents": 50
        }
        is_valid, error = pre_execution_validation(intent)
        assert not is_valid
        assert error is not None
        assert "Duality violation" in error
    
    def test_intent_without_kalshi_format(self):
        """Test intent without Kalshi format (auto-converts)."""
        intent = {
            "ticker": "TEST_TICKER",
            "side": "yes",
            "action": "buy"
        }
        is_valid, error = pre_execution_validation(intent)
        assert is_valid
        assert error is None


class TestPostExecutionValidation:
    """Test post-execution response validation."""
    
    def test_consistent_response(self):
        """Test consistent response."""
        intent = {
            "ticker": "TEST_TICKER",
            "side": "yes",
            "action": "buy"
        }
        response = {
            "side": "yes",
            "action": "buy"
        }
        is_valid, error = post_execution_validation(intent, response)
        assert is_valid
        assert error is None
    
    def test_inconsistent_response_side(self):
        """Test inconsistent response side."""
        intent = {
            "ticker": "TEST_TICKER",
            "side": "yes",
            "action": "buy"
        }
        response = {
            "side": "no",
            "action": "buy"
        }
        is_valid, error = post_execution_validation(intent, response)
        assert not is_valid
        assert error is not None
        assert "Response side mismatch" in error
    
    def test_inconsistent_response_action(self):
        """Test inconsistent response action."""
        intent = {
            "ticker": "TEST_TICKER",
            "side": "yes",
            "action": "buy"
        }
        response = {
            "side": "yes",
            "action": "sell"
        }
        is_valid, error = post_execution_validation(intent, response)
        assert not is_valid
        assert error is not None
        assert "Response action mismatch" in error
    
    def test_response_without_side_action(self):
        """Test response without side/action (passes)."""
        intent = {
            "ticker": "TEST_TICKER",
            "side": "yes",
            "action": "buy"
        }
        response = {}
        is_valid, error = post_execution_validation(intent, response)
        # Should pass (nothing to validate)
        assert is_valid
        assert error is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
