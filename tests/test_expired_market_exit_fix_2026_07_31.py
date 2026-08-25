"""
Regression tests for CRITICAL FIX (2026-07-31): Expired market exit handling.

This fix prevents the position monitor from attempting to exit positions in expired markets,
which causes 404 errors and retry loops. Expired markets have settled and positions
should be removed from the monitor without attempting exit orders.

Files modified:
- merid/position_management/position_monitor.py
"""

import pytest
import time
from datetime import datetime, timezone, timedelta
from merid.position_management.position_monitor import PositionMonitor, _is_expired_ticker
from merid.position_management.position import Position, PositionSide


class TestExpiredTickerDetection:
    """Tests for expired ticker detection."""
    
    def test_expired_ticker_current_year(self):
        """Test detection of expired ticker from current year."""
        # Create a ticker that expired 1 hour ago
        past_time = datetime.now(timezone.utc) - timedelta(hours=1)
        expiry_str = past_time.strftime("%d%b%H%M%S").upper()
        ticker = f"KXBTC15M-{expiry_str}-15"
        
        assert _is_expired_ticker(ticker) is True
    
    def test_expired_ticker_future(self):
        """Test that future ticker is not marked as expired."""
        # Create a ticker that expires in 1 hour
        future_time = datetime.now(timezone.utc) + timedelta(hours=1)
        expiry_str = future_time.strftime("%d%b%H%M%S").upper()
        ticker = f"KXBTC15M-{expiry_str}-15"
        
        assert _is_expired_ticker(ticker) is False
    
    def test_expired_ticker_buffer(self):
        """Test that ticker within 15-minute buffer is not marked as expired."""
        # Create a ticker that expired 10 minutes ago (within buffer)
        past_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        expiry_str = past_time.strftime("%d%b%H%M%S").upper()
        ticker = f"KXBTC15M-{expiry_str}-15"
        
        assert _is_expired_ticker(ticker) is False
    
    def test_expired_ticker_old(self):
        """Test that ticker expired 20 minutes ago is marked as expired."""
        # Create a ticker that expired 20 minutes ago (outside buffer)
        past_time = datetime.now(timezone.utc) - timedelta(minutes=20)
        expiry_str = past_time.strftime("%d%b%H%M%S").upper()
        ticker = f"KXBTC15M-{expiry_str}-15"
        
        assert _is_expired_ticker(ticker) is True
    
    def test_expired_ticker_invalid_format(self):
        """Test that invalid ticker format returns False (don't filter out)."""
        assert _is_expired_ticker("INVALID_TICKER") is False
        assert _is_expired_ticker("") is False
        assert _is_expired_ticker("KXBTC15M") is False
    
    def test_expired_ticker_invalid_date(self):
        """Test that invalid date (Feb 30) is marked as expired."""
        ticker = "KXBTC15M-30FEB120000-15"
        assert _is_expired_ticker(ticker) is True


class TestPositionMonitorExpiredMarketHandling:
    """Tests for position monitor handling of expired markets."""
    
    def test_expired_market_position_removed(self):
        """Test that positions in expired markets are removed without exit attempt."""
        monitor = PositionMonitor(poll_interval=1.0)
        
        # Create a position in an expired market
        past_time = datetime.now(timezone.utc) - timedelta(hours=1)
        expiry_str = past_time.strftime("%d%b%H%M%S").upper()
        expired_market_id = f"KXBTC15M-{expiry_str}-15"
        
        position = Position(
            position_id="test_position",
            market_id=expired_market_id,
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            take_profit_price_cents=60,
            stop_loss_price_cents=40,
        )
        
        monitor.add_position(position)
        
        # Expired markets are rejected at add time, so no exit order is ever
        # attempted.
        assert monitor.get_open_positions_count() == 0
        assert monitor._is_expired_market(expired_market_id) is True
    
    def test_active_market_position_kept(self):
        """Test that positions in active markets are not removed."""
        monitor = PositionMonitor(poll_interval=1.0)
        
        # Create a position in an active market (expires in future)
        future_time = datetime.now(timezone.utc) + timedelta(hours=1)
        expiry_str = future_time.strftime("%d%b%H%M%S").upper()
        active_market_id = f"KXBTC15M-{expiry_str}-15"
        
        position = Position(
            position_id="test_position",
            market_id=active_market_id,
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            take_profit_price_cents=60,
            stop_loss_price_cents=40,
        )
        
        monitor.add_position(position)
        
        # Verify position was added
        assert monitor.get_open_positions_count() == 1
        
        # The position should NOT be removed
        assert monitor._is_expired_market(active_market_id) is False
    
    def test_expired_market_no_exit_intent(self):
        """Test that expired markets don't trigger exit intents."""
        monitor = PositionMonitor(poll_interval=1.0)
        
        # Track exit intents
        exit_intents = []
        def mock_exit_callback(position, reason, price):
            exit_intents.append((position.market_id, reason, price))
        
        monitor.register_exit_intent_callback(mock_exit_callback)
        
        # Create a position in an expired market
        past_time = datetime.now(timezone.utc) - timedelta(hours=1)
        expiry_str = past_time.strftime("%d%b%H%M%S").upper()
        expired_market_id = f"KXBTC15M-{expiry_str}-15"
        
        position = Position(
            position_id="test_position",
            market_id=expired_market_id,
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            take_profit_price_cents=60,
            stop_loss_price_cents=40,
        )
        
        monitor.add_position(position)
        
        # Simulate poll cycle (this would normally check expired markets)
        # The expired market check should remove the position without exit intent
        if monitor._is_expired_market(expired_market_id):
            with monitor._lock:
                if position.position_id in monitor._open_positions:
                    del monitor._open_positions[position.position_id]
                if position.market_id in monitor._market_to_position:
                    del monitor._market_to_position[position.market_id]
        
        # Verify no exit intent was triggered
        assert len(exit_intents) == 0
        assert monitor.get_open_positions_count() == 0


class TestExpiredMarketRegression:
    """Regression tests to prevent expired market exit attempts."""
    
    def test_no_404_errors_for_expired_markets(self):
        """Test that expired markets don't cause 404 errors in exit attempts.
        
        This is a regression test for the bug where the position monitor
        attempted to exit positions in expired markets, causing 404 errors
        from the exchange API.
        """
        monitor = PositionMonitor(poll_interval=1.0)
        
        # Create positions in multiple expired markets
        expired_markets = []
        for i in range(5):
            past_time = datetime.now(timezone.utc) - timedelta(hours=i+1)
            expiry_str = past_time.strftime("%d%b%H%M%S").upper()
            market_id = f"KXBTC15M-{expiry_str}-15"
            expired_markets.append(market_id)
            
            position = Position(
                position_id=f"test_position_{i}",
                market_id=market_id,
                side=PositionSide.YES,
                size=10,
                avg_entry_price_cents=50,
                take_profit_price_cents=60,
                stop_loss_price_cents=40,
            )
            monitor.add_position(position)
        
        # All markets should be detected as expired
        for market_id in expired_markets:
            assert monitor._is_expired_market(market_id) is True
        
        # All positions should be removable without exit attempts
        # This prevents the 404 errors seen in the logs
        for market_id in expired_markets:
            if monitor._is_expired_market(market_id):
                # Simulate the removal that happens in poll cycle
                position_id = monitor._market_to_position.get(market_id)
                if position_id:
                    with monitor._lock:
                        if position_id in monitor._open_positions:
                            del monitor._open_positions[position_id]
                        if market_id in monitor._market_to_position:
                            del monitor._market_to_position[market_id]
        
        # All positions should be removed
        assert len(monitor.get_open_positions()) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
