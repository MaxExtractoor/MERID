"""
Integration tests for full lifecycle (entry → exit) thesis_side invariant.

Tests the complete trading flow from signal generation through intent construction,
order routing, fill processing, position caching, and exit order generation to ensure
thesis_side is preserved throughout the entire lifecycle.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from merid.event_venues.kalshi.strategy_positions import (
    ThesisSide,
    FillRecord,
    StrategyPosition,
    thesis_to_outcome_side,
    build_exit_order,
)
from merid.prediction.intent_contract import (
    IntentContract,
    StrategyIntent,
    EntryExit,
    ExposureLeg,
    ExposureChange,
    KalshiSidePayload,
    ExitReason,
)


class TestFullLifecycleThesisInvariant:
    """Test thesis_side invariant through full trading lifecycle."""
    
    def test_signal_to_intent_thesis_mapping(self):
        """Test that signal action correctly maps to thesis_side in intent."""
        # Simulate BULLISH_EVENT signal → YES thesis
        intent = IntentContract(
            strategy_intent=StrategyIntent.BULLISH_EVENT,
            entry_or_exit=EntryExit.ENTRY,
            target_leg=ExposureLeg.YES,
            exposure_change=ExposureChange(
                leg=ExposureLeg.YES,
                direction="increase",
                magnitude=10,
            ),
            outcome_side="yes",
            thesis_side="yes",
            kalshi_payload=KalshiSidePayload(
                side="yes",
                action="buy",
                price_cents=50,
            ),
            asset="BTC",
            ticker="KXBTC15M-26JUL211745-45",
            expected_post_position_size=10,  # Must match exposure_change.magnitude for ENTRY
        )
        
        # Validate intent
        is_valid, error = intent.validate()
        assert is_valid, f"Intent validation failed: {error}"
        assert intent.thesis_side == "yes"
        assert intent.outcome_side == "yes"
    
    def test_bearish_signal_to_no_thesis(self):
        """Test that BEARISH_EVENT signal correctly maps to NO thesis."""
        intent = IntentContract(
            strategy_intent=StrategyIntent.BEARISH_EVENT,
            entry_or_exit=EntryExit.ENTRY,
            target_leg=ExposureLeg.NO,
            exposure_change=ExposureChange(
                leg=ExposureLeg.NO,
                direction="increase",
                magnitude=10,
            ),
            outcome_side="no",
            thesis_side="no",
            kalshi_payload=KalshiSidePayload(
                side="no",
                action="buy",
                price_cents=50,
            ),
            asset="BTC",
            ticker="KXBTC15M-26JUL211745-45",
            expected_post_position_size=10,  # Must match exposure_change.magnitude for ENTRY
        )
        
        # Validate intent
        is_valid, error = intent.validate()
        assert is_valid, f"Intent validation failed: {error}"
        assert intent.thesis_side == "no"
        assert intent.outcome_side == "no"
    
    def test_intent_validation_prevents_mismatched_thesis(self):
        """Test that intent validation rejects mismatched outcome_side and thesis_side."""
        intent = IntentContract(
            strategy_intent=StrategyIntent.BULLISH_EVENT,
            entry_or_exit=EntryExit.ENTRY,
            target_leg=ExposureLeg.YES,
            exposure_change=ExposureChange(
                leg=ExposureLeg.YES,
                direction="increase",
                magnitude=10,
            ),
            outcome_side="yes",
            thesis_side="no",  # Mismatch!
            kalshi_payload=KalshiSidePayload(
                side="yes",
                action="buy",
                price_cents=50,
            ),
            asset="BTC",
            ticker="KXBTC15M-26JUL211745-45",
        )
        
        # Validate intent - should fail
        is_valid, error = intent.validate()
        assert not is_valid
        assert "outcome_side" in error.lower() or "thesis_side" in error.lower()
    
    def test_entry_fill_creates_strategy_position(self):
        """Test that entry fill creates StrategyPosition with correct thesis_side."""
        position = StrategyPosition(
            ticker="KXBTC15M-26JUL211745-45",
            thesis_side=ThesisSide.YES,
            size_fp=0,  # Start with zero, fills will build size
            avg_entry_price_cents=50,
        )
        
        # Add entry fill
        fill = FillRecord(
            timestamp=datetime.utcnow(),
            fill_id="fill_1",
            side="yes",
            action="buy",
            outcome_side="yes",
            count_fp=10,
            price_cents=50,
            fee_cents=1,
            intent_side="yes",
        )
        
        position.add_entry_fill(fill)
        
        # Assert position state
        assert position.thesis_side == ThesisSide.YES
        assert position.size_fp == 10
        assert len(position.entry_fills) == 1
        assert position.is_open is True
    
    def test_exit_fill_decreases_position_size(self):
        """Test that exit fill decreases position size while preserving thesis_side."""
        position = StrategyPosition(
            ticker="KXBTC15M-26JUL211745-45",
            thesis_side=ThesisSide.YES,
            size_fp=0,  # Start with zero
            avg_entry_price_cents=50,
        )
        
        # Add entry fill
        entry_fill = FillRecord(
            timestamp=datetime.utcnow(),
            fill_id="fill_1",
            side="yes",
            action="buy",
            outcome_side="yes",
            count_fp=10,
            price_cents=50,
            fee_cents=1,
            intent_side="yes",
        )
        position.add_entry_fill(entry_fill)
        
        # Add exit fill
        exit_fill = FillRecord(
            timestamp=datetime.utcnow(),
            fill_id="fill_2",
            side="yes",
            action="sell",
            outcome_side="yes",
            count_fp=5,
            price_cents=55,
            fee_cents=1,
            intent_side="yes",
        )
        position.add_exit_fill(exit_fill)
        
        # Assert position state
        assert position.thesis_side == ThesisSide.YES  # Preserved
        assert position.size_fp == 5  # Decreased
        assert len(position.exit_fills) == 1
        assert position.is_open is True
    
    def test_exit_order_generation_preserves_thesis(self):
        """Test that exit order generation uses thesis_side correctly."""
        position = StrategyPosition(
            ticker="KXBTC15M-26JUL211745-45",
            thesis_side=ThesisSide.YES,
            size_fp=10,
            avg_entry_price_cents=50,
        )
        
        # Build exit order
        exit_order = build_exit_order(position, qty_fp=5, price_cents=75)
        
        # Assert exit order uses correct thesis
        assert exit_order["thesis_side"] == "yes"
        assert exit_order["outcome_side"] == "yes"
        assert exit_order["kalshi_side"] == "SELL_YES"
        assert exit_order["size_fp"] == 5
    
    def test_exit_order_generation_no_thesis(self):
        """Test that exit order generation for NO thesis produces SELL_NO."""
        position = StrategyPosition(
            ticker="KXBTC15M-26JUL211745-45",
            thesis_side=ThesisSide.NO,
            size_fp=10,
            avg_entry_price_cents=50,
        )
        
        # Build exit order
        exit_order = build_exit_order(position, qty_fp=5, price_cents=75)
        
        # Assert exit order uses correct thesis
        assert exit_order["thesis_side"] == "no"
        assert exit_order["outcome_side"] == "no"
        assert exit_order["kalshi_side"] == "SELL_NO"
        assert exit_order["size_fp"] == 5
    
    def test_full_lifecycle_yes_entry_yes_exit(self):
        """Test full lifecycle: YES entry → YES exit (correct thesis preservation)."""
        # Step 1: Signal → Intent (BULLISH_EVENT → YES thesis)
        intent = IntentContract(
            strategy_intent=StrategyIntent.BULLISH_EVENT,
            entry_or_exit=EntryExit.ENTRY,
            target_leg=ExposureLeg.YES,
            exposure_change=ExposureChange(
                leg=ExposureLeg.YES,
                direction="increase",
                magnitude=10,
            ),
            outcome_side="yes",
            thesis_side="yes",
            kalshi_payload=KalshiSidePayload(
                side="yes",
                action="buy",
                price_cents=50,
            ),
            asset="BTC",
            ticker="KXBTC15M-26JUL211745-45",
            expected_post_position_size=10,  # Must match exposure_change.magnitude for ENTRY
        )
        is_valid, _ = intent.validate()
        assert is_valid
        
        # Step 2: Entry fill → StrategyPosition
        position = StrategyPosition(
            ticker=intent.ticker,
            thesis_side=ThesisSide.from_outcome_side(intent.thesis_side),
            size_fp=0,  # Start with zero, fills will build size
            avg_entry_price_cents=intent.kalshi_payload.price_cents,
        )
        
        entry_fill = FillRecord(
            timestamp=datetime.utcnow(),
            fill_id="fill_entry",
            side=intent.kalshi_payload.side,
            action=intent.kalshi_payload.action,
            outcome_side=intent.outcome_side,
            count_fp=intent.exposure_change.magnitude,
            price_cents=intent.kalshi_payload.price_cents,
            fee_cents=1,
            intent_side=intent.outcome_side,
        )
        position.add_entry_fill(entry_fill)
        
        # Step 3: Exit order generation
        exit_order = build_exit_order(position, qty_fp=10, price_cents=75)
        
        # Step 4: Exit fill
        exit_fill = FillRecord(
            timestamp=datetime.utcnow(),
            fill_id="fill_exit",
            side=exit_order["side"],
            action=exit_order["action"],
            outcome_side=exit_order["outcome_side"],
            count_fp=exit_order["size_fp"],
            price_cents=exit_order["price_cents"],
            fee_cents=1,
            intent_side=exit_order["outcome_side"],
        )
        position.add_exit_fill(exit_fill)
        
        # Assert thesis_side preserved throughout lifecycle
        assert position.thesis_side == ThesisSide.YES
        assert exit_order["thesis_side"] == "yes"
        assert exit_order["kalshi_side"] == "SELL_YES"
        assert position.size_fp == 0  # Fully closed
    
    def test_full_lifecycle_no_entry_no_exit(self):
        """Test full lifecycle: NO entry → NO exit (correct thesis preservation)."""
        # Step 1: Signal → Intent (BEARISH_EVENT → NO thesis)
        intent = IntentContract(
            strategy_intent=StrategyIntent.BEARISH_EVENT,
            entry_or_exit=EntryExit.ENTRY,
            target_leg=ExposureLeg.NO,
            exposure_change=ExposureChange(
                leg=ExposureLeg.NO,
                direction="increase",
                magnitude=10,
            ),
            outcome_side="no",
            thesis_side="no",
            kalshi_payload=KalshiSidePayload(
                side="no",
                action="buy",
                price_cents=50,
            ),
            asset="BTC",
            ticker="KXBTC15M-26JUL211745-45",
            expected_post_position_size=10,  # Must match exposure_change.magnitude for ENTRY
        )
        is_valid, _ = intent.validate()
        assert is_valid
        
        # Step 2: Entry fill → StrategyPosition
        position = StrategyPosition(
            ticker=intent.ticker,
            thesis_side=ThesisSide.from_outcome_side(intent.thesis_side),
            size_fp=0,  # Start with zero, fills will build size
            avg_entry_price_cents=intent.kalshi_payload.price_cents,
        )
        
        entry_fill = FillRecord(
            timestamp=datetime.utcnow(),
            fill_id="fill_entry",
            side=intent.kalshi_payload.side,
            action=intent.kalshi_payload.action,
            outcome_side=intent.outcome_side,
            count_fp=intent.exposure_change.magnitude,
            price_cents=intent.kalshi_payload.price_cents,
            fee_cents=1,
            intent_side=intent.outcome_side,
        )
        position.add_entry_fill(entry_fill)
        
        # Step 3: Exit order generation
        exit_order = build_exit_order(position, qty_fp=10, price_cents=75)
        
        # Step 4: Exit fill
        exit_fill = FillRecord(
            timestamp=datetime.utcnow(),
            fill_id="fill_exit",
            side=exit_order["side"],
            action=exit_order["action"],
            outcome_side=exit_order["outcome_side"],
            count_fp=exit_order["size_fp"],
            price_cents=exit_order["price_cents"],
            fee_cents=1,
            intent_side=exit_order["outcome_side"],
        )
        position.add_exit_fill(exit_fill)
        
        # Assert thesis_side preserved throughout lifecycle
        assert position.thesis_side == ThesisSide.NO
        assert exit_order["thesis_side"] == "no"
        assert exit_order["kalshi_side"] == "SELL_NO"
        assert position.size_fp == 0  # Fully closed
    
    def test_thesis_to_outcome_side_mapping(self):
        """Test thesis_to_outcome_side pure function mapping."""
        assert thesis_to_outcome_side(ThesisSide.YES) == "yes"
        assert thesis_to_outcome_side(ThesisSide.NO) == "no"
    
    def test_partial_exit_preserves_thesis(self):
        """Test that partial exit preserves thesis_side."""
        position = StrategyPosition(
            ticker="KXBTC15M-26JUL211745-45",
            thesis_side=ThesisSide.YES,
            size_fp=0,  # Start with zero
            avg_entry_price_cents=50,
        )
        
        # Add entry fill
        entry_fill = FillRecord(
            timestamp=datetime.utcnow(),
            fill_id="fill_1",
            side="yes",
            action="buy",
            outcome_side="yes",
            count_fp=10,
            price_cents=50,
            fee_cents=1,
            intent_side="yes",
        )
        position.add_entry_fill(entry_fill)
        
        # Partial exit (5 of 10)
        exit_order = build_exit_order(position, qty_fp=5, price_cents=75)
        exit_fill = FillRecord(
            timestamp=datetime.utcnow(),
            fill_id="fill_2",
            side=exit_order["side"],
            action=exit_order["action"],
            outcome_side=exit_order["outcome_side"],
            count_fp=exit_order["size_fp"],
            price_cents=exit_order["price_cents"],
            fee_cents=1,
            intent_side=exit_order["outcome_side"],
        )
        position.add_exit_fill(exit_fill)
        
        # Assert thesis preserved, size decreased
        assert position.thesis_side == ThesisSide.YES
        assert position.size_fp == 5
        assert position.is_open is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
