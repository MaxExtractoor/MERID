"""
Unit tests for ThesisSide domain layer types.

Tests the ThesisSide enum, StrategyPosition dataclass, and pure functions
to ensure canonical direction mapping per Kalshi's order-direction semantics.

Reference: https://docs.kalshi.com/getting_started/order_direction
"""

import pytest
from datetime import datetime
from merid.event_venues.kalshi.strategy_positions import (
    ThesisSide,
    FillRecord,
    StrategyPosition,
    thesis_to_outcome_side,
    build_exit_order,
)


class TestThesisSideEnum:
    """Test ThesisSide enum construction and validation."""
    
    def test_from_outcome_side_yes(self):
        """Test creating ThesisSide from outcome_side='yes'."""
        thesis = ThesisSide.from_outcome_side("yes")
        assert thesis == ThesisSide.YES
        
    def test_from_outcome_side_no(self):
        """Test creating ThesisSide from outcome_side='no'."""
        thesis = ThesisSide.from_outcome_side("no")
        assert thesis == ThesisSide.NO
    
    def test_from_outcome_side_case_insensitive(self):
        """Test that from_outcome_side is case-insensitive."""
        assert ThesisSide.from_outcome_side("YES") == ThesisSide.YES
        assert ThesisSide.from_outcome_side("Yes") == ThesisSide.YES
        assert ThesisSide.from_outcome_side("NO") == ThesisSide.NO
        assert ThesisSide.from_outcome_side("No") == ThesisSide.NO
    
    def test_from_outcome_side_invalid(self):
        """Test that invalid outcome_side raises ValueError."""
        with pytest.raises(ValueError, match="Invalid outcome_side"):
            ThesisSide.from_outcome_side("invalid")
    
    def test_from_kalshi_format_buy_yes(self):
        """Test creating ThesisSide from BUY_YES format."""
        thesis = ThesisSide.from_kalshi_format("BUY_YES")
        assert thesis == ThesisSide.YES
    
    def test_from_kalshi_format_sell_no(self):
        """Test creating ThesisSide from SELL_NO format."""
        thesis = ThesisSide.from_kalshi_format("SELL_NO")
        assert thesis == ThesisSide.YES  # SELL_NO also creates long YES exposure
    
    def test_from_kalshi_format_buy_no(self):
        """Test creating ThesisSide from BUY_NO format."""
        thesis = ThesisSide.from_kalshi_format("BUY_NO")
        assert thesis == ThesisSide.NO
    
    def test_from_kalshi_format_sell_yes(self):
        """Test creating ThesisSide from SELL_YES format."""
        thesis = ThesisSide.from_kalshi_format("SELL_YES")
        assert thesis == ThesisSide.NO  # SELL_YES creates long NO exposure
    
    def test_from_kalshi_format_case_insensitive(self):
        """Test that from_kalshi_format is case-insensitive."""
        assert ThesisSide.from_kalshi_format("buy_yes") == ThesisSide.YES
        assert ThesisSide.from_kalshi_format("SELL_NO") == ThesisSide.YES
        assert ThesisSide.from_kalshi_format("Buy_No") == ThesisSide.NO
    
    def test_from_kalshi_format_invalid(self):
        """Test that invalid Kalshi format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid Kalshi format"):
            ThesisSide.from_kalshi_format("invalid")
    
    def test_enum_values(self):
        """Test that enum values are correct."""
        assert ThesisSide.YES.value == "yes"
        assert ThesisSide.NO.value == "no"


class TestThesisToOutcomeSide:
    """Test thesis_to_outcome_side pure function."""
    
    def test_thesis_yes_to_outcome_yes(self):
        """Test that ThesisSide.YES maps to outcome_side='yes'."""
        outcome = thesis_to_outcome_side(ThesisSide.YES)
        assert outcome == "yes"
    
    def test_thesis_no_to_outcome_no(self):
        """Test that ThesisSide.NO maps to outcome_side='no'."""
        outcome = thesis_to_outcome_side(ThesisSide.NO)
        assert outcome == "no"


class TestStrategyPosition:
    """Test StrategyPosition dataclass."""
    
    def test_position_creation(self):
        """Test creating a StrategyPosition."""
        position = StrategyPosition(
            ticker="KXBTC15M-26JUL211745-45",
            agent_id="BTC_15M",
            thesis_side=ThesisSide.YES,
            size_fp=10,
            avg_entry_price_cents=50,
        )
        assert position.ticker == "KXBTC15M-26JUL211745-45"
        assert position.thesis_side == ThesisSide.YES
        assert position.size_fp == 10
        assert position.avg_entry_price_cents == 50
        assert position.is_open is True
    
    def test_position_not_open_when_zero_size(self):
        """Test that position with zero size is not open."""
        position = StrategyPosition(
            ticker="KXBTC15M-26JUL211745-45",
            agent_id="BTC_15M",
            thesis_side=ThesisSide.YES,
            size_fp=0,
            avg_entry_price_cents=50,
        )
        assert position.is_open is False
    
    def test_add_entry_fill_increases_size(self):
        """Test that add_entry_fill increases position size."""
        position = StrategyPosition(
            ticker="KXBTC15M-26JUL211745-45",
            agent_id="BTC_15M",
            thesis_side=ThesisSide.YES,
            size_fp=5,
            avg_entry_price_cents=50,
        )
        
        fill = FillRecord(
            timestamp=datetime.utcnow(),
            fill_id="fill_1",
            side="yes",
            action="buy",
            outcome_side="yes",
            count_fp=5,
            price_cents=55,
            fee_cents=1,
            intent_side="yes",
        )
        
        position.add_entry_fill(fill)
        assert position.size_fp == 10
        assert len(position.entry_fills) == 1
    
    def test_add_entry_fill_validates_outcome_side(self):
        """Test that add_entry_fill validates outcome_side matches thesis_side."""
        position = StrategyPosition(
            ticker="KXBTC15M-26JUL211745-45",
            agent_id="BTC_15M",
            thesis_side=ThesisSide.YES,
            size_fp=5,
            avg_entry_price_cents=50,
        )
        
        # Fill with wrong outcome_side
        fill = FillRecord(
            timestamp=datetime.utcnow(),
            fill_id="fill_1",
            side="no",
            action="buy",
            outcome_side="no",  # Wrong outcome_side
            count_fp=5,
            price_cents=55,
            fee_cents=1,
            intent_side="no",
        )
        
        with pytest.raises(ValueError, match="outcome_side"):
            position.add_entry_fill(fill)
    
    def test_add_exit_fill_decreases_size(self):
        """Test that add_exit_fill decreases position size."""
        position = StrategyPosition(
            ticker="KXBTC15M-26JUL211745-45",
            agent_id="BTC_15M",
            thesis_side=ThesisSide.YES,
            size_fp=10,
            avg_entry_price_cents=50,
        )
        
        fill = FillRecord(
            timestamp=datetime.utcnow(),
            fill_id="fill_1",
            side="yes",
            action="sell",
            outcome_side="yes",
            count_fp=5,
            price_cents=55,
            fee_cents=1,
            intent_side="yes",
        )
        
        position.add_exit_fill(fill)
        assert position.size_fp == 5
        assert len(position.exit_fills) == 1
    
    def test_add_exit_fill_validates_quantity(self):
        """Test that add_exit_fill validates quantity doesn't exceed position size."""
        position = StrategyPosition(
            ticker="KXBTC15M-26JUL211745-45",
            agent_id="BTC_15M",
            thesis_side=ThesisSide.YES,
            size_fp=5,
            avg_entry_price_cents=50,
        )
        
        # Fill with too much quantity
        fill = FillRecord(
            timestamp=datetime.utcnow(),
            fill_id="fill_1",
            side="yes",
            action="sell",
            outcome_side="yes",
            count_fp=10,  # Exceeds position size
            price_cents=55,
            fee_cents=1,
            intent_side="yes",
        )
        
        with pytest.raises(ValueError, match="exceeds position size"):
            position.add_exit_fill(fill)
    
    def test_notional_calculation(self):
        """Test notional USD calculation."""
        position = StrategyPosition(
            ticker="KXBTC15M-26JUL211745-45",
            agent_id="BTC_15M",
            thesis_side=ThesisSide.YES,
            size_fp=10,
            avg_entry_price_cents=50,
        )
        assert position.notional_usd == 5.0  # 10 * 50c / 100


class TestBuildExitOrder:
    """Test build_exit_order pure function."""
    
    def test_build_exit_order_yes_thesis(self):
        """Test building exit order for YES thesis."""
        position = StrategyPosition(
            ticker="KXBTC15M-26JUL211745-45",
            agent_id="BTC_15M",
            thesis_side=ThesisSide.YES,
            size_fp=10,
            avg_entry_price_cents=50,
        )
        
        order = build_exit_order(position, qty_fp=5, price_cents=75)
        
        assert order["market_ticker"] == "KXBTC15M-26JUL211745-45"
        assert order["outcome_side"] == "yes"
        assert order["action"] == "sell"
        assert order["kalshi_side"] == "SELL_YES"
        assert order["size_fp"] == 5
        assert order["price_cents"] == 75
        assert order["thesis_side"] == "yes"
    
    def test_build_exit_order_no_thesis(self):
        """Test building exit order for NO thesis."""
        position = StrategyPosition(
            ticker="KXBTC15M-26JUL211745-45",
            agent_id="BTC_15M",
            thesis_side=ThesisSide.NO,
            size_fp=10,
            avg_entry_price_cents=50,
        )
        
        order = build_exit_order(position, qty_fp=5, price_cents=75)
        
        assert order["market_ticker"] == "KXBTC15M-26JUL211745-45"
        assert order["outcome_side"] == "no"
        assert order["action"] == "sell"
        assert order["kalshi_side"] == "SELL_NO"
        assert order["size_fp"] == 5
        assert order["price_cents"] == 75
        assert order["thesis_side"] == "no"
    
    def test_build_exit_order_validates_quantity_positive(self):
        """Test that build_exit_order validates quantity is positive."""
        position = StrategyPosition(
            ticker="KXBTC15M-26JUL211745-45",
            agent_id="BTC_15M",
            thesis_side=ThesisSide.YES,
            size_fp=10,
            avg_entry_price_cents=50,
        )
        
        with pytest.raises(ValueError, match="Exit quantity must be positive"):
            build_exit_order(position, qty_fp=0, price_cents=75)
        
        with pytest.raises(ValueError, match="Exit quantity must be positive"):
            build_exit_order(position, qty_fp=-5, price_cents=75)
    
    def test_build_exit_order_validates_quantity_within_size(self):
        """Test that build_exit_order validates quantity doesn't exceed position size."""
        position = StrategyPosition(
            ticker="KXBTC15M-26JUL211745-45",
            agent_id="BTC_15M",
            thesis_side=ThesisSide.YES,
            size_fp=10,
            avg_entry_price_cents=50,
        )
        
        with pytest.raises(ValueError, match="exceeds position size"):
            build_exit_order(position, qty_fp=15, price_cents=75)
    
    def test_build_exit_order_validates_position_open(self):
        """Test that build_exit_order validates position is open."""
        position = StrategyPosition(
            ticker="KXBTC15M-26JUL211745-45",
            agent_id="BTC_15M",
            thesis_side=ThesisSide.YES,
            size_fp=0,  # Closed position
            avg_entry_price_cents=50,
        )
        
        with pytest.raises(ValueError, match="Position size_fp must be positive"):
            build_exit_order(position, qty_fp=5, price_cents=75)
    
    def test_build_exit_order_validates_position_size_positive(self):
        """Test that build_exit_order validates position size is positive."""
        position = StrategyPosition(
            ticker="KXBTC15M-26JUL211745-45",
            agent_id="BTC_15M",
            thesis_side=ThesisSide.YES,
            size_fp=-5,  # Invalid negative size
            avg_entry_price_cents=50,
        )
        
        with pytest.raises(ValueError, match="Position size_fp must be positive"):
            build_exit_order(position, qty_fp=5, price_cents=75)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
