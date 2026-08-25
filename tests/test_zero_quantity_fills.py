"""
Tests for zero-quantity fill handling (V15).

Zero-quantity fills should be treated as telemetry only and not change
position size or thesis_side.
"""

import pytest
from datetime import datetime
from merid.event_venues.kalshi.strategy_positions import StrategyPosition, FillRecord, ThesisSide


def test_zero_quantity_entry_fill_ignored():
    """Test that 0-quantity entry fills are ignored and don't change position state."""
    # Create a position with an initial entry
    position = StrategyPosition(
        ticker="KXBTC15M-TEST",
        agent_id="BTC_15M",
        thesis_side=ThesisSide.YES,
        size_fp=0,
        avg_entry_price_cents=50
    )
    
    # Add a normal entry fill
    normal_fill = FillRecord(
        timestamp=datetime.utcnow(),
        fill_id="fill_1",
        side="yes",
        action="buy",
        outcome_side="yes",
        count_fp=10,
        price_cents=50,
        fee_cents=1,
        intent_side="yes"
    )
    position.add_entry_fill(normal_fill)
    
    assert position.size_fp == 10
    assert len(position.entry_fills) == 1
    
    # Add a 0-quantity fill - should be ignored
    zero_fill = FillRecord(
        timestamp=datetime.utcnow(),
        fill_id="fill_2",
        side="yes",
        action="buy",
        outcome_side="yes",
        count_fp=0,
        price_cents=55,
        fee_cents=0,
        intent_side="yes"
    )
    position.add_entry_fill(zero_fill)
    
    # Position state should not change
    assert position.size_fp == 10
    assert len(position.entry_fills) == 1  # Zero fill not added
    assert position.thesis_side == ThesisSide.YES


def test_zero_quantity_exit_fill_ignored():
    """Test that 0-quantity exit fills are ignored and don't change position state."""
    # Create a position with an initial entry
    position = StrategyPosition(
        ticker="KXETH15M-TEST",
        agent_id="ETH_15M",
        thesis_side=ThesisSide.NO,
        size_fp=0,
        avg_entry_price_cents=50
    )
    
    # Add a normal entry fill
    entry_fill = FillRecord(
        timestamp=datetime.utcnow(),
        fill_id="fill_1",
        side="no",
        action="sell",
        outcome_side="no",
        count_fp=10,
        price_cents=50,
        fee_cents=1,
        intent_side="no"
    )
    position.add_entry_fill(entry_fill)
    
    assert position.size_fp == 10
    
    # Add a 0-quantity exit fill - should be ignored
    zero_exit_fill = FillRecord(
        timestamp=datetime.utcnow(),
        fill_id="fill_2",
        side="no",
        action="buy",
        outcome_side="no",
        count_fp=0,
        price_cents=45,
        fee_cents=0,
        intent_side="no"
    )
    position.add_exit_fill(zero_exit_fill)
    
    # Position state should not change
    assert position.size_fp == 10
    assert len(position.exit_fills) == 0  # Zero fill not added
    assert position.thesis_side == ThesisSide.NO


def test_zero_quantity_fill_between_normal_fills():
    """Test that 0-quantity fills between normal fills don't corrupt position."""
    position = StrategyPosition(
        ticker="KXSOL15M-TEST",
        agent_id="SOL_15M",
        thesis_side=ThesisSide.YES,
        size_fp=0,
        avg_entry_price_cents=50
    )
    
    # First entry
    fill1 = FillRecord(
        timestamp=datetime.utcnow(),
        fill_id="fill_1",
        side="yes",
        action="buy",
        outcome_side="yes",
        count_fp=5,
        price_cents=50,
        fee_cents=1,
        intent_side="yes"
    )
    position.add_entry_fill(fill1)
    
    # Zero-quantity fill in between
    zero_fill = FillRecord(
        timestamp=datetime.utcnow(),
        fill_id="fill_zero",
        side="yes",
        action="buy",
        outcome_side="yes",
        count_fp=0,
        price_cents=52,
        fee_cents=0,
        intent_side="yes"
    )
    position.add_entry_fill(zero_fill)
    
    # Second entry
    fill2 = FillRecord(
        timestamp=datetime.utcnow(),
        fill_id="fill_2",
        side="yes",
        action="buy",
        outcome_side="yes",
        count_fp=5,
        price_cents=55,
        fee_cents=1,
        intent_side="yes"
    )
    position.add_entry_fill(fill2)
    
    # Position should have size 10 (5 + 5, zero fill ignored)
    assert position.size_fp == 10
    assert len(position.entry_fills) == 2  # Only non-zero fills
    assert position.thesis_side == ThesisSide.YES


def test_zero_quantity_fill_before_exit():
    """Test that 0-quantity fills before exit don't affect exit classification."""
    position = StrategyPosition(
        ticker="KXDOGE15M-TEST",
        agent_id="DOGE_15M",
        thesis_side=ThesisSide.YES,
        size_fp=0,
        avg_entry_price_cents=50
    )
    
    # Entry
    entry_fill = FillRecord(
        timestamp=datetime.utcnow(),
        fill_id="fill_entry",
        side="yes",
        action="buy",
        outcome_side="yes",
        count_fp=10,
        price_cents=50,
        fee_cents=1,
        intent_side="yes"
    )
    position.add_entry_fill(entry_fill)
    
    # Zero-quantity fill before exit
    zero_fill = FillRecord(
        timestamp=datetime.utcnow(),
        fill_id="fill_zero",
        side="yes",
        action="sell",
        outcome_side="yes",
        count_fp=0,
        price_cents=60,
        fee_cents=0,
        intent_side="yes"
    )
    position.add_exit_fill(zero_fill)
    
    # Real exit
    exit_fill = FillRecord(
        timestamp=datetime.utcnow(),
        fill_id="fill_exit",
        side="yes",
        action="sell",
        outcome_side="yes",
        count_fp=10,
        price_cents=60,
        fee_cents=1,
        intent_side="yes"
    )
    position.add_exit_fill(exit_fill)
    
    # Position should be closed (10 - 10, zero fill ignored)
    assert position.size_fp == 0
    assert len(position.exit_fills) == 1  # Only non-zero exit fill
    assert position.thesis_side == ThesisSide.YES


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
