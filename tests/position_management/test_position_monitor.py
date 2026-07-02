"""
Tests for PositionMonitor.

Tests polling, exit intents, and callback mechanism.
"""

import pytest
import asyncio
import unittest
from datetime import datetime
from unittest.mock import Mock, patch
from merid.position_management.position import Position, PositionSide
from merid.position_management.exit_policy import ExitReason
from merid.position_management.position_monitor import (
    PositionMonitor,
    get_position_monitor,
)


class TestPositionMonitor:
    """Test PositionMonitor basic operations."""
    
    def test_get_position_monitor_singleton(self):
        """Test singleton pattern."""
        monitor1 = get_position_monitor()
        monitor2 = get_position_monitor()
        
        assert monitor1 is monitor2
    
    def test_add_position(self):
        """Test adding a position to monitor."""
        monitor = PositionMonitor()
        
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
        )
        
        monitor.add_position(position)
        
        assert len(monitor.get_open_positions()) == 1
        assert monitor.get_position(position.position_id) is position
        assert monitor.get_position_by_market("KXBTC15M-1234") is position
    
    def test_add_duplicate_position(self):
        """Test adding duplicate position is ignored."""
        monitor = PositionMonitor()
        
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        monitor.add_position(position)
        monitor.add_position(position)  # Duplicate
        
        assert len(monitor.get_open_positions()) == 1
    
    def test_remove_position(self):
        """Test removing a position from monitor."""
        monitor = PositionMonitor()
        
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        monitor.add_position(position)
        monitor.remove_position(position.position_id)
        
        assert len(monitor.get_open_positions()) == 0
        assert monitor.get_position(position.position_id) is None
        assert monitor.get_position_by_market("KXBTC15M-1234") is None
    
    def test_get_stats(self):
        """Test getting monitor statistics."""
        monitor = PositionMonitor(poll_interval=10.0)
        
        stats = monitor.get_stats()
        
        assert stats["running"] is False
        assert stats["open_positions"] == 0
        assert stats["poll_interval"] == 10.0


class TestPositionMonitorExitCallback:
    """Test exit intent callback mechanism."""
    
    def test_register_exit_intent_callback(self):
        """Test registering exit intent callback."""
        monitor = PositionMonitor()
        
        callback = Mock()
        monitor.register_exit_intent_callback(callback)
        
        # Callback is stored internally
        assert monitor._exit_intent_callback is callback
    
    def test_exit_intent_callback_on_stop_loss(self):
        """Test callback is triggered on stop loss."""
        monitor = PositionMonitor()
        
        callback = Mock()
        monitor.register_exit_intent_callback(callback)
        
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
        )
        
        monitor.add_position(position)
        
        # Manually trigger stop loss check
        asyncio.run(monitor._check_position(position, 35))
        
        # Callback should be called
        callback.assert_called_once()
        call_args = callback.call_args
        assert call_args[0][0] is position
        assert call_args[0][1] == ExitReason.STOP_LOSS
        assert call_args[0][2] == 35
        
        # Position should be removed
        assert len(monitor.get_open_positions()) == 0
    
    def test_exit_intent_callback_on_take_profit(self):
        """Test callback is triggered on take profit."""
        monitor = PositionMonitor()
        
        callback = Mock()
        monitor.register_exit_intent_callback(callback)
        
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            take_profit_price_cents=60,
        )
        
        monitor.add_position(position)
        
        # Manually trigger take profit check
        asyncio.run(monitor._check_position(position, 65))
        
        # Callback should be called
        callback.assert_called_once()
        call_args = callback.call_args
        assert call_args[0][1] == ExitReason.TAKE_PROFIT
        assert call_args[0][2] == 65
    
    def test_exit_intent_callback_on_trail(self):
        """Test callback is triggered on trailing stop."""
        monitor = PositionMonitor()
        
        callback = Mock()
        monitor.register_exit_intent_callback(callback)
        
        from merid.position_management.position import TrailingType
        
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            trailing_type=TrailingType.PERCENT,
            trailing_param=0.10,
        )
        
        monitor.add_position(position)
        
        # Move price up to set trail
        position.update_runtime_state(60)
        
        # Activate trailing (simulating break-even trigger)
        position.trailing_activated = True
        
        # Drop below trail
        asyncio.run(monitor._check_position(position, 53))
        
        # Callback should be called
        callback.assert_called_once()
        call_args = callback.call_args
        assert call_args[0][1] == ExitReason.TRAIL


class TestPositionMonitorPolling:
    """Test polling loop (mocked)."""
    
    @patch('merid.event_venues.kalshi.market_state.get_kalshi_market_state_store')
    @pytest.mark.asyncio
    async def test_poll_loop_with_market_state(self, mock_get_store):
        """Test polling loop with market state."""
        # Mock market state store
        mock_store = Mock()
        mock_state = Mock()
        mock_state.mid_cents = 60
        mock_store.get.return_value = mock_state
        mock_get_store.return_value = mock_store
        
        monitor = PositionMonitor(poll_interval=0.1)
        
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
        )
        
        monitor.add_position(position)
        
        # Start monitor
        await monitor.start()
        
        # Wait for one poll
        await asyncio.sleep(0.15)
        
        # Stop monitor
        await monitor.stop()
        
        # Position should have been updated
        assert position.current_price_cents == 60
    
    @patch('merid.event_venues.kalshi.market_state.get_kalshi_market_state_store')
    @pytest.mark.asyncio
    async def test_poll_loop_no_market_state(self, mock_get_store):
        """Test polling loop when market state unavailable."""
        # Mock market state store returning None
        mock_store = Mock()
        mock_store.get.return_value = None
        mock_get_store.return_value = mock_store
        
        monitor = PositionMonitor(poll_interval=0.1)
        
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        monitor.add_position(position)
        
        # Start monitor
        await monitor.start()
        
        # Wait for one poll
        await asyncio.sleep(0.15)
        
        # Stop monitor
        await monitor.stop()
        
        # Position should not have been updated
        assert position.current_price_cents == 0


class TestPositionMonitorThreadSafety:
    """Test thread safety of PositionMonitor operations."""
    
    def test_concurrent_add_positions(self):
        """Test concurrent add operations are thread-safe."""
        import threading
        monitor = PositionMonitor()
        
        positions_added = []
        
        def add_position(i):
            position = Position(
                market_id=f"KXBTC15M-{i}",
                series_ticker="KXBTC15M",
                side=PositionSide.YES,
                size=10,
                avg_entry_price_cents=50,
            )
            monitor.add_position(position)
            positions_added.append(i)
        
        threads = [threading.Thread(target=add_position, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # All positions should be added without corruption
        assert len(monitor.get_open_positions()) == 10
        assert len(positions_added) == 10
    
    def test_concurrent_add_remove(self):
        """Test concurrent add and remove operations are thread-safe."""
        import threading
        monitor = PositionMonitor()
        
        # Add initial positions
        for i in range(5):
            position = Position(
                market_id=f"KXBTC15M-{i}",
                series_ticker="KXBTC15M",
                side=PositionSide.YES,
                size=10,
                avg_entry_price_cents=50,
            )
            monitor.add_position(position)
        
        def add_position(i):
            position = Position(
                market_id=f"KXBTC15M-{i+5}",
                series_ticker="KXBTC15M",
                side=PositionSide.YES,
                size=10,
                avg_entry_price_cents=50,
            )
            monitor.add_position(position)
        
        def remove_position(i):
            # Try to remove one of the initial positions
            positions = monitor.get_open_positions()
            if positions:
                first_id = list(positions.keys())[0]
                monitor.remove_position(first_id)
        
        threads = []
        for i in range(5):
            threads.append(threading.Thread(target=add_position, args=(i,)))
            threads.append(threading.Thread(target=remove_position, args=(i,)))
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Monitor should still be in consistent state
        open_positions = monitor.get_open_positions()
        assert isinstance(open_positions, dict)
        # All positions should have valid data
        for pos in open_positions.values():
            assert pos.market_id.startswith("KXBTC15M-")


class TestPositionMonitorPositionCacheIntegration:
    """Test integration between position_cache and PositionMonitor."""
    
    @pytest.mark.asyncio
    async def test_position_cache_adds_to_monitor_on_new_position(self):
        """Test that position_cache.on_fill() adds new positions to PositionMonitor.
        
        This test verifies the fix for the bug where new positions were not being
        added to the PositionMonitor, preventing TP/SL enforcement.
        """
        from merid.position_management.position_monitor import get_position_monitor
        from merid.event_venues.kalshi.position_cache import get_position_cache
        from unittest.mock import Mock, patch
        
        # Get monitor and cache
        monitor = get_position_monitor()
        cache = get_position_cache()
        
        # Mock fills_ledger to avoid database dependency
        mock_ledger = Mock()
        mock_ledger.get_fill.return_value = None
        
        with patch('merid.event_venues.kalshi.fills_ledger.get_fills_ledger', return_value=mock_ledger):
            # Simulate a fill creating a new position
            await cache.on_fill(
                market_id="KXBTC15M-TEST",
                contracts=5,
                price_cents=50,
                fee_cents=0,
                side="yes",
                client_order_id="test-order-123",
                fill_id="test-fill-456",
                action="buy",
            )
        
        # Position should be in monitor
        monitored_position = monitor.get_position_by_market("KXBTC15M-TEST")
        assert monitored_position is not None
        assert monitored_position.market_id == "KXBTC15M-TEST"
        assert monitored_position.size == 5
        assert monitored_position.avg_entry_price_cents == 50
        
        # Clean up
        monitor.remove_position("KXBTC15M-TEST")
        # Clean up cache
        if hasattr(cache, '_positions') and "KXBTC15M-TEST" in cache._positions:
            del cache._positions["KXBTC15M-TEST"]
    
    @pytest.mark.asyncio
    async def test_position_cache_removes_from_monitor_on_close(self):
        """Test that position_cache.on_fill() removes positions from PositionMonitor when closed.
        
        This test verifies the fix for the bug where closed positions were not being
        removed from the PositionMonitor, causing it to track stale positions.
        """
        from merid.position_management.position_monitor import get_position_monitor
        from merid.event_venues.kalshi.position_cache import get_position_cache
        from merid.position_management.position import Position, PositionSide
        from unittest.mock import Mock, patch
        
        # Get monitor and cache
        monitor = get_position_monitor()
        cache = get_position_cache()
        
        # Add a position to monitor directly
        position = Position(
            position_id="KXBTC15M-TEST",
            market_id="KXBTC15M-TEST",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=5,
            avg_entry_price_cents=50,
        )
        monitor.add_position(position)
        
        # Verify position is in monitor
        assert monitor.get_position_by_market("KXBTC15M-TEST") is not None
        
        # Mock fills_ledger to avoid database dependency
        mock_ledger = Mock()
        mock_ledger.get_fill.return_value = None
        
        with patch('merid.event_venues.kalshi.fills_ledger.get_fills_ledger', return_value=mock_ledger):
            # First, create a position in cache
            await cache.on_fill(
                market_id="KXBTC15M-TEST",
                contracts=5,
                price_cents=50,
                fee_cents=0,
                side="yes",
                client_order_id="test-order-123",
                fill_id="test-fill-456",
                action="buy",
            )
            
            # Now simulate a fill that closes the position (sell 5 contracts)
            await cache.on_fill(
                market_id="KXBTC15M-TEST",
                contracts=5,
                price_cents=55,
                fee_cents=0,
                side="yes",
                client_order_id="test-order-123",
                fill_id="test-fill-789",
                action="sell",
            )
        
        # Position should be removed from monitor
        monitored_position = monitor.get_position_by_market("KXBTC15M-TEST")
        assert monitored_position is None
        
        # Clean up cache if position still exists
        if hasattr(cache, '_positions') and "KXBTC15M-TEST" in cache._positions:
            del cache._positions["KXBTC15M-TEST"]
    
    @pytest.mark.asyncio
    async def test_position_cache_records_close_on_position_close(self):
        """Test that position_cache.on_fill() calls record_close() when position closes.
        
        This test verifies the fix for the bug where record_close() was not being called
        with the asset parameter, causing asset_notional to grow without bound.
        """
        from merid.position_management.position_monitor import get_position_monitor
        from merid.event_venues.kalshi.position_cache import get_position_cache
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        from merid.position_management.position import Position, PositionSide
        from unittest.mock import Mock, patch
        
        # Get monitor, cache, and risk manager
        monitor = get_position_monitor()
        cache = get_position_cache()
        risk_mgr = get_kalshi_risk()
        
        # Set initial asset_notional for BTC
        risk_mgr._state.asset_notional["BTC"] = 5.0
        
        # Mock fills_ledger to avoid database dependency
        mock_ledger = Mock()
        mock_ledger.get_fill.return_value = None
        
        with patch('merid.event_venues.kalshi.fills_ledger.get_fills_ledger', return_value=mock_ledger):
            # First, create a position in cache
            await cache.on_fill(
                market_id="KXBTC15M-TEST",
                contracts=5,
                price_cents=50,
                fee_cents=0,
                side="yes",
                client_order_id="test-order-123",
                fill_id="test-fill-456",
                action="buy",
            )
            
            # Now simulate a fill that closes the position (sell 5 contracts)
            await cache.on_fill(
                market_id="KXBTC15M-TEST",
                contracts=5,
                price_cents=55,
                fee_cents=0,
                side="yes",
                client_order_id="test-order-123",
                fill_id="test-fill-789",
                action="sell",
            )
        
        # asset_notional should be decremented (5.0 - (5 * 50 / 100) = 5.0 - 2.5 = 2.5)
        # Note: The actual decrement uses the pre-fill contracts (5) and the close price (55)
        # So it should be 5.0 - (5 * 55 / 100) = 5.0 - 2.75 = 2.25
        expected_notional = 5.0 - (5 * 55 / 100)
        assert risk_mgr._state.asset_notional.get("BTC", 0.0) == expected_notional
        
        # Clean up
        if hasattr(cache, '_positions') and "KXBTC15M-TEST" in cache._positions:
            del cache._positions["KXBTC15M-TEST"]
        risk_mgr._state.asset_notional["BTC"] = 0.0


class TestPositionMonitorTrailingStopConfiguration:
    """Test trailing stop configuration aligned with 15m best practices."""
    
    @pytest.mark.asyncio
    async def test_position_cache_configures_r_multiple_trailing(self):
        """Test that position_cache configures R-multiple trailing with 0.5R trail distance.
        
        This test verifies the fix for aligning trailing stops with 15m research:
        - Move to break-even at +0.5R
        - Trail with 0.5R distance
        """
        from merid.position_management.position_monitor import get_position_monitor
        from merid.event_venues.kalshi.position_cache import get_position_cache
        from merid.position_management.position import TrailingType
        from unittest.mock import Mock, patch
        
        # Get monitor and cache
        monitor = get_position_monitor()
        cache = get_position_cache()
        
        # Mock fills_ledger to avoid database dependency
        mock_ledger = Mock()
        mock_ledger.get_fill.return_value = None
        
        with patch('merid.event_venues.kalshi.fills_ledger.get_fills_ledger', return_value=mock_ledger):
            # Simulate a fill creating a new position
            await cache.on_fill(
                market_id="KXBTC15M-TEST",
                contracts=5,
                price_cents=50,
                fee_cents=0,
                side="yes",
                client_order_id="test-order-123",
                fill_id="test-fill-456",
                action="buy",
            )
        
        # Position should be in monitor with trailing configuration
        monitored_position = monitor.get_position_by_market("KXBTC15M-TEST")
        assert monitored_position is not None
        assert monitored_position.market_id == "KXBTC15M-TEST"
        
        # Verify trailing stop configuration
        assert monitored_position.trailing_type == TrailingType.R_MULTIPLE
        assert monitored_position.trailing_param == 0.5  # 0.5R trail distance per research
        
        # Clean up
        monitor.remove_position("KXBTC15M-TEST")
        if hasattr(cache, '_positions') and "KXBTC15M-TEST" in cache._positions:
            del cache._positions["KXBTC15M-TEST"]
    
    def test_trailing_stop_0_5r_distance(self):
        """Test that 0.5R trailing distance is correctly calculated."""
        from merid.position_management.position import Position, PositionSide, TrailingType
        
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,  # 10c risk
            trailing_type=TrailingType.R_MULTIPLE,
            trailing_param=0.5,  # 0.5R trail
        )
        
        # Initial risk is 10c (50 - 40)
        assert position.initial_risk_cents == 10
        
        # Move price up to 60 (max favorable)
        position.update_runtime_state(60)
        assert position.max_favorable_price_cents == 60
        
        # Trail level should be max_favorable - (0.5 * risk) = 60 - 5 = 55
        trail_level = position.get_trail_level()
        assert trail_level == 55
        
        # Price at 55 should trigger trail
        assert position.should_trigger_trail(55) is True
        
        # Price at 56 should not trigger trail
        assert position.should_trigger_trail(56) is False


class TestPositionBreakEvenTrigger(unittest.IsolatedAsyncioTestCase):
    """Test break-even trigger at 1R (research: capital preservation)."""
    
    def test_break_even_triggers_at_1r(self):
        """Break-even should trigger when position reaches 1R profit."""
        from merid.position_management.position import Position, PositionSide, TrailingType
        
        position = Position(
            position_id="test_position",
            market_id="TEST-MARKET",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,  # 10 cents risk
            trailing_type=TrailingType.R_MULTIPLE,
            trailing_param=0.5,
        )
        
        # Initial risk should be 10 cents
        assert position.initial_risk_cents == 10
        
        # At 60 cents (10 cents profit = 1R), break-even should trigger
        assert position.should_trigger_break_even(60) is True
        
        # At 55 cents (5 cents profit = 0.5R), break-even should not trigger
        assert position.should_trigger_break_even(55) is False
        
        # At 50 cents (breakeven), break-even should not trigger
        assert position.should_trigger_break_even(50) is False
    
    def test_break_even_moves_sl_to_entry(self):
        """Triggering break-even should move SL to entry price."""
        from merid.position_management.position import Position, PositionSide, TrailingType
        
        position = Position(
            position_id="test_position",
            market_id="TEST-MARKET",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,  # Original SL at 40
            trailing_type=TrailingType.R_MULTIPLE,
            trailing_param=0.5,
        )
        
        # Trigger break-even
        position.trigger_break_even()
        
        # SL should be moved to entry price (50)
        assert position.stop_loss_price_cents == 50
        assert position.break_even_triggered is True
        assert position.break_even_price_cents == 50
    
    def test_break_even_only_triggers_once(self):
        """Break-even should only trigger once per position."""
        from merid.position_management.position import Position, PositionSide, TrailingType
        
        position = Position(
            position_id="test_position",
            market_id="TEST-MARKET",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
            trailing_type=TrailingType.R_MULTIPLE,
            trailing_param=0.5,
        )
        
        # Trigger break-even
        position.trigger_break_even()
        
        # Should not trigger again
        assert position.should_trigger_break_even(70) is False


class TestPositionScaleOut(unittest.IsolatedAsyncioTestCase):
    """Test partial scale-out at 1.5-2R (research: Pay Yourself strategy)."""
    
    def test_scale_out_triggers_at_target(self):
        """Scale-out should trigger when position reaches scale-out price."""
        from merid.position_management.position import Position, PositionSide, TrailingType
        
        position = Position(
            position_id="test_position",
            market_id="TEST-MARKET",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
            scale_out_price_cents=65,  # Scale-out at 65 cents
            trailing_type=TrailingType.R_MULTIPLE,
            trailing_param=0.5,
        )
        
        # At 65 cents, scale-out should trigger
        assert position.should_trigger_scale_out(65) is True
        
        # At 64 cents, scale-out should not trigger
        assert position.should_trigger_scale_out(64) is False
    
    def test_scale_out_closes_half_position(self):
        """Scale-out should close 50% of position."""
        from merid.position_management.position import Position, PositionSide, TrailingType
        
        position = Position(
            position_id="test_position",
            market_id="TEST-MARKET",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
            scale_out_price_cents=65,
            trailing_type=TrailingType.R_MULTIPLE,
            trailing_param=0.5,
        )
        
        # Trigger scale-out
        contracts_to_close = position.trigger_scale_out()
        
        # Should close 5 contracts (50% of 10)
        assert contracts_to_close == 5
        assert position.scale_out_triggered is True
        assert position.scale_out_remaining_size == 5
    
    def test_scale_out_only_triggers_once(self):
        """Scale-out should only trigger once per position."""
        from merid.position_management.position import Position, PositionSide, TrailingType
        
        position = Position(
            position_id="test_position",
            market_id="TEST-MARKET",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
            scale_out_price_cents=65,
            trailing_type=TrailingType.R_MULTIPLE,
            trailing_param=0.5,
        )
        
        # Trigger scale-out
        position.trigger_scale_out()
        
        # Should not trigger again
        assert position.should_trigger_scale_out(70) is False


class TestDelayedTrailingActivation(unittest.IsolatedAsyncioTestCase):
    """Test trailing activation delayed until after 1R (research: prevent early whipsaws)."""
    
    def test_trailing_not_active_initially(self):
        """Trailing should not be active initially (before 1R)."""
        from merid.position_management.position import Position, PositionSide, TrailingType
        
        position = Position(
            position_id="test_position",
            market_id="TEST-MARKET",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
            trailing_type=TrailingType.R_MULTIPLE,
            trailing_param=0.5,
        )
        
        # Trailing should not be active initially
        assert position.trailing_activated is False
    
    def test_trailing_can_be_manually_activated(self):
        """Trailing can be manually activated (by PositionMonitor after break-even)."""
        from merid.position_management.position import Position, PositionSide, TrailingType
        
        position = Position(
            position_id="test_position",
            market_id="TEST-MARKET",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
            trailing_type=TrailingType.R_MULTIPLE,
            trailing_param=0.5,
        )
        
        # Trailing should not be active initially
        assert position.trailing_activated is False
        
        # Manually activate trailing (simulating PositionMonitor behavior)
        position.trailing_activated = True
        
        # Trailing should now be active
        assert position.trailing_activated is True


class TestTimeBasedTrailingTightening(unittest.IsolatedAsyncioTestCase):
    """Test time-based trailing tightening as expiry approaches (research: lock in gains)."""
    
    def test_trailing_tightens_near_expiry(self):
        """Trailing distance should reduce as expiry approaches."""
        from merid.position_management.position import Position, PositionSide, TrailingType
        from datetime import datetime, timedelta
        
        position = Position(
            position_id="test_position",
            market_id="TEST-MARKET",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
            trailing_type=TrailingType.R_MULTIPLE,
            trailing_param=0.5,
        )
        
        # Set opened_at to 10 minutes ago (last 5 minutes of 15m window)
        position.opened_at = datetime.utcnow() - timedelta(minutes=10)
        position.max_favorable_price_cents = 60
        
        # Update runtime state to trigger time-based calculation
        position.update_runtime_state(60)
        
        # Trail level should be tighter (50% reduction in last 5 minutes)
        # Normal: 60 - (0.5 * 10) = 55
        # Tightened: 60 - (0.25 * 10) = 57.5 -> 57
        trail_level = position.get_trail_level()
        assert trail_level > 55  # Should be tighter (higher for YES)
    
    def test_trailing_normal_early_in_window(self):
        """Trailing distance should be normal early in window."""
        from merid.position_management.position import Position, PositionSide, TrailingType
        
        position = Position(
            position_id="test_position",
            market_id="TEST-MARKET",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
            trailing_type=TrailingType.R_MULTIPLE,
            trailing_param=0.5,
        )
        
        # Set opened_at to 2 minutes ago (early in window)
        position.max_favorable_price_cents = 60
        position.update_runtime_state(60)
        
        # Trail level should be normal (no tightening)
        # Normal: 60 - (0.5 * 10) = 55
        trail_level = position.get_trail_level()
        assert trail_level == 55


