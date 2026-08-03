"""
Tests for Position dataclass.

Tests TP/SL enforcement, trailing stops, and PnL computation.
"""

import pytest
from datetime import datetime, timedelta
from merid.position_management.position import (
    Position,
    PositionSide,
    TrailingType,
)
from merid.position_management.exit_policy import ExitReason


class TestPosition:
    """Test Position dataclass initialization and basic operations."""
    
    def test_position_creation(self):
        """Test basic position creation."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        assert position.position_id != ""
        assert position.market_id == "KXBTC15M-1234"
        assert position.side == PositionSide.YES
        assert position.size == 10
        assert position.avg_entry_price_cents == 50
        assert position.exit_triggered is False
        # CRITICAL FIX: 2026-07-31 - Position now sets default 5c risk if no SL set
        # This ensures all positions have profit-taking capability
        assert position.initial_risk_cents == 5  # Default 5c risk set in __post_init__
        assert position.take_profit_price_cents == 55  # Default TP at entry + 5c
    
    def test_position_with_tp_sl(self):
        """Test position with take profit and stop loss."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            take_profit_price_cents=60,  # +10c TP
            stop_loss_price_cents=40,     # -10c SL
        )
        
        assert position.take_profit_price_cents == 60
        assert position.stop_loss_price_cents == 40
        assert position.initial_risk_cents == 10  # 50c - 40c = 10c risk
    
    def test_position_with_trailing_stop(self):
        """Test position with trailing stop configuration."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            trailing_type=TrailingType.PERCENT,
            trailing_param=0.10,  # 10% trail
        )
        
        assert position.trailing_type == TrailingType.PERCENT
        assert position.trailing_param == 0.10
        assert position.max_favorable_price_cents == 0  # Not yet updated


class TestPositionPnL:
    """Test PnL computation for positions."""
    
    def test_update_runtime_state_yes(self):
        """Test PnL update for YES position."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
        )
        
        # Price moves up to 60c
        position.update_runtime_state(60)
        
        assert position.current_price_cents == 60
        assert position.unrealized_pnl_cents == 100  # (60-50) * 10
        assert position.r_multiple == 10.0  # 100 / 10 initial risk
        assert position.time_since_entry_seconds >= 0
    
    def test_update_runtime_state_no(self):
        """Test PnL update for NO position."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.NO,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=60,  # NO SL is higher
        )
        
        # Price moves down to 40c (bad for NO - position is long NO)
        position.update_runtime_state(40)
        
        assert position.current_price_cents == 40
        assert position.unrealized_pnl_cents == -100  # (40-50) * 10 - side-space convention
        assert position.r_multiple == -10.0  # -100 / 10 initial risk
    
    def test_pnl_negative(self):
        """Test negative PnL (losing position)."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
        )
        
        # Price moves down to 45c
        position.update_runtime_state(45)
        
        assert position.unrealized_pnl_cents == -50  # (45-50) * 10
        assert position.r_multiple == -5.0  # -50 / 10 initial risk
    
    def test_update_runtime_state_zero_entry_price(self):
        """Test update_runtime_state handles zero avg_entry_price_cents without division by zero.
        
        CRITICAL FIX (2026-07-16): When both initial_risk_cents and avg_entry_price_cents are 0,
        r_multiple should be set to 0.0 instead of raising ZeroDivisionError.
        """
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=0,  # Zero entry price
            stop_loss_price_cents=None,  # No stop loss, so initial_risk_cents = 0
        )
        
        # Should not raise ZeroDivisionError
        position.update_runtime_state(50)
        
        assert position.current_price_cents == 50
        assert position.unrealized_pnl_cents == 500  # (50-0) * 10
        assert position.r_multiple == 0.0  # Should be 0.0, not division by zero
    
    def test_update_runtime_state_zero_entry_with_stop_loss(self):
        """Test update_runtime_state handles zero avg_entry_price_cents with stop loss set.
        
        When avg_entry_price_cents is 0, even if stop_loss_price_cents is set,
        the initial_risk_cents calculation (entry - stop_loss) may be invalid.
        The fix ensures r_multiple is set to 0.0 instead of raising ZeroDivisionError.
        """
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=0,  # Zero entry price
            stop_loss_price_cents=40,  # Stop loss set, but entry is 0 so risk calculation is invalid
        )
        
        # Should not raise ZeroDivisionError, r_multiple should be 0.0
        position.update_runtime_state(50)
        
        assert position.current_price_cents == 50
        assert position.unrealized_pnl_cents == 500  # (50-0) * 10
        assert position.r_multiple == 0.0  # Cannot calculate valid R-multiple with zero entry


class TestPositionTriggers:
    """Test TP/SL and trailing stop trigger conditions."""
    
    def test_should_trigger_stop_loss_yes(self):
        """Test stop loss trigger for YES position."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
        )
        
        # Price at SL
        assert position.should_trigger_stop_loss(40) is True
        
        # Price below SL
        assert position.should_trigger_stop_loss(35) is True
        
        # Price above SL
        assert position.should_trigger_stop_loss(45) is False
    
    def test_should_trigger_stop_loss_no(self):
        """Test stop loss trigger for NO position."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.NO,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=60,
        )
        
        # Price at SL
        assert position.should_trigger_stop_loss(60) is True
        
        # Price above SL (should NOT trigger - side-space convention)
        assert position.should_trigger_stop_loss(65) is False
        
        # Price below SL (should trigger - side-space convention)
        assert position.should_trigger_stop_loss(55) is True
    
    def test_should_trigger_take_profit_yes(self):
        """Test take profit trigger for YES position."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            take_profit_price_cents=60,
        )
        
        # Price at TP
        assert position.should_trigger_take_profit(60) is True
        
        # Price above TP
        assert position.should_trigger_take_profit(65) is True
        
        # Price below TP
        assert position.should_trigger_take_profit(55) is False
    
    def test_should_trigger_take_profit_no(self):
        """Test take profit trigger for NO position."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.NO,
            size=10,
            avg_entry_price_cents=50,
            take_profit_price_cents=40,
        )
        
        # Price at TP
        assert position.should_trigger_take_profit(40) is True
        
        # Price below TP (should NOT trigger - side-space convention)
        assert position.should_trigger_take_profit(35) is False
        
        # Price above TP (should trigger - side-space convention)
        assert position.should_trigger_take_profit(45) is True


class TestPositionTrailing:
    """Test trailing stop logic."""
    
    def test_trailing_percent_yes(self):
        """Test percent trailing for YES position."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            trailing_type=TrailingType.PERCENT,
            trailing_param=0.10,  # 10% trail
        )
        
        # Price moves up to 60c
        position.update_runtime_state(60)
        
        assert position.max_favorable_price_cents == 60
        assert position.get_trail_level() == 54  # 60 * (1 - 0.10)
        
        # Price moves up to 70c
        position.update_runtime_state(70)
        
        assert position.max_favorable_price_cents == 70
        assert position.get_trail_level() == 63  # 70 * (1 - 0.10)
        
        # Price drops to 65c (above trail)
        assert position.should_trigger_trail(65) is False
        
        # Price drops to 62c (below trail)
        assert position.should_trigger_trail(62) is True
    
    def test_trailing_r_multiple_yes(self):
        """Test R-multiple trailing for YES position."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,  # 10c risk
            trailing_type=TrailingType.R_MULTIPLE,
            trailing_param=0.5,  # Trail at 0.5R below max
        )
        
        # Price moves up to 70c (2R profit)
        position.update_runtime_state(70)
        
        assert position.max_favorable_price_cents == 70
        assert position.get_trail_level() == 65  # 70 - (0.5 * 10)
        
        # Price drops to 66c (above trail)
        assert position.should_trigger_trail(66) is False
        
        # Price drops to 64c (below trail)
        assert position.should_trigger_trail(64) is True
    
    def test_trailing_no(self):
        """Test trailing for NO position."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.NO,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=60,  # 10c risk
            trailing_type=TrailingType.PERCENT,
            trailing_param=0.10,
        )
        
        # Price moves down to 40c (bad for NO - position is long NO)
        position.update_runtime_state(40)
        
        assert position.max_favorable_price_cents == 40
        assert position.get_trail_level() == 36  # 40 * (1 - 0.10) - side-space convention


class TestPositionExit:
    """Test position exit marking."""
    
    def test_mark_exited(self):
        """Test marking position as exited."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        assert position.exit_triggered is False
        assert position.exit_reason is None
        assert position.exit_price_cents is None
        assert position.exited_at is None
        
        position.mark_exited("take_profit", 60)
        
        assert position.exit_triggered is True
        assert position.exit_reason == "take_profit"
        assert position.exit_price_cents == 60
        assert position.exited_at is not None


class TestExtremeProfitExit:
    """Tests for extreme profit exit (99c YES / 1c NO)."""
    
    def test_extreme_profit_yes_at_99c(self):
        """Test YES position triggers extreme profit exit at 99c."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        # At 99c, should trigger extreme profit exit
        assert position.should_trigger_extreme_profit(99) is True
        
        # At 100c, should also trigger
        assert position.should_trigger_extreme_profit(100) is True
    
    def test_extreme_profit_yes_below_99c(self):
        """Test YES position does not trigger extreme profit exit below 99c."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        # At 98c, should not trigger
        assert position.should_trigger_extreme_profit(98) is False
        
        # At 50c (entry), should not trigger
        assert position.should_trigger_extreme_profit(50) is False
    
    def test_extreme_profit_no_at_1c(self):
        """Test NO position triggers extreme profit exit at 99c (side-space convention)."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.NO,
            size=10,
            avg_entry_price_cents=50,
        )
        
        # At 99c NO (equivalent to 1c YES), should trigger extreme profit exit
        assert position.should_trigger_extreme_profit(99) is True
        
        # At 100c NO, should also trigger
        assert position.should_trigger_extreme_profit(100) is True
    
    def test_extreme_profit_no_above_1c(self):
        """Test NO position does not trigger extreme profit exit below 99c (side-space convention)."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.NO,
            size=10,
            avg_entry_price_cents=50,
        )
        
        # At 98c NO (equivalent to 2c YES), should not trigger
        assert position.should_trigger_extreme_profit(98) is False
        
        # At 50c (entry), should not trigger
        assert position.should_trigger_extreme_profit(50) is False
    
    def test_extreme_profit_all_assets_yes(self):
        """Test extreme profit exit works for all 5 crypto assets (YES positions)."""
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        for asset in assets:
            position = Position(
                market_id=f"KX{asset}15M-1234",
                series_ticker=f"KX{asset}15M",
                side=PositionSide.YES,
                size=10,
                avg_entry_price_cents=50,
            )
            
            # At 99c, should trigger extreme profit exit for all assets
            assert position.should_trigger_extreme_profit(99) is True, f"Failed for {asset} YES at 99c"
            
            # At 98c, should not trigger for any asset
            assert position.should_trigger_extreme_profit(98) is False, f"Failed for {asset} YES at 98c"
    
    def test_extreme_profit_all_assets_no(self):
        """Test extreme profit exit works for all 5 crypto assets (NO positions)."""
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        for asset in assets:
            position = Position(
                market_id=f"KX{asset}15M-1234",
                series_ticker=f"KX{asset}15M",
                side=PositionSide.NO,
                size=10,
                avg_entry_price_cents=50,
            )
            
            # At 99c NO (equivalent to 1c YES), should trigger extreme profit exit for all assets
            assert position.should_trigger_extreme_profit(99) is True, f"Failed for {asset} NO at 99c"
            
            # At 98c NO (equivalent to 2c YES), should not trigger for any asset
            assert position.should_trigger_extreme_profit(98) is False, f"Failed for {asset} NO at 98c"


class TestProbabilityAdjustedTrailing:
    """Tests for probability-adjusted trailing stop logic."""
    
    def test_prob_adjusted_trail_yes_high_probability(self):
        """YES position at high probability (0.90+) should have tighter trailing."""
        position = Position(
            market_id="test_market",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,  # $0.50 entry
            take_profit_price_cents=80,
            stop_loss_price_cents=40,
            trailing_type=TrailingType.PERCENT,
            trailing_param=0.10,  # 10% trail
        )
        
        # Simulate price moved to $0.92 (high probability)
        position.update_runtime_state(current_price_cents=92)
        position.max_favorable_price_cents = 92
        
        base_trail = position.get_trail_level()
        adjusted_trail = position.get_probability_adjusted_trail_level()
        
        # Adjusted trail should be tighter (closer to max favorable)
        assert adjusted_trail is not None
        assert adjusted_trail > base_trail  # For YES, tighter = higher trail level
    
    def test_prob_adjusted_trail_yes_moderate_probability(self):
        """YES position at moderate probability (0.70-0.90) should have slightly tighter trailing."""
        position = Position(
            market_id="test_market",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            take_profit_price_cents=80,
            stop_loss_price_cents=40,
            trailing_type=TrailingType.PERCENT,
            trailing_param=0.10,
        )
        
        # Simulate price moved to $0.75 (moderate probability)
        position.update_runtime_state(current_price_cents=75)
        position.max_favorable_price_cents = 75
        
        base_trail = position.get_trail_level()
        adjusted_trail = position.get_probability_adjusted_trail_level()
        
        # Adjusted trail should be slightly tighter
        assert adjusted_trail is not None
        assert adjusted_trail > base_trail
    
    def test_prob_adjusted_trail_yes_low_probability(self):
        """YES position at low probability (<0.70) should have normal trailing."""
        position = Position(
            market_id="test_market",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            take_profit_price_cents=80,
            stop_loss_price_cents=40,
            trailing_type=TrailingType.PERCENT,
            trailing_param=0.10,
        )
        
        # Simulate price at $0.60 (low probability)
        position.update_runtime_state(current_price_cents=60)
        position.max_favorable_price_cents = 60
        
        base_trail = position.get_trail_level()
        adjusted_trail = position.get_probability_adjusted_trail_level()
        
        # Adjusted trail should equal base trail (no adjustment)
        assert adjusted_trail is not None
        assert adjusted_trail == base_trail
    
    def test_prob_adjusted_trail_no_low_probability(self):
        """NO position at low probability (0.10-) should have tighter trailing."""
        position = Position(
            market_id="test_market",
            side=PositionSide.NO,
            size=10,
            avg_entry_price_cents=50,  # $0.50 entry
            take_profit_price_cents=20,
            stop_loss_price_cents=60,
            trailing_type=TrailingType.PERCENT,
            trailing_param=0.10,
        )
        
        # Simulate price moved to $0.15 (low probability = winning for NO)
        position.update_runtime_state(current_price_cents=15)
        position.max_favorable_price_cents = 15
        
        base_trail = position.get_trail_level()
        adjusted_trail = position.get_probability_adjusted_trail_level()
        
        # Adjusted trail should be tighter (closer to max favorable)
        # For NO in side-space, tighter = higher trail level (closer to max favorable)
        assert adjusted_trail is not None
        # At 15c (0.15 prob), adjustment_factor = 0.6 for NO
        # base_trail = 15 * (1 - 0.10) = 13.5 -> 13
        # adjusted_distance = (15 - 13) * 0.6 = 1.2 -> 1
        # adjusted_trail = 15 - 1 = 14
        assert adjusted_trail > base_trail  # For NO, tighter = higher trail level
    
    def test_prob_adjusted_trail_no_moderate_probability(self):
        """NO position at moderate probability (0.10-0.30) should have slightly tighter trailing."""
        position = Position(
            market_id="test_market",
            side=PositionSide.NO,
            size=10,
            avg_entry_price_cents=50,
            take_profit_price_cents=20,
            stop_loss_price_cents=60,
            trailing_type=TrailingType.PERCENT,
            trailing_param=0.10,
        )
        
        # Simulate price at $0.25 (moderate probability)
        position.update_runtime_state(current_price_cents=25)
        position.max_favorable_price_cents = 25
        
        base_trail = position.get_trail_level()
        adjusted_trail = position.get_probability_adjusted_trail_level()
        
        # Adjusted trail should be slightly tighter
        # For NO in side-space, tighter = higher trail level
        assert adjusted_trail is not None
        # At 25c (0.25 prob), adjustment_factor = 0.8 for NO
        # base_trail = 25 * (1 - 0.10) = 22.5 -> 22
        # adjusted_distance = (25 - 22) * 0.8 = 2.4 -> 2
        # adjusted_trail = 25 - 2 = 23
        assert adjusted_trail > base_trail  # For NO, tighter = higher trail level
    
    def test_prob_adjusted_trail_no_high_probability(self):
        """NO position at high probability (>0.30) should have normal trailing."""
        position = Position(
            market_id="test_market",
            side=PositionSide.NO,
            size=10,
            avg_entry_price_cents=50,
            take_profit_price_cents=20,
            stop_loss_price_cents=60,
            trailing_type=TrailingType.PERCENT,
            trailing_param=0.10,
        )
        
        # Simulate price at $0.40 (high probability = losing for NO)
        position.update_runtime_state(current_price_cents=40)
        position.max_favorable_price_cents = 40
        
        base_trail = position.get_trail_level()
        adjusted_trail = position.get_probability_adjusted_trail_level()
        
        # Adjusted trail should equal base trail (no adjustment)
        assert adjusted_trail is not None
        assert adjusted_trail == base_trail
    
    def test_prob_adjusted_trail_no_trailing(self):
        """When trailing is disabled, probability adjustment returns None."""
        position = Position(
            market_id="test_market",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            take_profit_price_cents=80,
            stop_loss_price_cents=40,
            trailing_type=TrailingType.NONE,  # No trailing
        )
        
        position.update_runtime_state(current_price_cents=92)
        
        adjusted_trail = position.get_probability_adjusted_trail_level()
        assert adjusted_trail is None
    
    def test_prob_adjusted_trail_r_multiple(self):
        """Probability adjustment works with R_MULTIPLE trailing type."""
        position = Position(
            market_id="test_market",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            take_profit_price_cents=80,
            stop_loss_price_cents=40,
            trailing_type=TrailingType.R_MULTIPLE,
            trailing_param=1.0,  # 1R trail
        )
        
        position.update_runtime_state(current_price_cents=92)
        position.max_favorable_price_cents = 92
        
        base_trail = position.get_trail_level()
        adjusted_trail = position.get_probability_adjusted_trail_level()
        
        # Should still apply adjustment
        assert adjusted_trail is not None
        assert adjusted_trail > base_trail
