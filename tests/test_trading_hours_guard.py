"""Tests for KalshiTradingHoursGuard.

Verifies:
- Maintenance window detection (Thursday 3-5am ET)
- Live trading blocked during maintenance
- Paper trading allowed during maintenance
- Time calculations for maintenance windows
"""

import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from merid.guard.trading_hours import KalshiTradingHoursGuard, get_trading_hours_guard

ET = ZoneInfo("America/New_York")


class TestKalshiTradingHoursGuard:
    """Test suite for trading hours enforcement."""
    
    def test_outside_maintenance_window_live_allowed(self):
        """Live trading allowed outside Thursday 3-5am ET."""
        guard = KalshiTradingHoursGuard()
        
        # Tuesday at noon - should be allowed
        tuesday_noon = datetime(2026, 3, 24, 12, 0, tzinfo=ET)
        assert guard.is_live_trading_allowed(tuesday_noon) is True
        
        # Thursday at 2am - should be allowed (before maintenance)
        thursday_2am = datetime(2026, 3, 26, 2, 0, tzinfo=ET)
        assert guard.is_live_trading_allowed(thursday_2am) is True
        
        # Thursday at 6am - should be allowed (after maintenance)
        thursday_6am = datetime(2026, 3, 26, 6, 0, tzinfo=ET)
        assert guard.is_live_trading_allowed(thursday_6am) is True
    
    def test_inside_maintenance_window_live_blocked(self):
        """Live trading blocked during Thursday 3-5am ET maintenance."""
        guard = KalshiTradingHoursGuard()
        
        # Thursday at 3:30am - in maintenance window
        thursday_330am = datetime(2026, 3, 26, 3, 30, tzinfo=ET)
        assert guard.is_in_maintenance_window(thursday_330am) is True
        assert guard.is_live_trading_allowed(thursday_330am) is False
        
        # Thursday at 4:59am - still in maintenance window
        thursday_459am = datetime(2026, 3, 26, 4, 59, tzinfo=ET)
        assert guard.is_in_maintenance_window(thursday_459am) is True
        assert guard.is_live_trading_allowed(thursday_459am) is False
    
    def test_maintenance_window_boundary_exclusive_end(self):
        """Maintenance window ends at exactly 5:00 AM (exclusive)."""
        guard = KalshiTradingHoursGuard()
        
        # Thursday at exactly 5:00am - maintenance ended
        thursday_5am = datetime(2026, 3, 26, 5, 0, tzinfo=ET)
        assert guard.is_in_maintenance_window(thursday_5am) is False
        assert guard.is_live_trading_allowed(thursday_5am) is True
    
    def test_paper_trading_allowed_during_maintenance(self):
        """Paper trading proceeds during maintenance window."""
        guard = KalshiTradingHoursGuard()
        
        # Thursday at 4:00am - in maintenance
        thursday_4am = datetime(2026, 3, 26, 4, 0, tzinfo=ET)
        
        # Live should be blocked
        allowed, reason = guard.check_order_allowed(is_live=True, dt=thursday_4am)
        assert allowed is False
        assert reason == "maintenance_window_active"
        
        # Paper should be allowed
        allowed, reason = guard.check_order_allowed(is_live=False, dt=thursday_4am)
        assert allowed is True
        assert reason == "paper_trading_during_maintenance"
    
    def test_time_until_maintenance_end(self):
        """Calculate time remaining in maintenance window."""
        guard = KalshiTradingHoursGuard()
        
        # Thursday at 3:30am - 90 minutes until end
        thursday_330am = datetime(2026, 3, 26, 3, 30, tzinfo=ET)
        seconds_remaining = guard.get_time_until_maintenance_end(thursday_330am)
        assert seconds_remaining is not None
        assert 5400 <= seconds_remaining <= 5460  # ~90 minutes
        
        # Outside maintenance window - should return None
        tuesday_noon = datetime(2026, 3, 24, 12, 0, tzinfo=ET)
        assert guard.get_time_until_maintenance_end(tuesday_noon) is None
    
    def test_next_maintenance_window(self):
        """Calculate next scheduled maintenance window."""
        guard = KalshiTradingHoursGuard()
        
        # Start from Tuesday - next maintenance is Thursday
        tuesday = datetime(2026, 3, 24, 12, 0, tzinfo=ET)
        start, end = guard.get_next_maintenance_window(tuesday)
        
        assert start.weekday() == 3  # Thursday
        assert start.hour == 3 and start.minute == 0
        assert end.hour == 5 and end.minute == 0
        
        # If we're Thursday after maintenance, next is next week
        thursday_afternoon = datetime(2026, 3, 26, 14, 0, tzinfo=ET)
        start, end = guard.get_next_maintenance_window(thursday_afternoon)
        
        # If we're Thursday after maintenance, next is next week (6 days later, not 7)
        # Because (Thursday afternoon -> next Thursday morning) = 6 days + some hours
        assert start.weekday() == 3
        days_diff = (start.date() - thursday_afternoon.date()).days
        assert days_diff in [6, 7]  # Allow 6 or 7 depending on exact time calculation
    
    def test_singleton_behavior(self):
        """Trading hours guard is a singleton."""
        guard1 = get_trading_hours_guard()
        guard2 = get_trading_hours_guard()
        assert guard1 is guard2
    
    def test_idempotence_multiple_calls(self):
        """Guard methods are idempotent - multiple calls give same result."""
        guard = KalshiTradingHoursGuard()
        
        # Same input should give same output
        thursday_4am = datetime(2026, 3, 26, 4, 0, tzinfo=ET)
        
        result1 = guard.is_live_trading_allowed(thursday_4am)
        result2 = guard.is_live_trading_allowed(thursday_4am)
        result3 = guard.is_in_maintenance_window(thursday_4am)
        result4 = guard.is_in_maintenance_window(thursday_4am)
        
        assert result1 == result2 == False  # Should be False (blocked during maintenance)
        assert result3 == result4 == True  # Should be True (in maintenance)
    
    def test_with_mock_time_provider(self, monkeypatch):
        """Test with mocked time provider to ensure no dependency on system clock."""
        guard = KalshiTradingHoursGuard()
        
        # Mock the time provider to return a fixed "Thursday 4am ET" time
        fixed_thursday_4am = datetime(2026, 3, 26, 4, 0, tzinfo=ET)
        
        def mock_get_current_et_time():
            return fixed_thursday_4am
        
        monkeypatch.setattr(guard, 'get_current_et_time', mock_get_current_et_time)
        
        # Now is_live_trading_allowed() with no argument should use mocked time
        assert guard.is_live_trading_allowed() is False
        assert guard.is_in_maintenance_window() is True
        
        # Change mock to outside maintenance window
        fixed_tuesday_noon = datetime(2026, 3, 24, 12, 0, tzinfo=ET)
        
        def mock_get_current_et_time_2():
            return fixed_tuesday_noon
        
        monkeypatch.setattr(guard, 'get_current_et_time', mock_get_current_et_time_2)
        
        assert guard.is_live_trading_allowed() is True
        assert guard.is_in_maintenance_window() is False


class TestTradingHoursIntegration:
    """Integration tests for trading hours in execution flow."""
    
    @pytest.mark.asyncio
    async def test_live_order_blocked_during_maintenance(self):
        """Verify live order is blocked with correct reason during maintenance."""
        from merid.guard.trading_hours import get_trading_hours_guard
        
        guard = get_trading_hours_guard()
        
        # Simulate Thursday 4am ET
        thursday_4am = datetime(2026, 3, 26, 4, 0, tzinfo=ET)
        
        allowed, reason = guard.check_order_allowed(is_live=True, dt=thursday_4am)
        
        assert allowed is False
        assert reason == "maintenance_window_active"
    
    @pytest.mark.asyncio
    async def test_paper_order_allowed_during_maintenance(self):
        """Verify paper order proceeds during maintenance."""
        from merid.guard.trading_hours import get_trading_hours_guard
        
        guard = get_trading_hours_guard()
        
        # Simulate Thursday 4am ET
        thursday_4am = datetime(2026, 3, 26, 4, 0, tzinfo=ET)
        
        allowed, reason = guard.check_order_allowed(is_live=False, dt=thursday_4am)
        
        assert allowed is True
        assert reason == "paper_trading_during_maintenance"
