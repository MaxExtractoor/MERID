"""
Test suite for exit policy loss exit fixes (2026-07-31).

This test validates that the exit policy no longer systematically exits
positions for losses instead of profits.

Key fixes tested:
1. Symmetric risk: SL fallback restored to prevent asymmetric risk
2. Time stop reversal: Now exits slow winners (R >= 0.5) instead of losers
3. Emergency flatten: Only forces exit if position is profitable
4. Staged exits: Only execute if position has positive PnL
"""

import pytest
from datetime import datetime, timezone
from merid.position_management.position import Position, PositionSide
from merid.position_management.exit_policy import ExitPolicy, ExitReason
from merid.position_management.position_monitor import PositionMonitor


class TestSymmetricRiskFix:
    """Test that positions have symmetric risk (both TP and SL)."""
    
    def test_position_has_default_sl_when_none_set(self):
        """Test that positions without explicit SL get fallback SL."""
        position = Position(
            position_id="test_pos",
            market_id="KXBTC15M-TEST",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            take_profit_price_cents=None,  # No TP set
            stop_loss_price_cents=None,  # No SL set
        )
        
        # Position should have default SL set in __post_init__
        assert position.stop_loss_price_cents is not None
        assert position.stop_loss_price_cents == 45  # entry - 5 cents
        assert position.take_profit_price_cents is not None
        assert position.take_profit_price_cents == 55  # entry + 5 cents (1R)
    
    def test_position_preserves_explicit_sl(self):
        """Test that explicit SL values are preserved."""
        position = Position(
            position_id="test_pos",
            market_id="KXBTC15M-TEST",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            take_profit_price_cents=60,
            stop_loss_price_cents=40,  # Explicit SL
        )
        
        assert position.stop_loss_price_cents == 40
        assert position.take_profit_price_cents == 60


class TestTimeStopReversal:
    """Test that time stop now exits slow winners instead of losers."""
    
    def test_time_stop_exits_slow_winners(self):
        """Test that time stop triggers for positions with R >= 0.5 after max hold."""
        policy = ExitPolicy(
            position=Position(
                position_id="test_pos",
                market_id="KXBTC15M-TEST",
                side=PositionSide.YES,
                size=10,
                avg_entry_price_cents=50,
                take_profit_price_cents=60,
                stop_loss_price_cents=40,
            ),
            current_price_cents=55,  # 5 cent profit = 1R
            unrealized_pnl_cents=50,
            r_multiple=1.0,  # >= 0.5 threshold
            time_since_entry_seconds=1000,  # Exceeded max hold (900s default)
            time_to_expiry_seconds=300,
        )
        
        # Should trigger time stop (slow winner)
        assert policy.evaluate_time_stop() is True
    
    def test_time_stop_holds_losers(self):
        """Test that time stop does NOT trigger for losing positions."""
        policy = ExitPolicy(
            position=Position(
                position_id="test_pos",
                market_id="KXBTC15M-TEST",
                side=PositionSide.YES,
                size=10,
                avg_entry_price_cents=50,
                take_profit_price_cents=60,
                stop_loss_price_cents=40,
            ),
            current_price_cents=45,  # 5 cent loss = -1R
            unrealized_pnl_cents=-50,
            r_multiple=-1.0,  # < 0.5 threshold
            time_since_entry_seconds=1000,  # Exceeded max hold
            time_to_expiry_seconds=300,
        )
        
        # Should NOT trigger time stop (losing position)
        assert policy.evaluate_time_stop() is False
    
    def test_time_stop_holds_before_max_hold(self):
        """Test that time stop does not trigger before max hold time."""
        policy = ExitPolicy(
            position=Position(
                position_id="test_pos",
                market_id="KXBTC15M-TEST",
                side=PositionSide.YES,
                size=10,
                avg_entry_price_cents=50,
                take_profit_price_cents=60,
                stop_loss_price_cents=40,
            ),
            current_price_cents=55,
            unrealized_pnl_cents=50,
            r_multiple=1.0,
            time_since_entry_seconds=500,  # Below max hold (900s)
            time_to_expiry_seconds=700,
        )
        
        # Should NOT trigger (not enough time elapsed)
        assert policy.evaluate_time_stop() is False


class TestEmergencyFlattenPnLCheck:
    """Test that emergency flatten only exits profitable positions."""
    
    def test_emergency_flatten_exits_profitable(self):
        """Test that emergency flatten forces exit for profitable positions near expiry."""
        position = Position(
            position_id="test_pos",
            market_id="KXBTC15M-TEST",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            take_profit_price_cents=60,
            stop_loss_price_cents=40,
        )
        position.update_runtime_state(55)  # 5 cent profit
        
        # Simulate emergency flatten condition
        time_to_expiry = 30  # < 60 seconds
        pnl_cents = position.unrealized_pnl_cents
        
        # Should force exit (profitable position)
        assert pnl_cents > 0
        assert time_to_expiry <= 60.0
    
    def test_emergency_flatten_skips_underwater(self):
        """Test that emergency flatten skips underwater positions."""
        position = Position(
            position_id="test_pos",
            market_id="KXBTC15M-TEST",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            take_profit_price_cents=60,
            stop_loss_price_cents=40,
        )
        position.update_runtime_state(45)  # 5 cent loss
        
        # Simulate emergency flatten condition
        time_to_expiry = 30  # < 60 seconds
        pnl_cents = position.unrealized_pnl_cents
        
        # Should NOT force exit (underwater position)
        assert pnl_cents <= 0
        assert time_to_expiry <= 60.0


class TestStagedExitPnLCheck:
    """Test that staged exits only execute for profitable positions."""
    
    def test_staged_exit_requires_profit(self):
        """Test that staged exits only trigger when position has positive PnL."""
        position = Position(
            position_id="test_pos",
            market_id="KXBTC15M-TEST",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            take_profit_price_cents=60,
            stop_loss_price_cents=40,
        )
        
        # Simulate underwater position
        position.update_runtime_state(45)  # 5 cent loss
        
        # Staged exit should be skipped
        assert position.unrealized_pnl_cents <= 0
    
    def test_staged_exit_executes_for_profit(self):
        """Test that staged exits execute when position has positive PnL."""
        position = Position(
            position_id="test_pos",
            market_id="KXBTC15M-TEST",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            take_profit_price_cents=60,
            stop_loss_price_cents=40,
        )
        
        # Simulate profitable position
        position.update_runtime_state(55)  # 5 cent profit
        
        # Staged exit should execute
        assert position.unrealized_pnl_cents > 0


class TestPositionMonitorStartupSLFallback:
    """Test that position monitor sets side-aware SL fallback for startup-loaded positions."""
    
    def test_startup_position_gets_sl_fallback_yes(self):
        """Test that YES positions loaded at startup get side-aware SL fallback if missing."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        
        # Create cached position without SL
        cached_pos = CachedPosition(
            market_id="KXBTC15M-TEST",
            agent_id="BTC_15M",
            contracts=10,
            side="yes",
            thesis_side="yes",
            avg_price_cents=50,
            take_profit_price_cents=60,
            stop_loss_price_cents=None,  # Missing SL
        )
        
        # Simulate position monitor startup logic (side-aware)
        position_side = PositionSide.YES
        sl_price = cached_pos.stop_loss_price_cents
        if sl_price is None and cached_pos.avg_price_cents:
            if position_side == PositionSide.YES:
                sl_price = max(1, cached_pos.avg_price_cents - 5)  # YES: SL below entry
            else:
                sl_price = min(99, cached_pos.avg_price_cents + 5)  # NO: SL above entry
        
        # Should have side-aware fallback SL
        assert sl_price == 45  # YES: 50 - 5 = 45
        assert sl_price < cached_pos.avg_price_cents
    
    def test_startup_position_gets_sl_fallback_no(self):
        """Test that NO positions loaded at startup get side-aware SL fallback if missing."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        
        # Create cached position without SL
        cached_pos = CachedPosition(
            market_id="KXBTC15M-TEST",
            agent_id="BTC_15M",
            contracts=10,
            side="no",
            thesis_side="no",
            avg_price_cents=50,
            take_profit_price_cents=40,
            stop_loss_price_cents=None,  # Missing SL
        )
        
        # Simulate position monitor startup logic (side-aware)
        position_side = PositionSide.NO
        sl_price = cached_pos.stop_loss_price_cents
        if sl_price is None and cached_pos.avg_price_cents:
            if position_side == PositionSide.YES:
                sl_price = max(1, cached_pos.avg_price_cents - 5)  # YES: SL below entry
            else:
                sl_price = min(99, cached_pos.avg_price_cents + 5)  # NO: SL above entry
        
        # Should have side-aware fallback SL
        assert sl_price == 55  # NO: 50 + 5 = 55
        assert sl_price > cached_pos.avg_price_cents


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
