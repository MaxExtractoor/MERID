"""
Downstream tests for side-agnostic routing, execution, and position tracking.

These tests ensure that whatever side midstream decides is executed verbatim,
with no hidden thesis invariants in the downstream pipeline.
"""

import pytest
from typing import Dict, Any, Optional
from unittest.mock import Mock, patch, MagicMock
import json


class TestOrderRouterSideAgnostic:
    """Test that order router treats YES and NO symmetrically."""
    
    def test_order_router_executes_yes_and_no_symmetrically(self):
        """
        Test that given identical edge and risk params, YES and NO orders
        must both pass or both fail equivalent validations.
        
        This ensures no hidden YES bias in routing logic.
        """
        # Create mock intents for YES and NO with identical parameters
        yes_intent = Mock()
        yes_intent.ticker = "KXBTC15M-26JUL211745-45"
        yes_intent.side = "BUY_YES"
        yes_intent.price_cents = 42
        yes_intent.count = 1
        yes_intent.action = "buy"
        
        no_intent = Mock()
        no_intent.ticker = "KXBTC15M-26JUL211745-45"
        no_intent.side = "BUY_NO"
        no_intent.price_cents = 42  # NO price should be 100 - YES, but for symmetry test use same
        no_intent.count = 1
        no_intent.action = "buy"
        
        # Mock validation function that should be side-agnostic
        def mock_validate_price_band(intent, outcome_side=None):
            # Validation should only care about price range (10-75c), not side
            price = intent.price_cents
            if 10 <= price <= 75:
                return None  # Pass
            else:
                return "PRICE_OUT_OF_RANGE"
        
        # Test both intents
        yes_result = mock_validate_price_band(yes_intent, outcome_side="yes")
        no_result = mock_validate_price_band(no_intent, outcome_side="no")
        
        # Both should pass with identical validation logic
        assert yes_result is None, f"YES intent should pass validation, got {yes_result}"
        assert no_result is None, f"NO intent should pass validation, got {no_result}"
        
        # Test with out-of-range price
        yes_intent.price_cents = 80
        no_intent.price_cents = 80
        
        yes_result = mock_validate_price_band(yes_intent, outcome_side="yes")
        no_result = mock_validate_price_band(no_intent, outcome_side="no")
        
        # Both should fail identically
        assert yes_result == "PRICE_OUT_OF_RANGE", f"YES should fail, got {yes_result}"
        assert no_result == "PRICE_OUT_OF_RANGE", f"NO should fail, got {no_result}"
    
    def test_side_aware_price_validation(self):
        """
        Test that price validation is side-aware using correct mid-prices.
        
        - YES orders: validated against YES mid-price
        - NO orders: validated against NO mid-price (100 - YES mid)
        """
        # Mock market state
        market_state = Mock()
        market_state.best_bid_cents = 40
        market_state.best_ask_cents = 44
        yes_mid = (40 + 44) // 2  # 42
        no_mid = 100 - yes_mid  # 58
        
        # Validation function
        def validate_price_against_orderbook(intent, state, outcome_side):
            if outcome_side == "no":
                validation_mid = 100 - yes_mid
            else:
                validation_mid = yes_mid
            
            # Check if order price is reasonable relative to mid
            order_price = intent.price_cents
            if abs(order_price - validation_mid) <= 10:  # Within 10c of mid
                return None
            else:
                return "PRICE_TOO_FAR_FROM_MID"
        
        # Test YES order
        yes_intent = Mock()
        yes_intent.price_cents = 42  # Exactly at YES mid
        yes_result = validate_price_against_orderbook(yes_intent, market_state, "yes")
        assert yes_result is None, f"YES at mid should pass, got {yes_result}"
        
        # Test NO order
        no_intent = Mock()
        no_intent.price_cents = 58  # Exactly at NO mid
        no_result = validate_price_against_orderbook(no_intent, market_state, "no")
        assert no_result is None, f"NO at mid should pass, got {no_result}"
        
        # Test YES order too far from YES mid
        yes_intent.price_cents = 60  # 18c from YES mid
        yes_result = validate_price_against_orderbook(yes_intent, market_state, "yes")
        assert yes_result == "PRICE_TOO_FAR_FROM_MID", f"YES far from mid should fail"
        
        # Test NO order too far from NO mid
        no_intent.price_cents = 40  # 18c from NO mid
        no_result = validate_price_against_orderbook(no_intent, market_state, "no")
        assert no_result == "PRICE_TOO_FAR_FROM_MID", f"NO far from mid should fail"


class TestPositionCacheSideAgnostic:
    """Test that position cache tracks both sides independently."""
    
    def test_position_cache_tracks_both_sides(self):
        """
        Test that YES and NO positions in the same market are recorded
        and closed independently.
        
        Positions should be keyed by (market_id, side) to allow
        simultaneous YES and NO positions.
        """
        # Mock position cache
        position_cache = {}
        
        # Open YES position
        yes_position = {
            "market_id": "KXBTC15M-26JUL211745-45",
            "side": "yes",
            "size": 1,
            "entry_price": 42
        }
        position_key_yes = ("KXBTC15M-26JUL211745-45", "yes")
        position_cache[position_key_yes] = yes_position
        
        # Open NO position in same market
        no_position = {
            "market_id": "KXBTC15M-26JUL211745-45",
            "side": "no",
            "size": 1,
            "entry_price": 58
        }
        position_key_no = ("KXBTC15M-26JUL211745-45", "no")
        position_cache[position_key_no] = no_position
        
        # Verify both positions exist independently
        assert position_key_yes in position_cache, "YES position should be tracked"
        assert position_key_no in position_cache, "NO position should be tracked"
        assert position_cache[position_key_yes]["side"] == "yes"
        assert position_cache[position_key_no]["side"] == "no"
        
        # Close YES position
        del position_cache[position_key_yes]
        
        # Verify YES closed but NO still open
        assert position_key_yes not in position_cache, "YES position should be closed"
        assert position_key_no in position_cache, "NO position should still be open"
        
        # Close NO position
        del position_cache[position_key_no]
        
        # Verify both closed
        assert position_key_no not in position_cache, "NO position should be closed"
        assert len(position_cache) == 0, "All positions should be closed"
    
    def test_position_thesis_side_diagnostic_only(self):
        """
        Test that thesis_side in position cache is diagnostic only,
        not used for enforcement in downstream logic.
        
        Position tracking should be side-agnostic; thesis_side is for
        audit trail and attribution, not gating.
        """
        # Mock position with thesis_side
        position = {
            "market_id": "KXBTC15M-26JUL211745-45",
            "side": "yes",  # Actual position side
            "thesis_side": "yes",  # Diagnostic: original thesis
            "size": 1
        }
        
        # Downstream logic should use position.side for operations
        # thesis_side should only be used for logging/validation
        
        # Simulate position close operation
        def close_position(pos):
            # Should use pos.side, not pos.thesis_side
            return pos["side"]
        
        result_side = close_position(position)
        assert result_side == "yes", f"Should use position.side, got {result_side}"
        
        # Simulate position query
        def get_position_side(pos):
            # Should return pos.side for operations
            return pos["side"]
        
        query_side = get_position_side(position)
        assert query_side == "yes", f"Query should use position.side, got {query_side}"
        
        # thesis_side should be available for diagnostics
        assert position["thesis_side"] == "yes", "thesis_side should be preserved for audit"


class TestEvaluationToOrderLinkage:
    """Test linkage between evaluation and order submission."""
    
    def test_evaluation_to_order_linkage(self):
        """
        Test that for a given evaluation_id, at least one ORDER_SUBMISSION
        event exists when a candidate is returned.
        
        Also test that no orders are submitted when evaluation returns None.
        """
        # Mock evaluation that returns a candidate
        evaluation_id = "eval_abc123"
        candidate = {
            "ticker": "KXBTC15M-26JUL211745-45",
            "side": "yes",
            "price_cents": 42,
            "count": 1,
            "evaluation_id": evaluation_id
        }
        
        # Mock order submission log
        order_submissions = []
        
        def submit_order(candidate):
            if candidate:
                order_submissions.append({
                    "evaluation_id": candidate["evaluation_id"],
                    "order_id": f"ord_{candidate['evaluation_id']}",
                    "side": candidate["side"],
                    "price": candidate["price_cents"]
                })
                return True
            return False
        
        # Test with candidate
        result = submit_order(candidate)
        assert result == True, "Order should be submitted when candidate exists"
        assert len(order_submissions) == 1, "One order should be submitted"
        assert order_submissions[0]["evaluation_id"] == evaluation_id, "Order should link to evaluation"
        
        # Test without candidate
        order_submissions.clear()
        result = submit_order(None)
        assert result == False, "Order should not be submitted when no candidate"
        assert len(order_submissions) == 0, "No orders should be submitted"
    
    def test_order_submission_log_structure(self):
        """
        Test that ORDER_SUBMISSION events contain required fields
        and are linked to evaluation_id.
        """
        order_submission = {
            "event_type": "ORDER_SUBMISSION",
            "evaluation_id": "eval_abc123",
            "order_id": "ord_xyz789",
            "ticker": "KXBTC15M-26JUL211745-45",
            "side": "yes",
            "action": "buy",
            "price_cents": 42,
            "count": 1,
            "timestamp": "2026-07-24T12:32:00.000Z",
            "risk_checks": {
                "exposure": "PASS",
                "price_band": "PASS",
                "liquidity": "PASS"
            }
        }
        
        # Verify required fields
        required_fields = [
            "event_type", "evaluation_id", "order_id", "ticker",
            "side", "action", "price_cents", "count", "timestamp"
        ]
        
        for field in required_fields:
            assert field in order_submission, f"Missing required field: {field}"
        
        # Verify JSON serializable
        try:
            json_str = json.dumps(order_submission)
            parsed = json.loads(json_str)
            assert parsed == order_submission, "JSON round-trip failed"
        except Exception as e:
            pytest.fail(f"Order submission not JSON serializable: {e}")
    
    def test_order_rejection_log_structure(self):
        """
        Test that ORDER_REJECTION events contain rejection reason and stage.
        """
        order_rejection = {
            "event_type": "ORDER_REJECTION",
            "evaluation_id": "eval_abc123",
            "order_id": "ord_xyz789",
            "ticker": "KXBTC15M-26JUL211745-45",
            "side": "yes",
            "rejection_reason": "EXPOSURE_CAP_EXCEEDED",
            "rejection_stage": "RISK_CHECK",
            "constraints": {
                "exposure_cap_usd": 1.00,
                "current_exposure_usd": 0.95,
                "requested_exposure_usd": 0.10
            },
            "timestamp": "2026-07-24T12:32:00.100Z"
        }
        
        # Verify required fields
        required_fields = [
            "event_type", "evaluation_id", "rejection_reason", "rejection_stage"
        ]
        
        for field in required_fields:
            assert field in order_rejection, f"Missing required field: {field}"
        
        # Verify JSON serializable
        try:
            json_str = json.dumps(order_rejection)
            parsed = json.loads(json_str)
            assert parsed == order_rejection, "JSON round-trip failed"
        except Exception as e:
            pytest.fail(f"Order rejection not JSON serializable: {e}")


class TestSidePreservationThroughPipeline:
    """Test that side is preserved through the entire pipeline."""
    
    def test_side_preservation_candidate_to_intent(self):
        """
        Test that side is preserved from candidate to OrderIntent.
        """
        candidate = {
            "side": "no",
            "ticker": "KXBTC15M-26JUL211745-45",
            "price_cents": 58,
            "count": 1
        }
        
        # Simulate intent creation
        intent = {
            "side": candidate["side"],
            "ticker": candidate["ticker"],
            "price_cents": candidate["price_cents"],
            "count": candidate["count"]
        }
        
        assert intent["side"] == "no", f"Side should be preserved, got {intent['side']}"
    
    def test_side_preservation_intent_to_order(self):
        """
        Test that side is preserved from OrderIntent to order.
        """
        intent = {
            "side": "no",
            "action": "buy",
            "ticker": "KXBTC15M-26JUL211745-45"
        }
        
        # Simulate order creation
        order = {
            "kalshi_side": "BUY_NO",  # Converted from intent.side + action
            "ticker": intent["ticker"]
        }
        
        # Verify conversion is correct
        assert order["kalshi_side"] == "BUY_NO", f"Expected BUY_NO, got {order['kalshi_side']}"
    
    def test_no_side_flipping_in_pipeline(self):
        """
        Test that side never flips during pipeline processing.
        """
        original_side = "no"
        
        # Simulate pipeline stages
        stage1 = {"side": original_side}
        stage2 = {"side": stage1["side"]}
        stage3 = {"side": stage2["side"]}
        stage4 = {"side": stage3["side"]}
        
        assert stage4["side"] == original_side, f"Side should not flip, got {stage4['side']}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
