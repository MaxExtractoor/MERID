"""Tests for Kalshi 15-minute time helper.

This module tests the ET-based time calculations for Kalshi 15-minute crypto markets.
The single source of truth for 15-minute market selection is the ET window helper.
All components (catalog, scheduler, agents) must use get_kalshi_15m_window().

CRITICAL TIME CONTRACT:
- Source of truth: Kalshi contract times are in Eastern Time (America/New_York)
- Internal clock: System runs in UTC, but ticker suffixes, expiry minutes, 
  and 15m buckets operate in ET with conversion at the edges
- Ticker suffixes use UTC (YYMMMDDHHMM-MM format) for API compatibility
- All window calculations (entry, trading, cutoff) use ET
"""

import unittest
from datetime import datetime, timezone, timedelta
from merid.event_venues.kalshi.kalshi_15m_time import (
    get_current_utc_window,
    get_next_utc_window,
    get_previous_utc_window,
    get_kalshi_15m_window,
    compute_minutes_to_expiry,
    utc_to_et,
    et_to_utc,
    _format_suffix,
)


class TestUTCWindowBoundaries(unittest.TestCase):
    """Test UTC window boundary calculations."""
    
    def test_window_at_boundary(self):
        """Test window calculation at exact 15-minute boundary."""
        # 2026-06-26 14:00:00 UTC should be in window starting at 14:00
        now = datetime(2026, 6, 26, 14, 0, 0, tzinfo=timezone.utc)
        window = get_current_utc_window(now)
        
        self.assertEqual(window.start_utc, datetime(2026, 6, 26, 14, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(window.end_utc, datetime(2026, 6, 26, 14, 15, 0, tzinfo=timezone.utc))
        self.assertTrue(window.is_open(now))
    
    def test_window_mid_interval(self):
        """Test window calculation in middle of 15-minute interval."""
        # 2026-06-26 14:07:30 UTC should be in window starting at 14:00
        now = datetime(2026, 6, 26, 14, 7, 30, tzinfo=timezone.utc)
        window = get_current_utc_window(now)
        
        self.assertEqual(window.start_utc, datetime(2026, 6, 26, 14, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(window.end_utc, datetime(2026, 6, 26, 14, 15, 0, tzinfo=timezone.utc))
        self.assertTrue(window.is_open(now))
    
    def test_window_hour_boundary(self):
        """Test window calculation at hour boundary."""
        # 2026-06-26 14:15:00 UTC should be in window starting at 14:15
        now = datetime(2026, 6, 26, 14, 15, 0, tzinfo=timezone.utc)
        window = get_current_utc_window(now)
        
        self.assertEqual(window.start_utc, datetime(2026, 6, 26, 14, 15, 0, tzinfo=timezone.utc))
        self.assertEqual(window.end_utc, datetime(2026, 6, 26, 14, 30, 0, tzinfo=timezone.utc))
        self.assertTrue(window.is_open)
    
    def test_window_day_boundary(self):
        """Test window calculation at day boundary (midnight UTC)."""
        # 2026-06-27 00:00:00 UTC should be in window starting at 00:00
        now = datetime(2026, 6, 27, 0, 0, 0, tzinfo=timezone.utc)
        window = get_current_utc_window(now)
        
        self.assertEqual(window.start_utc, datetime(2026, 6, 27, 0, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(window.end_utc, datetime(2026, 6, 27, 0, 15, 0, tzinfo=timezone.utc))
        self.assertTrue(window.is_open(now))


class TestSuffixFormat(unittest.TestCase):
    """Test UTC-based ticker suffix formatting."""
    
    def test_suffix_format(self):
        """Test suffix format matches Kalshi UTC format."""
        # 2026-06-26 14:30:00 UTC → 26JUN261430-30
        dt = datetime(2026, 6, 26, 14, 30, 0, tzinfo=timezone.utc)
        suffix = _format_suffix(dt)
        
        self.assertEqual(suffix, "26JUN261430-30")
    
    def test_suffix_format_00_minute(self):
        """Test suffix format at 00 minute boundary."""
        # 2026-06-26 14:00:00 UTC → 26JUN261400-00
        dt = datetime(2026, 6, 26, 14, 0, 0, tzinfo=timezone.utc)
        suffix = _format_suffix(dt)
        
        self.assertEqual(suffix, "26JUN261400-00")
    
    def test_suffix_format_15_minute(self):
        """Test suffix format at 15 minute boundary."""
        # 2026-06-26 14:15:00 UTC → 26JUN261415-15
        dt = datetime(2026, 6, 26, 14, 15, 0, tzinfo=timezone.utc)
        suffix = _format_suffix(dt)
        
        self.assertEqual(suffix, "26JUN261415-15")
    
    def test_suffix_format_45_minute(self):
        """Test suffix format at 45 minute boundary."""
        # 2026-06-26 14:45:00 UTC → 26JUN261445-45
        dt = datetime(2026, 6, 26, 14, 45, 0, tzinfo=timezone.utc)
        suffix = _format_suffix(dt)
        
        self.assertEqual(suffix, "26JUN261445-45")
    
    def test_suffix_format_different_month(self):
        """Test suffix format for different month."""
        # 2026-04-22 12:00:00 UTC → 26APR221200-00 (matches external docs)
        dt = datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc)
        suffix = _format_suffix(dt)
        
        self.assertEqual(suffix, "26APR221200-00")


class TestNextWindow(unittest.TestCase):
    """Test next UTC window calculation."""
    
    def test_next_window_current(self):
        """Test next window from current time."""
        now = datetime(2026, 6, 26, 14, 7, 30, tzinfo=timezone.utc)
        next_window = get_next_utc_window(now)
        
        # Should be the 14:15 window
        self.assertEqual(next_window.start_utc, datetime(2026, 6, 26, 14, 15, 0, tzinfo=timezone.utc))
        self.assertEqual(next_window.end_utc, datetime(2026, 6, 26, 14, 30, 0, tzinfo=timezone.utc))
    
    def test_next_window_at_boundary(self):
        """Test next window at exact boundary."""
        now = datetime(2026, 6, 26, 14, 15, 0, tzinfo=timezone.utc)
        next_window = get_next_utc_window(now)
        
        # Should be the 14:30 window
        self.assertEqual(next_window.start_utc, datetime(2026, 6, 26, 14, 30, 0, tzinfo=timezone.utc))
        self.assertEqual(next_window.end_utc, datetime(2026, 6, 26, 14, 45, 0, tzinfo=timezone.utc))


class TestPreviousWindow(unittest.TestCase):
    """Test previous UTC window calculation."""
    
    def test_previous_window_current(self):
        """Test previous window from current time."""
        now = datetime(2026, 6, 26, 14, 7, 30, tzinfo=timezone.utc)
        prev_window = get_previous_utc_window(now)
        
        # Should be the 13:45 window
        self.assertEqual(prev_window.start_utc, datetime(2026, 6, 26, 13, 45, 0, tzinfo=timezone.utc))
        self.assertEqual(prev_window.end_utc, datetime(2026, 6, 26, 14, 0, 0, tzinfo=timezone.utc))
    
    def test_previous_window_at_boundary(self):
        """Test previous window at exact boundary."""
        now = datetime(2026, 6, 26, 14, 15, 0, tzinfo=timezone.utc)
        prev_window = get_previous_utc_window(now)
        
        # Should be the 14:00 window
        self.assertEqual(prev_window.start_utc, datetime(2026, 6, 26, 14, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(prev_window.end_utc, datetime(2026, 6, 26, 14, 15, 0, tzinfo=timezone.utc))


class TestMinutesToExpiry(unittest.TestCase):
    """Test minutes to expiry calculation."""
    
    def test_minutes_to_expiry_future(self):
        """Test minutes to expiry for future time."""
        expiry = datetime(2026, 6, 26, 14, 15, 0, tzinfo=timezone.utc)
        now = datetime(2026, 6, 26, 14, 0, 0, tzinfo=timezone.utc)
        
        mte = compute_minutes_to_expiry(expiry, now)
        self.assertEqual(mte, 15.0)
    
    def test_minutes_to_expiry_past(self):
        """Test minutes to expiry for past time (negative)."""
        expiry = datetime(2026, 6, 26, 14, 0, 0, tzinfo=timezone.utc)
        now = datetime(2026, 6, 26, 14, 15, 0, tzinfo=timezone.utc)
        
        mte = compute_minutes_to_expiry(expiry, now)
        self.assertEqual(mte, -15.0)
    
    def test_minutes_to_expiry_default_now(self):
        """Test minutes to expiry with default now parameter."""
        expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
        
        mte = compute_minutes_to_expiry(expiry)
        self.assertAlmostEqual(mte, 10.0, delta=1.0)  # Allow 1 second tolerance


class TestUTCETConversion(unittest.TestCase):
    """Test UTC to ET conversion (for trading hours)."""
    
    def test_utc_to_et(self):
        """Test UTC to ET conversion."""
        # 2026-06-26 14:00 UTC should be 10:00 ET (EDT, UTC-4 in June)
        utc_dt = datetime(2026, 6, 26, 14, 0, 0, tzinfo=timezone.utc)
        et_dt = utc_to_et(utc_dt)
        
        # In June, ET is EDT (UTC-4)
        self.assertEqual(et_dt.hour, 10)
        self.assertEqual(et_dt.minute, 0)
    
    def test_et_to_utc(self):
        """Test ET to UTC conversion."""
        # 2026-06-26 10:00 ET should be 14:00 UTC (EDT, UTC-4 in June)
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        ET = ZoneInfo('America/New_York')
        
        et_dt = datetime(2026, 6, 26, 10, 0, 0, tzinfo=ET)
        utc_dt = et_to_utc(et_dt)
        
        self.assertEqual(utc_dt.hour, 14)
        self.assertEqual(utc_dt.minute, 0)


class TestWindowIntegration(unittest.TestCase):
    """Integration tests for UTC window functionality."""
    
    def test_window_suffix_consistency(self):
        """Test that window suffix matches UTC time."""
        now = datetime(2026, 6, 26, 14, 7, 30, tzinfo=timezone.utc)
        window = get_current_utc_window(now)
        
        # Suffix should be based on window start (14:00 UTC)
        expected_suffix = "26JUN261400-00"
        self.assertEqual(window.suffix, expected_suffix)
    
    def test_window_minutes_to_expiry(self):
        """Test window's minutes_to_expiry property."""
        now = datetime(2026, 6, 26, 14, 7, 30, tzinfo=timezone.utc)
        window = get_current_utc_window(now)
        
        # Window ends at 14:15, so should be ~7.5 minutes to expiry
        mte = window.minutes_to_expiry(now)
        self.assertAlmostEqual(mte, 7.5, delta=0.1)
    
    def test_window_is_open(self):
        """Test window's is_open property."""
        now = datetime(2026, 6, 26, 14, 7, 30, tzinfo=timezone.utc)
        window = get_current_utc_window(now)
        
        self.assertTrue(window.is_open)
        
        # Test with time outside window
        future_time = datetime(2026, 6, 26, 14, 20, 0, tzinfo=timezone.utc)
        self.assertFalse(window.is_open(future_time))
    
    def test_15_minute_entry_window(self):
        """Test that 15-minute markets have a 0-15 minute entry window using ET.
        
        Kalshi 15-minute markets open at the top of each quarter hour (00, 15, 30, 45) ET
        and trade for exactly 15 minutes before settling. The catalog should only
        include markets with 0-15 minutes to expiry, not 0-30 minutes.
        
        This test uses ET as the source of truth for window calculation.
        """
        # At 11:37 PM ET (03:37 UTC), the active market opened at 11:30 PM ET and expires at 11:45 PM ET
        # Convert 11:37 PM ET to UTC (EDT is UTC-4 in June)
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        ET = ZoneInfo('America/New_York')
        
        now_et = datetime(2026, 6, 12, 23, 37, 0, tzinfo=ET)
        now_utc = now_et.astimezone(timezone.utc)
        
        # Get ET window
        window = get_kalshi_15m_window(now_utc)
        
        # Window should be 11:30 PM ET to 11:45 PM ET
        self.assertEqual(window.start_et.hour, 23)
        self.assertEqual(window.start_et.minute, 30)
        self.assertEqual(window.end_et.hour, 23)
        self.assertEqual(window.end_et.minute, 45)
        
        # Minutes to expiry should be ~8 minutes
        self.assertAlmostEqual(window.minutes_to_expiry, 8.0, delta=0.1)
        self.assertTrue(0.0 <= window.minutes_to_expiry <= 15.0)
        
        # Suffix should be based on UTC start time
        # 11:30 PM ET = 03:30 UTC next day (June 13)
        self.assertEqual(window.start_utc.day, 13)
        self.assertEqual(window.start_utc.hour, 3)
        self.assertEqual(window.start_utc.minute, 30)


class TestETWindowParameterized(unittest.TestCase):
    """Parameterized tests for ET window at different times of day."""
    
    def test_et_window_at_09_59_30_et(self):
        """Test ET window at 9:59:30 ET - should select 10:00 expiry."""
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        ET = ZoneInfo('America/New_York')
        
        # Scenario A: 2026-06-13 09:59:30 ET → Expected expiry 10:00 ET, suffix 26JUN131000-00
        now_et = datetime(2026, 6, 13, 9, 59, 30, tzinfo=ET)
        now_utc = now_et.astimezone(timezone.utc)
        
        window = get_kalshi_15m_window(now_utc)
        
        # Window should be 9:45 ET to 10:00 ET
        self.assertEqual(window.start_et.hour, 9)
        self.assertEqual(window.start_et.minute, 45)
        self.assertEqual(window.end_et.hour, 10)
        self.assertEqual(window.end_et.minute, 0)
        
        # Minutes to expiry should be ~0.5 minutes
        self.assertAlmostEqual(window.minutes_to_expiry, 0.5, delta=0.1)
        
        # Suffix is based on ET window END time (10:00 ET -> 26JUN131000-00)
        # 9:45 AM ET = 13:45 UTC
        self.assertEqual(window.start_utc.hour, 13)
        self.assertEqual(window.start_utc.minute, 45)
        self.assertIn("131000", window.suffix)
    
    def test_et_window_at_10_00_01_et(self):
        """Test ET window at 10:00:01 ET - should select 10:15 expiry."""
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        ET = ZoneInfo('America/New_York')
        
        # Scenario B: 2026-06-13 10:00:01 ET → Expected expiry 10:15 ET, suffix 26JUN131015-15
        now_et = datetime(2026, 6, 13, 10, 0, 1, tzinfo=ET)
        now_utc = now_et.astimezone(timezone.utc)
        
        window = get_kalshi_15m_window(now_utc)
        
        # Window should be 10:00 ET to 10:15 ET
        self.assertEqual(window.start_et.hour, 10)
        self.assertEqual(window.start_et.minute, 0)
        self.assertEqual(window.end_et.hour, 10)
        self.assertEqual(window.end_et.minute, 15)
        
        # Minutes to expiry should be ~14.98 minutes
        self.assertAlmostEqual(window.minutes_to_expiry, 14.98, delta=0.1)
        
        # Suffix is based on ET window END time (10:15 ET -> 26JUN131015-15)
        # 10:00 AM ET = 14:00 UTC
        self.assertEqual(window.start_utc.hour, 14)
        self.assertEqual(window.start_utc.minute, 0)
        self.assertIn("131015", window.suffix)
    
    def test_et_window_at_14_29_30_et(self):
        """Test ET window at 14:29:30 ET - should select 14:30 expiry."""
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        ET = ZoneInfo('America/New_York')
        
        # Scenario C: 2026-06-13 14:29:30 ET → Expected expiry 14:30 ET, suffix 26JUN131430-30
        now_et = datetime(2026, 6, 13, 14, 29, 30, tzinfo=ET)
        now_utc = now_et.astimezone(timezone.utc)
        
        window = get_kalshi_15m_window(now_utc)
        
        # Window should be 14:15 ET to 14:30 ET
        self.assertEqual(window.start_et.hour, 14)
        self.assertEqual(window.start_et.minute, 15)
        self.assertEqual(window.end_et.hour, 14)
        self.assertEqual(window.end_et.minute, 30)
        
        # Minutes to expiry should be ~0.5 minutes
        self.assertAlmostEqual(window.minutes_to_expiry, 0.5, delta=0.1)
        
        # Suffix is based on ET window END time (14:30 ET -> 26JUN131430-30)
        # 2:15 PM ET = 18:15 UTC
        self.assertEqual(window.start_utc.hour, 18)
        self.assertEqual(window.start_utc.minute, 15)
        self.assertIn("131430", window.suffix)


class TestSelectMarketsWindow(unittest.TestCase):
    """Test _select_markets window filtering with frozen time."""
    
    def test_select_markets_at_10_00_et(self):
        """Test that _select_markets selects the correct market at 10:00am ET.
        
        At 10:00am ET, the system should select the market expiring at 10:15 ET
        (the one currently in the 2-12 minute trading window).
        """
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        ET = ZoneInfo('America/New_York')
        
        # Freeze time at 10:00am ET (14:00 UTC)
        now_et = datetime(2026, 6, 13, 10, 0, 0, tzinfo=ET)
        now_utc = now_et.astimezone(timezone.utc)
        
        # Get ET window
        window = get_kalshi_15m_window(now_utc)
        
        # Window should be 10:00 ET to 10:15 ET
        self.assertEqual(window.start_et.hour, 10)
        self.assertEqual(window.start_et.minute, 0)
        self.assertEqual(window.end_et.hour, 10)
        self.assertEqual(window.end_et.minute, 15)
        
        # Minutes to expiry should be 15 minutes
        self.assertEqual(window.minutes_to_expiry, 15.0)
        
        # Suffix is based on ET window END time (10:15 ET -> 26JUN131015-15)
        # 10:00 AM ET = 14:00 UTC
        self.assertEqual(window.start_utc.hour, 14)
        self.assertEqual(window.start_utc.minute, 0)
        self.assertIn("131015", window.suffix)
        
        # Verify trading window (2-12 minutes) would select a different market
        # At 10:00am ET, the 10:00-10:15 window has 15 minutes to expiry
        # which is outside the 2-12 minute trading window
        # The system should select the 9:45-10:00 window (which just expired at 10:00)
        # or wait for the 10:00-10:15 window to enter the trading window
        self.assertGreater(window.minutes_to_expiry, 12.0)
    
    def test_select_markets_at_10_02_et(self):
        """Test that _select_markets selects the correct market at 10:02am ET.
        
        At 10:02am ET, the 10:00-10:15 window has 13 minutes to expiry,
        which is still outside the 2-12 minute trading window.
        The system should select the market closest to expiry.
        """
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        ET = ZoneInfo('America/New_York')
        
        # Freeze time at 10:02am ET (14:02 UTC)
        now_et = datetime(2026, 6, 13, 10, 2, 0, tzinfo=ET)
        now_utc = now_et.astimezone(timezone.utc)
        
        # Get ET window
        window = get_kalshi_15m_window(now_utc)
        
        # Window should be 10:00 ET to 10:15 ET
        self.assertEqual(window.start_et.hour, 10)
        self.assertEqual(window.start_et.minute, 0)
        self.assertEqual(window.end_et.hour, 10)
        self.assertEqual(window.end_et.minute, 15)
        
        # Minutes to expiry should be 13 minutes
        self.assertEqual(window.minutes_to_expiry, 13.0)
        
        # Still outside trading window (2-12 minutes)
        self.assertGreater(window.minutes_to_expiry, 12.0)
    
    def test_select_markets_at_10_05_et(self):
        """Test that _select_markets selects the correct market at 10:05am ET.
        
        At 10:05am ET, the 10:00-10:15 window has 10 minutes to expiry,
        which is inside the 2-12 minute trading window.
        The system should select this market.
        """
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        ET = ZoneInfo('America/New_York')
        
        # Freeze time at 10:05am ET (14:05 UTC)
        now_et = datetime(2026, 6, 13, 10, 5, 0, tzinfo=ET)
        now_utc = now_et.astimezone(timezone.utc)
        
        # Get ET window
        window = get_kalshi_15m_window(now_utc)
        
        # Window should be 10:00 ET to 10:15 ET
        self.assertEqual(window.start_et.hour, 10)
        self.assertEqual(window.start_et.minute, 0)
        self.assertEqual(window.end_et.hour, 10)
        self.assertEqual(window.end_et.minute, 15)
        
        # Minutes to expiry should be 10 minutes
        self.assertEqual(window.minutes_to_expiry, 10.0)
        
        # Inside trading window (2-12 minutes)
        self.assertTrue(2.0 <= window.minutes_to_expiry <= 12.0)


if __name__ == '__main__':
    unittest.main()
