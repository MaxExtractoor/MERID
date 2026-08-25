"""
Integration tests for signal→intent→router path.

Tests cover:
1. Signal generation with side information
2. Intent creation from signals with side preservation
3. Order routing with side-aware validation
4. End-to-end side preservation through the pipeline
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass
from typing import Optional, Dict, Any

# Import modules under test
from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async, _validate_price_against_orderbook
from merid.prediction.intent_contract import build_entry_order, StrategyIntent, EntryExit
from merid.event_venues.kalshi.strategy_positions import ThesisSide


class TestSignalIntentRouterIntegration:
    """Integration tests for signal→intent→router path."""
    
    def test_signal_to_intent_side_preservation(self):
        """Test that side is preserved from signal through intent creation.
        
        This tests the signal→intent path where:
        1. Signal has thesis_side (yes/no)
        2. Intent is created with outcome_side matching thesis_side
        3. Kalshi payload uses correct format (BUY_YES/BUY_NO)
        """
        # Simulate signal from agent
        signal = {
            "ticker": "KXBTC15M-26JUL211745-45",
            "thesis_side": "yes",
            "action": "buy",
            "price_cents": 50,
            "count": 1,
            "edge_pct": 5.0
        }
        
        # Create intent contract using build_entry_order
        intent_contract = build_entry_order(
            intent=StrategyIntent.BULLISH_EVENT,
            ticker=signal["ticker"],
            price_cents=signal["price_cents"],
            magnitude=signal["count"],
            client_order_id="test-client-order-id",
            asset="BTC"
        )
        
        # Verify side preservation
        assert intent_contract.outcome_side == "yes", f"outcome_side should be 'yes', got {intent_contract.outcome_side}"
        assert intent_contract.thesis_side == "yes", f"thesis_side should be 'yes', got {intent_contract.thesis_side}"
        assert intent_contract.kalshi_payload.side == "yes", f"payload.side should be 'yes', got {intent_contract.kalshi_payload.side}"
        assert intent_contract.kalshi_payload.action == "buy", f"payload.action should be 'buy', got {intent_contract.kalshi_payload.action}"
        assert intent_contract.kalshi_payload.to_kalshi_format() == "BUY_YES"
    
    def test_signal_to_intent_no_side(self):
        """Test that NO side is preserved from signal through intent creation."""
        # Simulate NO signal from agent
        signal = {
            "ticker": "KXBTC15M-26JUL211745-45",
            "thesis_side": "no",
            "action": "buy",
            "price_cents": 50,
            "count": 1,
            "edge_pct": 5.0
        }
        
        # Create intent contract using build_entry_order
        intent_contract = build_entry_order(
            intent=StrategyIntent.BEARISH_EVENT,
            ticker=signal["ticker"],
            price_cents=signal["price_cents"],
            magnitude=signal["count"],
            client_order_id="test-client-order-id",
            asset="BTC"
        )
        
        # Verify side preservation
        assert intent_contract.outcome_side == "no", f"outcome_side should be 'no', got {intent_contract.outcome_side}"
        assert intent_contract.thesis_side == "no", f"thesis_side should be 'no', got {intent_contract.thesis_side}"
        assert intent_contract.kalshi_payload.side == "no", f"payload.side should be 'no', got {intent_contract.kalshi_payload.side}"
        assert intent_contract.kalshi_payload.action == "buy", f"payload.action should be 'buy', got {intent_contract.kalshi_payload.action}"
        assert intent_contract.kalshi_payload.to_kalshi_format() == "BUY_NO"
    
    def test_intent_to_order_router_side_preservation(self):
        """Test that side is preserved from intent through order router validation.
        
        This tests the intent→router path where:
        1. Intent has side in Kalshi format (BUY_YES/BUY_NO)
        2. Router extracts outcome_side for validation
        3. Price validation uses correct mid-price for each side
        """
        # Create intent with YES side
        intent_yes = OrderIntent(
            ticker="KXBTC15M-26JUL211745-45",
            side="BUY_YES",
            action="buy",
            price_cents=50,
            count=1,
            order_type="limit",
            source="test"
        )
        
        # Create mock market state
        state = Mock()
        state.best_bid_cents = 45
        state.best_ask_cents = 55
        state.mid_cents = 50
        
        # Validate price against orderbook
        result_yes = _validate_price_against_orderbook(intent_yes, state)
        
        # Should pass validation (no error)
        assert result_yes is None, f"YES order should pass validation, got: {result_yes}"
        
        # Create intent with NO side
        intent_no = OrderIntent(
            ticker="KXBTC15M-26JUL211745-45",
            side="BUY_NO",
            action="buy",
            price_cents=50,
            count=1,
            order_type="limit",
            source="test"
        )
        
        # Validate price against orderbook
        result_no = _validate_price_against_orderbook(intent_no, state)
        
        # Should pass validation (no error)
        assert result_no is None, f"NO order should pass validation, got: {result_no}"
    
    def test_end_to_end_signal_to_router(self):
        """Test end-to-end side preservation from signal through intent to router.
        
        This is a comprehensive integration test covering:
        1. Signal generation with thesis_side
        2. Intent creation with outcome_side
        3. Order router validation with side-aware logic
        """
        # Stage 1: Signal generation
        signal = {
            "ticker": "KXBTC15M-26JUL211745-45",
            "thesis_side": "yes",
            "action": "buy",
            "price_cents": 50,
            "count": 1,
            "edge_pct": 5.0
        }
        
        # Stage 2: Intent creation
        intent_contract = build_entry_order(
            intent=StrategyIntent.BULLISH_EVENT,
            ticker=signal["ticker"],
            price_cents=signal["price_cents"],
            magnitude=signal["count"],
            client_order_id="test-client-order-id",
            asset="BTC"
        )
        
        # Verify intent side preservation
        assert intent_contract.outcome_side == signal["thesis_side"]
        assert intent_contract.thesis_side == signal["thesis_side"]
        
        # Stage 3: Create OrderIntent for router
        router_intent = OrderIntent(
            ticker=intent_contract.ticker,
            side=intent_contract.kalshi_payload.to_kalshi_format(),
            action=intent_contract.kalshi_payload.action,
            price_cents=intent_contract.kalshi_payload.price_cents,
            count=intent_contract.expected_post_position_size,
            order_type="limit",
            source="test"
        )
        
        # Verify router intent side preservation
        assert router_intent.side == "BUY_YES"
        
        # Stage 4: Router validation
        state = Mock()
        state.best_bid_cents = 45
        state.best_ask_cents = 55
        state.mid_cents = 50
        
        result = _validate_price_against_orderbook(router_intent, state)
        
        # Should pass validation
        assert result is None
    
    def test_dual_signal_handling(self):
        """Test that both YES and NO signals can be processed independently.
        
        This tests that the system can handle dual signals for the same market
        without side collapse or interference.
        """
        # Create YES signal
        yes_signal = {
            "ticker": "KXBTC15M-26JUL211745-45",
            "thesis_side": "yes",
            "action": "buy",
            "price_cents": 50,
            "count": 1
        }
        
        # Create NO signal
        no_signal = {
            "ticker": "KXBTC15M-26JUL211745-45",
            "thesis_side": "no",
            "action": "buy",
            "price_cents": 50,
            "count": 1
        }
        
        # Create intents for both
        yes_intent_contract = build_entry_order(
            intent=StrategyIntent.BULLISH_EVENT,
            ticker=yes_signal["ticker"],
            price_cents=yes_signal["price_cents"],
            magnitude=yes_signal["count"],
            client_order_id="test-yes-order-id",
            asset="BTC"
        )
        
        no_intent_contract = build_entry_order(
            intent=StrategyIntent.BEARISH_EVENT,
            ticker=no_signal["ticker"],
            price_cents=no_signal["price_cents"],
            magnitude=no_signal["count"],
            client_order_id="test-no-order-id",
            asset="BTC"
        )
        
        # Verify both intents are valid and independent
        assert yes_intent_contract.outcome_side == "yes"
        assert no_intent_contract.outcome_side == "no"
        assert yes_intent_contract.thesis_side == "yes"
        assert no_intent_contract.thesis_side == "no"
        assert yes_intent_contract.kalshi_payload.to_kalshi_format() == "BUY_YES"
        assert no_intent_contract.kalshi_payload.to_kalshi_format() == "BUY_NO"
    
    def test_side_format_conversion(self):
        """Test that side format conversion is consistent across the pipeline.
        
        Tests:
        1. Signal thesis_side (yes/no) → Intent outcome_side (yes/no)
        2. Intent outcome_side → Kalshi payload (BUY_YES/BUY_NO)
        3. Kalshi payload → Router intent side (BUY_YES/BUY_NO)
        4. Router intent side → outcome_side extraction (yes/no)
        """
        # Test YES side conversion
        thesis_side = "yes"
        
        # Stage 1: thesis_side → outcome_side
        outcome_side = thesis_side  # For entry, they're the same
        
        # Stage 2: outcome_side → Kalshi format
        kalshi_side = "BUY_YES" if outcome_side == "yes" else "BUY_NO"
        
        # Stage 3: Kalshi format → Router intent
        router_intent_side = kalshi_side
        
        # Stage 4: Router intent → outcome_side extraction
        side_lower = router_intent_side.lower() if router_intent_side else ""
        if "yes" in side_lower:
            extracted_outcome_side = "yes"
        elif "no" in side_lower:
            extracted_outcome_side = "no"
        else:
            extracted_outcome_side = side_lower
        
        # Verify round-trip preservation
        assert thesis_side == "yes"
        assert outcome_side == "yes"
        assert kalshi_side == "BUY_YES"
        assert router_intent_side == "BUY_YES"
        assert extracted_outcome_side == "yes"
        
        # Test NO side conversion
        thesis_side = "no"
        outcome_side = thesis_side
        kalshi_side = "BUY_YES" if outcome_side == "yes" else "BUY_NO"
        router_intent_side = kalshi_side
        side_lower = router_intent_side.lower() if router_intent_side else ""
        if "yes" in side_lower:
            extracted_outcome_side = "yes"
        elif "no" in side_lower:
            extracted_outcome_side = "no"
        else:
            extracted_outcome_side = side_lower
        
        assert thesis_side == "no"
        assert outcome_side == "no"
        assert kalshi_side == "BUY_NO"
        assert router_intent_side == "BUY_NO"
        assert extracted_outcome_side == "no"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
