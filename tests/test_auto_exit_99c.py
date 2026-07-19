"""Tests for 99c auto-exit functionality.

Per Kalshi semantics, contracts settle at exactly $1 if correct and $0 if not.
Selling early at 99c locks in almost all of the payoff. This is a high-priority
exit that overrides other policies to prevent "riding it" from 99c back down to 0.

Reference: https://help.kalshi.com/en/articles/15521632-auto-sell-take-profit
"""

import pytest
from merid.position_management.position import Position, PositionSide
from merid.position_management.exit_policy import ExitReason
from merid.position_management.exit_decision import ExitPriority, ExitDecision, ExitSourceLayer


class TestAutoExit99CYesPosition:
    """Test 99c auto-exit for YES positions."""
    
    def test_auto_exit_99c_triggers_at_99c_yes(self):
        """AUTO_EXIT_99C should trigger when yes_bid reaches 99c."""
        position = Position(
            position_id="test_pos",
            market_id="KXBTC15M-UP-20260719-1400",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=40,
        )
        
        # Should trigger at 99c
        assert position.should_trigger_auto_exit_99c(99, bid_cents=99) is True
    
    def test_auto_exit_99c_does_not_trigger_below_99c_yes(self):
        """AUTO_EXIT_99C should not trigger when yes_bid is below 99c."""
        position = Position(
            position_id="test_pos",
            market_id="KXBTC15M-UP-20260719-1400",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=40,
        )
        
        # Should not trigger at 98c
        assert position.should_trigger_auto_exit_99c(98, bid_cents=98) is False
        
        # Should not trigger at 95c
        assert position.should_trigger_auto_exit_99c(95, bid_cents=95) is False
        
        # Should not trigger at 50c
        assert position.should_trigger_auto_exit_99c(50, bid_cents=50) is False
    
    def test_auto_exit_99c_triggers_above_99c_yes(self):
        """AUTO_EXIT_99C should trigger when yes_bid is above 99c."""
        position = Position(
            position_id="test_pos",
            market_id="KXBTC15M-UP-20260719-1400",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=40,
        )
        
        # Should trigger at 100c
        assert position.should_trigger_auto_exit_99c(100, bid_cents=100) is True
    
    def test_auto_exit_99c_uses_bid_when_available_yes(self):
        """AUTO_EXIT_99C should use bid price when available (conservative)."""
        position = Position(
            position_id="test_pos",
            market_id="KXBTC15M-UP-20260719-1400",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=40,
        )
        
        # Mid price 100c, bid 98c - should use bid (98c < 99c, no trigger)
        assert position.should_trigger_auto_exit_99c(100, bid_cents=98) is False
        
        # Mid price 98c, bid 99c - should use bid (99c >= 99c, trigger)
        assert position.should_trigger_auto_exit_99c(98, bid_cents=99) is True
    
    def test_auto_exit_99c_fallback_to_mid_when_no_bid_yes(self):
        """AUTO_EXIT_99C should fall back to mid price when bid not available."""
        position = Position(
            position_id="test_pos",
            market_id="KXBTC15M-UP-20260719-1400",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=40,
        )
        
        # No bid provided, use mid price
        assert position.should_trigger_auto_exit_99c(99, bid_cents=None) is True
        assert position.should_trigger_auto_exit_99c(98, bid_cents=None) is False


class TestAutoExit99CNoPosition:
    """Test 99c auto-exit for NO positions."""
    
    def test_auto_exit_99c_triggers_at_99c_no(self):
        """AUTO_EXIT_99C should trigger when no_bid reaches 99c.
        
        For NO positions, 99c NO means YES at 1c (guaranteed win for NO).
        """
        position = Position(
            position_id="test_pos",
            market_id="KXBTC15M-UP-20260719-1400",
            side=PositionSide.NO,
            size=1,
            avg_entry_price_cents=40,
        )
        
        # Should trigger at 99c NO (YES at 1c, guaranteed win)
        assert position.should_trigger_auto_exit_99c(99, bid_cents=99) is True
    
    def test_auto_exit_99c_does_not_trigger_below_99c_no(self):
        """AUTO_EXIT_99C should not trigger when no_bid is below 99c."""
        position = Position(
            position_id="test_pos",
            market_id="KXBTC15M-UP-20260719-1400",
            side=PositionSide.NO,
            size=1,
            avg_entry_price_cents=40,
        )
        
        # Should not trigger at 98c NO
        assert position.should_trigger_auto_exit_99c(98, bid_cents=98) is False
        
        # Should not trigger at 50c NO
        assert position.should_trigger_auto_exit_99c(50, bid_cents=50) is False
    
    def test_auto_exit_99c_triggers_above_99c_no(self):
        """AUTO_EXIT_99C should trigger when no_bid is above 99c."""
        position = Position(
            position_id="test_pos",
            market_id="KXBTC15M-UP-20260719-1400",
            side=PositionSide.NO,
            size=1,
            avg_entry_price_cents=40,
        )
        
        # Should trigger at 100c NO
        assert position.should_trigger_auto_exit_99c(100, bid_cents=100) is True
    
    def test_auto_exit_99c_uses_bid_when_available_no(self):
        """AUTO_EXIT_99C should use bid price when available (conservative)."""
        position = Position(
            position_id="test_pos",
            market_id="KXBTC15M-UP-20260719-1400",
            side=PositionSide.NO,
            size=1,
            avg_entry_price_cents=40,
        )
        
        # Mid price 100c, bid 98c - should use bid (98c < 99c, no trigger)
        assert position.should_trigger_auto_exit_99c(100, bid_cents=98) is False
        
        # Mid price 98c, bid 99c - should use bid (99c >= 99c, trigger)
        assert position.should_trigger_auto_exit_99c(98, bid_cents=99) is True


class TestAutoExit99CPriority:
    """Test AUTO_EXIT_99C priority in exit resolution."""
    
    def test_auto_exit_99c_priority_is_95(self):
        """AUTO_EXIT_99C should have priority 95 (higher than EXTREME_PROFIT at 90)."""
        assert ExitPriority.AUTO_EXIT_99C.value == 95
        assert ExitPriority.AUTO_EXIT_99C.value > ExitPriority.EXTREME_PROFIT.value
        assert ExitPriority.AUTO_EXIT_99C.value < ExitPriority.RISK.value
    
    def test_auto_exit_99c_overrides_extreme_profit(self):
        """AUTO_EXIT_99C should override EXTREME_PROFIT in exit resolution."""
        from merid.position_management.exit_resolver import ExitResolver
        
        auto_exit_99c = ExitDecision(
            reason=ExitReason.AUTO_EXIT_99C,
            priority=ExitPriority.AUTO_EXIT_99C,
            source_layer=ExitSourceLayer.POSITION_LEVEL,
            exit_price_cents=99,
        )
        
        extreme_profit = ExitDecision(
            reason=ExitReason.EXTREME_PROFIT,
            priority=ExitPriority.EXTREME_PROFIT,
            source_layer=ExitSourceLayer.POSITION_LEVEL,
            exit_price_cents=99,
        )
        
        resolver = ExitResolver()
        winning = resolver.resolve([auto_exit_99c, extreme_profit])
        
        assert winning.reason == ExitReason.AUTO_EXIT_99C
    
    def test_auto_exit_99c_overrides_trailing_stop(self):
        """AUTO_EXIT_99C should override TRAIL (trailing stop, priority 25)."""
        from merid.position_management.exit_resolver import ExitResolver
        
        auto_exit_99c = ExitDecision(
            reason=ExitReason.AUTO_EXIT_99C,
            priority=ExitPriority.AUTO_EXIT_99C,
            source_layer=ExitSourceLayer.POSITION_LEVEL,
            exit_price_cents=99,
        )
        
        trail = ExitDecision(
            reason=ExitReason.TRAIL,
            priority=ExitPriority.TRAIL,
            source_layer=ExitSourceLayer.POSITION_LEVEL,
            exit_price_cents=50,
        )
        
        resolver = ExitResolver()
        winning = resolver.resolve([auto_exit_99c, trail])
        
        assert winning.reason == ExitReason.AUTO_EXIT_99C
    
    def test_auto_exit_99c_overrides_stop_loss(self):
        """AUTO_EXIT_99C should override STOP_LOSS (priority 60)."""
        from merid.position_management.exit_resolver import ExitResolver
        
        auto_exit_99c = ExitDecision(
            reason=ExitReason.AUTO_EXIT_99C,
            priority=ExitPriority.AUTO_EXIT_99C,
            source_layer=ExitSourceLayer.POSITION_LEVEL,
            exit_price_cents=99,
        )
        
        stop_loss = ExitDecision(
            reason=ExitReason.STOP_LOSS,
            priority=ExitPriority.STOP_LOSS,
            source_layer=ExitSourceLayer.POSITION_LEVEL,
            exit_price_cents=45,
        )
        
        resolver = ExitResolver()
        winning = resolver.resolve([auto_exit_99c, stop_loss])
        
        assert winning.reason == ExitReason.AUTO_EXIT_99C


class TestAutoExit99CTrajectory:
    """Test AUTO_EXIT_99C behavior along price trajectories."""
    
    def test_yes_position_trajectory_40_to_99(self):
        """Test YES position trajectory: 40c → 70c → 95c → 99c → 98c.
        
        Should exit only at 99c and not generate further decisions after.
        """
        position = Position(
            position_id="test_pos",
            market_id="KXBTC15M-UP-20260719-1400",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=40,
        )
        
        # 40c - no exit
        assert position.should_trigger_auto_exit_99c(40, bid_cents=40) is False
        
        # 70c - no exit
        assert position.should_trigger_auto_exit_99c(70, bid_cents=70) is False
        
        # 95c - no exit
        assert position.should_trigger_auto_exit_99c(95, bid_cents=95) is False
        
        # 99c - exit triggers
        assert position.should_trigger_auto_exit_99c(99, bid_cents=99) is True
        
        # After exit, position.exit_triggered should prevent re-trigger
        position.exit_triggered = True
        assert position.should_trigger_auto_exit_99c(98, bid_cents=98) is False
    
    def test_no_position_trajectory_40_to_99(self):
        """Test NO position trajectory: 40c → 70c → 95c → 99c → 98c.
        
        Should exit only at 99c and not generate further decisions after.
        """
        position = Position(
            position_id="test_pos",
            market_id="KXBTC15M-UP-20260719-1400",
            side=PositionSide.NO,
            size=1,
            avg_entry_price_cents=40,
        )
        
        # 40c - no exit
        assert position.should_trigger_auto_exit_99c(40, bid_cents=40) is False
        
        # 70c - no exit
        assert position.should_trigger_auto_exit_99c(70, bid_cents=70) is False
        
        # 95c - no exit
        assert position.should_trigger_auto_exit_99c(95, bid_cents=95) is False
        
        # 99c - exit triggers
        assert position.should_trigger_auto_exit_99c(99, bid_cents=99) is True
        
        # After exit, position.exit_triggered should prevent re-trigger
        position.exit_triggered = True
        assert position.should_trigger_auto_exit_99c(98, bid_cents=98) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
